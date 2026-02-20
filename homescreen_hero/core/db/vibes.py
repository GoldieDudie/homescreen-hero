from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional, Set

from sqlalchemy import func, select

from .base import session_scope
from .models import MovieVibe
from ..vibe_scoring import VIBE_NAMES, SCORE_VERSION

logger = logging.getLogger(__name__)


def get_existing_rating_keys(score_version: Optional[int] = None) -> Set[int]:
    # Get all plex_rating_keys that already have vibe scores.
    # If score_version is provided, only return keys at that version.
    with session_scope() as db:
        stmt = select(MovieVibe.plex_rating_key)
        if score_version is not None:
            stmt = stmt.where(MovieVibe.score_version == score_version)
        rows = db.execute(stmt).scalars().all()
        return set(rows)


def upsert_movie_vibe(
    plex_rating_key: int,
    tmdb_id: Optional[int],
    title: str,
    year: Optional[int],
    plex_library: str,
    genres: List[str],
    tmdb_keywords: list,
    scores: Dict[str, float],
    tmdb_overview: Optional[str] = None,
) -> None:
    # Insert or update a MovieVibe row
    with session_scope() as db:
        existing = db.execute(
            select(MovieVibe).where(MovieVibe.plex_rating_key == plex_rating_key)
        ).scalar_one_or_none()

        if existing:
            existing.tmdb_id = tmdb_id
            existing.title = title
            existing.year = year
            existing.plex_library = plex_library
            existing.genres = genres
            existing.tmdb_keywords = tmdb_keywords
            existing.tmdb_overview = tmdb_overview
            existing.computed_at = datetime.utcnow()
            existing.score_version = SCORE_VERSION
            for vibe in VIBE_NAMES:
                setattr(existing, f"vibe_{vibe}", scores[vibe])
        else:
            vibe_kwargs = {f"vibe_{vibe}": scores[vibe] for vibe in VIBE_NAMES}
            row = MovieVibe(
                plex_rating_key=plex_rating_key,
                tmdb_id=tmdb_id,
                title=title,
                year=year,
                plex_library=plex_library,
                genres=genres,
                tmdb_keywords=tmdb_keywords,
                tmdb_overview=tmdb_overview,
                computed_at=datetime.utcnow(),
                score_version=SCORE_VERSION,
                **vibe_kwargs,
            )
            db.add(row)


def get_vibe_stats() -> Dict:
    # Get summary statistics about vibe computation status
    with session_scope() as db:
        total = db.execute(
            select(func.count(MovieVibe.id))
        ).scalar() or 0

        current = db.execute(
            select(func.count(MovieVibe.id)).where(
                MovieVibe.score_version == SCORE_VERSION
            )
        ).scalar() or 0

        # Count per library
        lib_rows = db.execute(
            select(MovieVibe.plex_library, func.count(MovieVibe.id))
            .group_by(MovieVibe.plex_library)
        ).all()
        libraries = {lib: count for lib, count in lib_rows}

        # Last computed timestamp
        latest = db.execute(
            select(func.max(MovieVibe.computed_at))
        ).scalar()

        return {
            "total_movies_scored": total,
            "current_version_count": current,
            "outdated_version_count": total - current,
            "score_version": SCORE_VERSION,
            "libraries": libraries,
            "last_computed": latest,
        }
