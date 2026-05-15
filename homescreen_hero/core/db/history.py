from __future__ import annotations

from datetime import datetime
import logging
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import func, select, and_
from sqlalchemy.orm import Session

from .base import get_engine, session_scope
from .models import RotationRecord, CollectionUsage
from ..config.schema import CollectionRef

logger = logging.getLogger(__name__)


def init_db() -> None:
    from . import Base

    engine = get_engine()
    logger.debug("Ensuring database schema is initialized")
    Base.metadata.create_all(bind=engine)

    # Auto-add any new columns defined in models but missing from existing tables
    _auto_migrate_columns(engine, Base)

    # Migrate name-only unique constraints to composite (library, name) ones
    _migrate_collection_identity_schema(engine)


def _auto_migrate_columns(engine, Base) -> None:
    # Compare SQLAlchemy model columns against actual DB and add any missing ones.
    # create_all() handles new tables; this handles new columns on existing tables.
    from sqlalchemy import text, inspect as sa_inspect

    inspector = sa_inspect(engine)
    existing_tables = set(inspector.get_table_names())

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue

        existing_cols = {col["name"] for col in inspector.get_columns(table.name)}

        for column in table.columns:
            if column.name in existing_cols:
                continue

            col_type = column.type.compile(dialect=engine.dialect)
            sql = f"ALTER TABLE {table.name} ADD COLUMN {column.name} {col_type}"

            # NOT NULL columns need a DEFAULT for SQLite ALTER TABLE
            if not column.nullable and column.default is not None:
                default_val = column.default.arg
                if not callable(default_val):
                    if isinstance(default_val, bool):
                        sql += f" NOT NULL DEFAULT {1 if default_val else 0}"
                    elif isinstance(default_val, str):
                        sql += f" NOT NULL DEFAULT '{default_val}'"
                    elif isinstance(default_val, (int, float)):
                        sql += f" NOT NULL DEFAULT {default_val}"

            logger.info("Auto-migrate: %s.%s (%s)", table.name, column.name, col_type)
            with engine.connect() as conn:
                conn.execute(text(sql))
                conn.commit()


def _migrate_collection_identity_schema(engine) -> None:
    # Migrate tables that had a name-only unique constraint to composite (library, name).
    # SQLite can't ALTER constraints, so we use the rename+recreate approach.
    # We detect the old schema by checking if the old name-only unique index exists.
    from sqlalchemy import inspect as sa_inspect, text

    inspector = sa_inspect(engine)
    existing_tables = set(inspector.get_table_names())

    migrations = [
        # (table_name, old_unique_index_names, recreate_sql, copy_sql)
        (
            "collection_usage",
            {"collection_name", "ix_collection_usage_collection_name", "uq_collection_usage_collection_name"},
            """CREATE TABLE collection_usage_new (
                id INTEGER PRIMARY KEY,
                library_name VARCHAR NOT NULL DEFAULT '',
                collection_name VARCHAR NOT NULL,
                last_rotation_id INTEGER,
                last_rotated_at DATETIME,
                times_used INTEGER NOT NULL DEFAULT 0,
                CONSTRAINT uq_collection_usage_lib_name UNIQUE (library_name, collection_name)
            )""",
            "INSERT OR IGNORE INTO collection_usage_new SELECT id, COALESCE(library_name, ''), collection_name, last_rotation_id, last_rotated_at, times_used FROM collection_usage",
        ),
        (
            "pinned_collections",
            {"collection_name", "ix_pinned_collections_collection_name", "uq_pinned_collections_collection_name"},
            """CREATE TABLE pinned_collections_new (
                id INTEGER PRIMARY KEY,
                collection_name VARCHAR NOT NULL,
                library_name VARCHAR NOT NULL,
                display_order INTEGER NOT NULL DEFAULT 0,
                pinned_at DATETIME NOT NULL,
                visibility_home BOOLEAN NOT NULL DEFAULT 1,
                visibility_shared BOOLEAN NOT NULL DEFAULT 0,
                visibility_recommended BOOLEAN NOT NULL DEFAULT 0,
                CONSTRAINT uq_pinned_collections_lib_name UNIQUE (library_name, collection_name)
            )""",
            "INSERT OR IGNORE INTO pinned_collections_new SELECT id, collection_name, library_name, display_order, pinned_at, visibility_home, visibility_shared, visibility_recommended FROM pinned_collections",
        ),
        (
            "collection_display_order",
            {"collection_name", "ix_collection_display_order_collection_name", "uq_collection_display_order_collection_name"},
            """CREATE TABLE collection_display_order_new (
                id INTEGER PRIMARY KEY,
                library_name VARCHAR NOT NULL DEFAULT '',
                collection_name VARCHAR NOT NULL,
                display_order INTEGER NOT NULL DEFAULT 0,
                updated_at DATETIME NOT NULL,
                CONSTRAINT uq_collection_display_order_lib_name UNIQUE (library_name, collection_name)
            )""",
            "INSERT OR IGNORE INTO collection_display_order_new SELECT id, COALESCE(library_name, ''), collection_name, display_order, updated_at FROM collection_display_order",
        ),
    ]

    for table_name, old_unique_names, recreate_sql, copy_sql in migrations:
        if table_name not in existing_tables:
            continue

        indexes = {idx["name"] for idx in inspector.get_indexes(table_name)}
        # Also check unique constraints by examining the CREATE TABLE statement
        # to catch inline UNIQUE constraints that don't appear as named indexes
        with engine.connect() as conn:
            row = conn.execute(text(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table_name}'")).fetchone()
            table_ddl = (row[0] or "").upper() if row else ""

        # Detect old schema: has name-only UNIQUE on collection_name but not a composite one
        has_old_unique = bool(indexes & old_unique_names) or (
            "UNIQUE" in table_ddl
            and "COLLECTION_NAME" in table_ddl
            and "LIBRARY_NAME" not in table_ddl.split("UNIQUE")[1][:50]
        )
        has_new_unique = any("LIB_NAME" in idx for idx in indexes)

        if not has_old_unique or has_new_unique:
            continue

        logger.info("Migrating %s to composite (library_name, collection_name) unique constraint", table_name)
        with engine.connect() as conn:
            conn.execute(text(recreate_sql))
            conn.execute(text(copy_sql))
            conn.execute(text(f"DROP TABLE {table_name}"))
            conn.execute(text(f"ALTER TABLE {table_name}_new RENAME TO {table_name}"))
            conn.commit()
        logger.info("Migration of %s complete", table_name)


def record_rotation(
    featured_collections: Iterable[CollectionRef],
    success: bool = True,
    error_message: Optional[str] = None,
    group_contributions: Optional[Dict[str, List[CollectionRef]]] = None,
) -> int:
    # Create a new RotationRecord and update CollectionUsage
    featured_list = list(featured_collections)
    # Store as {library, name} dicts for forward-compatibility; old records had bare strings
    featured_json = [{"library": r.library, "name": r.name} for r in featured_list]
    group_json = (
        {g: [{"library": r.library, "name": r.name} for r in refs] for g, refs in group_contributions.items()}
        if group_contributions else None
    )
    now = datetime.utcnow()

    with session_scope() as db:
        record = RotationRecord(
            success=success,
            error_message=error_message,
            featured_collections=featured_json,
            group_contributions=group_json,
        )
        db.add(record)
        db.flush()  # Ensure record.id is populated

        rotation_id = record.id

        logger.info(
            "Recording rotation %d: featured_collections=%s",
            rotation_id,
            [str(r) for r in featured_list],
        )

        for ref in featured_list:
            _update_collection_usage(db, ref, rotation_id, now)

        return rotation_id


def _update_collection_usage(
    db: Session,
    ref: CollectionRef,
    rotation_id: int,
    when: datetime,
) -> None:
    stmt = select(CollectionUsage).where(
        and_(
            CollectionUsage.library_name == ref.library,
            CollectionUsage.collection_name == ref.name,
        )
    )
    usage = db.execute(stmt).scalar_one_or_none()

    if usage is None:
        usage = CollectionUsage(
            library_name=ref.library,
            collection_name=ref.name,
            last_rotation_id=rotation_id,
            last_rotated_at=when,
            times_used=1,
        )
        db.add(usage)
    else:
        usage.last_rotation_id = rotation_id
        usage.last_rotated_at = when
        usage.times_used += 1


def get_rotation_history_context() -> Tuple[int, Dict[CollectionRef, CollectionUsage]]:
    # Returns:
    #   - max_rotation_id (0 if no rotations yet)
    #   - dict mapping CollectionRef -> CollectionUsage
    with session_scope() as db:
        max_id_stmt = select(func.max(RotationRecord.id))
        max_id = db.execute(max_id_stmt).scalar()
        if max_id is None:
            max_id = 0

        logger.debug("Loaded max rotation id: %d", max_id)

        usage_stmt = select(CollectionUsage)
        rows = db.execute(usage_stmt).scalars().all()

        usage_map: Dict[CollectionRef, CollectionUsage] = {
            CollectionRef(library=u.library_name, name=u.collection_name): u
            for u in rows
        }

        logger.debug("Loaded usage context for %d collections", len(usage_map))

        return max_id, usage_map


def get_recent_rotations(limit: int = 10) -> List[RotationRecord]:
    # Utility to inspect recent rotations
    with session_scope() as db:
        stmt = (
            select(RotationRecord)
            .order_by(RotationRecord.created_at.desc())
            .limit(limit)
        )
        rows = db.execute(stmt).scalars().all()
        return list(rows)


def get_last_rotation_collections() -> List[CollectionRef]:
    # Get the collections from the most recent rotation (for allow_repeats logic).
    # Handles both new {library, name} dicts and legacy bare-string records.
    with session_scope() as db:
        stmt = (
            select(RotationRecord)
            .order_by(RotationRecord.id.desc())
            .limit(1)
        )
        record = db.execute(stmt).scalar_one_or_none()
        if record is None:
            return []
        refs = []
        for item in record.featured_collections or []:
            if isinstance(item, dict):
                refs.append(CollectionRef(library=item.get("library", ""), name=item["name"]))
            else:
                # Legacy bare-string record — library unknown, use empty string
                refs.append(CollectionRef(library="", name=str(item)))
        return refs
