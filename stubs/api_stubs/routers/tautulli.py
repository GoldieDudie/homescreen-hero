from fastapi import APIRouter, Request
from stubs.api_stubs.fixture_loader import load_json

router = APIRouter(prefix="/tautulli")


def _wrap(data):
    return {"response": {"result": "success", "data": data}}


@router.get("/api/v2")
def tautulli_api(request: Request, cmd: str = "", apikey: str = ""):
    # Route based on Tautulli command
    params = dict(request.query_params)
    handler = COMMAND_HANDLERS.get(cmd)
    if handler:
        return handler(params)
    return _wrap({})


def _get_activity(params):
    return _wrap(load_json("tautulli", "activity.json"))


def _get_libraries_table(params):
    return _wrap(load_json("tautulli", "libraries.json"))


def _get_library_media_info(params):
    return _wrap(load_json("tautulli", "library_media_info.json"))


def _get_item_watch_time_stats(params):
    return _wrap(load_json("tautulli", "item_watch_time_stats.json"))


def _get_history(params):
    return _wrap(load_json("tautulli", "history.json"))


def _get_user_watch_time_stats(params):
    return _wrap(load_json("tautulli", "user_watch_time_stats.json"))


def _get_users_table(params):
    return _wrap(load_json("tautulli", "users_table.json"))


def _get_home_stats(params):
    return _wrap(load_json("tautulli", "home_stats.json"))


def _get_plays_by_date(params):
    return _wrap(load_json("tautulli", "plays_by_date.json"))


def _get_plays_by_hourofday(params):
    return _wrap(load_json("tautulli", "plays_by_hourofday.json"))


def _get_stream_type_by_top_10_users(params):
    return _wrap(load_json("tautulli", "stream_type_by_users.json"))


def _get_plays_by_stream_type(params):
    return _wrap(load_json("tautulli", "plays_by_stream_type.json"))


COMMAND_HANDLERS = {
    "get_activity": _get_activity,
    "get_libraries_table": _get_libraries_table,
    "get_library_media_info": _get_library_media_info,
    "get_item_watch_time_stats": _get_item_watch_time_stats,
    "get_history": _get_history,
    "get_user_watch_time_stats": _get_user_watch_time_stats,
    "get_users_table": _get_users_table,
    "get_home_stats": _get_home_stats,
    "get_plays_by_date": _get_plays_by_date,
    "get_plays_by_hourofday": _get_plays_by_hourofday,
    "get_stream_type_by_top_10_users": _get_stream_type_by_top_10_users,
    "get_plays_by_stream_type": _get_plays_by_stream_type,
}
