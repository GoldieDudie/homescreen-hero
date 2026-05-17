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

        # Compute insert position
        all_in_lib_stmt = (
            select(LibraryHubOrder)
            .where(LibraryHubOrder.library_name == library_name)
            .order_by(LibraryHubOrder.position.asc())
        )
        all_rows = list(db.execute(all_in_lib_stmt).scalars().all())

        insert_pos: int
        if group_name is not None:
            # Find last member of this group
            last_member_idx = -1
            for i, row in enumerate(all_rows):
                if row.group_name == group_name:
                    last_member_idx = i
            if last_member_idx >= 0:
                insert_pos = last_member_idx + 1
            else:
                insert_pos = len(all_rows)
        else:
            insert_pos = len(all_rows)

        # Shift everything at insert_pos and after up by 1
        for row in all_rows[insert_pos:]:
            row.position += 1

        new_row = LibraryHubOrder(
            library_name=library_name,
            hub_title=hub_title,
            position=insert_pos,
            hub_type=hub_type,
            group_name=group_name,
            pin_position=None,
            updated_at=now,
        )
        db.add(new_row)
        db.flush()
        db.expunge(new_row)
        logger.info(
            "slot_in_hub: inserted '%s' at position %d in '%s' (group=%s)",
            hub_title,
            insert_pos,
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
