from __future__ import annotations

from datetime import datetime
import logging
from typing import Dict, List, Optional, Set

from sqlalchemy import and_, func, select

from .base import session_scope
from .models import CollectionDisplayOrder, PinnedCollection
from ..config.schema import CollectionRef

logger = logging.getLogger(__name__)


def get_pinned_collections() -> List[PinnedCollection]:
    with session_scope() as db:
        stmt = select(PinnedCollection).order_by(PinnedCollection.display_order.asc())
        return list(db.execute(stmt).scalars().all())


def get_pinned_refs() -> Set[CollectionRef]:
    with session_scope() as db:
        stmt = select(PinnedCollection.library_name, PinnedCollection.collection_name)
        rows = db.execute(stmt).all()
        return {CollectionRef(library=r.library_name, name=r.collection_name) for r in rows}


def get_pinned_visibility_map() -> Dict[CollectionRef, Dict[str, bool]]:
    with session_scope() as db:
        stmt = select(PinnedCollection)
        rows = db.execute(stmt).scalars().all()
        return {
            CollectionRef(library=p.library_name, name=p.collection_name): {
                "home": p.visibility_home,
                "shared": p.visibility_shared,
                "recommended": p.visibility_recommended,
            }
            for p in rows
        }


def is_collection_pinned(ref: CollectionRef) -> bool:
    with session_scope() as db:
        stmt = select(PinnedCollection).where(
            and_(
                PinnedCollection.library_name == ref.library,
                PinnedCollection.collection_name == ref.name,
            )
        )
        return db.execute(stmt).scalar_one_or_none() is not None


def pin_collection(
    ref: CollectionRef,
    display_order: Optional[int] = None,
    visibility_home: bool = True,
    visibility_shared: bool = False,
    visibility_recommended: bool = False,
    pin_position: Optional[str] = None,
    rating_key: Optional[int] = None,
) -> PinnedCollection:
    # Pin a collection. If already pinned, update order/visibility/position.
    # pin_position=None means "don't change" on update, defaults to "top" on create.
    # rating_key=None means "don't change" on update; storing it lets the pin
    # survive a later rename (see reconcile_pinned_collection_identities).
    with session_scope() as db:
        stmt = select(PinnedCollection).where(
            and_(
                PinnedCollection.library_name == ref.library,
                PinnedCollection.collection_name == ref.name,
            )
        )
        existing = db.execute(stmt).scalar_one_or_none()

        if existing is not None:
            if display_order is not None:
                existing.display_order = display_order
            existing.visibility_home = visibility_home
            existing.visibility_shared = visibility_shared
            existing.visibility_recommended = visibility_recommended
            if pin_position is not None:
                existing.pin_position = pin_position
            if rating_key is not None:
                existing.rating_key = rating_key
            logger.info("Updated pin for %s (home=%s, shared=%s, recommended=%s, position=%s)",
                        ref, visibility_home, visibility_shared, visibility_recommended, existing.pin_position)
            return existing

        if display_order is None:
            max_order_stmt = select(func.max(PinnedCollection.display_order))
            max_order = db.execute(max_order_stmt).scalar()
            display_order = (max_order or 0) + 1

        pinned = PinnedCollection(
            collection_name=ref.name,
            library_name=ref.library,
            rating_key=rating_key,
            display_order=display_order,
            pinned_at=datetime.utcnow(),
            pin_position=pin_position or "top",
            visibility_home=visibility_home,
            visibility_shared=visibility_shared,
            visibility_recommended=visibility_recommended,
        )
        db.add(pinned)
        logger.info("Pinned %s (order=%d, position=%s, home=%s, shared=%s, recommended=%s)",
                    ref, display_order, pinned.pin_position, visibility_home, visibility_shared, visibility_recommended)
        return pinned


def get_pinned_position_map() -> Dict[CollectionRef, str]:
    with session_scope() as db:
        rows = db.execute(select(PinnedCollection)).scalars().all()
        return {
            CollectionRef(library=p.library_name, name=p.collection_name): p.pin_position
            for p in rows
        }


def unpin_collection(ref: CollectionRef) -> bool:
    with session_scope() as db:
        stmt = select(PinnedCollection).where(
            and_(
                PinnedCollection.library_name == ref.library,
                PinnedCollection.collection_name == ref.name,
            )
        )
        existing = db.execute(stmt).scalar_one_or_none()
        if existing is None:
            return False
        db.delete(existing)
        logger.info("Unpinned %s", ref)
        return True


def set_pin_rating_key(ref: CollectionRef, rating_key: int) -> bool:
    # Store the ratingKey on an existing pin (identified by current name). No-op
    # if the pin doesn't exist. Used by the toggle-pin endpoint to record the
    # collection's identity at pin time.
    with session_scope() as db:
        stmt = select(PinnedCollection).where(
            and_(
                PinnedCollection.library_name == ref.library,
                PinnedCollection.collection_name == ref.name,
            )
        )
        pinned = db.execute(stmt).scalar_one_or_none()
        if pinned is None:
            return False
        pinned.rating_key = rating_key
        return True


def reconcile_pinned_collection_identities(
    live_by_library: Dict[str, List[tuple]],
) -> List[str]:
    # Keep pins bound to their collection across renames using the stable
    # ratingKey. `live_by_library` maps library_name -> list of (rating_key,
    # name) for every collection currently in that library.
    #
    # For each pin:
    #   - rating_key set + found live under a different name → rename the pin to
    #     the live name (self-heal), unless another pin in the library already
    #     holds that name (collision → skip, logged).
    #   - rating_key not set + name matches a live collection → backfill the
    #     ratingKey so future renames are survivable.
    #   - otherwise → orphaned (collection deleted, or renamed before we ever
    #     stored its ratingKey); logged, left untouched for the user to resolve.
    #
    # Returns a list of human-readable change descriptions (empty if no change).
    changes: List[str] = []
    with session_scope() as db:
        pins = db.execute(select(PinnedCollection)).scalars().all()
        pins_by_lib: Dict[str, List[PinnedCollection]] = {}
        for p in pins:
            pins_by_lib.setdefault(p.library_name, []).append(p)

        for lib, lib_pins in pins_by_lib.items():
            live = live_by_library.get(lib) or []
            name_by_key = {int(rk): nm for rk, nm in live if rk is not None}
            key_by_name = {nm: int(rk) for rk, nm in live if rk is not None}
            names_in_use = {p.collection_name for p in lib_pins}

            for p in lib_pins:
                if p.rating_key is not None:
                    live_name = name_by_key.get(int(p.rating_key))
                    if live_name is None:
                        logger.warning(
                            "Pinned collection '%s' (lib=%s, ratingKey=%s) not found "
                            "in Plex — collection may have been deleted",
                            p.collection_name, lib, p.rating_key,
                        )
                        continue
                    if live_name != p.collection_name:
                        if live_name in names_in_use:
                            logger.warning(
                                "Pin rename skipped: '%s' (lib=%s, ratingKey=%s) is now "
                                "named '%s' but a pin with that name already exists",
                                p.collection_name, lib, p.rating_key, live_name,
                            )
                            continue
                        names_in_use.discard(p.collection_name)
                        names_in_use.add(live_name)
                        msg = (
                            f"Re-bound pin (lib={lib}, ratingKey={p.rating_key}): "
                            f"'{p.collection_name}' → '{live_name}'"
                        )
                        p.collection_name = live_name
                        changes.append(msg)
                        logger.info(msg)
                else:
                    rk = key_by_name.get(p.collection_name)
                    if rk is not None:
                        p.rating_key = rk
                        msg = (
                            f"Backfilled ratingKey {rk} for pin "
                            f"'{p.collection_name}' (lib={lib})"
                        )
                        changes.append(msg)
                        logger.info(msg)
                    else:
                        logger.warning(
                            "Pinned collection '%s' (lib=%s) has no ratingKey and no "
                            "live collection by that name — orphaned pin",
                            p.collection_name, lib,
                        )
    return changes


def get_display_order() -> Dict[CollectionRef, int]:
    with session_scope() as db:
        result: Dict[CollectionRef, int] = {}

        pinned_stmt = select(PinnedCollection).order_by(PinnedCollection.display_order.asc())
        for row in db.execute(pinned_stmt).scalars().all():
            ref = CollectionRef(library=row.library_name, name=row.collection_name)
            result[ref] = row.display_order

        order_stmt = select(CollectionDisplayOrder).order_by(CollectionDisplayOrder.display_order.asc())
        for row in db.execute(order_stmt).scalars().all():
            ref = CollectionRef(library=row.library_name, name=row.collection_name)
            if ref not in result:
                result[ref] = row.display_order + 10000

        return result


def update_display_order(ordered_refs: List[CollectionRef]) -> None:
    with session_scope() as db:
        now = datetime.utcnow()
        pinned_order = 0

        for idx, ref in enumerate(ordered_refs):
            pinned_stmt = select(PinnedCollection).where(
                and_(
                    PinnedCollection.library_name == ref.library,
                    PinnedCollection.collection_name == ref.name,
                )
            )
            pinned = db.execute(pinned_stmt).scalar_one_or_none()
            if pinned is not None:
                pinned.display_order = pinned_order
                pinned_order += 1

            stmt = select(CollectionDisplayOrder).where(
                and_(
                    CollectionDisplayOrder.library_name == ref.library,
                    CollectionDisplayOrder.collection_name == ref.name,
                )
            )
            existing = db.execute(stmt).scalar_one_or_none()
            if existing is not None:
                existing.display_order = idx
                existing.updated_at = now
            else:
                db.add(CollectionDisplayOrder(
                    library_name=ref.library,
                    collection_name=ref.name,
                    display_order=idx,
                    updated_at=now,
                ))

        logger.info("Updated display order for %d collections", len(ordered_refs))
