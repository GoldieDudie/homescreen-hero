from __future__ import annotations

import json
import logging
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import requests
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from homescreen_hero.core.config.loader import load_config
from homescreen_hero.core.integrations.plex_client import (
    get_plex_server,
    get_library_collections,
)
from homescreen_hero.core.auth import CurrentUser, require_admin


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tools/poster-backup", tags=["tools"])

BACKUP_DIR_NAME = "poster-backups"


def _get_backup_root() -> Path:
    data_dir = Path(os.getenv("HSH_DATA_DIR", "data"))
    backup_root = data_dir / BACKUP_DIR_NAME
    backup_root.mkdir(parents=True, exist_ok=True)
    return backup_root


# Request / Response models

class BackupLibrarySelection(BaseModel):
    library_name: str
    include_movies: bool = False
    include_shows: bool = False
    include_collections: bool = False


class StartBackupRequest(BaseModel):
    libraries: List[BackupLibrarySelection]


class LibraryInfo(BaseModel):
    name: str
    type: str  # "movie" or "show"
    movie_count: int = 0
    show_count: int = 0
    collection_count: int = 0


class BackupSummary(BaseModel):
    id: str
    created_at: str
    total_posters: int
    movies: int
    shows: int
    collections: int
    size_mb: float
    libraries: List[str]


class BackupResult(BaseModel):
    id: str
    total_posters: int
    movies: int
    shows: int
    collections: int
    errors: int


class RestoreResult(BaseModel):
    total_restored: int
    errors: int


# Endpoints

@router.get("/libraries", response_model=List[LibraryInfo])
def get_libraries_for_backup(
    _current_user: CurrentUser = Depends(require_admin),
) -> List[LibraryInfo]:
    config = load_config()
    server = get_plex_server(config)

    libraries = []
    for lib_config in config.plex.libraries:
        if not lib_config.enabled:
            continue
        try:
            section = server.library.section(lib_config.name)
            lib_type = section.type  # "movie" or "show"

            collections = section.collections()

            libraries.append(LibraryInfo(
                name=lib_config.name,
                type=lib_type,
                movie_count=section.totalSize if lib_type == "movie" else 0,
                show_count=section.totalSize if lib_type == "show" else 0,
                collection_count=len(collections),
            ))
        except Exception as e:
            logger.warning("Failed to load library %s: %s", lib_config.name, e)

    return libraries


@router.post("/start")
def start_backup(
    request: StartBackupRequest,
    _current_user: CurrentUser = Depends(require_admin),
):
    if not request.libraries:
        raise HTTPException(status_code=400, detail="No libraries selected")

    def generate_events():
        config = load_config()
        server = get_plex_server(config)
        http_session = requests.Session()
        http_session.verify = False

        # First pass: count total items to back up
        total_items = 0
        lib_work = []  # (lib_selection, section, items_list, collections_list)

        for lib_selection in request.libraries:
            try:
                section = server.library.section(lib_selection.library_name)
            except Exception as e:
                logger.error("Library %s not found: %s", lib_selection.library_name, e)
                continue

            lib_type = section.type
            items_list = []
            collections_list = []

            if (lib_type == "movie" and lib_selection.include_movies) or \
               (lib_type == "show" and lib_selection.include_shows):
                items_list = section.all()
                total_items += len(items_list)

            if lib_selection.include_collections:
                collections_list = section.collections()
                total_items += len(collections_list)

            lib_work.append((lib_selection, section, items_list, collections_list))

        if total_items == 0:
            yield f"data: {json.dumps({'type': 'error', 'message': 'No items found to back up'})}\n\n"
            return

        # Send initial count
        yield f"data: {json.dumps({'type': 'start', 'total': total_items})}\n\n"

        timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        backup_dir = _get_backup_root() / timestamp

        manifest = {
            "created_at": datetime.now().isoformat(),
            "libraries": [],
            "items": [],
        }

        counts = {"movies": 0, "shows": 0, "collections": 0, "errors": 0}
        processed = 0

        for lib_selection, section, items_list, collections_list in lib_work:
            manifest["libraries"].append(lib_selection.library_name)
            lib_type = section.type

            # Back up movie/show posters
            if items_list:
                category = "movies" if lib_type == "movie" else "shows"
                category_dir = backup_dir / category
                category_dir.mkdir(parents=True, exist_ok=True)

                for item in items_list:
                    processed += 1
                    if not getattr(item, "thumb", None):
                        yield f"data: {json.dumps({'type': 'progress', 'processed': processed, 'total': total_items, 'title': item.title, 'skipped': True})}\n\n"
                        continue
                    try:
                        thumb_url = server.url(item.thumb, includeToken=True)
                        img_data = http_session.get(thumb_url, timeout=15).content
                        filename = f"{item.ratingKey}.jpg"
                        (category_dir / filename).write_bytes(img_data)

                        manifest["items"].append({
                            "type": category.rstrip("s"),
                            "rating_key": str(item.ratingKey),
                            "title": item.title,
                            "year": getattr(item, "year", None),
                            "library": lib_selection.library_name,
                            "filename": f"{category}/{filename}",
                        })
                        counts[category] += 1
                    except Exception as e:
                        logger.warning("Failed to backup poster for %s: %s", item.title, e)
                        counts["errors"] += 1

                    yield f"data: {json.dumps({'type': 'progress', 'processed': processed, 'total': total_items, 'title': item.title})}\n\n"

            # Back up collection posters
            if collections_list:
                collections_dir = backup_dir / "collections"
                collections_dir.mkdir(parents=True, exist_ok=True)

                for col in collections_list:
                    processed += 1
                    if not getattr(col, "thumb", None):
                        yield f"data: {json.dumps({'type': 'progress', 'processed': processed, 'total': total_items, 'title': col.title, 'skipped': True})}\n\n"
                        continue
                    try:
                        thumb_url = server.url(col.thumb, includeToken=True)
                        img_data = http_session.get(thumb_url, timeout=15).content
                        filename = f"{col.ratingKey}.jpg"
                        (collections_dir / filename).write_bytes(img_data)

                        manifest["items"].append({
                            "type": "collection",
                            "rating_key": str(col.ratingKey),
                            "title": col.title,
                            "library": lib_selection.library_name,
                            "filename": f"collections/{filename}",
                        })
                        counts["collections"] += 1
                    except Exception as e:
                        logger.warning("Failed to backup poster for collection %s: %s", col.title, e)
                        counts["errors"] += 1

                    yield f"data: {json.dumps({'type': 'progress', 'processed': processed, 'total': total_items, 'title': col.title})}\n\n"

        total = counts["movies"] + counts["shows"] + counts["collections"]

        if total == 0:
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            yield f"data: {json.dumps({'type': 'error', 'message': 'No posters found to back up'})}\n\n"
            return

        (backup_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

        yield f"data: {json.dumps({'type': 'complete', 'id': timestamp, 'total_posters': total, 'movies': counts['movies'], 'shows': counts['shows'], 'collections': counts['collections'], 'errors': counts['errors']})}\n\n"

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/list", response_model=List[BackupSummary])
def list_backups(
    _current_user: CurrentUser = Depends(require_admin),
) -> List[BackupSummary]:
    backup_root = _get_backup_root()
    backups = []

    for entry in sorted(backup_root.iterdir(), reverse=True):
        if not entry.is_dir():
            continue

        manifest_path = entry / "manifest.json"
        if not manifest_path.exists():
            continue

        try:
            manifest = json.loads(manifest_path.read_text())

            # Count by type
            movies = sum(1 for i in manifest["items"] if i["type"] == "movie")
            shows = sum(1 for i in manifest["items"] if i["type"] == "show")
            collections = sum(1 for i in manifest["items"] if i["type"] == "collection")

            # Calculate total size
            total_bytes = sum(
                f.stat().st_size
                for f in entry.rglob("*")
                if f.is_file()
            )

            backups.append(BackupSummary(
                id=entry.name,
                created_at=manifest.get("created_at", ""),
                total_posters=movies + shows + collections,
                movies=movies,
                shows=shows,
                collections=collections,
                size_mb=round(total_bytes / (1024 * 1024), 1),
                libraries=manifest.get("libraries", []),
            ))
        except Exception as e:
            logger.warning("Failed to read backup %s: %s", entry.name, e)

    return backups


@router.post("/restore/{backup_id}")
def restore_backup(
    backup_id: str,
    _current_user: CurrentUser = Depends(require_admin),
):
    backup_dir = _get_backup_root() / backup_id
    manifest_path = backup_dir / "manifest.json"

    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Backup not found")

    def generate_events():
        manifest = json.loads(manifest_path.read_text())
        config = load_config()
        server = get_plex_server(config)

        total = len(manifest["items"])
        yield f"data: {json.dumps({'type': 'start', 'total': total})}\n\n"

        restored = 0
        errors = 0

        for idx, item_entry in enumerate(manifest["items"], 1):
            poster_path = backup_dir / item_entry["filename"]
            if not poster_path.exists():
                errors += 1
                yield f"data: {json.dumps({'type': 'progress', 'processed': idx, 'total': total, 'title': item_entry.get('title', 'unknown')})}\n\n"
                continue

            try:
                rating_key = item_entry["rating_key"]
                item_type = item_entry["type"]

                if item_type == "collection":
                    section = server.library.section(item_entry["library"])
                    target = None
                    for col in section.collections():
                        if str(col.ratingKey) == rating_key:
                            target = col
                            break
                    if not target:
                        logger.warning("Collection %s not found, skipping", item_entry["title"])
                        errors += 1
                        yield f"data: {json.dumps({'type': 'progress', 'processed': idx, 'total': total, 'title': item_entry.get('title', 'unknown')})}\n\n"
                        continue
                else:
                    target = server.fetchItem(int(rating_key))

                target.uploadPoster(filepath=str(poster_path))
                restored += 1
                time.sleep(0.1)

            except Exception as e:
                logger.warning(
                    "Failed to restore poster for %s (%s): %s",
                    item_entry.get("title", "unknown"),
                    item_entry.get("type", "unknown"),
                    e,
                )
                errors += 1

            yield f"data: {json.dumps({'type': 'progress', 'processed': idx, 'total': total, 'title': item_entry.get('title', 'unknown')})}\n\n"

        yield f"data: {json.dumps({'type': 'complete', 'total_restored': restored, 'errors': errors})}\n\n"

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.delete("/{backup_id}")
def delete_backup(
    backup_id: str,
    _current_user: CurrentUser = Depends(require_admin),
) -> dict:
    backup_dir = _get_backup_root() / backup_id
    if not backup_dir.exists():
        raise HTTPException(status_code=404, detail="Backup not found")

    shutil.rmtree(backup_dir)
    return {"success": True, "message": f"Backup {backup_id} deleted"}
