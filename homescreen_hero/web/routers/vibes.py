from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from ...core.auth import CurrentUser, require_admin
from ...core.config.loader import load_config
from ...core.db.vibes import get_vibe_stats
from ...core.vibe_compute import compute_all_vibes
from ...core.vibe_scoring import VIBE_DISPLAY_NAMES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vibes", tags=["vibes"])


class VibeStatusResponse(BaseModel):
    total_movies_scored: int
    current_version_count: int
    outdated_version_count: int
    score_version: int
    libraries: Dict[str, int]
    last_computed: Optional[datetime] = None
    vibe_names: Dict[str, str]


class VibeComputeResponse(BaseModel):
    status: str
    results: Optional[Dict[str, Any]] = None


@router.get("/status", response_model=VibeStatusResponse)
def get_status(
    current_user: CurrentUser = Depends(require_admin),
) -> VibeStatusResponse:
    # Get vibe computation status
    stats = get_vibe_stats()
    return VibeStatusResponse(
        **stats,
        vibe_names=VIBE_DISPLAY_NAMES,
    )


@router.post("/compute", response_model=VibeComputeResponse)
def trigger_compute(
    background_tasks: BackgroundTasks,
    force: bool = False,
    current_user: CurrentUser = Depends(require_admin),
) -> VibeComputeResponse:
    # Trigger async vibe computation (returns immediately)
    config = load_config()

    if config.tmdb is None or not config.tmdb.enabled:
        raise HTTPException(
            status_code=400,
            detail="TMDb integration is not configured. Add tmdb settings to config.yaml.",
        )

    background_tasks.add_task(compute_all_vibes, config, force)

    return VibeComputeResponse(status="started")


@router.post("/compute-sync", response_model=VibeComputeResponse)
def trigger_compute_sync(
    force: bool = False,
    current_user: CurrentUser = Depends(require_admin),
) -> VibeComputeResponse:
    # Trigger synchronous vibe computation (blocks until complete)
    config = load_config()

    if config.tmdb is None or not config.tmdb.enabled:
        raise HTTPException(
            status_code=400,
            detail="TMDb integration is not configured. Add tmdb settings to config.yaml.",
        )

    results = compute_all_vibes(config, force)

    return VibeComputeResponse(status="completed", results=results)
