from fastapi import APIRouter
from stubs.api_stubs.fixture_loader import load_json

router = APIRouter(prefix="/trakt")


@router.get("/movies/popular")
def popular_movies(page: int = 1, limit: int = 10):
    return load_json("trakt", "popular_movies.json")[:limit]


@router.get("/movies/trending")
def trending_movies(page: int = 1, limit: int = 10):
    return load_json("trakt", "trending_movies.json")[:limit]


@router.get("/movies/anticipated")
def anticipated_movies(page: int = 1, limit: int = 10):
    return load_json("trakt", "anticipated_movies.json")[:limit]


@router.get("/shows/popular")
def popular_shows(page: int = 1, limit: int = 10):
    return load_json("trakt", "popular_shows.json")[:limit]


@router.get("/users/{username}/lists/{slug}/items/movies")
def list_items(username: str, slug: str, extended: str = ""):
    return load_json("trakt", "list_items.json")
