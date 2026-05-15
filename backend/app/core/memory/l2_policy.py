"""
L2 Policy Memory - Sub-task strategy induction from traces.
"""

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from .neo4j_client import Neo4jClient, get_neo4j_client

logger = logging.getLogger(__name__)


class PolicyStatus(str, Enum):
    """Policy lifecycle status."""

    CANDIDATE = "candidate"
    ACTIVE = "active"
    RETIRED = "retired"


@dataclass
class Policy:
    """
    Induced policy from multiple traces.

    A policy captures a reusable strategy for handling
    a particular type of task or error pattern.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    signature: str = ""  # Pattern hash for grouping
    primary_tag: str = ""  # Primary category
    secondary_tag: str = ""  # Secondary category
    strategy: str = ""  # The induced strategy
    gain: float = 0.0  # Effectiveness measure
    status: PolicyStatus = PolicyStatus.CANDIDATE
    episode_count: int = 0  # Number of episodes that contributed
    episode_ids: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict = field(default_factory=dict)

    @staticmethod
    def compute_signature(
        primary_tag: str,
        secondary_tag: str,
        tool_name: str = "",
        error_code: str = "",
    ) -> str:
        """
        Compute a signature hash for policy bucketing.

        Format: primary_tag|secondary_tag|tool_name|error_code
        """
        parts = [primary_tag, secondary_tag, tool_name, error_code]
        sig_str = "|".join(parts)
        return hashlib.md5(sig_str.encode()).hexdigest()[:16]


class PolicyMemory:
    """
    L2 Policy Memory - induces and manages policies from traces.

    Policy induction happens when the same signature appears
    across multiple episodes, indicating a reusable strategy.
    """

    def __init__(self, client: Optional[Neo4jClient] = None):
        self._client = client
        self._induction_threshold = 2  # Min episodes before induction

    @property
    def client(self) -> Neo4jClient:
        if self._client is None:
            self._client = get_neo4j_client()
        return self._client

    async def add_policy(self, policy: Policy) -> Policy:
        """Add a new policy."""
        query = """
        CREATE (p:Policy {
            id: $id,
            signature: $signature,
            primary_tag: $primary_tag,
            secondary_tag: $secondary_tag,
            strategy: $strategy,
            gain: $gain,
            status: $status,
            episode_count: $episode_count,
            episode_ids: $episode_ids,
            created_at: datetime($created_at),
            updated_at: datetime($updated_at),
            metadata: $metadata
        })
        RETURN p
        """

        params = {
            "id": policy.id,
            "signature": policy.signature,
            "primary_tag": policy.primary_tag,
            "secondary_tag": policy.secondary_tag,
            "strategy": policy.strategy,
            "gain": policy.gain,
            "status": policy.status.value,
            "episode_count": policy.episode_count,
            "episode_ids": str(policy.episode_ids),
            "created_at": policy.created_at.isoformat(),
            "updated_at": policy.updated_at.isoformat(),
            "metadata": str(policy.metadata),
        }

        await self.client.execute_write(query, params)
        logger.info(f"Created policy {policy.id} with signature {policy.signature}")
        return policy

    async def get_policies_by_signature(
        self,
        signature: str,
        status: Optional[PolicyStatus] = None,
    ) -> list[Policy]:
        """Get policies matching a signature."""
        if status:
            query = """
            MATCH (p:Policy {signature: $signature, status: $status})
            RETURN p
            ORDER BY p.gain DESC
            """
            params = {"signature": signature, "status": status.value}
        else:
            query = """
            MATCH (p:Policy {signature: $signature})
            RETURN p
            ORDER BY p.gain DESC
            """
            params = {"signature": signature}

        results = await self.client.execute_query(query, params)

        policies = []
        for record in results:
            p = record.get("p", {})
            policies.append(
                Policy(
                    id=p.get("id", ""),
                    signature=p.get("signature", ""),
                    primary_tag=p.get("primary_tag", ""),
                    secondary_tag=p.get("secondary_tag", ""),
                    strategy=p.get("strategy", ""),
                    gain=float(p.get("gain", 0.0)),
                    status=PolicyStatus(p.get("status", PolicyStatus.CANDIDATE.value)),
                    episode_count=int(p.get("episode_count", 0)),
                    created_at=datetime.fromisoformat(p.get("created_at", datetime.utcnow().isoformat())),
                )
            )
        return policies

    async def get_active_policies(self, min_gain: float = 0.0) -> list[Policy]:
        """Get all active policies above gain threshold."""
        query = """
        MATCH (p:Policy)
        WHERE p.status = $status AND p.gain >= $min_gain
        RETURN p
        ORDER BY p.gain DESC
        """

        results = await self.client.execute_query(
            query,
            {"status": PolicyStatus.ACTIVE.value, "min_gain": min_gain},
        )

        policies = []
        for record in results:
            p = record.get("p", {})
            policies.append(
                Policy(
                    id=p.get("id", ""),
                    signature=p.get("signature", ""),
                    primary_tag=p.get("primary_tag", ""),
                    secondary_tag=p.get("secondary_tag", ""),
                    strategy=p.get("strategy", ""),
                    gain=float(p.get("gain", 0.0)),
                    status=PolicyStatus.ACTIVE,
                    episode_count=int(p.get("episode_count", 0)),
                )
            )
        return policies

    async def update_policy_status(
        self,
        policy_id: str,
        new_status: PolicyStatus,
        gain_delta: float = 0.0,
    ) -> bool:
        """Update a policy's status and optionally adjust gain."""
        query = """
        MATCH (p:Policy {id: $id})
        SET p.status = $status,
            p.gain = p.gain + $gain_delta,
            p.updated_at = datetime()
        RETURN p
        """

        result = await self.client.execute_write(
            query,
            {
                "id": policy_id,
                "status": new_status.value,
                "gain_delta": gain_delta,
            },
        )

        return result.get("counters", {}).get("properties_set", 0) > 0

    async def merge_policy_episodes(
        self,
        policy_id: str,
        new_episode_ids: list[str],
    ) -> bool:
        """Merge additional episodes into a policy."""
        query = """
        MATCH (p:Policy {id: $id})
        SET p.episode_ids = p.episode_ids + $new_episodes,
            p.episode_count = size(p.episode_ids),
            p.updated_at = datetime()
        RETURN p
        """

        result = await self.client.execute_write(
            query,
            {"id": policy_id, "new_episodes": str(new_episode_ids)},
        )

        return result.get("counters", {}).get("properties_set", 0) > 0

    async def count_by_status(self, status: PolicyStatus) -> int:
        """Count policies by status."""
        query = """
        MATCH (p:Policy {status: $status})
        RETURN count(p) as count
        """
        results = await self.client.execute_query(
            query,
            {"status": status.value},
        )
        return results[0].get("count", 0) if results else 0
