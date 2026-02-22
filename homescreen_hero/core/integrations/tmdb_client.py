from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import logging
import requests

from ..config.schema import AppConfig, TmdbSettings

logger = logging.getLogger(__name__)


def _parse_connection_error(exc: Exception, service_name: str) -> str:
    # Parse requests.ConnectionError into user-friendly messages
    error_str = str(exc).lower()

    if "connection refused" in error_str:
        return f"Connection refused. Check that {service_name} is reachable."
    if "name or service not known" in error_str or "nodename nor servname" in error_str:
        return "Host not found. Check that the hostname or IP address is correct."
    if "no route to host" in error_str:
        return "No route to host. Check the IP address and network connectivity."
    if "network is unreachable" in error_str:
        return "Network unreachable. Check your network connection."
    if "ssl" in error_str or "certificate" in error_str:
        return "SSL/TLS error. Check the URL or try a different protocol."
    if "max retries" in error_str:
        return f"Could not connect to {service_name}. Check your network connection."

    return f"Could not connect to {service_name}. Check your network connection."


@dataclass
class TmdbConfig:
    api_key: str
    base_url: str = "https://api.themoviedb.org/3"


@dataclass
class TmdbMovieData:
    tmdb_id: int
    genres: List[str]
    keywords: List[Dict[str, Any]]
    overview: Optional[str] = None
    poster_path: Optional[str] = None


class TmdbClient:
    def __init__(self, cfg: TmdbConfig) -> None:
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "HomeScreenHero/1.0",
        })

    def _build_url(self, path: str) -> str:
        base = self.cfg.base_url.rstrip("/")
        return f"{base}/{path.lstrip('/')}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        timeout: float = 10.0,
    ) -> Any:
        url = self._build_url(path)

        if params is None:
            params = {}
        params["api_key"] = self.cfg.api_key

        logger.debug("TMDb request: %s %s", method, url)

        resp = self.session.request(
            method=method,
            url=url,
            params=params,
            timeout=timeout,
        )

        try:
            resp.raise_for_status()
        except requests.HTTPError:
            logger.warning(
                "TMDb HTTP error: %s %s -> %s",
                method,
                url,
                resp.status_code,
            )
            raise

        return resp.json()

    def ping(self) -> Tuple[bool, Optional[str]]:
        # Validate API key by hitting /configuration
        if not self.cfg.api_key:
            return False, "No API key configured"

        try:
            self._request("GET", "/configuration")
            return True, None
        except requests.Timeout:
            return False, "Connection timed out. Check your network connection."
        except requests.ConnectionError as exc:
            return False, _parse_connection_error(exc, "TMDb")
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response else "unknown"
            if status == 401:
                return False, "Invalid API key. Check your TMDb API key."
            return False, f"TMDb API returned error {status}"
        except Exception:
            logger.debug("TMDb ping error", exc_info=True)
            return False, "Connection failed. Check your network connection."

    def get_movie_with_keywords(self, tmdb_id: int) -> TmdbMovieData:
        # Fetch movie details + keywords in a single request
        data = self._request(
            "GET",
            f"/movie/{tmdb_id}",
            params={"append_to_response": "keywords"},
        )

        genres = [g["name"] for g in data.get("genres", [])]
        keywords_data = data.get("keywords", {}).get("keywords", [])

        return TmdbMovieData(
            tmdb_id=tmdb_id,
            genres=genres,
            keywords=keywords_data,
            overview=data.get("overview"),
            poster_path=data.get("poster_path"),
        )


    def get_movie_images(self, tmdb_id: int) -> Dict[str, Optional[str]]:
        # Fetch poster_path and backdrop_path for a movie
        data = self._request("GET", f"/movie/{tmdb_id}")
        return {
            "poster_path": data.get("poster_path"),
            "backdrop_path": data.get("backdrop_path"),
        }

    def get_tv_images(self, tmdb_id: int) -> Dict[str, Optional[str]]:
        # Fetch poster_path and backdrop_path for a TV show
        data = self._request("GET", f"/tv/{tmdb_id}")
        return {
            "poster_path": data.get("poster_path"),
            "backdrop_path": data.get("backdrop_path"),
        }


def get_tmdb_client(config: AppConfig) -> Optional[TmdbClient]:
    if config.tmdb is None:
        logger.info("TMDb not configured")
        return None

    tmdb_cfg: TmdbSettings = config.tmdb

    if not tmdb_cfg.enabled:
        logger.info("TMDb is disabled in config")
        return None

    if not tmdb_cfg.api_key:
        logger.warning("TMDb enabled but api_key is missing")
        return None

    cfg = TmdbConfig(
        api_key=tmdb_cfg.api_key,
        base_url=tmdb_cfg.base_url,
    )
    return TmdbClient(cfg)
