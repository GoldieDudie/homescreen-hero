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
    poster_path: Optional[str] = None,
    duration_minutes: Optional[int] = None,
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
            existing.poster_path = poster_path
            existing.duration_minutes = duration_minutes
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
                poster_path=poster_path,
                duration_minutes=duration_minutes,
                computed_at=datetime.utcnow(),
                score_version=SCORE_VERSION,
                **vibe_kwargs,
            )
            db.add(row)


DURATION_RANGES = {
    "quick": (None, 100),
    "standard": (100, 150),
    "long": (150, None),
}


def get_ranked_movies_by_vibes(
    vibe_names: List[str],
    limit: int = 10,
    duration_bucket: Optional[str] = None,
    exclude_rating_keys: Optional[Set[int]] = None,
    only_rating_keys: Optional[Set[int]] = None,
) -> List[tuple]:
    # Return movies ranked by max score across selected vibes.
    # Uses SQLite's scalar max(a, b, ...) which returns the largest argument.
    # Optional filters: duration bucket, exclude/include specific rating keys.
    vibe_columns = [getattr(MovieVibe, f"vibe_{name}") for name in vibe_names]
    match_score = func.max(*vibe_columns).label("match_score")

    with session_scope() as db:
        stmt = (
            select(MovieVibe, match_score)
            .where(MovieVibe.score_version == SCORE_VERSION)
        )

        # Duration filter
        if duration_bucket and duration_bucket in DURATION_RANGES:
            low, high = DURATION_RANGES[duration_bucket]
            stmt = stmt.where(MovieVibe.duration_minutes.isnot(None))
            if low is not None:
                stmt = stmt.where(MovieVibe.duration_minutes >= low)
            if high is not None:
                stmt = stmt.where(MovieVibe.duration_minutes < high)

        # Rewatch filter: exclude watched movies ("something new")
        if exclude_rating_keys:
            stmt = stmt.where(MovieVibe.plex_rating_key.notin_(exclude_rating_keys))

        # Rewatch filter: only include watched movies ("rewatch")
        if only_rating_keys is not None:
            stmt = stmt.where(MovieVibe.plex_rating_key.in_(only_rating_keys))

        stmt = stmt.order_by(match_score.desc()).limit(limit)

        rows = db.execute(stmt).all()
        # Detach ORM objects from session so they're usable outside
        for row in rows:
            db.expunge(row[0])
        return [(row[0], row[1]) for row in rows]


def get_ranked_movies_by_vibes_group(
    player_vibes: List[List[str]],
    limit: int = 10,
    duration_bucket: Optional[str] = None,
    exclude_rating_keys: Optional[Set[int]] = None,
    only_rating_keys: Optional[Set[int]] = None,
) -> List[tuple]:
    # Return movies ranked by group score: MIN of each player's best vibe match.
    # Each player's score = MAX of their selected vibe columns (same as single-player).
    # Group score = MIN across all players — ensures everyone is happy with the pick.
    player_max_exprs = []
    for vibes in player_vibes:
        vibe_columns = [getattr(MovieVibe, f"vibe_{name}") for name in vibes]
        player_max_exprs.append(func.max(*vibe_columns))

    group_score = func.min(*player_max_exprs).label("group_score")

    with session_scope() as db:
        stmt = (
            select(MovieVibe, group_score)
            .where(MovieVibe.score_version == SCORE_VERSION)
        )

        # Duration filter
        if duration_bucket and duration_bucket in DURATION_RANGES:
            low, high = DURATION_RANGES[duration_bucket]
            stmt = stmt.where(MovieVibe.duration_minutes.isnot(None))
            if low is not None:
                stmt = stmt.where(MovieVibe.duration_minutes >= low)
            if high is not None:
                stmt = stmt.where(MovieVibe.duration_minutes < high)

        # Rewatch filter: exclude watched movies ("something new")
        if exclude_rating_keys:
            stmt = stmt.where(MovieVibe.plex_rating_key.notin_(exclude_rating_keys))

        # Rewatch filter: only include watched movies ("rewatch")
        if only_rating_keys is not None:
            stmt = stmt.where(MovieVibe.plex_rating_key.in_(only_rating_keys))

        stmt = stmt.order_by(group_score.desc()).limit(limit)

        rows = db.execute(stmt).all()
        for row in rows:
            db.expunge(row[0])
        return [(row[0], row[1]) for row in rows]


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
