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

_REORDER_MOVE_DELAY_SECONDS = 0.2
_REORDER_SETTLE_DELAY_SECONDS = 0.35
_REORDER_MAX_ATTEMPTS = 2


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

    def sort_key(name: str) -> tuple:
        if name in pinned_names:
            return (0, pinned_order[name], name)
        return (1, 0, name)

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
                            logger.info(
                                "Enabling visibility for pinned collection '%s' (lib=%s): home=%s, shared=%s, recommended=%s",
                                name, lib,
                                visibility.get("home", True),
                                visibility.get("shared", False),
                                visibility.get("recommended", False),
                            )
                            if not dry_run:
                                hub.updateVisibility(
                                    home=visibility.get("home", True),
                                    shared=visibility.get("shared", False),
                                    recommended=visibility.get("recommended", False),
                                )
                        continue
                    else:
                        logger.debug("Suppressing non-pinned library instance of '%s' (lib=%s)", name, lib)
                        if not dry_run:
                            hub.updateVisibility(home=False, shared=False, recommended=False)
                        continue

                if matching_ref is not None:
                    visibility = collection_visibility.get(matching_ref, {"home": True, "shared": False, "recommended": False})
                    logger.info(
                        "Enabling visibility for collection '%s' (lib=%s): home=%s, shared=%s, recommended=%s",
                        name, lib,
                        visibility.get("home", True),
                        visibility.get("shared", False),
                        visibility.get("recommended", False),
                    )
                    if not dry_run:
                        hub.updateVisibility(
                            home=visibility.get("home", True),
                            shared=visibility.get("shared", False),
                            recommended=visibility.get("recommended", False),
                        )
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
                        hub.updateVisibility(home=False, shared=False, recommended=False)

            # Track applied refs (all selected refs for this name that had instances)
            for ref in selected_name_refs:
                if any(lib == ref.library for lib, _ in instances) or (ref.library == "" and instances):
                    applied.append(ref)
        else:
            # Not selected: disable matching instances, but only where we manage the library
            # AND only specific (lib, name) instances we've previously rotated or have configured.
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
                    logger.info("Disabling visibility for previously managed collection (removed from config): %s (lib=%s)", name, _lib)
                else:
                    logger.debug("Disabling visibility for collection: %s (lib=%s)", name, _lib)
                if not dry_run:
                    coll.visibility().updateVisibility(home=False, shared=False, recommended=False)

    logger.info(
        "Home screen selection applied; %d collections enabled, %d collections processed",
        len(applied),
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


def _get_target_hub_order_for_library(
    managed_hubs: List[Any],
    ordered_collection_names: List[str],
) -> List[str]:
    hub_titles = {hub.title for hub in managed_hubs}
    return [name for name in ordered_collection_names if name in hub_titles]


def _get_current_hub_order_for_library(
    server: PlexServer,
    library_name: str,
    target_names: List[str],
) -> List[str]:
    target_set = set(target_names)
    return [
        hub.title
        for hub in _get_managed_hubs_for_library(server, library_name)
        if hub.title in target_set
    ]


def _reorder_library_hubs(
    server: PlexServer,
    library_name: str,
    target_order: List[str],
) -> List[str]:
    if len(target_order) < 2:
        return list(target_order)

    current_order = _get_current_hub_order_for_library(server, library_name, target_order)
    if current_order == target_order:
        logger.debug(
            "Managed hub order already correct for '%s': %s",
            library_name,
            target_order,
        )
        return current_order

    # Move first item to top, then chain each subsequent item after the previous one.
    # This gives Plex an explicit anchor for each move rather than racing for position 0.
    for attempt in range(1, _REORDER_MAX_ATTEMPTS + 1):
        hub_map = {
            hub.title: hub
            for hub in _get_managed_hubs_for_library(server, library_name)
        }

        first_hub = hub_map.get(target_order[0])
        if first_hub is None:
            logger.warning(
                "First collection '%s' not found in managed hubs for '%s'",
                target_order[0],
                library_name,
            )
            break

        try:
            first_hub.move(after=None)
            logger.debug("Moved '%s' to top in '%s'", target_order[0], library_name)
        except Exception as e:
            logger.warning("Failed to move collection '%s' in '%s': %s", target_order[0], library_name, e)
            break

        prev_hub = first_hub
        for name in target_order[1:]:
            hub = hub_map.get(name)
            if hub is None:
                logger.debug(
                    "Skipping '%s' during reorder for '%s' - not found in managed hubs",
                    name,
                    library_name,
                )
                continue

            try:
                time.sleep(_REORDER_MOVE_DELAY_SECONDS)
                hub.move(after=prev_hub)
                logger.debug(
                    "Moved '%s' after '%s' in '%s' (attempt %d/%d)",
                    name,
                    prev_hub.title,
                    library_name,
                    attempt,
                    _REORDER_MAX_ATTEMPTS,
                )
                prev_hub = hub
            except Exception as e:
                logger.warning(
                    "Failed to move collection '%s' in '%s': %s",
                    name,
                    library_name,
                    e,
                )

        time.sleep(_REORDER_SETTLE_DELAY_SECONDS)
        current_order = _get_current_hub_order_for_library(
            server,
            library_name,
            target_order,
        )
        if current_order == target_order:
            logger.debug(
                "Verified managed hub order for '%s' on attempt %d/%d",
                library_name,
                attempt,
                _REORDER_MAX_ATTEMPTS,
            )
            return current_order

        logger.warning(
            "Managed hub order mismatch for '%s' after attempt %d/%d. "
            "Requested=%s Current=%s",
            library_name,
            attempt,
            _REORDER_MAX_ATTEMPTS,
            target_order,
            current_order,
        )

    return current_order


def reorder_homescreen_collections(
    server: PlexServer,
    config: AppConfig,
    ordered_collections: List[CollectionRef],
    *,
    dry_run: bool = False,
) -> List[str]:
    # Reorder collections on the Plex homescreen using ManagedHub.move().
    # Plex keeps libraries separate, so we reorder within each library.
    # Hub titles are collection names (strings), so we extract ref.name for API calls.
    ordered_names = [r.name for r in ordered_collections]
    enabled_libraries = [lib.name for lib in config.plex.libraries if lib.enabled]

    library_orders: Dict[str, List[str]] = {}
    total_hubs = 0
    for library_name in enabled_libraries:
        try:
            hubs = _get_managed_hubs_for_library(server, library_name)
            total_hubs += len(hubs)
            target_order = _get_target_hub_order_for_library(hubs, ordered_names)
            if target_order:
                library_orders[library_name] = target_order
        except Exception as e:
            logger.warning("Could not get managed hubs for library %s: %s", library_name, e)

    logger.debug(
        "Found %d managed hubs for reordering, requested order: %s",
        total_hubs,
        ordered_names,
    )

    if dry_run:
        logger.info("Dry run - would reorder collections: %s", ordered_names)
        return ordered_names

    applied_order: List[str] = []
    for library_name, target_order in library_orders.items():
        logger.debug("Reordering %d collections in '%s': %s", len(target_order), library_name, target_order)
        applied_order.extend(_reorder_library_hubs(server, library_name, target_order))

    if applied_order:
        logger.info("Reordered %d collections on homescreen", len(applied_order))

    return applied_order


def get_managed_hub_titles(server: PlexServer, library_name: str) -> List[str]:
    # Return current ordered list of managed hub titles for a library.
    # Includes user collections, smart hubs (e.g. Recently Added), and any other managed hub.
    try:
        return [hub.title for hub in _get_managed_hubs_for_library(server, library_name)]
    except Exception as e:
        logger.warning("Could not list managed hubs for '%s': %s", library_name, e)
        return []


def reorder_library_hubs_full(
    server: PlexServer,
    library_name: str,
    target_hub_titles: List[str],
    *,
    dry_run: bool = False,
) -> Tuple[List[str], List[str]]:
    # Full-list reorder for a single library. target_hub_titles is the desired ORDER
    # of all hubs we want to position in this library. Hubs present in Plex but missing
    # from target_hub_titles are left untouched (drift to end). Hubs in target that
    # don't exist in Plex are skipped silently.
    #
    # Returns (final_hub_order_in_plex, list_of_error_messages).
    if not target_hub_titles:
        return ([], [])

    errors: List[str] = []

    try:
        hubs = _get_managed_hubs_for_library(server, library_name)
    except Exception as e:
        msg = f"Could not load managed hubs for '{library_name}': {e}"
        logger.warning(msg)
        return ([], [msg])

    hub_by_title = {hub.title: hub for hub in hubs}
    target_present = [t for t in target_hub_titles if t in hub_by_title]
    missing_in_plex = [t for t in target_hub_titles if t not in hub_by_title]
    if missing_in_plex:
        logger.debug(
            "reorder_library_hubs_full: %d titles in target not found as hubs in '%s': %s",
            len(missing_in_plex),
            library_name,
            missing_in_plex,
        )

    current_order = [hub.title for hub in hubs if hub.title in set(target_present)]
    if current_order == target_present:
        logger.debug("Hub order already matches target for '%s'", library_name)
        return (current_order, [])

    if dry_run:
        logger.info(
            "Dry run reorder for '%s': would target %d hubs: %s",
            library_name,
            len(target_present),
            target_present,
        )
        return (target_present, [])

    final_order: List[str] = current_order
    for attempt in range(1, _REORDER_MAX_ATTEMPTS + 1):
        # Refresh hub instances each attempt (Plex may invalidate)
        hubs = _get_managed_hubs_for_library(server, library_name)
        hub_by_title = {hub.title: hub for hub in hubs}

        first_title = target_present[0]
        first_hub = hub_by_title.get(first_title)
        if first_hub is None:
            errors.append(f"First target hub '{first_title}' vanished in '{library_name}'")
            break

        try:
            first_hub.move(after=None)
            logger.debug("Moved '%s' to top in '%s'", first_title, library_name)
        except Exception as e:
            errors.append(f"Failed to move '{first_title}' to top in '{library_name}': {e}")
            logger.warning(errors[-1])
            break

        prev_hub = first_hub
        for title in target_present[1:]:
            hub = hub_by_title.get(title)
            if hub is None:
                continue
            try:
                time.sleep(_REORDER_MOVE_DELAY_SECONDS)
                hub.move(after=prev_hub)
                prev_hub = hub
            except Exception as e:
                # Smart hubs and some managed hubs may not support move().
                # Log + continue — that hub stays where Plex puts it.
                errors.append(f"Could not move '{title}' in '{library_name}': {e}")
                logger.warning(errors[-1])

        time.sleep(_REORDER_SETTLE_DELAY_SECONDS)
        hubs_after = _get_managed_hubs_for_library(server, library_name)
        final_order = [h.title for h in hubs_after if h.title in set(target_present)]
        if final_order == target_present:
            logger.debug(
                "Verified hub order for '%s' on attempt %d/%d",
                library_name,
                attempt,
                _REORDER_MAX_ATTEMPTS,
            )
            return (final_order, errors)

        logger.warning(
            "Hub order mismatch for '%s' after attempt %d/%d. Target=%s Current=%s",
            library_name,
            attempt,
            _REORDER_MAX_ATTEMPTS,
            target_present,
            final_order,
        )

    errors.append(
        f"Hub order did not converge for '{library_name}' after {_REORDER_MAX_ATTEMPTS} attempts"
    )
    return (final_order, errors)


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
