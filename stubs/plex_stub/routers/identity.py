from fastapi import APIRouter
from fastapi.responses import Response

from xml.etree.ElementTree import SubElement

from stubs.plex_stub.xml_builder import build_server_identity, build_media_container, xml_response

router = APIRouter()


@router.get("/")
def server_identity():
    xml = xml_response(build_server_identity())
    return Response(content=xml, media_type="text/xml")


DEMO_SESSIONS = [
    {
        "type": "movie",
        "title": "Inception",
        "ratingKey": "1030",
        "duration": "8880000",
        "viewOffset": "4200000",
        "user": "MovieFan2024",
        "player": "Plex Web",
        "state": "playing",
    },
    {
        "type": "episode",
        "title": "Ozymandias",
        "grandparentTitle": "Breaking Bad",
        "parentIndex": "5",
        "index": "14",
        "ratingKey": "2020",
        "duration": "2820000",
        "viewOffset": "1800000",
        "user": "BingeWatcher",
        "player": "Apple TV",
        "state": "playing",
    },
    {
        "type": "movie",
        "title": "Interstellar",
        "ratingKey": "1032",
        "duration": "10140000",
        "viewOffset": "6600000",
        "user": "CinematicVibes",
        "player": "Plex for Samsung TV",
        "state": "paused",
    },
]


@router.get("/status/sessions")
def active_sessions():
    container = build_media_container(size=str(len(DEMO_SESSIONS)))
    for i, s in enumerate(DEMO_SESSIONS):
        v = SubElement(container, "Video")
        v.set("sessionKey", str(i + 1))
        v.set("type", s["type"])
        v.set("title", s["title"])
        v.set("ratingKey", s["ratingKey"])
        v.set("duration", s["duration"])
        v.set("viewOffset", s["viewOffset"])
        v.set("key", f"/library/metadata/{s['ratingKey']}")
        v.set("librarySectionID", "1")
        v.set("librarySectionTitle", "Movies")
        if s["type"] == "episode":
            v.set("grandparentTitle", s.get("grandparentTitle", ""))
            v.set("parentIndex", s.get("parentIndex", ""))
            v.set("index", s.get("index", ""))
            v.set("librarySectionID", "2")
            v.set("librarySectionTitle", "TV Shows")
        # User
        user = SubElement(v, "User")
        user.set("id", str(i + 1))
        user.set("title", s["user"])
        # Player
        player = SubElement(v, "Player")
        player.set("title", s["player"])
        player.set("state", s["state"])
        player.set("product", s["player"])
    return Response(content=xml_response(container), media_type="text/xml")
