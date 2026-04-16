import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional, Callable, Awaitable, Any
from uuid import uuid4

if TYPE_CHECKING:
    from app.core.kernel import FerrymanKernel

logger = logging.getLogger(__name__)


@dataclass
class AgentDeps:
    kernel: "FerrymanKernel"
    session_id: str
    skill_name: Optional[str] = None
    emit_event_cb: Optional[Callable[..., Awaitable[None]]] = None
    _tool_event_seq: int = field(default=0, init=False, repr=False)

    async def emit_tool_event(self, run_id: str, tool_name: str, phase: str, **kwargs: Any) -> None:
        if self.emit_event_cb:
            from app.models.events import FerrymanEventEnvelope, EventNamespace, ToolActivityPayload, ToolPhase
            self._tool_event_seq += 1
            event_id = uuid4().hex
            payload = ToolActivityPayload(
                run_id=run_id,
                event_id=event_id,
                seq=self._tool_event_seq,
                tool_name=tool_name,
                phase=ToolPhase(phase),
                **kwargs
            )
            event = FerrymanEventEnvelope(
                namespace=EventNamespace.AGENT,
                event="tool_activity",
                session_id=self.session_id,
                payload=payload
            )
            logger.debug({
                "message": {
                    "event": "tool_activity_emit",
                    "session_id": self.session_id,
                    "run_id": run_id,
                    "skill_name": self.skill_name,
                    "tool_name": tool_name,
                    "phase": phase,
                    "event_id": event_id,
                    "seq": self._tool_event_seq,
                }
            })
            await self.emit_event_cb(event)
