import os

from .plex_client import get_plex_server as _get_real_plex_server, apply_home_screen_selection
from .trakt_client import get_trakt_client as _get_real_trakt_client
from .mdblist_client import get_mdblist_client as _get_real_mdblist_client
from .tautulli_client import get_tautulli_client as _get_real_tautulli_client
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


def get_trakt_client(config):
    # Use mock Trakt client in demo mode
    if is_demo_mode():
        from .mock_plex_client import get_mock_trakt_client
        return get_mock_trakt_client(config)
    return _get_real_trakt_client(config)


def get_mdblist_client(config):
    # Use mock MDBList client in demo mode
    if is_demo_mode():
        from .mock_plex_client import get_mock_mdblist_client
        return get_mock_mdblist_client(config)
    return _get_real_mdblist_client(config)


def get_tautulli_client(config):
    # Use mock Tautulli client in demo mode
    if is_demo_mode():
        from .mock_plex_client import get_mock_tautulli_client
        return get_mock_tautulli_client(config)
    return _get_real_tautulli_client(config)


__all__ = [
    "get_plex_server",
    "get_trakt_client",
    "get_mdblist_client",
    "get_tautulli_client",
    "sync_all_trakt_sources",
    "sync_all_letterboxd_sources",
    "sync_all_mdblist_sources",
    "apply_home_screen_selection",
    "is_demo_mode",
]
