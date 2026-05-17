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
    delete_hub,
    get_library_hub_order,
    set_library_hub_order,
    slot_in_hub,
    upsert_hub,
)
from .integrations.plex_client import (
    _get_managed_hubs_for_library,
    reorder_library_hubs_full,
)

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


def sync_library_hub_order(
    server: PlexServer,
    config: AppConfig,
    library_name: str,
    *,
    smart_group_collections: Optional[Dict[str, List[CollectionRef]]] = None,
    push_to_plex: bool = False,
) -> SyncResult:
    # Reconcile LibraryHubOrder DB rows with Plex's actual managed hubs for this library.
    # If push_to_plex=True, also push the resulting DB order to Plex via reorder_library_hubs_full.
    result = SyncResult(library_name=library_name)

    try:
        plex_hubs = _get_managed_hubs_for_library(server, library_name)
    except Exception as e:
        logger.warning("sync_library_hub_order: could not load hubs for '%s': %s", library_name, e)
        return result

    plex_titles = [hub.title for hub in plex_hubs]
    plex_hub_by_title = {hub.title: hub for hub in plex_hubs}

    configured_groups = _build_collection_to_group_map(config, smart_group_collections)
    configured_keys = set(configured_groups.keys())

    existing_rows = get_library_hub_order(library_name)
    existing_titles = {r.hub_title for r in existing_rows}

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

    # 3) Push to Plex if requested
    if push_to_plex:
        ordered_rows = get_library_hub_order(library_name)
        target_titles = [r.hub_title for r in ordered_rows]
        # Apply pin overrides: pinned-top moves to start, pinned-bottom to end
        pinned_top = [r.hub_title for r in ordered_rows if r.pin_position == "top"]
        pinned_bottom = [r.hub_title for r in ordered_rows if r.pin_position == "bottom"]
        middle = [
            t for t in target_titles
            if t not in pinned_top and t not in pinned_bottom
        ]
        final = pinned_top + middle + pinned_bottom
        _, errors = reorder_library_hubs_full(server, library_name, final)
        result.plex_reorder_errors.extend(errors)

    logger.info(
        "sync: library '%s' done. added=%d removed=%d updated=%d errors=%d",
        library_name,
        len(result.added),
        len(result.removed),
        len(result.updated),
        len(result.plex_reorder_errors),
    )
    return result


def sync_all_libraries(
    server: PlexServer,
    config: AppConfig,
    *,
    smart_group_collections: Optional[Dict[str, List[CollectionRef]]] = None,
    push_to_plex: bool = False,
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
                push_to_plex=push_to_plex,
            )
        )
    return results


def apply_saved_order_to_plex(
    server: PlexServer,
    library_name: str,
) -> Tuple[List[str], List[str]]:
    # Push the DB order to Plex for a single library, respecting pin positions.
    ordered_rows = get_library_hub_order(library_name)
    pinned_top = [r.hub_title for r in ordered_rows if r.pin_position == "top"]
    pinned_bottom = [r.hub_title for r in ordered_rows if r.pin_position == "bottom"]
    middle = [
        r.hub_title for r in ordered_rows
        if r.pin_position not in ("top", "bottom")
    ]
    final = pinned_top + middle + pinned_bottom
    final_order, errors = reorder_library_hubs_full(server, library_name, final)
    return final_order, errors


def save_library_hub_order(
    library_name: str,
    ordered_hub_titles: List[str],
) -> None:
    # Write user's drag-reordered hub list to DB.
    set_library_hub_order(library_name, ordered_hub_titles)
