"""
Checkpoint persistence for orchestration plans.
Stores step execution snapshots to SQLite JSON columns.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .models import Checkpoint

logger = logging.getLogger(__name__)

_DB_PATH = Path.home() / ".rabai_orchestration.db"


def _get_db_path() -> Path:
    path = Path(__file__).parent / "orchestration.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _init_db(db_path: Optional[Path] = None) -> None:
    path = db_path or _get_db_path()
    with sqlite3.connect(str(path)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS checkpoints (
                plan_id TEXT NOT NULL,
                step_id TEXT NOT NULL,
                step_context TEXT NOT NULL DEFAULT '{}',
                plan_status TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                PRIMARY KEY (plan_id, step_id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_checkpoints_plan_id
            ON checkpoints(plan_id)
        """)
        conn.commit()


def _json_dumps(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, default=str)


class CheckpointStore:
    """
    Persists Checkpoint objects to SQLite.

    Uses WAL mode for safe concurrent access.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = db_path or _get_db_path()
        _init_db(self._db_path)

    def save(self, checkpoint: Checkpoint) -> None:
        """Save or overwrite a checkpoint."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO checkpoints
                    (plan_id, step_id, step_context, plan_status, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    checkpoint.plan_id,
                    checkpoint.step_id,
                    _json_dumps(checkpoint.step_context),
                    _json_dumps(checkpoint.plan_status),
                    checkpoint.created_at.isoformat(),
                ),
            )
            conn.commit()
        logger.debug(f"Checkpoint saved: plan={checkpoint.plan_id} step={checkpoint.step_id}")

    def load(self, plan_id: str, step_id: str) -> Optional[Checkpoint]:
        """Load a specific checkpoint."""
        with sqlite3.connect(str(self._db_path)) as conn:
            row = conn.execute(
                "SELECT plan_id, step_id, step_context, plan_status, created_at "
                "FROM checkpoints WHERE plan_id=? AND step_id=?",
                (plan_id, step_id),
            ).fetchone()
        if not row:
            return None
        return Checkpoint(
            plan_id=row[0],
            step_id=row[1],
            step_context=json.loads(row[2]),
            plan_status=json.loads(row[3]),
            created_at=datetime.fromisoformat(row[4]),
        )

    def load_latest(self, plan_id: str) -> Optional[Checkpoint]:
        """Load the latest checkpoint for a plan (highest created_at)."""
        with sqlite3.connect(str(self._db_path)) as conn:
            row = conn.execute(
                "SELECT plan_id, step_id, step_context, plan_status, created_at "
                "FROM checkpoints WHERE plan_id=? ORDER BY created_at DESC LIMIT 1",
                (plan_id,),
            ).fetchone()
        if not row:
            return None
        return Checkpoint(
            plan_id=row[0],
            step_id=row[1],
            step_context=json.loads(row[2]),
            plan_status=json.loads(row[3]),
            created_at=datetime.fromisoformat(row[4]),
        )

    def list_for_plan(self, plan_id: str) -> list[Checkpoint]:
        """List all checkpoints for a plan."""
        with sqlite3.connect(str(self._db_path)) as conn:
            rows = conn.execute(
                "SELECT plan_id, step_id, step_context, plan_status, created_at "
                "FROM checkpoints WHERE plan_id=? ORDER BY created_at ASC",
                (plan_id,),
            ).fetchall()
        return [
            Checkpoint(
                plan_id=r[0],
                step_id=r[1],
                step_context=json.loads(r[2]),
                plan_status=json.loads(r[3]),
                created_at=datetime.fromisoformat(r[4]),
            )
            for r in rows
        ]

    def delete_for_plan(self, plan_id: str) -> None:
        """Delete all checkpoints for a plan."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("DELETE FROM checkpoints WHERE plan_id=?", (plan_id,))
            conn.commit()
        logger.debug(f"Checkpoints deleted for plan={plan_id}")

    def save_snapshot(
        self,
        plan_id: str,
        step_id: str,
        step_context: dict[str, Any],
        plan_status: dict[str, str],
    ) -> None:
        """Convenience method to build and save a checkpoint."""
        checkpoint = Checkpoint(
            plan_id=plan_id,
            step_id=step_id,
            step_context=step_context,
            plan_status=plan_status,
            created_at=datetime.now(timezone.utc),
        )
        self.save(checkpoint)
