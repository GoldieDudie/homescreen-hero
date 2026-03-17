from fastapi import APIRouter
from stubs.api_stubs.fixture_loader import load_json

router = APIRouter(prefix="/mal")


@router.get("/anime/ranking")
def anime_ranking(ranking_type: str = "all", limit: int = 10, offset: int = 0, fields: str = "", nsfw: str = "true"):
    data = load_json("mal", "ranking.json")
    items = data.get("data", [])
    return {"data": items[offset:offset + limit], "paging": {}}


@router.get("/users/{username}/animelist")
def user_animelist(username: str, fields: str = "", limit: int = 100, offset: int = 0, nsfw: str = "true", status: str = None):
    data = load_json("mal", "user_list.json")
    items = data.get("data", [])
    return {"data": items[offset:offset + limit], "paging": {}}


@router.get("/anime/season/{year}/{season}")
def seasonal_anime(year: int, season: str, sort: str = "anime_score", limit: int = 10, offset: int = 0, fields: str = "", nsfw: str = "true"):
    data = load_json("mal", "ranking.json")
    items = data.get("data", [])
    return {"data": items[offset:offset + limit], "paging": {}}
