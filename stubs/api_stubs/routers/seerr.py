from fastapi import APIRouter, Request
from stubs.api_stubs.fixture_loader import load_json

router = APIRouter(prefix="/seerr")


@router.get("/api/v1/status")
def status():
    return {"version": "2.0.0", "commitTag": "demo", "updateAvailable": False, "commitsBehind": 0}


@router.get("/api/v1/request")
def get_requests(take: int = 20, skip: int = 0, sort: str = "added", sortDirection: str = "desc", filter: str = None):
    data = load_json("seerr", "requests.json")
    results = data.get("results", [])
    return {
        "pageInfo": {"pages": 1, "pageSize": take, "results": len(results), "page": 1},
        "results": results[skip:skip + take],
    }


@router.get("/api/v1/request/{request_id}")
def get_request(request_id: int):
    data = load_json("seerr", "requests.json")
    for r in data.get("results", []):
        if r.get("id") == request_id:
            return r
    return {"id": request_id, "status": 2}


@router.post("/api/v1/request/{request_id}/approve")
def approve_request(request_id: int):
    return {"id": request_id, "status": 2}


@router.post("/api/v1/request/{request_id}/decline")
def decline_request(request_id: int):
    return {"id": request_id, "status": 3}


@router.delete("/api/v1/request/{request_id}")
def delete_request(request_id: int):
    return {}


MOVIE_DATA = {
    1184918: {
        "title": "The Wild Robot",
        "posterPath": "/wTnV3PCVW5O92JMrFvvrRcV39RU.jpg",
        "backdropPath": "/1pmXyN3sKeYoUhu5VBZiDU4BX21.jpg",
        "overview": "After a shipwreck, an intelligent robot called Roz is stranded on an uninhabited island. To survive the harsh environment, Roz bonds with the island's animals and cares for an orphaned baby goose.",
        "releaseDate": "2024-09-27",
        "voteAverage": 8.4,
    },
    822119: {
        "title": "Captain America: Brave New World",
        "posterPath": "/pzIddUEMWhWzfvLI3TwxUG2wGoi.jpg",
        "backdropPath": "/8eifdha9GQeZAkexgtD45546XKx.jpg",
        "overview": "Sam Wilson, the new Captain America, finds himself in the middle of an international incident and must discover the motive behind a nefarious global plot.",
        "releaseDate": "2025-02-14",
        "voteAverage": 6.2,
    },
    693134: {
        "title": "Dune: Part Two",
        "posterPath": "/1pdfLvkbY9ohJlCjQH2CZjjYVvJ.jpg",
        "backdropPath": "/ylkdrn23p3gQcHx7ukIfuy2CkTE.jpg",
        "overview": "Follow the mythic journey of Paul Atreides as he unites with Chani and the Fremen while on a path of revenge against the conspirators who destroyed his family.",
        "releaseDate": "2024-02-27",
        "voteAverage": 8.1,
    },
    762509: {
        "title": "Mufasa: The Lion King",
        "posterPath": "/lurEK87kukWNaHd0zYnsi3yzJrs.jpg",
        "backdropPath": "/1w8kutrRucTd3wlYyu5QlUDMiG1.jpg",
        "overview": "Mufasa, a cub lost and alone, meets a sympathetic lion named Taka, the heir to a royal bloodline. The chance encounter sets in motion an expansive journey of a group of misfits searching for their destiny.",
        "releaseDate": "2024-12-18",
        "voteAverage": 7.1,
    },
    999999: {
        "title": "Unreleased Movie",
        "posterPath": None,
        "backdropPath": None,
        "overview": "This movie has not been released yet.",
        "releaseDate": "2026-12-01",
        "voteAverage": None,
    },
}

TV_DATA = {
    94997: {
        "name": "House of the Dragon",
        "posterPath": "/7QMsOTMUswlwxJP0rTTZfmz2tX2.jpg",
        "backdropPath": "/2xGcSLyTAzConiHAByWqhfLiatT.jpg",
        "overview": "The Targaryen dynasty is at the absolute apex of its power, with more than 15 dragons under their yoke. Most combatants combatants combatants. The Targaryens' political war ignites into full-blown conflict.",
        "firstAirDate": "2022-08-21",
        "voteAverage": 8.4,
    },
    246: {
        "name": "Avatar: The Last Airbender",
        "posterPath": "/v2vn1coUMPKw0GI1KGC5J4IXtqp.jpg",
        "backdropPath": "/kU98MbVVgi72wzceyrEbClZmMFe.jpg",
        "overview": "In a war-torn world of elemental magic, a young boy reawakens to undertake a dangerous mystic quest to fulfill his destiny as the Avatar and bring peace to the world.",
        "firstAirDate": "2005-02-21",
        "voteAverage": 8.7,
    },
}


@router.get("/api/v1/movie/{tmdb_id}")
def get_movie(tmdb_id: int):
    data = MOVIE_DATA.get(tmdb_id, {"title": f"Movie {tmdb_id}", "posterPath": None, "backdropPath": None, "overview": None, "releaseDate": None, "voteAverage": None})
    return {
        "id": tmdb_id, "mediaType": "movie", "title": data["title"],
        "posterPath": data["posterPath"], "backdropPath": data.get("backdropPath"),
        "overview": data.get("overview"), "releaseDate": data.get("releaseDate"),
        "voteAverage": data.get("voteAverage"), "status": "Released",
    }


@router.get("/api/v1/tv/{tmdb_id}")
def get_tv(tmdb_id: int):
    data = TV_DATA.get(tmdb_id, {"name": f"Show {tmdb_id}", "posterPath": None, "backdropPath": None, "overview": None, "firstAirDate": None, "voteAverage": None})
    return {
        "id": tmdb_id, "mediaType": "tv", "name": data["name"],
        "posterPath": data["posterPath"], "backdropPath": data.get("backdropPath"),
        "overview": data.get("overview"), "firstAirDate": data.get("firstAirDate"),
        "voteAverage": data.get("voteAverage"), "status": "Returning Series",
    }


@router.get("/api/v1/movie/{tmdb_id}/ratings")
@router.get("/api/v1/tv/{tmdb_id}/ratings")
def get_ratings(tmdb_id: int):
    return {"criticsRating": "fresh", "criticsScore": 85, "audienceRating": "upright", "audienceScore": 90}


@router.get("/api/v1/search")
def search(query: str = "", page: int = 1):
    return {"results": [], "totalResults": 0, "totalPages": 0, "page": page}


@router.get("/api/v1/settings/radarr")
def radarr_settings():
    return [{"id": 1, "name": "Radarr", "hostname": "localhost", "port": 7878, "isDefault": True}]


@router.get("/api/v1/settings/radarr/{radarr_id}/profiles")
def radarr_profiles(radarr_id: int):
    return [{"id": 1, "name": "HD-1080p"}, {"id": 4, "name": "Ultra-HD"}]


@router.get("/api/v1/settings/sonarr")
def sonarr_settings():
    return [{"id": 1, "name": "Sonarr", "hostname": "localhost", "port": 8989, "isDefault": True}]


@router.get("/api/v1/settings/sonarr/{sonarr_id}/profiles")
def sonarr_profiles(sonarr_id: int):
    return [{"id": 1, "name": "HD-1080p"}, {"id": 4, "name": "Ultra-HD"}]


@router.post("/api/v1/request")
def submit_request(request: Request):
    return {"id": 999, "status": 1, "mediaType": "movie"}
