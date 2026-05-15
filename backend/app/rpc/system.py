from __future__ import annotations

import logging

from jsonrpcserver import Success, method

logger = logging.getLogger(__name__)


@method
async def ping(context):
    return Success("pong")


@method
async def status(context):
    """Get system status for TUI."""
    runtime = getattr(context, "runtime", None)
    if not runtime:
        return Success({
            "status": "error",
            "message": "Runtime not available",
        })

    # Gather status from various components
    status_info = {
        "status": "ok",
        "components": {},
    }

    # Heartbeat status
    if hasattr(runtime, "heartbeat_runner"):
        hb = runtime.heartbeat_runner
        status_info["components"]["heartbeat"] = {
            "running": getattr(hb, "_running", False),
        }

    # Evolution manager status
    if hasattr(runtime, "evolution_manager"):
        ev = runtime.evolution_manager
        status_info["components"]["evolution"] = {
            "running": getattr(ev, "_running", False) if hasattr(ev, "_running") else None,
        }

    # Memory manager status
    if hasattr(runtime, "memory_manager"):
        mm = runtime.memory_manager
        status_info["components"]["memory"] = {
            "running": getattr(mm, "_running", False) if hasattr(mm, "_running") else None,
        }

    # Session count
    if hasattr(runtime, "session_manager"):
        sm = runtime.session_manager
        status_info["components"]["sessions"] = {
            "active_count": len(getattr(sm, "_sessions", {})),
        }

    # Schedule manager status
    if hasattr(runtime, "schedule_manager"):
        sched = runtime.schedule_manager
        status_info["components"]["schedules"] = {
            "running": getattr(sched, "_running", False) if hasattr(sched, "_running") else None,
        }

    return Success(status_info)

