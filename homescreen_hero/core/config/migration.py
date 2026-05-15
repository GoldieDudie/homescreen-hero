from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml


logger = logging.getLogger(__name__)


# Integration config sections that have `sources: [{name, plex_library}]`.
_SOURCE_SECTIONS = ("trakt", "letterboxd", "mdblist", "tmdb", "anilist", "mal")


class MigrationError(Exception):
    # Raised when bare-string collections can't be resolved to a (library, name) ref.
    def __init__(
        self,
        unresolved: List[Tuple[str, str]],
        ambiguous: List[Tuple[str, str, List[str]]],
    ) -> None:
        self.unresolved = unresolved
        self.ambiguous = ambiguous
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        lines = [
            "Cannot auto-migrate config.yaml to library-scoped collection format.",
            "",
        ]
        if self.ambiguous:
            lines.append("Ambiguous collection names (exist in multiple libraries):")
            for group, name, libs in self.ambiguous:
                lines.append(f"  - group '{group}': '{name}' found in {libs}")
            lines.append("")
        if self.unresolved:
            lines.append("Unresolvable collection names (not found in Plex or integration sources):")
            for group, name in self.unresolved:
                lines.append(f"  - group '{group}': '{name}'")
            lines.append("")
        lines.append(
            "Edit config.yaml to replace each bare string with {library: <name>, name: <name>}, "
            "then restart. See docs for the new collection format."
        )
        return "\n".join(lines)


def needs_collection_migration(raw_data: dict) -> bool:
    # Returns True if any group has a bare-string entry in its collections list.
    if not isinstance(raw_data, dict):
        return False
    for group in raw_data.get("groups") or []:
        if not isinstance(group, dict):
            continue
        for item in group.get("collections") or []:
            if isinstance(item, str):
                return True
    return False


def build_source_library_map(raw_data: dict) -> Dict[str, str]:
    # Build {collection_name -> plex_library} from configured integration sources.
    mapping: Dict[str, str] = {}
    for section_name in _SOURCE_SECTIONS:
        section = raw_data.get(section_name)
        if not isinstance(section, dict):
            continue
        for src in section.get("sources") or []:
            if not isinstance(src, dict):
                continue
            name = src.get("name")
            lib = src.get("plex_library")
            if isinstance(name, str) and isinstance(lib, str) and name and lib:
                mapping[name] = lib
    return mapping


def migrate_collections(
    raw_data: dict,
    plex_resolver: Optional[Callable[[str], List[str]]] = None,
) -> bool:
    # Mutate raw_data in place, converting bare-string collections to {library, name}.
    # plex_resolver(name) -> list of library names that contain a collection with that name.
    # Returns True if any change was made. Raises MigrationError if anything can't be resolved.
    source_map = build_source_library_map(raw_data)
    unresolved: List[Tuple[str, str]] = []
    ambiguous: List[Tuple[str, str, List[str]]] = []
    changed = False

    for group in raw_data.get("groups") or []:
        if not isinstance(group, dict):
            continue
        group_name = group.get("name", "?")
        new_collections: List[Any] = []
        for item in group.get("collections") or []:
            if not isinstance(item, str):
                new_collections.append(item)
                continue

            lib = source_map.get(item)

            if lib is None and plex_resolver is not None:
                try:
                    libs = plex_resolver(item)
                except Exception as exc:
                    logger.warning("Plex resolver failed for '%s': %s", item, exc)
                    libs = []
                if len(libs) == 1:
                    lib = libs[0]
                elif len(libs) > 1:
                    ambiguous.append((group_name, item, sorted(libs)))
                    new_collections.append(item)  # keep original so caller sees it
                    continue

            if lib is None:
                unresolved.append((group_name, item))
                new_collections.append(item)
                continue

            new_collections.append({"library": lib, "name": item})
            changed = True

        group["collections"] = new_collections

    if unresolved or ambiguous:
        raise MigrationError(unresolved, ambiguous)

    return changed


def build_plex_resolver_from_raw(raw_data: dict) -> Optional[Callable[[str], List[str]]]:
    # Build a Plex collection resolver from raw config data. Returns None if Plex
    # isn't configured or unreachable. The resolver returns library names that contain
    # a collection with the given name.
    try:
        from plexapi.server import PlexServer
        import requests
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except ImportError:
        logger.warning("plexapi not installed; cannot resolve collections from Plex")
        return None

    plex = raw_data.get("plex") or {}
    base_url = plex.get("base_url")
    # Token can come from env (HSH_PLEX_TOKEN) — check both.
    import os
    token = os.getenv("HSH_PLEX_TOKEN") or plex.get("token")

    if not base_url or not token:
        logger.warning("Plex base_url or token missing; cannot resolve collections from Plex")
        return None

    libraries_cfg = plex.get("libraries") or []
    library_names = [
        lib.get("name") for lib in libraries_cfg
        if isinstance(lib, dict) and lib.get("name") and lib.get("enabled", True)
    ]

    try:
        session = requests.Session()
        session.verify = False
        server = PlexServer(base_url, token, session=session)
    except Exception as exc:
        logger.warning("Could not connect to Plex at %s: %s", base_url, exc)
        return None

    # Pre-fetch all collections from configured libraries: name -> [libraries]
    by_name: Dict[str, List[str]] = {}
    if not library_names:
        # Fall back to all sections if libraries aren't enumerated in config
        try:
            library_names = [s.title for s in server.library.sections()]
        except Exception as exc:
            logger.warning("Could not enumerate Plex libraries: %s", exc)
            return None

    for lib_name in library_names:
        try:
            section = server.library.section(lib_name)
            for coll in section.collections():
                by_name.setdefault(coll.title, []).append(lib_name)
        except Exception as exc:
            logger.warning("Could not load collections from library '%s': %s", lib_name, exc)

    logger.info(
        "Plex resolver built: %d unique collection names across %d libraries",
        len(by_name),
        len(library_names),
    )

    def resolver(name: str) -> List[str]:
        return list(by_name.get(name, []))

    return resolver


def migrate_config_file(
    path: Path,
    plex_resolver: Optional[Callable[[str], List[str]]] = None,
    backup: bool = True,
) -> bool:
    # Migrate a config.yaml file in place. Writes a .bak copy first when backup=True.
    # Returns True if file was rewritten; False if no migration needed.
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict) or not needs_collection_migration(raw):
        return False

    changed = migrate_collections(raw, plex_resolver=plex_resolver)
    if not changed:
        return False

    if backup:
        bak_path = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, bak_path)
        logger.info("Backed up original config to %s", bak_path)

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, sort_keys=False, allow_unicode=True)
    tmp_path.replace(path)
    logger.info("Migrated config %s to library-scoped collection format", path)
    return True


def _cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m homescreen_hero.core.config.migration",
        description="Migrate config.yaml to library-scoped collection format.",
    )
    parser.add_argument("config", type=Path, help="Path to config.yaml")
    parser.add_argument(
        "--no-plex",
        action="store_true",
        help="Don't query Plex; only resolve names via integration sources",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Don't write a .bak copy of the original file",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    with args.config.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    resolver = None
    if not args.no_plex:
        resolver = build_plex_resolver_from_raw(raw)

    try:
        changed = migrate_config_file(
            args.config,
            plex_resolver=resolver,
            backup=not args.no_backup,
        )
    except MigrationError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if changed:
        print(f"Migrated {args.config}")
    else:
        print(f"No migration needed for {args.config}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
