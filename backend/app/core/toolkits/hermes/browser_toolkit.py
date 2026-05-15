"""
Browser Toolkit - Hermes-style browser automation using agent-browser CLI.

Provides:
- Browser automation via agent-browser (no local Chrome needed!)
- Computer use (macOS desktop control via CUA driver)
- Web scraping and content extraction

Requires:
- agent-browser CLI: npm install -g agent-browser && agent-browser install
- cua-driver for computer use: (see installation in cua_backend)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from app.core.deps import AgentDeps
from app.core.toolkits.base import Toolkit

logger = logging.getLogger(__name__)


# Standard PATH for agent-browser discovery
_SANE_PATH_DIRS = (
    "/opt/homebrew/bin",
    "/opt/homebrew/sbin",
    "/usr/local/sbin",
    "/usr/local/bin",
    "/usr/sbin",
    "/usr/bin",
    "/sbin",
    "/bin",
)


def _merge_browser_path(existing_path: str = "") -> str:
    """Prepend browser-specific PATH fallbacks."""
    path_parts = [p for p in (existing_path or "").split(os.pathsep) if p]
    existing_parts = set(path_parts)
    prefix_parts = []

    for part in _SANE_PATH_DIRS:
        if part and part not in existing_parts and part not in prefix_parts:
            if os.path.isdir(part):
                prefix_parts.append(part)

    return os.pathsep.join(prefix_parts + path_parts)


@dataclass
class BrowserConfig:
    """Browser/Computer use configuration."""

    # agent-browser CLI path
    agent_browser_path: Optional[str] = None

    # Computer use (CUA driver)
    computer_use_backend: str = "cua-driver"
    cua_driver_path: Optional[str] = None

    # Session settings
    session_timeout: int = 300


def _is_agent_browser_available() -> bool:
    """Check if agent-browser CLI is available."""
    try:
        result = subprocess.run(
            ["agent-browser", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            env={**os.environ, "PATH": _merge_browser_path()},
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def _agent_browser_install_hint() -> str:
    return "npm install -g agent-browser && agent-browser install"


class BrowserToolkit(Toolkit):
    """
    Browser automation toolkit using Hermes's agent-browser CLI.

    No local Chrome needed! Uses headless browser via agent-browser.
    """

    name = "browser"

    @classmethod
    def get_tools(cls) -> list:
        return [
            cls.browser_navigate,
            cls.browser_snapshot,
            cls.browser_screenshot,
            cls.browser_click,
            cls.browser_type,
            cls.browser_press,
            cls.browser_scroll,
            cls.browser_open,
            cls.browser_close,
            cls.computer_see,
            cls.computer_click,
            cls.computer_type,
            cls.computer_key,
        ]

    def __init__(self, config: Optional[BrowserConfig] = None):
        self.config = config or BrowserConfig()

    def _run_agent_browser(
        self,
        task_id: str,
        command: str,
        args: list[str],
        timeout: int = 30,
    ) -> dict[str, Any]:
        """Run agent-browser CLI command."""
        if not _is_agent_browser_available():
            return {
                "error": f"agent-browser not found. Install with: {_agent_browser_install_hint()}",
                "success": False,
                "hint": "Run: npm install -g agent-browser && agent-browser install",
            }

        cmd = [
            "agent-browser",
            command,
            "--task-id",
            task_id,
            *args,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, "PATH": _merge_browser_path()},
            )

            if result.returncode == 0:
                try:
                    return {"success": True, "data": json.loads(result.stdout) if result.stdout else {}}
                except json.JSONDecodeError:
                    return {"success": True, "data": {"output": result.stdout}}
            else:
                error_msg = result.stderr or "Command failed"
                if "Chrome" in error_msg or "chromium" in error_msg.lower():
                    return {
                        "success": False,
                        "error": "Chrome/Chromium not found. Run: agent-browser install",
                        "hint": "This downloads headless Chrome for browser automation",
                    }
                return {"success": False, "error": error_msg}

        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"Command timed out after {timeout}s"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def browser_navigate(
        self,
        ctx: AgentDeps,
        url: str,
        task_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Navigate to URL."""
        tid = task_id or ctx.deps.session_id or "default"
        result = self._run_agent_browser(tid, "goto", [url])
        if result.get("success"):
            return {"success": True, "url": url, "message": f"Navigated to {url}"}
        return result

    async def browser_snapshot(
        self,
        ctx: AgentDeps,
        task_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Get page accessibility snapshot."""
        tid = task_id or ctx.deps.session_id or "default"
        result = self._run_agent_browser(tid, "snapshot", [])
        return result

    async def browser_screenshot(
        self,
        ctx: AgentDeps,
        task_id: Optional[str] = None,
        full_page: bool = False,
    ) -> dict[str, Any]:
        """Take a screenshot."""
        tid = task_id or ctx.deps.session_id or "default"

        # Create temp file for screenshot
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            screenshot_path = f.name

        args = [screenshot_path]
        if full_page:
            args.insert(0, "--full")

        result = self._run_agent_browser(tid, "screenshot", args)

        if result.get("success") and os.path.exists(screenshot_path):
            try:
                with open(screenshot_path, "rb") as f:
                    b64_data = base64.b64encode(f.read()).decode()
                os.unlink(screenshot_path)
                return {
                    "success": True,
                    "data": f"data:image/png;base64,{b64_data}",
                    "path": screenshot_path,
                }
            except Exception as e:
                return {"success": False, "error": str(e)}

        # Cleanup temp file on failure
        if os.path.exists(screenshot_path):
            os.unlink(screenshot_path)
        return result

    async def browser_click(
        self,
        ctx: AgentDeps,
        selector: str,
        task_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Click an element by selector."""
        tid = task_id or ctx.deps.session_id or "default"
        result = self._run_agent_browser(tid, "click", [selector])
        if result.get("success"):
            return {"success": True, "message": f"Clicked {selector}"}
        return result

    async def browser_type(
        self,
        ctx: AgentDeps,
        selector: str,
        text: str,
        task_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Type text into an element."""
        tid = task_id or ctx.deps.session_id or "default"
        result = self._run_agent_browser(tid, "type", [selector, text])
        if result.get("success"):
            return {"success": True, "message": f"Typed into {selector}"}
        return result

    async def browser_press(
        self,
        ctx: AgentDeps,
        keys: str,
        task_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Press a key."""
        tid = task_id or ctx.deps.session_id or "default"
        result = self._run_agent_browser(tid, "press", [keys])
        if result.get("success"):
            return {"success": True, "message": f"Pressed {keys}"}
        return result

    async def browser_scroll(
        self,
        ctx: AgentDeps,
        direction: str = "down",
        amount: int = 3,
        task_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Scroll the page."""
        tid = task_id or ctx.deps.session_id or "default"
        result = self._run_agent_browser(tid, "scroll", [direction, str(amount)])
        if result.get("success"):
            return {"success": True, "message": f"Scrolled {direction}"}
        return result

    async def browser_open(
        self,
        ctx: AgentDeps,
        url: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Open browser, optionally navigate to URL."""
        tid = task_id or ctx.deps.session_id or "default"
        args = [url] if url else []
        result = self._run_agent_browser(tid, "open", args)
        if result.get("success"):
            return {"success": True, "message": "Browser opened", "url": url}
        return result

    async def browser_close(
        self,
        ctx: AgentDeps,
        task_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Close the browser."""
        tid = task_id or ctx.deps.session_id or "default"
        result = self._run_agent_browser(tid, "close", [])
        if result.get("success"):
            return {"success": True, "message": "Browser closed"}
        return result

    # === Computer Use (CUA driver) ===

    async def computer_see(
        self,
        ctx: AgentDeps,
        mode: str = "som",
        app: Optional[str] = None,
    ) -> dict[str, Any]:
        """Capture screen/element tree via cua-driver."""
        try:
            from app.core.toolkits.hermes.cua_backend import CuaDriverBackend

            backend = CuaDriverBackend()
            if not backend.is_available():
                return {
                    "error": "cua-driver not available. Install from: https://github.com/trycua/cua-driver",
                    "success": False,
                }
            backend.start()
            try:
                cap = backend.capture(mode=mode, app=app)
                result: dict[str, Any] = {
                    "success": True,
                    "mode": cap.mode,
                    "width": cap.width,
                    "height": cap.height,
                    "app": cap.app,
                    "window_title": cap.window_title,
                    "elements": [
                        {
                            "index": e.index,
                            "role": e.role,
                            "label": e.label,
                            "bounds": list(e.bounds),
                        }
                        for e in cap.elements
                    ],
                }
                if cap.png_b64:
                    result["image"] = f"data:image/png;base64,{cap.png_b64}"
                return result
            finally:
                backend.stop()
        except ImportError:
            return {
                "error": "cua-driver not installed. Run: hermes computer-use install",
                "success": False,
            }
        except Exception as e:
            return {"error": str(e), "success": False}

    async def computer_click(
        self,
        ctx: AgentDeps,
        x: int,
        y: int,
        button: str = "left",
        click_count: int = 1,
    ) -> dict[str, Any]:
        """Click at coordinates via cua-driver."""
        try:
            from app.core.toolkits.hermes.cua_backend import CuaDriverBackend

            backend = CuaDriverBackend()
            if not backend.is_available():
                return {"error": "cua-driver not available", "success": False}
            backend.start()
            try:
                res = backend.click(x=x, y=y, button=button, click_count=click_count)
                return {"success": res.ok, "message": res.message}
            finally:
                backend.stop()
        except Exception as e:
            return {"error": str(e), "success": False}

    async def computer_type(
        self,
        ctx: AgentDeps,
        text: str,
    ) -> dict[str, Any]:
        """Type text via cua-driver."""
        try:
            from app.core.toolkits.hermes.cua_backend import CuaDriverBackend

            backend = CuaDriverBackend()
            if not backend.is_available():
                return {"error": "cua-driver not available", "success": False}
            backend.start()
            try:
                res = backend.type_text(text)
                return {"success": res.ok, "message": res.message}
            finally:
                backend.stop()
        except Exception as e:
            return {"error": str(e), "success": False}

    async def computer_key(
        self,
        ctx: AgentDeps,
        keys: str,
    ) -> dict[str, Any]:
        """Press key via cua-driver."""
        try:
            from app.core.toolkits.hermes.cua_backend import CuaDriverBackend

            backend = CuaDriverBackend()
            if not backend.is_available():
                return {"error": "cua-driver not available", "success": False}
            backend.start()
            try:
                res = backend.key(keys)
                return {"success": res.ok, "message": res.message}
            finally:
                backend.stop()
        except Exception as e:
            return {"error": str(e), "success": False}
