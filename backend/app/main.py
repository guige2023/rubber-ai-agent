import asyncio
import logging
import os
import signal
from contextlib import asynccontextmanager
from logging.config import dictConfig
from typing import Optional

from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI

from app.core.config import get_settings
from app.core.runtime import RabAiAgentRuntime
from app.rpc.registry import register_rpc_methods
from app.rpc.sessions import reconcile_stale_pending_runs_on_startup
from app.rpc.websocket import register_websocket
from app.rpc.health import router as health_router

# P1-SEC-3: Patch logging config to inject redaction
from app.core.security.log_redactor import patch_dict_config_logging

logger = logging.getLogger(__name__)

# Global shutdown event for coordinating graceful shutdown
_shutdown_event: asyncio.Event | None = None
_reload_event: asyncio.Event | None = None


def configure_logging(log_level: Optional[str] = None) -> None:
    settings = get_settings()
    log_level = (log_level or settings.log_level).upper()
    log_dir = settings.log_dir
    log_file = log_dir / "rabaiagent.log"

    os.makedirs(log_dir, exist_ok=True)

    dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "correlation_id": {
                "()": "asgi_correlation_id.CorrelationIdFilter",
                "uuid_length": 32,
                "default_value": "-",
            },
        },
        "formatters": {
            "json": {
                "()": "pythonjsonlogger.orjson.OrjsonFormatter",
                "format": "%(asctime)s %(levelname)s %(name)s %(module)s %(funcName)s:%(lineno)d [%(correlation_id)s] %(message)s",
                "rename_fields": {"levelname": "severity", "asctime": "timestamp"},
            },
            "standard": {
                "format": "%(asctime)s [%(levelname)s] %(name)s [%(correlation_id)s]: %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "filters": ["correlation_id"],
                "formatter": "json",
            },
            "file": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "filename": str(log_file),
                "when": "D",
                "interval": 1,
                "backupCount": 3,
                "filters": ["correlation_id"],
                "formatter": "json",
                "encoding": "utf-8",
            },
        },
        "loggers": {
            "": {
                "handlers": ["console", "file"],
                "level": log_level,
            },
            "httpx": {
                "level": "WARNING",
                "handlers": ["console", "file"],
                "propagate": False,
            },
            "httpcore": {
                "level": "WARNING",
                "handlers": ["console", "file"],
                "propagate": False,
            },
            "trafilatura": {
                "level": "WARNING",
                "handlers": ["console", "file"],
                "propagate": False,
            },
            "pydantic_ai": {
                "level": log_level,
                "handlers": ["console", "file"],
                "propagate": False,
            },
        },
    })


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    global _shutdown_event, _reload_event

    configure_logging()
    logger.info("🚀 RabAiAgent Sidecar starting...")

    # Initialize shutdown and reload events
    _shutdown_event = asyncio.Event()
    _reload_event = asyncio.Event()

    # Set up signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda s=sig: _handle_shutdown_signal(s, fastapi_app)
        )
    loop.add_signal_handler(
        signal.SIGHUP,
        lambda: _handle_hup_signal(fastapi_app)
    )

    # Require bearer token - no default fallback
    bearer_token = os.environ.get("RABAIAGENT_BEARER_TOKEN")
    if not bearer_token:
        logger.error("RABAIAGENT_BEARER_TOKEN environment variable is required")
        raise RuntimeError("RABAIAGENT_BEARER_TOKEN must be set")
    fastapi_app.state.bearer_token = bearer_token

    fastapi_app.state.runtime = RabAiAgentRuntime(get_settings())

    # Initialize Gateway
    await _setup_gateway(fastapi_app)

    # Recover gateway sessions from SQLite
    gateway_router = getattr(fastapi_app.state, "gateway_router", None)
    if gateway_router and hasattr(gateway_router, "recover_sessions"):
        try:
            recovered = await gateway_router.recover_sessions()
            logger.info(f"Gateway session recovery complete: {len(recovered)} sessions recovered")
        except Exception as e:
            logger.error(f"Failed to recover gateway sessions: {e}")

    reconcile_stale_pending_runs_on_startup()
    fastapi_app.state.runtime.skill_manager.scan_skills()
    fastapi_app.state.schedule_manager = fastapi_app.state.runtime.schedule_manager
    await fastapi_app.state.runtime.model_pricing_service.start()
    await fastapi_app.state.schedule_manager.start()
    await fastapi_app.state.runtime.trigger_manager.sync_all()

    # Start HeartbeatRunner, EvolutionManager, MemoryManager
    await fastapi_app.state.runtime.start()

    yield

    # Graceful shutdown
    logger.info("Initiating graceful shutdown...")
    await _shutdown_gateway(fastapi_app)
    await fastapi_app.state.schedule_manager.shutdown()
    await fastapi_app.state.runtime.model_pricing_service.shutdown()
    await fastapi_app.state.runtime.browser_manager.shutdown()
    # Shutdown runtime systems (heartbeat, evolution, memory)
    await fastapi_app.state.runtime.shutdown()
    logger.info("🛑 RabAiAgent Sidecar shutting down...")


def _handle_shutdown_signal(sig: signal.Signals, fastapi_app: FastAPI) -> None:
    """Handle SIGTERM/SIGINT for graceful shutdown."""
    sig_name = sig.name
    logger.info(f"Received {sig_name}, initiating graceful shutdown...")

    # Set shutdown flag on runtime for in-flight request drainage
    runtime = getattr(fastapi_app.state, "runtime", None)
    if runtime:
        runtime._shutdown_requested = True

    if _shutdown_event:
        _shutdown_event.set()


def _handle_hup_signal(fastapi_app: FastAPI) -> None:
    """Handle SIGHUP for configuration reload."""
    logger.info("Received SIGHUP, reloading configuration...")

    # Clear cached settings to force reload
    from app.core.config import get_settings
    settings = get_settings()
    if hasattr(settings, 'cache_clear'):
        settings.cache_clear()

    # Trigger configuration reload
    try:
        # Reload environment variables
        from app.core.config import Settings
        new_settings = Settings(_env_file=os.environ.get("ENV_FILE", ".env"))
        logger.info("Configuration reloaded successfully")
    except Exception as e:
        logger.error(f"Failed to reload configuration: {e}")

    if _reload_event:
        _reload_event.set()


async def _setup_gateway(fastapi_app: FastAPI) -> None:
    """Initialize the Gateway with platform adapters."""
    from app.gateway import get_router, get_registry
    from app.gateway.platforms import FeishuAdapter

    router = get_router()
    registry = get_registry()

    # Set up agent handler
    router.set_agent_handler(_create_gateway_agent_handler(fastapi_app))

    # Register Feishu if configured
    feishu_app_id = os.environ.get("FEISHU_APP_ID")
    feishu_app_secret = os.environ.get("FEISHU_APP_SECRET")
    if feishu_app_id and feishu_app_secret:
        feishu_adapter = FeishuAdapter(
            app_id=feishu_app_id,
            app_secret=feishu_app_secret,
        )
        registry.register(feishu_adapter)
        logger.info("Feishu adapter registered")
    else:
        logger.info("Feishu not configured (FEISHU_APP_ID/FEISHU_APP_SECRET not set)")

    # Connect all registered adapters
    await registry.connect_all()

    # Store in app state
    fastapi_app.state.gateway_router = router
    fastapi_app.state.gateway_registry = registry


async def _shutdown_gateway(fastapi_app: FastAPI) -> None:
    """Shutdown the Gateway."""
    registry = getattr(fastapi_app.state, "gateway_registry", None)
    if registry:
        await registry.disconnect_all()


async def _create_gateway_agent_handler(fastapi_app: FastAPI):
    """
    Create the agent handler for the Gateway.

    This bridges the Gateway to the RabAiAgent runtime's agent system.
    P0-API-3: Real implementation that runs messages through the agent pipeline.
    """
    from app.gateway import GatewayRouter, AgentResponse, SessionContext
    import uuid
    import logging

    logger = logging.getLogger(__name__)

    async def handle(session_ctx: SessionContext) -> AgentResponse:
        runtime = fastapi_app.state.runtime
        content = session_ctx.content or ""
        session_key = session_ctx.session_key

        if not content:
            return AgentResponse(
                session_key=session_key,
                content="No content provided.",
            )

        try:
            # Map platform session_key to a RabAi session_id
            # Use the session_key as the session_id (shortuuid format)
            import hashlib
            session_id = hashlib.sha256(session_key.encode()).hexdigest()[:22]

            # Ensure the session exists in session_manager
            runtime.session_manager.ensure_session(
                session_id=session_id,
                metadata={
                    "platform": session_ctx.platform,
                    "session_key": session_key,
                },
            )

            # Generate a unique run_id
            run_id = str(uuid.uuid4())

            # Create agent deps
            deps = runtime.create_agent_deps(
                session_id=session_id,
                run_id=run_id,
            )

            # Run the master agent (this is the real agent pipeline)
            result = await runtime.agent_manager.run_master_agent(
                instruction=content,
                session_id=session_id,
                run_id=run_id,
                deps=deps,
            )

            # Extract text response from result
            response_content = ""
            if isinstance(result, dict):
                response_content = result.get("content", "")
                if isinstance(response_content, list):
                    # Handle result parts
                    parts_text = []
                    for part in response_content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            parts_text.append(part.get("content", ""))
                    response_content = "\n".join(parts_text)
                elif not isinstance(response_content, str):
                    response_content = str(response_content)
            elif isinstance(result, str):
                response_content = result

            if not response_content:
                response_content = "Agent completed without output."

            logger.info({
                "message": {
                    "event": "gateway_agent_run",
                    "session_key": session_key,
                    "session_id": session_id,
                    "response_length": len(response_content),
                }
            })

            return AgentResponse(
                session_key=session_key,
                content=response_content,
            )

        except Exception as e:
            logger.exception(f"Gateway agent error for {session_key}: {e}")
            return AgentResponse(
                session_key=session_key,
                content=f"Error processing request: {str(e)}",
            )

    return handle


register_rpc_methods()

app = FastAPI(title="RabAiAgent Sidecar", version="1.0.0", lifespan=lifespan)
app.add_middleware(CorrelationIdMiddleware, update_request_header=True)  # type:ignore
register_websocket(app)

# P1-DEVOPS-2 + P1-MON-1: Health check endpoints (no /api/v1 prefix for k8s probes)
app.include_router(health_router)

# Register REST API routers under /api/v1 prefix (P0-API-1)
from fastapi import APIRouter

# Feishu REST endpoints
from app.rpc.feishu import router as feishu_router
feishu_v1_router = APIRouter(prefix="/api/v1")
feishu_v1_router.include_router(feishu_router)
app.include_router(feishu_v1_router)

# Trigger REST endpoints
from app.rpc.trigger import router as trigger_router, webhook_router as trigger_webhook_router
trigger_v1_router = APIRouter(prefix="/api/v1")
trigger_v1_router.include_router(trigger_router)
trigger_v1_router.include_router(trigger_webhook_router)
app.include_router(trigger_v1_router)

# Legacy routes (without /api/v1 prefix) — DEPRECATED, mapped for backwards compat
# These will be removed in a future version
app.include_router(feishu_router)  # /feishu/* (no /api/v1)
app.include_router(trigger_router)  # /triggers/* (no /api/v1)
app.include_router(trigger_webhook_router)  # /webhooks/* (no /api/v1)

# P1-SEC-3: Inject log redaction into existing handlers (after all routers registered)
try:
    patch_dict_config_logging()
except Exception:
    pass  # Non-fatal, logging may not be configured yet


if __name__ == "__main__":
    from app.sidecar import main

    main()
