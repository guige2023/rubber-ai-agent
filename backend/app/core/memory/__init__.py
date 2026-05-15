"""
Memory Module - Hierarchical memory system inspired by MemOS.

Architecture:
- L1 Trace: Step-level records (action + observation + reflection + value)
- L2 Policy: Sub-task strategies induced from traces
- L3 World Model: Compressed environmental cognition
- Skill: Crystallized callable capabilities

Storage:
- Neo4j for graph relationships
- SQLite for vector search
"""

from .memory_manager import MemoryManager
from .neo4j_client import Neo4jClient, get_neo4j_client
from .l1_trace import TraceMemory, TraceRecord
from .l2_policy import PolicyMemory, Policy
from .l3_world import WorldModelMemory, WorldModel
from .skill_crystal import SkillCrystal, CrystallizedSkill
from .retrieval import MemoryRetrieval, RetrievalResult, Tier
from .embedding import EmbeddingService, get_embedding_service
from .consolidation import MemoryConsolidation

__all__ = [
    "MemoryManager",
    "Neo4jClient",
    "get_neo4j_client",
    "TraceMemory",
    "TraceRecord",
    "PolicyMemory",
    "Policy",
    "WorldModelMemory",
    "WorldModel",
    "SkillCrystal",
    "CrystallizedSkill",
    "MemoryRetrieval",
    "RetrievalResult",
    "Tier",
    "EmbeddingService",
    "get_embedding_service",
    "MemoryConsolidation",
]
