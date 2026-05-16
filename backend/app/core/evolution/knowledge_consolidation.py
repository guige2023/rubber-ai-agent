"""
P1-EVOL-3: KnowledgeConsolidationEngine

Consolidates scattered experiences from the agent's memory and failure history
into durable, structured knowledge in the agent's skill system.

Based on Hermes-style "knowledge consolidation" — experiences become skills,
patterns become policies.

Usage:
    consolidation = KnowledgeConsolidation()
    await consolidation.run_now()  # Force immediate consolidation
    await consolidation.consolidate_session(session_id)  # After session ends
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from app.core.evolution.failure_learning import FailureLearningEngine

logger = logging.getLogger(__name__)


# ── What to consolidate ───────────────────────────────────────────────────

@dataclass
class KnowledgeFragment:
    """A piece of knowledge extracted from an experience."""
    source: str  # "conversation" | "failure_record" | "tool_result" | "user_feedback"
    session_id: str
    title: str  # Short title for this knowledge
    content: str  # The actual knowledge content
    confidence: float  # 0-1
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)


# ── Consolidation engine ─────────────────────────────────────────────────

class KnowledgeConsolidation:
    """
    Consolidates agent experiences into durable knowledge.

    Runs on:
    - Session end (conversation patterns → memory)
    - Periodic intervals (7 days idle → full consolidation)
    - Explicit trigger (curator → run_now)

    Outputs:
    - Updates to MEMORY.md / USER.md (personal facts)
    - New or updated skills (reusable patterns)
    - Failure avoidances (from FailureLearningEngine)
    """

    _instance: "KnowledgeConsolidation | None" = None

    @classmethod
    def get_instance(cls) -> "KnowledgeConsolidation":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._running = False
        self._consolidation_task: asyncio.Task | None = None
        self._interval_hours = 24  # Run consolidation at most once per day

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._consolidation_task = asyncio.create_task(self._background_consolidation())
        logger.info("KnowledgeConsolidation started")

    async def shutdown(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._consolidation_task:
            self._consolidation_task.cancel()
            try:
                await self._consolidation_task
            except asyncio.CancelledError:
                pass
        logger.info("KnowledgeConsolidation stopped")

    async def run_now(self) -> dict:
        """
        Force an immediate consolidation run.

        Returns:
            Dict with consolidation results
        """
        logger.info("[KnowledgeConsolidation] Running immediate consolidation")
        results = {
            "fragments_extracted": 0,
            "skills_created": 0,
            "skills_updated": 0,
            "memory_updated": False,
            "errors": [],
        }

        try:
            # 1. Consolidate from failure learning
            fail_results = await self._consolidate_failures()
            results["skills_updated"] += fail_results

            # 2. Consolidate recent sessions
            session_results = await self._consolidate_recent_sessions()
            results["fragments_extracted"] += session_results["fragments"]
            results["skills_created"] += session_results["skills_created"]
            results["memory_updated"] = session_results["memory_updated"]

        except Exception as e:
            logger.exception(f"[KnowledgeConsolidation] Error: {e}")
            results["errors"].append(str(e))

        logger.info(f"[KnowledgeConsolidation] Done: {results}")
        return results

    async def consolidate_session(self, session_id: str) -> dict:
        """
        Consolidate knowledge from a single session.

        Called when a session ends.
        """
        results = {"fragments": [], "actions": []}

        try:
            from app.core.session_manager import SessionManager
            sm = SessionManager()
            messages = sm.load_chat_messages(session_id)
            if not messages:
                return results

            # Extract knowledge from conversation
            fragments = await self._extract_fragments_from_messages(session_id, messages)
            results["fragments"] = fragments

            for frag in fragments:
                action = await self._apply_fragment(frag)
                if action:
                    results["actions"].append(action)

        except Exception as e:
            logger.exception(f"[KnowledgeConsolidation] Session consolidation error: {e}")

        return results

    # ── Fragment extraction ────────────────────────────────────────────────

    async def _extract_fragments_from_messages(self, session_id: str, messages) -> list[KnowledgeFragment]:
        """Analyze messages and extract knowledge fragments."""
        fragments = []

        # Build conversation text for pattern analysis
        conv_text = "\n".join(
            f"[{m.role}]: {getattr(m, 'content', '') or ''}"
            for m in messages[-20:]  # Last 20 messages
        )

        # Pattern: User corrections ("you should", "actually", "no, I meant")
        correction_pattern = re.compile(
            r"(?:actually|no|you (?:should|need to)|I meant|wait|"
            r"that[' ]?s? wrong|not (?:that|this)|"
            r"I wanted you to|please (?:don[' ]t|different))",
            re.I,
        )
        if correction_pattern.search(conv_text):
            # Extract the correction context
            for msg in messages:
                if msg.role == "user" and correction_pattern.search(msg.content or ""):
                    fragments.append(KnowledgeFragment(
                        source="conversation",
                        session_id=session_id,
                        title="User Correction Pattern",
                        content=f"User corrected agent: {msg.content[:300]}",
                        confidence=0.7,
                        tags=["user-correction", "preference"],
                    ))
                    break

        # Pattern: Repeated tool failures (same tool called multiple times)
        tool_counts: dict[str, int] = {}
        for msg in messages:
            if msg.role == "assistant" and hasattr(msg, "parts"):
                for part in (msg.parts or []):
                    if isinstance(part, dict) and part.get("type") == "tool_call":
                        tool = part.get("name", "unknown")
                        tool_counts[tool] = tool_counts.get(tool, 0) + 1

        for tool, count in tool_counts.items():
            if count >= 3:
                fragments.append(KnowledgeFragment(
                    source="conversation",
                    session_id=session_id,
                    title=f"Repeated Tool: {tool}",
                    content=f"{tool} was called {count}x in this session — consider batching or optimizing",
                    confidence=0.6,
                    tags=["tool-usage", "efficiency"],
                ))

        return fragments[:5]  # Max 5 fragments per session

    async def _apply_fragment(self, frag: KnowledgeFragment) -> Optional[str]:
        """Apply a knowledge fragment to memory or skill system."""
        try:
            if frag.confidence < 0.7:
                return None  # Skip low-confidence fragments

            # High-confidence corrections → update USER.md
            if "user-correction" in frag.tags:
                await self._update_user_memory(frag)
                return "Updated user preferences"

            # Tool patterns → update relevant skill
            if "tool-usage" in frag.tags:
                skill_name = self._infer_skill_for_fragment(frag)
                if skill_name:
                    await self._update_skill_with_insight(skill_name, frag)
                    return f"Updated skill: {skill_name}"

            return None

        except Exception as e:
            logger.warning(f"[KnowledgeConsolidation] Failed to apply fragment: {e}")
            return None

    async def _update_user_memory(self, frag: KnowledgeFragment) -> None:
        """Update USER.md with user preference knowledge."""
        workspace = Path.home() / ".openclaw" / "workspace"
        user_md = workspace / "USER.md"
        if not user_md.exists():
            return

        try:
            existing = user_md.read_text()
            # Check if this preference is already recorded
            if frag.title in existing or frag.content[:50] in existing:
                return

            # Append to USER.md under a "## Learned Preferences" section
            entry = f"\n### {frag.created_at.strftime('%Y-%m-%d')}: {frag.title}\n"
            entry += f"{frag.content}\n"

            if "## Learned Preferences" in existing:
                existing = existing.replace(
                    "## Learned Preferences",
                    f"## Learned Preferences{entry}",
                )
            else:
                existing += f"\n## Learned Preferences\n{entry}"

            user_md.write_text(existing)
            logger.info(f"[KnowledgeConsolidation] Updated USER.md with: {frag.title}")

        except Exception as e:
            logger.warning(f"[KnowledgeConsolidation] Failed to update USER.md: {e}")

    async def _update_skill_with_insight(self, skill_name: str, frag: KnowledgeFragment) -> None:
        """Add an insight to an existing skill."""
        try:
            from app.core.skill_manager import SkillManager
            settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
            sm = SkillManager(settings=settings)
            sm.scan_skills()

            skill = sm.skills.get(skill_name)
            if not skill:
                return

            skill_path = skill.path / "SKILL.md"
            if not skill_path.exists():
                return

            existing = skill_path.read_text()

            # Append insight under a "## Lessons Learned" section
            insight = f"\n### {frag.created_at.strftime('%Y-%m-%d')}\n"
            insight += f"{frag.content}\n"

            if "## Lessons Learned" in existing:
                existing = existing.replace("## Lessons Learned", f"## Lessons Learned{insight}")
            else:
                existing += f"\n## Lessons Learned\n{insight}"

            skill_path.write_text(existing)
            logger.info(f"[KnowledgeConsolidation] Updated skill {skill_name}")

        except Exception as e:
            logger.warning(f"[KnowledgeConsolidation] Failed to update skill {skill_name}: {e}")

    def _infer_skill_for_fragment(self, frag: KnowledgeFragment) -> Optional[str]:
        """Guess which skill this fragment relates to based on tags."""
        tag_to_skill = {
            "tool-usage": "tool-execution",
            "efficiency": "tool-execution",
            "web": "web-search",
            "file": "file-operations",
            "code": "code-generation",
        }
        for tag in frag.tags:
            if tag in tag_to_skill:
                return tag_to_skill[tag]
        return None

    # ── Failure consolidation ─────────────────────────────────────────────

    async def _consolidate_failures(self) -> int:
        """
        Convert failure patterns into skill avoidance notes.

        Returns number of skills updated.
        """
        engine = FailureLearningEngine.get_instance()
        avoidances = engine.get_avoidances()
        updated = 0

        for pattern in avoidances:
            if not pattern.avoidance_note or not pattern.tool_name:
                continue

            skill_name = self._infer_skill_for_fragment(
                KnowledgeFragment(
                    source="failure_record",
                    session_id="",
                    title=f"Failure: {pattern.tool_name}",
                    content=pattern.avoidance_note,
                    confidence=0.9,
                    tags=["avoidance"],
                ),
            )
            if not skill_name:
                skill_name = pattern.tool_name.replace("-", "-")

            frag = KnowledgeFragment(
                source="failure_record",
                session_id="",
                title=f"Avoid: {pattern.error_type} in {pattern.tool_name}",
                content=pattern.avoidance_note,
                confidence=0.9,
                tags=["avoidance", pattern.error_type],
            )
            action = await self._apply_fragment(frag)
            if action:
                updated += 1

        return updated

    # ── Recent session consolidation ─────────────────────────────────────

    async def _consolidate_recent_sessions(self) -> dict:
        """Consolidate knowledge from sessions in the last 24h."""
        results = {
            "fragments": 0,
            "skills_created": 0,
            "memory_updated": False,
        }

        try:
            from app.core.session_manager import SessionManager
            sm = SessionManager()
            recent = sm.get_recent_sessions(limit=10)

            for session in recent:
                # Only consolidate sessions from last 24h
                if session.updated_at < datetime.now(timezone.utc) - timedelta(hours=24):
                    continue

                frag_count = len(await self.consolidate_session(session.id))
                results["fragments"] += frag_count
                if frag_count > 0:
                    results["memory_updated"] = True

        except Exception as e:
            logger.warning(f"[KnowledgeConsolidation] Recent sessions error: {e}")

        return results

    # ── Background consolidation ──────────────────────────────────────────

    async def _background_consolidation(self) -> None:
        """Run consolidation every 24 hours (at most)."""
        while self._running:
            try:
                await asyncio.sleep(self._interval_hours * 3600)
                if self._running:
                    await self.run_now()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[KnowledgeConsolidation] Background error: {e}")
                await asyncio.sleep(3600)  # Retry in 1h
