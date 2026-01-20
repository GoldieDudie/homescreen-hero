# Seed demo database with sample rotation history and usage stats
# For use in demo/testing environments

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from .models import RotationRecord, CollectionUsage, CollectionAnalytics

logger = logging.getLogger(__name__)


def seed_demo_rotation_history(session: Session) -> None:
    # Seed the database with sample rotation history

    all_collections = [
        "Oscar Winners 2024",
        "80s Action Classics",
        "Criterion Collection",
        "Studio Ghibli Films",
        "Nolan Collection",
        "90s Crime Dramas",
        "Best Picture Winners",
        "Sci-Fi Essentials",
        "HBO Prestige Dramas",
        "90s Sitcoms",
        "Modern Comedy Classics",
        "British Comedy",
        "Anime Classics",
    ]

    # Check if we already have data
    existing_count = session.query(RotationRecord).count()
    if existing_count > 0:
        logger.info("Demo data already exists (%d records). Skipping seed.", existing_count)
        return

    logger.info("Seeding demo rotation history...")

    # Create 15 sample rotations over the past 30 days
    num_rotations = 15
    base_date = datetime.now() - timedelta(days=30)

    rotation_patterns = [
        ["Oscar Winners 2024", "80s Action Classics", "HBO Prestige Dramas"],
        ["Criterion Collection", "Studio Ghibli Films", "90s Sitcoms"],
        ["Nolan Collection", "Sci-Fi Essentials", "Anime Classics"],
        ["Best Picture Winners", "Modern Comedy Classics", "British Comedy"],
        ["90s Crime Dramas", "HBO Prestige Dramas", "Studio Ghibli Films"],
        ["Oscar Winners 2024", "Nolan Collection", "90s Sitcoms"],
        ["80s Action Classics", "Criterion Collection", "Anime Classics"],
        ["Sci-Fi Essentials", "Best Picture Winners", "British Comedy"],
        ["Studio Ghibli Films", "90s Crime Dramas", "Modern Comedy Classics"],
        ["HBO Prestige Dramas", "Nolan Collection", "Oscar Winners 2024"],
        ["Anime Classics", "80s Action Classics", "90s Sitcoms"],
        ["British Comedy", "Criterion Collection", "Sci-Fi Essentials"],
        ["Modern Comedy Classics", "Best Picture Winners", "Studio Ghibli Films"],
        ["90s Crime Dramas", "Oscar Winners 2024", "Anime Classics"],
        ["Nolan Collection", "HBO Prestige Dramas", "80s Action Classics"],
    ]

    for rotation_idx in range(num_rotations):
        rotation_date = base_date + timedelta(days=rotation_idx * 2, hours=(rotation_idx * 3) % 24)
        collections = rotation_patterns[rotation_idx]

        record = RotationRecord(
            created_at=rotation_date,
            success=True,
            error_message=None,
            featured_collections=collections,
        )
        session.add(record)

    session.flush()

    # Seed collection usage stats
    logger.info("Seeding collection usage stats...")

    usage_counts = {
        "Oscar Winners 2024": 4,
        "80s Action Classics": 4,
        "Criterion Collection": 3,
        "Studio Ghibli Films": 4,
        "Nolan Collection": 4,
        "90s Crime Dramas": 3,
        "Best Picture Winners": 3,
        "Sci-Fi Essentials": 3,
        "HBO Prestige Dramas": 4,
        "90s Sitcoms": 4,
        "Modern Comedy Classics": 3,
        "British Comedy": 3,
        "Anime Classics": 4,
    }

    last_rotation = session.query(RotationRecord).order_by(RotationRecord.id.desc()).first()

    for name, times_used in usage_counts.items():
        usage = CollectionUsage(
            collection_name=name,
            last_rotation_id=last_rotation.id if last_rotation else None,
            last_rotated_at=datetime.now() - timedelta(days=times_used),
            times_used=times_used,
        )
        session.add(usage)

    session.commit()
    logger.info("Demo rotation history seeded successfully!")


def seed_demo_analytics(session: Session) -> None:
    # Seed demo analytics data

    existing_count = session.query(CollectionAnalytics).count()
    if existing_count > 0:
        logger.info("Demo analytics already exists (%d records). Skipping.", existing_count)
        return

    logger.info("Seeding demo analytics...")

    # Sample analytics for collections
    analytics_data = [
        ("Oscar Winners 2024", "Movies", 45, 12600, 8),
        ("Nolan Collection", "Movies", 78, 21000, 12),
        ("Studio Ghibli Films", "Movies", 34, 8400, 6),
        ("80s Action Classics", "Movies", 56, 15000, 10),
        ("HBO Prestige Dramas", "TV Shows", 120, 36000, 15),
        ("90s Sitcoms", "TV Shows", 89, 18000, 11),
        ("Sci-Fi Essentials", "Movies", 42, 11200, 7),
        ("Best Picture Winners", "Movies", 31, 9000, 5),
    ]

    base_date = datetime.now() - timedelta(days=14)

    for i, (name, library, plays, duration, users) in enumerate(analytics_data):
        analytics = CollectionAnalytics(
            collection_name=name,
            plex_library=library,
            media_type="movie" if library == "Movies" else "show",
            total_plays=plays,
            total_duration_seconds=duration,
            unique_users=users,
            rotation_id=i + 1,
            collected_at=base_date + timedelta(days=i),
        )
        session.add(analytics)

    session.commit()
    logger.info("Demo analytics seeded successfully!")
