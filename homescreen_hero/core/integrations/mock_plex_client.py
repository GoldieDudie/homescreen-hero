# Mock Plex client for demo/testing purposes
# Provides realistic sample data without requiring a real Plex Media Server

from __future__ import annotations

import logging
from typing import Dict, List
from datetime import datetime

logger = logging.getLogger(__name__)


class MockPlayer:
    # Mock player object for sessions

    def __init__(self, state: str = "playing", device: str = "Chrome", platform: str = "Windows"):
        self.state = state
        self.device = device
        self.platform = platform


class MockSession:
    # Mock session object for active streams

    def __init__(
        self,
        title: str,
        username: str,
        media_type: str = "movie",
        state: str = "playing",
        view_offset: int = 0,
        duration: int = 7200000,
        grandparent_title: str = None,
    ):
        self.title = title
        self.usernames = [username]
        self.username = username
        self.type = media_type
        self.grandparentTitle = grandparent_title
        self.viewOffset = view_offset
        self.duration = duration
        self.players = [MockPlayer(state=state)]


class MockVisibility:
    # Mock visibility object for collections

    def __init__(self, collection_title: str, is_active: bool = False, is_shared: bool = False):
        self.collection_title = collection_title
        self.home = is_active
        self.shared = is_shared
        self.recommended = False
        self.promotedToOwnHome = is_active
        self.promotedToSharedHome = is_shared
        self.promotedToRecommended = False

    def updateVisibility(self, home: bool = False, shared: bool = False, recommended: bool = False):
        self.home = home
        self.shared = shared
        self.recommended = recommended
        self.promotedToOwnHome = home
        self.promotedToSharedHome = shared
        self.promotedToRecommended = recommended
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
        "The Green Mile": "/8VG8fDNiy50H4FedGwdSVUPoaJe.jpg",
        "Interstellar": "/gEU2QniE6E77NI6lCU6MxlNBvIx.jpg",
        "Gladiator": "/ty8TGRuvJLPUmAR1H1nRIsgwvim.jpg",
        "The Departed": "/nT97ifVT2J1yMQmeq20Qblg61T.jpg",
        "The Prestige": "/tRNlZbgNCNOpLpbPEz5L8G8A0JN.jpg",
        "Whiplash": "/7fn624j5lj3xTme2SgiLCeuedmO.jpg",
        "The Lion King": "/sKCr78MXSLixwmZ8DyJLrpMsd15.jpg",
        "Spirited Away": "/39wmItIWsg5sZMyRUHLkWBcuVCM.jpg",
        "Princess Mononoke": "/jHWmNr7m544fJ8eItsfNk8fs2Ed.jpg",
        "My Neighbor Totoro": "/rtGDOeG9LzoerkDGZF9dnVeLppL.jpg",
        "Howl's Moving Castle": "/13kOl2v0nD2OLbVSHnHk8GUFEhO.jpg",
        "Die Hard": "/yFihWxQcmqcaBR31QM6Y8gT6aYV.jpg",
        "Terminator 2: Judgment Day": "/5M0j0B18abtBI5gi2RhfjjurTqb.jpg",
        "RoboCop": "/esmAU0fCO28FbS6bUBKLAzJrohZ.jpg",
        "Predator": "/k3mW4qfJo6SKqe6laRyNGnbB9n5.jpg",
        "The Breakfast Club": "/wM9ErA8UVdcce5P4oefQinN8VVV.jpg",
        "Ferris Bueller's Day Off": "/9LTQNCvoLsKXP0LtaKAaYVtRaQL.jpg",
        "Back to the Future": "/fNOH9f1aA7XRTzl1sAOx9iF553Q.jpg",
        "Oppenheimer": "/8Gxv8gSFCU0XGDykEGv7zR1n2ua.jpg",
        "Everything Everywhere All at Once": "/w3LxiVYdWWRvEVdn5RYq6jIqkb1.jpg",
        "The Batman": "/74xTEgt7R36Fpooo50r9T25onhq.jpg",
        "Barbie": "/iuFNMS8U5cb6xfzi51Dbkovj7vM.jpg",
        "Dune": "/d5NXSklXo0qyIYkgV94XAgMIckC.jpg",
        "Dune: Part Two": "/1pdfLvkbY9ohJlCjQH2CZjjYVvJ.jpg",
        "The Dark Knight Rises": "/qJ2tW6WMUDux911r6m7haRef0WH.jpg",
        "The Lord of the Rings: The Return of the King": "/rCzpDGLbOoPwLjy3OAm5NUPOTrC.jpg",
        "The Matrix Reloaded": "/p96dm7sCMn4VYAStA6siNz30G1r.jpg",
        "The Lord of the Rings: The Fellowship of the Ring": "/6oom5QYQ2yQTMJIbnvbkBL9cHo6.jpg",
        "The Lord of the Rings: The Two Towers": "/5VTN0pR8gcqV3EPUHHfMGnJYN9L.jpg",
        "Star Wars": "/6FfCtAuVAW8XJjZ7eWeLibRLWTw.jpg",
        "Iron Man": "/78lPtwv72eTNqFW9COBYI0dWDJa.jpg",
        "Avengers: Infinity War": "/7WsyChQLEftFiDOVTGkv3hFpyyt.jpg",
        "Avengers: Endgame": "/bR8ISy1O9XQxqiy0fQFw2BX72RQ.jpg",
        "Schindler's List": "/sF1U4EUQS8YHUYjNl3pMGNIQyr0.jpg",
        "Fight Club": "/pB8BM7pdSp6B6Ih7QZ4DrQ3PmJK.jpg",
        # Christmas Movies
        "Home Alone": "/onTSipZ8R3bliBdKfPtsDuHTdlL.jpg",
        "Elf": "/oOleziEempUPu96jkGs0Pj6tKxj.jpg",
        "The Polar Express": "/eOoCzH0MqeGr2taUZO4SwG416PF.jpg",
        "Love Actually": "/7QPeVsr9rcFU9Gl90yg0gTOTpVv.jpg",
        "A Christmas Story": "/34nSHYqmb7222tiqiuKqKJmZiQa.jpg",
        # Halloween/Horror Movies
        "Halloween": "/wijlZ3HaYMvlDTPqJoTCWKFkCPU.jpg",
        "The Shining": "/uAR0AWqhQL1hQa69UDEbb2rE5Wx.jpg",
        "A Nightmare on Elm Street": "/wGTpGGRMZmyFCcrY2YoxVTIBlli.jpg",
        "Scream": "/3O3klyyYpAZBBE4n7IngzTomRDp.jpg",
        "Get Out": "/tFXcEccSQMf3lfhfXKSU9iRBpa3.jpg",
        "Hocus Pocus": "/by4D4Q9NlUjFSEUA1yrxq6ksXmk.jpg",
        "The Conjuring": "/wVYREutTvI2tmxr6ujrHT704wGF.jpg",
        "Beetlejuice": "/z8ykp9HugsetInG2zTbZT6spamT.jpg",
        # TV Shows
        "Breaking Bad": "/ztkUQFLlC19CCMYHW9o1zWhJRNq.jpg",
        "The Sopranos": "/rTc7ZXdroqjkKivFPvCPX0Ru7uw.jpg",
        "The Wire": "/4lbclFySvugI51fwsyxBTOm4DqK.jpg",
        "Game of Thrones": "/1XS1oqL89opfnbLl8WnZY1O1uJx.jpg",
        "Better Call Saul": "/fC2HDm5t0kHl7mTm7jxMR31b7by.jpg",
        "Friends": "/f496cm9enuEsZkSPzCwnTESEK5s.jpg",
        "Seinfeld": "/aCw8ONfyz3AhngVQa1E2Ss4KSUQ.jpg",
        "The Office": "/7DJKHzAi83BmQrWLrYYOqcoKfhR.jpg",
        "Parks and Recreation": "/dFs6yHxheEGoZSoA0Fdkgy6Jxh0.jpg",
        "Arrested Development": "/qMzwO952hMWQSCfHkp7IL20s4K7.jpg",
        "The IT Crowd": "/qZXkBoOUYzvKI4UCMzDQ5kqWHjh.jpg",
        "Fleabag": "/27vEYsRKa3eAniwmoccOoluEXQ1.jpg",
        "Cowboy Bebop": "/xDiXDfZwC6XYC6fxHI1jl3A3Ill.jpg",
        "Death Note": "/tCZFfYTIwrR7n94J6G14Y4hAFU6.jpg",
        "Attack on Titan": "/hTP1DtLGFamjfu8WqjnuQdP1n4i.jpg",
        "Fullmetal Alchemist: Brotherhood": "/5ZFUEOULaVml7pQuXxhpR2SmVUw.jpg",
        "Fawlty Towers": "/rnZoIJ8QjQrdCqbaXMrRaQV1Fwg.jpg",
    }

    def __init__(self, title: str, year: int = 2020, media_type: str = "movie"):
        self.title = title
        self.year = year
        self.type = media_type
        self.ratingKey = abs(hash(title + str(year))) % 1000000

        poster_path = self.TMDB_POSTERS.get(title, "/placeholder.jpg")
        self.thumb = f"https://image.tmdb.org/t/p/w500{poster_path}"

        # Mock GUIDs for matching
        if media_type == "movie":
            self.guids = [
                type('obj', (object,), {'id': f'imdb://tt{abs(hash(title)) % 10000000:07d}'})(),
                type('obj', (object,), {'id': f'tmdb://{abs(hash(title + str(year))) % 100000}'})(),
            ]
        else:
            self.guids = [
                type('obj', (object,), {'id': f'tvdb://{abs(hash(title)) % 100000}'})(),
                type('obj', (object,), {'id': f'tmdb://{abs(hash(title + str(year))) % 100000}'})(),
            ]

    def addCollection(self, collection_name: str):
        logger.info("[MOCK] Adding '%s' to collection '%s'", self.title, collection_name)

    def removeCollection(self, collection_name: str):
        logger.info("[MOCK] Removing '%s' from collection '%s'", self.title, collection_name)


class MockCollection:
    # Mock Plex collection

    # Custom collection posters (self-hosted for fast loading)
    CUSTOM_POSTERS = {
        "80s Action Classics": "/demo-posters/80s-Action-Classics.png",
        "90s Crime Dramas": "/demo-posters/90s-Crime-Dramas.jpg",
        "90s Sitcoms": "/demo-posters/90s-Sitcoms.png",
        "Anime Classics": "/demo-posters/Anime-Classics.png",
        "Best Picture Winners": "/demo-posters/Best-Picture-Winners.jpg",
        "Classic Horror": "/demo-posters/Classic-Horror.jpg",
        "Criterion Collection": "/demo-posters/Criterion-Collection.png",
        "Halloween Favorites": "/demo-posters/Halloween-Favorites.jpg",
        "HBO Prestige Dramas": "/demo-posters/HBO-Prestige-Dramas.png",
        "Holiday Comedies": "/demo-posters/Holiday-Comedies.png",
        "Hot on TV": "/demo-posters/Hot-on-TV.jpg",
        "Modern Comedy Classics": "/demo-posters/Modern-Comedy-Classics.png",
        "Nolan Collection": "/demo-posters/Nolan-Collection.jpg",
        "Oscar Winners 2024": "/demo-posters/Oscar-Winners-2024.png",
        "Recently Requested": "/demo-posters/Recently-Requested.png",
        "Sci-Fi Essentials": "/demo-posters/Sci-Fi-Essentials.png",
        "Studio Ghibli Films": "/demo-posters/Studio-Ghibli-Films.png",
        "Trending Movies": "/demo-posters/Trending-Movies.png",
        "British Comedy": "/demo-posters/British-Comedy.jpg",
    }


    def __init__(self, title: str, library_name: str, items: List[MockMediaItem] = None, is_active: bool = False, is_shared: bool = False):
        self.title = title
        self.library_name = library_name
        self.librarySectionTitle = library_name
        self.ratingKey = abs(hash(title)) % 100000
        self.addedAt = datetime.now()
        self._items = items or []
        self._visibility = MockVisibility(title, is_active=is_active, is_shared=is_shared)

        # Use custom poster if available
        if title in self.CUSTOM_POSTERS:
            self.thumb = self.CUSTOM_POSTERS[title]
        elif self._items:
            self.thumb = self._items[0].thumb
        else:
            self.thumb = "https://image.tmdb.org/t/p/w500/placeholder.jpg"

    def visibility(self) -> MockVisibility:
        return self._visibility

    def items(self) -> List[MockMediaItem]:
        return self._items

    def addItems(self, items: List[MockMediaItem]):
        logger.info("[MOCK] Adding %d items to collection '%s'", len(items), self.title)
        self._items.extend(items)

    def removeItems(self, items: List[MockMediaItem]):
        logger.info("[MOCK] Removing %d items from collection '%s'", len(items), self.title)
        for item in items:
            if item in self._items:
                self._items.remove(item)

    def delete(self):
        logger.info("[MOCK] Deleted collection: %s", self.title)


class MockLibrary:
    # Mock Plex library section

    def __init__(self, name: str, library_type: str = "movie"):
        self.title = name
        self.type = library_type
        self._collections: Dict[str, MockCollection] = {}
        self._all_items: List[MockMediaItem] = []
        self._initialize_sample_data()

    def _initialize_sample_data(self):
        if self.type == "movie":
            self._initialize_movie_library()
        elif self.type == "show":
            self._initialize_tv_library()

    def _initialize_movie_library(self):
        # Sample movies
        sample_movies = [
            MockMediaItem("The Shawshank Redemption", 1994),
            MockMediaItem("The Godfather", 1972),
            MockMediaItem("The Dark Knight", 2008),
            MockMediaItem("Pulp Fiction", 1994),
            MockMediaItem("Forrest Gump", 1994),
            MockMediaItem("Inception", 2010),
            MockMediaItem("The Matrix", 1999),
            MockMediaItem("Goodfellas", 1990),
            MockMediaItem("The Silence of the Lambs", 1991),
            MockMediaItem("Saving Private Ryan", 1998),
            MockMediaItem("The Green Mile", 1999),
            MockMediaItem("Interstellar", 2014),
            MockMediaItem("Gladiator", 2000),
            MockMediaItem("The Departed", 2006),
            MockMediaItem("The Prestige", 2006),
            MockMediaItem("Whiplash", 2014),
            MockMediaItem("The Lion King", 1994),
            MockMediaItem("Spirited Away", 2001),
            MockMediaItem("Princess Mononoke", 1997),
            MockMediaItem("My Neighbor Totoro", 1988),
            MockMediaItem("Howl's Moving Castle", 2004),
            MockMediaItem("Die Hard", 1988),
            MockMediaItem("Terminator 2: Judgment Day", 1991),
            MockMediaItem("RoboCop", 1987),
            MockMediaItem("Predator", 1987),
            MockMediaItem("The Breakfast Club", 1985),
            MockMediaItem("Ferris Bueller's Day Off", 1986),
            MockMediaItem("Back to the Future", 1985),
            MockMediaItem("Oppenheimer", 2023),
            MockMediaItem("Everything Everywhere All at Once", 2022),
            MockMediaItem("The Batman", 2022),
            MockMediaItem("Barbie", 2023),
            MockMediaItem("Dune", 2021),
            MockMediaItem("Dune: Part Two", 2024),
            MockMediaItem("The Dark Knight Rises", 2012),
            MockMediaItem("The Lord of the Rings: The Return of the King", 2003),
            MockMediaItem("The Matrix Reloaded", 2003),
            MockMediaItem("The Lord of the Rings: The Fellowship of the Ring", 2001),
            MockMediaItem("The Lord of the Rings: The Two Towers", 2002),
            MockMediaItem("Star Wars", 1977),
            MockMediaItem("Iron Man", 2008),
            MockMediaItem("Avengers: Infinity War", 2018),
            MockMediaItem("Avengers: Endgame", 2019),
            MockMediaItem("Schindler's List", 1993),
            MockMediaItem("Fight Club", 1999),
            # Christmas Movies (indices 45-49)
            MockMediaItem("Home Alone", 1990),
            MockMediaItem("Elf", 2003),
            MockMediaItem("The Polar Express", 2004),
            MockMediaItem("Love Actually", 2003),
            MockMediaItem("A Christmas Story", 1983),
            # Halloween/Horror Movies (indices 50-57)
            MockMediaItem("Halloween", 1978),
            MockMediaItem("The Shining", 1980),
            MockMediaItem("A Nightmare on Elm Street", 1984),
            MockMediaItem("Scream", 1996),
            MockMediaItem("Get Out", 2017),
            MockMediaItem("Hocus Pocus", 1993),
            MockMediaItem("The Conjuring", 2013),
            MockMediaItem("Beetlejuice", 1988),
        ]
        self._all_items = sample_movies

        # Collections matching config.demo.yaml
        # (collection_name, movie_indices, is_active, is_shared)
        collections_config = {
            "Oscar Winners 2024": ([28, 29, 31], True, False),  # Oppenheimer, EEAAO, Barbie
            "Best Picture Winners": ([0, 1, 4, 12, 43], False, False),  # Shawshank, Godfather, Forrest Gump, Gladiator, Schindler's
            "Criterion Collection": ([0, 3, 8, 17, 18], False, False),  # Shawshank, Pulp Fiction, Silence of Lambs, Spirited Away, Mononoke
            "80s Action Classics": ([21, 22, 23, 24], True, False),  # Die Hard, T2, RoboCop, Predator
            "Nolan Collection": ([2, 5, 11, 14, 34], False, False),  # Dark Knight, Inception, Interstellar, Prestige, DK Rises
            "90s Crime Dramas": ([0, 3, 7, 8, 44], False, False),  # Shawshank, Pulp Fiction, Goodfellas, Silence, Fight Club
            "Sci-Fi Essentials": ([5, 6, 11, 32, 33], True, True),  # Inception, Matrix, Interstellar, Dune, Dune 2 - SHARED
            "Studio Ghibli Films": ([17, 18, 19, 20], True, True),  # Spirited Away, Mononoke, Totoro, Howl's - SHARED
            "Modern Comedy Classics": ([31, 29], False, False),  # Barbie, EEAAO
            "Recently Requested": ([33, 28, 31, 30], True, False),  # Dune 2, Oppenheimer, Barbie, Batman
            "Trending Movies": ([28, 33, 31, 29, 32], True, True),  # Oppenheimer, Dune 2, Barbie, EEAAO, Dune - SHARED
            # Christmas Collections
            "Christmas Classics": ([45, 46, 47, 48, 49, 21], False, False),  # Home Alone, Elf, Polar Express, Love Actually, Christmas Story, Die Hard
            "Holiday Comedies": ([45, 46, 48], False, False),  # Home Alone, Elf, Christmas Story
            # Spooky Season Collections
            "Halloween Favorites": ([50, 53, 55, 57], False, False),  # Halloween, Scream, Hocus Pocus, Beetlejuice
            "Classic Horror": ([50, 51, 52, 56], False, False),  # Halloween, Shining, Nightmare, Conjuring
        }

        for title, (indices, is_active, is_shared) in collections_config.items():
            items = [sample_movies[i] for i in indices if i < len(sample_movies)]
            self._collections[title] = MockCollection(title, self.title, items, is_active=is_active, is_shared=is_shared)

    def _initialize_tv_library(self):
        sample_shows = [
            MockMediaItem("Breaking Bad", 2008, "show"),
            MockMediaItem("The Sopranos", 1999, "show"),
            MockMediaItem("The Wire", 2002, "show"),
            MockMediaItem("Game of Thrones", 2011, "show"),
            MockMediaItem("Better Call Saul", 2015, "show"),
            MockMediaItem("Friends", 1994, "show"),
            MockMediaItem("Seinfeld", 1989, "show"),
            MockMediaItem("The Office", 2005, "show"),
            MockMediaItem("Parks and Recreation", 2009, "show"),
            MockMediaItem("Arrested Development", 2003, "show"),
            MockMediaItem("The IT Crowd", 2006, "show"),
            MockMediaItem("Fleabag", 2016, "show"),
            MockMediaItem("Cowboy Bebop", 1998, "show"),
            MockMediaItem("Death Note", 2006, "show"),
            MockMediaItem("Attack on Titan", 2013, "show"),
            MockMediaItem("Fullmetal Alchemist: Brotherhood", 2009, "show"),
            MockMediaItem("Fawlty Towers", 1975, "show"),
        ]
        self._all_items = sample_shows

        # Collections matching config.demo.yaml
        # (collection_name, show_indices, is_active, is_shared)
        collections_config = {
            "HBO Prestige Dramas": ([0, 1, 2, 3, 4], True, True),  # Breaking Bad, Sopranos, Wire, GoT, BCS - SHARED
            "90s Sitcoms": ([5, 6, 7], True, False),  # Friends, Seinfeld, Office
            "Modern Comedy Classics": ([7, 8, 9, 11], False, False),  # Office, Parks, Arrested Dev, Fleabag
            "British Comedy": ([10, 16], False, False),  # IT Crowd, Fawlty Towers
            "Anime Classics": ([12, 13, 14, 15], False, False),  # Cowboy Bebop, Death Note, AoT, FMA:B
            "Hot on TV": ([0, 3, 4, 7], True, False),  # Breaking Bad, GoT, BCS, Office
        }

        for title, (indices, is_active, is_shared) in collections_config.items():
            items = [sample_shows[i] for i in indices if i < len(sample_shows)]
            self._collections[title] = MockCollection(title, self.title, items, is_active=is_active, is_shared=is_shared)

    def collections(self) -> List[MockCollection]:
        return list(self._collections.values())

    def search(self, title: str = None, year: int = None, libtype: str = None, **kwargs) -> List[MockMediaItem]:
        results = []
        for item in self._all_items:
            if title and title.lower() not in item.title.lower():
                continue
            if year and item.year != year:
                continue
            if libtype and item.type != libtype:
                continue
            results.append(item)
        return results

    def createCollection(self, title: str, items: List[MockMediaItem] = None) -> MockCollection:
        logger.info("[MOCK] Creating collection '%s' in library '%s'", title, self.title)
        if title not in self._collections:
            self._collections[title] = MockCollection(title, self.title, items or [])
        return self._collections[title]

    def all(self, limit: int = None) -> List[MockMediaItem]:
        if limit:
            return self._all_items[:limit]
        return self._all_items

    def fetchItem(self, rating_key: int) -> MockMediaItem:
        for item in self._all_items:
            if item.ratingKey == rating_key:
                return item
        return None


class MockLibraryManager:
    # Mock library section manager

    def __init__(self):
        self._libraries: Dict[str, MockLibrary] = {
            "Movies": MockLibrary("Movies", "movie"),
            "TV Shows": MockLibrary("TV Shows", "show"),
        }

    def section(self, name: str) -> MockLibrary:
        if name not in self._libraries:
            logger.warning("[MOCK] Library '%s' not found, creating empty library", name)
            self._libraries[name] = MockLibrary(name, "movie")
        return self._libraries[name]

    def sections(self) -> List[MockLibrary]:
        return list(self._libraries.values())


class MockPlexServer:
    # Mock PlexServer for demo mode

    def __init__(self, base_url: str = "http://mock:32400", token: str = "mock-token"):
        self.base_url = base_url
        self.token = token
        self.friendlyName = "Demo Plex Server"
        self.version = "1.40.0.0000-demo"
        self.myPlexUsername = "demo_user"
        self.library = MockLibraryManager()
        logger.info("[MOCK] Connected to mock Plex server at %s (Demo Mode)", base_url)

    def url(self, path: str, includeToken: bool = False) -> str:
        # If already a full URL, return as-is
        if path.startswith("http://") or path.startswith("https://"):
            return path
        # Demo poster paths should be returned as-is (served by frontend)
        if path.startswith("/demo-posters/"):
            return path
        url = f"{self.base_url}{path}"
        if includeToken:
            url += f"?X-Plex-Token={self.token}"
        return url

    def transcodeImage(self, url: str, height: int = 450, width: int = 300, minSize: int = 1) -> str:
        # For demo posters, return the URL unchanged (no transcoding needed)
        if "/demo-posters/" in url:
            # Extract just the path portion if it's a full URL
            if url.startswith("/demo-posters/"):
                return url
            # Handle case where url() was called first and prepended base_url
            import re
            match = re.search(r'(/demo-posters/[^?]+)', url)
            if match:
                return match.group(1)
        return url

    def fetchItem(self, rating_key: int):
        return MockMediaItem(f"Item-{rating_key}")

    def sessions(self) -> list:
        # Return mock active sessions to show users watching content
        return [
            MockSession(
                title="The Dark Knight",
                username="MovieFan2024",
                media_type="movie",
                state="playing",
                view_offset=4320000,  # 72 minutes in
                duration=9120000,  # 152 minutes total
            ),
            MockSession(
                title="Ozymandias",
                username="WalterWhiteFan",
                media_type="episode",
                state="playing",
                view_offset=1800000,  # 30 minutes in
                duration=2820000,  # 47 minutes total
                grandparent_title="Breaking Bad",
            ),
            MockSession(
                title="Interstellar",
                username="SciFiLover",
                media_type="movie",
                state="paused",
                view_offset=6600000,  # 110 minutes in
                duration=10140000,  # 169 minutes total
            ),
        ]

    def __repr__(self):
        return f"<MockPlexServer:{self.friendlyName}>"


# Singleton instance to persist state across requests
_mock_plex_server_instance: MockPlexServer = None


def get_mock_plex_server(config) -> MockPlexServer:
    # Factory function matching the real get_plex_server signature
    # Returns singleton instance so visibility changes persist
    global _mock_plex_server_instance
    if _mock_plex_server_instance is None:
        _mock_plex_server_instance = MockPlexServer(
            base_url=config.plex.base_url,
            token=config.plex.token,
        )
    return _mock_plex_server_instance


class MockTraktClient:
    # Mock Trakt client for demo mode

    def __init__(self):
        logger.info("[MOCK] Initialized mock Trakt client (Demo Mode)")

    def ping(self):
        # Always return success
        return (True, None)

    def get_list_items(self, url: str):
        # Return empty list - we're not actually syncing
        return []

    def get_list_items_from_url(self, url: str):
        # Return empty list - we're not actually syncing
        return []


class MockMDBListClient:
    # Mock MDBList client for demo mode

    def __init__(self):
        logger.info("[MOCK] Initialized mock MDBList client (Demo Mode)")

    def ping(self):
        # Always return success
        return (True, None)

    def get_list_items(self, url: str):
        # Return empty list - we're not actually syncing
        return []

    def get_list_items_from_url(self, url: str):
        # Return empty list - we're not actually syncing
        return []


def get_mock_trakt_client(config) -> MockTraktClient:
    # Factory function for mock Trakt client
    if config.trakt is None or not config.trakt.enabled:
        return None
    return MockTraktClient()


def get_mock_mdblist_client(config) -> MockMDBListClient:
    # Factory function for mock MDBList client
    if config.mdblist is None or not config.mdblist.enabled:
        return None
    return MockMDBListClient()


class MockTautulliClient:
    # Mock Tautulli client for demo mode with realistic sample data

    def __init__(self):
        logger.info("[MOCK] Initialized mock Tautulli client (Demo Mode)")

        # Sample users for consistent data across endpoints
        self._users = [
            {"username": "MovieFan2024", "friendly_name": "MovieFan2024", "total_plays": 247, "total_duration": 892800},
            {"username": "WalterWhiteFan", "friendly_name": "WalterWhiteFan", "total_plays": 189, "total_duration": 756000},
            {"username": "SciFiLover", "friendly_name": "SciFiLover", "total_plays": 156, "total_duration": 624000},
            {"username": "ComedyKing", "friendly_name": "ComedyKing", "total_plays": 134, "total_duration": 483600},
            {"username": "BingeWatcher", "friendly_name": "BingeWatcher", "total_plays": 98, "total_duration": 352800},
            {"username": "ClassicFilmBuff", "friendly_name": "ClassicFilmBuff", "total_plays": 76, "total_duration": 273600},
            {"username": "AnimeEnthusiast", "friendly_name": "AnimeEnthusiast", "total_plays": 64, "total_duration": 230400},
            {"username": "FamilyAccount", "friendly_name": "FamilyAccount", "total_plays": 52, "total_duration": 187200},
        ]

    def ping(self):
        # Always return success for demo mode
        return (True, None)

    def get_home_stats(self, time_range: int = 30, stats_type: str = "plays"):
        # Return mock home stats with top users
        return [
            {
                "stat_id": "top_users",
                "stat_type": "total_plays",
                "rows": self._users[:5]
            }
        ]

    def get_users_table(self, length: int = 25, order_column: str = "total_plays"):
        # Return mock users table
        return self._users[:length]

    def get_user_watch_time_stats(self, query_days: int = 30, grouping: int = 0):
        # Scale stats based on query_days
        scale = query_days / 30.0
        return [
            {
                "username": u["username"],
                "friendly_name": u["friendly_name"],
                "total_plays": int(u["total_plays"] * scale),
                "total_time": int(u["total_duration"] * scale),
            }
            for u in self._users
        ]

    def get_plays_by_date(self, time_range: int = 30, y_axis: str = "plays"):
        # Generate mock daily play data
        import random
        from datetime import datetime, timedelta

        random.seed(42)  # Consistent data
        categories = []
        movie_data = []
        tv_data = []

        base_date = datetime.now()
        for i in range(time_range - 1, -1, -1):
            date = base_date - timedelta(days=i)
            categories.append(date.strftime("%Y-%m-%d"))
            # Higher activity on weekends
            is_weekend = date.weekday() >= 5
            base_plays = 25 if is_weekend else 15
            movie_data.append(random.randint(base_plays - 8, base_plays + 12))
            tv_data.append(random.randint(base_plays - 5, base_plays + 15))

        return {
            "categories": categories,
            "series": [
                {"name": "Movies", "data": movie_data},
                {"name": "TV", "data": tv_data},
            ]
        }

    def get_plays_by_hourofday(self, time_range: int = 30, y_axis: str = "plays"):
        # Generate mock hourly distribution - peak in evenings
        hours = [str(h).zfill(2) for h in range(24)]

        # Realistic viewing pattern: low morning, peak evening
        hourly_pattern = [
            3, 2, 1, 1, 1, 2,   # 00-05: Late night/early morning (low)
            4, 8, 12, 10, 8, 9,  # 06-11: Morning/midday
            11, 12, 14, 16, 18, 22,  # 12-17: Afternoon
            35, 48, 52, 45, 28, 12,  # 18-23: Evening peak
        ]

        return {
            "categories": hours,
            "series": [
                {"name": "Plays", "data": hourly_pattern},
            ]
        }

    def get_history(self, length: int = 1000, start: int = 0, order_column: str = "date", order_dir: str = "desc"):
        # Generate mock history entries with realistic concurrent viewing patterns
        import random
        from datetime import datetime, timedelta

        random.seed(43)
        history = []
        base_time = datetime.now()

        # Generate viewing sessions over the past 30 days
        for i in range(min(length, 500)):
            # Random time in the past 30 days
            days_ago = random.randint(0, 29)
            hour = random.choices(
                range(24),
                weights=[3, 2, 1, 1, 1, 2, 4, 8, 12, 10, 8, 9, 11, 12, 14, 16, 18, 22, 35, 48, 52, 45, 28, 12]
            )[0]
            minute = random.randint(0, 59)

            start_time = base_time - timedelta(days=days_ago, hours=24-hour, minutes=minute)
            duration_minutes = random.randint(20, 180)
            stop_time = start_time + timedelta(minutes=duration_minutes)

            history.append({
                "started": int(start_time.timestamp()),
                "stopped": int(stop_time.timestamp()),
                "user": random.choice(self._users)["username"],
                "media_type": random.choice(["movie", "episode", "episode", "episode"]),  # More TV
            })

        return history

    def get_plays_by_stream_type(self, time_range: int = 30, y_axis: str = "plays"):
        # Generate mock stream type data with concurrent viewer info
        import random
        from datetime import datetime, timedelta

        random.seed(44)
        categories = []
        direct_play = []
        direct_stream = []
        transcode = []
        concurrent = []

        base_date = datetime.now()
        for i in range(time_range - 1, -1, -1):
            date = base_date - timedelta(days=i)
            categories.append(date.strftime("%Y-%m-%d"))
            is_weekend = date.weekday() >= 5
            base = 20 if is_weekend else 12

            direct_play.append(random.randint(base - 5, base + 8))
            direct_stream.append(random.randint(3, 8))
            transcode.append(random.randint(2, 6))
            concurrent.append(random.randint(2, 5 if is_weekend else 4))

        return {
            "categories": categories,
            "series": [
                {"name": "Direct Play", "data": direct_play},
                {"name": "Direct Stream", "data": direct_stream},
                {"name": "Transcode", "data": transcode},
                {"name": "Max Concurrent", "data": concurrent},
            ]
        }

    def get_libraries(self):
        # Return mock library info
        return [
            {"section_id": 1, "section_name": "Movies", "section_type": "movie", "count": 45},
            {"section_id": 2, "section_name": "TV Shows", "section_type": "show", "count": 17},
        ]

    def get_library_collections(self, section_id: int):
        # Return mock collection info
        if section_id == 1:  # Movies
            return [
                {"rating_key": 1001, "title": "Oscar Winners 2024"},
                {"rating_key": 1002, "title": "80s Action Classics"},
                {"rating_key": 1003, "title": "Sci-Fi Essentials"},
                {"rating_key": 1004, "title": "Studio Ghibli Films"},
                {"rating_key": 1005, "title": "Trending Movies"},
            ]
        else:  # TV Shows
            return [
                {"rating_key": 2001, "title": "HBO Prestige Dramas"},
                {"rating_key": 2002, "title": "90s Sitcoms"},
                {"rating_key": 2003, "title": "Hot on TV"},
            ]

    def get_collection_stats(self, rating_key: int, query_days: int = 30):
        # Return mock collection stats
        import random
        random.seed(rating_key)  # Consistent per collection
        return {
            "total_plays": random.randint(50, 300),
            "total_duration": random.randint(100000, 500000),
            "total_time": f"{random.randint(10, 100)}h {random.randint(0, 59)}m",
        }


def get_mock_tautulli_client(config) -> MockTautulliClient:
    # Factory function for mock Tautulli client
    if config.tautulli is None or not config.tautulli.enabled:
        return None
    return MockTautulliClient()
