from fastapi import APIRouter, Request
from fastapi.responses import Response

from stubs.plex_stub.state import state
from stubs.plex_stub.xml_builder import build_managed_hubs, xml_response

router = APIRouter()


@router.get("/hubs/sections/{section_id}/manage")
def get_managed_hubs(section_id: str, metadataItemId: str = None):
    if metadataItemId:
        # collection.visibility() call - return hub for specific collection
        identifier = state.get_hub_identifier(section_id, metadataItemId)
        vis = state.hub_visibility.get(identifier, {})
        hub = {
            "identifier": identifier,
            "title": "",
            "deletable": "1",
            "homeVisibility": "none",
            "recommendationsVisibility": "none",
            "promotedToOwnHome": str(vis.get("promotedToOwnHome", 0)),
            "promotedToSharedHome": str(vis.get("promotedToSharedHome", 0)),
            "promotedToRecommended": str(vis.get("promotedToRecommended", 0)),
        }
        # Try to find the collection title
        coll, _ = state.find_collection(metadataItemId)
        if coll:
            hub["title"] = coll["title"]
        xml = xml_response(build_managed_hubs([hub]))
        return Response(content=xml, media_type="text/xml")

    # managedHubs() call - return all hubs for section
    hubs = state.get_managed_hubs(section_id)
    xml = xml_response(build_managed_hubs(hubs))
    return Response(content=xml, media_type="text/xml")


@router.post("/hubs/sections/{section_id}/manage")
def create_managed_hub(
    section_id: str,
    metadataItemId: str = None,
    promotedToOwnHome: int = 0,
    promotedToSharedHome: int = 0,
    promotedToRecommended: int = 0,
):
    # updateVisibility() for non-promoted collections (first promotion)
    identifier = state.get_hub_identifier(section_id, metadataItemId)
    state.update_visibility(section_id, identifier, promotedToOwnHome, promotedToSharedHome, promotedToRecommended)

    vis = state.hub_visibility[identifier]
    hub = {
        "identifier": identifier,
        "title": "",
        "deletable": "1",
        "homeVisibility": "none",
        "recommendationsVisibility": "none",
        "promotedToOwnHome": str(vis["promotedToOwnHome"]),
        "promotedToSharedHome": str(vis["promotedToSharedHome"]),
        "promotedToRecommended": str(vis["promotedToRecommended"]),
    }
    coll, _ = state.find_collection(metadataItemId)
    if coll:
        hub["title"] = coll["title"]
    xml = xml_response(build_managed_hubs([hub]))
    return Response(content=xml, media_type="text/xml")


@router.put("/hubs/sections/{section_id}/manage/{identifier:path}")
def update_managed_hub(
    section_id: str,
    identifier: str,
    promotedToOwnHome: int = None,
    promotedToSharedHome: int = None,
    promotedToRecommended: int = None,
):
    # Check if this is a move request (identifier ends with /move)
    if identifier.endswith("/move"):
        return _handle_move(section_id, identifier[:-5])

    state.update_visibility(section_id, identifier, promotedToOwnHome, promotedToSharedHome, promotedToRecommended)

    vis = state.hub_visibility.get(identifier, {})
    hub = {
        "identifier": identifier,
        "title": "",
        "deletable": "1",
        "homeVisibility": "none",
        "recommendationsVisibility": "none",
        "promotedToOwnHome": str(vis.get("promotedToOwnHome", 0)),
        "promotedToSharedHome": str(vis.get("promotedToSharedHome", 0)),
        "promotedToRecommended": str(vis.get("promotedToRecommended", 0)),
    }
    xml = xml_response(build_managed_hubs([hub]))
    return Response(content=xml, media_type="text/xml")


def _handle_move(section_id: str, identifier: str, after: str = None):
    state.move_hub(section_id, identifier, after)
    hubs = state.get_managed_hubs(section_id)
    xml = xml_response(build_managed_hubs(hubs))
    return Response(content=xml, media_type="text/xml")
