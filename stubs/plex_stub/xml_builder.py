from xml.etree.ElementTree import Element, SubElement, tostring

def xml_response(root: Element) -> str:
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(root, encoding="unicode")


def build_media_container(**attrs) -> Element:
    container = Element("MediaContainer")
    for k, v in attrs.items():
        container.set(k, str(v))
    return container


def build_server_identity() -> Element:
    return build_media_container(
        allowCameraUpload="1",
        allowChannelAccess="1",
        allowMediaDeletion="1",
        allowSharing="1",
        allowSync="1",
        backgroundProcessing="1",
        certificate="1",
        companionProxy="0",
        diagnostics="",
        eventStream="1",
        friendlyName="Demo Plex Server",
        hubSearch="1",
        machineIdentifier="demo-server-001",
        multiuser="1",
        myPlex="1",
        myPlexMappingState="mapped",
        myPlexSigninState="ok",
        myPlexSubscription="1",
        myPlexUsername="demo@example.com",
        ownerFeatures="camera_upload,cloudsync,dvr,hardware_transcoding",
        photoAutoTag="1",
        platform="Linux",
        platformVersion="6.1",
        pluginHost="0",
        readOnlyLibraries="0",
        requestParametersInCookie="0",
        streamingBrainVersion="2",
        sync="1",
        transcoderActiveVideoSessions="0",
        transcoderAudio="1",
        transcoderLyrics="1",
        transcoderPhoto="1",
        transcoderSubtitles="1",
        transcoderVideo="1",
        transcoderVideoBitrates="64,96,208,720,1500,2000,3000,4000,8000,16000",
        transcoderVideoQualities="0,1,2,3,4,5,6,7,8,9,10,11",
        transcoderVideoResolutions="128x32,220x62,300x200,384x216,480x270,600x400,768x432,1024x576,1280x720,1400x1050",
        updatedAt="1700000000",
        updater="1",
        version="1.40.0.1234-demo",
        voiceSearch="1",
    )


def build_library_sections(sections: list[dict]) -> Element:
    container = build_media_container(
        size=str(len(sections)),
        allowSync="1",
        identifier="com.plexapp.plugins.library",
        mediaTagVersion="1",
        title1="Plex Library",
    )
    for section in sections:
        directory = SubElement(container, "Directory")
        directory.set("allowSync", "1")
        directory.set("art", f"/library/sections/{section['key']}/art/1700000000")
        directory.set("composite", f"/library/sections/{section['key']}/composite/1700000000")
        directory.set("createdAt", "1700000000")
        directory.set("filters", "1")
        directory.set("key", str(section["key"]))
        directory.set("language", "en")
        directory.set("refreshing", "0")
        directory.set("scanner", section.get("scanner", "Plex Movie"))
        directory.set("thumb", f"/library/sections/{section['key']}/thumb/1700000000")
        directory.set("title", section["title"])
        directory.set("type", section["type"])
        directory.set("updatedAt", "1700000000")
        directory.set("uuid", section.get("uuid", f"demo-uuid-{section['key']}"))
        directory.set("agent", section.get("agent", "tv.plex.agents.movie"))
        loc = SubElement(directory, "Location")
        loc.set("id", str(section["key"]))
        loc.set("path", section.get("path", f"/media/{section['type']}"))
    return container


def build_collections(collections: list[dict], section_id: str, section_title: str) -> Element:
    container = build_media_container(
        size=str(len(collections)),
        allowSync="1",
        identifier="com.plexapp.plugins.library",
        librarySectionID=section_id,
        librarySectionTitle=section_title,
        librarySectionUUID=f"demo-uuid-{section_id}",
        mediaTagVersion="1",
    )
    for coll in collections:
        d = SubElement(container, "Directory")
        d.set("addedAt", str(coll.get("addedAt", "1700000000")))
        d.set("childCount", str(coll.get("childCount", 0)))
        d.set("collectionMode", str(coll.get("collectionMode", "-1")))
        d.set("collectionSort", str(coll.get("collectionSort", "0")))
        d.set("content", coll.get("content", ""))
        d.set("contentRating", coll.get("contentRating", ""))
        d.set("guid", coll.get("guid", f"collection://demo-{coll['ratingKey']}"))
        d.set("index", str(coll.get("index", "1")))
        d.set("key", f"/library/metadata/{coll['ratingKey']}")
        d.set("librarySectionID", section_id)
        d.set("librarySectionKey", f"/library/sections/{section_id}")
        d.set("librarySectionTitle", section_title)
        d.set("maxYear", str(coll.get("maxYear", "2024")))
        d.set("minYear", str(coll.get("minYear", "2000")))
        d.set("ratingKey", str(coll["ratingKey"]))
        d.set("smart", str(coll.get("smart", "0")))
        d.set("subtype", coll.get("subtype", "movie"))
        d.set("summary", coll.get("summary", ""))
        d.set("thumb", coll.get("thumb", f"/library/metadata/{coll['ratingKey']}/thumb/1700000000"))
        d.set("title", coll["title"])
        d.set("titleSort", coll.get("titleSort", coll["title"]))
        d.set("type", "collection")
        d.set("updatedAt", str(coll.get("updatedAt", "1700000000")))
        # Add labels if present
        for label in coll.get("labels", []):
            lbl = SubElement(d, "Label")
            lbl.set("tag", label)
    return container


def build_filtering_meta(section_type: str) -> list[Element]:
    # Build Meta elements that PlexAPI needs for sort/filter validation
    # section_type is "movie" or "show"
    type_elem = Element("Type")
    type_elem.set("key", f"/library/sections/1/all?type=1")
    type_elem.set("type", section_type)
    type_elem.set("title", section_type.capitalize() + "s")
    type_elem.set("active", "0")

    # Add common sort fields
    for sort_key in ["titleSort", "year", "rating", "audienceRating", "duration",
                     "addedAt", "originallyAvailableAt", "lastViewedAt", "mediaHeight",
                     "random"]:
        sort = SubElement(type_elem, "Sort")
        sort.set("key", sort_key)
        sort.set("title", sort_key)
        sort.set("defaultDirection", "asc" if sort_key == "titleSort" else "desc")

    return [type_elem]


def build_managed_hubs(hubs: list[dict]) -> Element:
    container = build_media_container(size=str(len(hubs)))
    for hub in hubs:
        h = SubElement(container, "Hub")
        h.set("identifier", hub["identifier"])
        h.set("title", hub["title"])
        h.set("deletable", str(hub.get("deletable", "1")))
        h.set("homeVisibility", hub.get("homeVisibility", "none"))
        h.set("recommendationsVisibility", hub.get("recommendationsVisibility", "none"))
        h.set("promotedToOwnHome", str(hub.get("promotedToOwnHome", "0")))
        h.set("promotedToSharedHome", str(hub.get("promotedToSharedHome", "0")))
        h.set("promotedToRecommended", str(hub.get("promotedToRecommended", "0")))
    return container


def build_video_items(items: list[dict], section_id: str, section_title: str) -> Element:
    container = build_media_container(
        size=str(len(items)),
        allowSync="1",
        identifier="com.plexapp.plugins.library",
        librarySectionID=section_id,
        librarySectionTitle=section_title,
        librarySectionUUID=f"demo-uuid-{section_id}",
        mediaTagVersion="1",
    )
    for item in items:
        v = SubElement(container, "Video")
        v.set("ratingKey", str(item["ratingKey"]))
        v.set("key", f"/library/metadata/{item['ratingKey']}")
        v.set("type", item.get("type", "movie"))
        v.set("title", item["title"])
        v.set("year", str(item.get("year", "")))
        v.set("thumb", item.get("thumb", f"/library/metadata/{item['ratingKey']}/thumb/1700000000"))
        v.set("addedAt", str(item.get("addedAt", "1700000000")))
        v.set("updatedAt", str(item.get("updatedAt", "1700000000")))
        v.set("librarySectionID", section_id)
        v.set("librarySectionKey", f"/library/sections/{section_id}")
        v.set("librarySectionTitle", section_title)
        v.set("duration", str(item.get("duration", "7200000")))
        v.set("contentRating", item.get("contentRating", ""))
        # Primary GUID
        v.set("guid", item.get("guid", f"plex://movie/demo-{item['ratingKey']}"))
        # External GUIDs
        for guid_id in item.get("guids", []):
            g = SubElement(v, "Guid")
            g.set("id", guid_id)
        # Genres
        for genre in item.get("genres", []):
            ge = SubElement(v, "Genre")
            ge.set("tag", genre)
        # Media (for resolution info)
        if "videoResolution" in item:
            media = SubElement(v, "Media")
            media.set("videoResolution", item["videoResolution"])
    return container
