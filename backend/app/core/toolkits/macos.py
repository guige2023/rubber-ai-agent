"""
MacosToolkit - Native macOS desktop control using osascript, screencapture, Quartz.

Replicates mac-control skill capabilities:
- Screenshot (PIL or screencapture)
- Application control (osascript)
- Window management (osascript)
- Mouse control (Quartz CGEvent, needs Accessibility)
- Keyboard simulation (osascript System Events, needs Accessibility)
- Clipboard (pbcopy/pbpaste)
- System control (volume, brightness via osascript)
- Process management (ps/pkill)

No new dependencies required. Uses macOS native commands.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Annotated, Any

from pydantic_ai.tools import RunContext

from app.core.deps import AgentDeps
from app.core.toolkits.base import Toolkit


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


async def _run_shell(cmd: str, timeout: float = 30.0) -> tuple[str, str, int]:
    """Run a shell command, return (stdout, stderr, returncode)."""
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return (
                stdout_b.decode("utf-8", errors="replace").strip(),
                stderr_b.decode("utf-8", errors="replace").strip(),
                proc.returncode or 0,
            )
        except asyncio.TimeoutError:
            proc.kill()
            try:
                await proc.wait()
            except Exception:
                pass
            return "", "Command timed out / Accessibility permission may be required", -1
    except Exception as e:
        return "", str(e), -1


async def _run_python(code: str, timeout: float = 30.0) -> tuple[str, str, int]:
    """Run a Python snippet via /usr/bin/python3, return (stdout, stderr, returncode)."""
    cmd = f'/usr/bin/python3 -c "{code.replace("\\", "\\\\").replace('"', '\\"')}"'
    return await _run_shell(cmd, timeout)


def _screen_h() -> int:
    """Get main screen height using system_profiler fallback."""
    # We resolve this lazily at call time in get_screen_info
    return 0


# ---------------------------------------------------------------------------
# Toolkit
# ---------------------------------------------------------------------------


class MacosToolkit(Toolkit):
    """Native macOS desktop control toolkit."""

    @staticmethod
    def get_tools():
        return [
            # Screenshot
            MacosToolkit.screenshot,
            # Application management
            MacosToolkit.open_application,
            MacosToolkit.close_application,
            MacosToolkit.get_frontmost_application,
            MacosToolkit.list_running_applications,
            # Window management
            MacosToolkit.list_windows,
            MacosToolkit.set_window_bounds,
            MacosToolkit.move_window,
            # Mouse control (needs Accessibility)
            MacosToolkit.click_mouse,
            MacosToolkit.move_mouse,
            MacosToolkit.double_click_mouse,
            MacosToolkit.drag_mouse,
            MacosToolkit.get_mouse_position,
            # Keyboard simulation (needs Accessibility)
            MacosToolkit.type_text,
            MacosToolkit.press_key,
            MacosToolkit.press_hotkey,
            # Clipboard
            MacosToolkit.clipboard_read,
            MacosToolkit.clipboard_write,
            # System control
            MacosToolkit.set_volume,
            MacosToolkit.get_screen_info,
            # Process management
            MacosToolkit.list_processes,
            MacosToolkit.kill_process,
        ]

    # ------------------------------------------------------------------
    # Screenshot
    # ------------------------------------------------------------------

    @staticmethod
    async def screenshot(
        ctx: RunContext[AgentDeps],
        path: Annotated[str, "Screenshot save path"] = "/tmp/screenshot.png",
    ) -> str:
        """Capture full screen and save to file. Uses PIL as fallback if screencapture needs permission."""
        # Try PIL first (no special permissions needed)
        try:
            pil_code = f'import Quartz; from PIL import ImageGrab; img = ImageGrab.grab(); img.save("{path}"); print("ok")'
            stdout, stderr, rc = await _run_python(pil_code)
            if rc == 0 and Path(path).exists():
                return f"Screenshot saved: {path}"
        except Exception:
            pass

        # Fallback to screencapture
        stdout, stderr, rc = await _run_shell(f"/usr/sbin/screencapture -x {path}")
        if rc == 0 and Path(path).exists():
            return f"Screenshot saved: {path}"
        return f"Screenshot failed: {stderr or 'unknown error'}"

    # ------------------------------------------------------------------
    # Application management
    # ------------------------------------------------------------------

    @staticmethod
    async def open_application(
        ctx: RunContext[AgentDeps],
        name: Annotated[str, "App name (e.g. Safari) or path to .app"],
    ) -> str:
        """Open or activate an application by name or path."""
        escaped = name.replace("\\", "\\\\").replace('"', '\\"')
        stdout, stderr, rc = await _run_shell(f"osascript -e \'tell application \"{escaped}\" to activate\'")
        if rc == 0:
            return f"Application '{name}' activated"
        return f"Failed to activate '{name}': {stderr}"

    @staticmethod
    async def close_application(
        ctx: RunContext[AgentDeps],
        name: Annotated[str, "App name to quit"],
    ) -> str:
        """Close an application by name (graceful quit)."""
        escaped = name.replace("\\", "\\\\").replace('"', '\\"')
        stdout, stderr, rc = await _run_shell(f"osascript -e \'tell application \"{escaped}\" to quit\'")
        if rc == 0:
            return f"Application '{name}' closed"
        return f"Failed to close '{name}': {stderr}"

    @staticmethod
    async def get_frontmost_application(ctx: RunContext[AgentDeps]) -> str:
        """Get the name of the currently frontmost application (via ps)."""
        # Get frontmost app PID from ps - to find the app owning the focused window
        # We use the fact that the frontmost app is the one with highest CPU at the moment
        # Better: use AppleScript path to frontmost (no Accessibility needed for reading)
        stdout, stderr, rc = await _run_shell(
            "osascript -e 'POSIX path of (path to frontmost application from user domain)'",
            timeout=10.0,
        )
        if rc == 0 and stdout.strip():
            name = stdout.strip().split("/")[-2] if "/" in stdout else stdout.strip()
            return name
        # Fallback: last resort
        stdout2, _, _ = await _run_shell(
            "ps -axc -o comm | head -5", timeout=5.0
        )
        lines = [l.strip() for l in stdout2.split("\n") if l.strip()]
        return lines[1] if len(lines) > 1 else "unknown"

    @staticmethod
    async def list_running_applications(ctx: RunContext[AgentDeps]) -> str:
        """List all currently running visible applications."""
        # Fast approach: ps aux to list processes from /Applications
        stdout, stderr, rc = await _run_shell(
            "ps aux | grep '/Applications/' | grep -v grep | "
            "awk '{for(i=NF;i>=NF-4;i--) printf \"%s \", $i; print \"\"}' | "
            "sort -u | head -40",
            timeout=10.0,
        )
        if rc == 0 and stdout.strip():
            apps = [a.strip() for a in stdout.strip().split("\n") if a.strip() and a.strip() != "--"]
            return "\n".join(f"  - {a}" for a in sorted(set(apps))) if apps else "(no visible applications)"
        return f"Error listing applications: {stderr}"  

    # ------------------------------------------------------------------
    # Window management
    # ------------------------------------------------------------------

    @staticmethod
    async def list_windows(ctx: RunContext[AgentDeps]) -> str:
        """List all visible windows: AppName | x,y | WxH"""
        script = """osascript -e 'tell application "System Events"
          set windowList to {}
          repeat with appProcess in (every application process whose visible is true)
            repeat with win in (every window of appProcess)
              set appName to name of appProcess
              set winPos to position of win
              set winSize to size of win
              copy (appName & "|" & (item 1 of winPos as text) & "," & (item 2 of winPos as text) & "|" & (item 1 of winSize as text) & "x" & (item 2 of winSize as text)) to end of windowList
            end repeat
          end repeat
          return windowList
        end tell'"""
        stdout, stderr, rc = await _run_shell(script)
        if rc != 0:
            return f"Error listing windows (may need Accessibility permission): {stderr}"
        lines = [line.strip() for line in stdout.split(", ") if line.strip()]
        if not lines:
            return "(no visible windows)"
        return "\n".join(f"  {line}" for line in lines)

    @staticmethod
    async def set_window_bounds(
        ctx: RunContext[AgentDeps],
        app_name: Annotated[str, "Application name"],
        x: Annotated[int, "Left edge X"],
        y: Annotated[int, "Top edge Y"],
        width: Annotated[int, "Width"],
        height: Annotated[int, "Height"],
    ) -> str:
        """Set window position and size: {x, y, x+width, y+height}."""
        bounds = f"{{{x}, {y}, {x + width}, {y + height}}}"
        cmd = [
            "osascript",
            "-e",
            f"tell application \"{app_name}\" to set bounds of window 1 to {bounds}",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr_b = await proc.communicate()
        if proc.returncode == 0:
            return f"Window bounds set: {app_name} ({x},{y}) {width}x{height}"
        return f"Failed (may need Accessibility permission): {stderr_b.decode()}"

    @staticmethod
    async def move_window(
        ctx: RunContext[AgentDeps],
        app_name: Annotated[str, "Application name"],
        x: Annotated[int, "New left edge X"],
        y: Annotated[int, "New top edge Y"],
    ) -> str:
        """Move window to new position (preserves current size)."""
        escaped = app_name.replace('"', '\\"')
        # First get current size
        script = f"osascript -e \'tell application \"{escaped}\" to get size of window 1\'"
        stdout, stderr, rc = await _run_shell(script)
        if rc != 0:
            return f"Failed to get window size: {stderr}"
        try:
            w, h = [int(v.strip()) for v in stdout.split(",")]
        except Exception:
            return f"Could not parse window size from: {stdout}"
        return await MacosToolkit.set_window_bounds(ctx, app_name, x, y, w, h)

    # ------------------------------------------------------------------
    # Mouse control (needs Accessibility)
    # ------------------------------------------------------------------

    @staticmethod
    async def click_mouse(
        ctx: RunContext[AgentDeps],
        x: Annotated[int, "X coordinate (desktop pixel)"],
        y: Annotated[int, "Y coordinate (desktop pixel, 0=top)"],
        button: Annotated[str, "left / right / middle"] = "left",
    ) -> str:
        """Click at desktop coordinate (needs Accessibility permission)."""
        btn_map = {
            "left": "Quartz.kCGEventLeftMouseDown",
            "right": "Quartz.kCGEventRightMouseDown",
            "middle": "Quartz.kCGEventOtherMouseDown",
        }
        btn_code = btn_map.get(button.lower(), "Quartz.kCGEventLeftMouseDown")
        code = f"""import Quartz; x, y = {x}, {y}; down = Quartz.CGEventCreateMouseEvent(None, {btn_code}, (x, y), Quartz.kCGMouseButtonLeft); up = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseUp, (x, y), Quartz.kCGMouseButtonLeft); Quartz.CGEventPost(Quartz.kCGHIDEventTap, down); Quartz.CGEventPost(Quartz.kCGHIDEventTap, up); print('clicked')"""
        stdout, stderr, rc = await _run_python(code)
        if rc == 0:
            return f"Clicked at ({x}, {y})"
        return f"Click failed (needs Accessibility permission): {stderr}"

    @staticmethod
    async def move_mouse(
        ctx: RunContext[AgentDeps],
        x: Annotated[int, "Target X"],
        y: Annotated[int, "Target Y"],
    ) -> str:
        """Move mouse cursor to desktop coordinate."""
        code = f"import Quartz; Quartz.CGEventMoveMouse(Quartz.CGEventCreate(None), ({x}, {y})); print('moved')"
        stdout, stderr, rc = await _run_python(code)
        if rc == 0:
            return f"Mouse moved to ({x}, {y})"
        return f"Move failed (needs Accessibility permission): {stderr}"

    @staticmethod
    async def double_click_mouse(
        ctx: RunContext[AgentDeps],
        x: Annotated[int, "X coordinate"],
        y: Annotated[int, "Y coordinate"],
    ) -> str:
        """Double-click at desktop coordinate."""
        code = f"""import Quartz; x, y = {x}, {y}; d = Quartz.kCGEventLeftMouseDown; u = Quartz.kCGEventLeftMouseUp; ev = lambda t: Quartz.CGEventCreateMouseEvent(None, t, (x, y), Quartz.kCGMouseButtonLeft); Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev(d)); Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev(u)); Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev(d)); Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev(u)); print('double-clicked')"""
        stdout, stderr, rc = await _run_python(code)
        if rc == 0:
            return f"Double-clicked at ({x}, {y})"
        return f"Double-click failed (needs Accessibility permission): {stderr}"

    @staticmethod
    async def drag_mouse(
        ctx: RunContext[AgentDeps],
        x1: Annotated[int, "Start X"],
        y1: Annotated[int, "Start Y"],
        x2: Annotated[int, "End X"],
        y2: Annotated[int, "End Y"],
    ) -> str:
        """Drag from (x1,y1) to (x2,y2)."""
        code = f"""import Quartz, time; x1, y1, x2, y2 = {x1}, {y1}, {x2}, {y2}
move = lambda tx, ty: Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, (tx, ty), Quartz.kCGMouseButtonLeft)
down = lambda tx, ty: Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseDown, (tx, ty), Quartz.kCGMouseButtonLeft)
up = lambda tx, ty: Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseUp, (tx, ty), Quartz.kCGMouseButtonLeft)
Quartz.CGEventPost(Quartz.kCGHIDEventTap, down(x1, y1)); time.sleep(0.05)
for i in range(11): cx = x1 + (x2-x1)*i/10; cy = y1 + (y2-y1)*i/10; Quartz.CGEventPost(Quartz.kCGHIDEventTap, move(cx, cy)); time.sleep(0.02)
Quartz.CGEventPost(Quartz.kCGHIDEventTap, up(x2, y2)); print('dragged')"""
        stdout, stderr, rc = await _run_python(code)
        if rc == 0:
            return f"Dragged from ({x1},{y1}) to ({x2},{y2})"
        return f"Drag failed (needs Accessibility permission): {stderr}"

    @staticmethod
    async def get_mouse_position(ctx: RunContext[AgentDeps]) -> str:
        """Get current mouse position in desktop coordinates."""
        code = "import Quartz; pos = Quartz.NSEvent.mouseLocation(); main = Quartz.NSScreen.screens()[0]; h = main.frame().size.height; print(f'{(int(pos.x)}, {int(h-pos.y)})')"
        stdout, stderr, rc = await _run_python(code)
        if rc == 0:
            return f"Mouse position: {stdout}"
        return f"Failed to get mouse position: {stderr}"

    # ------------------------------------------------------------------
    # Keyboard simulation (needs Accessibility)
    # ------------------------------------------------------------------

    @staticmethod
    async def type_text(
        ctx: RunContext[AgentDeps],
        text: Annotated[str, "Text to type"],
    ) -> str:
        """Type text (needs Accessibility permission)."""
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        stdout, stderr, rc = await _run_shell(
            f"osascript -e \'tell application \"System Events\" to keystroke \"{escaped}\"\'"
        )
        if rc == 0:
            return f"Typed: {text[:50]}{'...' if len(text) > 50 else ''}"
        return f"Type failed (needs Accessibility permission): {stderr}"

    @staticmethod
    async def press_key(
        ctx: RunContext[AgentDeps],
        key: Annotated[str, "Key name (e.g. 'return', 'escape', 'delete', 'a')"],
    ) -> str:
        """Press a single key (needs Accessibility permission)."""
        escaped = key.replace('"', '\\"')
        stdout, stderr, rc = await _run_shell(
            f"osascript -e \'tell application \"System Events\" to key code (do shell script \"osascript -e \'tell application \\\"System Events\\\" to return ASCII number of \\\"{escaped}\\\"\'\")\'"
        )
        # Simpler: use key code directly for common keys
        keycode_map = {
            "return": "36", "enter": "76", "escape": "53", "tab": "48",
            "delete": "51", "forward_delete": "117", "up": "126", "down": "125",
            "left": "123", "right": "124", "space": "49",
        }
        code = keycode_map.get(key.lower())
        if code:
            stdout, stderr, rc = await _run_shell(
                f"osascript -e \'tell application \"System Events\" to key code {code}\'"
            )
            if rc == 0:
                return f"Pressed key: {key}"
        return f"Press key failed (needs Accessibility permission): {stderr}"

    @staticmethod
    async def press_hotkey(
        ctx: RunContext[AgentDeps],
        key: Annotated[str, "Key to press (e.g. 's', 'a')"],
        modifiers: Annotated[str, "Comma-separated: cmd,shift,ctrl,alt"] = "",
    ) -> str:
        """Press a hotkey combination (needs Accessibility permission)."""
        mod_map = {
            "cmd": "command down", "command": "command down",
            "shift": "shift down",
            "ctrl": "control down", "control": "control down",
            "alt": "option down", "option": "option down",
        }
        parts = [mod_map.get(m.strip().lower(), "") for m in modifiers.split(",") if m.strip()]
        mods = " ".join(p for p in parts if p)
        using_clause = f" using {mods}" if mods else ""
        escaped = key.replace('"', '\\"')
        stdout, stderr, rc = await _run_shell(
            f"osascript -e \'tell application \"System Events\" to keystroke \"{escaped}\"{using_clause}\'"
        )
        if rc == 0:
            combo = f"{modifiers}+{key}" if modifiers else key
            return f"Pressed hotkey: {combo}"
        return f"Hotkey failed (needs Accessibility permission): {stderr}"

    # ------------------------------------------------------------------
    # Clipboard
    # ------------------------------------------------------------------

    @staticmethod
    async def clipboard_read(ctx: RunContext[AgentDeps]) -> str:
        """Read current clipboard contents."""
        stdout, stderr, rc = await _run_shell("pbpaste")
        if rc == 0:
            content = stdout or "(empty)"
            return f"Clipboard:\n{content}"
        return f"Clipboard read failed: {stderr}"

    @staticmethod
    async def clipboard_write(
        ctx: RunContext[AgentDeps],
        text: Annotated[str, "Text to write to clipboard"],
    ) -> str:
        """Write text to clipboard."""
        proc = await asyncio.create_subprocess_exec(
            "pbcopy",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        proc.stdin.write(text.encode("utf-8"))
        await proc.stdin.drain()
        await proc.stdin.close()
        await proc.wait()
        if proc.returncode == 0:
            return "Clipboard written"
        return f"Clipboard write failed"

    # ------------------------------------------------------------------
    # System control
    # ------------------------------------------------------------------

    @staticmethod
    async def set_volume(
        ctx: RunContext[AgentDeps],
        level: Annotated[int, "Volume 0-7"] = 5,
    ) -> str:
        """Set output volume (0-7)."""
        lvl = max(0, min(7, level))
        stdout, stderr, rc = await _run_shell(f"osascript -e \'set volume output volume {lvl}\'")
        if rc == 0:
            return f"Volume set to {lvl}"
        return f"Volume set failed: {stderr}"

    @staticmethod
    async def get_screen_info(ctx: RunContext[AgentDeps]) -> dict[str, Any]:
        """Get screen resolution and environment info."""
        code = """import Quartz
main = Quartz.NSScreen.screens()[0]
frame = main.frame()
print(f"Resolution: {int(frame.size.width)}x{int(frame.size.height)}")
print(f"MenuBar height: ~25 (47 with notch)")
print(f"Dock height: ~80")
"""
        stdout, stderr, rc = await _run_python(code)
        result = {
            "resolution": "unknown",
            "menu_bar_height": 25,
            "dock_height": 80,
        }
        if rc == 0:
            for line in stdout.split("\n"):
                if "Resolution" in line:
                    result["resolution"] = line.split(":", 1)[1].strip()
        return result

    # ------------------------------------------------------------------
    # Process management
    # ------------------------------------------------------------------

    @staticmethod
    async def list_processes(
        ctx: RunContext[AgentDeps],
        filter: Annotated[str | None, "Filter by name (optional)"] = None,
        limit: Annotated[int, "Max number of results"] = 20,
    ) -> str:
        """List running processes (ps aux wrapper)."""
        cmd = "ps aux"
        if filter:
            cmd += f" | grep -i '{filter}' | grep -v grep | head -{limit}"
        else:
            cmd += f" | head -{limit}"
        stdout, stderr, rc = await _run_shell(cmd)
        return stdout or f"No processes found{': ' + stderr if stderr else ''}"

    @staticmethod
    async def kill_process(
        ctx: RunContext[AgentDeps],
        name: Annotated[str | None, "Process name to kill"] = None,
        pid: Annotated[int | None, "Process PID to kill"] = None,
    ) -> str:
        """Kill a process by name or PID."""
        if name:
            stdout, stderr, rc = await _run_shell(f"pkill -f '{name}'")
            if rc == 0:
                return f"Killed processes matching: {name}"
            return f"No process found matching '{name}': {stderr}"
        elif pid:
            stdout, stderr, rc = await _run_shell(f"kill -9 {pid}")
            if rc == 0:
                return f"Killed PID {pid}"
            return f"Failed to kill PID {pid}: {stderr}"
        return "Specify either name or pid"
