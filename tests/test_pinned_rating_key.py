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


def _pin(name, lib, rating_key=None, home=True):
    from homescreen_hero.core.db import pin_collection
    from homescreen_hero.core.config.schema import CollectionRef
    pin_collection(
        CollectionRef(library=lib, name=name),
        visibility_home=home,
        rating_key=rating_key,
    )


def _pins_by_name():
    from homescreen_hero.core.db import get_pinned_collections
    return {(p.library_name, p.collection_name): p for p in get_pinned_collections()}


def test_reconcile_renames_pin_when_collection_renamed():
    # Pin stored under old name with a ratingKey; the collection is now named
    # something else in Plex under the same ratingKey → pin re-binds to new name.
    from homescreen_hero.core.db import reconcile_pinned_collection_identities

    _pin("Recently Added in Documentary Series", "DocuSeries", rating_key=67936, home=False)
    changes = reconcile_pinned_collection_identities(
        {"DocuSeries": [(67936, "Recently Added in Docuseries")]}
    )

    pins = _pins_by_name()
    assert ("DocuSeries", "Recently Added in Docuseries") in pins
    assert ("DocuSeries", "Recently Added in Documentary Series") not in pins
    # visibility preserved through the rename
    assert pins[("DocuSeries", "Recently Added in Docuseries")].visibility_home is False
    assert len(changes) == 1


def test_reconcile_backfills_rating_key_by_name():
    # Pre-existing pin with no ratingKey and a matching live name → backfilled.
    from homescreen_hero.core.db import reconcile_pinned_collection_identities

    _pin("Must See TV Series", "TV Series", rating_key=None)
    reconcile_pinned_collection_identities(
        {"TV Series": [(64886, "Must See TV Series")]}
    )
    p = _pins_by_name()[("TV Series", "Must See TV Series")]
    assert p.rating_key == 64886


def test_reconcile_leaves_orphan_untouched():
    # No ratingKey and no live collection by that name → left as-is, no crash.
    from homescreen_hero.core.db import reconcile_pinned_collection_identities

    _pin("Ghost Collection", "TV Series", rating_key=None)
    changes = reconcile_pinned_collection_identities(
        {"TV Series": [(1, "Something Else")]}
    )
    assert ("TV Series", "Ghost Collection") in _pins_by_name()
    assert changes == []


def test_reconcile_skips_rename_on_name_collision():
    # ratingKey says rename to a name that another pin already holds → skip.
    from homescreen_hero.core.db import reconcile_pinned_collection_identities

    _pin("Old Name", "TV Series", rating_key=500)
    _pin("New Name", "TV Series", rating_key=600)  # already holds the target name
    changes = reconcile_pinned_collection_identities(
        {"TV Series": [(500, "New Name"), (600, "New Name")]}
    )
    pins = _pins_by_name()
    assert ("TV Series", "Old Name") in pins  # rename skipped (collision)
    assert changes == []


def test_reconcile_keeps_pin_when_ratingkey_absent_live():
    # ratingKey set but collection missing from Plex (deleted) → pin untouched.
    from homescreen_hero.core.db import reconcile_pinned_collection_identities

    _pin("Deleted Coll", "TV Series", rating_key=777)
    reconcile_pinned_collection_identities({"TV Series": [(1, "Other")]})
    assert ("TV Series", "Deleted Coll") in _pins_by_name()
