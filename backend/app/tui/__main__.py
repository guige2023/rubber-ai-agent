"""
TUI entry point - run with: python -m app.tui
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os

from app.tui.app import run_tui


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RabAi Agent TUI")
    parser.add_argument(
        "--gateway",
        default=os.environ.get("FERRYMAN_WS_URL", "ws://127.0.0.1:8000/ws"),
        help="Gateway WebSocket URL (default: ws://127.0.0.1:8000/ws)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("FERRYMAN_BEARER_TOKEN", "dev-token"),
        help="Bearer token for authentication",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Run the TUI
    asyncio.run(run_tui(gateway_url=args.gateway, token=args.token))


if __name__ == "__main__":
    main()
