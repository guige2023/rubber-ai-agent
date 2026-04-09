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
        for prefix in ("./",):
            file_path = file_path.removeprefix(prefix)
        return file_path

    @staticmethod
    async def read_file(ctx: RunContext[AgentDeps], file_path: str) -> str:
        """Read a file from the session workspace."""
        kernel = ctx.deps.kernel
        base_dir = kernel.get_session_workspace(ctx.deps.session_id)
        p = base_dir / FileToolkit._normalize_workspace_path(file_path)
        if not p.exists():
            return f"Error: File not found: {file_path}"
        return p.read_text(encoding="utf-8")

    @staticmethod
    async def write_file(ctx: RunContext[AgentDeps], file_path: str, content: str) -> str:
        """Write content to a file in the session workspace."""
        kernel = ctx.deps.kernel
        base_dir = kernel.get_session_workspace(ctx.deps.session_id)
        normalized = FileToolkit._normalize_workspace_path(file_path)
        full_path = base_dir / normalized
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} characters to {normalized}"

    @staticmethod
    async def list_files(ctx: RunContext[AgentDeps], directory: str = ".") -> str:
        """List files and directories in the session workspace."""
        kernel = ctx.deps.kernel
        base_dir = kernel.get_session_workspace(ctx.deps.session_id)
        p = base_dir / FileToolkit._normalize_workspace_path(directory)
        if not p.exists():
            return f"Error: Directory not found: {directory}"
        entries = sorted(p.iterdir())
        return "\n".join(
            f"{'[DIR] ' if e.is_dir() else ''}{e.name}" for e in entries
        )
