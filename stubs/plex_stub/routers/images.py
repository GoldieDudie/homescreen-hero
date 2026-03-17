import logging
from pathlib import Path

import requests as http_client
from cachetools import TTLCache
from fastapi import APIRouter
from fastapi.responses import FileResponse, Response

from stubs.plex_stub.state import state

router = APIRouter()
logger = logging.getLogger(__name__)

POSTERS_DIR = Path(__file__).parent.parent / "fixtures" / "posters"

TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"

# Cache TMDb images in memory so we don't re-fetch on every request
_tmdb_cache: TTLCache = TTLCache(maxsize=200, ttl=7200)

# Collection ratingKey -> poster filename
COLLECTION_POSTERS = {
    "10001": "Oscar-Winners-2024.png",
    "10002": "80s-Action-Classics.png",
    "10003": "Studio-Ghibli-Films.png",
    "10004": "Nolan-Collection.jpg",
    "10005": "90s-Crime-Dramas.jpg",
    "10006": "Sci-Fi-Essentials.png",
    "10007": "A24-Collection.png",  # reusing for A24
    "10008": "Holiday-Comedies.png",
    "10009": "Popular-on-Trakt.png",
    "10010": "Letterboxd-Favorites.png",
    "10016": "Spielberg-Collection.png",
    "10017": "Tarantino-Collection.png",
    "10018": "Villeneuve-Collection.png",
    "10020": "MCU-Infinity-Saga.png",
    "10021": "Heist-Movies.jpg",
    "10019": "Anime-Classics.png",
    "10013": "Classic-Horror.jpeg",
    "10014": "Halloween-Favorites.png",
    "10015": "Modern-Horror.png",
    "10011": "Trending-Movies.png",
    "10012": "Recently-Requested.png",
    "20006": "Anime-Classics.png",
    "20007": "MAL-Spring-Season.jpg",
    "20004": "Critically-Acclaimed-TV.png",
    "20005": "Binge-Worthy-Miniseries.png",
    "20001": "HBO-Prestige-Dramas.png",
    "20002": "Anime-Classics.png",
    "20003": "Currently-Airing-on-TV.png",
}

# Movie/show ratingKey -> TMDb poster path (fetched from TMDb API)
TMDB_POSTERS = {
    # Oscar Winners 2024
    "1001": "/8Gxv8gSFCU0XGDykEGv7zR1n2ua.jpg",      # Oppenheimer
    "1002": "/kCGlIMHnOm8JPXq3rXM6c5wMxcT.jpg",       # Poor Things
    "1003": "/VHSzNBTwxV8vh7wylo7O9CLdac.jpg",         # The Holdovers
    "1004": "/kQs6keheMwCxJxrzV83VUwFtHkB.jpg",        # Anatomy of a Fall
    "1005": "/dB6Krk806zeqd0YNp2ngQ9zXteH.jpg",        # Killers of the Flower Moon
    # 80s Action
    "1010": "/7Bjd8kfmDSOzpmhySpEhkUyK2oH.jpg",       # Die Hard
    "1011": "/k3mW4qfJo6SKqe6laRyNGnbB9n5.jpg",       # Predator
    "1012": "/esmAU0fCO28FbS6bUBKLAzJrohZ.jpg",       # RoboCop
    "1013": "/6gt44oqb4nE8vflPElffeGwsHVl.jpg",        # Lethal Weapon
    "1014": "/wVbeL6fkbTKSmNfalj4VoAUUqJv.jpg",        # Total Recall
    # Studio Ghibli
    "1020": "/39wmItIWsg5sZMyRUHLkWBcuVCM.jpg",       # Spirited Away
    "1021": "/cMYCDADoLKLbB83g4WnJegaZimC.jpg",        # Princess Mononoke
    "1022": "/rtGDOeG9LzoerkDGZF9dnVeLppL.jpg",       # My Neighbor Totoro
    "1023": "/13kOl2v0nD2OLbVSHnHk8GUFEhO.jpg",       # Howl's Moving Castle
    "1024": "/39wmItIWsg5sZMyRUHLkWBcuVCM.jpg",       # Nausicaa (fallback to Spirited Away)
    # Nolan
    "1030": "/xlaY2zyzMfkhk0HSC5VUwzoZPU1.jpg",        # Inception
    "1031": "/qJ2tW6WMUDux911r6m7haRef0WH.jpg",       # The Dark Knight
    "1032": "/gEU2QniE6E77NI6lCU6MxlNBvIx.jpg",       # Interstellar
    "1033": "/b4Oe15CGLL61Ped0RAS9JpqdmCt.jpg",        # Dunkirk
    "1034": "/aCIFMriQh8rvhxpN1IWGgvH0Tlg.jpg",        # Tenet
    # 90s Crime
    "1040": "/vQWk5YBFWF4bZaofAbv0tShwBvQ.jpg",        # Pulp Fiction
    "1041": "/9cqNxx0GxF0bflZmeSMuL5tnGzr.jpg",       # The Shawshank Redemption
    "1042": "/9OkCLM73MIU2CrKZbqiT8Ln1wY2.jpg",        # Goodfellas
    "1043": "/umSVjVdbVwtx5ryCA2QXL44Durm.jpg",        # Heat
    "1044": "/191nKfP0ehp3uIvWqgPbFmI4lv9.jpg",        # Se7en
    # Sci-Fi
    "1050": "/gajva2L0rPYkEWjzgFlBXCAVBE5.jpg",       # Blade Runner 2049
    "1051": "/ve72VxNqjGM69Uky4WTo2bK6rfq.jpg",        # 2001
    "1052": "/pEzNVQfdzYDzVK0XqxERIw2x2se.jpg",        # Arrival
    "1053": "/dmJW8IAKHKxFNiUnoDR7JfsK7Rp.jpg",        # Ex Machina
    "1054": "/p96dm7sCMn4VYAStA6siNz30G1r.jpg",        # The Matrix
    # A24
    "1060": "/u68AjlvlutfEIcpmbYpKcdi09ut.jpg",        # Everything Everywhere
    "1061": "/qLnfEmPrDjJfPyyddLJPkXmshkp.jpg",        # Moonlight
    "1062": "/gl66K7zRdtNYGrxyS2YDUP5ASZd.jpg",        # Lady Bird
    "1063": "/hjlZSXM86wJrfCv5VKfR5DI2VeU.jpg",        # Hereditary
    "1064": "/f1tIYarTbkBdIT1aW0gzelDwknv.jpg",        # The Lighthouse
    # Holiday
    "1070": "/bSqt9rhDZx1Q7UZ86dBPKdNomp2.jpg",        # It's a Wonderful Life
    "1071": "/i5We88HdO9Nsrv8xLyo4toNsLUM.jpg",        # Home Alone
    "1072": "/oOleziEempUPu96jkGs0Pj6tKxj.jpg",       # Elf
    "1073": "/7Bjd8kfmDSOzpmhySpEhkUyK2oH.jpg",       # Die Hard (holiday too)
    "1074": "/oQffRNjK8e19rF7xVYEN8ew0j7b.jpg",        # Nightmare Before Christmas
    "1075": "/oat42hUw8XzKYUmfy0YLAxYd484.jpg",       # National Lampoon's Christmas Vacation
    # MCU
    "1100": "/78lPtwv72eTNqFW9COBYI0dWDJa.jpg",       # Iron Man
    "1101": "/RYMX2wcKCBAr24UyPD7xwmjaTn.jpg",        # The Avengers
    "1102": "/vSNxAJTlD0r02V9sPYpOjqDZXUK.jpg",       # Captain America: First Avenger
    "1103": "/r7vmZjiyZw9rpJMQJdXpjgiCOk9.jpg",       # Guardians of the Galaxy
    "1104": "/7WsyChQLEftFiDOVTGkv3hFpyyt.jpg",       # Avengers: Infinity War
    "1105": "/ulzhLuWrPK07P1YkdWQLZnQh1JL.jpg",       # Avengers: Endgame
    # Heist
    "1110": "/hQQCdZrsHtZyR6NbKH2YyCqd2fR.jpg",       # Ocean's Eleven
    "1111": "/eSkjK4kctyrWpFhxl35GPvSs6tI.jpg",       # The Italian Job
    "1112": "/3NIzyXkfylsjflRKSz8Fts3lXzm.jpg",       # The Town
    "1113": "/tYzFuYXmT8LOYASlFCkaPiAFAl0.jpg",       # Baby Driver
    "1114": "/ffMUgkDZICNiyaws1Jkv8qG8uFW.jpg",       # Inside Man
    # Directors
    "1090": "/sF1U4EUQS8YHUYjNl3pMGNIQyr0.jpg",       # Schindler's List
    "1091": "/tjbLSFwi0I3phZwh8zoHWNfbsEp.jpg",       # Jaws
    "1092": "/uqx37cS8cpHg8U35f9U5IBlrCV3.jpg",       # Saving Private Ryan
    "1093": "/ceG9VzoRAVGwivFU403Wc3AHRys.jpg",       # Raiders of the Lost Ark
    "1094": "/maFjKnJ62hDQ9E66dKqDZgbUy0H.jpg",       # Jurassic Park
    "1095": "/xi8Iu6qyTfyZVDVy60raIOYJJmk.jpg",       # Reservoir Dogs
    "1096": "/v7TaX8kXMXs5yFFGR41guUDNcnB.jpg",       # Kill Bill: Vol. 1
    "1097": "/7sfbEnaARXDDhKm0CZ7D7uc2sbo.jpg",       # Inglourious Basterds
    "1098": "/7oWY8VDWW7thTzWh3OKYRkWUlD5.jpg",       # Django Unchained
    "1099": "/lz8vNyXeidqqOdJW9ZjnDAMb5Vr.jpg",       # Sicario
    # Horror
    "1080": "/uAR0AWqhQL1hQa69UDEbb2rE5Wx.jpg",       # The Shining
    "1081": "/wijlZ3HaYMvlDTPqJoTCWKFkCPU.jpg",       # Halloween
    "1082": "/wGTpGGRMZmyFCcrY2YoxVTIBlli.jpg",       # A Nightmare on Elm Street
    "1083": "/lr9ZIrmuwVmZhpZuTCW8D9g0ZJe.jpg",       # Scream
    "1084": "/5x0CeVHJI8tcDx8tUUwYHQSNILq.jpg",       # The Exorcist
    "1085": "/tFXcEccSQMf3lfhfXKSU9iRBpa3.jpg",       # Get Out
    "1086": "/7LEI8ulZzO5gy9Ww2NVCrKmHeDZ.jpg",       # Midsommar
    "1087": "/wVYREutTvI2tmxr6ujrHT704wGF.jpg",       # The Conjuring
    "1088": "/9E2y5Q7WlCVNEhP5GiVTjhEhx1o.jpg",       # It
    "1089": "/by4D4Q9NlUjFSEUA1yrxq6ksXmk.jpg",       # Hocus Pocus
    # TV - Additional
    "2020": "/ztkUQFLlC19CCMYHW9o1zWhJRNq.jpg",       # Breaking Bad
    "2021": "/fC2HDm5t0kHl7mTm7jxMR31b7by.jpg",       # Better Call Saul
    "2022": "/zYqVTiHK5ZajYcNzAW7qWte5NWS.jpg",       # True Detective
    "2023": "/7O4iVfOMQmdCSxhOg1WnzG1AgYT.jpg",       # Shogun
    "2024": "/eKfVzzEazSIjJMrw9ADa2x8ksLz.jpg",       # The Bear
    # TV - HBO
    "2001": "/rTc7ZXdroqjkKivFPvCPX0Ru7uw.jpg",       # The Sopranos
    "2002": "/4lbclFySvugI51fwsyxBTOm4DqK.jpg",       # The Wire
    "2003": "/z0XiwdrCQ9yVIr4O0pxzaAYRxdW.jpg",        # Succession
    "2004": "/hlLXt2tOPT6RRnjiUmoxyG1LTFi.jpg",       # Chernobyl
    "2005": "/8JMXquNmdMUy2n2RgW8gfOM0O3l.jpg",        # Band of Brothers
    # TV - Anime
    "2010": "/hTP1DtLGFamjfu8WqjnuQdP1n4i.jpg",       # Attack on Titan
    "2011": "/5ZFUEOULaVml7pQuXxhpR2SmVUw.jpg",       # FMA Brotherhood
    "2012": "/xDiXDfZwC6XYC6fxHI1jl3A3Ill.jpg",       # Cowboy Bebop
    "2013": "/vGYpEsy3Feh7FvqRCBcJk5Do35C.jpg",        # Steins;Gate
    "2014": "/4vrvWEbyHi4ruuQ07nJnnwBBGIR.jpg",        # Vinland Saga
}


@router.get("/photo/:/transcode")
def transcode_image(url: str = "", width: int = 0, height: int = 0, minSize: int = 0):
    # Extract rating key from url path like /library/metadata/{ratingKey}/thumb/12345
    rating_key = _extract_rating_key(url)
    logger.info("Transcode request: url=%s -> rating_key=%s, found=%s", url, rating_key, rating_key in TMDB_POSTERS or rating_key in COLLECTION_POSTERS)
    return _serve_poster(rating_key)


@router.get("/library/metadata/{rating_key}/thumb/{timestamp}")
def get_thumb(rating_key: str, timestamp: str):
    return _serve_poster(rating_key)


def _extract_rating_key(path: str) -> str | None:
    parts = path.split("/")
    for i, part in enumerate(parts):
        if part == "metadata" and i + 1 < len(parts):
            return parts[i + 1]
    return None


def _serve_poster(rating_key: str | None):
    if not rating_key:
        return _fallback_pixel()

    # Check collection posters first (self-hosted)
    if rating_key in COLLECTION_POSTERS:
        poster_path = POSTERS_DIR / COLLECTION_POSTERS[rating_key]
        if poster_path.exists():
            return FileResponse(poster_path)

    # Check TMDb posters (fetch and cache from CDN)
    if rating_key in TMDB_POSTERS:
        return _fetch_tmdb_poster(rating_key, TMDB_POSTERS[rating_key])

    # Scan posters dir by rating key filename
    if POSTERS_DIR.exists():
        for ext in [".jpg", ".png", ".jpeg", ".webp"]:
            poster_path = POSTERS_DIR / f"{rating_key}{ext}"
            if poster_path.exists():
                return FileResponse(poster_path)

    return _fallback_pixel()


def _fetch_tmdb_poster(rating_key: str, poster_path: str):
    cached = _tmdb_cache.get(rating_key)
    if cached:
        return Response(content=cached, media_type="image/jpeg")

    url = f"{TMDB_IMAGE_BASE}{poster_path}"
    try:
        resp = http_client.get(url, timeout=10)
        resp.raise_for_status()
        _tmdb_cache[rating_key] = resp.content
        media_type = resp.headers.get("content-type", "image/jpeg")
        return Response(content=resp.content, media_type=media_type)
    except Exception as exc:
        logger.warning("Failed to fetch TMDb poster %s: %s", url, exc)
        return _fallback_pixel()


def _fallback_pixel():
    # 1x1 transparent PNG - no-cache so browser doesn't cache failed lookups
    pixel = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
        b"\r\n\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    return Response(
        content=pixel,
        media_type="image/png",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
    )
