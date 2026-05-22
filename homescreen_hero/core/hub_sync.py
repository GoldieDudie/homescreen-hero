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
from .integrations.plex_client import _get_managed_hubs_for_library

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
    # DB-only — does NOT push the resulting order to Plex (Plex's reorder API does not
    # reliably accept chained moves; user-driven single moves go through the /hubs/move
    # endpoint instead).
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

    # 4) Align DB positions to Plex's current order. Plex is the source of truth
    # for hub ordering — any reorder we did via /hubs/move already updated Plex,
    # so re-reading Plex here doesn't clobber user changes.
    set_library_hub_order(library_name, plex_titles)

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
