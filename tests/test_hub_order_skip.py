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


def _ref(library, name):
    from homescreen_hero.core.config.schema import CollectionRef
    return CollectionRef(library=library, name=name)


# ---- _changed_libraries_since_last_rotation ----

def test_unchanged_membership_yields_no_changed_libraries():
    # A library whose promoted set is identical to the previous rotation must NOT
    # be flagged for re-enforcement (this is what skips the live-home churn).
    from homescreen_hero.core.db import record_rotation
    from homescreen_hero.core.service import _changed_libraries_since_last_rotation

    prev = [_ref("TV Series", "A"), _ref("TV Series", "B"), _ref("Movies", "M1")]
    record_rotation(prev)

    changed = _changed_libraries_since_last_rotation(list(prev))
    assert changed == set()


def test_added_member_flags_only_that_library():
    from homescreen_hero.core.db import record_rotation
    from homescreen_hero.core.service import _changed_libraries_since_last_rotation

    record_rotation([_ref("TV Series", "A"), _ref("Movies", "M1")])

    # TV Series gains a member; Movies unchanged.
    changed = _changed_libraries_since_last_rotation(
        [_ref("TV Series", "A"), _ref("TV Series", "B"), _ref("Movies", "M1")]
    )
    assert changed == {"TV Series"}


def test_removed_member_flags_that_library():
    from homescreen_hero.core.db import record_rotation
    from homescreen_hero.core.service import _changed_libraries_since_last_rotation

    record_rotation([_ref("TV Series", "A"), _ref("TV Series", "B"), _ref("Movies", "M1")])

    changed = _changed_libraries_since_last_rotation(
        [_ref("TV Series", "A"), _ref("Movies", "M1")]
    )
    assert changed == {"TV Series"}


def test_no_history_treats_all_current_libraries_as_changed():
    # First-ever rotation (no prior history): every library with members must be
    # enforced — we can't assume anything is already correctly clustered.
    from homescreen_hero.core.service import _changed_libraries_since_last_rotation

    changed = _changed_libraries_since_last_rotation(
        [_ref("TV Series", "A"), _ref("Movies", "M1")]
    )
    assert changed == {"TV Series", "Movies"}
