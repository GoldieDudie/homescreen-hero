# User-facing API endpoints (non-admin).

import logging
from datetime import datetime
from typing import Any, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from homescreen_hero.core.auth import CurrentUser, get_current_user
from homescreen_hero.core.config.loader import load_config
from homescreen_hero.core.integrations.plex_client import get_plex_server
from homescreen_hero.core.integrations.tmdb_client import get_tmdb_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/user", tags=["user"])

TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"


def _extract_tmdb_id(item: Any) -> Optional[int]:
    # Extract TMDb ID from Plex item's external GUIDs
    for guid in getattr(item, "guids", None) or []:
        guid_id = getattr(guid, "id", None)
        if guid_id and guid_id.startswith("tmdb://"):
            try:
                return int(guid_id.replace("tmdb://", ""))
            except ValueError:
                pass
    return None


class RecentMediaItem(BaseModel):
    title: str
    year: Optional[int] = None
    thumb: Optional[str] = None
    art: Optional[str] = None  # Widescreen backdrop/fanart
    type: str  # "movie" or "show"
    added_at: datetime
    summary: Optional[str] = None


class RecentMediaResponse(BaseModel):
    items: List[RecentMediaItem]


@router.get("/recent-media", response_model=RecentMediaResponse)
def get_recent_media(
    limit: int = 10,
    current_user: CurrentUser = Depends(get_current_user),
) -> RecentMediaResponse:
    # Returns recently added movies/shows from Plex with TMDb image URLs
    config = load_config()
    server = get_plex_server(config)
    tmdb_client = get_tmdb_client(config)
    enabled_libraries = [lib.name for lib in config.plex.libraries if lib.enabled]

    all_items: List[RecentMediaItem] = []

    for lib_name in enabled_libraries:
        try:
            section = server.library.section(lib_name)
            if section.type not in ("movie", "show"):
                continue

            items = section.recentlyAdded(maxresults=limit)
            for item in items:
                added_at = getattr(item, "addedAt", None)
                if added_at is None:
                    continue

                thumb_url = None
                art_url = None
                is_episode = item.type == "episode"

                if tmdb_client:
                    try:
                        if is_episode:
                            # For episodes, fetch the parent show for its TMDb ID
                            show = server.fetchItem(item.grandparentRatingKey)
                            show.reload(includeGuids=1)
                            tmdb_id = _extract_tmdb_id(show)
                            if tmdb_id:
                                images = tmdb_client.get_tv_images(tmdb_id)
                        else:
                            item.reload(includeGuids=1)
                            tmdb_id = _extract_tmdb_id(item)
                            if tmdb_id:
                                images = tmdb_client.get_movie_images(tmdb_id)

                        if tmdb_id and images:
                            if images["poster_path"]:
                                thumb_url = f"{TMDB_IMAGE_BASE}/w500{images['poster_path']}"
                            if images["backdrop_path"]:
                                art_url = f"{TMDB_IMAGE_BASE}/w1280{images['backdrop_path']}"
                    except Exception as e:
                        logger.debug(
                            "TMDb image fetch failed for '%s': %s",
                            item.title, e,
                        )

                # Fall back to Plex URLs if TMDb didn't work
                if not thumb_url and hasattr(item, "thumb") and item.thumb:
                    thumb_url = server.url(item.thumb, includeToken=True)
                if not art_url and hasattr(item, "art") and item.art:
                    art_url = server.url(item.art, includeToken=True)

                # For episodes, show the series name instead of episode title
                display_title = (
                    getattr(item, "grandparentTitle", item.title)
                    if is_episode else item.title
                )

                all_items.append(
                    RecentMediaItem(
                        title=display_title,
                        year=getattr(item, "year", None),
                        thumb=thumb_url,
                        art=art_url,
                        type="show" if is_episode else item.type,
                        added_at=added_at,
                        summary=getattr(item, "summary", None),
                    )
                )
        except Exception as e:
            logger.warning(f"Error fetching recent items from {lib_name}: {e}")
            continue

    all_items.sort(key=lambda x: x.added_at, reverse=True)
    all_items = all_items[:limit]

    return RecentMediaResponse(items=all_items)
