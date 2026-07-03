from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple
from collections import defaultdict
from datetime import date
import threading
import time

import logging

from .integrations import (
    get_plex_server,
    sync_all_trakt_sources,
    sync_all_letterboxd_sources,
    sync_all_mdblist_sources,
    sync_all_tmdb_sources,
    sync_all_anilist_sources,
    sync_all_mal_sources,
    apply_home_screen_selection,
)
from .integrations.plex_client import get_library_collections
from .config.loader import load_config
from .config.schema import AppConfig, CollectionRef, RotationExecution, RotationResult
from .rotation import run_rotation_with_history, run_auto_rotation_with_history, build_collection_visibility_map, build_visibility_map_from_rotation_result, build_collection_sort_map
from .smart_groups import build_collection_metadata, resolve_smart_rules
from .db import (
    init_db,
    get_last_rotation_collections,
    get_rotation_history_context,
    record_rotation,
    create_simulation,
    get_simulation_by_id,
    mark_simulation_applied,
    get_pinned_refs,
)


logger = logging.getLogger(__name__)


def _changed_libraries_since_last_rotation(
    applied_collections: List[CollectionRef],
) -> Optional[Set[str]]:
    # Return the set of library names whose promoted-collection membership
    # differs from the previous rotation. Must be called BEFORE record_rotation
    # writes this rotation's history (get_last_rotation_collections then still
    # returns the prior rotation). Returns None to signal "enforce all" — used as
    # a safe fallback when history can't be read.
    try:
        from .db.history import get_last_rotation_collections
        prev = get_last_rotation_collections()
    except Exception as e:
        logger.warning("Could not load last rotation for change detection; enforcing all libraries: %s", e)
        return None

    prev_by_lib: Dict[str, Set[str]] = defaultdict(set)
    for r in prev:
        prev_by_lib[r.library].add(r.name)
    curr_by_lib: Dict[str, Set[str]] = defaultdict(set)
    for r in applied_collections:
        curr_by_lib[r.library].add(r.name)

    return {
        lib for lib in set(prev_by_lib) | set(curr_by_lib)
        if prev_by_lib[lib] != curr_by_lib[lib]
    }


def _sync_hub_order_post_rotation(
    server,
    config: AppConfig,
    smart_group_collections: Optional[Dict[str, List[CollectionRef]]],
    applied_collections: Optional[List[CollectionRef]] = None,
) -> None:
    # After rotation visibility is applied:
    # 1. Reconcile per-library hub order in our DB (slot-in newly active hubs,
    #    remove stale ones). Does NOT push full order to Plex (Plex's chain reorder
    #    is unreliable).
    # 2. Re-enforce pin-top and pin-bottom via single moves — necessary because
    #    Plex appends newly-promoted hubs to the end, which would otherwise push
    #    a pinned-bottom hub upward.
    from .hub_sync import sync_library_hub_order, enforce_group_adjacency
    from .db import get_library_hub_order, PIN_TOP, PIN_BOTTOM
    from .integrations.plex_client import _get_managed_hubs_for_library, move_hub_after, pin_hub_to_top

    # Group-adjacency moves are the main source of live home-screen "churn" a
    # browsing user can catch mid-rotation. A library whose promoted-collection
    # membership is unchanged this rotation has no newly-appended hubs to cluster,
    # so re-running adjacency would only chase cosmetic float drift while
    # scrambling the live view. Skip adjacency for unchanged libraries; pin
    # enforcement still runs (it self-skips when pins are already in place) and
    # re-triggers adjacency only if a pin actually moves. None = enforce all.
    changed_libraries: Optional[Set[str]] = (
        _changed_libraries_since_last_rotation(applied_collections)
        if applied_collections is not None else None
    )
    if changed_libraries is not None:
        logger.info(
            "Hub-order adjacency scoped to changed libraries: %s",
            sorted(changed_libraries) if changed_libraries else "(none changed)",
        )

    for lib in config.plex.libraries:
        if not lib.enabled:
            continue
        try:
            sync_library_hub_order(
                server,
                config,
                lib.name,
                smart_group_collections=smart_group_collections,
            )
        except Exception as e:
            logger.error("Hub order sync failed for library '%s': %s", lib.name, e, exc_info=True)
            continue

        membership_changed = changed_libraries is None or lib.name in changed_libraries

        # Cluster scattered group members (rotation appends new hubs at default
        # positions which fragments groups). Runs before pin enforcement so pins
        # still win the top/bottom slots. Skipped when this library's membership
        # is unchanged — nothing was appended, so nothing scattered.
        if membership_changed:
            try:
                adjacency_errors = enforce_group_adjacency(server, lib.name)
                for err in adjacency_errors:
                    logger.warning("Post-rotation adjacency in '%s': %s", lib.name, err)
            except Exception as e:
                logger.error("Group adjacency enforcement failed for '%s': %s",
                             lib.name, e, exc_info=True)
        else:
            logger.debug(
                "Skipping group adjacency for '%s' — promoted membership unchanged this rotation",
                lib.name,
            )

        # Re-enforce pins (at most 2 single moves per library)
        pin_moved = False
        try:
            rows = get_library_hub_order(lib.name)
            pin_top = next((r.hub_title for r in rows if r.pin_position == PIN_TOP), None)
            pin_bottom = next((r.hub_title for r in rows if r.pin_position == PIN_BOTTOM), None)
            if pin_top is None and pin_bottom is None:
                continue

            plex_titles = [h.title for h in _get_managed_hubs_for_library(server, lib.name)]
            if not plex_titles:
                continue

            if pin_top and pin_top not in plex_titles[:2]:
                err = pin_hub_to_top(server, lib.name, pin_top)
                if err:
                    logger.warning("Post-rotation pin-top failed for '%s' in '%s': %s",
                                   pin_top, lib.name, err)
                else:
                    logger.info("Post-rotation re-pinned '%s' to top in '%s'", pin_top, lib.name)
                    plex_titles = [h.title for h in _get_managed_hubs_for_library(server, lib.name)]
                    pin_moved = True

            if pin_bottom and plex_titles[-1] != pin_bottom:
                last = next((t for t in reversed(plex_titles) if t != pin_bottom), None)
                if last:
                    err = move_hub_after(server, lib.name, pin_bottom, last)
                    if err:
                        logger.warning("Post-rotation pin-bottom failed for '%s' in '%s': %s",
                                       pin_bottom, lib.name, err)
                    else:
                        logger.info("Post-rotation re-pinned '%s' to bottom in '%s'",
                                    pin_bottom, lib.name)
                        pin_moved = True
        except Exception as e:
            logger.error("Post-rotation pin enforcement failed for '%s': %s",
                         lib.name, e, exc_info=True)

        # Pin moves shift all other hubs by 1 position, which can displace groups
        # relative to their anchors. Re-run adjacency enforcement so groups land
        # correctly without waiting for the next rotation.
        if pin_moved:
            try:
                adjacency_errors = enforce_group_adjacency(server, lib.name)
                for err in adjacency_errors:
                    logger.warning("Post-pin adjacency in '%s': %s", lib.name, err)
            except Exception as e:
                logger.error("Post-pin adjacency enforcement failed for '%s': %s",
                             lib.name, e, exc_info=True)


def _resolve_smart_groups(server, config: AppConfig) -> Dict[str, List[CollectionRef]]:
    # Resolve all smart groups into concrete CollectionRef lists.
    smart_groups = [g for g in config.groups if g.smart]
    if not smart_groups:
        return {}

    logger.info("Resolving %d smart group(s)", len(smart_groups))
    metadata = build_collection_metadata(server, config)
    result: Dict[str, List[CollectionRef]] = {}
    for group in smart_groups:
        resolved = resolve_smart_rules(group.rules, metadata)
        result[group.name] = resolved
        logger.info("Smart group '%s' resolved to %d collections", group.name, len(resolved))
    return result


# Cache smart group resolution so concurrent /sync calls (one per library on
# dashboard load) don't each re-query Plex for all collection metadata.
# Short TTL — config changes during dev should be picked up quickly.
_SMART_GROUPS_CACHE_TTL_SECONDS = 60.0
_smart_groups_cache: Optional[Tuple[float, Dict[str, List[CollectionRef]]]] = None
_smart_groups_cache_lock = threading.Lock()


def resolve_smart_groups_cached(server, config: AppConfig) -> Dict[str, List[CollectionRef]]:
    # Thread-safe cached wrapper for _resolve_smart_groups. First caller within
    # the TTL window does the work; concurrent and subsequent callers reuse it.
    global _smart_groups_cache
    now = time.time()
    with _smart_groups_cache_lock:
        if (
            _smart_groups_cache is not None
            and (now - _smart_groups_cache[0]) < _SMART_GROUPS_CACHE_TTL_SECONDS
        ):
            return _smart_groups_cache[1]
        result = _resolve_smart_groups(server, config)
        _smart_groups_cache = (now, result)
        return result


def invalidate_smart_groups_cache() -> None:
    # Call this after config saves so the next /sync picks up the new rules.
    global _smart_groups_cache
    with _smart_groups_cache_lock:
        _smart_groups_cache = None


def _run_auto_rotation(
    server,
    config: AppConfig,
    max_rotation_id: int,
    usage_map: Dict,
    pinned: set,
    last_rotation_collections: List[CollectionRef],
) -> RotationResult:
    auto_rotate = config.rotation.auto_rotate
    library_names = auto_rotate.libraries or [lib.name for lib in config.plex.libraries if lib.enabled]

    if not library_names:
        raise ValueError("Auto-rotate enabled but no libraries specified or available")

    logger.info("Auto-rotate mode: fetching collections from libraries: %s", library_names)

    all_collections: List[CollectionRef] = []
    seen: set = set()
    for library_name in library_names:
        try:
            collections_map = get_library_collections(server, library_name)
            for coll_name in collections_map.keys():
                ref = CollectionRef(library=library_name, name=coll_name)
                if ref not in seen:
                    seen.add(ref)
                    all_collections.append(ref)
            logger.info("Found %d collections in library '%s'", len(collections_map), library_name)
        except Exception as e:
            logger.warning("Failed to get collections from library '%s': %s", library_name, e)

    logger.info("Total: %d unique collections across %d libraries", len(all_collections), len(library_names))

    return run_auto_rotation_with_history(
        all_collections,
        max_collections=config.rotation.max_collections,
        collection_selection="random",
        blacklisted_collections=config.rotation.blacklisted_collections,
        allow_repeats=config.rotation.allow_repeats,
        last_rotation_collections=last_rotation_collections,
        max_rotation_id=max_rotation_id,
        usage_map=usage_map,
        pinned=pinned,
        per_library_limits=config.rotation.per_library_limits,
    )


def _sync_selected_collections(
    server,
    config: AppConfig,
    selected_collections: List[CollectionRef],
) -> None:
    # Sync only integration sources whose collections were selected for rotation.
    from .integrations.trakt_sync import sync_single_trakt_source
    from .integrations.letterboxd_sync import sync_single_letterboxd_source
    from .integrations.mdblist_sync import sync_single_mdblist_source
    from .integrations.tmdb_sync import sync_single_tmdb_source
    from .integrations.anilist_sync import sync_single_anilist_source
    from .integrations.mal_sync import sync_single_mal_source
    from .db import record_sync_result

    # Build name -> source maps for quick lookup (name is the collection name)
    trakt_sources = {s.name: s for s in (config.trakt.sources if config.trakt and config.trakt.enabled else [])}
    letterboxd_sources = {s.name: s for s in (config.letterboxd.sources if config.letterboxd else [])}
    mdblist_sources = {s.name: s for s in (config.mdblist.sources if config.mdblist and config.mdblist.enabled else [])}
    tmdb_sources = {s.name: s for s in (config.tmdb.sources if config.tmdb and config.tmdb.enabled else [])}
    anilist_sources = {s.name: s for s in (config.anilist.sources if config.anilist else [])}
    mal_sources = {s.name: s for s in (config.mal.sources if config.mal and config.mal.enabled else [])}

    def _sync_and_record(integration_type: str, source, sync_fn):
        try:
            total, matched = sync_fn(server, config, source)
            record_sync_result(
                integration_type=integration_type,
                source_name=source.name,
                source_url=source.url,
                items_total=total,
                items_matched=matched,
            )
        except Exception as exc:
            logger.error(f"Error syncing {integration_type} source '{source.name}': {exc}")
            record_sync_result(
                integration_type=integration_type,
                source_name=source.name,
                source_url=source.url,
                items_total=0,
                items_matched=0,
                sync_status="error",
                error_message=str(exc),
            )

    for ref in selected_collections:
        name = ref.name
        if name in trakt_sources:
            logger.info("Syncing selected Trakt collection: %s", ref)
            _sync_and_record("trakt", trakt_sources[name], sync_single_trakt_source)
        elif name in letterboxd_sources:
            logger.info("Syncing selected Letterboxd collection: %s", ref)
            _sync_and_record("letterboxd", letterboxd_sources[name], sync_single_letterboxd_source)
        elif name in mdblist_sources:
            logger.info("Syncing selected MDBList collection: %s", ref)
            _sync_and_record("mdblist", mdblist_sources[name], sync_single_mdblist_source)
        elif name in tmdb_sources:
            logger.info("Syncing selected TMDb collection: %s", ref)
            _sync_and_record("tmdb", tmdb_sources[name], sync_single_tmdb_source)
        elif name in anilist_sources:
            logger.info("Syncing selected AniList collection: %s", ref)
            _sync_and_record("anilist", anilist_sources[name], sync_single_anilist_source)
        elif name in mal_sources:
            logger.info("Syncing selected MAL collection: %s", ref)
            _sync_and_record("mal", mal_sources[name], sync_single_mal_source)
        else:
            logger.debug("Collection '%s' is not a synced source, skipping sync", ref)


def _reconcile_pin_identities(server, config: AppConfig) -> None:
    # Re-bind pinned collections to their Plex collection by ratingKey before
    # their visibility is read, so a pin survives a rename (a renamed collection
    # keeps its ratingKey; only its title changes). Without this, a rename
    # orphans the pin on the old name and HSH silently stops enforcing its
    # visibility — leaving e.g. a Home=off collection stuck on Home.
    from .db import reconcile_pinned_collection_identities

    live_by_library: Dict[str, List[tuple]] = {}
    for lib in config.plex.libraries:
        if not lib.enabled:
            continue
        try:
            section = server.library.section(lib.name)
            live_by_library[lib.name] = [
                (int(c.ratingKey), c.title)
                for c in section.collections()
                if getattr(c, "ratingKey", None) is not None
            ]
        except Exception as e:
            logger.warning("Pin reconcile: could not list collections for '%s': %s", lib.name, e)

    try:
        reconcile_pinned_collection_identities(live_by_library)
    except Exception as e:
        logger.error("Pin identity reconcile failed: %s", e, exc_info=True)


def run_rotation_once(
    config: Optional[AppConfig] = None,
    *,
    dry_run: bool = False,
) -> RotationExecution:
    # Orchestrate a single, history-aware rotation against Plex
    #
    # dry_run:
    #   - When True: do NOT change Plex, but DO update rotation history
    #   - When False: change Plex and update rotation history
    if config is None:
        config = load_config()

    logger.info("Starting rotation (dry_run=%s)", dry_run)

    init_db()
    server = get_plex_server(config)
    smart_group_collections = _resolve_smart_groups(server, config)
    _reconcile_pin_identities(server, config)
    use_auto_rotate = config.rotation.auto_rotate.enabled

    if config.rotation.sync_all_on_rotation:
        logger.info("Syncing all integration sources")
        for sync_fn, name in [
            (sync_all_trakt_sources, "Trakt"),
            (sync_all_letterboxd_sources, "Letterboxd"),
            (sync_all_mdblist_sources, "MDBList"),
            (sync_all_tmdb_sources, "TMDb"),
            (sync_all_anilist_sources, "AniList"),
            (sync_all_mal_sources, "MAL"),
        ]:
            try:
                sync_fn(server, config)
            except Exception as e:
                logger.error("%s sync failed, continuing with rotation: %s", name, e)
    else:
        logger.info("Selective sync mode: will only sync collections selected for rotation")
        max_rotation_id, usage_map = get_rotation_history_context()
        pinned = get_pinned_refs()
        last_rotation_collections = get_last_rotation_collections()

        if use_auto_rotate:
            rotation_result = _run_auto_rotation(server, config, max_rotation_id, usage_map, pinned, last_rotation_collections)
        else:
            rotation_result = run_rotation_with_history(
                config,
                max_rotation_id=max_rotation_id,
                usage_map=usage_map,
                last_rotation_collections=last_rotation_collections,
                pinned=pinned,
                smart_group_collections=smart_group_collections,
            )

        _sync_selected_collections(server, config, rotation_result.selected_collections)

    if config.rotation.sync_all_on_rotation:
        max_rotation_id, usage_map = get_rotation_history_context()
        pinned = get_pinned_refs()
        last_rotation_collections = get_last_rotation_collections()

        if use_auto_rotate:
            rotation_result = _run_auto_rotation(server, config, max_rotation_id, usage_map, pinned, last_rotation_collections)
        else:
            rotation_result = run_rotation_with_history(
                config,
                max_rotation_id=max_rotation_id,
                usage_map=usage_map,
                last_rotation_collections=last_rotation_collections,
                pinned=pinned,
                smart_group_collections=smart_group_collections,
            )

    if use_auto_rotate:
        auto_rotate = config.rotation.auto_rotate
        auto_vis = {"home": auto_rotate.visibility_home, "shared": auto_rotate.visibility_shared, "recommended": auto_rotate.visibility_recommended}
        collection_visibility = {ref: auto_vis.copy() for ref in rotation_result.selected_collections}
    else:
        collection_visibility = build_visibility_map_from_rotation_result(rotation_result, config, smart_group_collections)

    from .db import get_pinned_visibility_map
    collection_visibility.update(get_pinned_visibility_map())

    collection_sort = build_collection_sort_map(config, smart_group_collections)

    applied = apply_home_screen_selection(
        server,
        config,
        rotation_result.selected_collections,
        collection_visibility,
        dry_run=dry_run,
        smart_group_collections=smart_group_collections,
        collection_sort=collection_sort,
    )

    if not dry_run:
        _sync_hub_order_post_rotation(server, config, smart_group_collections, applied_collections=applied)

        try:
            from .user_targeting import apply_rotation_targeting, sync_all_user_filters
            apply_rotation_targeting(server, config, applied, smart_group_collections)
            sync_all_user_filters(config)
        except Exception as e:
            logger.error("Failed to apply user targeting: %s", e, exc_info=True)

    group_contributions = {
        g.group_name: g.chosen_collections
        for g in rotation_result.groups
        if g.chosen_collections
    }

    rotation_id = record_rotation(
        rotation_result.selected_collections,
        success=True,
        error_message=None,
        group_contributions=group_contributions or None,
    )

    if not dry_run and config.tautulli and config.tautulli.enabled and config.tautulli.collect_on_rotation:
        try:
            from .integrations.tautulli_analytics import collect_analytics_for_collections
            logger.info("Collecting analytics after rotation %d", rotation_id)
            analytics_result = collect_analytics_for_collections(
                config=config,
                collection_refs=rotation_result.selected_collections,
                rotation_id=rotation_id,
            )
            logger.info(
                "Analytics collection complete: %d succeeded, %d failed",
                len(analytics_result.get("collected", [])),
                len(analytics_result.get("failed", [])),
            )
        except Exception as e:
            logger.error("Failed to collect analytics after rotation: %s", e, exc_info=True)

    execution = RotationExecution(
        rotation=rotation_result,
        applied_collections=applied,
        dry_run=dry_run,
    )

    logger.info("Selected collections: %s", [str(r) for r in rotation_result.selected_collections])
    logger.info("Applied collections: %s", [str(r) for r in applied])
    logger.info("Rotation complete (dry_run=%s)", dry_run)

    return execution


def simulate_rotation_once(
    config: Optional[AppConfig] = None,
) -> RotationExecution:
    # Simulation only, doesn't actualy write/set anything on Plex
    if config is None:
        config = load_config()

    init_db()
    max_rotation_id, usage_map = get_rotation_history_context()
    last_rotation_collections = get_last_rotation_collections()

    logger.info("Simulating next rotation (no Plex write, no history write)")

    pinned = get_pinned_refs()
    server = get_plex_server(config)
    smart_group_collections = _resolve_smart_groups(server, config)

    if config.rotation.auto_rotate.enabled:
        rotation_result = _run_auto_rotation(server, config, max_rotation_id, usage_map, pinned, last_rotation_collections)
    else:
        rotation_result = run_rotation_with_history(
            config,
            max_rotation_id=max_rotation_id,
            usage_map=usage_map,
            last_rotation_collections=last_rotation_collections,
            pinned=pinned,
            smart_group_collections=smart_group_collections,
        )

    simulation_id = create_simulation(rotation_result)

    logger.info("Simulation %s created with collections: %s", simulation_id, [str(r) for r in rotation_result.selected_collections])

    from .rotation import order_collections_for_display
    from .db import get_pinned_collections
    pinned_db = get_pinned_collections()
    pinned_order = {CollectionRef(library=p.library_name, name=p.collection_name): p.display_order for p in pinned_db}
    pinned_positions = {CollectionRef(library=p.library_name, name=p.collection_name): p.pin_position for p in pinned_db}
    ordered = order_collections_for_display(
        list(rotation_result.selected_collections),
        config,
        pinned_names=pinned,
        pinned_order=pinned_order,
        smart_group_collections=smart_group_collections,
        pinned_positions=pinned_positions,
    )

    # Sort chosen_collections per group to match display ordering
    group_cfg_map = {g.name: g for g in config.groups}
    for group_result in rotation_result.groups:
        gcfg = group_cfg_map.get(group_result.group_name)
        if not gcfg or not group_result.chosen_collections:
            continue
        if gcfg.collection_order == "alpha":
            group_result.chosen_collections = sorted(group_result.chosen_collections, key=lambda r: (r.library, r.name))
        elif gcfg.collection_order == "custom" and not gcfg.smart:
            coll_list = gcfg.collections
            group_result.chosen_collections = sorted(
                group_result.chosen_collections,
                key=lambda r: coll_list.index(r) if r in coll_list else len(coll_list),
            )

    # Group by library to match how Plex displays collections per-library section
    enabled_libraries = [lib.name for lib in config.plex.libraries if lib.enabled]
    library_grouped: List[CollectionRef] = []
    used: set = set()
    for lib_name in enabled_libraries:
        for ref in ordered:
            if ref not in used and ref.library == lib_name:
                library_grouped.append(ref)
                used.add(ref)
    for ref in ordered:
        if ref not in used:
            library_grouped.append(ref)

    execution = RotationExecution(
        rotation=rotation_result,
        applied_collections=library_grouped,
        dry_run=True,
        simulation_id=simulation_id,
    )
    return execution


# Take a previously simulated rotation and actually apply it to Plex
def sync_all_sources(config: Optional[AppConfig] = None) -> Dict[str, int]:
    # Sync all Trakt, Letterboxd, and MDBList sources without running a rotation.
    if config is None:
        config = load_config()

    logger.info("Starting manual sync of all sources")

    # Ensure DB tables exist
    init_db()

    # Connect to Plex
    server = get_plex_server(config)

    # Sync all sources
    sync_all_trakt_sources(server, config)
    sync_all_letterboxd_sources(server, config)
    sync_all_mdblist_sources(server, config)
    sync_all_tmdb_sources(server, config)
    sync_all_anilist_sources(server, config)
    sync_all_mal_sources(server, config)

    logger.info("Manual sync complete")

    return {
        "status": "success",
    }


def restore_plex_visibility(config: Optional[AppConfig] = None) -> None:
    # Re-apply the last rotation's visibility to Plex without selecting new collections
    # or writing a new rotation history entry. Called when Plex reconnects after an outage.
    if config is None:
        config = load_config()

    init_db()
    last_collections = get_last_rotation_collections()
    if not last_collections:
        logger.info("Plex reconnect restore: no previous rotation found, skipping")
        return

    logger.info(
        "Plex reconnect: restoring visibility for %d collections", len(last_collections)
    )

    server = get_plex_server(config)
    smart_group_collections = resolve_smart_groups_cached(server, config)
    _reconcile_pin_identities(server, config)

    from datetime import date
    from .config.schema import RotationResult as _RotationResult

    rotation_result = _RotationResult(
        selected_collections=last_collections,
        groups=[],
        max_global=len(last_collections),
        remaining_global=0,
        today=date.today(),
    )

    if config.rotation.auto_rotate.enabled:
        auto_rotate = config.rotation.auto_rotate
        auto_vis = {
            "home": auto_rotate.visibility_home,
            "shared": auto_rotate.visibility_shared,
            "recommended": auto_rotate.visibility_recommended,
        }
        collection_visibility = {ref: auto_vis.copy() for ref in last_collections}
    else:
        collection_visibility = build_visibility_map_from_rotation_result(
            rotation_result, config, smart_group_collections
        )

    from .db import get_pinned_visibility_map
    collection_visibility.update(get_pinned_visibility_map())

    collection_sort = build_collection_sort_map(config, smart_group_collections)

    apply_home_screen_selection(
        server,
        config,
        last_collections,
        collection_visibility,
        dry_run=False,
        smart_group_collections=smart_group_collections,
        collection_sort=collection_sort,
    )

    _sync_hub_order_post_rotation(server, config, smart_group_collections)
    logger.info("Plex reconnect: visibility restored successfully")


def apply_simulation(
    simulation_id: int,
    config: Optional[AppConfig] = None,
) -> RotationExecution:
    if config is None:
        config = load_config()

    init_db()

    sim = get_simulation_by_id(simulation_id)
    if sim is None:
        raise ValueError(f"Simulation {simulation_id} not found")
    if sim.applied:
        raise ValueError(f"Simulation {simulation_id} has already been applied")

    logger.info("Applying simulation %s", simulation_id)

    if sim.rotation_snapshot:
        rotation_result = RotationResult(**sim.rotation_snapshot)
    else:
        selected_raw = list(sim.selected_collections or [])
        # Handle both new {library, name} dicts and legacy bare strings
        selected: List[CollectionRef] = []
        for item in selected_raw:
            if isinstance(item, dict):
                selected.append(CollectionRef(library=item.get("library", ""), name=item["name"]))
            else:
                selected.append(CollectionRef(library="", name=str(item)))
        rotation_result = RotationResult(
            selected_collections=selected,
            groups=[],
            max_global=len(selected),
            remaining_global=0,
            today=date.today(),
        )

    server = get_plex_server(config)
    smart_group_collections = _resolve_smart_groups(server, config)
    _reconcile_pin_identities(server, config)

    if config.rotation.auto_rotate.enabled:
        auto_rotate = config.rotation.auto_rotate
        auto_vis = {"home": auto_rotate.visibility_home, "shared": auto_rotate.visibility_shared, "recommended": auto_rotate.visibility_recommended}
        collection_visibility = {ref: auto_vis.copy() for ref in rotation_result.selected_collections}
    else:
        collection_visibility = build_visibility_map_from_rotation_result(rotation_result, config, smart_group_collections)

    from .db import get_pinned_visibility_map
    collection_visibility.update(get_pinned_visibility_map())

    applied = apply_home_screen_selection(
        server,
        config,
        rotation_result.selected_collections,
        collection_visibility,
        dry_run=False,
        smart_group_collections=smart_group_collections,
    )

    _sync_hub_order_post_rotation(server, config, smart_group_collections)

    try:
        from .user_targeting import apply_rotation_targeting, sync_all_user_filters
        apply_rotation_targeting(server, config, applied, smart_group_collections)
        sync_all_user_filters(config)
    except Exception as e:
        logger.error("Failed to apply user targeting: %s", e, exc_info=True)

    sim_group_contributions = {
        g.group_name: g.chosen_collections
        for g in rotation_result.groups
        if g.chosen_collections
    }
    record_rotation(
        rotation_result.selected_collections,
        success=True,
        error_message=None,
        group_contributions=sim_group_contributions or None,
    )

    # Mark simulation as applied
    mark_simulation_applied(simulation_id)

    logger.info(
        "Simulation %s applied. Collections: %s",
        simulation_id,
        rotation_result.selected_collections,
    )

    execution = RotationExecution(
        rotation=rotation_result,
        applied_collections=applied,
        dry_run=False,
        simulation_id=simulation_id,
    )
    return execution
