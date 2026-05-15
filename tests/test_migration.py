from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from homescreen_hero.core.config.migration import (
    MigrationError,
    build_source_library_map,
    migrate_collections,
    migrate_config_file,
    needs_collection_migration,
)


def _base_raw() -> dict:
    return {
        "plex": {"base_url": "http://x", "token": "t", "libraries": []},
        "rotation": {"enabled": True},
        "groups": [],
    }


def test_needs_collection_migration_detects_bare_string():
    raw = _base_raw()
    raw["groups"] = [{"name": "g", "collections": ["foo"]}]
    assert needs_collection_migration(raw) is True


def test_needs_collection_migration_skips_dict_format():
    raw = _base_raw()
    raw["groups"] = [{"name": "g", "collections": [{"library": "Movies", "name": "foo"}]}]
    assert needs_collection_migration(raw) is False


def test_needs_collection_migration_empty():
    assert needs_collection_migration({}) is False
    assert needs_collection_migration({"groups": []}) is False


def test_build_source_library_map_collects_from_all_sections():
    raw = _base_raw()
    raw["trakt"] = {"enabled": True, "sources": [{"name": "Trending", "plex_library": "Movies"}]}
    raw["mdblist"] = {"enabled": True, "sources": [{"name": "Top10", "plex_library": "TV Shows"}]}
    raw["tmdb"] = {"sources": [{"name": "TMDb Pop", "plex_library": "Movies"}]}
    raw["mal"] = {"sources": [{"name": "Anime Top", "plex_library": "Anime"}]}
    m = build_source_library_map(raw)
    assert m == {
        "Trending": "Movies",
        "Top10": "TV Shows",
        "TMDb Pop": "Movies",
        "Anime Top": "Anime",
    }


def test_build_source_library_map_ignores_malformed_entries():
    raw = {"trakt": {"sources": [{"name": "ok", "plex_library": "Movies"}, "junk", {"name": "noLib"}]}}
    m = build_source_library_map(raw)
    assert m == {"ok": "Movies"}


def test_migrate_uses_source_map_only():
    raw = _base_raw()
    raw["trakt"] = {"enabled": True, "sources": [{"name": "Trending", "plex_library": "Movies"}]}
    raw["groups"] = [{"name": "g1", "collections": ["Trending"]}]
    changed = migrate_collections(raw)
    assert changed is True
    assert raw["groups"][0]["collections"] == [{"library": "Movies", "name": "Trending"}]


def test_migrate_uses_plex_resolver_when_source_unknown():
    raw = _base_raw()
    raw["groups"] = [{"name": "g1", "collections": ["Space Movies"]}]

    def resolver(name):
        return ["Movies"] if name == "Space Movies" else []

    changed = migrate_collections(raw, plex_resolver=resolver)
    assert changed is True
    assert raw["groups"][0]["collections"] == [{"library": "Movies", "name": "Space Movies"}]


def test_migrate_aborts_on_ambiguous_name():
    raw = _base_raw()
    raw["groups"] = [{"name": "g1", "collections": ["Top 250"]}]

    def resolver(name):
        return ["Movies", "Movies IMAX"]

    with pytest.raises(MigrationError) as exc_info:
        migrate_collections(raw, plex_resolver=resolver)
    err = exc_info.value
    assert len(err.ambiguous) == 1
    assert err.ambiguous[0][0] == "g1"
    assert err.ambiguous[0][1] == "Top 250"
    assert err.ambiguous[0][2] == ["Movies", "Movies IMAX"]
    assert err.unresolved == []


def test_migrate_aborts_on_unresolvable_name():
    raw = _base_raw()
    raw["groups"] = [{"name": "g1", "collections": ["Nonexistent"]}]

    def resolver(name):
        return []

    with pytest.raises(MigrationError) as exc_info:
        migrate_collections(raw, plex_resolver=resolver)
    err = exc_info.value
    assert err.unresolved == [("g1", "Nonexistent")]
    assert err.ambiguous == []


def test_migrate_no_plex_resolver_unresolved_name():
    raw = _base_raw()
    raw["groups"] = [{"name": "g1", "collections": ["Space Movies"]}]
    with pytest.raises(MigrationError):
        migrate_collections(raw, plex_resolver=None)


def test_migrate_preserves_existing_dict_entries():
    raw = _base_raw()
    raw["trakt"] = {"sources": [{"name": "Trending", "plex_library": "Movies"}]}
    raw["groups"] = [
        {
            "name": "g1",
            "collections": ["Trending", {"library": "TV Shows", "name": "MyShow"}],
        }
    ]
    changed = migrate_collections(raw)
    assert changed is True
    assert raw["groups"][0]["collections"] == [
        {"library": "Movies", "name": "Trending"},
        {"library": "TV Shows", "name": "MyShow"},
    ]


def test_migrate_returns_false_when_nothing_to_change():
    raw = _base_raw()
    raw["groups"] = [{"name": "g1", "collections": [{"library": "Movies", "name": "X"}]}]
    assert migrate_collections(raw) is False


def test_migration_error_message_includes_ambiguous_and_unresolved():
    err = MigrationError(
        unresolved=[("g1", "Foo")],
        ambiguous=[("g2", "Bar", ["A", "B"])],
    )
    msg = str(err)
    assert "Foo" in msg
    assert "Bar" in msg
    assert "g1" in msg and "g2" in msg
    assert "A" in msg and "B" in msg


def test_migrate_config_file_writes_backup_and_new_format(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    raw = _base_raw()
    raw["trakt"] = {"sources": [{"name": "Trending", "plex_library": "Movies"}]}
    raw["groups"] = [{"name": "g1", "collections": ["Trending"]}]
    cfg.write_text(yaml.safe_dump(raw))

    changed = migrate_config_file(cfg)
    assert changed is True

    bak = cfg.with_suffix(".yaml.bak")
    assert bak.exists()
    assert "Trending" in bak.read_text()  # backup is original

    new_raw = yaml.safe_load(cfg.read_text())
    assert new_raw["groups"][0]["collections"] == [{"library": "Movies", "name": "Trending"}]


def test_migrate_config_file_noop_when_already_migrated(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    raw = _base_raw()
    raw["groups"] = [{"name": "g1", "collections": [{"library": "Movies", "name": "X"}]}]
    cfg.write_text(yaml.safe_dump(raw))
    assert migrate_config_file(cfg) is False
    assert not cfg.with_suffix(".yaml.bak").exists()
