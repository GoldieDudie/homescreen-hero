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
from homescreen_hero.core.hub_sync import sync_library_hub_order
from homescreen_hero.core.integrations.plex_client import (
    _get_managed_hubs_for_library,
    get_plex_server,
    move_hub_after,
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
    # Current Plex visibility (populated by /sync response only; omitted in GET)
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


# Single-action request models (mirror Plex's UI: one user action = one server call)

class MoveHubRequest(BaseModel):
    hub_title: str
    after_hub_title: Optional[str] = None  # None = move to top


class MoveHubResponse(BaseModel):
    library_name: str
    hub_title: str
    error: Optional[str] = None


class VisibilityRequest(BaseModel):
    hub_title: str
    home: bool
    shared: bool
    recommended: bool


class VisibilityResponse(BaseModel):
    library_name: str
    hub_title: str
    home: bool
    shared: bool
    recommended: bool
    error: Optional[str] = None


class PinsRequest(BaseModel):
    top: Optional[str] = None
    bottom: Optional[str] = None


class PinsResponse(BaseModel):
    library_name: str
    top: Optional[str] = None
    bottom: Optional[str] = None


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


# ---- single-action endpoints (mirror Plex's UI: one user action = one server call) ----

@router.post("/{library_name}/hubs/move", response_model=MoveHubResponse)
def move_hub(
    library_name: str,
    request: MoveHubRequest,
    _current_user: CurrentUser = Depends(require_admin),
) -> MoveHubResponse:
    # Single drag = single PUT to Plex. Mirrors Plex Web's own behavior exactly.
    # Also persists the resulting DB order so it survives sync.
    init_db()
    _validate_library(library_name)
    config = load_config()
    server = get_plex_server(config)

    rows = get_library_hub_order(library_name)
    titles = [r.hub_title for r in rows]
    if request.hub_title not in titles:
        raise HTTPException(
            status_code=404,
            detail=f"Hub '{request.hub_title}' not found in '{library_name}'",
        )
    if request.after_hub_title is not None and request.after_hub_title not in titles:
        raise HTTPException(
            status_code=404,
            detail=f"Anchor hub '{request.after_hub_title}' not found in '{library_name}'",
        )

    # Push to Plex first; only persist DB order on success so the two stay aligned.
    error = move_hub_after(server, library_name, request.hub_title, request.after_hub_title)
    if error is None:
        remaining = [t for t in titles if t != request.hub_title]
        if request.after_hub_title is None:
            new_titles = [request.hub_title] + remaining
        else:
            anchor_idx = remaining.index(request.after_hub_title)
            new_titles = remaining[: anchor_idx + 1] + [request.hub_title] + remaining[anchor_idx + 1 :]
        set_library_hub_order(library_name, new_titles)
        logger.info(
            "Moved '%s' in '%s' after %s",
            request.hub_title,
            library_name,
            request.after_hub_title or "<top>",
        )

    return MoveHubResponse(
        library_name=library_name,
        hub_title=request.hub_title,
        error=error,
    )


@router.post("/{library_name}/hubs/visibility", response_model=VisibilityResponse)
def set_hub_visibility(
    library_name: str,
    request: VisibilityRequest,
    _current_user: CurrentUser = Depends(require_admin),
) -> VisibilityResponse:
    # Single visibility change. Body MUST send all three flags (Plex requires all
    # three on every call — partial updates would clobber the unset fields).
    init_db()
    _validate_library(library_name)
    config = load_config()
    server = get_plex_server(config)

    rows = get_library_hub_order(library_name)
    row = next((r for r in rows if r.hub_title == request.hub_title), None)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Hub '{request.hub_title}' not found in '{library_name}'",
        )
    if row.hub_type == HUB_TYPE_COLLECTION:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot edit visibility for HSH-managed collection '{request.hub_title}' from dashboard",
        )

    plex_hubs = _get_managed_hubs_for_library(server, library_name)
    hub = next((h for h in plex_hubs if h.title == request.hub_title), None)
    if hub is None:
        raise HTTPException(
            status_code=404,
            detail=f"Hub '{request.hub_title}' not found in Plex for '{library_name}'",
        )

    error: Optional[str] = None
    try:
        hub.updateVisibility(
            home=request.home,
            shared=request.shared,
            recommended=request.recommended,
        )
        logger.info(
            "Updated visibility for '%s' in '%s': home=%s shared=%s recommended=%s",
            request.hub_title,
            library_name,
            request.home,
            request.shared,
            request.recommended,
        )
    except Exception as e:
        error = f"Failed to update visibility: {e}"
        logger.warning(error)

    return VisibilityResponse(
        library_name=library_name,
        hub_title=request.hub_title,
        home=request.home,
        shared=request.shared,
        recommended=request.recommended,
        error=error,
    )


@router.post("/{library_name}/hubs/pins", response_model=PinsResponse)
def set_hub_pins(
    library_name: str,
    request: PinsRequest,
    _current_user: CurrentUser = Depends(require_admin),
) -> PinsResponse:
    # Batched ok: pins are DB-only writes (1 top + 1 bottom per library).
    # Pin enforcement against Plex is via subsequent move calls, not here.
    init_db()
    _validate_library(library_name)

    rows = get_library_hub_order(library_name)
    titles = {r.hub_title for r in rows}
    if request.top is not None and request.top not in titles:
        raise HTTPException(
            status_code=404,
            detail=f"Pin-top hub '{request.top}' not found in '{library_name}'",
        )
    if request.bottom is not None and request.bottom not in titles:
        raise HTTPException(
            status_code=404,
            detail=f"Pin-bottom hub '{request.bottom}' not found in '{library_name}'",
        )
    if request.top is not None and request.top == request.bottom:
        raise HTTPException(
            status_code=400,
            detail=f"Hub '{request.top}' cannot be both top and bottom",
        )

    current_top = next((r.hub_title for r in rows if r.pin_position == PIN_TOP), None)
    current_bottom = next((r.hub_title for r in rows if r.pin_position == PIN_BOTTOM), None)

    if current_top != request.top:
        if current_top is not None:
            set_pin(library_name, current_top, None)
        if request.top is not None:
            set_pin(library_name, request.top, PIN_TOP)
    if current_bottom != request.bottom:
        if current_bottom is not None:
            set_pin(library_name, current_bottom, None)
        if request.bottom is not None:
            set_pin(library_name, request.bottom, PIN_BOTTOM)

    return PinsResponse(library_name=library_name, top=request.top, bottom=request.bottom)
