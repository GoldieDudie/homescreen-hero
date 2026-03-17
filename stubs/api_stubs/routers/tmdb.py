from fastapi import APIRouter
from stubs.api_stubs.fixture_loader import load_json

router = APIRouter(prefix="/tmdb")


@router.get("/configuration")
def configuration(api_key: str = ""):
    return {"images": {"base_url": "https://image.tmdb.org/t/p/", "secure_base_url": "https://image.tmdb.org/t/p/"}}


@router.get("/list/{list_id}")
def get_list(list_id: str, api_key: str = "", page: int = 1, language: str = "en-US"):
    return load_json("tmdb", "list_items.json")


@router.get("/movie/{tmdb_id}")
def get_movie(tmdb_id: str, api_key: str = ""):
    return {"id": int(tmdb_id), "title": "Demo Movie", "belongs_to_collection": None}


@router.get("/collection/{collection_id}")
def get_collection(collection_id: str, api_key: str = ""):
    return {"id": int(collection_id), "name": "Demo Collection", "parts": []}


@router.get("/search/collection")
def search_collection(api_key: str = "", query: str = "", language: str = "en-US"):
    return {"results": [], "total_pages": 0, "total_results": 0}
