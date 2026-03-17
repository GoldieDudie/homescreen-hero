# Seed the demo database with varied rotation history
# Run: python -m stubs.seed_demo_db

import random
from datetime import datetime, timedelta, timezone

from homescreen_hero.core.db.history import init_db, record_rotation
from homescreen_hero.core.db.history import session_scope
from homescreen_hero.core.db.models import RotationRecord, PinnedCollection, CollectionAnalytics, SourceSyncRecord

COLLECTIONS = {
    "Featured Films": ["Oscar Winners 2024", "Christopher Nolan Collection", "A24 Films"],
    "Genre Picks": ["80s Action Classics", "90s Crime Dramas", "Sci-Fi Essentials"],
    "Animation": ["Studio Ghibli Films"],
    "Trending": ["Trakt Popular", "Letterboxd Favorites"],
    "TV Highlights": ["HBO Prestige Dramas", "Anime Essentials"],
    "Holiday": ["Holiday Classics"],
}


def seed():
    init_db()

    # Skip if already seeded
    with session_scope() as db:
        existing = db.query(RotationRecord).first()
    if existing:
        print("Database already has rotation history, skipping seed")
        return

    now = datetime.now(timezone.utc)
    random.seed(42)

    for i in range(15):
        hours_ago = (15 - i) * 8
        created_at = now - timedelta(hours=hours_ago)

        featured = []
        contributions = {}

        # Featured Films: 1-3 picks
        picks = random.sample(COLLECTIONS["Featured Films"], k=random.randint(1, 3))
        featured.extend(picks)
        contributions["Featured Films"] = picks

        # Genre Picks: 1-2 picks
        picks = random.sample(COLLECTIONS["Genre Picks"], k=random.randint(1, 2))
        featured.extend(picks)
        contributions["Genre Picks"] = picks

        # Animation: 0-1 picks
        if random.random() > 0.4:
            picks = random.sample(COLLECTIONS["Animation"], k=1)
            featured.extend(picks)
            contributions["Animation"] = picks

        # Trending: 0-1 picks
        if random.random() > 0.5:
            picks = random.sample(COLLECTIONS["Trending"], k=1)
            featured.extend(picks)
            contributions["Trending"] = picks

        # TV Highlights: 1 pick
        picks = random.sample(COLLECTIONS["TV Highlights"], k=1)
        featured.extend(picks)
        contributions["TV Highlights"] = picks

        record_rotation(
            featured_collections=featured,
            success=True,
            group_contributions=contributions,
        )

        # Backdate the record
        with session_scope() as db:
            record = db.query(RotationRecord).order_by(RotationRecord.id.desc()).first()
            if record:
                record.created_at = created_at

    print("Seeded 15 rotation records")

    # Seed collection analytics
    with session_scope() as db:
        existing_analytics = db.query(CollectionAnalytics).first()
        if not existing_analytics:
            analytics_data = [
                ("Oscar Winners 2024", "Movies", 10001, "movie", 47, 338400, 6),
                ("80s Action Classics", "Movies", 10002, "movie", 38, 273600, 5),
                ("Studio Ghibli Films", "Movies", 10003, "movie", 32, 230400, 4),
                ("Christopher Nolan Collection", "Movies", 10004, "movie", 55, 396000, 7),
                ("90s Crime Dramas", "Movies", 10005, "movie", 41, 295200, 5),
                ("Sci-Fi Essentials", "Movies", 10006, "movie", 44, 316800, 6),
                ("A24 Films", "Movies", 10007, "movie", 29, 208800, 4),
                ("Holiday Classics", "Movies", 10008, "movie", 18, 129600, 5),
                ("Trakt Popular", "Movies", 10009, "movie", 35, 252000, 6),
                ("Letterboxd Favorites", "Movies", 10010, "movie", 22, 158400, 4),
                ("Classic Horror", "Movies", 10013, "movie", 26, 187200, 4),
                ("Halloween Favorites", "Movies", 10014, "movie", 20, 144000, 5),
                ("Modern Horror", "Movies", 10015, "movie", 31, 223200, 5),
                ("Spielberg Collection", "Movies", 10016, "movie", 42, 302400, 6),
                ("Tarantino Collection", "Movies", 10017, "movie", 37, 266400, 5),
                ("Denis Villeneuve Collection", "Movies", 10018, "movie", 28, 201600, 4),
                ("HBO Prestige Dramas", "TV Shows", 20001, "show", 62, 446400, 7),
                ("Anime Essentials", "TV Shows", 20002, "show", 48, 345600, 5),
                ("Critically Acclaimed TV", "TV Shows", 20004, "show", 56, 403200, 6),
                ("Binge-Worthy Miniseries", "TV Shows", 20005, "show", 34, 244800, 5),
            ]
            collected_at = now - timedelta(hours=2)
            for name, library, rk, mtype, plays, duration, users in analytics_data:
                db.add(CollectionAnalytics(
                    collection_name=name,
                    plex_library=library,
                    rating_key=rk,
                    media_type=mtype,
                    total_plays=plays,
                    total_duration_seconds=duration,
                    unique_users=users,
                    collected_at=collected_at,
                ))
            print("Seeded 20 collection analytics records")
        else:
            print("Collection analytics already exist, skipping")

    # Seed source sync records
    with session_scope() as db:
        existing_syncs = db.query(SourceSyncRecord).first()
        if not existing_syncs:
            sync_time = now - timedelta(hours=6)
            syncs = [
                SourceSyncRecord(integration_type="trakt", source_name="Trakt Popular", source_url="https://trakt.tv/users/demo/lists/popular", sync_status="success", last_sync_time=sync_time, items_total=20, items_matched=18),
                SourceSyncRecord(integration_type="trakt", source_name="MCU Infinity Saga", source_url="https://trakt.tv/users/demo/lists/mcu-infinity-saga", sync_status="success", last_sync_time=sync_time - timedelta(hours=1), items_total=23, items_matched=21),
                SourceSyncRecord(integration_type="trakt", source_name="Heist Movies", source_url="https://trakt.tv/users/demo/lists/heist-movies", sync_status="success", last_sync_time=sync_time - timedelta(hours=2), items_total=15, items_matched=14),
                SourceSyncRecord(integration_type="mdblist", source_name="Sci-Fi Essentials", source_url="https://mdblist.com/lists/demo/sci-fi", sync_status="success", last_sync_time=sync_time - timedelta(hours=3), items_total=30, items_matched=27),
                SourceSyncRecord(integration_type="letterboxd", source_name="Letterboxd Favorites", source_url="https://letterboxd.com/demo/list/favorites/", sync_status="success", last_sync_time=sync_time - timedelta(hours=4), items_total=25, items_matched=22),
                SourceSyncRecord(integration_type="anilist", source_name="Top Anime", source_url="https://anilist.co/user/demo/animelist", sync_status="success", last_sync_time=sync_time - timedelta(hours=5), items_total=50, items_matched=38),
                SourceSyncRecord(integration_type="mal", source_name="MAL Spring Season", source_url="mal://season/2026/spring", sync_status="success", last_sync_time=sync_time - timedelta(hours=6), items_total=40, items_matched=31),
            ]
            for s in syncs:
                db.add(s)
            print("Seeded 7 source sync records")
        else:
            print("Source sync records already exist, skipping")

    # Seed pinned collections
    with session_scope() as db:
        existing_pins = db.query(PinnedCollection).first()
        if not existing_pins:
            pins = [
                PinnedCollection(collection_name="Trending Movies", library_name="Movies", display_order=0, visibility_home=True, visibility_shared=True),
                PinnedCollection(collection_name="Recently Downloaded Movies", library_name="Movies", display_order=1, visibility_home=True, visibility_shared=False),
                PinnedCollection(collection_name="Currently Airing on TV", library_name="TV Shows", display_order=2, visibility_home=True, visibility_shared=True),
            ]
            for pin in pins:
                db.add(pin)
            print("Seeded 3 pinned collections")
        else:
            print("Pinned collections already exist, skipping")


if __name__ == "__main__":
    seed()
