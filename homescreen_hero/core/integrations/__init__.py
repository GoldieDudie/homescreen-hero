import os

from .plex_client import get_plex_server as _get_real_plex_server, apply_home_screen_selection
from .trakt_client import get_trakt_client
from .trakt_sync import sync_all_trakt_sources
from .letterboxd_sync import sync_all_letterboxd_sources
from .mdblist_sync import sync_all_mdblist_sources


def is_demo_mode() -> bool:
    return os.environ.get("DEMO_MODE", "").lower() in ("true", "1", "yes")


def get_plex_server(config):
    # Use mock Plex server in demo mode
    if is_demo_mode():
        from .mock_plex_client import get_mock_plex_server
        return get_mock_plex_server(config)
    return _get_real_plex_server(config)


__all__ = [
    "get_plex_server",
    "get_trakt_client",
    "sync_all_trakt_sources",
    "sync_all_letterboxd_sources",
    "sync_all_mdblist_sources",
    "apply_home_screen_selection",
    "is_demo_mode",
]
