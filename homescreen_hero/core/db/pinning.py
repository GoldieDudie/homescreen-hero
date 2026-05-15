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
) -> PinnedCollection:
    # Pin a collection. If already pinned, update the order/visibility.
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
            logger.info("Updated pin for %s (home=%s, shared=%s, recommended=%s)",
                        ref, visibility_home, visibility_shared, visibility_recommended)
            return existing

        if display_order is None:
            max_order_stmt = select(func.max(PinnedCollection.display_order))
            max_order = db.execute(max_order_stmt).scalar()
            display_order = (max_order or 0) + 1

        pinned = PinnedCollection(
            collection_name=ref.name,
            library_name=ref.library,
            display_order=display_order,
            pinned_at=datetime.utcnow(),
            visibility_home=visibility_home,
            visibility_shared=visibility_shared,
            visibility_recommended=visibility_recommended,
        )
        db.add(pinned)
        logger.info("Pinned %s (order=%d, home=%s, shared=%s, recommended=%s)",
                    ref, display_order, visibility_home, visibility_shared, visibility_recommended)
        return pinned


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
