"""
L1 Trace Memory - Step-level records of agent actions and observations.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .neo4j_client import Neo4jClient, get_neo4j_client

logger = logging.getLogger(__name__)


@dataclass
class TraceRecord:
    """A single step in an agent execution trace."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    run_id: str = ""
    action: str = ""  # What the agent did
    observation: str = ""  # What happened as a result
    reflection: str = ""  # Agent's self-reflection
    value: float = 0.0  # Computed value/reward
    embedding: Optional[list[float]] = None  # Vector representation
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "action": self.action,
            "observation": self.observation,
            "reflection": self.reflection,
            "value": self.value,
            "embedding": self.embedding,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }


class TraceMemory:
    """
    L1 Trace Memory - stores step-level records.

    Each trace captures:
    - Action: What the agent did
    - Observation: What happened
    - Reflection: Agent's self-assessment
    - Value: Computed reward/value
    """

    def __init__(self, client: Optional[Neo4jClient] = None):
        self._client = client

    @property
    def client(self) -> Neo4jClient:
        if self._client is None:
            self._client = get_neo4j_client()
        return self._client

    async def add_trace(self, trace: TraceRecord) -> TraceRecord:
        """
        Add a new trace record.

        Args:
            trace: TraceRecord to store

        Returns:
            The stored trace with any generated fields
        """
        query = """
        CREATE (t:Trace {
            id: $id,
            session_id: $session_id,
            run_id: $run_id,
            action: $action,
            observation: $observation,
            reflection: $reflection,
            value: $value,
            created_at: datetime($created_at),
            metadata: $metadata
        })
        RETURN t
        """

        params = {
            "id": trace.id,
            "session_id": trace.session_id,
            "run_id": trace.run_id,
            "action": trace.action,
            "observation": trace.observation,
            "reflection": trace.reflection,
            "value": trace.value,
            "created_at": trace.created_at.isoformat(),
            "metadata": str(trace.metadata),
        }

        await self.client.execute_write(query, params)

        # Create relationship to session
        if trace.session_id:
            session_query = """
            MATCH (s:Session {id: $session_id})
            MATCH (t:Trace {id: $trace_id})
            CREATE (t)-[:BELONGS_TO]->(s)
            """
            await self.client.execute_write(
                session_query,
                {"session_id": trace.session_id, "trace_id": trace.id},
            )

        logger.debug(f"Added trace {trace.id} for session {trace.session_id}")
        return trace

    async def get_traces_for_session(
        self,
        session_id: str,
        limit: int = 100,
    ) -> list[TraceRecord]:
        """
        Get traces for a session.

        Args:
            session_id: Session ID
            limit: Max number of traces to return

        Returns:
            List of TraceRecords
        """
        query = """
        MATCH (t:Trace)-[:BELONGS_TO]->(s:Session {id: $session_id})
        WHERE t.session_id = $session_id
        RETURN t
        ORDER BY t.created_at DESC
        LIMIT $limit
        """

        results = await self.client.execute_query(
            query,
            {"session_id": session_id, "limit": limit},
        )

        traces = []
        for record in results:
            t = record.get("t", {})
            traces.append(
                TraceRecord(
                    id=t.get("id", ""),
                    session_id=t.get("session_id", ""),
                    run_id=t.get("run_id", ""),
                    action=t.get("action", ""),
                    observation=t.get("observation", ""),
                    reflection=t.get("reflection", ""),
                    value=float(t.get("value", 0.0)),
                    created_at=datetime.fromisoformat(t.get("created_at", datetime.utcnow().isoformat())),
                    metadata={},
                )
            )
        return traces

    async def search_by_value(
        self,
        min_value: float = 0.0,
        limit: int = 50,
    ) -> list[TraceRecord]:
        """
        Search traces by minimum value.

        Args:
            min_value: Minimum value threshold
            limit: Max results

        Returns:
            High-value traces
        """
        query = """
        MATCH (t:Trace)
        WHERE t.value >= $min_value
        RETURN t
        ORDER BY t.value DESC
        LIMIT $limit
        """

        results = await self.client.execute_query(
            query,
            {"min_value": min_value, "limit": limit},
        )

        traces = []
        for record in results:
            t = record.get("t", {})
            traces.append(
                TraceRecord(
                    id=t.get("id", ""),
                    session_id=t.get("session_id", ""),
                    action=t.get("action", ""),
                    observation=t.get("observation", ""),
                    value=float(t.get("value", 0.0)),
                )
            )
        return traces

    async def count_traces(self) -> int:
        """Count total traces."""
        query = "MATCH (t:Trace) RETURN count(t) as count"
        results = await self.client.execute_query(query)
        return results[0].get("count", 0) if results else 0
