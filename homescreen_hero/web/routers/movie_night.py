# Movie Night picker API — Phase 2A (single-player vibe picker)

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from homescreen_hero.core.auth import CurrentUser, get_current_user
from homescreen_hero.core.db.vibes import get_ranked_movies_by_vibes
from homescreen_hero.core.vibe_scoring import VIBE_NAMES, VIBE_DISPLAY_NAMES

logger = logging.getLogger(__name__)

TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"

router = APIRouter(prefix="/movie-night", tags=["movie-night"])


class MovieNightPickRequest(BaseModel):
    vibes: List[str]

    @field_validator("vibes")
    @classmethod
    def validate_vibes(cls, v: List[str]) -> List[str]:
        if len(v) < 2 or len(v) > 3:
            raise ValueError("Must select 2-3 vibes")
        for vibe in v:
            if vibe not in VIBE_NAMES:
                raise ValueError(f"Unknown vibe: {vibe}")
        return v


class MovieNightMovie(BaseModel):
    plex_rating_key: int
    title: str
    year: Optional[int] = None
    poster_url: Optional[str] = None
    overview: Optional[str] = None
    genres: Optional[List[str]] = None
    match_score: float
    vibe_scores: Dict[str, float]


class MovieNightPickResponse(BaseModel):
    movies: List[MovieNightMovie]
    vibe_names: Dict[str, str]


@router.post("/pick", response_model=MovieNightPickResponse)
def pick_movies(
    request: MovieNightPickRequest,
    current_user: CurrentUser = Depends(get_current_user),
) -> MovieNightPickResponse:
    ranked = get_ranked_movies_by_vibes(request.vibes, limit=10)

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
                match_score=round(match_score, 4),
                vibe_scores=vibe_scores,
            )
        )

    return MovieNightPickResponse(
        movies=movies,
        vibe_names=VIBE_DISPLAY_NAMES,
    )
