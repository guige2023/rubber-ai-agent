from pathlib import Path

from pydantic_ai.tools import RunContext

from app.core.deps import AgentDeps

class FileToolkit:
    """Tools for managing files within the session workspace."""

    @staticmethod
    def get_tools():
        return [FileToolkit.read_file, FileToolkit.write_file, FileToolkit.list_files]

    @staticmethod
    def _normalize_workspace_path(file_path: str) -> str:
        """Normalize agent-supplied paths so they stay rooted in the session workspace."""
        file_path = file_path.strip()
        for prefix in ("./",):
            file_path = file_path.removeprefix(prefix)
        return file_path or "."

    @staticmethod
    def resolve_session_path(kernel, session_id: str, raw_path: str) -> Path:
        """Resolve a user-supplied workspace-relative path into an absolute workspace path."""
        workspace_dir = kernel.get_session_workspace(session_id).resolve()
        normalized = FileToolkit._normalize_workspace_path(raw_path)
        candidate = (workspace_dir / normalized).resolve()

        try:
            candidate.relative_to(workspace_dir)
        except ValueError as exc:
            raise ValueError(f"Path escapes session workspace: {raw_path}") from exc

        return candidate

    @staticmethod
    async def read_file(ctx: RunContext[AgentDeps], file_path: str) -> str:
        """Read a file from the session workspace."""
        p = FileToolkit.resolve_session_path(ctx.deps.kernel, ctx.deps.session_id, file_path)
        if not p.exists():
            return f"Error: File not found: {file_path}"
        return p.read_text(encoding="utf-8")

    @staticmethod
    async def write_file(ctx: RunContext[AgentDeps], file_path: str, content: str) -> str:
        """Write content to a file in the session workspace."""
        normalized = FileToolkit._normalize_workspace_path(file_path)
        full_path = FileToolkit.resolve_session_path(ctx.deps.kernel, ctx.deps.session_id, file_path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} characters to {normalized}"

    @staticmethod
    async def list_files(ctx: RunContext[AgentDeps], directory: str = ".") -> str:
        """List files and directories in the session workspace."""
        p = FileToolkit.resolve_session_path(ctx.deps.kernel, ctx.deps.session_id, directory)
        if not p.exists():
            return f"Error: Directory not found: {directory}"
        entries = sorted(p.iterdir())
        return "\n".join(
            f"{'[DIR] ' if e.is_dir() else ''}{e.name}" for e in entries
        )
