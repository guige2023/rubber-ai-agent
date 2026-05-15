"""
CUA Driver Backend for macOS computer use.

Based on Hermes's computer_use/cua_backend.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import threading
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_CUA_DRIVER_CMD = os.environ.get("RABAIAGENT_CUA_DRIVER_CMD", "cua-driver")
_CUA_DRIVER_ARGS = ["mcp"]


def _is_macos() -> bool:
    return sys.platform == "darwin"


def cua_driver_binary_available() -> bool:
    """Check if cua-driver is on PATH."""
    return bool(shutil.which(_CUA_DRIVER_CMD))


def cua_driver_install_hint() -> str:
    return (
        "cua-driver is not installed. Install with:\n"
        "  hermes computer-use install\n"
        '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/trycua/cua/main/libs/cua-driver/scripts/install.sh)"\n'
    )


@dataclass
class UIElement:
    index: int
    role: str
    label: str
    bounds: Tuple[int, int, int, int]
    app: str = ""
    pid: int = 0
    window_id: int = 0


@dataclass
class CaptureResult:
    mode: str
    width: int
    height: int
    png_b64: Optional[str]
    elements: List[UIElement]
    app: str
    window_title: str
    png_bytes_len: int = 0


@dataclass
class ActionResult:
    ok: bool
    action: str
    message: str = ""
    meta: dict = None


class ComputerUseBackend:
    """Base class for computer use backends."""

    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def is_available(self) -> bool:
        raise NotImplementedError

    def capture(self, mode: str = "som", app: Optional[str] = None) -> CaptureResult:
        raise NotImplementedError

    def click(self, element: Optional[int] = None, x: Optional[int] = None, y: Optional[int] = None,
              button: str = "left", click_count: int = 1, modifiers: Optional[List[str]] = None) -> ActionResult:
        raise NotImplementedError

    def type_text(self, text: str) -> ActionResult:
        raise NotImplementedError

    def key(self, keys: str) -> ActionResult:
        raise NotImplementedError

    def scroll(self, direction: str, amount: int = 3, element: Optional[int] = None,
               x: Optional[int] = None, y: Optional[int] = None, modifiers: Optional[List[str]] = None) -> ActionResult:
        raise NotImplementedError

    def list_apps(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def focus_app(self, app: str, raise_window: bool = False) -> ActionResult:
        raise NotImplementedError


class _AsyncBridge:
    """Runs asyncio loop on background thread for MCP."""

    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._ready.clear()

        def _run() -> None:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._ready.set()
            try:
                self._loop.run_forever()
            finally:
                try:
                    self._loop.close()
                except Exception:
                    pass

        self._thread = threading.Thread(target=_run, daemon=True, name="cua-driver-loop")
        self._thread.start()
        if not self._ready.wait(timeout=5.0):
            raise RuntimeError("cua-driver asyncio bridge failed to start")

    def run(self, coro, timeout: Optional[float] = 30.0) -> Any:
        if not self._loop or not self._thread or not self._thread.is_alive():
            raise RuntimeError("cua-driver bridge not started")
        fut: Future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=timeout)

    def stop(self) -> None:
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=2.0)
        self._thread = None
        self._loop = None


class _CuaDriverSession:
    """MCP session for cua-driver."""

    def __init__(self, bridge: _AsyncBridge) -> None:
        self._bridge = bridge
        self._session = None
        self._exit_stack = None
        self._lock = threading.Lock()
        self._started = False

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._bridge.start()
            self._bridge.run(self._aenter(), timeout=15.0)
            self._started = True

    async def _aenter(self) -> None:
        from contextlib import AsyncExitStack
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        if not cua_driver_binary_available():
            raise RuntimeError(cua_driver_install_hint())

        params = StdioServerParameters(
            command=_CUA_DRIVER_CMD,
            args=_CUA_DRIVER_ARGS,
            env={**os.environ},
        )
        stack = AsyncExitStack()
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._exit_stack = stack
        self._session = session

    async def _aexit(self) -> None:
        if self._exit_stack is not None:
            try:
                await self._exit_stack.aclose()
            except Exception as e:
                logger.warning("cua-driver shutdown error: %s", e)
        self._exit_stack = None
        self._session = None

    def stop(self) -> None:
        with self._lock:
            if not self._started:
                return
            try:
                self._bridge.run(self._aexit(), timeout=5.0)
            finally:
                self._started = False

    async def _call_tool_async(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        result = await self._session.call_tool(name, args)
        return self._extract_result(result)

    def call_tool(self, name: str, args: Dict[str, Any], timeout: float = 30.0) -> Dict[str, Any]:
        self._bridge.run(self._call_tool_async(name, args), timeout=timeout)

    def _extract_result(self, mcp_result: Any) -> Dict[str, Any]:
        """Convert MCP result to dict."""
        data: Any = None
        images: List[str] = []
        is_error = bool(getattr(mcp_result, "isError", False))
        structured: Optional[Dict] = getattr(mcp_result, "structuredContent", None) or None
        text_chunks: List[str] = []

        for part in getattr(mcp_result, "content", []) or []:
            ptype = getattr(part, "type", None)
            if ptype == "text":
                text_chunks.append(getattr(part, "text", "") or "")
            elif ptype == "image":
                b64 = getattr(part, "data", None)
                if b64:
                    images.append(b64)

        if text_chunks:
            joined = "\n".join(t for t in text_chunks if t)
            try:
                data = json.loads(joined) if joined.strip().startswith(("{", "[")) else joined
            except json.JSONDecodeError:
                data = joined

        return {"data": data, "images": images, "structuredContent": structured, "isError": is_error}


def _parse_elements_from_tree(markdown: str) -> List[UIElement]:
    """Parse UIElement list from get_window_state AX tree markdown."""
    elements = []
    pattern = re.compile(r'^\s*-\s+\[(\d+)\]\s+(\w+)(?:\s+"([^"]*)")?', re.MULTILINE)
    for m in pattern.finditer(markdown):
        elements.append(UIElement(
            index=int(m.group(1)),
            role=m.group(2),
            label=m.group(3) or "",
            bounds=(0, 0, 0, 0),
        ))
    return elements


def _parse_windows_from_text(text: str) -> List[Dict[str, Any]]:
    """Parse window records from list_windows text output."""
    windows = []
    pattern = re.compile(r'^-\s+(.+?)\s+\(pid\s+(\d+)\)\s+.*\[window_id:\s+(\d+)\]', re.MULTILINE)
    for m in pattern.finditer(text):
        windows.append({
            "app_name": m.group(1).strip(),
            "pid": int(m.group(2)),
            "window_id": int(m.group(3)),
            "off_screen": "[off-screen]" in m.group(0),
        })
    return windows


class CuaDriverBackend(ComputerUseBackend):
    """macOS computer use via cua-driver MCP."""

    def __init__(self) -> None:
        self._bridge = _AsyncBridge()
        self._session = _CuaDriverSession(self._bridge)
        self._active_pid: Optional[int] = None
        self._active_window_id: Optional[int] = None

    def start(self) -> None:
        self._session.start()

    def stop(self) -> None:
        try:
            self._session.stop()
        finally:
            self._bridge.stop()

    def is_available(self) -> bool:
        if not _is_macos():
            return False
        return cua_driver_binary_available()

    def capture(self, mode: str = "som", app: Optional[str] = None) -> CaptureResult:
        """Capture the frontmost window."""
        # List windows
        lw_out = self._session.call_tool("list_windows", {"on_screen_only": True})
        sc = lw_out.get("structuredContent") or {}
        raw_windows = sc.get("windows") if sc else None

        if raw_windows:
            windows = [
                {
                    "app_name": w.get("app_name", ""),
                    "pid": int(w["pid"]),
                    "window_id": int(w["window_id"]),
                    "off_screen": not w.get("is_on_screen", True),
                    "title": w.get("title", ""),
                    "z_index": w.get("z_index", 0),
                }
                for w in raw_windows
            ]
            windows.sort(key=lambda w: w["z_index"])
        else:
            raw_text = lw_out["data"] if isinstance(lw_out["data"], str) else ""
            windows = _parse_windows_from_text(raw_text)

        if not windows:
            return CaptureResult(mode=mode, width=0, height=0, png_b64=None,
                               elements=[], app="", window_title="", png_bytes_len=0)

        # Filter by app name
        if app:
            app_lower = app.lower()
            filtered = [w for w in windows if app_lower in w["app_name"].lower()]
            if filtered:
                windows = filtered

        target = next((w for w in windows if not w["off_screen"]), windows[0])
        self._active_pid = target["pid"]
        self._active_window_id = target["window_id"]

        png_b64: Optional[str] = None
        elements: List[UIElement] = []

        if mode == "vision":
            sc_out = self._session.call_tool("screenshot", {"window_id": self._active_window_id, "format": "jpeg", "quality": 85})
            if sc_out["images"]:
                png_b64 = sc_out["images"][0]
        else:
            gws_out = self._session.call_tool("get_window_state", {"pid": self._active_pid, "window_id": self._active_window_id})
            text = gws_out["data"] if isinstance(gws_out["data"], str) else ""
            elements = _parse_elements_from_tree(text)
            if gws_out["images"]:
                png_b64 = gws_out["images"][0]

        png_bytes_len = len(base64.b64decode(png_b64, validate=False)) if png_b64 else 0

        return CaptureResult(
            mode=mode,
            width=0,
            height=0,
            png_b64=png_b64,
            elements=elements,
            app=target["app_name"],
            window_title=target.get("title", ""),
            png_bytes_len=png_bytes_len,
        )

    def click(self, element: Optional[int] = None, x: Optional[int] = None, y: Optional[int] = None,
              button: str = "left", click_count: int = 1, modifiers: Optional[List[str]] = None) -> ActionResult:
        if self._active_pid is None:
            return ActionResult(ok=False, action="click", message="No active window — call capture() first.")

        args: Dict[str, Any] = {"pid": self._active_pid}
        if element is not None and self._active_window_id is not None:
            args["element_index"] = element
            args["window_id"] = self._active_window_id
        elif x is not None and y is not None:
            args["x"] = x
            args["y"] = y
        else:
            return ActionResult(ok=False, action="click", message="click requires element= or x/y.")

        tool = "right_click" if button == "right" else ("double_click" if click_count == 2 else "click")
        if modifiers:
            args["modifier"] = modifiers

        return self._action(tool, args)

    def type_text(self, text: str) -> ActionResult:
        if self._active_pid is None:
            return ActionResult(ok=False, action="type_text", message="No active window — call capture() first.")
        return self._action("type_text_chars", {"pid": self._active_pid, "text": text})

    def key(self, keys: str) -> ActionResult:
        if self._active_pid is None:
            return ActionResult(ok=False, action="key", message="No active window — call capture() first.")

        # Parse key combo
        MODIFIER_NAMES = {"cmd", "shift", "option", "alt", "ctrl", "fn"}
        parts = [p.strip().lower() for p in re.split(r'[+-]', keys) if p.strip()]
        modifiers = []
        key_name = None
        for part in parts:
            if part in {"command": "cmd", "alt": "option", "control": "ctrl"}:
                modifiers.append(part)
            elif part in MODIFIER_NAMES:
                modifiers.append(part)
            else:
                key_name = part

        if modifiers and key_name:
            return self._action("hotkey", {"pid": self._active_pid, "keys": modifiers + [key_name]})
        elif key_name:
            return self._action("press_key", {"pid": self._active_pid, "key": key_name})
        else:
            return ActionResult(ok=False, action="key", message=f"Could not parse key from '{keys}'.")

    def scroll(self, direction: str, amount: int = 3, element: Optional[int] = None,
               x: Optional[int] = None, y: Optional[int] = None, modifiers: Optional[List[str]] = None) -> ActionResult:
        if self._active_pid is None:
            return ActionResult(ok=False, action="scroll", message="No active window — call capture() first.")

        args: Dict[str, Any] = {
            "pid": self._active_pid,
            "direction": direction,
            "amount": max(1, min(50, amount)),
        }
        if element is not None and self._active_window_id is not None:
            args["element_index"] = element
            args["window_id"] = self._active_window_id
        elif x is not None and y is not None:
            args["x"] = x
            args["y"] = y

        return self._action("scroll", args)

    def list_apps(self) -> List[Dict[str, Any]]:
        out = self._session.call_tool("list_apps", {})
        data = out.get("data", {})
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("apps", [])
        return []

    def focus_app(self, app: str, raise_window: bool = False) -> ActionResult:
        lw_out = self._session.call_tool("list_windows", {"on_screen_only": True})
        sc = lw_out.get("structuredContent") or {}
        raw_windows = sc.get("windows") if sc else None

        if raw_windows:
            windows = [
                {
                    "app_name": w.get("app_name", ""),
                    "pid": int(w["pid"]),
                    "window_id": int(w["window_id"]),
                    "z_index": w.get("z_index", 0),
                }
                for w in raw_windows
            ]
            windows.sort(key=lambda w: w["z_index"])
        else:
            raw_text = lw_out["data"] if isinstance(lw_out["data"], str) else ""
            windows = _parse_windows_from_text(raw_text)

        app_lower = app.lower()
        matched = [w for w in windows if app_lower in w["app_name"].lower()]
        target = matched[0] if matched else (windows[0] if windows else None)

        if target:
            self._active_pid = target["pid"]
            self._active_window_id = target["window_id"]
            return ActionResult(
                ok=True, action="focus_app",
                message=f"Targeted {target['app_name']} (pid {self._active_pid})",
            )
        return ActionResult(ok=False, action="focus_app", message=f"No on-screen window found for app '{app}'.")

    def _action(self, name: str, args: Dict[str, Any]) -> ActionResult:
        try:
            out = self._session.call_tool(name, args)
        except Exception as e:
            logger.exception("cua-driver %s call failed", name)
            return ActionResult(ok=False, action=name, message=f"cua-driver error: {e}")

        ok = not out["isError"]
        message = ""
        data = out["data"]
        if isinstance(data, dict):
            message = str(data.get("message", ""))
        elif isinstance(data, str):
            message = data

        return ActionResult(ok=ok, action=name, message=message, meta=data if isinstance(data, dict) else {})


import sys
