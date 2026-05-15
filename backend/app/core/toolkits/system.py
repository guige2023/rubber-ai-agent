"""
System Toolkit - Unrestricted system operations for OpenCLAW-style full access.

WARNING: These tools provide unrestricted access to the file system and shell.
Only enable them in trusted environments.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
from pathlib import Path
from typing import Annotated, Any

from pydantic import BeforeValidator
from pydantic_ai.tools import RunContext

from app.core.deps import AgentDeps
from app.core.toolkits.base import Toolkit


def _coerce_args(v: object) -> list[str] | None:
    """Coerce a JSON-encoded argument list into `list[str]`."""
    if v is None or isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            import json
            return json.loads(v)
        except (json.JSONDecodeError, ValueError):
            return shlex.split(v) if v else []
    return None


class SystemToolkit(Toolkit):
    """Unrestricted system operations - USE WITH CAUTION.

    These tools provide full access to the file system and shell commands.
    Only use in trusted environments where full system access is required.
    """

    @staticmethod
    def get_tools():
        return [
            SystemToolkit.run_shell_command,
            SystemToolkit.read_file_unrestricted,
            SystemToolkit.write_file_unrestricted,
            SystemToolkit.file_exists,
            SystemToolkit.list_directory,
            SystemToolkit.create_directory,
            SystemToolkit.remove_file,
            SystemToolkit.remove_directory,
            SystemToolkit.get_home_directory,
            SystemToolkit.get_desktop_directory,
            SystemToolkit.get_current_working_directory,
        ]

    @staticmethod
    async def run_shell_command(
        ctx: RunContext[AgentDeps],
        command: Annotated[str, "The shell command to execute"],
        timeout_ms: Annotated[int, "Timeout in milliseconds"] = 60000,
        cwd: Annotated[str | None, "Working directory (defaults to current)"] = None,
    ) -> dict[str, Any]:
        """Execute an arbitrary shell command with full access.

        This is a powerful tool that can run any shell command.
        Use with caution - it has full system access.

        Args:
            command: The shell command to execute
            timeout_ms: Maximum time to wait in milliseconds (default 60s)
            cwd: Working directory for the command (defaults to current directory)

        Returns:
            Dictionary with returncode, stdout, stderr
        """
        if not command or not command.strip():
            return {"error": "No command provided", "returncode": -1, "stdout": "", "stderr": ""}

        # Security: Log the command for audit
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"[SYSTEM TOOLKIT] Executing command: {command}")

        try:
            # Always use shell to handle pipes, redirects, and compound commands
            use_shell = any(c in command for c in ('&&', '||', '|', '>', '<', '$', '`', ';'))

            if cwd:
                cwd_path = Path(cwd).expanduser().resolve()
                if not cwd_path.exists():
                    return {"error": f"Working directory does not exist: {cwd}", "returncode": -1, "stdout": "", "stderr": ""}

            timeout_sec = max(timeout_ms, 1) / 1000

            if use_shell:
                # Shell command string with pipes, redirects, etc.
                shell_cmd = f"cd {shlex.quote(str(cwd_path))} && {command}" if cwd else command
                process = await asyncio.create_subprocess_shell(
                    shell_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            else:
                # Simple command without shell features - can use exec
                cmd_list = shlex.split(command)
                process = await asyncio.create_subprocess_exec(
                    *cmd_list,
                    cwd=str(cwd_path) if cwd else None,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout_sec,
                )
            except asyncio.TimeoutError:
                process.kill()
                stdout, stderr = await process.communicate()
                return {
                    "error": f"Command timed out after {timeout_ms}ms",
                    "returncode": -1,
                    "stdout": stdout.decode("utf-8", errors="replace") if stdout else "",
                    "stderr": stderr.decode("utf-8", errors="replace") if stderr else "",
                    "timed_out": True,
                }

            return {
                "returncode": process.returncode,
                "stdout": stdout.decode("utf-8", errors="replace") if stdout else "",
                "stderr": stderr.decode("utf-8", errors="replace") if stderr else "",
                "timed_out": False,
            }

        except Exception as e:
            return {"error": str(e), "returncode": -1, "stdout": "", "stderr": ""}

    @staticmethod
    async def read_file_unrestricted(
        ctx: RunContext[AgentDeps],
        file_path: Annotated[str, "Absolute or relative path to the file to read"],
    ) -> str:
        """Read the contents of any file on the system.

        Args:
            file_path: Path to the file (absolute or relative to cwd)

        Returns:
            File contents as string
        """
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            return f"Error: File not found: {file_path}"
        if not path.is_file():
            return f"Error: Not a file: {file_path}"
        try:
            return path.read_text(encoding="utf-8")
        except Exception as e:
            return f"Error reading file: {e}"

    @staticmethod
    async def write_file_unrestricted(
        ctx: RunContext[AgentDeps],
        file_path: Annotated[str, "Absolute or relative path to the file to write"],
        content: Annotated[str, "Content to write to the file"],
    ) -> dict[str, Any]:
        """Write content to any file on the system.

        Creates parent directories as needed.

        Args:
            file_path: Path to the file
            content: Content to write

        Returns:
            Success message with file path
        """
        path = Path(file_path).expanduser().resolve()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return {"success": True, "path": str(path), "bytes": len(content)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def file_exists(
        ctx: RunContext[AgentDeps],
        path: Annotated[str, "Path to check"],
    ) -> dict[str, Any]:
        """Check if a file or directory exists.

        Returns:
            Dictionary with exists, is_file, is_dir
        """
        p = Path(path).expanduser().resolve()
        return {
            "exists": p.exists(),
            "is_file": p.is_file() if p.exists() else False,
            "is_dir": p.is_dir() if p.exists() else False,
            "path": str(p),
        }

    @staticmethod
    async def list_directory(
        ctx: RunContext[AgentDeps],
        directory: Annotated[str, "Directory to list"] = ".",
    ) -> str:
        """List contents of a directory.

        Args:
            directory: Path to directory (defaults to current directory)
        """
        path = Path(directory).expanduser().resolve()
        if not path.exists():
            return f"Error: Directory not found: {directory}"
        if not path.is_dir():
            return f"Error: Not a directory: {directory}"

        try:
            entries = sorted(path.iterdir())
            result = []
            for e in entries:
                entry_type = "DIR" if e.is_dir() else "FILE"
                size = f" ({e.stat().st_size} bytes)" if e.is_file() else ""
                result.append(f"[{entry_type}] {e.name}{size}")
            return "\n".join(result) if result else "(empty directory)"
        except Exception as e:
            return f"Error listing directory: {e}"

    @staticmethod
    async def create_directory(
        ctx: RunContext[AgentDeps],
        directory: Annotated[str, "Directory path to create"],
        parents: Annotated[bool, "Create parent directories"] = True,
    ) -> dict[str, Any]:
        """Create a directory.

        Args:
            directory: Path to create
            parents: Whether to create parent directories
        """
        path = Path(directory).expanduser().resolve()
        try:
            path.mkdir(parents=parents, exist_ok=True)
            return {"success": True, "path": str(path)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def remove_file(
        ctx: RunContext[AgentDeps],
        file_path: Annotated[str, "File to remove"],
    ) -> dict[str, Any]:
        """Remove a file.

        Args:
            file_path: Path to file to remove
        """
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            return {"success": False, "error": "File not found"}
        if not path.is_file():
            return {"success": False, "error": "Not a file"}
        try:
            path.unlink()
            return {"success": True, "path": str(path)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def remove_directory(
        ctx: RunContext[AgentDeps],
        directory: Annotated[str, "Directory to remove"],
        recursive: Annotated[bool, "Remove recursively"] = False,
    ) -> dict[str, Any]:
        """Remove a directory.

        Args:
            directory: Path to directory to remove
            recursive: Whether to remove recursively (delete contents)
        """
        path = Path(directory).expanduser().resolve()
        if not path.exists():
            return {"success": False, "error": "Directory not found"}
        if not path.is_dir():
            return {"success": False, "error": "Not a directory"}
        try:
            if recursive:
                import shutil
                shutil.rmtree(path)
            else:
                path.rmdir()
            return {"success": True, "path": str(path)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def get_home_directory(ctx: RunContext[AgentDeps]) -> str:
        """Get the current user's home directory."""
        return str(Path.home())

    @staticmethod
    async def get_desktop_directory(ctx: RunContext[AgentDeps]) -> str:
        """Get the current user's desktop directory."""
        home = Path.home()
        desktop_mac = home / "Desktop"
        desktop_windows = home / "Desktop"
        if desktop_mac.exists():
            return str(desktop_mac)
        if desktop_windows.exists():
            return str(desktop_windows)
        # Fallback
        return str(home / "Desktop")

    @staticmethod
    async def get_current_working_directory(ctx: RunContext[AgentDeps]) -> str:
        """Get the current working directory."""
        return str(Path.cwd())
