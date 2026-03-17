from fastapi import APIRouter, Request
from stubs.api_stubs.fixture_loader import load_json

router = APIRouter(prefix="/anilist")


@router.post("")
async def graphql(request: Request):
    body = await request.json()
    query = body.get("query", "")
    variables = body.get("variables", {})

    # Route based on query content
    if "Viewer" in query:
        return {"data": {"Viewer": {"id": 1}}}

    if "MediaListCollection" in query:
        if "entries" in query:
            # Full user list with entries
            return load_json("anilist", "user_list.json")
        else:
            # Just list names
            return load_json("anilist", "user_lists.json")

    if "Page" in query:
        # Browse query
        return load_json("anilist", "browse.json")

    return {"data": {}}
