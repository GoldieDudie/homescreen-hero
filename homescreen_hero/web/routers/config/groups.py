from __future__ import annotations

import os
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends

from homescreen_hero.core.auth import CurrentUser, require_admin
from homescreen_hero.core.config.loader import (
    CONFIG_ENV_VAR,
    get_config_path,
    load_config,
)
from homescreen_hero.core.config.schema import (
    CollectionGroupConfig,
    TraktSettings,
    LetterboxdSettings,
    MDBListSettings,
    TMDbSettings,
    AniListSettings,
    MALSettings,
)
from homescreen_hero.core.integrations.plex_client import get_plex_server
from homescreen_hero.core.poster_proxy import build_collection_poster_url

from .helpers import load_config_mapping, save_config_mapping, load_group_list
from .schemas import (
    ConfigSaveResponse,
    CollectionGroupPayload,
    GroupTargetUsersPayload,
    GroupVisibilityPayload,
    GroupValidationResult,
    CollectionSourcesResponse,
    GroupReorderRequest,
    SmartGroupPreviewRequest,
    SmartGroupPreviewResponse,
    SmartGroupPreviewCollection,
    SmartFilterOptionsResponse,
)

router = APIRouter()


# ========================================================================
# COLLECTION GROUPS CRUD
# ========================================================================

@router.get("/groups", response_model=list[CollectionGroupConfig])
def list_groups(current_user: CurrentUser = Depends(require_admin)) -> list[CollectionGroupConfig]:
    # Return list of all configured collection groups
    try:
        config = load_config()
        return config.groups
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/groups", response_model=ConfigSaveResponse)
def create_group(
    payload: CollectionGroupPayload,
    current_user: CurrentUser = Depends(require_admin)
) -> ConfigSaveResponse:
    # Append new collection group to config.yaml
    try:
        data = load_config_mapping()
        groups = load_group_list(data)

        new_group = payload.model_dump(exclude_none=True)
        # Place new groups at the end of the display order
        max_order = max((g.get("display_order", 0) for g in groups), default=-1)
        new_group["display_order"] = max_order + 1
        groups.append(new_group)
        config_path = get_config_path()
        save_config_mapping({**data, "groups": groups})

        return ConfigSaveResponse(
            ok=True,
            path=str(config_path),
            env_override=CONFIG_ENV_VAR in os.environ,
            message=f"Group '{payload.name}' added.",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/groups/{index}", response_model=ConfigSaveResponse)
def update_group(
    index: int,
    payload: CollectionGroupPayload,
    current_user: CurrentUser = Depends(require_admin),
) -> ConfigSaveResponse:
    # Replace existing collection group at given index in config.yaml
    try:
        data = load_config_mapping()
        groups = load_group_list(data)

        if index < 0 or index >= len(groups):
            raise HTTPException(status_code=404, detail="Group not found")

        groups[index] = payload.model_dump(exclude_none=True)
        config_path = get_config_path()
        save_config_mapping({**data, "groups": groups})

        return ConfigSaveResponse(
            ok=True,
            path=str(config_path),
            env_override=CONFIG_ENV_VAR in os.environ,
            message=f"Group '{payload.name}' updated.",
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/groups/{index}", response_model=ConfigSaveResponse)
def delete_group(
    index: int,
    current_user: CurrentUser = Depends(require_admin)
) -> ConfigSaveResponse:
    # Remove collection group at given index from config.yaml
    try:
        data = load_config_mapping()
        groups = load_group_list(data)

        if index < 0 or index >= len(groups):
            raise HTTPException(status_code=404, detail="Group not found")

        removed = groups.pop(index)
        config_path = get_config_path()
        save_config_mapping({**data, "groups": groups})

        name = removed.get("name") if isinstance(removed, dict) else None
        return ConfigSaveResponse(
            ok=True,
            path=str(config_path),
            env_override=CONFIG_ENV_VAR in os.environ,
            message=f"Group '{name or index}' deleted.",
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.patch("/groups/{index}/target-users", response_model=ConfigSaveResponse)
def set_group_target_users(
    index: int,
    payload: GroupTargetUsersPayload,
    current_user: CurrentUser = Depends(require_admin),
) -> ConfigSaveResponse:
    # Set target_users on a group without replacing the whole group
    try:
        data = load_config_mapping()
        groups = load_group_list(data)

        if index < 0 or index >= len(groups):
            raise HTTPException(status_code=404, detail="Group not found")

        group = groups[index]
        if payload.target_users is not None:
            group["target_users"] = payload.target_users
        else:
            group.pop("target_users", None)

        config_path = get_config_path()
        save_config_mapping({**data, "groups": groups})

        name = group.get("name", index)
        action = f"set to {payload.target_users}" if payload.target_users else "cleared"
        return ConfigSaveResponse(
            ok=True,
            path=str(config_path),
            env_override=CONFIG_ENV_VAR in os.environ,
            message=f"Target users for '{name}' {action}.",
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.patch("/groups/{index}/visibility", response_model=ConfigSaveResponse)
def patch_group_visibility(
    index: int,
    payload: GroupVisibilityPayload,
    current_user: CurrentUser = Depends(require_admin),
) -> ConfigSaveResponse:
    # Update only the three visibility flags on a group without touching the rest of its config
    try:
        data = load_config_mapping()
        groups = load_group_list(data)

        if index < 0 or index >= len(groups):
            raise HTTPException(status_code=404, detail="Group not found")

        groups[index]["visibility_home"] = payload.visibility_home
        groups[index]["visibility_shared"] = payload.visibility_shared
        groups[index]["visibility_recommended"] = payload.visibility_recommended

        config_path = get_config_path()
        save_config_mapping({**data, "groups": groups})

        name = groups[index].get("name", index)
        return ConfigSaveResponse(
            ok=True,
            path=str(config_path),
            env_override=CONFIG_ENV_VAR in os.environ,
            message=f"Visibility for '{name}' updated.",
        )
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/groups/reorder", response_model=ConfigSaveResponse)
def reorder_groups(
    payload: GroupReorderRequest,
    current_user: CurrentUser = Depends(require_admin),
) -> ConfigSaveResponse:
    # Update display_order for each group based on the provided name ordering
    try:
        data = load_config_mapping()
        groups = load_group_list(data)

        # Build a name->index lookup for the requested order
        name_to_order = {name: i for i, name in enumerate(payload.ordered_group_names)}

        # Update display_order on each group
        for group in groups:
            group_name = group.get("name", "")
            if group_name in name_to_order:
                group["display_order"] = name_to_order[group_name]

        config_path = get_config_path()
        save_config_mapping({**data, "groups": groups})

        return ConfigSaveResponse(
            ok=True,
            path=str(config_path),
            env_override=CONFIG_ENV_VAR in os.environ,
            message=f"Updated display order for {len(name_to_order)} groups.",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ========================================================================
# GROUP SOURCES (available collections for groups)
# ========================================================================

@router.get("/group-sources", response_model=CollectionSourcesResponse)
def list_group_sources(current_user: CurrentUser = Depends(require_admin)) -> CollectionSourcesResponse:
    # Return list of all available Plex collections and configured Trakt/Letterboxd sources
    try:
        config = load_config()
        server = get_plex_server(config)

        plex_sources: list[CollectionSourcesResponse.CollectionSource] = []
        for section in server.library.sections():
            try:
                for col in section.collections():
                    poster_url = build_collection_poster_url(server, col)
                    plex_sources.append(
                        CollectionSourcesResponse.CollectionSource(
                            name=col.title,
                            library=section.title,
                            source="plex",
                            detail=section.title,
                            poster_url=poster_url,
                        )
                    )
            except Exception:  # pragma: no cover - defensive
                continue

        trakt_sources: list[CollectionSourcesResponse.CollectionSource] = []
        trakt_cfg: Optional[TraktSettings] = getattr(config, "trakt", None)
        if trakt_cfg and getattr(trakt_cfg, "sources", None):
            for src in trakt_cfg.sources:
                trakt_sources.append(
                    CollectionSourcesResponse.CollectionSource(
                        name=src.name,
                        library=src.plex_library,
                        source="trakt",
                        detail=src.url,
                    )
                )

        letterboxd_sources: list[CollectionSourcesResponse.CollectionSource] = []
        letterboxd_cfg: Optional[LetterboxdSettings] = getattr(config, "letterboxd", None)
        if letterboxd_cfg and getattr(letterboxd_cfg, "sources", None):
            for src in letterboxd_cfg.sources:
                letterboxd_sources.append(
                    CollectionSourcesResponse.CollectionSource(
                        name=src.name,
                        library=src.plex_library,
                        source="letterboxd",
                        detail=src.url,
                    )
                )

        mdblist_sources: list[CollectionSourcesResponse.CollectionSource] = []
        mdblist_cfg: Optional[MDBListSettings] = getattr(config, "mdblist", None)
        if mdblist_cfg and getattr(mdblist_cfg, "sources", None):
            for src in mdblist_cfg.sources:
                mdblist_sources.append(
                    CollectionSourcesResponse.CollectionSource(
                        name=src.name,
                        library=src.plex_library,
                        source="mdblist",
                        detail=src.url,
                    )
                )

        tmdb_sources: list[CollectionSourcesResponse.CollectionSource] = []
        tmdb_cfg: Optional[TMDbSettings] = getattr(config, "tmdb", None)
        if tmdb_cfg and getattr(tmdb_cfg, "sources", None):
            for src in tmdb_cfg.sources:
                tmdb_sources.append(
                    CollectionSourcesResponse.CollectionSource(
                        name=src.name,
                        library=src.plex_library,
                        source="tmdb",
                        detail=src.url,
                    )
                )

        anilist_sources: list[CollectionSourcesResponse.CollectionSource] = []
        anilist_cfg: Optional[AniListSettings] = getattr(config, "anilist", None)
        if anilist_cfg and getattr(anilist_cfg, "sources", None):
            for src in anilist_cfg.sources:
                anilist_sources.append(
                    CollectionSourcesResponse.CollectionSource(
                        name=src.name,
                        library=src.plex_library,
                        source="anilist",
                        detail=src.url,
                    )
                )

        mal_sources: list[CollectionSourcesResponse.CollectionSource] = []
        mal_cfg: Optional[MALSettings] = getattr(config, "mal", None)
        if mal_cfg and getattr(mal_cfg, "sources", None):
            for src in mal_cfg.sources:
                mal_sources.append(
                    CollectionSourcesResponse.CollectionSource(
                        name=src.name,
                        library=src.plex_library,
                        source="mal",
                        detail=src.url,
                    )
                )

        # Filter Plex entries that duplicate an integration source (same library + name).
        # Each integration source authoritatively owns one (library, name) pair; Plex
        # exposes the synced copy. Without this, the picker shows duplicates.
        integration_keys = {
            (s.library, s.name)
            for s in trakt_sources + letterboxd_sources + mdblist_sources + tmdb_sources + anilist_sources + mal_sources
        }
        plex_sources = [s for s in plex_sources if (s.library, s.name) not in integration_keys]

        return CollectionSourcesResponse(
            plex=plex_sources,
            trakt=trakt_sources,
            letterboxd=letterboxd_sources,
            mdblist=mdblist_sources,
            tmdb=tmdb_sources,
            anilist=anilist_sources,
            mal=mal_sources,
        )
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ========================================================================
# SMART GROUPS
# ========================================================================

@router.post("/groups/preview-smart", response_model=SmartGroupPreviewResponse)
def preview_smart_group(
    payload: SmartGroupPreviewRequest,
    current_user: CurrentUser = Depends(require_admin),
) -> SmartGroupPreviewResponse:
    # Evaluate smart group rules and return matching collections with poster URLs.
    from homescreen_hero.core.smart_groups import build_collection_metadata, resolve_smart_rules

    try:
        config = load_config()
        server = get_plex_server(config)
        metadata = build_collection_metadata(server, config)
        matching_names = resolve_smart_rules(payload.rules, metadata)

        # Build (library, name) → metadata lookup for poster URLs
        meta_by_ref = {(m.library, m.name): m for m in metadata}
        collections = []
        for ref in matching_names:
            meta = meta_by_ref.get((ref.library, ref.name))
            collections.append(
                SmartGroupPreviewCollection(
                    name=ref.name,
                    library=ref.library,
                    poster_url=meta.poster_url if meta else None,
                )
            )
        return SmartGroupPreviewResponse(collections=collections, count=len(collections))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/groups/smart-filter-options", response_model=SmartFilterOptionsResponse)
def get_smart_filter_options(
    current_user: CurrentUser = Depends(require_admin),
) -> SmartFilterOptionsResponse:
    # Return available values for smart group rule builder dropdowns.
    from homescreen_hero.core.smart_groups import get_available_filter_options

    try:
        config = load_config()
        server = get_plex_server(config)
        options = get_available_filter_options(server, config)
        return SmartFilterOptionsResponse(**options)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ========================================================================
# VALIDATION
# ========================================================================

@router.get("/validate", response_model=List[GroupValidationResult])
def validate_config_groups(current_user: CurrentUser = Depends(require_admin)) -> List[GroupValidationResult]:
    # Validate configured collection groups against Plex collections.
    # A collection is "missing" if no (library, name) match exists in Plex.
    config = load_config()
    server = get_plex_server(config)

    plex_keys: set[tuple[str, str]] = set()
    for section in server.library.sections():
        try:
            for col in section.collections():
                plex_keys.add((section.title, col.title))
        except Exception:
            continue

    results: list[GroupValidationResult] = []
    for group in getattr(config, "groups", []):
        group_name = getattr(group, "name", "Unnamed")
        collections = list(getattr(group, "collections", []))

        issues: list[str] = []
        duplicates: list[str] = []

        seen: set[tuple[str, str]] = set()
        for ref in collections:
            key = (ref.library, ref.name)
            if key in seen and str(ref) not in duplicates:
                duplicates.append(str(ref))
            seen.add(key)

        if duplicates:
            issues.append(f"Duplicate collections in group: {', '.join(duplicates)}")

        missing = [str(ref) for ref in collections if (ref.library, ref.name) not in plex_keys]
        if missing:
            issues.append(f"Missing in Plex: {', '.join(missing)}")

        results.append(
            GroupValidationResult(
                name=group_name,
                collections=collections,
                ok=not issues,
                issues=issues,
            )
        )

    return results
