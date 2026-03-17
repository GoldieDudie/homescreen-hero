from fastapi import APIRouter, Request
from fastapi.responses import Response

from stubs.plex_stub.state import state
from stubs.plex_stub.xml_builder import build_media_container, build_video_items, xml_response

router = APIRouter()


@router.get("/library/metadata/{rating_key}/children")
def collection_items(rating_key: str):
    # collection.items() - return children of a collection
    items = state.get_collection_items(rating_key)
    coll, section_id = state.find_collection(rating_key)
    if not section_id:
        section_id = state.get_collection_items_section(rating_key)
    section_title = state.get_section_title(section_id) if section_id else "Unknown"

    if items:
        xml = xml_response(build_video_items(items, section_id, section_title))
    else:
        container = build_media_container(size="0")
        xml = xml_response(container)
    return Response(content=xml, media_type="text/xml")


@router.put("/library/sections/{section_id}/all")
def edit_collection_tags(section_id: str, request: Request):
    # Handles addLabel/removeLabel via PUT with query params
    # PlexAPI sends: type=18&id={ratingKey}&label[0].tag.tag={value}&label.locked=1
    params = dict(request.query_params)
    rating_key = params.get("id", "")

    if not rating_key:
        return Response(content=xml_response(build_media_container(size="0")), media_type="text/xml")

    # Get current labels
    coll, _ = state.find_collection(rating_key)
    current_labels = list(coll.get("labels", [])) if coll else []

    # Check for label additions (label[0].tag.tag, label[1].tag.tag, etc.)
    labels_to_add = []
    for key, value in params.items():
        if key.startswith("label[") and key.endswith("].tag.tag") and "-" not in key:
            labels_to_add.append(value)

    # Check for label removals (label[].tag.tag-)
    labels_to_remove = []
    remove_val = params.get("label[].tag.tag-", "")
    if remove_val:
        labels_to_remove = [l.strip() for l in remove_val.split(",")]

    for label in labels_to_add:
        if label not in current_labels:
            current_labels.append(label)

    for label in labels_to_remove:
        if label in current_labels:
            current_labels.remove(label)

    state.label_overrides[rating_key] = current_labels

    return Response(content=xml_response(build_media_container(size="0")), media_type="text/xml")


@router.put("/library/metadata/{rating_key}")
def edit_collection_metadata(rating_key: str):
    # Handles editTitle, editSummary, etc. - accept and ignore for demo
    return Response(content=xml_response(build_media_container(size="0")), media_type="text/xml")


@router.delete("/library/metadata/{rating_key}")
def delete_collection(rating_key: str):
    # collection.delete() - accept and ignore for demo
    return Response(content=xml_response(build_media_container(size="0")), media_type="text/xml")
