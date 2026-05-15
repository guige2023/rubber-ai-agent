"""
Memory Consolidation - Background process for memory maintenance.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ConsolidationConfig:
    """Configuration for consolidation behavior."""

    l2_induction_threshold: int = 2  # Min episodes before policy induction
    l3_abstraction_threshold: int = 3  # Min policies before world model
    skill_crystallization_threshold: float = 0.8  # Min gain for skill
    idle_hours_before_consolidation: int = 168  # 7 days
    consolidation_interval_hours: int = 24  # Run consolidation every 24 hours


class MemoryConsolidation:
    """
    Background memory consolidation.

    Runs after idle periods to:
    - Induce L2 policies from L1 traces
    - Abstract L3 world models from L2 policies
    - Crystallize L4 skills from stable policies
    - Merge narrow skills into umbrella skills
    """

    def __init__(
        self,
        config: Optional[ConsolidationConfig] = None,
    ):
        self.config = config or ConsolidationConfig()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_consolidation: Optional[datetime] = None

    async def start(self) -> None:
        """Start the consolidation background task."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Memory consolidation started")

    async def stop(self) -> None:
        """Stop the consolidation background task."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Memory consolidation stopped")

    async def _run_loop(self) -> None:
        """Main consolidation loop."""
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in consolidation loop: {e}")

            # Wait for next check
            await asyncio.sleep(3600)  # Check every hour

    async def _tick(self) -> None:
        """Check if consolidation should run."""
        now = datetime.utcnow()

        # Check if enough time has passed since last consolidation
        if self._last_consolidation:
            hours_since = (now - self._last_consolidation).total_seconds() / 3600
            if hours_since < self.config.consolidation_interval_hours:
                return

        # Run consolidation
        await self.run_consolidation()

    async def run_consolidation(self) -> dict:
        """
        Run full memory consolidation.

        Returns:
            Summary of consolidation actions taken
        """
        logger.info("Starting memory consolidation")
        start_time = datetime.utcnow()

        summary = {
            "started_at": start_time.isoformat(),
            "policies_induced": 0,
            "world_models_created": 0,
            "skills_crystallized": 0,
            "skills_merged": 0,
            "errors": [],
        }

        try:
            # Step 1: L2 Policy Induction
            policies_induced = await self._induce_policies()
            summary["policies_induced"] = policies_induced

            # Step 2: L3 World Model Abstraction
            world_models_created = await self._abstract_world_models()
            summary["world_models_created"] = world_models_created

            # Step 3: Skill Crystallization
            skills_crystallized = await self._crystallize_skills()
            summary["skills_crystallized"] = skills_crystallized

            # Step 4: Skill Merging (Curator)
            skills_merged = await self._merge_narrow_skills()
            summary["skills_merged"] = skills_merged

            self._last_consolidation = datetime.utcnow()
            summary["completed_at"] = self._last_consolidation.isoformat()

        except Exception as e:
            logger.error(f"Consolidation error: {e}")
            summary["errors"].append(str(e))

        duration = (datetime.utcnow() - start_time).total_seconds()
        logger.info(
            f"Memory consolidation completed in {duration:.1f}s: "
            f"{summary['policies_induced']} policies, "
            f"{summary['world_models_created']} world models, "
            f"{summary['skills_crystallized']} skills, "
            f"{summary['skills_merged']} merged"
        )

        return summary

    async def _induce_policies(self) -> int:
        """
        Induce new L2 policies from L1 traces.

        When traces with the same signature appear in multiple episodes,
        we induce a policy capturing the successful strategy.
        """
        from .neo4j_client import get_neo4j_client
        from .l1_trace import TraceMemory
        from .l2_policy import PolicyMemory, Policy, PolicyStatus

        neo4j = get_neo4j_client()
        trace_mem = TraceMemory(neo4j)
        policy_mem = PolicyMemory(neo4j)

        # Find trace patterns (simplified - would need more sophisticated grouping)
        # This is a placeholder for the actual induction logic
        count = 0

        # In real implementation:
        # 1. Group traces by signature
        # 2. For each group with >= threshold episodes
        # 3. Generate policy via LLM induction
        # 4. Create policy node

        return count

    async def _abstract_world_models(self) -> int:
        """
        Abstract L3 world models from L2 policies.

        When enough related policies exist, create a world model
        capturing the environmental context.
        """
        count = 0
        # Placeholder implementation
        return count

    async def _crystallize_skills(self) -> int:
        """
        Crystallize stable policies into callable skills.

        When a policy reaches active status with sufficient gain,
        it can be crystallized into a skill.
        """
        from .l2_policy import PolicyMemory, PolicyStatus
        from .skill_crystal import SkillCrystal, CrystallizedSkill, SkillProvenance

        policy_mem = PolicyMemory()
        skill_crystal = SkillCrystal()

        # Get active policies with high gain
        policies = await policy_mem.get_active_policies(
            min_gain=self.config.skill_crystallization_threshold
        )

        count = 0
        for policy in policies:
            # Check if skill already exists for this policy
            # (Would need to check policy-to-skill mappings)

            # Create crystallized skill
            skill = CrystallizedSkill(
                name=f"skill-{policy.signature}",
                description=f"Auto-crystallized from policy {policy.id}",
                content=f"# {policy.primary_tag} / {policy.secondary_tag}\n\n{policy.strategy}",
                provenance=SkillProvenance.DERIVED,
                source_policy_ids=[policy.id],
            )

            try:
                await skill_crystal.create_skill(skill)
                count += 1
            except Exception as e:
                logger.error(f"Failed to crystallize skill: {e}")

        return count

    async def _merge_narrow_skills(self) -> int:
        """
        Merge narrow skills into umbrella skills (Curator function).

        This is the "class-level" consolidation from Hermes's Curator.
        Looks for skills that are narrow variants and should be merged.
        """
        count = 0
        # Placeholder - would need to:
        # 1. Find skills with similar names/purposes
        # 2. Group them as candidates
        # 3. Create umbrella skill
        # 4. Mark narrow ones as absorbed
        return count

    def get_status(self) -> dict:
        """Get consolidation status."""
        return {
            "running": self._running,
            "last_consolidation": (
                self._last_consolidation.isoformat()
                if self._last_consolidation
                else None
            ),
            "config": {
                "l2_induction_threshold": self.config.l2_induction_threshold,
                "l3_abstraction_threshold": self.config.l3_abstraction_threshold,
                "skill_crystallization_threshold": self.config.skill_crystallization_threshold,
                "idle_hours_before_consolidation": self.config.idle_hours_before_consolidation,
            },
        }
