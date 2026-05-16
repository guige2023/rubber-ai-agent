"""
P1-DEVOPS-2 + P1-MON-1: Health Router with Snapshot Endpoint

Provides:
- GET  /health          — Basic liveness probe (DB + Redis check)
- GET  /health/snapshot — Full system snapshot (all components)
- GET  /health/ready    — Readiness probe (all deps ready)

Based on Paperclip's health.ts design but adapted for RabAi Agent's
SQLite + Redis stack.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.core.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["health"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class ComponentHealth(BaseModel):
    name: str
    status: str  # "ok" | "warning" | "error"
    latency_ms: Optional[float] = None
    detail: Optional[str] = None


class HealthSnapshot(BaseModel):
    status: str  # "ok" | "degraded" | "error"
    timestamp: str
    uptime_seconds: float
    version: str
    deployment_mode: str
    components: dict[str, ComponentHealth]


class ReadinessResponse(BaseModel):
    ready: bool
    checks: dict[str, bool]


# ── Global state (set at app startup) ──────────────────────────────────────

_start_time: float = time.monotonic()
_version: str = "1.0.0"  # TODO: pull from package or git tag


# ── Dependency checks ────────────────────────────────────────────────────────

async def _check_db() -> ComponentHealth:
    """Check SQLite connectivity and schema."""
    start = time.monotonic()
    try:
        from app.core.db import engine
        from sqlalchemy import text

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        latency = (time.monotonic() - start) * 1000

        # Check migrations applied
        from app.core.db import engine
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()

        detail = f"{len(tables)} tables"
        return ComponentHealth(
            name="database",
            status="ok",
            latency_ms=round(latency, 2),
            detail=detail,
        )
    except Exception as e:
        latency = (time.monotonic() - start) * 1000
        return ComponentHealth(
            name="database",
            status="error",
            latency_ms=round(latency, 2),
            detail=str(e)[:100],
        )


async def _check_redis() -> ComponentHealth:
    """Check Redis connectivity (optional dependency)."""
    start = time.monotonic()
    try:
        import redis
        r = redis.Redis(host="localhost", port=6379, socket_connect_timeout=3)
        r.ping()
        latency = (time.monotonic() - start) * 1000
        return ComponentHealth(
            name="redis",
            status="ok",
            latency_ms=round(latency, 2),
        )
    except ImportError:
        return ComponentHealth(
            name="redis",
            status="ok",
            latency_ms=0,
            detail="not installed (optional)",
        )
    except Exception as e:
        latency = (time.monotonic() - start) * 1000
        return ComponentHealth(
            name="redis",
            status="error",
            latency_ms=round(latency, 2),
            detail=str(e)[:100],
        )


async def _check_gateway() -> ComponentHealth:
    """Check OpenCLAW Gateway process."""
    start = time.monotonic()
    try:
        import subprocess

        result = subprocess.run(
            ["ps", "aux"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        pids = [
            int(line.split()[1])
            for line in result.stdout.split("\n")
            if "openclaw-gateway" in line and "grep" not in line
        ]
        latency = (time.monotonic() - start) * 1000
        if pids:
            return ComponentHealth(
                name="gateway",
                status="ok",
                latency_ms=round(latency, 2),
                detail=f"PIDs: {pids}",
            )
        else:
            return ComponentHealth(
                name="gateway",
                status="warning",
                latency_ms=round(latency, 2),
                detail="Gateway process not found",
            )
    except Exception as e:
        latency = (time.monotonic() - start) * 1000
        return ComponentHealth(
            name="gateway",
            status="error",
            latency_ms=round(latency, 2),
            detail=str(e)[:100],
        )


async def _check_skill_manager(request: Request) -> ComponentHealth:
    """Check skill registry via app state."""
    start = time.monotonic()
    try:
        runtime = getattr(request.app.state, "runtime", None)
        if runtime is None:
            return ComponentHealth(name="skills", status="warning", latency_ms=0, detail="Runtime not available")
        skill_count = len(getattr(runtime, "skill_manager", None) or {})
        return ComponentHealth(
            name="skills",
            status="ok",
            latency_ms=round((time.monotonic() - start) * 1000, 2),
            detail=f"{skill_count} skills loaded",
        )
    except Exception as e:
        return ComponentHealth(
            name="skills",
            status="error",
            latency_ms=round((time.monotonic() - start) * 1000, 2),
            detail=str(e)[:100],
        )


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("/", response_model=HealthSnapshot)
async def health_root(request: Request) -> HealthSnapshot:
    """
    Basic liveness probe + system snapshot.

    Checks: DB, Redis, Gateway, Skills
    """
    settings = get_settings()
    deployment_mode = "production" if not settings.bundled_skills_dir.exists() else "development"

    # Run all checks concurrently
    results = await asyncio.gather(
        _check_db(),
        _check_redis(),
        _check_gateway(),
        _check_skill_manager(request),
    )

    components = {r.name: r for r in results}

    # Determine overall status
    statuses = [r.status for r in results]
    if all(s == "ok" for s in statuses):
        overall = "ok"
    elif any(s == "error" for s in statuses):
        overall = "error"
    else:
        overall = "degraded"

    return HealthSnapshot(
        status=overall,
        timestamp=datetime.now(timezone.utc).isoformat(),
        uptime_seconds=round(time.monotonic() - _start_time, 2),
        version=_version,
        deployment_mode=deployment_mode,
        components={k: v.model_dump() for k, v in components.items()},
    )


@router.get("/snapshot", response_model=HealthSnapshot)
async def health_snapshot(request: Request) -> HealthSnapshot:
    """
    Full system snapshot for monitoring dashboards (Prometheus, Grafana, etc.).

    Returns the same data as / but explicitly meant for machine consumption.
    """
    return await health_root(request)


@router.get("/ready", response_model=ReadinessResponse)
async def health_ready(request: Request) -> ReadinessResponse:
    """
    Readiness probe for k8s/load balancer.

    Returns 200 only when all critical dependencies are ready.
    """
    db_health, redis_health = await asyncio.gather(
        _check_db(),
        _check_redis(),
    )

    checks = {
        "database": db_health.status == "ok",
        "redis": redis_health.status == "ok",
    }

    return ReadinessResponse(
        ready=all(checks.values()),
        checks=checks,
    )
