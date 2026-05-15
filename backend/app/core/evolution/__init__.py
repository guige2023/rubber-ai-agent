"""
Evolution Module - Self-evolution engine inspired by Hermes Agent.

Provides autonomous skill creation, memory nudge, and background review
for continuous agent improvement.
"""

from .evolution_manager import EvolutionManager
from .nudge import NudgeEngine, NudgeType, NudgeSignal
from .background_review import BackgroundReviewer
from .curator import Curator, CuratorConfig
from .skill_provenance import SkillProvenance, ProvenanceTracker

__all__ = [
    "EvolutionManager",
    "NudgeEngine",
    "NudgeType",
    "NudgeSignal",
    "BackgroundReviewer",
    "Curator",
    "CuratorConfig",
    "SkillProvenance",
    "ProvenanceTracker",
]
