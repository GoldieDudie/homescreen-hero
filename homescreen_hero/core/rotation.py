from __future__ import annotations

import logging
import random
from collections import defaultdict
from datetime import date
from typing import Dict, List, Optional, Set, Tuple

from .config.schema import (
    AppConfig,
    CollectionGroupConfig,
    CollectionRef,
    DateRange,
    GroupSelectionResult,
    RotationResult,
    DisplaySettings,
)
from .db import CollectionUsage

logger = logging.getLogger(__name__)


def _get_ordered_groups(
    groups: List[CollectionGroupConfig],
    group_order: str,
    rng: random.Random,
) -> List[CollectionGroupConfig]:
    if group_order == "random":
        logger.debug("Randomizing group processing order")
        shuffled = list(groups)
        rng.shuffle(shuffled)
        return shuffled

    if group_order == "weighted":
        logger.debug("Using weighted group order: sorting groups by weight")
        return sorted(groups, key=lambda g: (-g.weight, groups.index(g)))
    else:
        logger.debug("Using display_order group order")
        return sorted(groups, key=lambda g: g.display_order)


def _select_collections_from_group(
    available: List[CollectionRef],
    k: int,
    collection_selection: str,
    usage_map: Dict[CollectionRef, CollectionUsage],
    rng: random.Random,
) -> List[CollectionRef]:
    if collection_selection == "lru":
        def sort_key(ref: CollectionRef) -> Tuple[int, int]:
            usage = usage_map.get(ref)
            if usage is None or usage.last_rotation_id is None:
                return (0, 0)
            return (1, usage.last_rotation_id)

        return sorted(available, key=sort_key)[:k]
    else:
        return rng.sample(available, k=k)


def _parse_month_day(value: str) -> Tuple[int, int]:
    try:
        month_str, day_str = value.split("-", 1)
        month = int(month_str)
        day = int(day_str)
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError(f"Invalid MM-DD date format: {value!r}") from exc

    if not (1 <= month <= 12):
        raise ValueError(f"Month out of range in {value!r}")
    if not (1 <= day <= 31):
        raise ValueError(f"Day out of range in {value!r}")

    return month, day


def _is_date_in_range(today: date, dr: DateRange) -> bool:
    start_m, start_d = _parse_month_day(dr.start)
    end_m, end_d = _parse_month_day(dr.end)

    today_tuple = (today.month, today.day)
    start_tuple = (start_m, start_d)
    end_tuple = (end_m, end_d)

    if start_tuple <= end_tuple:
        return start_tuple <= today_tuple <= end_tuple
    else:
        return today_tuple >= start_tuple or today_tuple <= end_tuple


def _group_is_active(group: CollectionGroupConfig, today: date) -> bool:
    if not group.enabled:
        return False
    if group.date_range is None:
        return True
    return _is_date_in_range(today, group.date_range)


def _passes_gap_rule(
    ref: CollectionRef,
    group: CollectionGroupConfig,
    max_rotation_id: int,
    usage_map: Dict[CollectionRef, CollectionUsage],
) -> bool:
    if group.min_gap_rotations <= 0:
        return True
    if max_rotation_id == 0:
        return True
    usage = usage_map.get(ref)
    if usage is None or usage.last_rotation_id is None:
        return True
    gap = max_rotation_id - usage.last_rotation_id
    return gap >= group.min_gap_rotations


def _is_blacklisted(ref: CollectionRef, blacklist: List[str]) -> bool:
    # Blacklist is name-only; blocks a collection across all libraries.
    return ref.name in blacklist


def _get_collection_pool(
    group: CollectionGroupConfig,
    smart_group_collections: Optional[Dict[str, List[CollectionRef]]] = None,
) -> List[CollectionRef]:
    if group.smart and smart_group_collections and group.name in smart_group_collections:
        return list(smart_group_collections[group.name])
    return list(group.collections)


def run_rotation_with_history(
    config: AppConfig,
    *,
    max_rotation_id: int,
    usage_map: Dict[CollectionRef, CollectionUsage],
    last_rotation_collections: Optional[List[CollectionRef]] = None,
    pinned: Optional[Set[CollectionRef]] = None,
    smart_group_collections: Optional[Dict[str, List[CollectionRef]]] = None,
    today: Optional[date] = None,
    rng: Optional[random.Random] = None,
) -> RotationResult:
    if today is None:
        today = date.today()
    if rng is None:
        rng = random.Random()

    max_global = config.rotation.max_collections
    # 0 means unlimited — use infinity so all comparisons / min() calls work unchanged
    remaining_global: float = float("inf") if max_global == 0 else max_global
    allow_repeats = config.rotation.allow_repeats
    last_rotation_set: Set[CollectionRef] = set(last_rotation_collections or [])
    per_library_limits = config.rotation.per_library_limits

    selected: List[CollectionRef] = []
    selected_set: Set[CollectionRef] = set()
    group_results: List[GroupSelectionResult] = []
    library_counts: Dict[str, int] = defaultdict(int)

    def within_library_limit(ref: CollectionRef) -> bool:
        if not per_library_limits:
            return True
        max_for_lib = per_library_limits.get(ref.library)
        if max_for_lib is None:
            return True
        return library_counts[ref.library] < max_for_lib

    pinned_set: Set[CollectionRef] = pinned or set()
    blacklist = config.rotation.blacklisted_collections

    pinned_selected: List[CollectionRef] = []
    for ref in sorted(pinned_set, key=lambda r: (r.library, r.name)):
        if not _is_blacklisted(ref, blacklist):
            pinned_selected.append(ref)
            selected_set.add(ref)

    if pinned_selected:
        logger.info(
            "Including %d pinned collections (not counted against max_collections): %s",
            len(pinned_selected),
            [str(r) for r in pinned_selected],
        )

    logger.info("Starting rotation with history: %d max rotations observed", max_rotation_id)

    ordered_groups = _get_ordered_groups(config.groups, config.rotation.group_order, rng)

    for group in ordered_groups:
        is_active = _group_is_active(group, today)
        pool = _get_collection_pool(group, smart_group_collections)

        result = GroupSelectionResult(
            group_name=group.name,
            active=is_active,
            min_picks=group.min_picks,
            max_picks=group.max_picks,
            available_collections=pool,
            chosen_collections=[],
            picked_count=0,
            reason_skipped=None,
        )

        if not is_active:
            result.reason_skipped = "Group disabled or outside date_range"
            group_results.append(result)
            continue

        if remaining_global <= 0:
            result.reason_skipped = "Global max_collections reached before this group was processed"
            group_results.append(result)
            continue

        # pick_all_matching means "always pick every match" — bypasses the
        # no-repeats and gap-rule filters (which are about variety), but still
        # respects blacklist and already-selected.
        pick_all = group.smart and group.pick_all_matching

        available = [r for r in pool if r not in selected_set]
        if not pick_all:
            available = [r for r in available if _passes_gap_rule(r, group, max_rotation_id, usage_map)]
        available = [r for r in available if not _is_blacklisted(r, blacklist)]

        if not pick_all and not allow_repeats and last_rotation_set:
            available = [r for r in available if r not in last_rotation_set]

        available = [r for r in available if within_library_limit(r)]

        result.available_collections = available

        if not available:
            result.reason_skipped = "No available collections after applying gap rule, blacklist, and repeats filter"
            group_results.append(result)
            continue

        # Smart groups with pick_all_matching bypass min/max_picks (still subject to global cap)
        pick_all = group.smart and group.pick_all_matching
        effective_max = len(available) if pick_all else group.max_picks
        max_for_group = min(effective_max, remaining_global, len(available))

        if max_for_group <= 0:
            result.reason_skipped = "max_picks for this group or global cap prevented any selection"
            group_results.append(result)
            continue

        min_for_group = max_for_group if pick_all else min(group.min_picks, max_for_group)

        if min_for_group == max_for_group:
            k = max_for_group
        else:
            k = rng.randint(min_for_group, max_for_group)

        if k <= 0:
            result.reason_skipped = "Randomly chose to pick 0 from this group"
            group_results.append(result)
            continue

        group_selection = group.collection_selection

        if per_library_limits:
            chosen: List[CollectionRef] = []
            remaining_available = list(available)
            for _ in range(k):
                eligible = [r for r in remaining_available if within_library_limit(r)]
                if not eligible:
                    break
                pick = _select_collections_from_group(eligible, 1, group_selection, usage_map, rng)
                if not pick:
                    break
                ref = pick[0]
                chosen.append(ref)
                remaining_available.remove(ref)
                library_counts[ref.library] += 1
        else:
            chosen = _select_collections_from_group(available, k, group_selection, usage_map, rng)
            for ref in chosen:
                library_counts[ref.library] += 1

        selected.extend(chosen)
        selected_set.update(chosen)
        remaining_global -= len(chosen)

        result.chosen_collections = chosen
        result.picked_count = len(chosen)
        group_results.append(result)

        if remaining_global <= 0:
            break

    final_selected = pinned_selected + selected

    rotation_result = RotationResult(
        selected_collections=final_selected,
        groups=group_results,
        max_global=max_global,
        remaining_global=-1 if remaining_global == float("inf") else int(remaining_global),
        today=today,
        per_library_counts=dict(library_counts),
    )

    logger.info(
        "Rotation complete with history: %d selected, %d remaining",
        len(selected),
        -1 if remaining_global == float("inf") else int(remaining_global),
    )
    if library_counts:
        logger.info("Per-library counts: %s", dict(library_counts))
    logger.debug("Group selection details: %s", group_results)

    return rotation_result


def run_auto_rotation_with_history(
    all_collections: List[CollectionRef],
    *,
    max_collections: int,
    collection_selection: str,
    blacklisted_collections: List[str],
    allow_repeats: bool,
    last_rotation_collections: List[CollectionRef],
    max_rotation_id: int,
    usage_map: Dict[CollectionRef, CollectionUsage],
    pinned: Optional[Set[CollectionRef]] = None,
    per_library_limits: Optional[Dict[str, int]] = None,
    today: Optional[date] = None,
    rng: Optional[random.Random] = None,
) -> RotationResult:
    if today is None:
        today = date.today()
    if rng is None:
        rng = random.Random()

    pinned_set: Set[CollectionRef] = pinned or set()
    all_names_set = {r.name for r in all_collections}
    last_rotation_set: Set[CollectionRef] = set(last_rotation_collections)
    per_library_limits = per_library_limits or {}
    library_counts: Dict[str, int] = defaultdict(int)

    pinned_selected: List[CollectionRef] = []
    for ref in sorted(pinned_set, key=lambda r: (r.library, r.name)):
        if ref.name not in blacklisted_collections and ref in {r for r in all_collections}:
            pinned_selected.append(ref)

    if pinned_selected:
        logger.info(
            "Auto-rotate: Including %d pinned collections: %s",
            len(pinned_selected),
            [str(r) for r in pinned_selected],
        )

    pinned_refs_set = set(pinned_selected)
    available = [
        r for r in all_collections
        if r.name not in blacklisted_collections and r not in pinned_refs_set
    ]

    if not allow_repeats and last_rotation_set:
        before_count = len(available)
        available = [r for r in available if r not in last_rotation_set]
        filtered_count = before_count - len(available)
        if filtered_count > 0:
            logger.info(
                "Auto-rotate: Filtered out %d collections from last rotation (allow_repeats=False)",
                filtered_count,
            )

    logger.info(
        "Auto-rotate: %d collections available after filtering (%d blacklisted, %d pinned%s)",
        len(available),
        len([r for r in all_collections if r.name in blacklisted_collections]),
        len(pinned_selected),
        ", repeats excluded" if not allow_repeats else "",
    )

    def within_library_limit(ref: CollectionRef) -> bool:
        if not per_library_limits:
            return True
        max_for_lib = per_library_limits.get(ref.library)
        if max_for_lib is None:
            return True
        return library_counts[ref.library] < max_for_lib

    selected: List[CollectionRef] = []
    if per_library_limits:
        remaining_available = list(available)
        while len(selected) < max_collections and remaining_available:
            eligible = [r for r in remaining_available if within_library_limit(r)]
            if not eligible:
                break
            chosen = _select_collections_from_group(eligible, 1, collection_selection, usage_map, rng)
            if not chosen:
                break
            ref = chosen[0]
            selected.append(ref)
            remaining_available.remove(ref)
            library_counts[ref.library] += 1
    else:
        k = min(max_collections, len(available))
        if k > 0:
            selected = _select_collections_from_group(available, k, collection_selection, usage_map, rng)
            for ref in selected:
                library_counts[ref.library] += 1

    group_result = GroupSelectionResult(
        group_name="All Collections (Auto-Rotate)",
        active=True,
        min_picks=0,
        max_picks=max_collections,
        available_collections=available,
        chosen_collections=selected,
        picked_count=len(selected),
        reason_skipped=None if selected else "No collections available after filtering",
    )

    final_selected = pinned_selected + selected

    rotation_result = RotationResult(
        selected_collections=final_selected,
        groups=[group_result],
        max_global=max_collections,
        remaining_global=max_collections - len(selected),
        today=today,
        per_library_counts=dict(library_counts),
    )

    logger.info(
        "Auto-rotate complete: %d selected (%d pinned + %d rotated)",
        len(final_selected),
        len(pinned_selected),
        len(selected),
    )

    return rotation_result


def run_rotation_dry(
    config: AppConfig,
    *,
    smart_group_collections: Optional[Dict[str, List[CollectionRef]]] = None,
    today: Optional[date] = None,
    rng: Optional[random.Random] = None,
) -> RotationResult:
    if today is None:
        today = date.today()
    if rng is None:
        rng = random.Random()

    max_global = config.rotation.max_collections
    remaining_global: float = float("inf") if max_global == 0 else max_global

    selected: List[CollectionRef] = []
    selected_set: Set[CollectionRef] = set()
    group_results: List[GroupSelectionResult] = []

    logger.info("Starting dry rotation for %d groups", len(config.groups))

    ordered_groups = _get_ordered_groups(config.groups, config.rotation.group_order, rng)

    usage_map: Dict[CollectionRef, CollectionUsage] = {}

    for group in ordered_groups:
        is_active = _group_is_active(group, today)
        pool = _get_collection_pool(group, smart_group_collections)

        result = GroupSelectionResult(
            group_name=group.name,
            active=is_active,
            min_picks=group.min_picks,
            max_picks=group.max_picks,
            available_collections=pool,
            chosen_collections=[],
            picked_count=0,
            reason_skipped=None,
        )

        if not is_active:
            result.reason_skipped = "Group disabled or outside date_range"
            group_results.append(result)
            continue

        if remaining_global <= 0:
            result.reason_skipped = "Global max_collections reached before this group was processed"
            group_results.append(result)
            continue

        available = [r for r in pool if r not in selected_set]
        blacklist = config.rotation.blacklisted_collections
        available = [r for r in available if not _is_blacklisted(r, blacklist)]

        result.available_collections = available

        if not available:
            result.reason_skipped = "No available collections (all already selected by other groups)"
            group_results.append(result)
            continue

        # Smart groups with pick_all_matching bypass min/max_picks (still subject to global cap)
        pick_all = group.smart and group.pick_all_matching
        effective_max = len(available) if pick_all else group.max_picks
        max_for_group = min(effective_max, remaining_global, len(available))

        if max_for_group <= 0:
            result.reason_skipped = "max_picks for this group or global cap prevented any selection"
            group_results.append(result)
            continue

        min_for_group = max_for_group if pick_all else min(group.min_picks, max_for_group)

        if min_for_group == max_for_group:
            k = max_for_group
        else:
            k = rng.randint(min_for_group, max_for_group)

        if k <= 0:
            result.reason_skipped = "Randomly chose to pick 0 from this group"
            group_results.append(result)
            continue

        chosen = _select_collections_from_group(available, k, group.collection_selection, usage_map, rng)

        selected.extend(chosen)
        selected_set.update(chosen)
        remaining_global -= k

        result.chosen_collections = chosen
        result.picked_count = k
        group_results.append(result)

        if remaining_global <= 0:
            break

    rotation_result = RotationResult(
        selected_collections=selected,
        groups=group_results,
        max_global=max_global,
        remaining_global=-1 if remaining_global == float("inf") else int(remaining_global),
        today=today,
    )

    logger.info(
        "Dry rotation complete: %d selected, %d remaining",
        len(selected),
        remaining_global,
    )
    logger.debug("Group selection details: %s", group_results)

    return rotation_result


def select_collections_for_rotation(
    config: AppConfig,
    *,
    smart_group_collections: Optional[Dict[str, List[CollectionRef]]] = None,
    today: Optional[date] = None,
    rng: Optional[random.Random] = None,
) -> List[CollectionRef]:
    result = run_rotation_dry(config, smart_group_collections=smart_group_collections, today=today, rng=rng)
    return result.selected_collections


def build_collection_visibility_map(
    config: AppConfig,
    smart_group_collections: Optional[Dict[str, List[CollectionRef]]] = None,
) -> Dict[CollectionRef, Dict[str, bool]]:
    """Build a mapping from CollectionRef to visibility settings based on the group it belongs to."""
    visibility_map: Dict[CollectionRef, Dict[str, bool]] = {}

    for group in config.groups:
        pool = _get_collection_pool(group, smart_group_collections)
        for ref in pool:
            if ref not in visibility_map:
                visibility_map[ref] = {
                    "home": group.visibility_home,
                    "shared": group.visibility_shared,
                    "recommended": group.visibility_recommended,
                }

    return visibility_map


def build_visibility_map_from_rotation_result(
    rotation_result: RotationResult,
    config: AppConfig,
    smart_group_collections: Optional[Dict[str, List[CollectionRef]]] = None,
) -> Dict[CollectionRef, Dict[str, bool]]:
    # Build visibility map using the group that actually selected each collection.
    visibility_map: Dict[CollectionRef, Dict[str, bool]] = {}
    group_cfg_map = {g.name: g for g in config.groups}

    for group_result in rotation_result.groups:
        gcfg = group_cfg_map.get(group_result.group_name)
        if not gcfg or not group_result.chosen_collections:
            continue
        for ref in group_result.chosen_collections:
            if ref not in visibility_map:
                visibility_map[ref] = {
                    "home": gcfg.visibility_home,
                    "shared": gcfg.visibility_shared,
                    "recommended": gcfg.visibility_recommended,
                }

    # Fallback for collections not attributed to any group result
    unattributed = [r for r in rotation_result.selected_collections if r not in visibility_map]
    if unattributed:
        fallback = build_collection_visibility_map(config, smart_group_collections)
        for ref in unattributed:
            visibility_map[ref] = fallback.get(ref, {
                "home": True,
                "shared": False,
                "recommended": False,
            })

    return visibility_map


def build_collection_sort_map(
    config: AppConfig,
    smart_group_collections: Optional[Dict[str, List[CollectionRef]]] = None,
) -> Dict[CollectionRef, str]:
    sort_map: Dict[CollectionRef, str] = {}

    for group in config.groups:
        if not group.collection_sort:
            continue
        pool = _get_collection_pool(group, smart_group_collections)
        for ref in pool:
            if ref not in sort_map:
                sort_map[ref] = group.collection_sort

    return sort_map


def _build_collection_group_map(
    config: AppConfig,
    smart_group_collections: Optional[Dict[str, List[CollectionRef]]] = None,
) -> Dict[CollectionRef, CollectionGroupConfig]:
    coll_to_group: Dict[CollectionRef, CollectionGroupConfig] = {}
    for group in config.groups:
        pool = _get_collection_pool(group, smart_group_collections)
        for ref in pool:
            if ref not in coll_to_group:
                coll_to_group[ref] = group
    return coll_to_group


def order_collections_for_display(
    collections: List[CollectionRef],
    config: AppConfig,
    pinned_names: Optional[Set[CollectionRef]] = None,
    pinned_order: Optional[Dict[CollectionRef, int]] = None,
    smart_group_collections: Optional[Dict[str, List[CollectionRef]]] = None,
    pinned_positions: Optional[Dict[CollectionRef, str]] = None,
    rng: Optional[random.Random] = None,
) -> List[CollectionRef]:
    if rng is None:
        rng = random.Random()
    pinned_names = pinned_names or set()
    pinned_order = pinned_order or {}
    pinned_positions = pinned_positions or {}

    coll_to_group = _build_collection_group_map(config, smart_group_collections)
    mode = config.display.group_display_mode

    pinned_top = [r for r in collections if r in pinned_names and pinned_positions.get(r, "top") != "bottom"]
    pinned_bottom = [r for r in collections if r in pinned_names and pinned_positions.get(r, "top") == "bottom"]
    non_pinned = [r for r in collections if r not in pinned_names]

    pinned_top.sort(key=lambda r: (pinned_order.get(r, 0), r.library, r.name))
    pinned_bottom.sort(key=lambda r: (pinned_order.get(r, 0), r.library, r.name))

    group_buckets: Dict[str, List[CollectionRef]] = {}
    ungrouped: List[CollectionRef] = []

    for ref in non_pinned:
        group = coll_to_group.get(ref)
        if group:
            group_buckets.setdefault(group.name, []).append(ref)
        else:
            ungrouped.append(ref)

    sorted_group_names = sorted(
        group_buckets.keys(),
        key=lambda gn: next((g.display_order for g in config.groups if g.name == gn), 0),
    )

    for gn in sorted_group_names:
        bucket = group_buckets[gn]
        group_cfg = next((g for g in config.groups if g.name == gn), None)
        coll_order = group_cfg.collection_order if group_cfg else None
        if coll_order == "alpha":
            bucket.sort(key=lambda r: (r.library, r.name))
        elif coll_order == "custom" and group_cfg and not group_cfg.smart:
            coll_list = group_cfg.collections
            logger.debug("Custom order for group '%s': config list=%s, bucket before sort=%s", gn, coll_list, bucket)
            bucket.sort(key=lambda r: coll_list.index(r) if r in coll_list else len(coll_list))
            logger.debug("Custom order for group '%s': bucket after sort=%s", gn, bucket)
        else:
            rng.shuffle(bucket)

    if mode == "merged":
        ordered: List[CollectionRef] = []
        buckets = [group_buckets[gn] for gn in sorted_group_names]
        max_len = max((len(b) for b in buckets), default=0)
        for i in range(max_len):
            for bucket in buckets:
                if i < len(bucket):
                    ordered.append(bucket[i])
        ordered.extend(ungrouped)
    else:
        ordered = []
        for gn in sorted_group_names:
            ordered.extend(group_buckets[gn])
        ordered.extend(ungrouped)

    result = pinned_top + ordered + pinned_bottom
    logger.debug("Display ordering (%s): %s", mode, [str(r) for r in result])
    return result
