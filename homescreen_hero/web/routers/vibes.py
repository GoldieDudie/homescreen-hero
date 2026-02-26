from __future__ import annotations

import logging
import threading
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

# Guard against concurrent vibe computations
_compute_lock = threading.Lock()


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


def _guarded_compute(config, force: bool) -> None:
    # Wrapper that holds the lock so concurrent triggers are rejected
    try:
        compute_all_vibes(config, force)
    finally:
        _compute_lock.release()


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

    if not _compute_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail="Vibe computation is already running.",
        )

    background_tasks.add_task(_guarded_compute, config, force)

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

    if not _compute_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail="Vibe computation is already running.",
        )

    try:
        results = compute_all_vibes(config, force)
    finally:
        _compute_lock.release()

    return VibeComputeResponse(status="completed", results=results)
