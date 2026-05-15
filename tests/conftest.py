"""
Pytest configuration and shared fixtures
"""
import pytest
from datetime import date
from homescreen_hero.core.config.schema import (
    AppConfig,
    CollectionRef,
    RotationSettings,
    PlexSettings,
    PlexLibraryConfig,
    CollectionGroupConfig,
)


def cr(name: str, library: str = "Movies") -> CollectionRef:
    """Shorthand for creating a CollectionRef in tests."""
    return CollectionRef(library=library, name=name)


@pytest.fixture
def sample_config():
    """Basic AppConfig fixture for testing"""
    return AppConfig(
        plex=PlexSettings(
            base_url="http://localhost:32400",
            token="test-token",
            libraries=[
                PlexLibraryConfig(name="Movies", enabled=True),
                PlexLibraryConfig(name="TV Shows", enabled=True),
            ]
        ),
        rotation=RotationSettings(
            enabled=True,
            interval_hours=12,
            max_collections=5,
            allow_repeats=False,
        ),
        groups=[
            CollectionGroupConfig(
                name="Action",
                enabled=True,
                min_picks=1,
                max_picks=2,
                weight=1,
                min_gap_rotations=3,
                collections=[
                    cr("Action Movies"),
                    cr("Superhero Collection"),
                    cr("Die Hard Series"),
                ],
            ),
            CollectionGroupConfig(
                name="Comedy",
                enabled=True,
                min_picks=0,
                max_picks=1,
                weight=1,
                min_gap_rotations=2,
                collections=[
                    cr("Comedy Classics"),
                    cr("Stand-up Specials"),
                ],
            ),
        ]
    )


@pytest.fixture
def fixed_date():
    """Fixed date for testing date-based logic"""
    return date(2024, 12, 15)
