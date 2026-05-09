import asyncio
import json
import shlex
import sys
from pathlib import Path
from typing import Annotated

from pydantic import BeforeValidator
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.tools import RunContext

from app.core.deps import AgentDeps, get_skill_manager, get_workspace
from app.core.toolkits.base import Toolkit


def _coerce_args(v: object) -> list[str] | None:
    """Coerce a JSON-encoded argument list into `list[str]`."""
    if v is None or isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (json.JSONDecodeError, ValueError):
            return v
    return v


def _parse_stdout(stdout: str) -> object:
    text = stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


class CommandToolkit(Toolkit):
    """Run scripts from the current skill's scripts directory."""

    @staticmethod
    def get_tools():
        return [CommandToolkit.run_skill_script]

    @staticmethod
    def _resolve_script_path(ctx: RunContext[AgentDeps], script_name: str) -> Path:
        """Resolve a script path under the current skill's `scripts/` directory."""
        skill_name = ctx.deps.skill_name
        if not skill_name:
            raise ModelRetry("run_skill_script is only available inside a skill execution context.")

        skill = get_skill_manager(ctx.deps).skills.get(skill_name)
        if not skill:
            raise ModelRetry(f"Current skill '{skill_name}' is not registered.")

        scripts_dir = skill.path / "scripts"
        candidate = (scripts_dir / script_name).resolve()
        try:
            candidate.relative_to(scripts_dir.resolve())
        except ValueError as exc:
            raise ModelRetry(f"Script path escapes skill scripts directory: {script_name}") from exc

        if not candidate.exists():
            raise ModelRetry(f"Script not found: {script_name}")
        if not candidate.is_file():
            raise ModelRetry(f"Script is not a file: {script_name}")
        return candidate

    @staticmethod
    def _build_command(script_path: Path, args: list[str]) -> list[str]:
        """Build the subprocess command for a script based on its file type."""
        if script_path.suffix == ".py":
            if getattr(sys, "frozen", False):
                return [sys.executable, "--run-python-script", str(script_path), *args]
            return [sys.executable, str(script_path), *args]
        if script_path.suffix == ".sh":
            return ["/bin/bash", str(script_path), *args]
        return [str(script_path), *args]

    @staticmethod
    async def run_skill_script(
        ctx: RunContext[AgentDeps],
        script_name: str,
        args: Annotated[list[str] | None, BeforeValidator(_coerce_args)] = None,
        timeout_ms: int = 60000,
    ) -> object:
        """Run a script from the current skill's `scripts/` directory.

        The script runs with the current session workspace as its working
        directory. Successful scripts return parsed stdout when it is JSON,
        plain stdout text otherwise, or None for empty stdout. Execution
        failures return a lightweight diagnostic object with the command,
        error, and any stdout result produced before failure.
        """
        resolved_args = args or []
        script_path = CommandToolkit._resolve_script_path(ctx, script_name)
        workspace_dir = get_workspace(ctx.deps)
        command = CommandToolkit._build_command(script_path, resolved_args)

        cmd = shlex.join(command)
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(workspace_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as e:
            return {
                "cmd": cmd,
                "error": str(e),
            }

        timed_out = False
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=max(timeout_ms, 1) / 1000,
            )
        except asyncio.TimeoutError:
            timed_out = True
            process.kill()
            stdout, stderr = await process.communicate()

        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")
        parsed_stdout = _parse_stdout(stdout_text)

        if process.returncode == 0 and not timed_out:
            return parsed_stdout

        if timed_out:
            error = f"Script timed out after {timeout_ms}ms."
        elif stderr_text.strip():
            error = stderr_text.strip()
        else:
            error = f"Script exited with code {process.returncode}."

        result: dict[str, object] = {
            "cmd": cmd,
            "error": error,
        }
        if parsed_stdout is not None:
            result["result"] = parsed_stdout
        return result
