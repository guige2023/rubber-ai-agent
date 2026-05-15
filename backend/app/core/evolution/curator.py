"""
Curator - Idle-triggered background maintenance for skill organization.
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from app.core.health import (
    check_gateway_health,
    check_unanswered_sessions,
    check_missed_crons,
    get_daily_stats,
)
from app.core.memory.neo4j_client import get_neo4j_client
from app.core.memory.skill_crystal import SkillCrystal, SkillProvenance, CrystallizedSkill

logger = logging.getLogger(__name__)


@dataclass
class CuratorConfig:
    """Configuration for curator behavior."""

    idle_hours: int = 168  # 7 days idle before curator runs
    min_idle_hours: int = 1  # Minimum idle hours to run
    merge_threshold: int = 3  # Skills to merge before creating umbrella
    archive_after_days: int = 30  # Days before archiving unused skills
    consolidation_interval_hours: int = 24  # How often to check


class Curator:
    """
    Curator - Idle-triggered skill organization.

    Runs after idle periods to:
    - Merge narrow skills into umbrella skills
    - Archive stale skills
    - Consolidate agent-created skills

    This is the "class-level skill" organizer from Hermes Agent.
    """

    def __init__(self, config: Optional[CuratorConfig] = None):
        self.config = config or CuratorConfig()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_run: Optional[datetime] = None
        self._last_activity: Optional[datetime] = None
        self._lock = asyncio.Lock()
        self._skill_crystal: Optional[SkillCrystal] = None

    @property
    def skill_crystal(self) -> SkillCrystal:
        """Get or create the SkillCrystal instance."""
        if self._skill_crystal is None:
            self._skill_crystal = SkillCrystal(get_neo4j_client())
        return self._skill_crystal

    async def start(self) -> None:
        """Start the curator background task."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Curator started")

    async def stop(self) -> None:
        """Stop the curator background task."""
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("Curator stopped")

    async def _run_loop(self) -> None:
        """Main curator loop."""
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in curator loop: {e}")

            # Wait before next check
            await asyncio.sleep(3600)  # Check every hour

    async def _tick(self) -> None:
        """Check if curator should run."""
        if not self._last_activity:
            return

        now = datetime.utcnow()
        idle_hours = (now - self._last_activity).total_seconds() / 3600

        # Check if enough idle time has passed
        if idle_hours >= self.config.idle_hours:
            # Check if enough time since last run
            if self._last_run:
                hours_since_run = (now - self._last_run).total_seconds() / 3600
                if hours_since_run < self.config.consolidation_interval_hours:
                    return

            # Run curation
            await self.run_curation()

    def record_activity(self) -> None:
        """Record user/agent activity to reset idle timer."""
        self._last_activity = datetime.utcnow()

    async def run_curation(self) -> dict:
        """
        Run the curation process.

        Returns:
            Summary of curation actions
        """
        logger.info("Starting curator run")
        start_time = datetime.utcnow()

        summary = {
            "started_at": start_time.isoformat(),
            "skills_analyzed": 0,
            "skills_merged": 0,
            "skills_archived": 0,
            "umbrellas_created": 0,
            "errors": [],
            "health_checks": {},
        }

        try:
            # Step 1: Run health checks
            health_summary = await self._run_health_checks()
            summary["health_checks"] = health_summary

            # Step 2: Analyze agent-created skills
            analysis = await self._analyze_agent_skills()
            summary["skills_analyzed"] = analysis["count"]

            # Step 3: Find narrow skills that should be merged
            merge_candidates = await self._find_merge_candidates()
            summary["skills_merged"] = len(merge_candidates)

            # Step 4: Create umbrella skills
            umbrellas = await self._create_umbrella_skills(merge_candidates)
            summary["umbrellas_created"] = umbrellas

            # Step 5: Archive stale skills
            archived = await self._archive_stale_skills()
            summary["skills_archived"] = archived

            self._last_run = datetime.utcnow()
            summary["completed_at"] = self._last_run.isoformat()

        except Exception as e:
            logger.error(f"Curator error: {e}")
            summary["errors"].append(str(e))

        duration = (datetime.utcnow() - start_time).total_seconds()
        logger.info(
            f"Curator completed in {duration:.1f}s: "
            f"{summary['skills_analyzed']} analyzed, "
            f"{summary['skills_merged']} merged, "
            f"{summary['umbrellas_created']} umbrellas, "
            f"{summary['skills_archived']} archived"
        )

        return summary

    async def _analyze_agent_skills(self) -> dict:
        """
        Analyze agent-created skills for consolidation candidates.

        Returns:
            Analysis summary with skill groupings
        """
        try:
            # Query for all agent-created skills
            query = """
            MATCH (s:CrystallizedSkill)
            WHERE s.provenance = $provenance
            RETURN s
            ORDER BY s.created_at DESC
            """

            results = await self.skill_crystal.client.execute_query(
                query,
                {"provenance": SkillProvenance.AGENT.value}
            )

            skills = []
            for record in results:
                s = record.get("s", {})
                if s:
                    skill = CrystallizedSkill(
                        id=s.get("id", ""),
                        name=s.get("name", ""),
                        description=s.get("description", ""),
                        content=s.get("content", ""),
                        eta=float(s.get("eta", 1.0)),
                        usage_count=int(s.get("usage_count", 0)),
                        success_count=int(s.get("success_count", 0)),
                        provenance=SkillProvenance(s.get("provenance", SkillProvenance.AGENT.value)),
                        created_at=datetime.fromisoformat(s.get("created_at", datetime.utcnow().isoformat())),
                        updated_at=datetime.fromisoformat(s.get("updated_at", datetime.utcnow().isoformat())),
                    )
                    skills.append(skill)

            # Group skills by common prefix patterns
            groups = self._group_skills_by_prefix(skills)

            logger.info(f"Analyzed {len(skills)} agent-created skills, found {len(groups)} groups")

            return {
                "count": len(skills),
                "groups": groups,
                "skills": [
                    {
                        "id": s.id,
                        "name": s.name,
                        "description": s.description,
                        "eta": s.eta,
                        "usage_count": s.usage_count,
                    }
                    for s in skills
                ],
            }

        except Exception as e:
            logger.error(f"Error analyzing agent skills: {e}")
            return {
                "count": 0,
                "groups": [],
                "error": str(e),
            }

    def _group_skills_by_prefix(self, skills: list[CrystallizedSkill]) -> list[dict]:
        """
        Group skills by common prefixes (e.g., github-repo, github-issue -> github).

        Returns:
            List of skill groups with common prefixes
        """
        # Build prefix groups
        prefix_map: dict[str, list[CrystallizedSkill]] = {}

        for skill in skills:
            name = skill.name.lower()
            # Extract potential prefix (first segment before hyphen or underscore)
            parts = re.split(r"[-_]", name)
            if len(parts) > 1:
                prefix = parts[0]
                if prefix not in prefix_map:
                    prefix_map[prefix] = []
                prefix_map[prefix].append(skill)

        # Create groups for prefixes with multiple skills
        groups = []
        for prefix, grouped_skills in prefix_map.items():
            if len(grouped_skills) >= self.config.merge_threshold:
                groups.append({
                    "prefix": prefix,
                    "skills": [
                        {
                            "id": s.id,
                            "name": s.name,
                            "eta": s.eta,
                            "usage_count": s.usage_count,
                        }
                        for s in grouped_skills
                    ],
                    "umbrella_name": prefix,
                })

        return groups

    async def _find_merge_candidates(self) -> list[dict]:
        """
        Find skills that should be merged into umbrella skills.

        Returns:
            List of skill groups to merge
        """
        try:
            # Get all agent-created skills
            query = """
            MATCH (s:CrystallizedSkill)
            WHERE s.provenance = $provenance
            RETURN s
            ORDER BY s.usage_count DESC
            """

            results = await self.skill_crystal.client.execute_query(
                query,
                {"provenance": SkillProvenance.AGENT.value}
            )

            skills = []
            for record in results:
                s = record.get("s", {})
                if s:
                    skill = CrystallizedSkill(
                        id=s.get("id", ""),
                        name=s.get("name", ""),
                        description=s.get("description", ""),
                        content=s.get("content", ""),
                        eta=float(s.get("eta", 1.0)),
                        usage_count=int(s.get("usage_count", 0)),
                        success_count=int(s.get("success_count", 0)),
                        provenance=SkillProvenance(s.get("provenance", SkillProvenance.AGENT.value)),
                        created_at=datetime.fromisoformat(s.get("created_at", datetime.utcnow().isoformat())),
                        updated_at=datetime.fromisoformat(s.get("updated_at", datetime.utcnow().isoformat())),
                    )
                    skills.append(skill)

            # Find skills with similar prefixes
            merge_candidates = []
            prefix_map: dict[str, list[CrystallizedSkill]] = {}

            for skill in skills:
                name = skill.name.lower()
                parts = re.split(r"[-_]", name)
                if len(parts) > 1:
                    prefix = parts[0]
                    if prefix not in prefix_map:
                        prefix_map[prefix] = []
                    prefix_map[prefix].append(skill)

            # Create merge candidates for prefixes with enough skills
            for prefix, grouped_skills in prefix_map.items():
                if len(grouped_skills) >= self.config.merge_threshold:
                    # Calculate combined utility score
                    total_usage = sum(s.usage_count for s in grouped_skills)
                    avg_eta = sum(s.eta for s in grouped_skills) / len(grouped_skills)

                    merge_candidates.append({
                        "prefix": prefix,
                        "umbrella_name": prefix.capitalize(),
                        "skills": [
                            {
                                "id": s.id,
                                "name": s.name,
                                "eta": s.eta,
                                "usage_count": s.usage_count,
                            }
                            for s in sorted(grouped_skills, key=lambda x: x.usage_count, reverse=True)
                        ],
                        "total_usage": total_usage,
                        "avg_eta": avg_eta,
                        "merge_ready": len(grouped_skills) >= self.config.merge_threshold,
                    })

            # Sort by total usage (most used first)
            merge_candidates.sort(key=lambda x: x["total_usage"], reverse=True)

            logger.info(f"Found {len(merge_candidates)} merge candidates")
            return merge_candidates

        except Exception as e:
            logger.error(f"Error finding merge candidates: {e}")
            return []

    async def _create_umbrella_skills(
        self,
        merge_candidates: list[dict],
    ) -> list[str]:
        """
        Create umbrella skills from narrow skill groups.

        Args:
            merge_candidates: Groups of skills to merge

        Returns:
            List of created umbrella skill IDs
        """
        created = []

        for group in merge_candidates:
            umbrella_name = group.get("umbrella_name", "")
            child_skills = group.get("skills", [])

            if not umbrella_name or not child_skills:
                continue

            # Skip if not ready to merge
            if not group.get("merge_ready", False):
                continue

            try:
                # Generate umbrella skill content
                umbrella_content = self._generate_umbrella_content(group)

                # Create the umbrella skill
                umbrella_skill = CrystallizedSkill(
                    name=umbrella_name,
                    description=f"Umbrella skill containing related sub-skills: {', '.join(s['name'] for s in child_skills)}",
                    content=umbrella_content,
                    provenance=SkillProvenance.DERIVED,
                    source_policy_ids=[],
                    absorbed_skills=[s["name"] for s in child_skills],
                )

                # Save to Neo4j
                await self.skill_crystal.create_skill(umbrella_skill)

                # Absorb child skills into umbrella
                for child in child_skills:
                    child_id = child.get("id")
                    if child_id and umbrella_skill.id:
                        await self.skill_crystal.absorb_skill(
                            source_id=child_id,
                            target_id=umbrella_skill.id,
                        )

                created.append(umbrella_skill.id)
                logger.info(f"Created umbrella skill: {umbrella_name} absorbing {len(child_skills)} skills")

            except Exception as e:
                logger.error(f"Error creating umbrella skill {umbrella_name}: {e}")

        return created

    def _generate_umbrella_content(self, group: dict) -> str:
        """Generate umbrella skill content from child skills."""
        children = group.get("skills", [])
        child_names = [s.get("name", "") for s in children]

        content = f"# {group.get('umbrella_name', 'Unnamed')}\n\n"
        content += f"Auto-generated umbrella skill.\n\n"
        content += f"Contains: {', '.join(child_names)}\n\n"

        # Would include consolidated best practices from children
        content += "## Related Skills\n"
        for name in child_names:
            content += f"- {name}\n"

        return content

    async def _archive_stale_skills(self) -> int:
        """
        Archive skills that haven't been used in a while.

        Returns:
            Number of skills archived
        """
        try:
            # Find skills not used within the archive threshold
            archive_threshold = (
                datetime.utcnow() - timedelta(days=self.config.archive_after_days)
            ).isoformat()

            # Query for stale skills
            query = """
            MATCH (s:CrystallizedSkill)
            WHERE s.provenance = $provenance
                AND (s.usage_count = 0 OR s.updated_at < datetime($threshold))
            RETURN s
            """

            results = await self.skill_crystal.client.execute_query(
                query,
                {
                    "provenance": SkillProvenance.AGENT.value,
                    "threshold": archive_threshold,
                }
            )

            archived_count = 0
            for record in results:
                s = record.get("s", {})
                if s:
                    skill_id = s.get("id")
                    skill_name = s.get("name")

                    # Mark as archived by updating metadata
                    archive_query = """
                    MATCH (s:CrystallizedSkill {id: $id})
                    SET s.archived = true,
                        s.archived_at = datetime(),
                        s.updated_at = datetime()
                    """

                    try:
                        await self.skill_crystal.client.execute_write(
                            archive_query,
                            {"id": skill_id}
                        )
                        archived_count += 1
                        logger.info(f"Archived stale skill: {skill_name}")

                    except Exception as e:
                        logger.error(f"Error archiving skill {skill_name}: {e}")

            logger.info(f"Archived {archived_count} stale skills")
            return archived_count

        except Exception as e:
            logger.error(f"Error archiving stale skills: {e}")
            return 0

    async def _run_health_checks(self) -> dict:
        """
        Run OpenCLAW health checks as part of curation.

        Runs:
        - Gateway health (crashes, locks, connections)
        - Unanswered session detection
        - Missed cron jobs
        - Daily statistics

        Returns:
            Summary dict with check results
        """
        summary: dict = {
            "gateway_health": None,
            "unanswered": None,
            "missed_crons": None,
            "daily_stats": None,
        }

        try:
            # Gateway health check
            health_result = await check_gateway_health()
            summary["gateway_health"] = {
                "all_ok": health_result.all_ok,
                "issues_fixed": health_result.issues_fixed,
                "issues_detected": health_result.issues_detected,
                "issues": [
                    {
                        "code": i.code,
                        "severity": i.severity.value,
                        "message": i.message,
                    }
                    for i in health_result.issues
                ],
            }
            logger.info(
                f"Gateway health: ok={health_result.all_ok}, "
                f"fixed={health_result.issues_fixed}, "
                f"detected={health_result.issues_detected}"
            )
        except Exception as e:
            logger.warning(f"Gateway health check failed: {e}")
            summary["gateway_health"] = {"error": str(e)}

        try:
            # Unanswered sessions check
            unanswered_result = await check_unanswered_sessions(
                output_format="json",
            )
            if isinstance(unanswered_result, str):
                import json
                summary["unanswered"] = json.loads(unanswered_result)
            else:
                summary["unanswered"] = {
                    "count": unanswered_result.count,
                    "all_ok": unanswered_result.all_ok,
                }
        except Exception as e:
            logger.warning(f"Unanswered check failed: {e}")
            summary["unanswered"] = {"error": str(e)}

        try:
            # Missed crons check
            missed_result = await check_missed_crons(output_format="json")
            if isinstance(missed_result, str):
                import json
                summary["missed_crons"] = json.loads(missed_result)
            else:
                summary["missed_crons"] = {
                    "ok": missed_result.ok_count,
                    "missed": missed_result.missed_count,
                    "error": missed_result.error_count,
                }
        except Exception as e:
            logger.warning(f"Missed crons check failed: {e}")
            summary["missed_crons"] = {"error": str(e)}

        try:
            # Daily stats
            stats_result = await get_daily_stats(output_format="json")
            if isinstance(stats_result, str):
                import json
                summary["daily_stats"] = json.loads(stats_result)
            else:
                summary["daily_stats"] = {
                    "date": stats_result.date,
                    "total_issues": stats_result.total_issues,
                }
        except Exception as e:
            logger.warning(f"Daily stats collection failed: {e}")
            summary["daily_stats"] = {"error": str(e)}

        return summary

    async def run_now(self) -> dict:
        """Force curator to run immediately."""
        return await self.run_curation()

    def get_status(self) -> dict:
        """Get curator status."""
        return {
            "running": self._running,
            "last_run": self._last_run.isoformat() if self._last_run else None,
            "last_activity": self._last_activity.isoformat() if self._last_activity else None,
            "idle_hours": (
                (datetime.utcnow() - self._last_activity).total_seconds() / 3600
                if self._last_activity
                else None
            ),
            "config": {
                "idle_hours": self.config.idle_hours,
                "merge_threshold": self.config.merge_threshold,
                "archive_after_days": self.config.archive_after_days,
            },
        }
