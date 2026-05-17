import os
import pytest

os.environ["HOMESCREEN_HERO_DB"] = "sqlite:///:memory:"


@pytest.fixture(autouse=True)
def fresh_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from homescreen_hero.core.db import base as base_module
    from homescreen_hero.core.db.base import Base

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    base_module._engine = engine
    base_module.SessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True
    )
    yield
    engine.dispose()


class FakeHub:
    def __init__(self, section, title, deletable=True):
        self.section = section
        self.title = title
        self.identifier = title.replace(" ", "_")
        self.deletable = deletable
        self.promotedToOwnHome = False
        self.promotedToSharedHome = False
        self.promotedToRecommended = False
        self.move_calls = 0

    def move(self, after=None):
        self.move_calls += 1
        hubs = self.section._hubs
        hubs.remove(self)
        if after is None:
            hubs.insert(0, self)
            return
        idx = hubs.index(after)
        hubs.insert(idx + 1, self)

    def updateVisibility(self, home=None, shared=None, recommended=None):
        pass


class FakeSection:
    def __init__(self, name, titles):
        self.title = name
        self._hubs = [FakeHub(self, t) for t in titles]

    def managedHubs(self):
        return list(self._hubs)


class FakeServer:
    def __init__(self, sections):
        from types import SimpleNamespace
        self.library = SimpleNamespace(section=lambda name: sections[name])


def _make_config(library_names):
    from homescreen_hero.core.config.schema import (
        AppConfig, PlexSettings, PlexLibraryConfig, RotationSettings,
    )
    return AppConfig(
        plex=PlexSettings(
            base_url="http://localhost:32400",
            token="t",
            libraries=[PlexLibraryConfig(name=n, enabled=True) for n in library_names],
        ),
        rotation=RotationSettings(enabled=True, max_collections=10),
        groups=[],
    )


def test_first_sync_migrates_legacy_pins_one_top_one_bottom_per_library():
    from homescreen_hero.core.db.pinning import pin_collection
    from homescreen_hero.core.config.schema import CollectionRef
    from homescreen_hero.core.hub_sync import sync_library_hub_order
    from homescreen_hero.core.db import get_library_hub_order, PIN_TOP, PIN_BOTTOM

    # Seed legacy: 3 tops + 2 bottoms in Movies. Each pinned at increasing display_order.
    pin_collection(CollectionRef(library="Movies", name="TopA"), display_order=1, pin_position="top")
    pin_collection(CollectionRef(library="Movies", name="TopB"), display_order=2, pin_position="top")
    pin_collection(CollectionRef(library="Movies", name="TopC"), display_order=3, pin_position="top")
    pin_collection(CollectionRef(library="Movies", name="BotA"), display_order=4, pin_position="bottom")
    pin_collection(CollectionRef(library="Movies", name="BotB"), display_order=5, pin_position="bottom")

    section = FakeSection("Movies", ["TopA", "TopB", "TopC", "BotA", "BotB", "Other"])
    server = FakeServer({"Movies": section})
    config = _make_config(["Movies"])

    sync_library_hub_order(server, config, "Movies")

    rows = get_library_hub_order("Movies")
    pins = {(r.hub_title, r.pin_position) for r in rows if r.pin_position}
    # Only TopA (smallest display_order top) and BotA (smallest bottom) should survive as pins
    assert pins == {("TopA", PIN_TOP), ("BotA", PIN_BOTTOM)}


def test_migration_does_not_re_run_on_subsequent_sync():
    from homescreen_hero.core.db.pinning import pin_collection
    from homescreen_hero.core.config.schema import CollectionRef
    from homescreen_hero.core.hub_sync import sync_library_hub_order
    from homescreen_hero.core.db import get_library_hub_order, set_pin

    pin_collection(CollectionRef(library="Movies", name="LegacyTop"), display_order=1, pin_position="top")

    section = FakeSection("Movies", ["LegacyTop", "Other"])
    server = FakeServer({"Movies": section})
    config = _make_config(["Movies"])

    sync_library_hub_order(server, config, "Movies")
    # User then manually unpins LegacyTop in the new model
    set_pin("Movies", "LegacyTop", None)

    # Second sync should NOT re-migrate the legacy pin (would overwrite user's choice)
    sync_library_hub_order(server, config, "Movies")

    rows = get_library_hub_order("Movies")
    pins = [r.hub_title for r in rows if r.pin_position]
    assert pins == []  # Stays unpinned


def test_migration_skips_legacy_pins_not_in_plex():
    from homescreen_hero.core.db.pinning import pin_collection
    from homescreen_hero.core.config.schema import CollectionRef
    from homescreen_hero.core.hub_sync import sync_library_hub_order
    from homescreen_hero.core.db import get_library_hub_order, PIN_TOP

    # First top doesn't exist as a Plex hub anymore — migration should fall through to next
    pin_collection(CollectionRef(library="Movies", name="GhostTop"), display_order=1, pin_position="top")
    pin_collection(CollectionRef(library="Movies", name="RealTop"), display_order=2, pin_position="top")

    section = FakeSection("Movies", ["RealTop", "Other"])
    server = FakeServer({"Movies": section})
    config = _make_config(["Movies"])

    sync_library_hub_order(server, config, "Movies")

    rows = get_library_hub_order("Movies")
    pins = {(r.hub_title, r.pin_position) for r in rows if r.pin_position}
    assert pins == {("RealTop", PIN_TOP)}
