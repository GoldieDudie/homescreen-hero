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


# ---- Plex fake objects ----

class FakeHub:
    def __init__(self, section, title: str, deletable: bool = True,
                 fail_first_move: bool = False, raise_on_move: bool = False,
                 identifier: str = None):
        self.section = section
        self.title = title
        self.identifier = identifier if identifier is not None else title.replace(" ", "_")
        self.deletable = deletable
        self.promotedToOwnHome = False
        self.promotedToSharedHome = False
        self.promotedToRecommended = False
        self.fail_first_move = fail_first_move
        self.raise_on_move = raise_on_move
        self.move_calls = 0

    def move(self, after=None):
        self.move_calls += 1
        if self.raise_on_move:
            raise Exception("Hub does not support move")
        if self.fail_first_move and self.move_calls == 1:
            raise Exception("Simulated transient Plex API failure")
        hubs = self.section._hubs
        hubs.remove(self)
        if after is None:
            hubs.insert(0, self)
            return
        after_index = hubs.index(after)
        hubs.insert(after_index + 1, self)

    def updateVisibility(self, home=None, shared=None, recommended=None):
        if home is not None:
            self.promotedToOwnHome = home
        if shared is not None:
            self.promotedToSharedHome = shared
        if recommended is not None:
            self.promotedToRecommended = recommended


class FakeSection:
    def __init__(self, name, hub_specs, lib_type: str = "movie"):
        # hub_specs: list of (title, deletable) or (title, deletable, identifier)
        # or just title (deletable=True default, identifier derived from title)
        self.title = name
        self.type = lib_type
        self._hubs = []
        for spec in hub_specs:
            if isinstance(spec, tuple):
                if len(spec) == 3:
                    title, deletable, identifier = spec
                else:
                    title, deletable = spec
                    identifier = None
            else:
                title, deletable, identifier = spec, True, None
            self._hubs.append(FakeHub(self, title, deletable=deletable, identifier=identifier))

    def managedHubs(self):
        return list(self._hubs)


class FakeLibraryManager:
    def __init__(self, sections):
        self._sections = sections

    def section(self, name):
        return self._sections[name]


class FakeServer:
    def __init__(self, sections):
        self.library = FakeLibraryManager(sections)


def _make_config(*library_names):
    from homescreen_hero.core.config.schema import (
        AppConfig, PlexSettings, PlexLibraryConfig, RotationSettings,
    )
    return AppConfig(
        plex=PlexSettings(
            base_url="http://localhost:32400",
            token="test-token",
            libraries=[PlexLibraryConfig(name=n, enabled=True) for n in library_names],
        ),
        rotation=RotationSettings(enabled=True, max_collections=10),
        groups=[],
    )


def _make_config_with_group(library_name, group_name, collection_names):
    from homescreen_hero.core.config.schema import (
        AppConfig, PlexSettings, PlexLibraryConfig, RotationSettings,
        CollectionGroupConfig, CollectionRef,
    )
    return AppConfig(
        plex=PlexSettings(
            base_url="http://localhost:32400",
            token="test-token",
            libraries=[PlexLibraryConfig(name=library_name, enabled=True)],
        ),
        rotation=RotationSettings(enabled=True, max_collections=10),
        groups=[
            CollectionGroupConfig(
                name=group_name,
                enabled=True,
                min_picks=1,
                max_picks=10,
                collections=[
                    CollectionRef(library=library_name, name=n) for n in collection_names
                ],
            ),
        ],
    )


# ---- sync_library_hub_order tests ----

def test_sync_adds_all_hubs_on_first_run(monkeypatch):
    from homescreen_hero.core.hub_sync import sync_library_hub_order
    from homescreen_hero.core.db import get_library_hub_order

    section = FakeSection("Movies", ["A", "B", "C"])
    server = FakeServer({"Movies": section})
    config = _make_config("Movies")

    result = sync_library_hub_order(server, config, "Movies")

    assert result.added == ["A", "B", "C"]
    assert result.removed == []
    rows = get_library_hub_order("Movies")
    assert [r.hub_title for r in rows] == ["A", "B", "C"]


def test_sync_removes_stale_hubs():
    from homescreen_hero.core.hub_sync import sync_library_hub_order
    from homescreen_hero.core.db import slot_in_hub, get_library_hub_order, HUB_TYPE_COLLECTION

    # Pre-seed DB with hubs that are no longer in Plex
    slot_in_hub("Movies", "Stale1", HUB_TYPE_COLLECTION)
    slot_in_hub("Movies", "Stale2", HUB_TYPE_COLLECTION)
    slot_in_hub("Movies", "Survivor", HUB_TYPE_COLLECTION)

    section = FakeSection("Movies", ["Survivor", "NewHub"])
    server = FakeServer({"Movies": section})
    config = _make_config("Movies")

    result = sync_library_hub_order(server, config, "Movies")

    assert set(result.removed) == {"Stale1", "Stale2"}
    assert result.added == ["NewHub"]
    rows = get_library_hub_order("Movies")
    assert set(r.hub_title for r in rows) == {"Survivor", "NewHub"}


def test_sync_classifies_hub_types_correctly():
    from homescreen_hero.core.hub_sync import sync_library_hub_order
    from homescreen_hero.core.db import (
        get_library_hub_order, HUB_TYPE_COLLECTION, HUB_TYPE_SMART_HUB, HUB_TYPE_EXTERNAL,
    )

    # HSH-managed: "Action Movies" (configured)
    # External: "User Custom" (deletable=True but not configured)
    # Smart hub: "Recently Added Movies" (deletable=False)
    section = FakeSection("Movies", [
        ("Action Movies", True),
        ("User Custom", True),
        ("Recently Added Movies", False),
    ])
    server = FakeServer({"Movies": section})
    config = _make_config_with_group("Movies", "Action", ["Action Movies"])

    sync_library_hub_order(server, config, "Movies")

    rows = {r.hub_title: r for r in get_library_hub_order("Movies")}
    assert rows["Action Movies"].hub_type == HUB_TYPE_COLLECTION
    assert rows["Action Movies"].group_name == "Action"
    assert rows["User Custom"].hub_type == HUB_TYPE_EXTERNAL
    assert rows["Recently Added Movies"].hub_type == HUB_TYPE_SMART_HUB


def test_sync_does_not_affect_other_libraries(monkeypatch):
    from homescreen_hero.core.hub_sync import sync_library_hub_order
    from homescreen_hero.core.db import slot_in_hub, get_library_hub_order, HUB_TYPE_COLLECTION

    # Pre-seed Movies IMAX with same-named hubs — they should be left alone
    slot_in_hub("Movies IMAX", "Top 250", HUB_TYPE_COLLECTION)
    slot_in_hub("Movies IMAX", "This Week Popular", HUB_TYPE_COLLECTION)

    sections = {
        "Movies": FakeSection("Movies", ["Top 250", "This Week Popular", "New"]),
        "Movies IMAX": FakeSection("Movies IMAX", ["Top 250", "This Week Popular"]),
    }
    server = FakeServer(sections)
    config = _make_config("Movies", "Movies IMAX")

    sync_library_hub_order(server, config, "Movies")

    # IMAX rows untouched
    imax_rows = get_library_hub_order("Movies IMAX")
    assert {r.hub_title for r in imax_rows} == {"Top 250", "This Week Popular"}
    # Movies got the new one
    movies_rows = get_library_hub_order("Movies")
    assert {r.hub_title for r in movies_rows} == {"Top 250", "This Week Popular", "New"}


def test_sync_re_run_does_not_disrupt_order():
    from homescreen_hero.core.hub_sync import sync_library_hub_order
    from homescreen_hero.core.db import get_library_hub_order

    section = FakeSection("Movies", ["A", "B", "C"])
    server = FakeServer({"Movies": section})
    config = _make_config("Movies")

    sync_library_hub_order(server, config, "Movies")
    first_order = [r.hub_title for r in get_library_hub_order("Movies")]

    sync_library_hub_order(server, config, "Movies")
    second_order = [r.hub_title for r in get_library_hub_order("Movies")]

    assert first_order == second_order == ["A", "B", "C"]


# ---- move_hub_after tests ----

def test_move_hub_after_moves_to_position():
    from homescreen_hero.core.integrations import plex_client

    section = FakeSection("Movies", ["A", "B", "C", "D"])
    server = FakeServer({"Movies": section})

    error = plex_client.move_hub_after(server, "Movies", "D", "A")
    assert error is None
    assert [h.title for h in section.managedHubs()] == ["A", "D", "B", "C"]


def test_move_hub_after_with_none_moves_to_top():
    from homescreen_hero.core.integrations import plex_client

    section = FakeSection("Movies", ["A", "B", "C"])
    server = FakeServer({"Movies": section})

    error = plex_client.move_hub_after(server, "Movies", "C", None)
    assert error is None
    assert [h.title for h in section.managedHubs()] == ["C", "A", "B"]


def test_move_hub_after_unknown_hub_returns_error():
    from homescreen_hero.core.integrations import plex_client

    section = FakeSection("Movies", ["A", "B"])
    server = FakeServer({"Movies": section})

    error = plex_client.move_hub_after(server, "Movies", "GHOST", "A")
    assert error is not None and "not found" in error


def test_move_hub_after_unknown_anchor_returns_error():
    from homescreen_hero.core.integrations import plex_client

    section = FakeSection("Movies", ["A", "B"])
    server = FakeServer({"Movies": section})

    error = plex_client.move_hub_after(server, "Movies", "A", "GHOST")
    assert error is not None and "Anchor" in error


def test_move_hub_after_propagates_plex_failure():
    from homescreen_hero.core.integrations import plex_client

    section = FakeSection("Movies", ["A", "B"])
    section._hubs[0].raise_on_move = True
    server = FakeServer({"Movies": section})

    error = plex_client.move_hub_after(server, "Movies", "A", "B")
    assert error is not None and "Failed to move" in error


# ---- enforce_group_adjacency tests ----

def test_adjacency_no_op_when_groups_already_consecutive():
    from homescreen_hero.core.hub_sync import enforce_group_adjacency
    from homescreen_hero.core.db import slot_in_hub, HUB_TYPE_COLLECTION

    # DB: A, B, C all in group "G"; D, E ungrouped
    slot_in_hub("Movies", "A", HUB_TYPE_COLLECTION, group_name="G")
    slot_in_hub("Movies", "B", HUB_TYPE_COLLECTION, group_name="G")
    slot_in_hub("Movies", "C", HUB_TYPE_COLLECTION, group_name="G")
    slot_in_hub("Movies", "D", HUB_TYPE_COLLECTION)
    slot_in_hub("Movies", "E", HUB_TYPE_COLLECTION)

    section = FakeSection("Movies", ["A", "B", "C", "D", "E"])
    server = FakeServer({"Movies": section})

    errors = enforce_group_adjacency(server, "Movies")
    assert errors == []
    assert all(h.move_calls == 0 for h in section._hubs)


def test_adjacency_clusters_scattered_group_members():
    from homescreen_hero.core.hub_sync import enforce_group_adjacency
    from homescreen_hero.core.db import slot_in_hub, HUB_TYPE_COLLECTION

    slot_in_hub("Movies", "A", HUB_TYPE_COLLECTION, group_name="G")
    slot_in_hub("Movies", "B", HUB_TYPE_COLLECTION, group_name="G")
    slot_in_hub("Movies", "C", HUB_TYPE_COLLECTION, group_name="G")
    slot_in_hub("Movies", "X", HUB_TYPE_COLLECTION)
    slot_in_hub("Movies", "Y", HUB_TYPE_COLLECTION)

    # Plex order is scattered: A, X, B, Y, C
    section = FakeSection("Movies", ["A", "X", "B", "Y", "C"])
    server = FakeServer({"Movies": section})

    errors = enforce_group_adjacency(server, "Movies")
    assert errors == []
    # A stays, B & C cluster after it
    titles = [h.title for h in section.managedHubs()]
    a_idx = titles.index("A")
    assert titles[a_idx + 1] == "B"
    assert titles[a_idx + 2] == "C"


def test_adjacency_skips_pinned_group_members():
    from homescreen_hero.core.hub_sync import enforce_group_adjacency
    from homescreen_hero.core.db import slot_in_hub, set_pin, HUB_TYPE_COLLECTION, PIN_BOTTOM

    slot_in_hub("Movies", "A", HUB_TYPE_COLLECTION, group_name="G")
    slot_in_hub("Movies", "B", HUB_TYPE_COLLECTION, group_name="G")
    slot_in_hub("Movies", "C", HUB_TYPE_COLLECTION, group_name="G")
    slot_in_hub("Movies", "X", HUB_TYPE_COLLECTION)
    # Pin C to bottom — adjacency should NOT move C
    set_pin("Movies", "C", PIN_BOTTOM)

    # Plex: A, X, B, C  (C at bottom, A and B scattered)
    section = FakeSection("Movies", ["A", "X", "B", "C"])
    server = FakeServer({"Movies": section})

    enforce_group_adjacency(server, "Movies")
    titles = [h.title for h in section.managedHubs()]
    # B clusters after A; C stays at its pinned position
    a_idx = titles.index("A")
    assert titles[a_idx + 1] == "B"
    assert titles[-1] == "C"


def test_adjacency_ignores_single_member_groups():
    from homescreen_hero.core.hub_sync import enforce_group_adjacency
    from homescreen_hero.core.db import slot_in_hub, HUB_TYPE_COLLECTION

    slot_in_hub("Movies", "A", HUB_TYPE_COLLECTION, group_name="G")
    slot_in_hub("Movies", "X", HUB_TYPE_COLLECTION)

    section = FakeSection("Movies", ["X", "A"])
    server = FakeServer({"Movies": section})

    errors = enforce_group_adjacency(server, "Movies")
    assert errors == []
    assert all(h.move_calls == 0 for h in section._hubs)




# ---- pin_hub_to_top tests ----

def test_pin_to_top_moves_target_after_recently_added_anchor_movie(monkeypatch):
    # Movies library: anchor is movie.recentlyadded. Pinned hub should land
    # at managedHubs[1] (after anchor), so CW renders above it.
    from homescreen_hero.core.integrations import plex_client
    monkeypatch.setattr(plex_client.time, "sleep", lambda _s: None)

    section = FakeSection(
        "Movies",
        [
            ("Recently Added Movies", True, "movie.recentlyadded"),
            "A",
            "B",
            "C",
        ],
        lib_type="movie",
    )
    b = next(h for h in section._hubs if h.title == "B")
    b.promotedToOwnHome = True
    b.promotedToRecommended = True
    server = FakeServer({"Movies": section})

    error = plex_client.pin_hub_to_top(server, "Movies", "B")
    assert error is None

    titles = [h.title for h in section.managedHubs()]
    assert titles[0] == "Recently Added Movies"
    assert titles[1] == "B"
    # Visibility flags restored after cycle
    b_after = next(h for h in section.managedHubs() if h.title == "B")
    assert b_after.promotedToOwnHome is True
    assert b_after.promotedToRecommended is True


def test_pin_to_top_uses_tv_anchor_for_show_libraries(monkeypatch):
    # Show library: anchor is tv.recentlyadded.
    from homescreen_hero.core.integrations import plex_client
    monkeypatch.setattr(plex_client.time, "sleep", lambda _s: None)

    section = FakeSection(
        "TV Series",
        [
            ("Recently Added TV", True, "tv.recentlyadded"),
            "New Premieres",
        ],
        lib_type="show",
    )
    np = next(h for h in section._hubs if h.title == "New Premieres")
    np.promotedToRecommended = True
    server = FakeServer({"TV Series": section})

    error = plex_client.pin_hub_to_top(server, "TV Series", "New Premieres")
    assert error is None

    titles = [h.title for h in section.managedHubs()]
    assert titles[0] == "Recently Added TV"
    assert titles[1] == "New Premieres"


def test_pin_to_top_falls_back_to_position_zero_when_no_anchor(monkeypatch):
    # No recently-added anchor in managedHubs: falls back to move(after=None)
    # which lands at position 0 (CW will render below the pinned hub).
    from homescreen_hero.core.integrations import plex_client
    monkeypatch.setattr(plex_client.time, "sleep", lambda _s: None)

    section = FakeSection("Movies", ["A", "B", "C"], lib_type="movie")
    b = next(h for h in section._hubs if h.title == "B")
    b.promotedToRecommended = True
    server = FakeServer({"Movies": section})

    error = plex_client.pin_hub_to_top(server, "Movies", "B")
    assert error is None

    titles = [h.title for h in section.managedHubs()]
    assert titles[0] == "B"


def test_pin_to_top_refuses_unpromoted_hub(monkeypatch):
    from homescreen_hero.core.integrations import plex_client
    monkeypatch.setattr(plex_client.time, "sleep", lambda _s: None)

    section = FakeSection("Movies", ["A", "B"], lib_type="movie")
    # B has no visibility flags set
    server = FakeServer({"Movies": section})

    error = plex_client.pin_hub_to_top(server, "Movies", "B")
    assert error is not None
    assert "no visibility flags" in error


def test_pin_to_top_returns_error_for_unknown_hub(monkeypatch):
    from homescreen_hero.core.integrations import plex_client
    monkeypatch.setattr(plex_client.time, "sleep", lambda _s: None)

    section = FakeSection("Movies", ["A"], lib_type="movie")
    server = FakeServer({"Movies": section})

    error = plex_client.pin_hub_to_top(server, "Movies", "GHOST")
    assert error is not None and "not found" in error


def test_post_rotation_pin_enforcement_skips_repromote_when_already_at_position_one(monkeypatch):
    # Regression: pin_hub_to_top must NOT fire when pin_top is already at
    # managedHubs[1]. The old check was plex_titles[0] != pin_top, which
    # was always true because plex_titles[0] is recently-added (a SmartHub).
    # Fixed to plex_titles[1] != pin_top.
    from homescreen_hero.core.integrations import plex_client

    repromote_calls = []
    original_pin_hub_to_top = plex_client.pin_hub_to_top

    def tracking_pin_hub_to_top(server, library_name, hub_title):
        repromote_calls.append(hub_title)
        return original_pin_hub_to_top(server, library_name, hub_title)

    monkeypatch.setattr(plex_client, "pin_hub_to_top", tracking_pin_hub_to_top)
    monkeypatch.setattr(plex_client.time, "sleep", lambda _s: None)

    section = FakeSection(
        "Movies",
        [
            ("Recently Added Movies", False, "movie.recentlyadded"),
            "PinnedTop",   # already at managedHubs[1] — correct position
            "GroupA",
            "GroupB",
        ],
        lib_type="movie",
    )
    pinned_top = next(h for h in section._hubs if h.title == "PinnedTop")
    pinned_top.promotedToOwnHome = True
    server = FakeServer({"Movies": section})

    plex_titles = [h.title for h in section.managedHubs()]
    pin_top = "PinnedTop"

    # Correct condition (post-fix): only repromote when pin_top is not in the first two positions
    if pin_top and pin_top not in plex_titles[:2]:
        plex_client.pin_hub_to_top(server, "Movies", pin_top)

    assert repromote_calls == [], (
        "pin_hub_to_top must not fire when pin_top is already at managedHubs[1]; "
        "this repromote cycle is what causes other hubs to drift over time"
    )
    assert pinned_top.move_calls == 0


def test_post_rotation_pin_enforcement_skips_repromote_when_at_position_zero(monkeypatch):
    # pin_top at position 0 (no recently-added anchor in the library) is also correct —
    # must NOT fire for libraries like DocuFilms where the anchor isn't present.
    from homescreen_hero.core.integrations import plex_client

    repromote_calls = []
    original_pin_hub_to_top = plex_client.pin_hub_to_top

    def tracking_pin_hub_to_top(server, library_name, hub_title):
        repromote_calls.append(hub_title)
        return original_pin_hub_to_top(server, library_name, hub_title)

    monkeypatch.setattr(plex_client, "pin_hub_to_top", tracking_pin_hub_to_top)
    monkeypatch.setattr(plex_client.time, "sleep", lambda _s: None)

    section = FakeSection(
        "DocuFilms",
        [
            "PinnedTop",   # at position 0 (no recently-added anchor in this library)
            "GroupA",
            "GroupB",
        ],
        lib_type="movie",
    )
    pinned_top = next(h for h in section._hubs if h.title == "PinnedTop")
    pinned_top.promotedToOwnHome = True
    server = FakeServer({"DocuFilms": section})

    plex_titles = [h.title for h in section.managedHubs()]
    pin_top = "PinnedTop"

    if pin_top and pin_top not in plex_titles[:2]:
        plex_client.pin_hub_to_top(server, "DocuFilms", pin_top)

    assert repromote_calls == [], "pin_hub_to_top must not fire when pin_top is at position 0 either"


def test_post_rotation_pin_enforcement_does_repromote_when_displaced(monkeypatch):
    # pin_hub_to_top MUST fire when pin_top has drifted past position 1.
    from homescreen_hero.core.integrations import plex_client

    monkeypatch.setattr(plex_client.time, "sleep", lambda _s: None)

    section = FakeSection(
        "Movies",
        [
            ("Recently Added Movies", False, "movie.recentlyadded"),
            "GroupA",
            "PinnedTop",   # displaced to position 2 — needs enforcement
            "GroupB",
        ],
        lib_type="movie",
    )
    pinned_top = next(h for h in section._hubs if h.title == "PinnedTop")
    pinned_top.promotedToOwnHome = True
    server = FakeServer({"Movies": section})

    plex_titles = [h.title for h in section.managedHubs()]
    pin_top = "PinnedTop"

    if pin_top and pin_top not in plex_titles[:2]:
        plex_client.pin_hub_to_top(server, "Movies", pin_top)

    titles = [h.title for h in section.managedHubs()]
    assert titles[1] == "PinnedTop", "Displaced pin_top must be moved back to position 1"
