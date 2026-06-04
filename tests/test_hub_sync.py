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
        # Simulate Plex float-precision convergence: while drifted, move()
        # ignores the requested position and appends to the end. A re-promote
        # visibility cycle clears it. Off by default so existing tests behave
        # exactly as before.
        self.drift_until_repromote = False
        self.visibility_cycles = 0

    def move(self, after=None):
        self.move_calls += 1
        if self.raise_on_move:
            raise Exception("Hub does not support move")
        if self.fail_first_move and self.move_calls == 1:
            raise Exception("Simulated transient Plex API failure")
        hubs = self.section._hubs
        hubs.remove(self)
        if self.drift_until_repromote:
            hubs.append(self)
            return
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
        if home:  # the re-promote (on) half of a recovery cycle
            self.visibility_cycles += 1
            self.drift_until_repromote = False


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


def _no_sleep(monkeypatch):
    # The re-promote recovery in move_hub_after_verified sleeps to let Plex
    # settle; skip it in tests.
    monkeypatch.setattr(
        "homescreen_hero.core.integrations.plex_client.time.sleep", lambda *_: None
    )


def test_adjacency_recovers_drifted_member_via_repromote(monkeypatch):
    # A scattered group member whose plain move() silently fails (float-precision
    # convergence) must be recovered by the unpromote/re-promote cycle so the
    # group still converges in a single rotation.
    from homescreen_hero.core.hub_sync import enforce_group_adjacency
    from homescreen_hero.core.db import slot_in_hub, HUB_TYPE_COLLECTION

    _no_sleep(monkeypatch)
    slot_in_hub("Movies", "A", HUB_TYPE_COLLECTION, group_name="G")
    slot_in_hub("Movies", "B", HUB_TYPE_COLLECTION, group_name="G")
    slot_in_hub("Movies", "C", HUB_TYPE_COLLECTION, group_name="G")
    slot_in_hub("Movies", "X", HUB_TYPE_COLLECTION)
    slot_in_hub("Movies", "Y", HUB_TYPE_COLLECTION)

    # Plex order scattered: A, X, B, Y, C — and B's moves drift until re-promote.
    section = FakeSection("Movies", ["A", "X", "B", "Y", "C"])
    server = FakeServer({"Movies": section})
    b = next(h for h in section._hubs if h.title == "B")
    b.promotedToOwnHome = True  # re-promotable collection
    b.drift_until_repromote = True

    errors = enforce_group_adjacency(server, "Movies")

    assert errors == []
    assert b.visibility_cycles == 1  # recovered via one re-promote
    titles = [h.title for h in section.managedHubs()]
    a_idx = titles.index("A")
    assert titles[a_idx + 1] == "B"
    assert titles[a_idx + 2] == "C"


def test_adjacency_reports_precision_convergence_for_unrecoverable_member(monkeypatch):
    # A drifted member that is NOT re-promotable (no visibility flags) cannot be
    # recovered; enforce must surface an error rather than silently leaving the
    # group scattered for every future rotation.
    from homescreen_hero.core.hub_sync import enforce_group_adjacency
    from homescreen_hero.core.db import slot_in_hub, HUB_TYPE_COLLECTION

    _no_sleep(monkeypatch)
    slot_in_hub("Movies", "A", HUB_TYPE_COLLECTION, group_name="G")
    slot_in_hub("Movies", "B", HUB_TYPE_COLLECTION, group_name="G")
    slot_in_hub("Movies", "C", HUB_TYPE_COLLECTION, group_name="G")
    slot_in_hub("Movies", "X", HUB_TYPE_COLLECTION)

    section = FakeSection("Movies", ["A", "X", "B", "C"])
    server = FakeServer({"Movies": section})
    b = next(h for h in section._hubs if h.title == "B")
    b.drift_until_repromote = True  # promotedToOwnHome stays False → unrecoverable

    errors = enforce_group_adjacency(server, "Movies")

    assert errors != []
    assert any("not re-promotable" in e or "precision convergence" in e for e in errors)
    assert b.visibility_cycles == 0


def test_adjacency_selective_skip_leaves_correct_members_untouched(monkeypatch):
    # Members already correctly slotted must not be moved (selective reordering),
    # minimising Plex moves and therefore convergence risk.
    from homescreen_hero.core.hub_sync import enforce_group_adjacency
    from homescreen_hero.core.db import slot_in_hub, HUB_TYPE_COLLECTION

    _no_sleep(monkeypatch)
    slot_in_hub("Movies", "A", HUB_TYPE_COLLECTION, group_name="G")
    slot_in_hub("Movies", "B", HUB_TYPE_COLLECTION, group_name="G")
    slot_in_hub("Movies", "C", HUB_TYPE_COLLECTION, group_name="G")
    slot_in_hub("Movies", "X", HUB_TYPE_COLLECTION)

    # A and B already adjacent and correctly placed; only C is scattered.
    section = FakeSection("Movies", ["A", "B", "X", "C"])
    server = FakeServer({"Movies": section})

    errors = enforce_group_adjacency(server, "Movies")

    assert errors == []
    moves = {h.title: h.move_calls for h in section._hubs}
    assert moves["A"] == 0 and moves["B"] == 0  # already correct → skipped
    assert moves["C"] >= 1  # the only one that needed moving
    titles = [h.title for h in section.managedHubs()]
    a_idx = titles.index("A")
    assert titles[a_idx:a_idx + 3] == ["A", "B", "C"]


def test_sync_does_not_overwrite_db_order_with_plex_order():
    # Regression: sync_library_hub_order must NOT overwrite DB positions with
    # Plex's current order. updateVisibility re-appends hubs to the end of the
    # Plex list, so reading Plex after visibility changes would bake corrupt
    # positions into DB and cause persistent group drift.
    from homescreen_hero.core.hub_sync import sync_library_hub_order
    from homescreen_hero.core.db import slot_in_hub, get_library_hub_order, HUB_TYPE_COLLECTION

    # DB says the desired order is A, B, C
    slot_in_hub("Movies", "A", HUB_TYPE_COLLECTION)
    slot_in_hub("Movies", "B", HUB_TYPE_COLLECTION)
    slot_in_hub("Movies", "C", HUB_TYPE_COLLECTION)

    # Plex has them in a different order (simulating updateVisibility corruption)
    section = FakeSection("Movies", ["A", "C", "B"])
    server = FakeServer({"Movies": section})
    config = _make_config("Movies")

    sync_library_hub_order(server, config, "Movies")

    rows = get_library_hub_order("Movies")
    assert [r.hub_title for r in rows] == ["A", "B", "C"], (
        "DB order must be preserved; sync must not overwrite it with Plex's (possibly corrupt) order"
    )


def test_enforce_group_adjacency_repositions_group_at_wrong_absolute_position():
    # Regression: when an entire group is contiguous but at the wrong absolute
    # position (e.g. appended to the end by updateVisibility), enforce_group_adjacency
    # must move the group to its DB-specified position, not just fix internal scattering.
    from homescreen_hero.core.hub_sync import enforce_group_adjacency
    from homescreen_hero.core.db import slot_in_hub, HUB_TYPE_COLLECTION

    # DB order: X(0), Y(1), A(2, group=G), B(3, group=G)
    # Group G should appear right after Y.
    slot_in_hub("Movies", "X", HUB_TYPE_COLLECTION)
    slot_in_hub("Movies", "Y", HUB_TYPE_COLLECTION)
    slot_in_hub("Movies", "A", HUB_TYPE_COLLECTION, group_name="G")
    slot_in_hub("Movies", "B", HUB_TYPE_COLLECTION, group_name="G")

    # Plex has the group appended to the end (contiguous but wrong position)
    section = FakeSection("Movies", ["X", "Y", "A", "B"])
    server = FakeServer({"Movies": section})

    # No-op: group is already right after Y
    errors = enforce_group_adjacency(server, "Movies")
    assert errors == []
    assert [h.title for h in section.managedHubs()] == ["X", "Y", "A", "B"]

    # Now simulate updateVisibility drift: A and B appended to end after Z
    section2_hubs = ["X", "Y", "Z", "A", "B"]
    from homescreen_hero.core.db import slot_in_hub as _slot
    _slot("Movies", "Z", HUB_TYPE_COLLECTION)  # Z has no group; DB pos=4, after B

    # Rebuild DB: X(0), Y(1), A(2,G), B(3,G), Z(4) — but Plex has X,Y,Z,A,B
    section2 = FakeSection("Movies", ["X", "Y", "Z", "A", "B"])
    server2 = FakeServer({"Movies": section2})

    errors = enforce_group_adjacency(server2, "Movies")
    assert errors == []
    titles = [h.title for h in section2.managedHubs()]
    # Group G (A, B) should be repositioned after Y (its DB anchor)
    y_idx = titles.index("Y")
    assert titles[y_idx + 1] == "A", f"A should follow Y; got {titles}"
    assert titles[y_idx + 2] == "B", f"B should follow A; got {titles}"


def test_enforce_group_adjacency_repositions_group_appended_after_existing_groups():
    # Simulates the real-world Recommended Movies drift: a group is appended to
    # the very end of Plex's hub list (all members contiguous) but should appear
    # much earlier, right after a specific anchor hub.
    from homescreen_hero.core.hub_sync import enforce_group_adjacency
    from homescreen_hero.core.db import slot_in_hub, HUB_TYPE_COLLECTION

    # DB order mirrors the Movies library layout:
    # Recently Added(0), New Premieres(1), Rec1(2,Rec), Rec2(3,Rec), Home1(4,HS), Home2(5,HS)
    slot_in_hub("Movies", "Recently Added", HUB_TYPE_COLLECTION)
    slot_in_hub("Movies", "New Premieres", HUB_TYPE_COLLECTION)
    slot_in_hub("Movies", "Rec1", HUB_TYPE_COLLECTION, group_name="Recommended")
    slot_in_hub("Movies", "Rec2", HUB_TYPE_COLLECTION, group_name="Recommended")
    slot_in_hub("Movies", "Home1", HUB_TYPE_COLLECTION, group_name="Home Screen")
    slot_in_hub("Movies", "Home2", HUB_TYPE_COLLECTION, group_name="Home Screen")

    # Plex has Recommended appended to end (updateVisibility drift)
    section = FakeSection("Movies", ["Recently Added", "New Premieres", "Home1", "Home2", "Rec1", "Rec2"])
    server = FakeServer({"Movies": section})

    errors = enforce_group_adjacency(server, "Movies")
    assert errors == []
    titles = [h.title for h in section.managedHubs()]

    # Recommended group should now be right after New Premieres (its DB anchor)
    np_idx = titles.index("New Premieres")
    assert titles[np_idx + 1] == "Rec1", f"Rec1 should follow New Premieres; got {titles}"
    assert titles[np_idx + 2] == "Rec2", f"Rec2 should follow Rec1; got {titles}"



def test_enforce_defrag_gathers_stray_member_at_largest_cluster():
    # A group with a stray member (e.g. one re-appended by Plex on rotation)
    # must be gathered at its LARGEST existing cluster — the stray moves to join
    # the bulk, the group is NOT relocated to the stray. Non-group hubs between
    # them keep their position.
    from homescreen_hero.core.hub_sync import enforce_group_adjacency
    from homescreen_hero.core.db import (
        slot_in_hub, set_library_hub_order, get_library_hub_order,
        HUB_TYPE_COLLECTION, HUB_TYPE_EXTERNAL,
    )

    slot_in_hub("Movies", "Top", HUB_TYPE_EXTERNAL)
    for t in ["RecStray", "RecA", "RecB", "RecC"]:
        slot_in_hub("Movies", t, HUB_TYPE_COLLECTION, group_name="Rec")
    for t in ["X1", "X2"]:
        slot_in_hub("Movies", t, HUB_TYPE_EXTERNAL)

    # Stray Rec member up top; the main Rec cluster lower; two external hubs between.
    set_library_hub_order("Movies", ["Top", "RecStray", "X1", "X2", "RecA", "RecB", "RecC"])

    section = FakeSection("Movies", ["Top", "RecStray", "X1", "X2", "RecA", "RecB", "RecC"])
    server = FakeServer({"Movies": section})

    errors = enforce_group_adjacency(server, "Movies")
    assert errors == []

    # Stray joined the main cluster (down at the bigger run); X1/X2 stay put.
    db_titles = [r.hub_title for r in get_library_hub_order("Movies")]
    assert db_titles == ["Top", "X1", "X2", "RecStray", "RecA", "RecB", "RecC"], (
        f"group should gather at its largest cluster, non-group hubs preserved; got {db_titles}"
    )
    plex = [h.title for h in section.managedHubs()]
    rec = sorted(plex.index(t) for t in ["RecStray", "RecA", "RecB", "RecC"])
    assert rec == list(range(rec[0], rec[0] + 4)), f"Rec group split in Plex: {plex}"


def test_enforce_respects_group_dragged_below_external_hubs():
    # The user's scenario: a group dragged BELOW the external hubs (above the
    # pinned-bottom hub) must STAY there — de-frag/enforce must not pull it back
    # up into the other groups. The DB order is authoritative for placement.
    from homescreen_hero.core.hub_sync import enforce_group_adjacency
    from homescreen_hero.core.db import (
        slot_in_hub, set_pin, set_library_hub_order, get_library_hub_order,
        HUB_TYPE_COLLECTION, HUB_TYPE_EXTERNAL, PIN_BOTTOM,
    )

    for t in ["RecA", "RecB"]:
        slot_in_hub("Movies", t, HUB_TYPE_COLLECTION, group_name="Rec")
    for t in ["HomeA", "HomeB"]:
        slot_in_hub("Movies", t, HUB_TYPE_COLLECTION, group_name="Home")
    for t in ["RecentlyAdded", "Top250"]:
        slot_in_hub("Movies", t, HUB_TYPE_EXTERNAL)
    slot_in_hub("Movies", "MustSee", HUB_TYPE_EXTERNAL)
    set_pin("Movies", "MustSee", PIN_BOTTOM)

    # Simulate the user dragging Home below the external hubs, just above the pin.
    dragged = ["RecA", "RecB", "RecentlyAdded", "Top250", "HomeA", "HomeB", "MustSee"]
    set_library_hub_order("Movies", dragged)

    section = FakeSection("Movies", list(dragged))
    server = FakeServer({"Movies": section})

    errors = enforce_group_adjacency(server, "Movies")
    assert errors == []

    db_titles = [r.hub_title for r in get_library_hub_order("Movies")]
    assert db_titles == dragged, (
        f"manually-placed group below external hubs must be preserved; got {db_titles}"
    )
    plex = [h.title for h in section.managedHubs()]
    assert plex.index("HomeA") > plex.index("Top250"), (
        f"Home group must stay below the external hubs in Plex: {plex}"
    )
    assert plex.index("HomeB") == plex.index("HomeA") + 1, f"Home split in Plex: {plex}"


def test_enforce_defragment_preserves_pinned_and_non_group_hubs():
    # De-fragmentation must not disturb pinned hubs or ungrouped hubs — only
    # gather group members. Pinned members are excluded from gathering.
    from homescreen_hero.core.hub_sync import enforce_group_adjacency
    from homescreen_hero.core.db import (
        slot_in_hub, set_pin, set_library_hub_order, get_library_hub_order,
        HUB_TYPE_COLLECTION, HUB_TYPE_EXTERNAL, PIN_BOTTOM,
    )

    slot_in_hub("Movies", "Top", HUB_TYPE_EXTERNAL)
    for t in ["GA", "GB", "GC"]:
        slot_in_hub("Movies", t, HUB_TYPE_COLLECTION, group_name="G")
    slot_in_hub("Movies", "Bottom", HUB_TYPE_EXTERNAL)
    set_pin("Movies", "Bottom", PIN_BOTTOM)

    set_library_hub_order("Movies", ["Top", "GA", "GB", "GC", "Bottom"])

    section = FakeSection("Movies", ["Top", "GA", "GB", "GC", "Bottom"])
    server = FakeServer({"Movies": section})

    enforce_group_adjacency(server, "Movies")

    rows = get_library_hub_order("Movies")
    db_titles = [r.hub_title for r in rows]
    # Already canonical; order unchanged. Pinned hub stays at the end.
    assert db_titles == ["Top", "GA", "GB", "GC", "Bottom"]
    assert rows[-1].hub_title == "Bottom" and rows[-1].pin_position == PIN_BOTTOM


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


# ---- inter-group order durability (Option B) ----

def _make_config_two_groups(library_name, g1, g1_colls, g2, g2_colls):
    # G1 has the LOWER display_order, so config wants G1 before G2.
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
                name=g1, enabled=True, min_picks=1, max_picks=10, display_order=0,
                collections=[CollectionRef(library=library_name, name=n) for n in g1_colls],
            ),
            CollectionGroupConfig(
                name=g2, enabled=True, min_picks=1, max_picks=10, display_order=1,
                collections=[CollectionRef(library=library_name, name=n) for n in g2_colls],
            ),
        ],
    )


def test_dragged_group_order_survives_full_churn():
    # User drags G2 ABOVE G1 on the dashboard (against config display_order).
    # A rotation then fully churns BOTH groups (every member replaced). The
    # dragged inter-group order (G2 before G1) must survive the rotation.
    from homescreen_hero.core.hub_sync import sync_library_hub_order, enforce_group_adjacency
    from homescreen_hero.core.db import slot_in_hub, get_library_hub_order, HUB_TYPE_COLLECTION

    lib = "Movies"
    config = _make_config_two_groups(
        lib,
        "G1", ["g1a", "g1b", "g1c", "g1d"],
        "G2", ["g2a", "g2b", "g2c", "g2d"],
    )

    # Seed DB in the DRAGGED order: G2 first, then G1.
    slot_in_hub(lib, "g2a", HUB_TYPE_COLLECTION, group_name="G2")
    slot_in_hub(lib, "g2b", HUB_TYPE_COLLECTION, group_name="G2")
    slot_in_hub(lib, "g1a", HUB_TYPE_COLLECTION, group_name="G1")
    slot_in_hub(lib, "g1b", HUB_TYPE_COLLECTION, group_name="G1")
    assert [r.group_name for r in get_library_hub_order(lib)] == ["G2", "G2", "G1", "G1"]

    # Rotation fully churns both groups. Plex now shows the new members, promoted
    # in CONFIG order (G1 first), exactly as order_collections_for_display emits.
    section = FakeSection(lib, ["g1c", "g1d", "g2c", "g2d"])
    server = FakeServer({lib: section})

    sync_library_hub_order(server, config, lib)
    enforce_group_adjacency(server, lib)

    db_groups = [r.group_name for r in get_library_hub_order(lib)]
    first_g2 = db_groups.index("G2")
    first_g1 = db_groups.index("G1")
    assert first_g2 < first_g1, f"dragged group order (G2 before G1) lost: {db_groups}"


def test_dragged_group_order_survives_partial_retention():
    # Same drag (G2 above G1), but each group retains one member across the
    # rotation. slot_in should anchor new members to the retained ones, keeping
    # the dragged order.
    from homescreen_hero.core.hub_sync import sync_library_hub_order, enforce_group_adjacency
    from homescreen_hero.core.db import slot_in_hub, get_library_hub_order, HUB_TYPE_COLLECTION

    lib = "Movies"
    config = _make_config_two_groups(
        lib,
        "G1", ["g1a", "g1b", "g1c"],
        "G2", ["g2a", "g2b", "g2c"],
    )

    slot_in_hub(lib, "g2a", HUB_TYPE_COLLECTION, group_name="G2")
    slot_in_hub(lib, "g2b", HUB_TYPE_COLLECTION, group_name="G2")
    slot_in_hub(lib, "g1a", HUB_TYPE_COLLECTION, group_name="G1")
    slot_in_hub(lib, "g1b", HUB_TYPE_COLLECTION, group_name="G1")

    # g2b and g1b retained; g2c and g1c are new.
    section = FakeSection(lib, ["g1b", "g1c", "g2b", "g2c"])
    server = FakeServer({lib: section})

    sync_library_hub_order(server, config, lib)
    enforce_group_adjacency(server, lib)

    db_groups = [r.group_name for r in get_library_hub_order(lib)]
    assert db_groups.index("G2") < db_groups.index("G1"), f"order lost: {db_groups}"
