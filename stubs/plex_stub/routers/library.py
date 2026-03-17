from fastapi import APIRouter
from fastapi.responses import Response

from stubs.plex_stub.state import state
from stubs.plex_stub.xml_builder import (
    build_collections,
    build_filtering_meta,
    build_library_sections,
    build_media_container,
    build_video_items,
    xml_response,
)

router = APIRouter()


@router.get("/library")
def library_root():
    # PlexAPI's Library class fetches /library to initialize itself
    container = build_media_container(
        size="0",
        allowSync="1",
        identifier="com.plexapp.plugins.library",
        mediaTagVersion="1",
        title1="Plex Library",
    )
    return Response(content=xml_response(container), media_type="text/xml")


@router.get("/library/sections")
def list_sections():
    xml = xml_response(build_library_sections(state.get_libraries()))
    return Response(content=xml, media_type="text/xml")


@router.get("/library/sections/{section_id}/collections")
def list_collections_endpoint(section_id: str):
    section_title = state.get_section_title(section_id)
    collections = state.get_collections(section_id)
    xml = xml_response(build_collections(collections, section_id, section_title))
    return Response(content=xml, media_type="text/xml")


@router.get("/library/sections/{section_id}/all")
def list_section_items(section_id: str, type: str = None, includeGuids: str = None,
                       title: str = None, year: str = None, includeMeta: str = None,
                       sort: str = None):
    from xml.etree.ElementTree import SubElement
    section_title = state.get_section_title(section_id)
    section = state.get_section(section_id)
    section_type = section["type"] if section else "movie"

    # type=18 means collections
    if type == "18":
        collections = state.get_collections(section_id)
        container = build_collections(collections, section_id, section_title)
        if includeMeta:
            meta = SubElement(container, "Meta")
            for type_elem in build_filtering_meta("collection"):
                meta.append(type_elem)
        return Response(content=xml_response(container), media_type="text/xml")

    # Library items
    items = state.get_items(section_id)

    # Apply filters
    if title:
        items = [i for i in items if title.lower() in i["title"].lower()]
    if year:
        items = [i for i in items if str(i.get("year", "")) == year]

    # Apply sort
    if sort:
        sort_key = sort.split(":")[0]
        sort_desc = sort.endswith(":desc")
        if sort_key == "addedAt":
            items = sorted(items, key=lambda i: i.get("addedAt", 0), reverse=sort_desc)

    if items:
        container = build_video_items(items, section_id, section_title)
    else:
        container = build_media_container(size="0")

    # Add filtering meta if requested
    if includeMeta:
        meta = SubElement(container, "Meta")
        for type_elem in build_filtering_meta(section_type):
            meta.append(type_elem)

    return Response(content=xml_response(container), media_type="text/xml")


@router.get("/library/sections/{section_id}/recentlyAdded")
def recently_added(section_id: str, maxresults: int = 50):
    import time
    items = state.get_items(section_id)
    # Sort by addedAt descending, take maxresults
    items = sorted(items, key=lambda i: i.get("addedAt", 0), reverse=True)[:maxresults]
    # Make top items always "recent" relative to now
    now = int(time.time())
    offsets = [3600, 43200, 86400, 172800, 259200, 345600, 432000, 518400, 604800, 691200]
    items = [dict(item) for item in items]  # shallow copy so we don't mutate fixture
    for i, item in enumerate(items):
        if i < len(offsets):
            item["addedAt"] = now - offsets[i]
    section_title = state.get_section_title(section_id)
    if items:
        xml = xml_response(build_video_items(items, section_id, section_title))
    else:
        xml = xml_response(build_media_container(size="0"))
    return Response(content=xml, media_type="text/xml")



@router.get("/library/metadata/{rating_key}")
def get_metadata(rating_key: str):
    # PlexAPI fetches this for lazy-reload of collection/item details
    coll, section_id = state.find_collection(rating_key)
    if coll:
        section_title = state.get_section_title(section_id)
        xml = xml_response(build_collections([coll], section_id, section_title))
        return Response(content=xml, media_type="text/xml")

    # Check if it's a library item (movie/show)
    for sid in [lib["key"] for lib in state.get_libraries()]:
        for item in state.get_items(str(sid)):
            if str(item["ratingKey"]) == rating_key:
                section_title = state.get_section_title(str(sid))
                xml = xml_response(build_video_items([item], str(sid), section_title))
                return Response(content=xml, media_type="text/xml")

    # Return empty container for unknown items
    return Response(content=xml_response(build_media_container(size="0")), media_type="text/xml")
