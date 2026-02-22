from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from .config.schema import AppConfig
from .db.vibes import get_existing_rating_keys, upsert_movie_vibe
from .integrations.tmdb_client import TmdbClient, get_tmdb_client
from .integrations.plex_client import get_plex_server
from .vibe_scoring import SCORE_VERSION, compute_vibe_scores

logger = logging.getLogger(__name__)

# ~33 requests/sec, safely under TMDb's 40/sec limit
TMDB_REQUEST_DELAY = 0.03


def extract_tmdb_id(item: Any) -> Optional[int]:
    # Extract TMDb ID from Plex item's external GUIDs
    for guid in getattr(item, "guids", None) or []:
        guid_id = getattr(guid, "id", None)
        if guid_id and guid_id.startswith("tmdb://"):
            try:
                return int(guid_id.replace("tmdb://", ""))
            except ValueError:
                pass
    return None


def extract_genres(item: Any) -> List[str]:
    # Extract genre names from Plex item
    return [g.tag for g in getattr(item, "genres", None) or []]


def extract_content_rating(item: Any) -> Optional[str]:
    # Extract MPAA content rating (G, PG, PG-13, R, NC-17) from Plex item
    rating = getattr(item, "contentRating", None)
    if not rating:
        return None
    # Normalize common Plex rating formats to MPAA standard
    rating = rating.strip().upper()
    rating_map = {
        "G": "G",
        "PG": "PG",
        "PG-13": "PG-13",
        "R": "R",
        "NC-17": "NC-17",
        "NR": None,  # Not Rated — no signal
        "UNRATED": None,
        "NOT RATED": None,
        "TV-Y": "G",
        "TV-Y7": "G",
        "TV-G": "G",
        "TV-PG": "PG",
        "TV-14": "PG-13",
        "TV-MA": "R",
    }
    return rating_map.get(rating)


def compute_vibes_for_library(
    server: Any,
    library_name: str,
    tmdb_client: Optional[TmdbClient],
    force_recompute: bool = False,
) -> Dict[str, int]:
    # Compute vibe scores for all movies in a single Plex library
    try:
        library = server.library.section(library_name)
    except Exception:
        logger.error("Library '%s' not found on Plex server", library_name)
        return {"error": f"Library '{library_name}' not found"}

    if library.type != "movie":
        logger.info("Skipping non-movie library: %s", library_name)
        return {"skipped": "not a movie library"}

    items = library.all(includeGuids=1)
    logger.info("Computing vibes for %d movies in '%s'", len(items), library_name)

    # Load existing rating keys for incremental check
    existing_keys = set()
    if not force_recompute:
        existing_keys = get_existing_rating_keys(score_version=SCORE_VERSION)

    stats = {"total": len(items), "scored": 0, "skipped": 0, "errors": 0, "no_tmdb": 0}

    for item in items:
        rating_key = item.ratingKey

        # Skip if already computed with current version
        if rating_key in existing_keys and not force_recompute:
            stats["skipped"] += 1
            continue

        try:
            genres = extract_genres(item)
            tmdb_id = extract_tmdb_id(item)
            content_rating = extract_content_rating(item)
            keywords: list = []
            scoring_genres = genres

            overview: Optional[str] = None
            poster_path: Optional[str] = None

            if tmdb_id and tmdb_client:
                try:
                    tmdb_data = tmdb_client.get_movie_with_keywords(tmdb_id)
                    keywords = tmdb_data.keywords
                    overview = tmdb_data.overview
                    poster_path = tmdb_data.poster_path
                    # Prefer TMDb genres (more standardized), fall back to Plex
                    if tmdb_data.genres:
                        scoring_genres = tmdb_data.genres
                    time.sleep(TMDB_REQUEST_DELAY)
                except Exception as e:
                    logger.warning(
                        "TMDb fetch failed for '%s' (tmdb:%s): %s",
                        item.title, tmdb_id, e,
                    )
            elif not tmdb_id:
                stats["no_tmdb"] += 1

            scores = compute_vibe_scores(
                scoring_genres, keywords, content_rating, overview,
            )

            upsert_movie_vibe(
                plex_rating_key=rating_key,
                tmdb_id=tmdb_id,
                title=item.title,
                year=getattr(item, "year", None),
                plex_library=library_name,
                genres=scoring_genres,
                tmdb_keywords=keywords,
                tmdb_overview=overview,
                poster_path=poster_path,
                scores=scores,
            )
            stats["scored"] += 1

        except Exception as e:
            logger.error(
                "Error computing vibes for '%s' (rk:%s): %s",
                item.title, rating_key, e,
            )
            stats["errors"] += 1

    logger.info(
        "Vibe computation complete for '%s': %d scored, %d skipped, %d errors, %d no TMDb ID",
        library_name, stats["scored"], stats["skipped"], stats["errors"], stats["no_tmdb"],
    )
    return stats


def compute_all_vibes(
    config: Optional[AppConfig] = None,
    force_recompute: bool = False,
) -> Dict[str, Any]:
    # Main entry point: compute vibes for all movies across all enabled libraries
    if config is None:
        from .config.loader import load_config
        config = load_config()

    from .db.history import init_db
    init_db()

    server = get_plex_server(config)
    tmdb_client = get_tmdb_client(config)

    if tmdb_client is None:
        logger.warning(
            "TMDb not configured — scoring with Plex genres only (no keyword boosts)"
        )

    all_stats: Dict[str, Any] = {}
    for lib_config in config.plex.libraries:
        if not lib_config.enabled:
            continue
        try:
            stats = compute_vibes_for_library(
                server, lib_config.name, tmdb_client, force_recompute,
            )
            all_stats[lib_config.name] = stats
        except Exception as e:
            logger.error("Failed to compute vibes for library '%s': %s", lib_config.name, e)
            all_stats[lib_config.name] = {"error": str(e)}

    return all_stats
