"""
Evolution Manager - Coordinates all self-evolution components.
"""

import asyncio
import logging
import re
from pathlib import Path
from typing import Optional

import frontmatter

from .nudge import NudgeEngine, NudgeConfig, NudgeSignal, NudgeType
from .background_review import BackgroundReviewer, ReviewTask
from .curator import Curator, CuratorConfig
from .skill_provenance import ProvenanceTracker, ProvenanceType
from app.core.config import Settings

logger = logging.getLogger(__name__)


class EvolutionManager:
    """
    Main self-evolution engine coordinating all components.

    Integrates:
    - NudgeEngine: Detects evolution signals
    - BackgroundReviewer: Runs isolated review tasks
    - Curator: Scheduled skill organization
    - ProvenanceTracker: Tracks skill history

    This is the core of Hermes-style self-improvement.
    """

    def __init__(
        self,
        nudge_config: Optional[NudgeConfig] = None,
        curator_config: Optional[CuratorConfig] = None,
        settings: Optional[Settings] = None,
    ):
        self._nudge_engine = NudgeEngine(nudge_config)
        self._background_reviewer = BackgroundReviewer()
        self._curator = Curator(curator_config)
        self._provenance_tracker = ProvenanceTracker()
        self._settings = settings or Settings()
        self._skill_manager = self._create_skill_manager()
        self._initialized = False
        self._evolution_handler: Optional[callable] = None

    def _create_skill_manager(self) -> "SkillManager":
        """Create and initialize the skill manager."""
        from app.core.skill_manager import SkillManager
        manager = SkillManager(self._settings)
        manager.scan_skills()
        return manager

    async def initialize(self) -> None:
        """Initialize all evolution components."""
        if self._initialized:
            return

        # Start background reviewer
        await self._background_reviewer.start()

        # Start curator
        await self._curator.start()

        # Set up background review handler
        self._background_reviewer.set_review_handler(self._on_review_task)

        self._initialized = True
        logger.info("EvolutionManager initialized")

    async def shutdown(self) -> None:
        """Shutdown all evolution components."""
        await self._background_reviewer.stop()
        await self._curator.stop()
        self._initialized = False
        logger.info("EvolutionManager shutdown")

    def set_evolution_handler(
        self,
        handler: callable,
    ) -> None:
        """
        Set the handler that performs evolution actions.

        The handler receives:
        - nudge_type: Type of evolution to perform
        - signals: Detected signals
        - context: Additional context

        Returns:
            Evolution result dict
        """
        self._evolution_handler = handler

    def set_skill_manager(self, skill_manager: "SkillManager") -> None:
        """
        Inject the shared SkillManager so evolution can write skills to the
        same registry used by the rest of the application.
        """
        self._skill_manager = skill_manager

    def on_user_turn(self) -> bool:
        """
        Called after each user turn.

        Returns:
            True if memory nudge should be triggered
        """
        return self._nudge_engine.on_user_turn()

    def on_tool_iteration(self) -> bool:
        """
        Called after each tool iteration.

        Returns:
            True if skill nudge should be triggered
        """
        return self._nudge_engine.on_tool_iteration()

    def detect_signals(
        self,
        user_message: str,
        agent_response: str,
        tool_calls: list[dict],
        errors_overcome: list[str] = None,
    ) -> list[NudgeSignal]:
        """
        Analyze conversation for evolution signals.

        Returns:
            List of detected signals
        """
        return self._nudge_engine.detect_signals(
            user_message=user_message,
            agent_response=agent_response,
            tool_calls=tool_calls,
            errors_overcome=errors_overcome,
        )

    async def process_signals(
        self,
        signals: list[NudgeSignal],
        session_context: dict,
    ) -> list[str]:
        """
        Process detected signals through evolution pipeline.

        Args:
            signals: Detected signals
            session_context: Current session context

        Returns:
            List of review task IDs
        """
        task_ids = []

        for signal in signals:
            if signal.confidence < self._nudge_engine.config.min_confidence_threshold:
                continue

            if signal.nudge_type == NudgeType.MEMORY_REVIEW:
                task_id = await self._submit_memory_review(signal, session_context)
                task_ids.append(task_id)

            elif signal.nudge_type in (
                NudgeType.SKILL_CREATION,
                NudgeType.SKILL_IMPROVEMENT,
            ):
                task_id = await self._submit_skill_review(signal, session_context)
                task_ids.append(task_id)

        return task_ids

    async def _submit_memory_review(
        self,
        signal: NudgeSignal,
        session_context: dict,
    ) -> str:
        """Submit a memory review task."""
        prompt = self._build_memory_review_prompt(signal, session_context)
        return await self._background_reviewer.submit_memory_review(
            session_context=session_context,
            memory_prompt=prompt,
        )

    async def _submit_skill_review(
        self,
        signal: NudgeSignal,
        session_context: dict,
    ) -> str:
        """Submit a skill review task."""
        prompt = self._build_skill_review_prompt(signal, session_context)
        return await self._background_reviewer.submit_skill_review(
            signals=[{"type": signal.nudge_type.value, "evidence": signal.evidence}],
            skill_prompt=prompt,
        )

    def _build_memory_review_prompt(
        self,
        signal: NudgeSignal,
        context: dict,
    ) -> str:
        """Build prompt for memory review."""
        return f"""Review recent conversation and extract information for memory:

Context: {context.get('summary', 'No context provided')}

Detected signal: {signal.evidence}

Please:
1. Extract user preferences and habits
2. Note any facts the user shared about themselves
3. Identify corrections the user made to agent behavior
4. Record any important context that should be remembered

Write findings to memory files (MEMORY.md and USER.md as appropriate).
"""

    def _build_skill_review_prompt(
        self,
        signal: NudgeSignal,
        context: dict,
    ) -> str:
        """Build prompt for skill review."""
        return f"""Review recent agent behavior and determine if a new or updated skill is needed:

Detected signal: {signal.evidence}
Confidence: {signal.confidence:.2f}
Context: {context.get('summary', 'No context provided')}

Please:
1. Analyze if this represents a pattern that should be captured as a skill
2. If yes, create or update the appropriate skill
3. If a new skill is needed, write SKILL.md
4. Consider if existing skills should be updated

Focus on skills that capture reusable patterns, not one-off responses.
"""

    def _on_review_task(self, task: ReviewTask) -> tuple[str, str]:
        """
        Handle a background review task.

        Returns:
            (result, error)
        """
        try:
            if self._evolution_handler:
                result = self._evolution_handler(
                    task.task_type,
                    task.prompt,
                    getattr(task, "context", {}),
                )
                return result, ""

            # Default handling: process skill_review tasks to create/update skills
            if task.task_type == "skill_review":
                return self._process_skill_review(task)

            return "Task processed (no specific handler)", ""

        except Exception as e:
            logger.error(f"Error in review task {task.id}: {e}")
            return "", str(e)

    def _process_skill_review(self, task: ReviewTask) -> tuple[str, str]:
        """
        Process a skill review task to create or update a skill.

        Args:
            task: The review task with skill_prompt

        Returns:
            (result, error)
        """
        try:
            # Parse skill info from the prompt
            skill_info = self._parse_skill_from_prompt(task.prompt)
            if not skill_info:
                return "", "Could not parse skill info from prompt"

            skill_name = skill_info.get("name", "").strip()
            skill_content = skill_info.get("content", "")

            if not skill_name or not skill_content:
                return "", "Missing skill name or content"

            # Check if skill already exists
            existing_skill = None
            for name, skill in self._skill_manager.skills.items():
                if name.lower() == skill_name.lower():
                    existing_skill = skill
                    break

            if existing_skill:
                # Update existing skill
                return self._update_skill(existing_skill, skill_content)
            else:
                # Create new skill
                return self._create_skill(skill_name, skill_content)

        except Exception as e:
            logger.error(f"Error processing skill review: {e}")
            return "", str(e)

    def _parse_skill_from_prompt(self, prompt: str) -> dict:
        """
        Parse skill information from the review prompt.

        Expected format in prompt:
        - Skill name somewhere in the text
        - Content to use for SKILL.md

        Returns:
            Dict with 'name' and 'content' keys, or empty dict if not found
        """
        # Try to extract skill name from prompt
        # Look for patterns like "skill name: X" or "# Skill Name"
        name_match = re.search(r"(?:skill name:|#)\s*(.+?)(?:\n|$)", prompt, re.IGNORECASE)
        skill_name = name_match.group(1).strip() if name_match else ""

        # Extract the main content (everything after "Please:" or similar)
        content_match = re.search(
            r"(?:Please|Consider):\s*(.+?)(?:\n\n|---\n|$$)",
            prompt,
            re.DOTALL | re.IGNORECASE
        )
        content = content_match.group(1).strip() if content_match else prompt

        # Clean up the content - remove signal evidence and confidence info
        content = re.sub(r"Detected signal:.*?(?=\n|$)", "", content, flags=re.DOTALL)
        content = re.sub(r"Confidence:.*?(?=\n|$)", "", content, flags=re.DOTALL)
        content = re.sub(r"Context:.*?(?=\n|$)", "", content, flags=re.DOTALL)
        content = content.strip()

        return {
            "name": skill_name,
            "content": content,
        }

    def _create_skill(self, name: str, content: str) -> tuple[str, str]:
        """
        Create a new skill file.

        Args:
            name: Skill name (will be used as directory name)
            content: Skill content

        Returns:
            (result, error)
        """
        try:
            # Create skill directory
            skill_dir = self._settings.skills_dir[0] / name.replace(" ", "-").lower()
            skill_dir.mkdir(parents=True, exist_ok=True)

            # Write SKILL.md
            skill_md_path = skill_dir / "SKILL.md"
            skill_md_path.write_text(content)

            # Reload skills to pick up the new one
            self._skill_manager.scan_skills()

            logger.info(f"Created new skill: {name} at {skill_dir}")
            return f"Created skill: {name}", ""

        except Exception as e:
            logger.error(f"Error creating skill {name}: {e}")
            return "", f"Failed to create skill: {e}"

    def _update_skill(self, existing_skill, new_content: str) -> tuple[str, str]:
        """
        Update an existing skill's content.

        Args:
            existing_skill: The SkillModel to update
            new_content: New content for the skill

        Returns:
            (result, error)
        """
        try:
            skill_path = existing_skill.path / "SKILL.md"

            # Parse existing frontmatter to preserve metadata
            try:
                post = frontmatter.load(str(skill_path))
                post.content = new_content
                skill_path.write_text(frontmatter.dumps(post))
            except Exception:
                # If parsing fails, just overwrite
                skill_path.write_text(new_content)

            # Reload skills
            self._skill_manager.scan_skills()

            logger.info(f"Updated skill: {existing_skill.name}")
            return f"Updated skill: {existing_skill.name}", ""

        except Exception as e:
            logger.error(f"Error updating skill {existing_skill.name}: {e}")
            return "", f"Failed to update skill: {e}"

    def record_activity(self) -> None:
        """Record activity to reset curator idle timer."""
        self._curator.record_activity()

    async def trigger_curator_now(self) -> dict:
        """Force curator to run now."""
        return await self._curator.run_now()

    def get_nudge_status(self) -> dict:
        """Get nudge engine status."""
        return self._nudge_engine.get_status()

    def get_reviewer_status(self) -> dict:
        """Get background reviewer status."""
        return self._background_reviewer.get_status()

    def get_curator_status(self) -> dict:
        """Get curator status."""
        return self._curator.get_status()

    def get_provenance_status(self) -> dict:
        """Get provenance tracker status."""
        return self._provenance_tracker.get_status()

    def get_status(self) -> dict:
        """Get overall evolution manager status."""
        return {
            "initialized": self._initialized,
            "nudge": self.get_nudge_status(),
            "reviewer": self.get_reviewer_status(),
            "curator": self.get_curator_status(),
            "provenance": self.get_provenance_status(),
        }
