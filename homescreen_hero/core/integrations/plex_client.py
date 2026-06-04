from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import requests
import urllib3
from plexapi.server import PlexServer
from plexapi.myplex import MyPlexAccount

# Suppress noisy "Unverified HTTPS request" warnings — we intentionally
# skip cert verification for local Plex connections (still encrypted).
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from ..config.schema import AppConfig, CollectionRef

logger = logging.getLogger(__name__)


def _make_session() -> requests.Session:
    # Shared session that skips SSL cert verification for local Plex connections.
    # The connection is still encrypted (HTTPS), we just don't validate the cert —
    # self-hosted Plex servers commonly use certs issued for *.plex.direct which
    # don't match local IPs / custom hostnames.
    session = requests.Session()
    session.verify = False
    return session


def get_plex_server(config: AppConfig) -> PlexServer:
    # Create a PlexServer instance from the config
    base_url = config.plex.base_url
    token = config.plex.token

    logger.debug("Connecting to Plex at %s", base_url)

    # Raises if connection fails, which is good for early detection
    server = PlexServer(base_url, token, session=_make_session())
    return server


def get_library_collections(
    server: PlexServer,
    library_name: str,
) -> Dict[str, object]:
    # Return a dict mapping collection title -> Collection object
    library = server.library.section(library_name)
    collections = library.collections()

    by_title: Dict[str, object] = {}
    for coll in collections:
        # Titles are case-sensitive in Plex, but we'll store as-is
        by_title[coll.title] = coll

    return by_title


def get_collection_labels(collection: object) -> List[str]:
    # Extract label tags from a PlexAPI Collection object.
    # Returns empty list if collection has no labels or labels aren't loaded.
    return [label.tag for label in getattr(collection, "labels", [])]


def get_collection_item_count(collection: object) -> int:
    # Get the number of items in a collection without fetching them all.
    return getattr(collection, "childCount", 0)


def get_configured_collections(
    config: AppConfig,
    smart_group_collections: Optional[Dict[str, List[CollectionRef]]] = None,
) -> Set[CollectionRef]:
    # Build the set of all CollectionRefs referenced in groups and integration sources.
    refs: Set[CollectionRef] = set()

    for group in config.groups:
        if group.smart and smart_group_collections and group.name in smart_group_collections:
            refs.update(smart_group_collections[group.name])
        else:
            refs.update(group.collections)

    # Integration sources: name is the collection name, plex_library is the library.
    if config.trakt and config.trakt.enabled and config.trakt.sources:
        for source in config.trakt.sources:
            refs.add(CollectionRef(library=source.plex_library, name=source.name))

    if config.letterboxd and config.letterboxd.sources:
        for source in config.letterboxd.sources:
            refs.add(CollectionRef(library=source.plex_library, name=source.name))

    if config.mdblist and config.mdblist.enabled and config.mdblist.sources:
        for source in config.mdblist.sources:
            refs.add(CollectionRef(library=source.plex_library, name=source.name))

    if config.anilist and config.anilist.sources:
        for source in config.anilist.sources:
            refs.add(CollectionRef(library=source.plex_library, name=source.name))

    if config.tmdb and config.tmdb.enabled and config.tmdb.sources:
        for source in config.tmdb.sources:
            refs.add(CollectionRef(library=source.plex_library, name=source.name))

    if config.mal and config.mal.enabled and config.mal.sources:
        for source in config.mal.sources:
            refs.add(CollectionRef(library=source.plex_library, name=source.name))

    return refs


# Currently unused — auto-delete functionality is disabled in service.py
def cleanup_deleted_integration_sources(
    server: PlexServer,
    config: AppConfig,
    *,
    auto_update_config: bool = True,
) -> Dict[str, List[str]]:
    """
    This is deletion territory, so gonna try an detail exactly whats going on:

    This function:
    1. Identifies collections that were previously rotated but are no longer in:
       - Integration sources (Trakt/Letterboxd/MDBList)
       - Groups (manual collections or integration-backed collections)
       - Pinned collections
    2. Deletes those collections from Plex

    IMPORTANT: Collections are protected from deletion if they are:
    - Still in groups (manual or integration-backed)
    - Pinned by the user
    This preserves manually created Plex collections and user-pinned collections.

    Args:
        server: PlexServer instance
        config: Application configuration
        auto_update_config: Deprecated, no longer used (kept for API compatibility)

    Returns:
        Dict with keys:
            - 'deleted_from_plex': List of collection names deleted from Plex
            - 'orphaned_in_groups': List of collection names (always empty now)
            - 'config_updated': Boolean (always False now)
    """
    from ..db.history import get_rotation_history_context
    from ..config.loader import load_config_text, save_config_text, get_config_path
    import yaml

    # Get current integration source names
    current_integration_sources = set()

    if config.trakt and config.trakt.enabled and config.trakt.sources:
        for source in config.trakt.sources:
            current_integration_sources.add(source.name)

    if config.letterboxd and config.letterboxd.sources:
        for source in config.letterboxd.sources:
            current_integration_sources.add(source.name)

    if config.mdblist and config.mdblist.enabled and config.mdblist.sources:
        for source in config.mdblist.sources:
            current_integration_sources.add(source.name)

    if config.anilist and config.anilist.sources:
        for source in config.anilist.sources:
            current_integration_sources.add(source.name)

    # Get previously rotated collections from history
    _, usage_map = get_rotation_history_context()
    previously_rotated = set(usage_map.keys())

    # Get collections referenced in groups (might be manual collections)
    group_collections = set()
    for group in config.groups:
        for name in group.collections:
            group_collections.add(name)

    # Get pinned collections - users explicitly want these preserved
    from ..db import get_pinned_refs
    pinned_refs = get_pinned_refs()
    pinned_collections = {r.name for r in pinned_refs}

    logger.info(f"Cleanup check - Previously rotated: {sorted(previously_rotated)}")
    logger.info(f"Cleanup check - Integration sources: {sorted(current_integration_sources)}")
    logger.info(f"Cleanup check - Group collections: {sorted(group_collections)}")
    logger.info(f"Cleanup check - Pinned collections: {sorted(pinned_collections)}")

    # Find collections that were from integration sources but have been deleted
    # CRITICAL: Only delete collections if they meet ALL criteria:
    # 1. Previously rotated (in history)
    # 2. NOT in current integration sources (source was removed)
    # 3. NOT in current groups (not a manual collection)
    # 4. NOT pinned by the user
    #
    # If a collection is still in a group or pinned, it's either:
    # - A manual Plex collection that should be preserved
    # - An integration source that will be synced later
    # - A collection the user explicitly pinned
    # Either way, we should NEVER delete it.

    # Collections that were rotated but are no longer protected
    deleted_sources = previously_rotated - current_integration_sources - group_collections - pinned_collections

    logger.info(f"Cleanup check - Will delete (not protected): {sorted(deleted_sources)}")

    deleted_from_plex = []
    orphaned_in_groups = []

    # Get enabled libraries
    enabled_libraries = [lib.name for lib in config.plex.libraries if lib.enabled]

    logger.info("Checking for deleted integration sources to clean up...")

    if deleted_sources:
        logger.warning(f"DELETING {len(deleted_sources)} collections: {sorted(deleted_sources)}")

        for collection_name in sorted(deleted_sources):
            # These collections are no longer in config at all, safe to delete

            # Try to find and delete this collection from Plex
            deleted = False
            for library_name in enabled_libraries:
                try:
                    library = server.library.section(library_name)
                    # Check if collection exists
                    for coll in library.collections():
                        if coll.title == collection_name:
                            logger.info(f"Deleting collection '{collection_name}' from Plex library '{library_name}' (removed from config)")
                            coll.delete()
                            deleted = True
                            deleted_from_plex.append(collection_name)
                            break
                except Exception as e:
                    logger.warning(f"Error checking/deleting collection '{collection_name}' in library '{library_name}': {e}")

            if not deleted:
                logger.debug(f"Collection '{collection_name}' not found in Plex (may have been manually deleted)")
    else:
        logger.info("No deleted integration sources found - all previously managed collections are still in config")

    # Since we now preserve collections that are in groups (manual collections),
    # we no longer need to auto-update the config to remove orphaned references.
    # Collections are only deleted if they're completely removed from both
    # integration sources AND groups.
    config_updated = False

    return {
        'deleted_from_plex': deleted_from_plex,
        'orphaned_in_groups': orphaned_in_groups,
        'config_updated': config_updated,
    }


def _visibility_needs_update(hub, home: bool, shared: bool, recommended: bool) -> bool:
    # Plex re-appends a hub to the end of the managed list on every updateVisibility call,
    # even when the state hasn't changed. Only call updateVisibility when state actually differs.
    current_home = bool(getattr(hub, "promotedToOwnHome", False))
    current_shared = bool(getattr(hub, "promotedToSharedHome", False))
    current_recommended = bool(getattr(hub, "promotedToRecommended", False))
    logger.debug(
        "_visibility_needs_update '%s': current=(home=%s shared=%s recommended=%s) desired=(home=%s shared=%s recommended=%s)",
        getattr(hub, "title", "?"),
        current_home, current_shared, current_recommended,
        home, shared, recommended,
    )
    return current_home != home or current_shared != shared or current_recommended != recommended


def _suppress_managed_hub(hub_vis) -> str:
    # Fully drop an HSH-managed collection from the library's Managed
    # Recommendations rather than only clearing its visibility flags.
    #
    # updateVisibility(False, False, False) flips the promoted flags but leaves
    # the ManagedHub entry in place (_promoted stays True, all flags False). The
    # entry then lingers in managedHubs() forever, bloating LibraryHubOrder and
    # the group-adjacency machinery until oversized groups defeat the chained
    # moves (float-precision convergence). ManagedHub.remove() deletes the entry
    # so the collection leaves managedHubs() until it is promoted again.
    #
    # Only custom collections are removed; default system hubs
    # (movie.recentlyadded, recent.library.playlists, ...) are left untouched
    # even though Plex reports them deletable. Returns "removed" | "demoted" | "noop".
    identifier = str(getattr(hub_vis, "identifier", "") or "")
    if getattr(hub_vis, "_promoted", False) and identifier.startswith("custom.collection"):
        try:
            hub_vis.remove()
            return "removed"
        except Exception as e:
            # Fall back to a plain demote so visibility is still cleared.
            logger.warning("remove() failed for managed hub '%s': %s — falling back to demote",
                           getattr(hub_vis, "title", identifier), e)
    if _visibility_needs_update(hub_vis, False, False, False):
        hub_vis.updateVisibility(home=False, shared=False, recommended=False)
        return "demoted"
    return "noop"


def apply_home_screen_selection(
    server: PlexServer,
    config: AppConfig,
    selected_collections: Iterable[CollectionRef],
    collection_visibility: Dict[CollectionRef, Dict[str, bool]],
    *,
    dry_run: bool = False,
    smart_group_collections: Optional[Dict[str, List[CollectionRef]]] = None,
    collection_sort: Optional[Dict[CollectionRef, str]] = None,
) -> List[CollectionRef]:
    # Apply the chosen collections to the Plex Home screen.
    #
    # Strategy:
    #   - Build the union of all configured + previously rotated + selected collection names
    #   - Fetch those collections from all enabled Plex libraries
    #   - For each collection name and its library instances:
    #       - If a CollectionRef for that name is selected → enable visibility on the matching
    #         library instance, disable all other instances for that name
    #       - Else → disable all instances
    #
    # Returns the list of CollectionRefs that were (or would be) set to show on Home.

    from ..db.history import get_rotation_history_context

    enabled_libraries = [lib.name for lib in config.plex.libraries if lib.enabled]

    if not enabled_libraries:
        logger.warning("No enabled libraries configured for rotation")
        return []

    selected_set: Set[CollectionRef] = set(selected_collections)

    # Group selected refs by name so we can match the right library instance below.
    # Multiple refs with the same name (different libraries) are all supported.
    selected_refs_by_name: Dict[str, Set[CollectionRef]] = defaultdict(set)
    for ref in selected_set:
        selected_refs_by_name[ref.name].add(ref)

    configured_refs = get_configured_collections(config, smart_group_collections)
    configured_name_strings: Set[str] = {r.name for r in configured_refs}

    _, usage_map = get_rotation_history_context()
    # Track previously managed instances by full (library, name) so we don't disable
    # collections in libraries we've never actually rotated into.
    previously_rotated_refs: Set[Tuple[str, str]] = {(r.library, r.name) for r in usage_map.keys()}
    previously_rotated_names: Set[str] = {n for _, n in previously_rotated_refs}

    # Libraries scoped for cleanup: only libraries that have at least one
    # currently-configured collection OR a currently-selected collection.
    # If no active group manages a library, leave its collections alone,
    # even if we managed it in the past.
    active_libraries: Set[str] = (
        {r.library for r in configured_refs if r.library}
        | {r.library for r in selected_set if r.library}
    )

    # Process all names we care about (configured + rotated history + currently selected)
    all_names_to_process: Set[str] = (
        configured_name_strings
        | previously_rotated_names
        | {r.name for r in selected_set}
    )

    # Fetch all instances per library: {name: [(library_name, collection_obj), ...]}
    all_instances: Dict[str, List] = {}
    for library_name in enabled_libraries:
        logger.info("Fetching collections from library: %s", library_name)
        try:
            library_collections = get_library_collections(server, library_name)
            for coll_name, coll_obj in library_collections.items():
                all_instances.setdefault(coll_name, []).append((library_name, coll_obj))
        except Exception as e:
            logger.error("Failed to fetch collections from library '%s': %s", library_name, e)
            continue

    applied: List[CollectionRef] = []
    removed_count = 0

    logger.info(
        "Applying home screen selection to %d total collections (%d configured, %d previously rotated) across %d libraries (dry_run=%s)",
        len(all_names_to_process),
        len(configured_refs),
        len(previously_rotated_names),
        len(enabled_libraries),
        dry_run,
    )

    from ..db import get_pinned_collections
    pinned_db = get_pinned_collections()
    pinned_order: Dict[str, int] = {p.collection_name: p.display_order for p in pinned_db}
    # Map name → set of libraries it's pinned in (same name can be pinned in multiple libraries)
    pinned_libraries: Dict[str, Set[str]] = defaultdict(set)
    for p in pinned_db:
        pinned_libraries[p.collection_name].add(p.library_name)
    pinned_names: Set[str] = set(pinned_order.keys())

    # Promote selected collections in their intended display order (which honors
    # each group's collection_order — e.g. random for the Home Screen group)
    # rather than alphabetically. Plex appends newly-promoted hubs to the managed
    # list in promotion order, so this is what fixes the persisted within-group
    # order: previously sort_key fell back to alphabetical (1, 0, name), which
    # forced groups to display A→Z regardless of collection_order=random.
    # Unselected/demoted names are not in this map and trail (their order is
    # irrelevant — they are being removed).
    from ..rotation import order_collections_for_display
    _pin_refs = {CollectionRef(library=p.library_name, name=p.collection_name) for p in pinned_db}
    _pin_order_refs = {CollectionRef(library=p.library_name, name=p.collection_name): p.display_order for p in pinned_db}
    _pin_pos_refs = {CollectionRef(library=p.library_name, name=p.collection_name): p.pin_position for p in pinned_db}
    ordered_selected = order_collections_for_display(
        list(selected_set),
        config,
        pinned_names=_pin_refs,
        pinned_order=_pin_order_refs,
        smart_group_collections=smart_group_collections,
        pinned_positions=_pin_pos_refs,
    )
    promote_order_index: Dict[str, int] = {}
    for i, ref in enumerate(ordered_selected):
        promote_order_index.setdefault(ref.name, i)

    def sort_key(name: str) -> tuple:
        if name in pinned_names:
            return (0, pinned_order[name], name)
        return (1, promote_order_index.get(name, len(promote_order_index)), name)

    for name in sorted(all_names_to_process, key=sort_key):
        instances = all_instances.get(name)
        if not instances:
            if name in configured_name_strings:
                logger.warning("Configured collection not found in any enabled Plex library: %s", name)
            continue

        selected_name_refs = selected_refs_by_name.get(name)

        if selected_name_refs:
            for lib, coll in instances:
                hub = coll.visibility()

                # Find the CollectionRef that matches this specific library instance.
                # Refs with library="" (legacy migrated records) match the first instance.
                matching_ref = next(
                    (r for r in selected_name_refs if r.library == lib),
                    None,
                )
                if matching_ref is None and any(r.library == "" for r in selected_name_refs):
                    # Legacy ref with no library info — match the first available instance
                    if lib == instances[0][0]:
                        matching_ref = next(r for r in selected_name_refs if r.library == "")

                # Pinned collections override: a name can be pinned in multiple libraries
                if name in pinned_names:
                    is_pinned_lib = lib in pinned_libraries.get(name, set())
                    if is_pinned_lib:
                        # Use the ref for this specific library to get the right visibility settings
                        lib_ref = next((r for r in selected_name_refs if r.library == lib), None)
                        if lib_ref is None:
                            lib_ref = next((r for r in selected_name_refs), None)
                        if lib_ref:
                            visibility = collection_visibility.get(lib_ref, {"home": True, "shared": False, "recommended": False})
                            desired_home = visibility.get("home", True)
                            desired_shared = visibility.get("shared", False)
                            desired_recommended = visibility.get("recommended", False)
                            logger.info(
                                "Enabling visibility for pinned collection '%s' (lib=%s): home=%s, shared=%s, recommended=%s",
                                name, lib,
                                desired_home, desired_shared, desired_recommended,
                            )
                            if not dry_run:
                                if _visibility_needs_update(hub, desired_home, desired_shared, desired_recommended):
                                    hub.updateVisibility(home=desired_home, shared=desired_shared, recommended=desired_recommended)
                                else:
                                    logger.info("Skipping visibility update for pinned '%s' (lib=%s) — already correct", name, lib)
                        continue
                    else:
                        logger.debug("Suppressing non-pinned library instance of '%s' (lib=%s)", name, lib)
                        if not dry_run:
                            _suppress_managed_hub(hub)
                        continue

                if matching_ref is not None:
                    visibility = collection_visibility.get(matching_ref, {"home": True, "shared": False, "recommended": False})
                    desired_home = visibility.get("home", True)
                    desired_shared = visibility.get("shared", False)
                    desired_recommended = visibility.get("recommended", False)
                    logger.info(
                        "Enabling visibility for collection '%s' (lib=%s): home=%s, shared=%s, recommended=%s",
                        name, lib,
                        desired_home, desired_shared, desired_recommended,
                    )
                    if not dry_run:
                        if _visibility_needs_update(hub, desired_home, desired_shared, desired_recommended):
                            hub.updateVisibility(home=desired_home, shared=desired_shared, recommended=desired_recommended)
                        else:
                            logger.info("Skipping visibility update for '%s' (lib=%s) — already correct", name, lib)
                        if collection_sort and matching_ref in collection_sort:
                            try:
                                coll.sortUpdate(sort=collection_sort[matching_ref])
                                logger.debug("Set sort order for '%s' to '%s'", name, collection_sort[matching_ref])
                            except Exception:
                                logger.warning("Failed to update sort for '%s' (may be a smart collection)", name)
                else:
                    # No selected ref for this library instance. Only suppress if we manage
                    # this library; otherwise leave it untouched.
                    if lib not in active_libraries:
                        logger.debug("Skipping '%s' in unmanaged library '%s'", name, lib)
                        continue
                    logger.debug("Suppressing unselected library instance of '%s' (lib=%s)", name, lib)
                    if not dry_run:
                        _suppress_managed_hub(hub)

            # Track applied refs (all selected refs for this name that had instances)
            for ref in selected_name_refs:
                if any(lib == ref.library for lib, _ in instances) or (ref.library == "" and instances):
                    applied.append(ref)
        else:
            # Not selected: drop matching instances from Managed Recommendations,
            # but only where we manage the library AND only specific (lib, name)
            # instances we've previously rotated or have configured.
            configured_pairs: Set[Tuple[str, str]] = {(r.library, r.name) for r in configured_refs}
            for _lib, coll in instances:
                if _lib not in active_libraries:
                    logger.debug("Skipping '%s' in unmanaged library '%s'", name, _lib)
                    continue
                pair = (_lib, name)
                if pair not in previously_rotated_refs and pair not in configured_pairs:
                    # We've never managed this (lib, name) — leave it alone
                    logger.debug("Leaving unmanaged collection '%s' (lib=%s) untouched", name, _lib)
                    continue
                if pair in previously_rotated_refs and pair not in configured_pairs:
                    logger.debug("Removing previously managed collection (removed from config): %s (lib=%s)", name, _lib)
                else:
                    logger.debug("Removing unselected collection from managed recs: %s (lib=%s)", name, _lib)
                if not dry_run:
                    if _suppress_managed_hub(coll.visibility()) == "removed":
                        removed_count += 1

    logger.info(
        "Home screen selection applied; %d collections enabled, %d removed from managed recs, %d collections processed",
        len(applied),
        removed_count,
        len(all_names_to_process),
    )

    if dry_run:
        logger.info("Dry run — no changes were sent to Plex")

    # Ordering is no longer applied here. The service layer calls
    # hub_sync.sync_library_hub_order(...) per library after rotation; that path
    # uses LibraryHubOrder as the canonical per-library order (slot-in algorithm
    # for new hubs, pin top/bottom enforced, full-list reorder to Plex).
    return applied


def _get_managed_hubs_for_library(server: PlexServer, library_name: str) -> List[Any]:
    library = server.library.section(library_name)
    return [hub for hub in library.managedHubs() if hasattr(hub, "title")]


# Settle time after a visibility change before re-querying managedHubs.
# Plex needs a moment to update the managed list; without this the next
# call can return stale state.
_VISIBILITY_SETTLE_SECONDS = 0.5


# Identifiers of the "Recently Added" managedHub that sits at position 0
# by default in fresh libraries. Used as the pin-top anchor so the pinned
# hub lands at managedHubs[1], allowing Continue Watching to render above
# it (Plex renders a custom collection at managedHubs[0] above CW; a system
# hub at managedHubs[0] renders below CW).
_RECENTLY_ADDED_ANCHOR_BY_LIB_TYPE = {
    "movie": "movie.recentlyadded",
    "show": "tv.recentlyadded",
}


def pin_hub_to_top(
    server: PlexServer,
    library_name: str,
    hub_title: str,
) -> Optional[str]:
    # Pin to top means "first managed hub position" — but Plex renders a custom
    # collection at managedHubs[0] ABOVE Continue Watching. To keep CW at the
    # natural top of the Recommended tab, we land the pinned hub at
    # managedHubs[1] by anchoring after the library's default "Recently Added"
    # hub (tv.recentlyadded / movie.recentlyadded). Confirmed working on
    # TV Series; results may vary by library due to opaque Plex per-library
    # rendering state.
    #
    # Sequence:
    #   1. unpromote (clears managedHubs entry) + re-promote (fresh float at
    #      end) — defeats float-precision convergence after many moves
    #   2. move(after=anchor) — lands at managedHubs[1]
    #
    # If no anchor exists in managedHubs (rare), falls back to move(after=None)
    # which lands at position 0 (CW will render below the pinned hub).
    try:
        hubs = _get_managed_hubs_for_library(server, library_name)
    except Exception as e:
        return f"Could not load managed hubs for '{library_name}': {e}"

    hub = next((h for h in hubs if h.title == hub_title), None)
    if hub is None:
        return f"Hub '{hub_title}' not found in '{library_name}'"

    home = bool(getattr(hub, "promotedToOwnHome", False))
    shared = bool(getattr(hub, "promotedToSharedHome", False))
    recommended = bool(getattr(hub, "promotedToRecommended", False))

    if not (home or shared or recommended):
        return (
            f"Hub '{hub_title}' has no visibility flags set; "
            f"cannot pin to top without promotion"
        )

    try:
        hub.updateVisibility(home=False, shared=False, recommended=False)
        time.sleep(_VISIBILITY_SETTLE_SECONDS)
        hub.updateVisibility(home=home, shared=shared, recommended=recommended)
        time.sleep(_VISIBILITY_SETTLE_SECONDS)
    except Exception as e:
        return f"Visibility cycle failed for '{hub_title}': {e}"

    # Re-fetch — the hub instance is stale after visibility changes
    try:
        hubs_after = _get_managed_hubs_for_library(server, library_name)
    except Exception as e:
        return f"Could not reload hubs after re-promote in '{library_name}': {e}"

    target = next((h for h in hubs_after if h.title == hub_title), None)
    if target is None:
        return f"Hub '{hub_title}' did not return to managedHubs after re-promote"

    # Find the library type so we can pick the right anchor identifier.
    try:
        lib_type = server.library.section(library_name).type
    except Exception as e:
        return f"Could not load library section for '{library_name}': {e}"

    anchor_ident = _RECENTLY_ADDED_ANCHOR_BY_LIB_TYPE.get(lib_type)
    anchor = None
    if anchor_ident is not None:
        anchor = next((h for h in hubs_after if h.identifier == anchor_ident), None)

    try:
        target.move(after=anchor)
        if anchor is not None:
            logger.info(
                "pin_hub_to_top: re-promoted and pinned '%s' after '%s' in '%s' "
                "(home=%s shared=%s recommended=%s)",
                hub_title, anchor.title, library_name, home, shared, recommended,
            )
        else:
            logger.info(
                "pin_hub_to_top: re-promoted and pinned '%s' to top in '%s' — "
                "no '%s' anchor found, used move(after=None) "
                "(home=%s shared=%s recommended=%s)",
                hub_title, library_name, anchor_ident, home, shared, recommended,
            )
        return None
    except Exception as e:
        return f"Failed to move '{hub_title}' to top in '{library_name}': {e}"


def move_hub_after(
    server: PlexServer,
    library_name: str,
    hub_title: str,
    after_hub_title: Optional[str],
) -> Optional[str]:
    # Single PUT mirroring what Plex's own UI sends per drag.
    # after_hub_title=None means "move to literal position 0 of managedHubs".
    # Returns error message on failure, else None.
    #
    # Note on Continue Watching: in many Plex setups (esp. TV libraries) the
    # Continue Watching / On Deck hub is NOT part of managedHubs — Plex renders
    # it as a floating system row above the managed section. Pinning to position
    # 0 of managedHubs is the right behavior; CW floats above naturally.
    #
    # Why single-move-only: Plex's server does NOT reliably accept chained moves
    # attempting to enforce a global hub order — it rate-limits/re-normalizes between
    # rapid sequential calls. One drag = one PUT = the only working pattern.
    try:
        hubs = _get_managed_hubs_for_library(server, library_name)
    except Exception as e:
        return f"Could not load managed hubs for '{library_name}': {e}"

    hub_by_title = {h.title: h for h in hubs}

    target = hub_by_title.get(hub_title)
    if target is None:
        return f"Hub '{hub_title}' not found in '{library_name}'"

    after_hub = None
    if after_hub_title is not None:
        after_hub = hub_by_title.get(after_hub_title)
        if after_hub is None:
            return f"Anchor hub '{after_hub_title}' not found in '{library_name}'"

    try:
        target.move(after=after_hub)
        return None
    except Exception as e:
        return f"Failed to move '{hub_title}' in '{library_name}': {e}"


def _move_landed(hubs: List[Any], hub_title: str, after_hub_title: Optional[str]) -> bool:
    # True if hub_title currently sits immediately after after_hub_title
    # (or at position 0 when after_hub_title is None) in the given hub list.
    titles = [h.title for h in hubs]
    if hub_title not in titles:
        return False
    idx = titles.index(hub_title)
    if after_hub_title is None:
        return idx == 0
    if after_hub_title not in titles:
        return False
    return idx == titles.index(after_hub_title) + 1


def move_hub_after_verified(
    server: PlexServer,
    library_name: str,
    hub_title: str,
    after_hub_title: Optional[str],
) -> Optional[str]:
    # Like move_hub_after, but verifies the hub actually landed after its anchor
    # and recovers from Plex's float-precision convergence (see memory:
    # plex-hub-reorder-api). After many chained moves Plex's internal float
    # ordering loses precision and a move() silently fails to place the hub.
    #
    # Recovery mirrors pin_hub_to_top: unpromote + re-promote the hub (fresh
    # float spacing at the end of managedHubs) via a visibility cycle, then move
    # again. Only collections (hubs with visibility flags set) can be
    # re-promoted; smart/built-in hubs cannot, so for those we report the
    # failure rather than silently leaving them mis-placed.
    #
    # Returns None on success, else an error message.
    err = move_hub_after(server, library_name, hub_title, after_hub_title)
    if err:
        return err

    try:
        hubs = _get_managed_hubs_for_library(server, library_name)
    except Exception as e:
        return f"Could not reload hubs to verify move of '{hub_title}' in '{library_name}': {e}"

    if _move_landed(hubs, hub_title, after_hub_title):
        return None

    target = next((h for h in hubs if h.title == hub_title), None)
    if target is None:
        return f"Hub '{hub_title}' vanished from managedHubs during move in '{library_name}'"

    home = bool(getattr(target, "promotedToOwnHome", False))
    shared = bool(getattr(target, "promotedToSharedHome", False))
    recommended = bool(getattr(target, "promotedToRecommended", False))
    if not (home or shared or recommended):
        return (
            f"Move of '{hub_title}' did not land after '{after_hub_title}' in "
            f"'{library_name}' and the hub is not re-promotable (smart/built-in)"
        )

    # Re-promote to defeat float-precision convergence, then retry the move.
    try:
        target.updateVisibility(home=False, shared=False, recommended=False)
        time.sleep(_VISIBILITY_SETTLE_SECONDS)
        target.updateVisibility(home=home, shared=shared, recommended=recommended)
        time.sleep(_VISIBILITY_SETTLE_SECONDS)
    except Exception as e:
        return f"Visibility cycle failed during move recovery for '{hub_title}': {e}"

    err = move_hub_after(server, library_name, hub_title, after_hub_title)
    if err:
        return err

    try:
        hubs = _get_managed_hubs_for_library(server, library_name)
    except Exception as e:
        return f"Could not reload hubs to re-verify move of '{hub_title}' in '{library_name}': {e}"

    if _move_landed(hubs, hub_title, after_hub_title):
        logger.info(
            "move recovery succeeded: re-promoted '%s' and placed after '%s' in '%s'",
            hub_title, after_hub_title, library_name,
        )
        return None

    return (
        f"precision convergence: '{hub_title}' would not stay after "
        f"'{after_hub_title}' in '{library_name}' even after re-promote"
    )




# Home user functions for watch history copying

def get_recently_added(server: PlexServer, config: AppConfig, limit: int = 10) -> List[Dict[str, Any]]:
    # Fetch recently added items across all enabled Plex libraries.
    # Returns a flat list sorted by addedAt (newest first), limited to `limit` items.
    from ..poster_proxy import create_proxy_url

    enabled_libraries = [lib.name for lib in config.plex.libraries if lib.enabled]
    all_items: List[Dict[str, Any]] = []

    for library_name in enabled_libraries:
        try:
            library = server.library.section(library_name)
            recent = library.recentlyAdded(maxresults=limit)

            for item in recent:
                thumb = None
                if getattr(item, "thumb", None):
                    try:
                        full_url = server.url(item.thumb, includeToken=True)
                        plex_url = server.transcodeImage(full_url, height=450, width=300, minSize=1)
                        thumb = create_proxy_url(plex_url)
                    except Exception:
                        thumb = None

                media_type = getattr(item, "type", "unknown")

                all_items.append({
                    "title": item.title,
                    "year": getattr(item, "year", None),
                    "added_at": item.addedAt.isoformat() if item.addedAt else None,
                    "thumb": thumb,
                    "media_type": media_type,
                    "rating_key": str(item.ratingKey),
                    "library": library_name,
                })
        except Exception as e:
            logger.warning("Failed to fetch recently added from '%s': %s", library_name, e)

    # Sort by added_at descending and trim to limit
    all_items.sort(key=lambda x: x["added_at"] or "", reverse=True)
    return all_items[:limit]


def get_plex_account(config: AppConfig) -> MyPlexAccount:
    # Create MyPlexAccount from configured token for home user access
    # This requires a Plex.tv account token, not a local server token
    return MyPlexAccount(token=config.plex.token)


def get_all_plex_users(config: AppConfig) -> List[Dict[str, Any]]:
    # Return all Plex users (friends + home) with id, username, title, thumb, is_home, is_admin
    # Used by user targeting to compute exclusion sets
    account = get_plex_account(config)
    users = []

    # Admin account
    users.append({
        "id": account.id,
        "username": account.username or account.title,
        "title": account.title or account.username,
        "thumb": account.thumb,
        "is_home": True,
        "is_admin": True,
    })

    skipped = 0
    for user in account.users():
        # Skip users with no active server access (old/removed friends, pending invites)
        servers = getattr(user, "servers", []) or []
        if not servers or all(getattr(s, "pending", False) for s in servers):
            skipped += 1
            continue

        username = getattr(user, "username", "") or ""
        title = getattr(user, "title", "") or ""
        users.append({
            "id": user.id,
            "username": username or title,  # Fall back to title for managed users
            "title": title or username,
            "thumb": getattr(user, "thumb", None),
            "is_home": bool(getattr(user, "home", False)),
            "is_admin": False,
        })

    if skipped:
        logger.debug(f"Skipped {skipped} users with no active server access")
    logger.debug(f"Found {len(users)} total Plex users")
    return users


def get_home_users(config: AppConfig) -> List[Dict[str, Any]]:
    # Return list of home users with id, username, title, thumb, is_admin
    account = get_plex_account(config)
    users = []

    # Include server owner account (unsure how I plan to handle admin account labels, will come back)
    users.append({
        "id": account.id,
        "username": account.title or account.username,
        "title": account.title or account.username,
        "thumb": account.thumb,
        "is_admin": True,
    })

    # Add managed/home users (filter out friends - only include home users)
    for user in account.users():
        if user.home:
            users.append({
                "id": user.id,
                "username": user.title or user.username,  # Use title as username for managed users
                "title": user.title or user.username,
                "thumb": user.thumb,
                "is_admin": False,
            })

    logger.debug(f"Found {len(users)} home users")
    return users


def get_server_for_user(config: AppConfig, username: str) -> PlexServer:
    # Get PlexServer authenticated as a specific home user
    account = get_plex_account(config)

    # Just return normal server if it's my admin account
    if username == account.username or username == account.title:
        return get_plex_server(config)

    # Switch to the home user
    logger.debug(f"Switching to home user: {username}")
    user_account = account.switchHomeUser(username)

    for resource in user_account.resources():
        if resource.product == "Plex Media Server":
            try:
                logger.debug(f"Connecting to server as {username} via resource")
                return resource.connect(timeout=30)
            except Exception as e:
                logger.warning(f"Failed to connect via resource: {e}")
                try:
                    logger.debug(f"Retrying with configured base_url")
                    return PlexServer(config.plex.base_url, resource.accessToken, session=_make_session())
                except Exception as e2:
                    logger.error(f"Failed with configured base_url: {e2}")
                    raise

    raise ValueError(f"Could not find Plex server for user '{username}'")
