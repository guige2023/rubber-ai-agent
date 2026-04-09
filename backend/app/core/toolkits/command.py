import asyncio
import json
import os
import sys
from pathlib import Path
from typing import List

from pydantic_ai.tools import RunContext

from app.core.deps import AgentDeps


class CommandToolkit:
    """Run scripts from the current skill's scripts directory."""

    @staticmethod
    def get_tools():
        return [CommandToolkit.run_skill_script]

    @staticmethod
    def _resolve_script_path(ctx: RunContext[AgentDeps], script_name: str) -> Path:
        skill_name = ctx.deps.skill_name
        if not skill_name:
            raise RuntimeError("run_skill_script is only available inside a skill execution context.")

        skill = ctx.deps.kernel.skills.get(skill_name)
        if not skill:
            raise RuntimeError(f"Current skill '{skill_name}' is not registered.")

        scripts_dir = skill.path / "scripts"
        candidate = (scripts_dir / script_name).resolve()
        try:
            candidate.relative_to(scripts_dir.resolve())
        except ValueError as exc:
            raise RuntimeError(f"Script path escapes skill scripts directory: {script_name}") from exc

        if not candidate.exists():
            raise RuntimeError(f"Script not found: {script_name}")
        if not candidate.is_file():
            raise RuntimeError(f"Script is not a file: {script_name}")
        return candidate

    @staticmethod
    def _build_command(script_path: Path, args: List[str]) -> List[str]:
        if script_path.suffix == ".py":
            return [sys.executable, str(script_path), *args]
        if script_path.suffix == ".sh":
            return ["/bin/bash", str(script_path), *args]
        return [str(script_path), *args]

    @staticmethod
    async def run_skill_script(
        ctx: RunContext[AgentDeps],
        script_name: str,
        args: List[str] | None = None,
        timeout_ms: int = 10000,
    ) -> str:
        """
        Run a script from the current skill's `scripts/` directory.
        The script runs with cwd set to the current session workspace.
        """
        resolved_args = args or []
        script_path = CommandToolkit._resolve_script_path(ctx, script_name)
        workspace_dir = ctx.deps.kernel.get_session_workspace(ctx.deps.session_id)
        command = CommandToolkit._build_command(script_path, resolved_args)

        env = os.environ.copy()
        env.update(
            {
                "FERRYMAN_SESSION_ID": ctx.deps.session_id,
                "FERRYMAN_WORKSPACE_DIR": str(workspace_dir),
                "FERRYMAN_SKILL_NAME": ctx.deps.skill_name or "",
                "FERRYMAN_SKILL_DIR": str(script_path.parent.parent),
            }
        )

        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(workspace_dir),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

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

        result = {
            "ok": process.returncode == 0 and not timed_out,
            "script_name": script_name,
            "command": command,
            "cwd": str(workspace_dir),
            "exit_code": process.returncode,
            "timed_out": timed_out,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
        }
        return json.dumps(result, ensure_ascii=False)
