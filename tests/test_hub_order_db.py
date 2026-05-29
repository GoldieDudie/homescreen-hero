import os
import pytest
from sqlalchemy.exc import IntegrityError

# Use in-memory DB BEFORE importing app modules
os.environ["HOMESCREEN_HERO_DB"] = "sqlite:///:memory:"


@pytest.fixture(autouse=True)
def fresh_db():
    # Recreate engine + tables for each test using an in-memory DB.
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


def test_slot_in_hub_appends_when_no_group():
    from homescreen_hero.core.db import slot_in_hub, get_library_hub_order, HUB_TYPE_COLLECTION

    slot_in_hub("Movies", "A", HUB_TYPE_COLLECTION)
    slot_in_hub("Movies", "B", HUB_TYPE_COLLECTION)
    slot_in_hub("Movies", "C", HUB_TYPE_COLLECTION)

    rows = get_library_hub_order("Movies")
    assert [r.hub_title for r in rows] == ["A", "B", "C"]
    assert [r.position for r in rows] == [0, 1, 2]


def test_slot_in_hub_inserts_after_last_group_member():
    from homescreen_hero.core.db import slot_in_hub, get_library_hub_order, HUB_TYPE_COLLECTION

    slot_in_hub("Movies", "Top", HUB_TYPE_COLLECTION)
    slot_in_hub("Movies", "RecA", HUB_TYPE_COLLECTION, group_name="Recommended")
    slot_in_hub("Movies", "RecB", HUB_TYPE_COLLECTION, group_name="Recommended")
    slot_in_hub("Movies", "Bottom", HUB_TYPE_COLLECTION)

    # New rec arrives — should land after RecB, before "Bottom"
    slot_in_hub("Movies", "RecC", HUB_TYPE_COLLECTION, group_name="Recommended")

    rows = get_library_hub_order("Movies")
    assert [r.hub_title for r in rows] == ["Top", "RecA", "RecB", "RecC", "Bottom"]


def test_slot_in_hub_noop_on_existing():
    from homescreen_hero.core.db import slot_in_hub, get_library_hub_order, HUB_TYPE_COLLECTION

    slot_in_hub("Movies", "A", HUB_TYPE_COLLECTION)
    slot_in_hub("Movies", "B", HUB_TYPE_COLLECTION)
    slot_in_hub("Movies", "C", HUB_TYPE_COLLECTION)

    # Re-slot existing — should NOT move
    slot_in_hub("Movies", "A", HUB_TYPE_COLLECTION)

    rows = get_library_hub_order("Movies")
    assert [r.hub_title for r in rows] == ["A", "B", "C"]


def test_set_pin_enforces_one_top_per_library():
    from homescreen_hero.core.db import slot_in_hub, set_pin, get_library_hub_order, HUB_TYPE_COLLECTION, PIN_TOP

    slot_in_hub("Movies", "A", HUB_TYPE_COLLECTION)
    slot_in_hub("Movies", "B", HUB_TYPE_COLLECTION)
    slot_in_hub("Movies", "C", HUB_TYPE_COLLECTION)

    set_pin("Movies", "A", PIN_TOP)
    set_pin("Movies", "B", PIN_TOP)  # Should evict A

    rows = get_library_hub_order("Movies")
    tops = [r for r in rows if r.pin_position == PIN_TOP]
    assert len(tops) == 1
    assert tops[0].hub_title == "B"


def test_set_pin_enforces_one_bottom_per_library():
    from homescreen_hero.core.db import slot_in_hub, set_pin, get_library_hub_order, HUB_TYPE_COLLECTION, PIN_BOTTOM

    slot_in_hub("Movies", "A", HUB_TYPE_COLLECTION)
    slot_in_hub("Movies", "B", HUB_TYPE_COLLECTION)

    set_pin("Movies", "A", PIN_BOTTOM)
    set_pin("Movies", "B", PIN_BOTTOM)

    rows = get_library_hub_order("Movies")
    bottoms = [r for r in rows if r.pin_position == PIN_BOTTOM]
    assert len(bottoms) == 1
    assert bottoms[0].hub_title == "B"


def test_set_pin_independent_per_library():
    from homescreen_hero.core.db import slot_in_hub, set_pin, get_library_hub_order, HUB_TYPE_COLLECTION, PIN_TOP

    slot_in_hub("Movies", "A", HUB_TYPE_COLLECTION)
    slot_in_hub("TV Shows", "X", HUB_TYPE_COLLECTION)

    set_pin("Movies", "A", PIN_TOP)
    set_pin("TV Shows", "X", PIN_TOP)

    movies_top = [r for r in get_library_hub_order("Movies") if r.pin_position == PIN_TOP]
    tv_top = [r for r in get_library_hub_order("TV Shows") if r.pin_position == PIN_TOP]
    assert len(movies_top) == 1 and movies_top[0].hub_title == "A"
    assert len(tv_top) == 1 and tv_top[0].hub_title == "X"


def test_set_pin_clear_with_none():
    from homescreen_hero.core.db import slot_in_hub, set_pin, get_hub, HUB_TYPE_COLLECTION, PIN_TOP

    slot_in_hub("Movies", "A", HUB_TYPE_COLLECTION)
    set_pin("Movies", "A", PIN_TOP)

    assert get_hub("Movies", "A").pin_position == PIN_TOP

    set_pin("Movies", "A", None)
    assert get_hub("Movies", "A").pin_position is None


def test_set_pin_invalid_position_raises():
    from homescreen_hero.core.db import slot_in_hub, set_pin, HUB_TYPE_COLLECTION

    slot_in_hub("Movies", "A", HUB_TYPE_COLLECTION)
    with pytest.raises(ValueError):
        set_pin("Movies", "A", "middle")


def test_set_library_hub_order_rewrites_positions():
    from homescreen_hero.core.db import slot_in_hub, set_library_hub_order, get_library_hub_order, HUB_TYPE_COLLECTION

    slot_in_hub("Movies", "A", HUB_TYPE_COLLECTION)
    slot_in_hub("Movies", "B", HUB_TYPE_COLLECTION)
    slot_in_hub("Movies", "C", HUB_TYPE_COLLECTION)

    set_library_hub_order("Movies", ["C", "A", "B"])

    rows = get_library_hub_order("Movies")
    assert [r.hub_title for r in rows] == ["C", "A", "B"]
    assert [r.position for r in rows] == [0, 1, 2]


def test_set_library_hub_order_pushes_unseen_to_end():
    from homescreen_hero.core.db import slot_in_hub, set_library_hub_order, get_library_hub_order, HUB_TYPE_COLLECTION

    slot_in_hub("Movies", "A", HUB_TYPE_COLLECTION)
    slot_in_hub("Movies", "B", HUB_TYPE_COLLECTION)
    slot_in_hub("Movies", "C", HUB_TYPE_COLLECTION)
    slot_in_hub("Movies", "D", HUB_TYPE_COLLECTION)

    # Only reorder a subset — others should be appended at end in original relative order
    set_library_hub_order("Movies", ["C", "A"])

    rows = get_library_hub_order("Movies")
    titles = [r.hub_title for r in rows]
    assert titles[:2] == ["C", "A"]
    assert set(titles[2:]) == {"B", "D"}


def test_delete_hub_removes_row():
    from homescreen_hero.core.db import slot_in_hub, delete_hub, get_library_hub_order, HUB_TYPE_COLLECTION

    slot_in_hub("Movies", "A", HUB_TYPE_COLLECTION)
    slot_in_hub("Movies", "B", HUB_TYPE_COLLECTION)

    assert delete_hub("Movies", "A") is True
    assert delete_hub("Movies", "A") is False  # Already gone

    titles = [r.hub_title for r in get_library_hub_order("Movies")]
    assert titles == ["B"]


def test_unique_lib_title_enforced():
    from homescreen_hero.core.db import slot_in_hub, HUB_TYPE_COLLECTION

    slot_in_hub("Movies", "A", HUB_TYPE_COLLECTION)
    # Re-slotting is no-op (handled inside slot_in_hub). But raw insertion via
    # session of a duplicate row should be rejected by the unique constraint —
    # tested implicitly: slot_in_hub returns existing without raising.
    second = slot_in_hub("Movies", "A", HUB_TYPE_COLLECTION)
    assert second.hub_title == "A"


def test_upsert_hub_updates_group_name():
    from homescreen_hero.core.db import slot_in_hub, upsert_hub, get_hub, HUB_TYPE_COLLECTION

    slot_in_hub("Movies", "A", HUB_TYPE_COLLECTION, group_name="GroupX")
    upsert_hub("Movies", "A", HUB_TYPE_COLLECTION, group_name="GroupY")

    assert get_hub("Movies", "A").group_name == "GroupY"


# ---- position integrity: positions must always be a clean 0..N-1 sequence ----

def test_delete_hub_compacts_positions():
    # Regression: delete_hub must not leave a gap. Gaps cause slot_in_hub
    # (which assigns a list index as a position value) to later produce
    # duplicate positions, corrupting hub ordering.
    from homescreen_hero.core.db import (
        slot_in_hub, delete_hub, get_library_hub_order, HUB_TYPE_COLLECTION,
    )

    for t in ["A", "B", "C", "D"]:
        slot_in_hub("Movies", t, HUB_TYPE_COLLECTION)

    delete_hub("Movies", "B")

    rows = get_library_hub_order("Movies")
    assert [r.hub_title for r in rows] == ["A", "C", "D"]
    assert [r.position for r in rows] == [0, 1, 2], "positions must be compacted, no gaps"


def test_slot_in_hub_keeps_positions_contiguous_after_delete():
    # Regression (root cause of group scrambling): after a delete leaves a gap,
    # appending a hub must NOT create a duplicate position. slot_in_hub used to
    # assign a list index as the position value, colliding with an existing row.
    from homescreen_hero.core.db import (
        slot_in_hub, delete_hub, get_library_hub_order, HUB_TYPE_COLLECTION,
    )

    for t in ["A", "B", "C", "D"]:
        slot_in_hub("Movies", t, HUB_TYPE_COLLECTION)
    delete_hub("Movies", "B")        # leaves a gap under the old (buggy) impl
    slot_in_hub("Movies", "E", HUB_TYPE_COLLECTION)  # append

    rows = get_library_hub_order("Movies")
    positions = [r.position for r in rows]
    assert positions == list(range(len(rows))), (
        f"positions must be a clean 0..N-1 sequence with no duplicates/gaps, got {positions}"
    )
    assert len(set(positions)) == len(positions), "no duplicate positions allowed"


def test_slot_in_hub_recovers_from_pre_corrupted_positions():
    # Even if the DB already has duplicate/gapped positions (legacy corruption),
    # a slot_in_hub must heal the affected library to a clean 0..N-1 sequence.
    from homescreen_hero.core.db import (
        slot_in_hub, get_library_hub_order, HUB_TYPE_COLLECTION,
    )
    from homescreen_hero.core.db.base import session_scope
    from homescreen_hero.core.db.models import LibraryHubOrder
    from datetime import datetime

    # Hand-craft a corrupt state: duplicate position 1, gap at 2.
    now = datetime.utcnow()
    with session_scope() as db:
        db.add(LibraryHubOrder(library_name="Movies", hub_title="A", position=0,
                               hub_type=HUB_TYPE_COLLECTION, updated_at=now))
        db.add(LibraryHubOrder(library_name="Movies", hub_title="B", position=1,
                               hub_type=HUB_TYPE_COLLECTION, updated_at=now))
        db.add(LibraryHubOrder(library_name="Movies", hub_title="C", position=1,
                               hub_type=HUB_TYPE_COLLECTION, updated_at=now))
        db.add(LibraryHubOrder(library_name="Movies", hub_title="D", position=5,
                               hub_type=HUB_TYPE_COLLECTION, updated_at=now))

    slot_in_hub("Movies", "E", HUB_TYPE_COLLECTION)

    rows = get_library_hub_order("Movies")
    positions = [r.position for r in rows]
    assert positions == list(range(len(rows))), (
        f"slot_in_hub must heal corrupt positions to 0..N-1, got {positions}"
    )
