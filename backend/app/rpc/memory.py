"""
Memory RPC methods for frontend access.
"""

from __future__ import annotations

import logging
from typing import Optional

from jsonrpcserver import Success, method

logger = logging.getLogger(__name__)


@method
async def list_memory_tiers(context) -> Success:
    """Get statistics for each memory tier (L1/L2/L3/Skills)."""
    runtime = context.runtime
    memory_manager = getattr(runtime, "memory_manager", None)

    if not memory_manager:
        return Success({"error": "Memory manager not available"})

    await memory_manager.initialize()

    # Get stats from neo4j directly
    neo4j = memory_manager._neo4j

    # Count L1 traces
    l1_result = await neo4j.execute_query(
        "MATCH (t:Trace) RETURN count(t) as count"
    )
    l1_count = l1_result[0].get("count", 0) if l1_result and len(l1_result) > 0 else 0

    # Count L2 policies
    l2_result = await neo4j.execute_query(
        "MATCH (p:Policy) RETURN count(p) as count"
    )
    l2_count = l2_result[0].get("count", 0) if l2_result and len(l2_result) > 0 else 0

    # Count L3 world models
    l3_result = await neo4j.execute_query(
        "MATCH (w:WorldModel) RETURN count(w) as count"
    )
    l3_count = l3_result[0].get("count", 0) if l3_result and len(l3_result) > 0 else 0

    # Count crystallized skills
    skills_result = await neo4j.execute_query(
        "MATCH (s:CrystallizedSkill) RETURN count(s) as count"
    )
    skills_count = skills_result[0].get("count", 0) if skills_result and len(skills_result) > 0 else 0

    # Count reliable skills (eta >= 0.7)
    reliable_result = await neo4j.execute_query(
        "MATCH (s:CrystallizedSkill) WHERE s.eta >= 0.7 RETURN count(s) as count"
    )
    reliable_count = reliable_result[0].get("count", 0) if reliable_result and len(reliable_result) > 0 else 0

    return Success({
        "tiers": {
            "l1_trace": {"count": l1_count, "description": "Session trace memories"},
            "l2_policy": {"count": l2_count, "description": "Induced policies"},
            "l3_world_model": {"count": l3_count, "description": "World model inferences"},
            "crystallized_skills": {
                "count": skills_count,
                "reliable_count": reliable_count,
                "description": "Agent capabilities"
            },
        },
    })


@method
async def list_skill_crystals(context, min_eta: Optional[float] = None) -> Success:
    """List all crystallized skills, optionally filtered by minimum eta."""
    runtime = context.runtime
    memory_manager = getattr(runtime, "memory_manager", None)

    if not memory_manager:
        return Success({"error": "Memory manager not available"})

    await memory_manager.initialize()

    neo4j = memory_manager._neo4j

    if min_eta is not None:
        query = """
        MATCH (s:CrystallizedSkill)
        WHERE s.eta >= $min_eta
        RETURN s
        ORDER BY s.eta DESC
        """
        results = await neo4j.execute_query(query, {"min_eta": min_eta})
    else:
        query = "MATCH (s:CrystallizedSkill) RETURN s ORDER BY s.eta DESC"
        results = await neo4j.execute_query(query)

    skills = []
    for record in results:
        s = record.get("s", {})
        if s:
            skill_data = {
                "id": s.get("id", ""),
                "name": s.get("name", ""),
                "description": s.get("description", ""),
                "eta": s.get("eta", 0.0),
                "usage_count": s.get("usage_count", 0),
                "success_count": s.get("success_count", 0),
                "provenance": s.get("provenance", "agent"),
                "created_at": str(s.get("created_at", "")),
                "updated_at": str(s.get("updated_at", "")),
            }
            skills.append(skill_data)

    return Success({
        "skills": skills,
        "total": len(skills),
    })


@method
async def get_skill_crystal(context, skill_id: str) -> Success:
    """Get a single crystallized skill by ID."""
    runtime = context.runtime
    memory_manager = getattr(runtime, "memory_manager", None)

    if not memory_manager:
        return Success({"error": "Memory manager not available"})

    skill = await memory_manager.get_skill(skill_id)
    if not skill:
        return Success({"error": "Skill not found"})

    return Success({
        "skill": {
            "id": skill.id,
            "name": skill.name,
            "description": skill.description,
            "content": skill.content,
            "eta": skill.eta,
            "usage_count": skill.usage_count,
            "success_count": skill.success_count,
            "provenance": skill.provenance.value if hasattr(skill.provenance, 'value') else skill.provenance,
            "created_at": skill.created_at.isoformat() if skill.created_at else None,
            "updated_at": skill.updated_at.isoformat() if skill.updated_at else None,
        }
    })


@method
async def trigger_memory_consolidation(context) -> Success:
    """Manually trigger memory consolidation."""
    runtime = context.runtime
    memory_manager = getattr(runtime, "memory_manager", None)

    if not memory_manager:
        return Success({"error": "Memory manager not available"})

    await memory_manager.initialize()

    try:
        result = await memory_manager.run_consolidation()
        return Success({
            "status": "success",
            "result": result,
        })
    except Exception as e:
        logger.exception("Memory consolidation failed")
        return Success({
            "status": "error",
            "message": str(e),
        })


@method
async def get_memory_settings(context) -> Success:
    """Get memory system settings."""
    runtime = context.runtime
    memory_manager = getattr(runtime, "memory_manager", None)

    if not memory_manager:
        return Success({"error": "Memory manager not available"})

    # Get consolidation config if available
    consolidation_status = None
    if memory_manager._consolidation:
        consolidation_status = memory_manager._consolidation.get_status()

    return Success({
        "settings": {
            "consolidation": consolidation_status,
            "embedding_provider": memory_manager._embedding.provider if memory_manager._embedding else None,
            "embedding_dimensions": memory_manager._embedding.dimensions if memory_manager._embedding else None,
        }
    })


@method
async def record_skill_usage(context, skill_id: str, success: bool) -> Success:
    """Record skill usage and update reliability."""
    runtime = context.runtime
    memory_manager = getattr(runtime, "memory_manager", None)

    if not memory_manager:
        return Success({"error": "Memory manager not available"})

    await memory_manager.initialize()

    result = await memory_manager.record_skill_usage(skill_id, success)
    return Success({
        "status": "success" if result else "error",
        "updated": result,
    })
