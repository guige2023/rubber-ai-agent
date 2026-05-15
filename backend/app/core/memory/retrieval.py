"""
Memory Retrieval - Tier-based memory recall system.
"""

import logging
import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .neo4j_client import Neo4jClient, get_neo4j_client
from .l1_trace import TraceMemory
from .l2_policy import PolicyMemory, PolicyStatus
from .l3_world import WorldModelMemory
from .skill_crystal import SkillCrystal
from .embedding import EmbeddingService, get_embedding_service

logger = logging.getLogger(__name__)


class Tier(str, Enum):
    """Retrieval tier levels."""

    TIER_1 = "tier_1"  # Skills (crystallized)
    TIER_2 = "tier_2"  # Traces and episodes
    TIER_3 = "tier_3"  # World models


@dataclass
class RetrievalResult:
    """A single retrieval result."""

    tier: Tier
    content: str
    score: float
    metadata: dict


@dataclass
class InjectionPacket:
    """Collection of retrieved items for injection into agent context."""

    tier_1_skills: list[RetrievalResult]  # Skills to include
    tier_2_traces: list[RetrievalResult]  # High-value traces
    tier_3_world: list[RetrievalResult]  # World model context
    total_tokens_estimate: int = 0


class MemoryRetrieval:
    """
    Tier-based memory retrieval.

    Retrieval happens in 3 tiers:
    - Tier 1: Skills with high reliability (η ≥ min_eta)
    - Tier 2: Traces and episodes based on value and relevance
    - Tier 3: World models for environmental context
    """

    def __init__(
        self,
        neo4j_client: Optional[Neo4jClient] = None,
        embedding_service: Optional[EmbeddingService] = None,
    ):
        self._neo4j = neo4j_client
        self._embedding = embedding_service
        self._trace_memory: Optional[TraceMemory] = None
        self._policy_memory: Optional[PolicyMemory] = None
        self._world_memory: Optional[WorldModelMemory] = None
        self._skill_crystal: Optional[SkillCrystal] = None

    @property
    def neo4j(self) -> Neo4jClient:
        if self._neo4j is None:
            self._neo4j = get_neo4j_client()
        return self._neo4j

    @property
    def embedding(self) -> EmbeddingService:
        if self._embedding is None:
            self._embedding = get_embedding_service()
        return self._embedding

    @property
    def trace_memory(self) -> TraceMemory:
        if self._trace_memory is None:
            self._trace_memory = TraceMemory(self.neo4j)
        return self._trace_memory

    @property
    def policy_memory(self) -> PolicyMemory:
        if self._policy_memory is None:
            self._policy_memory = PolicyMemory(self.neo4j)
        return self._policy_memory

    @property
    def world_memory(self) -> WorldModelMemory:
        if self._world_memory is None:
            self._world_memory = WorldModelMemory(self.neo4j)
        return self._world_memory

    @property
    def skill_crystal(self) -> SkillCrystal:
        if self._skill_crystal is None:
            self._skill_crystal = SkillCrystal(self.neo4j)
        return self._skill_crystal

    async def turn_start_retrieve(
        self,
        session_id: str,
        query: str,
        min_skill_eta: float = 0.7,
        max_traces: int = 10,
        max_world_models: int = 3,
    ) -> InjectionPacket:
        """
        Full Tier 1+2+3 retrieval at start of user turn.

        This is the main entry point for retrieval, called when
        a new user message arrives.
        """
        # Query embedding
        query_embedding = await self.embedding.embed(query, role="query")

        # Tier 1: Skills
        tier_1_skills = await self._retrieve_tier_1_skills(min_skill_eta)

        # Tier 2: Traces
        tier_2_traces = await self._retrieve_tier_2_traces(
            session_id, query_embedding, max_traces
        )

        # Tier 3: World Models
        tier_3_world = await self._retrieve_tier_3_world(
            session_id, query_embedding, max_world_models
        )

        # Estimate tokens
        total_tokens = self._estimate_tokens(
            tier_1_skills + tier_2_traces + tier_3_world
        )

        return InjectionPacket(
            tier_1_skills=tier_1_skills,
            tier_2_traces=tier_2_traces,
            tier_3_world=tier_3_world,
            total_tokens_estimate=total_tokens,
        )

    async def tool_driven_retrieve(
        self,
        session_id: str,
        query: str,
        max_traces: int = 5,
    ) -> list[RetrievalResult]:
        """
        Tier 1+2 retrieval when agent calls memory_search tool.

        Used when the agent explicitly requests memory context.
        """
        query_embedding = await self.embedding.embed(query, role="query")

        # Skills with lower threshold since agent is asking
        skills = await self._retrieve_tier_1_skills(min_eta=0.5)

        # Traces
        traces = await self._retrieve_tier_2_traces(
            session_id, query_embedding, max_traces
        )

        return skills + traces

    async def skill_invoke_retrieve(
        self,
        skill_name: str,
    ) -> Optional[RetrievalResult]:
        """
        Single skill retrieval for skill invocation.

        Returns the skill content if found.
        """
        skill = await self.skill_crystal.get_by_name(skill_name)
        if not skill:
            return None

        return RetrievalResult(
            tier=Tier.TIER_1,
            content=skill.content,
            score=skill.eta,
            metadata={
                "skill_id": skill.id,
                "name": skill.name,
                "provenance": skill.provenance.value,
            },
        )

    async def _retrieve_tier_1_skills(
        self,
        min_eta: float,
    ) -> list[RetrievalResult]:
        """Retrieve reliable skills (Tier 1)."""
        skills = await self.skill_crystal.get_reliable_skills(min_eta)

        results = []
        for skill in skills:
            results.append(
                RetrievalResult(
                    tier=Tier.TIER_1,
                    content=skill.content,
                    score=skill.eta,
                    metadata={
                        "skill_id": skill.id,
                        "name": skill.name,
                        "description": skill.description,
                        "provenance": skill.provenance.value,
                    },
                )
            )
        return results

    async def _retrieve_tier_2_traces(
        self,
        session_id: str,
        query_embedding: list[float],
        max_results: int,
    ) -> list[RetrievalResult]:
        """Retrieve high-value traces (Tier 2)."""
        # Get traces for session
        traces = await self.trace_memory.get_traces_for_session(session_id, limit=100)

        if not traces:
            return []

        # Score by value + cosine similarity
        scored_traces = []
        for trace in traces:
            # Combine value score with embedding similarity if available
            value_score = trace.value
            embedding_score = 0.0

            if trace.embedding:
                embedding_score = self._cosine_similarity(query_embedding, trace.embedding)

            # Weighted combination
            combined_score = 0.7 * value_score + 0.3 * embedding_score

            scored_traces.append((combined_score, trace))

        # Sort and take top results
        scored_traces.sort(key=lambda x: x[0], reverse=True)
        top_traces = scored_traces[:max_results]

        results = []
        for score, trace in top_traces:
            results.append(
                RetrievalResult(
                    tier=Tier.TIER_2,
                    content=f"Action: {trace.action}\nObservation: {trace.observation}\nReflection: {trace.reflection}",
                    score=score,
                    metadata={
                        "trace_id": trace.id,
                        "value": trace.value,
                        "created_at": trace.created_at.isoformat(),
                    },
                )
            )
        return results

    async def _retrieve_tier_3_world(
        self,
        session_id: str,
        query_embedding: list[float],
        max_results: int,
    ) -> list[RetrievalResult]:
        """Retrieve world models (Tier 3)."""
        # Get high confidence world models
        world_models = await self.world_memory.get_high_confidence(min_confidence=0.5)

        if not world_models:
            return []

        # Score by confidence
        scored_models = []
        for wm in world_models:
            scored_models.append((wm.confidence, wm))

        scored_models.sort(key=lambda x: x[0], reverse=True)
        top_models = scored_models[:max_results]

        results = []
        for confidence, wm in top_models:
            content = f"Environment: {wm.environment}\nRules: {wm.inference_rules}\nConstraints: {wm.constraints}"
            results.append(
                RetrievalResult(
                    tier=Tier.TIER_3,
                    content=content,
                    score=confidence,
                    metadata={
                        "worldmodel_id": wm.id,
                        "domain_key": wm.domain_key,
                    },
                )
            )
        return results

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if len(a) != len(b):
            return 0.0

        dot_product = sum(x * y for x, y in zip(a, b))
        magnitude_a = math.sqrt(sum(x * x for x in a))
        magnitude_b = math.sqrt(sum(x * x for x in b))

        if magnitude_a == 0 or magnitude_b == 0:
            return 0.0

        return dot_product / (magnitude_a * magnitude_b)

    @staticmethod
    def _estimate_tokens(results: list[RetrievalResult]) -> int:
        """Rough estimate of tokens in results."""
        # Rough estimate: 4 chars per token
        total_chars = sum(len(r.content) for r in results)
        return total_chars // 4
