#!/usr/bin/env python3
# Reset demo database to initial state
# Called during demo deployment restarts to ensure a clean state

import os
import sys
from pathlib import Path

# Add the app to the Python path
sys.path.insert(0, str(Path(__file__).parent))

from homescreen_hero.core.db.base import get_session
from homescreen_hero.core.db.history import init_db
from homescreen_hero.core.db.seed_demo_data import seed_demo_rotation_history, seed_demo_analytics
from homescreen_hero.core.db.models import RotationRecord, CollectionUsage, CollectionAnalytics


def reset_demo_database():
    print("Initializing demo database...")

    # Create data directory if needed
    data_dir = Path("/data")
    if not data_dir.exists():
        data_dir.mkdir(parents=True, exist_ok=True)
        print(f"Created data directory: {data_dir}")

    logs_dir = data_dir / "logs"
    if not logs_dir.exists():
        logs_dir.mkdir(parents=True, exist_ok=True)
        print(f"Created logs directory: {logs_dir}")

    # Initialize the database schema
    init_db()

    session = get_session()

    try:
        # Check if we need to seed (empty database)
        rotation_count = session.query(RotationRecord).count()

        if rotation_count == 0:
            print("Empty database detected, seeding demo data...")
            seed_demo_rotation_history(session)
            seed_demo_analytics(session)
            print("Demo database initialized!")
        else:
            print(f"Database already has {rotation_count} rotation records, skipping seed")

    except Exception as e:
        print(f"Error initializing database: {e}")
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    reset_demo_database()
