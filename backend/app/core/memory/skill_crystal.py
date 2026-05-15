"""
Skill Crystal - Crystallized callable capabilities from policy.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from .neo4j_client import Neo4jClient, get_neo4j_client

logger = logging.getLogger(__name__)


class SkillProvenance(str, Enum):
    """Who/what created the skill."""

    AGENT = "agent"  # Created by the agent itself
    HUMAN = "human"  # Created by a human
    BUNDLED = "bundled"  # Bundled with the system
    DERIVED = "derived"  # Derived from another skill


@dataclass
class CrystallizedSkill:
    """
    A crystallized skill - callable capability derived from policies.

    Skills are the highest level of memory abstraction,
    representing reusable capabilities the agent can invoke directly.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    content: str = ""  # Full SKILL.md content
    eta: float = 1.0  # Reliability score (0-1, Beta distribution)
    usage_count: int = 0
    success_count: int = 0
    provenance: SkillProvenance = SkillProvenance.AGENT
    source_policy_ids: list[str] = field(default_factory=list)
    absorbed_skills: list[str] = field(default_factory=list)  # Skills merged into this one
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict = field(default_factory=dict)

    @property
    def reliability(self) -> float:
        """Compute reliability score from Beta distribution."""
        if self.usage_count == 0:
            return 0.5  # Prior
        # Beta posterior: (success + 1) / (usage + 2)
        return (self.success_count + 1) / (self.usage_count + 2)


class SkillCrystal:
    """
    Skill Crystal - manages crystallized skills.

    Skills are created when:
    - A policy becomes stable and reliable
    - Multiple related policies can be combined
    - An agent autonomously creates one based on user feedback
    """

    def __init__(self, client: Optional[Neo4jClient] = None):
        self._client = client

    @property
    def client(self) -> Neo4jClient:
        if self._client is None:
            self._client = get_neo4j_client()
        return self._client

    async def create_skill(self, skill: CrystallizedSkill) -> CrystallizedSkill:
        """Create a new crystallized skill."""
        query = """
        CREATE (s:CrystallizedSkill {
            id: $id,
            name: $name,
            description: $description,
            content: $content,
            eta: $eta,
            usage_count: $usage_count,
            success_count: $success_count,
            provenance: $provenance,
            source_policy_ids: $source_policy_ids,
            absorbed_skills: $absorbed_skills,
            created_at: datetime($created_at),
            updated_at: datetime($updated_at),
            metadata: $metadata
        })
        RETURN s
        """

        params = {
            "id": skill.id,
            "name": skill.name,
            "description": skill.description,
            "content": skill.content,
            "eta": skill.eta,
            "usage_count": skill.usage_count,
            "success_count": skill.success_count,
            "provenance": skill.provenance.value,
            "source_policy_ids": str(skill.source_policy_ids),
            "absorbed_skills": str(skill.absorbed_skills),
            "created_at": skill.created_at.isoformat(),
            "updated_at": skill.updated_at.isoformat(),
            "metadata": str(skill.metadata),
        }

        await self.client.execute_write(query, params)

        # Link to source policies
        for policy_id in skill.source_policy_ids:
            rel_query = """
            MATCH (s:CrystallizedSkill {id: $skill_id})
            MATCH (p:Policy {id: $policy_id})
            CREATE (s)-[:CRYSTALLIZED_FROM]->(p)
            """
            await self.client.execute_write(
                rel_query,
                {"skill_id": skill.id, "policy_id": policy_id},
            )

        logger.info(f"Created crystallized skill {skill.name} ({skill.id})")
        return skill

    async def get_skill(self, skill_id: str) -> Optional[CrystallizedSkill]:
        """Get a skill by ID."""
        query = """
        MATCH (s:CrystallizedSkill {id: $id})
        RETURN s
        """

        results = await self.client.execute_query(query, {"id": skill_id})
        if not results:
            return None

        s = results[0].get("s", {})
        return self._record_to_skill(s)

    async def get_by_name(self, name: str) -> Optional[CrystallizedSkill]:
        """Get a skill by name."""
        query = """
        MATCH (s:CrystallizedSkill {name: $name})
        RETURN s
        """

        results = await self.client.execute_query(query, {"name": name})
        if not results:
            return None

        s = results[0].get("s", {})
        return self._record_to_skill(s)

    async def get_reliable_skills(self, min_eta: float = 0.7) -> list[CrystallizedSkill]:
        """Get skills above reliability threshold (for Tier 1 retrieval)."""
        query = """
        MATCH (s:CrystallizedSkill)
        WHERE s.eta >= $min_eta
        RETURN s
        ORDER BY s.eta DESC
        """

        results = await self.client.execute_query(query, {"min_eta": min_eta})

        skills = []
        for record in results:
            s = record.get("s", {})
            skills.append(self._record_to_skill(s))
        return skills

    async def record_usage(
        self,
        skill_id: str,
        success: bool,
    ) -> bool:
        """Record skill usage and update reliability."""
        query = """
        MATCH (s:CrystallizedSkill {id: $id})
        SET s.usage_count = s.usage_count + 1,
            s.success_count = s.success_count + $success_delta,
            s.eta = (s.success_count + 1.0) / (s.usage_count + 2.0),
            s.updated_at = datetime()
        RETURN s
        """

        result = await self.client.execute_write(
            query,
            {"id": skill_id, "success_delta": 1 if success else 0},
        )

        return result.get("counters", {}).get("properties_set", 0) > 0

    async def absorb_skill(
        self,
        source_id: str,
        target_id: str,
    ) -> bool:
        """
        Absorb one skill into another (for curator consolidation).

        The source skill is deleted and marked as absorbed into target.
        """
        query = """
        MATCH (source:CrystallizedSkill {id: $source_id})
        MATCH (target:CrystallizedSkill {id: $target_id})
        SET target.absorbed_skills = target.absorbed_skills + $source_name,
            target.updated_at = datetime()
        WITH source
        DETACH DELETE source
        """

        # Get source name first
        source = await self.get_skill(source_id)
        if not source:
            return False

        try:
            await self.client.execute_write(
                query,
                {"source_id": source_id, "target_id": target_id, "source_name": source.name},
            )
            logger.info(f"Absorbed skill {source.name} into {target_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to absorb skill: {e}")
            return False

    async def update_content(
        self,
        skill_id: str,
        content: str,
    ) -> bool:
        """Update skill content (for agent self-improvement)."""
        query = """
        MATCH (s:CrystallizedSkill {id: $id})
        SET s.content = $content,
            s.updated_at = datetime()
        """

        result = await self.client.execute_write(
            query,
            {"id": skill_id, "content": content},
        )

        return result.get("counters", {}).get("properties_set", 0) > 0

    def _record_to_skill(self, record: dict) -> CrystallizedSkill:
        """Convert Neo4j record to CrystallizedSkill."""
        return CrystallizedSkill(
            id=record.get("id", ""),
            name=record.get("name", ""),
            description=record.get("description", ""),
            content=record.get("content", ""),
            eta=float(record.get("eta", 1.0)),
            usage_count=int(record.get("usage_count", 0)),
            success_count=int(record.get("success_count", 0)),
            provenance=SkillProvenance(record.get("provenance", SkillProvenance.AGENT.value)),
            created_at=datetime.fromisoformat(record.get("created_at", datetime.utcnow().isoformat())),
            updated_at=datetime.fromisoformat(record.get("updated_at", datetime.utcnow().isoformat())),
        )
