from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from plexapi.server import PlexServer

from .config.schema import AppConfig, CollectionRef
from .db import (
    HUB_TYPE_COLLECTION,
    HUB_TYPE_EXTERNAL,
    HUB_TYPE_SMART_HUB,
    PIN_BOTTOM,
    PIN_TOP,
    delete_hub,
    get_library_hub_order,
    get_pinned_collections,
    set_library_hub_order,
    set_pin,
    slot_in_hub,
    upsert_hub,
)
from .integrations.plex_client import _get_managed_hubs_for_library, move_hub_after

logger = logging.getLogger(__name__)


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
) -> Dict[Tuple[str, str], str]:
    # (library_name, collection_name) -> group_name
    result: Dict[Tuple[str, str], str] = {}
    smart_group_collections = smart_group_collections or {}
    for group in config.groups:
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

    logger.info(
        "sync: library '%s' done. added=%d removed=%d updated=%d errors=%d",
        library_name,
        len(result.added),
        len(result.removed),
        len(result.updated),
        len(result.plex_reorder_errors),
    )
    return result


def enforce_group_adjacency(
    server: PlexServer,
    library_name: str,
) -> List[str]:
    # Ensure HSH-managed groups in Plex match the DB-specified order in two ways:
    #
    #   (a) ADJACENCY: all group members are consecutive in Plex's hub list.
    #       Plex appends newly-promoted hubs to the end, scattering group members.
    #
    #   (b) ABSOLUTE POSITION: each group starts immediately after its DB anchor
    #       (the nearest non-pinned hub that precedes the group's first member in
    #       DB position order). When updateVisibility re-appends an entire group
    #       to the end, the group is internally contiguous but at the wrong slot —
    #       adjacency alone would miss this.
    #
    # Groups are processed in DB order (top → bottom). After each group is fixed,
    # Plex's hub list is re-fetched so subsequent groups see the updated positions.
    # Pinned hubs are never moved here; pin enforcement runs after and wins.
    #
    # Returns a list of error messages (empty on full success).
    errors: List[str] = []

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

    # Build groups in DB position order, excluding pinned members
    groups_db_order: Dict[str, List[str]] = {}
    for row in rows:  # rows are already sorted by position asc
        if row.group_name and row.hub_title not in pinned:
            groups_db_order.setdefault(row.group_name, []).append(row.hub_title)

    if not groups_db_order:
        return errors

    db_pos_of = {r.hub_title: r.position for r in rows}
    db_titles_in_order = [r.hub_title for r in rows]

    for group_name, members in groups_db_order.items():
        if len(members) < 2:
            continue

        first_member = members[0]
        if first_member not in position_of:
            continue  # not visible in Plex yet

        first_db_pos = db_pos_of.get(first_member)
        if first_db_pos is None:
            continue

        # Anchor: nearest non-pinned hub before this group in DB order.
        # Skip pinned hubs — they have their own enforcement and their Plex
        # position can differ significantly from their DB position.
        anchor: Optional[str] = None
        for title in reversed(db_titles_in_order):
            if db_pos_of[title] < first_db_pos and title not in pinned:
                anchor = title
                break

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

        if needs_reposition:
            logger.info(
                "Repositioning group '%s' in '%s': first member '%s' at Plex pos %d, "
                "expected after anchor '%s' (Plex pos %s)",
                group_name, library_name, first_member, position_of[first_member],
                effective_anchor, position_of.get(effective_anchor),
            )
            # Move first member to correct absolute position, then chain the rest
            err = move_hub_after(server, library_name, first_member, effective_anchor)
            if err:
                errors.append(f"[group '{group_name}'] reposition: {err}")
                logger.warning("Group reposition failed: %s", err)
            else:
                prev = first_member
                for member in members[1:]:
                    if member not in position_of:
                        continue
                    err = move_hub_after(server, library_name, member, prev)
                    if err:
                        errors.append(f"[group '{group_name}'] reposition chain: {err}")
                        logger.warning("Group reposition chain move failed: %s", err)
                        break
                    prev = member
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
            prev = members_by_plex[0]
            for member in members_by_plex[1:]:
                err = move_hub_after(server, library_name, member, prev)
                if err:
                    errors.append(f"[group '{group_name}'] {err}")
                    logger.warning("Group adjacency move failed: %s", err)
                    break
                prev = member

        # Re-fetch position map so subsequent groups see the updated order
        try:
            plex_hubs = _get_managed_hubs_for_library(server, library_name)
            plex_titles = [h.title for h in plex_hubs]
            position_of = {title: i for i, title in enumerate(plex_titles)}
        except Exception as e:
            errors.append(f"Could not refresh hubs after processing group '{group_name}': {e}")
            break

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
