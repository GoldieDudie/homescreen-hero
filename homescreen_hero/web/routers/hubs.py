from __future__ import annotations

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from homescreen_hero.core.auth import CurrentUser, require_admin
from homescreen_hero.core.config.loader import load_config
from homescreen_hero.core.db import (
    HUB_TYPE_COLLECTION,
    HUB_TYPE_EXTERNAL,
    HUB_TYPE_SMART_HUB,
    PIN_BOTTOM,
    PIN_TOP,
    get_library_hub_order,
    init_db,
    set_library_hub_order,
    set_pin,
)
from homescreen_hero.core.hub_sync import (
    apply_saved_order_to_plex,
    sync_library_hub_order,
)
from homescreen_hero.core.integrations.plex_client import (
    _get_managed_hubs_for_library,
    get_plex_server,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/libraries", tags=["hubs"])


# ---- response/request models ----

class HubOut(BaseModel):
    title: str
    position: int
    hub_type: str  # collection | smart_hub | external
    group_name: Optional[str] = None
    pin_position: Optional[str] = None  # top | bottom | null
    # Current Plex visibility (populated by /sync and /batch responses; omitted in GET)
    promoted_to_own_home: Optional[bool] = None
    promoted_to_shared_home: Optional[bool] = None
    promoted_to_recommended: Optional[bool] = None
    # True when user can edit visibility from dashboard (external + smart_hub only)
    visibility_editable: bool = False


class LibraryHubsResponse(BaseModel):
    library_name: str
    hubs: List[HubOut]


class EnabledLibrary(BaseModel):
    name: str
    enabled: bool
    type: Optional[str] = None  # "movie" | "show" — best-effort, may be None


class EnabledLibrariesResponse(BaseModel):
    libraries: List[EnabledLibrary]


class SyncResponse(BaseModel):
    library_name: str
    hubs: List[HubOut]
    added: List[str] = Field(default_factory=list)
    removed: List[str] = Field(default_factory=list)
    plex_reorder_errors: List[str] = Field(default_factory=list)


class PinSetting(BaseModel):
    top: Optional[str] = None
    bottom: Optional[str] = None


class VisibilityChange(BaseModel):
    hub_title: str
    home: bool
    shared: bool
    recommended: bool


class BatchSaveRequest(BaseModel):
    ordered_hub_titles: List[str]
    pins: PinSetting = Field(default_factory=PinSetting)
    visibility_changes: List[VisibilityChange] = Field(default_factory=list)


class BatchSaveResponse(BaseModel):
    library_name: str
    hubs: List[HubOut]
    plex_reorder_errors: List[str] = Field(default_factory=list)
    visibility_errors: List[str] = Field(default_factory=list)


# ---- helpers ----

def _validate_library(library_name: str) -> None:
    config = load_config()
    enabled = {lib.name for lib in config.plex.libraries if lib.enabled}
    if library_name not in enabled:
        raise HTTPException(
            status_code=404,
            detail=f"Library '{library_name}' is not enabled or does not exist",
        )


def _rows_to_hubs(rows, plex_hub_by_title: Optional[Dict] = None) -> List[HubOut]:
    out: List[HubOut] = []
    for r in rows:
        visibility_editable = r.hub_type in (HUB_TYPE_EXTERNAL, HUB_TYPE_SMART_HUB)
        hub_data = {
            "title": r.hub_title,
            "position": r.position,
            "hub_type": r.hub_type,
            "group_name": r.group_name,
            "pin_position": r.pin_position,
            "visibility_editable": visibility_editable,
        }
        if plex_hub_by_title is not None:
            plex_hub = plex_hub_by_title.get(r.hub_title)
            if plex_hub is not None:
                hub_data["promoted_to_own_home"] = bool(getattr(plex_hub, "promotedToOwnHome", False))
                hub_data["promoted_to_shared_home"] = bool(getattr(plex_hub, "promotedToSharedHome", False))
                hub_data["promoted_to_recommended"] = bool(getattr(plex_hub, "promotedToRecommended", False))
        out.append(HubOut(**hub_data))
    return out


# ---- endpoints ----

@router.get("", response_model=EnabledLibrariesResponse)
def list_enabled_libraries(
    _current_user: CurrentUser = Depends(require_admin),
) -> EnabledLibrariesResponse:
    config = load_config()
    libs: List[EnabledLibrary] = []
    for lib in config.plex.libraries:
        libs.append(EnabledLibrary(
            name=lib.name,
            enabled=lib.enabled,
            type=getattr(lib, "type", None),
        ))
    return EnabledLibrariesResponse(libraries=libs)


@router.get("/{library_name}/hubs", response_model=LibraryHubsResponse)
def get_library_hubs(
    library_name: str,
    _current_user: CurrentUser = Depends(require_admin),
) -> LibraryHubsResponse:
    # Fast DB-only read. Use /sync to refresh from Plex.
    init_db()
    _validate_library(library_name)
    rows = get_library_hub_order(library_name)
    return LibraryHubsResponse(
        library_name=library_name,
        hubs=_rows_to_hubs(rows),
    )


@router.post("/{library_name}/hubs/sync", response_model=SyncResponse)
def sync_hubs(
    library_name: str,
    push_to_plex: bool = False,
    _current_user: CurrentUser = Depends(require_admin),
) -> SyncResponse:
    init_db()
    _validate_library(library_name)
    config = load_config()
    server = get_plex_server(config)

    # Smart groups are resolved here when needed by config — for sync we just want
    # to know which (lib, title) pairs are HSH-managed. Smart-resolved refs come
    # from service._resolve_smart_groups, which requires runtime metadata.
    # For sync, we conservatively use only explicitly-configured (non-smart) refs;
    # smart-group hubs not yet present in DB will be classified as "external" until
    # a rotation runs. This is fine as a fallback and self-corrects after rotation.
    sync_result = sync_library_hub_order(
        server,
        config,
        library_name,
        smart_group_collections=None,
        push_to_plex=push_to_plex,
    )

    rows = get_library_hub_order(library_name)
    plex_hub_by_title = {hub.title: hub for hub in _get_managed_hubs_for_library(server, library_name)}
    return SyncResponse(
        library_name=library_name,
        hubs=_rows_to_hubs(rows, plex_hub_by_title=plex_hub_by_title),
        added=sync_result.added,
        removed=sync_result.removed,
        plex_reorder_errors=sync_result.plex_reorder_errors,
    )


@router.post("/{library_name}/hubs/batch", response_model=BatchSaveResponse)
def batch_save(
    library_name: str,
    request: BatchSaveRequest,
    _current_user: CurrentUser = Depends(require_admin),
) -> BatchSaveResponse:
    # Apply dashboard pending edits in one atomic-ish operation:
    #   1. Persist new hub order in DB
    #   2. Apply pin changes (1 top + 1 bottom max per library)
    #   3. Apply visibility changes via Plex API (only on non-HSH-managed hubs)
    #   4. Push final order to Plex
    init_db()
    _validate_library(library_name)
    config = load_config()
    server = get_plex_server(config)

    existing_rows = get_library_hub_order(library_name)
    existing_by_title = {r.hub_title: r for r in existing_rows}

    # Validate: every requested hub_title must exist in DB
    payload_titles = set(request.ordered_hub_titles)
    unknown = payload_titles - set(existing_by_title.keys())
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown hubs in library '{library_name}': {sorted(unknown)}",
        )

    # Validate visibility changes — only allowed on external + smart_hub
    visibility_errors: List[str] = []
    for change in request.visibility_changes:
        row = existing_by_title.get(change.hub_title)
        if row is None:
            visibility_errors.append(f"Unknown hub for visibility change: {change.hub_title}")
            continue
        if row.hub_type == HUB_TYPE_COLLECTION:
            visibility_errors.append(
                f"Cannot edit visibility for HSH-managed collection '{change.hub_title}' from dashboard"
            )
            continue

    # 1. Reorder DB
    set_library_hub_order(library_name, request.ordered_hub_titles)

    # 2. Pin changes
    new_top = request.pins.top
    new_bottom = request.pins.bottom
    current_top = next((r.hub_title for r in existing_rows if r.pin_position == PIN_TOP), None)
    current_bottom = next((r.hub_title for r in existing_rows if r.pin_position == PIN_BOTTOM), None)

    if new_top != current_top:
        if current_top is not None and current_top != new_top:
            set_pin(library_name, current_top, None)
        if new_top is not None:
            set_pin(library_name, new_top, PIN_TOP)
    if new_bottom != current_bottom:
        if current_bottom is not None and current_bottom != new_bottom:
            set_pin(library_name, current_bottom, None)
        if new_bottom is not None:
            set_pin(library_name, new_bottom, PIN_BOTTOM)

    # 3. Visibility changes (Plex API) — only valid ones
    plex_hubs = _get_managed_hubs_for_library(server, library_name)
    plex_hub_by_title = {hub.title: hub for hub in plex_hubs}

    for change in request.visibility_changes:
        row = existing_by_title.get(change.hub_title)
        if row is None or row.hub_type == HUB_TYPE_COLLECTION:
            continue  # already errored above
        hub = plex_hub_by_title.get(change.hub_title)
        if hub is None:
            visibility_errors.append(f"Hub '{change.hub_title}' not found in Plex")
            continue
        try:
            hub.updateVisibility(
                home=change.home,
                shared=change.shared,
                recommended=change.recommended,
            )
            logger.info(
                "Updated visibility for '%s' in '%s': home=%s shared=%s recommended=%s",
                change.hub_title,
                library_name,
                change.home,
                change.shared,
                change.recommended,
            )
        except Exception as e:
            visibility_errors.append(f"Failed to update visibility for '{change.hub_title}': {e}")
            logger.warning(visibility_errors[-1])

    # 4. Push order to Plex (DB now has final order + pins; apply respects pins)
    _, reorder_errors = apply_saved_order_to_plex(server, library_name)

    # 5. Re-read final state for response
    final_rows = get_library_hub_order(library_name)
    plex_hubs_after = _get_managed_hubs_for_library(server, library_name)
    plex_hub_by_title_after = {hub.title: hub for hub in plex_hubs_after}

    return BatchSaveResponse(
        library_name=library_name,
        hubs=_rows_to_hubs(final_rows, plex_hub_by_title=plex_hub_by_title_after),
        plex_reorder_errors=reorder_errors,
        visibility_errors=visibility_errors,
    )
