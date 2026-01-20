# Mock Plex client for demo/testing purposes
# Provides realistic sample data without requiring a real Plex Media Server

from __future__ import annotations

import logging
from typing import Dict, List
from datetime import datetime

logger = logging.getLogger(__name__)


class MockVisibility:
    # Mock visibility object for collections

    def __init__(self, collection_title: str, is_active: bool = False):
        self.collection_title = collection_title
        self.home = is_active
        self.shared = False
        self.recommended = False
        self.promotedToOwnHome = is_active

    def updateVisibility(self, home: bool = False, shared: bool = False, recommended: bool = False):
        self.home = home
        self.shared = shared
        self.recommended = recommended
        self.promotedToOwnHome = home
        logger.info(
            "[MOCK] Updated visibility for '%s': home=%s, shared=%s, recommended=%s",
            self.collection_title, home, shared, recommended
        )


class MockMediaItem:
    # Mock media item (movie or show)

    # TMDb poster paths for sample content
    TMDB_POSTERS = {
        # Movies
        "The Shawshank Redemption": "/9cqNxx0GxF0bflZmeSMuL5tnGzr.jpg",
        "The Godfather": "/3bhkrj58Vtu7enYsRolD1fZdja1.jpg",
        "The Dark Knight": "/qJ2tW6WMUDux911r6m7haRef0WH.jpg",
        "Pulp Fiction": "/d5iIlFn5s0ImszYzBPb8JPIfbXD.jpg",
        "Forrest Gump": "/arw2vcBveWOVZr6pxd9XTd1TdQa.jpg",
        "Inception": "/oYuLEt3zVCKq57qu2F8dT7NIa6f.jpg",
        "The Matrix": "/f89U3ADr1oiB1s9GkdPOEpXUk5H.jpg",
        "Goodfellas": "/aKuFiU82s5ISJpGZp7YkIr3kCUd.jpg",
        "The Silence of the Lambs": "/uS9m8OBk1A8eM9I042bx8XXpqAq.jpg",
        "Saving Private Ryan": "/uqx37cS8cpHg8U35f9U5IBlrCV3.jpg",
        "Interstellar": "/gEU2QniE6E77NI6lCU6MxlNBvIx.jpg",
        "Gladiator": "/ty8TGRuvJLPUmAR1H1nRIsgwvim.jpg",
        "Spirited Away": "/39wmItIWsg5sZMyRUHLkWBcuVCM.jpg",
        "Princess Mononoke": "/jHWmNr7m544fJ8eItsfNk8fs2Ed.jpg",
        "My Neighbor Totoro": "/rtGDOeG9LzoerkDGZF9dnVeLppL.jpg",
        "Die Hard": "/yFihWxQcmqcaBR31QM6Y8gT6aYV.jpg",
        "Terminator 2: Judgment Day": "/5M0j0B18abtBI5gi2RhfjjurTqb.jpg",
        "Oppenheimer": "/8Gxv8gSFCU0XGDykEGv7zR1n2ua.jpg",
        "Barbie": "/iuFNMS8U5cb6xfzi51Dbkovj7vM.jpg",
        "Dune": "/d5NXSklXo0qyIYkgV94XAgMIckC.jpg",
        # TV Shows
        "Breaking Bad": "/ztkUQFLlC19CCMYHW9o1zWhJRNq.jpg",
        "The Sopranos": "/rTc7ZXdroqjkKivFPvCPX0Ru7uw.jpg",
        "The Wire": "/4lbclFySvugI51fwsyxBTOm4DqK.jpg",
        "Game of Thrones": "/1XS1oqL89opfnbLl8WnZY1O1uJx.jpg",
        "Friends": "/f496cm9enuEsZkSPzCwnTESEK5s.jpg",
        "The Office": "/7DJKHzAi83BmQrWLrYYOqcoKfhR.jpg",
    }

    def __init__(self, title: str, year: int = 2020, media_type: str = "movie"):
        self.title = title
        self.year = year
        self.type = media_type
        self.ratingKey = hash(title) % 100000
        self.thumb = self.TMDB_POSTERS.get(title, "/default.jpg")


class MockCollection:
    # Mock Plex collection

    DEMO_COLLECTIONS = {
        "Movies": {
            "Oscar Winners 2024": ["Oppenheimer", "Barbie", "The Holdovers"],
            "Best Picture Winners": ["The Godfather", "Forrest Gump", "Gladiator"],
            "Criterion Collection": ["Spirited Away", "The Silence of the Lambs", "Pulp Fiction"],
            "80s Action Classics": ["Die Hard", "Terminator 2: Judgment Day", "Predator"],
            "Nolan Collection": ["The Dark Knight", "Inception", "Interstellar"],
            "90s Crime Dramas": ["Goodfellas", "Pulp Fiction", "The Shawshank Redemption"],
            "Sci-Fi Essentials": ["The Matrix", "Interstellar", "Dune"],
            "Studio Ghibli Films": ["Spirited Away", "Princess Mononoke", "My Neighbor Totoro"],
            "Modern Comedy Classics": ["Barbie", "The Grand Budapest Hotel"],
        },
        "TV Shows": {
            "HBO Prestige Dramas": ["The Sopranos", "The Wire", "Game of Thrones"],
            "90s Sitcoms": ["Friends", "Seinfeld"],
            "British Comedy": ["The Office UK", "Fawlty Towers"],
            "Anime Classics": ["Cowboy Bebop", "Neon Genesis Evangelion"],
        },
    }

    def __init__(self, title: str, library_name: str = "Movies"):
        self.title = title
        self.librarySectionTitle = library_name
        self.ratingKey = hash(title) % 100000
        self.addedAt = datetime.now()
        self._visibility = MockVisibility(title)

        # Build mock items
        items_titles = self.DEMO_COLLECTIONS.get(library_name, {}).get(title, [])
        media_type = "movie" if library_name == "Movies" else "show"
        self._items = [MockMediaItem(t, media_type=media_type) for t in items_titles]

    def items(self) -> List[MockMediaItem]:
        return self._items

    def visibility(self) -> MockVisibility:
        return self._visibility

    def delete(self):
        logger.info("[MOCK] Deleted collection: %s", self.title)


class MockLibrarySection:
    # Mock Plex library section

    def __init__(self, name: str, library_type: str = "movie"):
        self.title = name
        self.type = library_type
        self._collections = self._build_collections(name)

    def _build_collections(self, library_name: str) -> Dict[str, MockCollection]:
        collections = {}
        demo_colls = MockCollection.DEMO_COLLECTIONS.get(library_name, {})
        for coll_name in demo_colls:
            collections[coll_name] = MockCollection(coll_name, library_name)
        return collections

    def collections(self) -> List[MockCollection]:
        return list(self._collections.values())

    def search(self, title: str = None, **kwargs) -> List[MockMediaItem]:
        # Return mock search results
        all_items = []
        for coll in self._collections.values():
            all_items.extend(coll.items())
        if title:
            return [i for i in all_items if title.lower() in i.title.lower()]
        return all_items


class MockLibrary:
    # Mock Plex library manager

    def __init__(self):
        self._sections = {
            "Movies": MockLibrarySection("Movies", "movie"),
            "TV Shows": MockLibrarySection("TV Shows", "show"),
            "Anime": MockLibrarySection("Anime", "movie"),
        }

    def section(self, name: str) -> MockLibrarySection:
        if name not in self._sections:
            logger.warning("[MOCK] Library '%s' not found, returning empty library", name)
            return MockLibrarySection(name, "movie")
        return self._sections[name]

    def sections(self) -> List[MockLibrarySection]:
        return list(self._sections.values())


class MockPlexServer:
    # Mock PlexServer for demo mode

    def __init__(self, base_url: str = "http://mock:32400", token: str = "mock-token"):
        self.base_url = base_url
        self.token = token
        self.friendlyName = "Demo Plex Server"
        self.version = "1.32.0.0000-demo"
        self.library = MockLibrary()
        logger.info("[MOCK] Created MockPlexServer at %s", base_url)

    def fetchItem(self, rating_key: int):
        # Return a mock item
        return MockMediaItem(f"Item-{rating_key}")


def get_mock_plex_server(config) -> MockPlexServer:
    # Factory function matching the real get_plex_server signature
    return MockPlexServer(
        base_url=config.plex.base_url,
        token=config.plex.token,
    )
