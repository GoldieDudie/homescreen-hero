import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


class DemoState:
    # Mutable in-memory state for the Plex stub.
    # Tracks visibility changes, hub ordering, and label edits.

    # Collections that start promoted on the homescreen
    INITIAL_PINNED = {
        # Pinned collections (always on homescreen)
        "custom.collection.1.10011": {"promotedToOwnHome": 1, "promotedToSharedHome": 1, "promotedToRecommended": 0},  # Trending Movies
        "custom.collection.1.10012": {"promotedToOwnHome": 1, "promotedToSharedHome": 0, "promotedToRecommended": 0},  # Recently Downloaded Movies
        "custom.collection.2.20003": {"promotedToOwnHome": 1, "promotedToSharedHome": 1, "promotedToRecommended": 0},  # Currently Airing on TV
        # Rotation-selected collections (simulating a recent rotation)
        "custom.collection.1.10001": {"promotedToOwnHome": 1, "promotedToSharedHome": 1, "promotedToRecommended": 0},  # Oscar Winners 2024
        "custom.collection.1.10006": {"promotedToOwnHome": 1, "promotedToSharedHome": 1, "promotedToRecommended": 0},  # Sci-Fi Essentials
        "custom.collection.1.10003": {"promotedToOwnHome": 1, "promotedToSharedHome": 0, "promotedToRecommended": 0},  # Studio Ghibli Films
        "custom.collection.2.20001": {"promotedToOwnHome": 1, "promotedToSharedHome": 0, "promotedToRecommended": 0},  # HBO Prestige Dramas
    }

    def __init__(self):
        self._server_data = None
        self.hub_visibility = dict(self.INITIAL_PINNED)
        self.hub_order = {}  # {section_id: [identifier1, identifier2, ...]}
        self.label_overrides = {}  # {ratingKey: [label1, label2, ...]}

    @property
    def server_data(self) -> dict:
        if self._server_data is None:
            self._server_data = json.loads((FIXTURES / "server.json").read_text())
        return self._server_data

    def get_libraries(self) -> list[dict]:
        return self.server_data["libraries"]

    def get_section(self, section_id: str) -> dict | None:
        for lib in self.get_libraries():
            if str(lib["key"]) == section_id:
                return lib
        return None

    def get_section_title(self, section_id: str) -> str:
        section = self.get_section(section_id)
        return section["title"] if section else "Unknown"

    def get_collections(self, section_id: str) -> list[dict]:
        colls = self.server_data["collections"].get(section_id, [])
        # Apply label overrides
        result = []
        for coll in colls:
            coll_copy = dict(coll)
            rk = str(coll["ratingKey"])
            if rk in self.label_overrides:
                coll_copy["labels"] = self.label_overrides[rk]
            result.append(coll_copy)
        return result

    def find_collection(self, rating_key: str) -> tuple[dict | None, str]:
        for section_id, colls in self.server_data["collections"].items():
            for coll in colls:
                if str(coll["ratingKey"]) == rating_key:
                    coll_copy = dict(coll)
                    if rating_key in self.label_overrides:
                        coll_copy["labels"] = self.label_overrides[rating_key]
                    return coll_copy, section_id
        return None, ""

    def get_hub_identifier(self, section_id: str, rating_key: str) -> str:
        return f"custom.collection.{section_id}.{rating_key}"

    def get_managed_hubs(self, section_id: str) -> list[dict]:
        colls = self.get_collections(section_id)
        hubs = []
        for coll in colls:
            rk = str(coll["ratingKey"])
            identifier = self.get_hub_identifier(section_id, rk)
            vis = self.hub_visibility.get(identifier, {})
            hubs.append({
                "identifier": identifier,
                "title": coll["title"],
                "deletable": "1",
                "homeVisibility": "none",
                "recommendationsVisibility": "none",
                "promotedToOwnHome": str(vis.get("promotedToOwnHome", 0)),
                "promotedToSharedHome": str(vis.get("promotedToSharedHome", 0)),
                "promotedToRecommended": str(vis.get("promotedToRecommended", 0)),
            })

        # Apply ordering if set
        order = self.hub_order.get(section_id)
        if order:
            order_map = {ident: idx for idx, ident in enumerate(order)}
            hubs.sort(key=lambda h: order_map.get(h["identifier"], 999))

        return hubs

    def update_visibility(self, section_id: str, identifier: str,
                          home: int | None = None, shared: int | None = None,
                          recommended: int | None = None):
        current = self.hub_visibility.get(identifier, {
            "promotedToOwnHome": 0,
            "promotedToSharedHome": 0,
            "promotedToRecommended": 0,
        })
        if home is not None:
            current["promotedToOwnHome"] = home
        if shared is not None:
            current["promotedToSharedHome"] = shared
        if recommended is not None:
            current["promotedToRecommended"] = recommended
        self.hub_visibility[identifier] = current

    def move_hub(self, section_id: str, identifier: str, after: str | None = None):
        hubs = self.get_managed_hubs(section_id)
        identifiers = [h["identifier"] for h in hubs]

        if identifier not in identifiers:
            return

        identifiers.remove(identifier)
        if after is None:
            # Move to top
            identifiers.insert(0, identifier)
        elif after in identifiers:
            idx = identifiers.index(after)
            identifiers.insert(idx + 1, identifier)
        else:
            identifiers.append(identifier)

        self.hub_order[section_id] = identifiers

    def get_items(self, section_id: str) -> list[dict]:
        return self.server_data.get("items", {}).get(section_id, [])

    def get_collection_items(self, rating_key: str) -> list[dict]:
        # collection_items maps ratingKey -> list of item ratingKeys
        item_keys = self.server_data.get("collection_items", {}).get(str(rating_key), [])
        if not item_keys:
            return []

        # Build a lookup of all items across all sections
        item_lookup = {}
        for section_id, items in self.server_data.get("items", {}).items():
            for item in items:
                item_lookup[item["ratingKey"]] = (item, section_id)

        result = []
        for key in item_keys:
            if key in item_lookup:
                result.append(item_lookup[key][0])
        return result

    def get_collection_items_section(self, rating_key: str) -> str:
        # Find which section a collection's items belong to
        item_keys = self.server_data.get("collection_items", {}).get(str(rating_key), [])
        if not item_keys:
            return ""
        for section_id, items in self.server_data.get("items", {}).items():
            for item in items:
                if item["ratingKey"] == item_keys[0]:
                    return section_id
        return ""

    def reset(self):
        self.hub_visibility = dict(self.INITIAL_PINNED)
        self.hub_order.clear()
        self.label_overrides.clear()


# Singleton state instance
state = DemoState()
