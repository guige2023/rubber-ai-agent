from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.core.kernel import FerrymanKernel

@dataclass
class AgentDeps:
    kernel: "FerrymanKernel"
    session_id: str
    skill_name: Optional[str] = None
