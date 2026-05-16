"""
P0-DB-2: Formal Migration System

Replaces auto_migrate with a proper versioned migration system.
Migrations are numbered SQL scripts that run exactly once and are tracked
in the app_configs table.

Migration directory structure:
    backend/migrations/
        0001_add_fk_constraints.sql
        0002_add_composite_indexes.sql
        ...

Each migration file contains:
- A descriptive filename with the migration number and name
- Up migration (applied when running forward)
- Down migration (applied when rolling back) — optional but recommended

The runner tracks applied migrations in app_configs.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlmodel import SQLModel

from app.core.db import engine

logger = logging.getLogger(__name__)

# Key used to track applied migrations in app_configs
MIGRATIONS_KEY = "system.db.migrations"
MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"


def _get_applied_migrations() -> set[str]:
    """Read the set of already-applied migration IDs from app_configs."""
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT value FROM app_configs WHERE `key` = :key"),
                {"key": MIGRATIONS_KEY},
            ).first()
            if row:
                import json
                return set(json.loads(row[0]))
    except Exception:
        pass
    return set()


def _save_applied_migrations(migration_ids: set[str]) -> None:
    """Persist the set of applied migration IDs to app_configs."""
    import json
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ")
    with engine.connect() as conn:
        conn.execute(
            text(
                """
                INSERT OR REPLACE INTO app_configs (`key`, value, category, metadata, updated_at)
                VALUES (:key, :value, :category, :metadata, :updated_at)
                """
            ),
            {
                "key": MIGRATIONS_KEY,
                "value": json.dumps(sorted(migration_ids)),
                "category": "system",
                "metadata": json.dumps({"description": "Applied DB migrations"}),
                "updated_at": now,
            },
        )
        conn.commit()


def _parse_migration_filename(filename: str) -> tuple[int, str]:
    """Parse migration number and name from filename like '0001_add_fk_constraints.sql'."""
    m = re.match(r"^(\d+)_([a-z0-9_]+)\.sql$", filename)
    if not m:
        return (-1, "")
    return int(m.group(1)), m.group(2)


def _read_migration_sql(filepath: Path) -> str:
    """Read migration file, stripping -- comments and splitting on statement-breakpoint."""
    content = filepath.read_text(encoding="utf-8")
    lines = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") or not stripped:
            continue
        lines.append(line)
    return "\n".join(lines)


def run_migrations() -> None:
    """
    Discover and run all unapplied migrations in order.

    Each migration runs exactly once. After running, its ID is saved to
    app_configs so it won't run again on future startups.
    """
    if not MIGRATIONS_DIR.exists():
        logger.info(f"Migrations directory not found: {MIGRATIONS_DIR}")
        return

    # Collect all migration files
    migrations: dict[int, Path] = {}
    for fname in os.listdir(MIGRATIONS_DIR):
        num, name = _parse_migration_filename(fname)
        if num > 0:
            migrations[num] = MIGRATIONS_DIR / fname

    if not migrations:
        logger.info("No migration files found")
        return

    applied = _get_applied_migrations()
    to_apply = sorted(n for n in migrations if str(n) not in applied)

    if not to_apply:
        logger.info(f"All migrations up to date (latest: {max(migrations.keys())})")
        return

    logger.info(f"Running {len(to_apply)} migration(s): {to_apply}")

    for num in to_apply:
        filepath = migrations[num]
        sql = _read_migration_sql(filepath)
        migration_id = str(num)

        logger.info(f"Applying migration {num}: {filepath.name}")
        try:
            with engine.connect() as conn:
                # SQLite doesn't support semicolon-separated multi-statement in a single
                # execute() cleanly, so split on semicolons and execute one by one.
                for stmt in sql.split(";"):
                    stmt = stmt.strip()
                    if not stmt:
                        continue
                    conn.execute(text(stmt))
                conn.commit()
        except Exception as e:
            logger.error(f"Migration {num} failed: {e}")
            raise

        # Mark as applied
        applied.add(migration_id)
        _save_applied_migrations(applied)
        logger.info(f"Migration {num} applied successfully")

    logger.info(f"Migrations complete. Applied: {sorted(int(x) for x in applied)}")


def rollback_migration(n: int) -> None:
    """
    Roll back a specific migration by number.

    This reads the migration file and executes the -- rollback: section.
    For safety, rollbacks are manual and must be explicitly called.
    """
    applied = _get_applied_migrations()
    migration_id = str(n)

    if migration_id not in applied:
        raise ValueError(f"Migration {n} is not applied")

    migrations: dict[int, Path] = {}
    for fname in os.listdir(MIGRATIONS_DIR):
        num, name = _parse_migration_filename(fname)
        if num > 0:
            migrations[num] = MIGRATIONS_DIR / fname

    if n not in migrations:
        raise ValueError(f"Migration {n} file not found")

    filepath = migrations[n]
    content = filepath.read_text(encoding="utf-8")

    # Extract rollback section
    rollback_lines = []
    in_rollback = False
    for line in content.splitlines():
        if line.strip().startswith("-- rollback:"):
            in_rollback = True
            continue
        if in_rollback:
            if line.strip().startswith("--") and not line.strip().startswith("-- "):
                break
            rollback_lines.append(line)

    if not rollback_lines:
        raise ValueError(f"No rollback section found in migration {n}")

    rollback_sql = "\n".join(rollback_lines).strip()
    logger.info(f"Rolling back migration {n}")
    try:
        with engine.connect() as conn:
            for stmt in rollback_sql.split(";"):
                stmt = stmt.strip()
                if not stmt:
                    continue
                conn.execute(text(stmt))
            conn.commit()
    except Exception as e:
        logger.error(f"Rollback of migration {n} failed: {e}")
        raise

    applied.discard(migration_id)
    _save_applied_migrations(applied)
    logger.info(f"Migration {n} rolled back successfully")
