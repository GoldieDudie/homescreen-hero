from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

from plexapi.server import PlexServer

from .config.schema import AppConfig, CollectionRef
from .db import (
    HUB_TYPE_COLLECTION,
    HUB_TYPE_EXTERNAL,
    HUB_TYPE_SMART_HUB,
    PIN_BOTTOM,
    PIN_TOP,
    defragment_library_hub_order,
    delete_hub,
    get_library_hub_order,
    get_pinned_collections,
    set_library_hub_order,
    set_pin,
    slot_in_hub,
    upsert_hub,
)
from .integrations.plex_client import (
    _RECENTLY_ADDED_ANCHOR_BY_LIB_TYPE,
    _get_managed_hubs_for_library,
    move_hub_after_verified,
    repromote_hub,
)

logger = logging.getLogger(__name__)

# Identifiers of the native "Recently Added" hub per library type. When the
# top-most enforcement unit is a custom collection, we anchor it AFTER this hub
# so a system hub stays at managedHubs[0] — Plex renders a custom collection at
# [0] ABOVE Continue Watching / On Deck (sinking it), but a system hub at [0]
# keeps CW on top. Mirrors pin_hub_to_top's landing-at-[1] logic.
_NATIVE_TOP_ANCHOR_IDENTIFIERS = frozenset(_RECENTLY_ADDED_ANCHOR_BY_LIB_TYPE.values())


@dataclass
class SyncResult:
    library_name: str
    added: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    updated: List[str] = field(default_factory=list)
    plex_reorder_errors: List[str] = field(default_factory=list)


def _build_collection_to_group_map(
    config: AppConfig,
    smart_group_collections: Optional[Dict[str, List[CollectionRef]]] = None,
    today: Optional[date] = None,
) -> Dict[Tuple[str, str], str]:
    # (library_name, collection_name) -> group_name
    # Only ACTIVE groups may claim a collection. A disabled or out-of-season group
    # must not label hubs that an active group actually produced — otherwise two
    # active groups that share a collection with an inactive superset group get
    # clustered under the inactive group's name (e.g. Chill/Intense Genres rendered
    # as the deactivated Home Screen group).
    from .rotation import _group_is_active

    result: Dict[Tuple[str, str], str] = {}
    smart_group_collections = smart_group_collections or {}
    today = today or date.today()
    for group in config.groups:
        if not _group_is_active(group, today):
            continue
        if group.smart:
            refs = smart_group_collections.get(group.name, [])
        else:
            refs = group.collections
        for ref in refs:
            key = (ref.library, ref.name)
            # First group wins (matches existing rotation behaviour)
            if key not in result:
                result[key] = group.name
    return result


def _classify_hub(hub, configured_keys: set[Tuple[str, str]], library_name: str) -> str:
    # Decide hub_type from Plex hub metadata + HSH config.
    # configured_keys = set of (library, title) tuples that HSH manages via its groups.
    title = hub.title
    if (library_name, title) in configured_keys:
        return HUB_TYPE_COLLECTION
    # Smart hubs (Recently Added, Top Rated, etc.) are non-deletable managed recommendations.
    if not getattr(hub, "deletable", True):
        return HUB_TYPE_SMART_HUB
    return HUB_TYPE_EXTERNAL


def _migrate_legacy_pins_into_hub_order(library_name: str, current_titles: set[str]) -> None:
    # One-shot: when LibraryHubOrder is first populated for a library, port over
    # the pin metadata from the legacy PinnedCollection table. The new model allows
    # only 1 top + 1 bottom per library, so we pick the smallest display_order from
    # each side (earliest-pinned wins).
    legacy = [p for p in get_pinned_collections() if p.library_name == library_name]
    if not legacy:
        return

    legacy_tops = sorted(
        [p for p in legacy if p.pin_position == PIN_TOP],
        key=lambda p: p.display_order,
    )
    legacy_bottoms = sorted(
        [p for p in legacy if p.pin_position == PIN_BOTTOM],
        key=lambda p: p.display_order,
    )

    winner_top = next((p for p in legacy_tops if p.collection_name in current_titles), None)
    winner_bottom = next((p for p in legacy_bottoms if p.collection_name in current_titles), None)

    if winner_top is not None:
        set_pin(library_name, winner_top.collection_name, PIN_TOP)
        if len(legacy_tops) > 1:
            dropped = [p.collection_name for p in legacy_tops if p is not winner_top]
            logger.info(
                "Legacy pin migration for '%s': kept top='%s', dropped extras=%s",
                library_name, winner_top.collection_name, dropped,
            )
    if winner_bottom is not None:
        set_pin(library_name, winner_bottom.collection_name, PIN_BOTTOM)
        if len(legacy_bottoms) > 1:
            dropped = [p.collection_name for p in legacy_bottoms if p is not winner_bottom]
            logger.info(
                "Legacy pin migration for '%s': kept bottom='%s', dropped extras=%s",
                library_name, winner_bottom.collection_name, dropped,
            )


def sync_library_hub_order(
    server: PlexServer,
    config: AppConfig,
    library_name: str,
    *,
    smart_group_collections: Optional[Dict[str, List[CollectionRef]]] = None,
) -> SyncResult:
    # Reconcile LibraryHubOrder DB rows with Plex's actual managed hubs for this library.
    # DB is the source of truth for ordering — we only update it for hubs that appear
    # in Plex but not in DB (slot_in_hub) or in DB but not in Plex (delete_hub).
    # We deliberately do NOT overwrite the DB with Plex's current order: calling
    # updateVisibility re-appends the hub to the end of Plex's managed list, so reading
    # Plex immediately after visibility changes would bake corrupted positions into DB.
    # enforce_group_adjacency runs after this and corrects Plex to match the DB.
    result = SyncResult(library_name=library_name)

    try:
        plex_hubs = _get_managed_hubs_for_library(server, library_name)
    except Exception as e:
        logger.warning("sync_library_hub_order: could not load hubs for '%s': %s", library_name, e)
        return result

    plex_hub_by_title = {hub.title: hub for hub in plex_hubs}

    configured_groups = _build_collection_to_group_map(config, smart_group_collections)
    configured_keys = set(configured_groups.keys())

    existing_rows = get_library_hub_order(library_name)
    existing_titles = {r.hub_title for r in existing_rows}
    is_first_sync = not existing_rows

    # Snapshot the inter-group order BEFORE any deletions/slot-ins. When a group
    # fully churns in one rotation (every member replaced), slot_in_hub has no
    # surviving member to anchor to and appends the new members at the bottom in
    # Plex/config order — silently discarding a user's dashboard drag that put
    # the group elsewhere. We re-impose this snapshot after slotting so the
    # dragged inter-group order survives a full churn.
    pre_pinned = {r.hub_title for r in existing_rows if r.pin_position is not None}
    group_order_snapshot: List[str] = []
    for r in existing_rows:  # already position-sorted
        if r.group_name and r.hub_title not in pre_pinned and r.group_name not in group_order_snapshot:
            group_order_snapshot.append(r.group_name)

    # 1) Remove DB rows for hubs that no longer exist in Plex
    for row in existing_rows:
        if row.hub_title not in plex_hub_by_title:
            if delete_hub(library_name, row.hub_title):
                result.removed.append(row.hub_title)
                logger.info("sync: removed stale hub '%s' from '%s'", row.hub_title, library_name)

    # 2) Add new hubs via slot-in; update metadata for existing
    for hub in plex_hubs:
        title = hub.title
        hub_type = _classify_hub(hub, configured_keys, library_name)
        group_name = configured_groups.get((library_name, title))

        if title in existing_titles:
            # Refresh type/group_name in case config changed
            upsert_hub(
                library_name,
                title,
                hub_type,
                group_name=group_name,
            )
            result.updated.append(title)
        else:
            slot_in_hub(
                library_name,
                title,
                hub_type,
                group_name=group_name,
            )
            result.added.append(title)
            logger.info(
                "sync: added hub '%s' to '%s' (type=%s, group=%s)",
                title,
                library_name,
                hub_type,
                group_name,
            )

    # 3) Legacy-pin migration on first sync only
    if is_first_sync:
        _migrate_legacy_pins_into_hub_order(library_name, set(plex_hub_by_title.keys()))

    # 4) Re-impose the pre-sync inter-group order (preserves dashboard drags
    #    through a full churn). Skipped on first sync — no prior order to honor.
    if group_order_snapshot:
        _reimpose_group_order(library_name, group_order_snapshot, config)

    logger.info(
        "sync: library '%s' done. added=%d removed=%d updated=%d errors=%d",
        library_name,
        len(result.added),
        len(result.removed),
        len(result.updated),
        len(result.plex_reorder_errors),
    )
    return result


def _reimpose_group_order(
    library_name: str,
    group_order_snapshot: List[str],
    config: AppConfig,
) -> bool:
    # Reorder the library's group BLOCKS to match the pre-sync inter-group order
    # (group_order_snapshot), leaving every ungrouped and pinned hub exactly
    # where it is. Each group block is slotted back into a position currently
    # occupied by a group block, just reordered among themselves — so a group
    # that fully churned (and got appended to the bottom by slot_in_hub) is
    # pulled back to its dragged place. Groups absent from the snapshot (newly
    # added) are ordered AFTER the snapshot groups by config display_order, then
    # name; the user can then drag them. Returns True if the order changed.
    rows = get_library_hub_order(library_name)
    if not rows:
        return False

    pinned = {r.hub_title for r in rows if r.pin_position is not None}
    titles = [r.hub_title for r in rows]
    group_of = {r.hub_title: r.group_name for r in rows}

    # Collapse consecutive same-group non-pinned hubs into group blocks; pinned
    # and ungrouped hubs are singleton blocks that never move.
    blocks: List[Tuple[Optional[str], List[str]]] = []
    i = 0
    while i < len(titles):
        g = group_of.get(titles[i])
        if g and titles[i] not in pinned:
            members: List[str] = []
            while i < len(titles) and group_of.get(titles[i]) == g and titles[i] not in pinned:
                members.append(titles[i])
                i += 1
            blocks.append((g, members))
        else:
            blocks.append((None, [titles[i]]))
            i += 1

    group_block_idxs = [idx for idx, (g, _) in enumerate(blocks) if g is not None]
    if len(group_block_idxs) < 2:
        return False  # 0 or 1 group block — nothing to reorder

    snapshot_rank = {g: i for i, g in enumerate(group_order_snapshot)}
    cfg_order = {g.name: g.display_order for g in config.groups}

    def rank(group_name: str) -> Tuple[int, int, str]:
        if group_name in snapshot_rank:
            return (0, snapshot_rank[group_name], "")
        return (1, cfg_order.get(group_name, 0), group_name)

    reordered = sorted((blocks[idx] for idx in group_block_idxs), key=lambda b: rank(b[0]))
    for slot_idx, gb in zip(group_block_idxs, reordered):
        blocks[slot_idx] = gb

    new_titles: List[str] = []
    for _, members in blocks:
        new_titles.extend(members)

    if new_titles == titles:
        return False

    set_library_hub_order(library_name, new_titles)
    logger.info(
        "Re-imposed inter-group order in '%s': %s",
        library_name,
        [g for g, _ in blocks if g is not None],
    )
    return True


def _place_group_consecutive(
    server: PlexServer,
    library_name: str,
    group_name: str,
    head: str,
    head_anchor: Optional[str],
    tail: List[str],
    move_head: bool,
) -> List[str]:
    # Place a group's members consecutively in Plex using verified moves that
    # recover from float-precision convergence (see move_hub_after_verified).
    #
    # When move_head is True, `head` is moved to sit immediately after
    # `head_anchor` (or to position 0 when head_anchor is None) — this sets the
    # group's absolute position. When move_head is False, `head` keeps its
    # current slot and the rest are clustered after it (adjacency-only).
    #
    # Each member in `tail` is then placed immediately after its predecessor.
    # Selective reordering: members already correctly slotted are skipped, which
    # minimises the number of Plex moves and therefore the convergence risk.
    errors: List[str] = []

    def positions() -> Dict[str, int]:
        hubs = _get_managed_hubs_for_library(server, library_name)
        return {h.title: i for i, h in enumerate(hubs)}

    try:
        pos = positions()
    except Exception as e:
        return [f"[group '{group_name}'] could not load hubs: {e}"]

    if move_head:
        already = head in pos and (
            (head_anchor is None and pos[head] == 0)
            or (head_anchor is not None and head_anchor in pos
                and pos[head] == pos[head_anchor] + 1)
        )
        if not already:
            err = move_hub_after_verified(server, library_name, head, head_anchor)
            if err:
                errors.append(f"[group '{group_name}'] reposition: {err}")
                logger.warning("Group reposition failed: %s", err)
                return errors
            try:
                pos = positions()
            except Exception as e:
                errors.append(f"[group '{group_name}'] could not reload hubs: {e}")
                return errors

    prev = head
    for member in tail:
        if member not in pos:
            continue
        if prev in pos and pos[member] == pos[prev] + 1:
            prev = member  # already adjacent — skip the move
            continue
        err = move_hub_after_verified(server, library_name, member, prev)
        if err:
            errors.append(f"[group '{group_name}'] chain: {err}")
            logger.warning("Group chain move failed: %s", err)
            return errors
        try:
            pos = positions()
        except Exception as e:
            errors.append(f"[group '{group_name}'] could not reload hubs: {e}")
            return errors
        prev = member

    return errors


def _regroup_via_repromote(
    server: PlexServer,
    library_name: str,
    group_name: str,
    members_in_order: List[str],
    head_anchor: Optional[str],
) -> List[str]:
    # Last-resort placement when chained moves cannot make a group contiguous
    # because its float region has converged (the per-hub re-promote recovery in
    # move_hub_after_verified refreshes only the moved hub, never the saturated
    # anchor gap it's inserted into).
    #
    # Re-promote every member in DB order: each unpromote+repromote re-appends
    # the hub to the END of managedHubs with fresh, widely-spaced floats, so
    # after the loop the members are contiguous and correctly ordered at the
    # tail. The internal gaps between them are now fresh, so the subsequent chain
    # never has to insert into a saturated gap. Only the single head→anchor move
    # targets the original (possibly saturated) region; if that one move can't
    # win, the group is left contiguous-but-trailing — which self-corrects on a
    # later rotation and is strictly better than leaving it split across the
    # screen.
    #
    # Returns a list of error messages (empty when the group ends contiguous,
    # regardless of whether the absolute head position was achieved).
    errors: List[str] = []

    def positions() -> Dict[str, int]:
        hubs = _get_managed_hubs_for_library(server, library_name)
        return {h.title: i for i, h in enumerate(hubs)}

    logger.info(
        "Regrouping '%s' in '%s' via re-promote (%d members) — chained moves "
        "could not cluster the group (float convergence)",
        group_name, library_name, len(members_in_order),
    )

    # 1) Re-promote each member in order → contiguous, ordered, fresh floats at tail.
    repromotable: List[str] = []
    for member in members_in_order:
        err = repromote_hub(server, library_name, member)
        if err:
            # A member with no visibility flags (smart/built-in) genuinely cannot
            # be re-promoted; record it but keep going so the rest still cluster.
            errors.append(f"[group '{group_name}'] regroup re-promote: {err}")
            logger.warning("Regroup re-promote failed: %s", err)
            continue
        repromotable.append(member)

    if not repromotable:
        return errors

    # 2) Place the head at its absolute position (after the anchor). Failure here
    #    is tolerated: the group is already contiguous at the tail.
    try:
        pos = positions()
    except Exception as e:
        errors.append(f"[group '{group_name}'] regroup could not load hubs: {e}")
        return errors

    head = repromotable[0]
    head_target_ok = head in pos and (
        (head_anchor is None and pos[head] == 0)
        or (head_anchor is not None and head_anchor in pos
            and pos[head] == pos[head_anchor] + 1)
    )
    if not head_target_ok:
        err = move_hub_after_verified(server, library_name, head, head_anchor)
        if err:
            logger.info(
                "Regroup of '%s' in '%s': group is contiguous but head could not "
                "reach its anchor slot (%s) — leaving contiguous-but-trailing, "
                "will self-correct: %s",
                group_name, library_name, head_anchor, err,
            )
            return errors  # contiguous-but-trailing — not a hard failure
        try:
            pos = positions()
        except Exception as e:
            errors.append(f"[group '{group_name}'] regroup could not reload hubs: {e}")
            return errors

    # 3) Chain the rest after the head. Members share fresh floats now, so these
    #    moves land without re-promotion.
    prev = head
    for member in repromotable[1:]:
        if member not in pos:
            continue
        if prev in pos and pos[member] == pos[prev] + 1:
            prev = member
            continue
        err = move_hub_after_verified(server, library_name, member, prev)
        if err:
            errors.append(f"[group '{group_name}'] regroup chain: {err}")
            logger.warning("Regroup chain move failed: %s", err)
            return errors
        try:
            pos = positions()
        except Exception as e:
            errors.append(f"[group '{group_name}'] regroup could not reload hubs: {e}")
            return errors
        prev = member

    return errors


def enforce_group_adjacency(
    server: PlexServer,
    library_name: str,
) -> List[str]:
    # Ensure HSH-managed hubs in Plex match the DB-specified order. The unit of
    # enforcement is either a multi-member GROUP or a single ungrouped COLLECTION
    # (despite the legacy name, this is no longer groups-only); both are held to
    # their DB slot in two ways:
    #
    #   (a) ADJACENCY: all of a group's members are consecutive in Plex's hub
    #       list. Plex appends newly-promoted hubs to the end, scattering members.
    #       (No-op for a single collection — nothing to cluster.)
    #
    #   (b) ABSOLUTE POSITION: each unit starts immediately after its DB anchor
    #       (the nearest non-pinned hub that precedes the unit's first member in
    #       DB position order). When updateVisibility re-appends a unit to the
    #       end, it is internally contiguous but at the wrong slot — adjacency
    #       alone would miss this.
    #
    # Only re-promotable custom collections are moved; native/smart hubs (Recently
    # Added, Seasonal, …) are never repositioned and serve as stable anchors —
    # they cannot be convergence-recovered, and the user does not reorder them.
    #
    # Units are processed in DB order (top → bottom). After each unit is fixed,
    # Plex's hub list is re-fetched so later units see the updated positions.
    # Pinned hubs are never moved here; pin enforcement runs after and wins.
    #
    # Returns a list of error messages (empty on full success).
    errors: List[str] = []

    # Self-heal: gather each group's members contiguously in the DB before
    # computing anchors. Rotation churn can interleave a group's members with
    # other groups in the DB; the anchor logic below ("highest current Plex
    # position among DB predecessors") is only correct when each group is
    # contiguous — otherwise a group anchors onto a lone member of another
    # group and splits it. Members are gathered at the group's largest existing
    # cluster; group order and non-group hub positions are left as the DB has
    # them, so manual drag placement is preserved. Derived from DB group
    # metadata only (not Plex order).
    try:
        if defragment_library_hub_order(library_name):
            logger.info("De-fragmented DB hub order for '%s' before adjacency enforcement", library_name)
    except Exception as e:
        logger.warning("Could not de-fragment hub order for '%s': %s", library_name, e)

    try:
        plex_hubs = _get_managed_hubs_for_library(server, library_name)
    except Exception as e:
        return [f"Could not load hubs for adjacency enforcement in '{library_name}': {e}"]

    plex_titles = [h.title for h in plex_hubs]
    position_of = {title: i for i, title in enumerate(plex_titles)}

    rows = get_library_hub_order(library_name)
    if not rows:
        return errors

    pinned = {r.hub_title for r in rows if r.pin_position is not None}
    pinned_bottom = {r.hub_title for r in rows if r.pin_position == PIN_BOTTOM}

    # Build groups in DB position order, excluding pinned members
    groups_db_order: Dict[str, List[str]] = {}
    for row in rows:  # rows are already sorted by position asc
        if row.group_name and row.hub_title not in pinned:
            groups_db_order.setdefault(row.group_name, []).append(row.hub_title)

    # Detect ungrouped hubs that are re-promotable custom collections. HSH's DB
    # types every ungrouped hub as 'external', so classify by the LIVE Plex
    # identifier instead: custom collections can be repositioned and convergence-
    # recovered (they have a rating key), whereas native/smart hubs (Recently
    # Added, Seasonal, …) cannot. We position collections to their DB slot and
    # leave native hubs untouched as stable anchors.
    collection_titles = {
        h.title for h in plex_hubs
        if str(getattr(h, "identifier", "") or "").startswith("custom.collection.")
    }

    # Native "Recently Added" hub title (if this library has one visible in the
    # managed list). Used below to keep a system hub at managedHubs[0] so the
    # native Continue Watching / On Deck row renders on top.
    native_top_anchor: Optional[str] = next(
        (
            h.title for h in plex_hubs
            if str(getattr(h, "identifier", "") or "") in _NATIVE_TOP_ANCHOR_IDENTIFIERS
        ),
        None,
    )

    # Enforcement units in DB position order. A unit is either a multi-member
    # group or a single ungrouped collection; both are positioned to their DB
    # slot via the same anchor logic below (a single member simply has no
    # internal adjacency to enforce). Generalising to ungrouped collections means
    # a lone collection no longer needs to be put in a group to be held in place.
    units: List[Tuple[str, List[str]]] = []
    seen_groups: Set[str] = set()
    for row in rows:  # DB position order
        if row.hub_title in pinned:
            continue
        if row.group_name:
            if row.group_name in seen_groups:
                continue
            seen_groups.add(row.group_name)
            members = groups_db_order.get(row.group_name)
            if members:
                units.append((row.group_name, members))
        elif row.hub_title in collection_titles:
            units.append((row.hub_title, [row.hub_title]))

    if not units:
        return errors

    # Keep Continue Watching / On Deck on top of the library: Plex renders a
    # custom collection at managedHubs[0] ABOVE the native on-deck row (sinking
    # it), but a system hub at [0] keeps it on top (see pin_hub_to_top). When the
    # top-most enforcement unit is a custom collection and the library has a
    # native "Recently Added" hub, raise that native hub to position 0 first so
    # the collection lands at [1]. The native hub is Home/Shared-only (not on the
    # Recommended tab), so moving it to [0] does not change the visible
    # Recommended order — it only reclaims [0] for a system hub.
    # Only when the native hub does NOT already precede the top collection in DB
    # order: if it does, the normal anchor path below moves the collection down
    # onto it (native untouched, fewer moves). We raise the native hub only when
    # DB places it after the collection (or not at all) — otherwise the top
    # collection would be forced to absolute position 0.
    db_pos_of = {r.hub_title: r.position for r in rows}
    top_head = units[0][1][0] if units[0][1] else None
    native_db_pos = db_pos_of.get(native_top_anchor) if native_top_anchor else None
    top_head_db_pos = db_pos_of.get(top_head)
    native_precedes_top_in_db = (
        native_db_pos is not None
        and top_head_db_pos is not None
        and native_db_pos < top_head_db_pos
    )
    if (
        native_top_anchor is not None
        and top_head is not None
        and top_head in collection_titles
        and native_top_anchor != top_head
        and native_top_anchor in position_of
        and position_of[native_top_anchor] != 0
        and not native_precedes_top_in_db
    ):
        raise_err = move_hub_after_verified(server, library_name, native_top_anchor, None)
        if raise_err:
            logger.warning(
                "Could not raise native hub '%s' to top in '%s' (Continue Watching "
                "may render below the top collection): %s",
                native_top_anchor, library_name, raise_err,
            )
        else:
            logger.info(
                "Raised native hub '%s' to managedHubs[0] in '%s' to keep "
                "Continue Watching on top",
                native_top_anchor, library_name,
            )
        # Refresh positions regardless: even a failed verified-move may have
        # shifted the list, and subsequent anchor math must see live positions.
        try:
            plex_hubs = _get_managed_hubs_for_library(server, library_name)
            plex_titles = [h.title for h in plex_hubs]
            position_of = {title: i for i, title in enumerate(plex_titles)}
        except Exception as e:
            return [f"Could not refresh hubs after raising native hub in '{library_name}': {e}"]

    db_titles_in_order = [r.hub_title for r in rows]

    for group_name, members in units:
        if not members:
            continue

        first_member = members[0]
        if first_member not in position_of:
            continue  # not visible in Plex yet

        first_db_pos = db_pos_of.get(first_member)
        if first_db_pos is None:
            continue

        # Anchor: among the hubs that precede this group in DB order, pick the
        # one with the HIGHEST current Plex position.
        #
        # Using the last predecessor in DB order (naive approach) breaks when
        # Plex smart hubs drift to low positions: those hubs never get
        # re-appended by rotation, so over time they end up near pos 0 while
        # HSH-managed collections are at higher positions. A drifted smart hub
        # as anchor would place the group near the top of the screen instead of
        # after the collection hubs that logically precede it.
        #
        # Pinned-TOP hubs ARE eligible anchors: they are locked at the top by
        # Plex and never drift, so they are reliable. Excluding them caused the
        # group to be targeted at the pinned hub's slot — e.g. when New Premieres
        # (pinned top) sits between Recently Added TV and the group, the old code
        # picked Recently Added TV and tried to move the group's first member
        # into New Premieres' slot, which Plex's float precision rejected every
        # run ("would not stay even after re-promote"), leaving the group split.
        # Only pinned-BOTTOM hubs are excluded (they live at the end, never a
        # valid top anchor).
        anchor: Optional[str] = None
        best_plex_pos = -1
        for title in db_titles_in_order:
            if db_pos_of[title] < first_db_pos and title not in pinned_bottom and title in position_of:
                if position_of[title] > best_plex_pos:
                    best_plex_pos = position_of[title]
                    anchor = title

        # When no non-pinned anchor exists (group is the first non-pinned block),
        # fall back to the rightmost (in Plex) pinned hub that DB places before
        # the group. This catches the case where the group has leapfrogged a
        # pinned hub (e.g. DocuFilms Recommended sits before New Premieres in
        # Plex even though DB says New Premieres → Recommended).
        effective_anchor = anchor
        if anchor is None:
            pinned_before_in_db = [
                t for t in db_titles_in_order
                if db_pos_of[t] < first_db_pos and t in pinned and t in position_of
            ]
            if pinned_before_in_db:
                effective_anchor = max(pinned_before_in_db, key=lambda t: position_of[t])

        # No DB predecessor → this unit would otherwise be forced to absolute
        # position 0, putting a custom collection at managedHubs[0] and sinking
        # Continue Watching. When the native "Recently Added" hub has been raised
        # to position 0 (see the pre-step above), anchor the collection after it
        # so it lands at [1] and a system hub keeps [0]. Only when the native hub
        # is confirmed at [0]; if raising it failed, fall through to the old
        # behaviour (collection at [0]) rather than dragging it down to the
        # native hub's buried position.
        if (
            effective_anchor is None
            and native_top_anchor is not None
            and native_top_anchor != first_member
            and position_of.get(native_top_anchor) == 0
            and first_member in collection_titles
        ):
            effective_anchor = native_top_anchor

        # Check whether the group needs repositioning
        if effective_anchor is None:
            needs_reposition = position_of[first_member] != 0
        elif effective_anchor in position_of:
            needs_reposition = position_of[first_member] != position_of[effective_anchor] + 1
        else:
            # Anchor not present in Plex (e.g. not yet promoted); skip reposition
            needs_reposition = False

        # Check whether members are already consecutive in Plex
        member_plex_positions = [position_of[m] for m in members if m in position_of]
        needs_adjacency = (
            len(member_plex_positions) >= 2
            and max(member_plex_positions) - min(member_plex_positions) != len(member_plex_positions) - 1
        )

        if not needs_reposition and not needs_adjacency:
            continue

        # Placement errors are held locally: a chained-move failure that the
        # whole-group re-promote recovery below then fixes should NOT surface as
        # a rotation error. They are only committed if the group is still broken
        # after regroup.
        placement_errors: List[str] = []
        if needs_reposition:
            logger.info(
                "Repositioning group '%s' in '%s': first member '%s' at Plex pos %d, "
                "expected after anchor '%s' (Plex pos %s)",
                group_name, library_name, first_member, position_of[first_member],
                effective_anchor, position_of.get(effective_anchor),
            )
            # Move first member to its correct absolute position, then chain the
            # rest after it.
            seq = [m for m in members if m in position_of]
            placement_errors.extend(_place_group_consecutive(
                server, library_name, group_name,
                head=seq[0], head_anchor=effective_anchor, tail=seq[1:],
                move_head=True,
            ))
        else:
            # Adjacency-only: anchor at first member's current Plex position.
            # Sort by current Plex position so members[0] stays put.
            members_by_plex = sorted(
                [m for m in members if m in position_of],
                key=lambda m: position_of[m],
            )
            logger.info(
                "Clustering scattered group '%s' in '%s' (%d members, positions %s)",
                group_name, library_name, len(members_by_plex),
                [position_of[m] for m in members_by_plex],
            )
            placement_errors.extend(_place_group_consecutive(
                server, library_name, group_name,
                head=members_by_plex[0], head_anchor=None, tail=members_by_plex[1:],
                move_head=False,
            ))

        # Re-fetch position map so subsequent groups see the updated order
        try:
            plex_hubs = _get_managed_hubs_for_library(server, library_name)
            plex_titles = [h.title for h in plex_hubs]
            position_of = {title: i for i, title in enumerate(plex_titles)}
        except Exception as e:
            errors.extend(placement_errors)
            errors.append(f"Could not refresh hubs after processing group '{group_name}': {e}")
            break

        # Final verification: the group should now be contiguous in Plex. If it
        # is not, float-precision convergence defeated the per-hub re-promote
        # recovery in move_hub_after_verified (which refreshes only the moved
        # hub, never the saturated anchor gap). Recover by re-promoting the whole
        # group so every member gets fresh float spacing, then re-verify.
        def _is_scattered(pos_map: Dict[str, int]) -> Optional[List[int]]:
            ps = sorted(pos_map[m] for m in members if m in pos_map)
            if len(ps) >= 2 and ps[-1] - ps[0] != len(ps) - 1:
                return ps
            return None

        if _is_scattered(position_of) is None:
            # Group is contiguous — placement succeeded (or self-resolved). Any
            # transient placement_errors are discarded.
            continue

        regroup_errors = _regroup_via_repromote(
            server, library_name, group_name, [m for m in members if m in position_of],
            effective_anchor,
        )
        try:
            plex_hubs = _get_managed_hubs_for_library(server, library_name)
            plex_titles = [h.title for h in plex_hubs]
            position_of = {title: i for i, title in enumerate(plex_titles)}
        except Exception as e:
            errors.extend(placement_errors + regroup_errors)
            errors.append(f"Could not refresh hubs after regrouping '{group_name}': {e}")
            break

        still = _is_scattered(position_of)
        if still is None:
            # Regroup made the group contiguous — the earlier placement churn is
            # not actionable, so it is logged-only and not surfaced as an error.
            if placement_errors or regroup_errors:
                logger.info(
                    "Group '%s' in '%s' clustered via re-promote recovery (%d "
                    "transient placement issue(s) resolved)",
                    group_name, library_name, len(placement_errors) + len(regroup_errors),
                )
            continue

        # Still scattered even after a full re-promote: genuinely unrecoverable
        # (e.g. members are smart/built-in hubs that cannot be re-promoted).
        errors.extend(placement_errors + regroup_errors)
        msg = (
            f"group '{group_name}' in '{library_name}' still scattered after "
            f"regroup (positions {still}) — precision convergence"
        )
        errors.append(msg)
        logger.warning(msg)

    return errors


def sync_all_libraries(
    server: PlexServer,
    config: AppConfig,
    *,
    smart_group_collections: Optional[Dict[str, List[CollectionRef]]] = None,
) -> List[SyncResult]:
    results: List[SyncResult] = []
    for lib in config.plex.libraries:
        if not lib.enabled:
            continue
        results.append(
            sync_library_hub_order(
                server,
                config,
                lib.name,
                smart_group_collections=smart_group_collections,
            )
        )
    return results


def save_library_hub_order(
    library_name: str,
    ordered_hub_titles: List[str],
) -> None:
    # Write user's drag-reordered hub list to DB.
    set_library_hub_order(library_name, ordered_hub_titles)
