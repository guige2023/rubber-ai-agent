from __future__ import annotations

import argparse
import os
import sys


def configure_release_runtime() -> None:
    is_frozen = getattr(sys, "frozen", False)
    if not is_frozen:
        return

    # Release sidecars should not load ambient Pydantic plugins such as Logfire.
    os.environ.setdefault("PYDANTIC_DISABLE_PLUGINS", "1")


configure_release_runtime()

import uvicorn

from app.core.config import get_settings
from app.main import app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ferryman backend sidecar")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind")
    parser.add_argument("--port", type=int, default=None, help="Port to bind")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    settings = get_settings()
    uvicorn.run(
        app,
        host=args.host,
        port=args.port or settings.port,
    )


if __name__ == "__main__":
    main()
