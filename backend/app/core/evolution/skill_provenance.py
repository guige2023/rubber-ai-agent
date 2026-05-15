"""
Skill Provenance - Tracks skill creation and modification history.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class ProvenanceType(str, Enum):
    """Who created/modified the skill."""

    BUNDLED = "bundled"  # Shipped with the system
    HUMAN = "human"  # Created by human developer
    AGENT = "agent"  # Created by the agent
    DERIVED = "derived"  # Created from another skill


@dataclass
class ProvenanceEntry:
    """An entry in the provenance log."""

    timestamp: datetime
    event_type: str  # "created", "modified", "absorbed", "archived"
    actor: ProvenanceType
    details: dict = field(default_factory=dict)


@dataclass
class SkillProvenance:
    """Provenance information for a skill."""

    skill_id: str
    skill_name: str
    created_at: datetime
    created_by: ProvenanceType
    modified_at: datetime
    modified_by: ProvenanceType
    entries: list[ProvenanceEntry] = field(default_factory=list)


class ProvenanceTracker:
    """
    Tracks skill provenance - who created/modified each skill.

    Maintains:
    - Creation provenance (bundled, human, agent)
    - Modification history
    - Absorption chains (when skills are merged)
    - Archive status
    """

    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or self._default_storage_path()
        self._provenance_cache: dict[str, SkillProvenance] = {}
        self._load_cache()

    @staticmethod
    def _default_storage_path() -> Path:
        """Get default storage path."""
        # Use RabAiAgent data directory
        data_dir = Path.home() / ".rabaiagent" / "user"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / "skill_provenance.json"

    def _load_cache(self) -> None:
        """Load provenance cache from disk."""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r") as f:
                    data = json.load(f)
                    for skill_id, entries in data.items():
                        self._provenance_cache[skill_id] = self._deserialize(entries)
            except Exception as e:
                logger.error(f"Failed to load provenance cache: {e}")

    def _save_cache(self) -> None:
        """Save provenance cache to disk."""
        try:
            data = {
                skill_id: self._serialize(prov)
                for skill_id, prov in self._provenance_cache.items()
            }
            with open(self.storage_path, "w") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save provenance cache: {e}")

    def _serialize(self, prov: SkillProvenance) -> dict:
        """Serialize provenance to dict."""
        return {
            "skill_id": prov.skill_id,
            "skill_name": prov.skill_name,
            "created_at": prov.created_at.isoformat(),
            "created_by": prov.created_by.value,
            "modified_at": prov.modified_at.isoformat(),
            "modified_by": prov.modified_by.value,
            "entries": [
                {
                    "timestamp": e.timestamp.isoformat(),
                    "event_type": e.event_type,
                    "actor": e.actor.value,
                    "details": e.details,
                }
                for e in prov.entries
            ],
        }

    def _deserialize(self, data: dict) -> SkillProvenance:
        """Deserialize provenance from dict."""
        entries = [
            ProvenanceEntry(
                timestamp=datetime.fromisoformat(e["timestamp"]),
                event_type=e["event_type"],
                actor=ProvenanceType(e["actor"]),
                details=e.get("details", {}),
            )
            for e in data.get("entries", [])
        ]

        return SkillProvenance(
            skill_id=data["skill_id"],
            skill_name=data["skill_name"],
            created_at=datetime.fromisoformat(data["created_at"]),
            created_by=ProvenanceType(data["created_by"]),
            modified_at=datetime.fromisoformat(data["modified_at"]),
            modified_by=ProvenanceType(data["modified_by"]),
            entries=entries,
        )

    def track_creation(
        self,
        skill_id: str,
        skill_name: str,
        created_by: ProvenanceType,
    ) -> None:
        """
        Track skill creation.

        Args:
            skill_id: Unique skill ID
            skill_name: Skill name
            created_by: Who created the skill
        """
        now = datetime.utcnow()
        provenance = SkillProvenance(
            skill_id=skill_id,
            skill_name=skill_name,
            created_at=now,
            created_by=created_by,
            modified_at=now,
            modified_by=created_by,
            entries=[
                ProvenanceEntry(
                    timestamp=now,
                    event_type="created",
                    actor=created_by,
                    details={"skill_name": skill_name},
                )
            ],
        )

        self._provenance_cache[skill_id] = provenance
        self._save_cache()
        logger.debug(f"Tracked creation of skill {skill_name} by {created_by.value}")

    def track_modification(
        self,
        skill_id: str,
        modified_by: ProvenanceType,
        details: dict,
    ) -> None:
        """
        Track skill modification.

        Args:
            skill_id: Skill ID
            modified_by: Who modified the skill
            details: Modification details
        """
        if skill_id not in self._provenance_cache:
            logger.warning(f"Skill {skill_id} not found in provenance cache")
            return

        provenance = self._provenance_cache[skill_id]
        now = datetime.utcnow()

        entry = ProvenanceEntry(
            timestamp=now,
            event_type="modified",
            actor=modified_by,
            details=details,
        )

        provenance.entries.append(entry)
        provenance.modified_at = now
        provenance.modified_by = modified_by

        self._save_cache()
        logger.debug(f"Tracked modification of skill {skill_id} by {modified_by.value}")

    def track_absorption(
        self,
        source_skill_id: str,
        target_skill_id: str,
        absorbed_by: ProvenanceType,
    ) -> None:
        """
        Track when a skill is absorbed into another skill.

        Args:
            source_skill_id: Skill that was absorbed
            target_skill_id: Skill that absorbed it
            absorbed_by: Who performed the absorption
        """
        if source_skill_id not in self._provenance_cache:
            logger.warning(f"Source skill {source_skill_id} not found")
            return

        now = datetime.utcnow()
        source = self._provenance_cache[source_skill_id]

        # Track absorption in source
        entry = ProvenanceEntry(
            timestamp=now,
            event_type="absorbed",
            actor=absorbed_by,
            details={
                "absorbed_into": target_skill_id,
            },
        )
        source.entries.append(entry)

        # Update target if exists
        if target_skill_id in self._provenance_cache:
            target = self._provenance_cache[target_skill_id]
            entry = ProvenanceEntry(
                timestamp=now,
                event_type="absorbed_other",
                actor=absorbed_by,
                details={
                    "absorbed": source_skill_id,
                },
            )
            target.entries.append(entry)
            target.modified_at = now
            target.modified_by = absorbed_by

        self._save_cache()
        logger.debug(f"Tracked absorption: {source_skill_id} -> {target_skill_id}")

    def get_provenance(self, skill_id: str) -> Optional[SkillProvenance]:
        """Get provenance for a skill."""
        return self._provenance_cache.get(skill_id)

    def is_agent_created(self, skill_id: str) -> bool:
        """Check if a skill was created by the agent."""
        provenance = self._provenance_cache.get(skill_id)
        if not provenance:
            return False
        return provenance.created_by == ProvenanceType.AGENT

    def is_background_review(self, skill_id: str) -> bool:
        """
        Check if skill was created by background review (not foreground).

        Used by curator to avoid touching foreground creations.
        """
        provenance = self._provenance_cache.get(skill_id)
        if not provenance:
            return False

        # Check if creation entry has background flag
        for entry in provenance.entries:
            if entry.event_type == "created":
                return entry.details.get("background", False)

        return False

    def get_all_agent_created(self) -> list[str]:
        """Get IDs of all agent-created skills."""
        return [
            skill_id
            for skill_id, prov in self._provenance_cache.items()
            if prov.created_by == ProvenanceType.AGENT
        ]

    def get_status(self) -> dict:
        """Get provenance tracker status."""
        total = len(self._provenance_cache)
        agent_created = sum(
            1 for p in self._provenance_cache.values() if p.created_by == ProvenanceType.AGENT
        )
        human_created = sum(
            1 for p in self._provenance_cache.values() if p.created_by == ProvenanceType.HUMAN
        )
        bundled = sum(
            1 for p in self._provenance_cache.values() if p.created_by == ProvenanceType.BUNDLED
        )

        return {
            "total_skills": total,
            "agent_created": agent_created,
            "human_created": human_created,
            "bundled": bundled,
            "cache_path": str(self.storage_path),
        }
