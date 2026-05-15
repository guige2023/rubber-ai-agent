"""
Memory Manager - Coordinates all memory layers.
"""

import logging
from typing import Optional

from .neo4j_client import Neo4jClient, get_neo4j_client, init_neo4j
from .l1_trace import TraceMemory, TraceRecord
from .l2_policy import PolicyMemory, Policy, PolicyStatus
from .l3_world import WorldModelMemory, WorldModel
from .skill_crystal import SkillCrystal, CrystallizedSkill, SkillProvenance
from .retrieval import MemoryRetrieval, InjectionPacket, Tier, RetrievalResult
from .consolidation import MemoryConsolidation, ConsolidationConfig
from .embedding import EmbeddingService, get_embedding_service, init_embedding_service

logger = logging.getLogger(__name__)


class MemoryManager:
    """
    Main memory manager coordinating all memory layers.

    Provides a unified interface for:
    - Storing traces from agent execution
    - Retrieving context for agent prompts
    - Managing policy induction
    - Handling skill crystallization
    - Running consolidation
    """

    def __init__(
        self,
        neo4j_client: Optional[Neo4jClient] = None,
        embedding_service: Optional[EmbeddingService] = None,
        consolidation_config: Optional[ConsolidationConfig] = None,
    ):
        self._neo4j = neo4j_client
        self._embedding = embedding_service
        self._trace_memory: Optional[TraceMemory] = None
        self._policy_memory: Optional[PolicyMemory] = None
        self._world_memory: Optional[WorldModelMemory] = None
        self._skill_crystal: Optional[SkillCrystal] = None
        self._retrieval: Optional[MemoryRetrieval] = None
        self._consolidation: Optional[MemoryConsolidation] = None
        self._consolidation_config = consolidation_config
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize all memory components."""
        if self._initialized:
            return

        # Initialize Neo4j
        if self._neo4j is None:
            self._neo4j = await init_neo4j()
        else:
            if not self._neo4j.is_connected:
                await self._neo4j.connect()
                await self._neo4j.init_schema()

        # Initialize embedding service
        if self._embedding is None:
            self._embedding = await init_embedding_service()

        # Initialize sub-managers
        self._trace_memory = TraceMemory(self._neo4j)
        self._policy_memory = PolicyMemory(self._neo4j)
        self._world_memory = WorldModelMemory(self._neo4j)
        self._skill_crystal = SkillCrystal(self._neo4j)
        self._retrieval = MemoryRetrieval(self._neo4j, self._embedding)

        # Initialize consolidation
        self._consolidation = MemoryConsolidation(self._consolidation_config)

        self._initialized = True
        logger.info("MemoryManager initialized")

    async def shutdown(self) -> None:
        """Shutdown memory components."""
        if self._consolidation:
            await self._consolidation.stop()

        if self._neo4j and self._neo4j.is_connected:
            await self._neo4j.disconnect()

        self._initialized = False
        logger.info("MemoryManager shutdown")

    # ========== Trace Operations ==========

    async def add_trace(self, trace: TraceRecord) -> TraceRecord:
        """Add a new L1 trace record."""
        if not self._initialized:
            await self.initialize()
        return await self._trace_memory.add_trace(trace)

    async def get_traces_for_session(
        self,
        session_id: str,
        limit: int = 100,
    ) -> list[TraceRecord]:
        """Get traces for a session."""
        if not self._initialized:
            await self.initialize()
        return await self._trace_memory.get_traces_for_session(session_id, limit)

    # ========== Policy Operations ==========

    async def add_policy(self, policy: Policy) -> Policy:
        """Add a new L2 policy."""
        if not self._initialized:
            await self.initialize()
        return await self._policy_memory.add_policy(policy)

    async def get_active_policies(self, min_gain: float = 0.0) -> list[Policy]:
        """Get active policies above gain threshold."""
        if not self._initialized:
            await self.initialize()
        return await self._policy_memory.get_active_policies(min_gain)

    async def update_policy_status(
        self,
        policy_id: str,
        new_status: PolicyStatus,
        gain_delta: float = 0.0,
    ) -> bool:
        """Update a policy's status."""
        if not self._initialized:
            await self.initialize()
        return await self._policy_memory.update_policy_status(policy_id, new_status, gain_delta)

    # ========== Skill Operations ==========

    async def create_skill(self, skill: CrystallizedSkill) -> CrystallizedSkill:
        """Create a new crystallized skill."""
        if not self._initialized:
            await self.initialize()
        return await self._skill_crystal.create_skill(skill)

    async def get_skill(self, skill_id: str) -> Optional[CrystallizedSkill]:
        """Get a skill by ID."""
        if not self._initialized:
            await self.initialize()
        return await self._skill_crystal.get_skill(skill_id)

    async def get_skill_by_name(self, name: str) -> Optional[CrystallizedSkill]:
        """Get a skill by name."""
        if not self._initialized:
            await self.initialize()
        return await self._skill_crystal.get_by_name(name)

    async def record_skill_usage(
        self,
        skill_id: str,
        success: bool,
    ) -> bool:
        """Record skill usage and update reliability."""
        if not self._initialized:
            await self.initialize()
        return await self._skill_crystal.record_usage(skill_id, success)

    async def update_skill_content(
        self,
        skill_id: str,
        content: str,
    ) -> bool:
        """Update skill content (for agent self-improvement)."""
        if not self._initialized:
            await self.initialize()
        return await self._skill_crystal.update_content(skill_id, content)

    # ========== Retrieval Operations ==========

    async def retrieve(
        self,
        session_id: str,
        query: str,
    ) -> InjectionPacket:
        """
        Full Tier 1+2+3 retrieval.

        Called at start of user turn to inject memory context.
        """
        if not self._initialized:
            await self.initialize()
        return await self._retrieval.turn_start_retrieve(session_id, query)

    async def skill_invoke_retrieve(
        self,
        skill_name: str,
    ) -> Optional[RetrievalResult]:
        """Single skill retrieval for skill invocation."""
        if not self._initialized:
            await self.initialize()
        return await self._retrieval.skill_invoke_retrieve(skill_name)

    # ========== Consolidation Operations ==========

    async def start_consolidation(self) -> None:
        """Start background consolidation."""
        if not self._initialized:
            await self.initialize()
        await self._consolidation.start()

    async def run_consolidation(self) -> dict:
        """Run consolidation manually."""
        if not self._initialized:
            await self.initialize()
        return await self._consolidation.run_consolidation()

    # ========== World Model Operations ==========

    async def create_world_model(self, model: WorldModel) -> WorldModel:
        """Create a new L3 world model."""
        if not self._initialized:
            await self.initialize()
        return await self._world_memory.add_world_model(model)

    async def get_world_models_by_domain(
        self,
        domain_key: str,
    ) -> list[WorldModel]:
        """Get world models for a domain."""
        if not self._initialized:
            await self.initialize()
        return await self._world_memory.get_by_domain(domain_key)

    # ========== Status ==========

    def get_status(self) -> dict:
        """Get memory system status."""
        return {
            "initialized": self._initialized,
            "neo4j_connected": self._neo4j.is_connected if self._neo4j else False,
            "embedding_provider": self._embedding.provider if self._embedding else None,
            "embedding_dimensions": self._embedding.dimensions if self._embedding else None,
            "consolidation": self._consolidation.get_status() if self._consolidation else None,
        }
