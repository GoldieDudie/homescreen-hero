from __future__ import annotations

from datetime import datetime
import logging
from typing import Dict, List, Optional

from sqlalchemy import and_, delete, select

from .base import session_scope
from .models import LibraryHubOrder

logger = logging.getLogger(__name__)

# Hub type constants
HUB_TYPE_COLLECTION = "collection"
HUB_TYPE_SMART_HUB = "smart_hub"
HUB_TYPE_EXTERNAL = "external"

# Pin position constants
PIN_TOP = "top"
PIN_BOTTOM = "bottom"


def get_library_hub_order(library_name: str) -> List[LibraryHubOrder]:
    with session_scope() as db:
        stmt = (
            select(LibraryHubOrder)
            .where(LibraryHubOrder.library_name == library_name)
            .order_by(LibraryHubOrder.position.asc())
        )
        rows = list(db.execute(stmt).scalars().all())
        for r in rows:
            db.expunge(r)
        return rows


def get_all_libraries_hub_order() -> Dict[str, List[LibraryHubOrder]]:
    with session_scope() as db:
        stmt = select(LibraryHubOrder).order_by(
            LibraryHubOrder.library_name.asc(),
            LibraryHubOrder.position.asc(),
        )
        result: Dict[str, List[LibraryHubOrder]] = {}
        for row in db.execute(stmt).scalars().all():
            result.setdefault(row.library_name, []).append(row)
            db.expunge(row)
        return result


def get_hub(library_name: str, hub_title: str) -> Optional[LibraryHubOrder]:
    with session_scope() as db:
        stmt = select(LibraryHubOrder).where(
            and_(
                LibraryHubOrder.library_name == library_name,
                LibraryHubOrder.hub_title == hub_title,
            )
        )
        row = db.execute(stmt).scalar_one_or_none()
        if row is not None:
            db.expunge(row)
        return row


def set_library_hub_order(library_name: str, ordered_hub_titles: List[str]) -> None:
    # Rewrite positions for hubs in this library. Hubs not in the list keep their existing positions
    # bumped past the end (effectively appended). Pin position is preserved.
    now = datetime.utcnow()
    with session_scope() as db:
        existing_stmt = select(LibraryHubOrder).where(LibraryHubOrder.library_name == library_name)
        existing = {r.hub_title: r for r in db.execute(existing_stmt).scalars().all()}

        seen: set[str] = set()
        for idx, title in enumerate(ordered_hub_titles):
            row = existing.get(title)
            if row is None:
                logger.debug(
                    "set_library_hub_order: skipping unknown hub '%s' in library '%s' "
                    "(must be upserted first via slot_in_hub)",
                    title,
                    library_name,
                )
                continue
            row.position = idx
            row.updated_at = now
            seen.add(title)

        # Push unseen existing rows past the end, preserving their relative order
        unseen = [r for title, r in existing.items() if title not in seen]
        unseen.sort(key=lambda r: r.position)
        for offset, row in enumerate(unseen):
            row.position = len(ordered_hub_titles) + offset
            row.updated_at = now

        logger.info(
            "Set hub order for library '%s': %d hubs ordered, %d untouched",
            library_name,
            len(seen),
            len(unseen),
        )


def defragment_library_hub_order(library_name: str) -> bool:
    # Make each group's members contiguous WITHOUT changing where the group
    # sits. Each group is gathered at the START of its largest existing
    # contiguous run, so a single stray member (e.g. one re-appended by Plex on
    # rotation) can't relocate the whole group. Group order relative to other
    # groups, and the position of every non-group / pinned hub, are left exactly
    # as the DB has them — the DB order (set by the user's drags) is the source
    # of truth for WHERE each group lives. Derived purely from DB group metadata
    # (never reads Plex order), so it is safe to persist.
    #
    # Why: rotation churn can leave a group's members interleaved with other
    # groups in the DB. Adjacency enforcement then picks an anchor that lands
    # inside another group and splits it. Gathering members removes that, while
    # preserving manual placement (a group dragged below the external hubs stays
    # there).
    #
    # Returns True if the stored order changed.
    rows = get_library_hub_order(library_name)
    if not rows:
        return False

    pinned = {r.hub_title for r in rows if r.pin_position is not None}
    titles = [r.hub_title for r in rows]
    group_of = {
        r.hub_title: r.group_name
        for r in rows
        if r.group_name and r.hub_title not in pinned
    }

    members: Dict[str, List[str]] = {}
    for t in titles:
        g = group_of.get(t)
        if g:
            members.setdefault(g, []).append(t)
    if not members:
        return False

    index_of = {t: i for i, t in enumerate(titles)}

    # Anchor each group at the start of its largest contiguous run; ties keep
    # the earliest run.
    anchor_idx: Dict[str, int] = {}
    for g, mem in members.items():
        idxs = sorted(index_of[m] for m in mem)
        best_start, best_len = idxs[0], 1
        run_start, run_len = idxs[0], 1
        for prev, cur in zip(idxs, idxs[1:]):
            run_start, run_len = (run_start, run_len + 1) if cur == prev + 1 else (cur, 1)
            if run_len > best_len:
                best_len, best_start = run_len, run_start
        anchor_idx[g] = best_start

    canonical: List[str] = []
    emitted: set[str] = set()
    for i, t in enumerate(titles):
        g = group_of.get(t)
        if g:
            if g not in emitted and i == anchor_idx[g]:
                canonical.extend(members[g])
                emitted.add(g)
            # other member occurrences are skipped — emitted with the block
        else:
            canonical.append(t)

    if canonical == titles:
        return False

    set_library_hub_order(library_name, canonical)
    return True


def upsert_hub(
    library_name: str,
    hub_title: str,
    hub_type: str,
    *,
    group_name: Optional[str] = None,
    position: Optional[int] = None,
) -> LibraryHubOrder:
    # Insert hub if missing; update hub_type/group_name if exists.
    # Caller passes explicit position for new hubs (use slot_in_hub for the algorithm).
    now = datetime.utcnow()
    with session_scope() as db:
        stmt = select(LibraryHubOrder).where(
            and_(
                LibraryHubOrder.library_name == library_name,
                LibraryHubOrder.hub_title == hub_title,
            )
        )
        existing = db.execute(stmt).scalar_one_or_none()

        if existing is not None:
            existing.hub_type = hub_type
            existing.group_name = group_name
            existing.updated_at = now
            if position is not None:
                existing.position = position
            db.flush()
            db.expunge(existing)
            return existing

        if position is None:
            from sqlalchemy import func
            max_pos = db.execute(
                select(func.max(LibraryHubOrder.position)).where(
                    LibraryHubOrder.library_name == library_name
                )
            ).scalar()
            position = (max_pos if max_pos is not None else -1) + 1

        row = LibraryHubOrder(
            library_name=library_name,
            hub_title=hub_title,
            position=position,
            hub_type=hub_type,
            group_name=group_name,
            pin_position=None,
            updated_at=now,
        )
        db.add(row)
        db.flush()
        db.expunge(row)
        logger.info(
            "Upserted hub '%s' in library '%s' (type=%s, group=%s, position=%d)",
            hub_title,
            library_name,
            hub_type,
            group_name,
            position,
        )
        return row


def delete_hub(library_name: str, hub_title: str) -> bool:
    with session_scope() as db:
        stmt = select(LibraryHubOrder).where(
            and_(
                LibraryHubOrder.library_name == library_name,
                LibraryHubOrder.hub_title == hub_title,
            )
        )
        row = db.execute(stmt).scalar_one_or_none()
        if row is None:
            return False
        db.delete(row)
        db.flush()

        # Compact remaining positions to 0..N-1 so the delete leaves no gap.
        # Gaps let slot_in_hub later assign a colliding position value.
        remaining_stmt = (
            select(LibraryHubOrder)
            .where(LibraryHubOrder.library_name == library_name)
            .order_by(LibraryHubOrder.position.asc())
        )
        for i, r in enumerate(db.execute(remaining_stmt).scalars().all()):
            if r.position != i:
                r.position = i

        logger.info("Deleted hub '%s' from library '%s'", hub_title, library_name)
        return True


def set_pin(library_name: str, hub_title: str, pin_position: Optional[str]) -> Optional[LibraryHubOrder]:
    # Set or clear pin_position for a hub. Enforces per-library uniqueness:
    # if another hub already holds the requested slot, it is unpinned first.
    # pin_position=None clears the pin.
    if pin_position is not None and pin_position not in (PIN_TOP, PIN_BOTTOM):
        raise ValueError(f"Invalid pin_position: {pin_position!r}")

    now = datetime.utcnow()
    with session_scope() as db:
        target_stmt = select(LibraryHubOrder).where(
            and_(
                LibraryHubOrder.library_name == library_name,
                LibraryHubOrder.hub_title == hub_title,
            )
        )
        target = db.execute(target_stmt).scalar_one_or_none()
        if target is None:
            logger.warning(
                "set_pin: hub '%s' not found in library '%s'",
                hub_title,
                library_name,
            )
            return None

        if pin_position is not None:
            # Clear any existing pin in the same slot for this library
            conflict_stmt = select(LibraryHubOrder).where(
                and_(
                    LibraryHubOrder.library_name == library_name,
                    LibraryHubOrder.pin_position == pin_position,
                    LibraryHubOrder.hub_title != hub_title,
                )
            )
            for row in db.execute(conflict_stmt).scalars().all():
                row.pin_position = None
                row.updated_at = now
                logger.info(
                    "set_pin: cleared %s pin from '%s' in '%s' (replaced by '%s')",
                    pin_position,
                    row.hub_title,
                    library_name,
                    hub_title,
                )

        target.pin_position = pin_position
        target.updated_at = now
        db.flush()
        db.expunge(target)
        logger.info(
            "set_pin: hub '%s' in '%s' pin_position=%s",
            hub_title,
            library_name,
            pin_position,
        )
        return target


def slot_in_hub(
    library_name: str,
    hub_title: str,
    hub_type: str,
    *,
    group_name: Optional[str] = None,
) -> LibraryHubOrder:
    # Insert a new hub into the library at the right position based on slot-in rules:
    #   1. If hub belongs to a group that has existing members, insert after the last member.
    #   2. Else, append to end.
    # Pin position is NOT set here (set_pin handles that separately).
    # If hub already exists, this is a no-op (returns existing without repositioning).
    now = datetime.utcnow()
    with session_scope() as db:
        stmt = select(LibraryHubOrder).where(
            and_(
                LibraryHubOrder.library_name == library_name,
                LibraryHubOrder.hub_title == hub_title,
            )
        )
        existing = db.execute(stmt).scalar_one_or_none()
        if existing is not None:
            # Just refresh metadata, leave position alone
            existing.hub_type = hub_type
            existing.group_name = group_name
            existing.updated_at = now
            db.flush()
            db.expunge(existing)
            return existing

        # Compute insert index (position in the ordered list, not a stored value)
        all_in_lib_stmt = (
            select(LibraryHubOrder)
            .where(LibraryHubOrder.library_name == library_name)
            .order_by(LibraryHubOrder.position.asc())
        )
        all_rows = list(db.execute(all_in_lib_stmt).scalars().all())

        insert_idx: int
        if group_name is not None:
            # Find last member of this group
            last_member_idx = -1
            for i, row in enumerate(all_rows):
                if row.group_name == group_name:
                    last_member_idx = i
            insert_idx = last_member_idx + 1 if last_member_idx >= 0 else len(all_rows)
        else:
            insert_idx = len(all_rows)

        new_row = LibraryHubOrder(
            library_name=library_name,
            hub_title=hub_title,
            position=insert_idx,
            hub_type=hub_type,
            group_name=group_name,
            pin_position=None,
            updated_at=now,
        )
        db.add(new_row)

        # Renumber the whole library to a clean 0..N-1 sequence. This is the
        # ONLY safe way to assign positions: prior versions stored the list
        # index as a position value, which collided with existing rows once
        # delete_hub had left gaps — producing duplicate positions and
        # scrambling group ordering. Renumbering also self-heals any legacy
        # corruption present when this runs.
        ordered = all_rows[:insert_idx] + [new_row] + all_rows[insert_idx:]
        for i, row in enumerate(ordered):
            if row.position != i:
                row.position = i
                row.updated_at = now

        db.flush()
        db.expunge(new_row)
        logger.info(
            "slot_in_hub: inserted '%s' at position %d in '%s' (group=%s)",
            hub_title,
            insert_idx,
            library_name,
            group_name,
        )
        return new_row


def get_pin_for_slot(library_name: str, pin_position: str) -> Optional[LibraryHubOrder]:
    with session_scope() as db:
        stmt = select(LibraryHubOrder).where(
            and_(
                LibraryHubOrder.library_name == library_name,
                LibraryHubOrder.pin_position == pin_position,
            )
        )
        row = db.execute(stmt).scalar_one_or_none()
        if row is not None:
            db.expunge(row)
        return row


def clear_library(library_name: str) -> int:
    # Test helper: wipe all hub order rows for a library.
    with session_scope() as db:
        result = db.execute(
            delete(LibraryHubOrder).where(LibraryHubOrder.library_name == library_name)
        )
        return int(result.rowcount or 0)
