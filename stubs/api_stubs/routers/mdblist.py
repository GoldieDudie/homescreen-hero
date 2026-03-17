from fastapi import APIRouter
from stubs.api_stubs.fixture_loader import load_json

router = APIRouter(prefix="/mdblist")


@router.get("/user")
def ping(apikey: str = ""):
    return {"username": "demo_user", "api_requests": 100, "api_requests_remaining": 90}


@router.get("/lists/{username}/{listname}/items")
def list_items(username: str, listname: str, apikey: str = "", limit: int = 100, offset: int = 0):
    data = load_json("mdblist", "list_items.json")
    movies = data.get("movies", [])
    return {"movies": movies[offset:offset + limit]}
