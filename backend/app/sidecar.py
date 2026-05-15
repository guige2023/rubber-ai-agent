from __future__ import annotations

import argparse
import os
import runpy
import sys


def configure_release_runtime() -> None:
    is_frozen = getattr(sys, "frozen", False)
    if not is_frozen:
        return

    # Release sidecars should not load ambient Pydantic plugins such as Logfire.
    os.environ.setdefault("PYDANTIC_DISABLE_PLUGINS", "1")
    os.environ.setdefault("FERRYMAN_LOG_LEVEL", "INFO")


configure_release_runtime()

import uvicorn

from app.core.config import get_settings
from app.main import app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RabAiAgent backend sidecar")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind")
    parser.add_argument("--port", type=int, default=None, help="Port to bind")
    parser.add_argument("--smoke-test-bundle", action="store_true", help="Run bundled runtime smoke tests and exit")
    parser.add_argument(
        "--run-python-script",
        nargs=argparse.REMAINDER,
        help="Execute a bundled Python skill script within the frozen sidecar runtime.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.run_python_script:
        script_path, *script_args = args.run_python_script
        sys.argv = [script_path, *script_args]
        runpy.run_path(script_path, run_name="__main__")
        return
    if args.smoke_test_bundle:
        from app.release_smoke import main as smoke_main

        raise SystemExit(smoke_main())

    settings = get_settings()
    uvicorn.run(
        app,
        host=args.host,
        port=args.port or settings.port,
    )


if __name__ == "__main__":
    main()
