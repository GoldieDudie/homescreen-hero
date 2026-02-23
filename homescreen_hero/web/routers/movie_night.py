# Movie Night picker API — Phase 2B (single-player vibe picker with filters)

import logging
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator

from homescreen_hero.core.auth import CurrentUser, get_current_user
from homescreen_hero.core.db.vibes import get_ranked_movies_by_vibes
from homescreen_hero.core.vibe_scoring import VIBE_NAMES, VIBE_DISPLAY_NAMES

logger = logging.getLogger(__name__)

TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"
VALID_DURATIONS = {"quick", "standard", "long"}
VALID_REWATCH_MODES = {"new", "rewatch", "any"}

router = APIRouter(prefix="/movie-night", tags=["movie-night"])


class MovieNightPickRequest(BaseModel):
    vibes: List[str]
    duration: Optional[str] = None
    rewatch_mode: Optional[str] = "new"

    @field_validator("vibes")
    @classmethod
    def validate_vibes(cls, v: List[str]) -> List[str]:
        if len(v) < 2 or len(v) > 3:
            raise ValueError("Must select 2-3 vibes")
        for vibe in v:
            if vibe not in VIBE_NAMES:
                raise ValueError(f"Unknown vibe: {vibe}")
        return v

    @field_validator("duration")
    @classmethod
    def validate_duration(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_DURATIONS:
            raise ValueError(f"Invalid duration: {v}")
        return v

    @field_validator("rewatch_mode")
    @classmethod
    def validate_rewatch_mode(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_REWATCH_MODES:
            raise ValueError(f"Invalid rewatch_mode: {v}")
        return v


class MovieNightMovie(BaseModel):
    plex_rating_key: int
    title: str
    year: Optional[int] = None
    poster_url: Optional[str] = None
    overview: Optional[str] = None
    genres: Optional[List[str]] = None
    duration_minutes: Optional[int] = None
    match_score: float
    vibe_scores: Dict[str, float]


class MovieNightPickResponse(BaseModel):
    movies: List[MovieNightMovie]
    vibe_names: Dict[str, str]
    filters_applied: Dict[str, str]


def _is_home_user(config: Any, username: str) -> bool:
    # Check if the user is the server admin or a Plex Home member.
    # Friends/shared users can't be impersonated via switchHomeUser.
    try:
        from homescreen_hero.core.integrations.plex_client import get_home_users
        home_users = get_home_users(config)
        return any(u["username"] == username for u in home_users)
    except Exception:
        return False


def _get_user_watched_keys(username: str) -> Optional[Set[int]]:
    # Get rating keys of movies this user has watched, via Plex API.
    # Only works for the server admin and Plex Home members.
    # Returns None for friends/shared users or on failure (caller degrades gracefully).
    try:
        from homescreen_hero.core.config.loader import load_config
        from homescreen_hero.core.integrations.plex_client import get_server_for_user

        config = load_config()

        # Only home users can be impersonated — bail early for friends
        if not _is_home_user(config, username):
            logger.info("User '%s' is not a Plex Home member, skipping watch history", username)
            return None

        server = get_server_for_user(config, username)

        watched_keys: Set[int] = set()
        for lib_config in config.plex.libraries:
            if not lib_config.enabled:
                continue
            try:
                library = server.library.section(lib_config.name)
                if library.type != "movie":
                    continue
                for item in library.all():
                    if getattr(item, "isWatched", False):
                        watched_keys.add(item.ratingKey)
            except Exception as e:
                logger.warning("Failed to get watched status for library '%s': %s", lib_config.name, e)

        return watched_keys
    except Exception as e:
        logger.warning("Failed to get watch history from Plex for '%s': %s", username, e)
        return None


@router.post("/pick", response_model=MovieNightPickResponse)
def pick_movies(
    request: MovieNightPickRequest,
    current_user: CurrentUser = Depends(get_current_user),
) -> MovieNightPickResponse:
    filters_applied: Dict[str, str] = {}
    exclude_keys: Optional[Set[int]] = None
    only_keys: Optional[Set[int]] = None

    # Handle rewatch mode
    rewatch = request.rewatch_mode or "any"
    if rewatch in ("new", "rewatch"):
        watched_keys = _get_user_watched_keys(current_user.username)
        if watched_keys is not None:
            if rewatch == "new":
                exclude_keys = watched_keys
                filters_applied["rewatch_mode"] = "new"
            else:
                only_keys = watched_keys
                filters_applied["rewatch_mode"] = "rewatch"
        else:
            # Plex unavailable — degrade to "any"
            filters_applied["rewatch_mode"] = "any"
            filters_applied["rewatch_fallback"] = "plex_unavailable"
    else:
        filters_applied["rewatch_mode"] = "any"

    # Duration filter
    if request.duration:
        filters_applied["duration"] = request.duration

    ranked = get_ranked_movies_by_vibes(
        request.vibes,
        limit=10,
        duration_bucket=request.duration,
        exclude_rating_keys=exclude_keys,
        only_rating_keys=only_keys,
    )

    movies = []
    for movie_vibe, match_score in ranked:
        poster_url = None
        if movie_vibe.poster_path:
            poster_url = f"{TMDB_IMAGE_BASE}/w500{movie_vibe.poster_path}"

        vibe_scores = {
            name: getattr(movie_vibe, f"vibe_{name}") for name in VIBE_NAMES
        }

        movies.append(
            MovieNightMovie(
                plex_rating_key=movie_vibe.plex_rating_key,
                title=movie_vibe.title,
                year=movie_vibe.year,
                poster_url=poster_url,
                overview=movie_vibe.tmdb_overview,
                genres=movie_vibe.genres,
                duration_minutes=movie_vibe.duration_minutes,
                match_score=round(match_score, 4),
                vibe_scores=vibe_scores,
            )
        )

    return MovieNightPickResponse(
        movies=movies,
        vibe_names=VIBE_DISPLAY_NAMES,
        filters_applied=filters_applied,
    )
