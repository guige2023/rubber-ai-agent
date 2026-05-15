"""
Memory Manager - L1/L2/L3 memory system for agents.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class MemoryTier(Enum):
    """Memory tier levels."""
    L1_WORKING = "l1_working"      # Current session, short-term
    L2_SEMANTIC = "l2_semantic"    # Long-term semantic, Neo4j
    L3_CRYSTAL = "l3_crystal"      # Crystallized knowledge, Skills


@dataclass
class MemoryEntry:
    """A single memory entry."""
    id: str
    tier: MemoryTier
    content: Any
    metadata: dict[str, Any]
    created_at: datetime
    accessed_at: datetime
    access_count: int = 0
    importance: float = 0.5  # 0.0 to 1.0


class MemoryManager:
    """
    Manages L1/L2/L3 memory for the agent cluster.

    - L1 (Working Memory): Current session context, stored in SQLite
    - L2 (Semantic Memory): Long-term semantic knowledge, stored in Neo4j
    - L3 (Crystal Memory): Crystallized knowledge (Skills), stored in files/vector DB
    """

    def __init__(self) -> None:
        self._l1_store: dict[str, MemoryEntry] = {}
        self._l2_conn: Optional[Any] = None  # Neo4j connection
        self._l3_path: Optional[str] = None
        self._lock = asyncio.Lock()
        self._initialized = False

    async def initialize(
        self,
        l2_uri: Optional[str] = None,
        l3_path: Optional[str] = None,
    ) -> None:
        """Initialize memory stores."""
        if self._initialized:
            return

        # Initialize L2 connection if URI provided
        if l2_uri:
            await self._init_l2(l2_uri)

        # Set L3 path
        if l3_path:
            self._l3_path = l3_path

        self._initialized = True
        logger.info("MemoryManager initialized")

    async def _init_l2(self, uri: str) -> None:
        """Initialize Neo4j connection for L2 memory."""
        try:
            from neo4j import AsyncGraphDatabase

            # Extract connection details from URI
            # uri format: neo4j://user:pass@host:port
            self._l2_conn = AsyncGraphDatabase.driver(uri)
            await self._l2_conn.verify_connectivity()
            logger.info(f"L2 memory connected to Neo4j: {uri}")
        except Exception as e:
            logger.warning(f"Failed to connect to Neo4j: {e}. L2 memory will be disabled.")
            self._l2_conn = None

    async def shutdown(self) -> None:
        """Shutdown memory stores."""
        if self._l2_conn:
            await self._l2_conn.close()
        self._initialized = False
        logger.info("MemoryManager shutdown")

    # === L1 Working Memory ===

    async def l1_store(
        self,
        key: str,
        value: Any,
        metadata: Optional[dict[str, Any]] = None,
    ) -> MemoryEntry:
        """Store in L1 working memory."""
        entry = MemoryEntry(
            id=key,
            tier=MemoryTier.L1_WORKING,
            content=value,
            metadata=metadata or {},
            created_at=datetime.utcnow(),
            accessed_at=datetime.utcnow(),
        )
        async with self._lock:
            self._l1_store[key] = entry
        return entry

    async def l1_retrieve(self, key: str) -> Optional[Any]:
        """Retrieve from L1 working memory."""
        async with self._lock:
            entry = self._l1_store.get(key)
            if entry:
                entry.access_count += 1
                entry.accessed_at = datetime.utcnow()
                return entry.content
        return None

    async def l1_forget(self, key: str) -> bool:
        """Remove from L1 working memory."""
        async with self._lock:
            if key in self._l1_store:
                del self._l1_store[key]
                return True
        return False

    async def l1_keys(self) -> list[str]:
        """List all L1 keys."""
        async with self._lock:
            return list(self._l1_store.keys())

    # === L2 Semantic Memory ===

    async def l2_store(
        self,
        subject: str,
        predicate: str,
        object: Any,
        metadata: Optional[dict[str, Any]] = None,
    ) -> bool:
        """
        Store triple in L2 semantic memory (Neo4j).

        Args:
            subject: Subject entity
            predicate: Relationship
            object: Object value
        """
        if not self._l2_conn:
            logger.debug("L2 memory not available, skipping")
            return False

        try:
            async with self._l2_conn.session() as session:
                await session.run(
                    """
                    MERGE (s:Entity {name: $subject})
                    MERGE (o:Entity {name: $object})
                    MERGE (s)-[r:RELATES {type: $predicate}]->(o)
                    """,
                    subject=subject,
                    predicate=predicate,
                    object=str(object),
                )
            return True
        except Exception as e:
            logger.error(f"L2 store error: {e}")
            return False

    async def l2_query(self, subject: str) -> list[dict]:
        """
        Query L2 semantic memory.

        Returns all triples where subject is the entity.
        """
        if not self._l2_conn:
            return []

        try:
            async with self._l2_conn.session() as session:
                result = await session.run(
                    """
                    MATCH (s:Entity {name: $subject})-[r]-(o)
                    RETURN type(r) as predicate, o.name as object
                    """,
                    subject=subject,
                )
                records = await result.data()
                return [{"predicate": r["predicate"], "object": r["object"]} for r in records]
        except Exception as e:
            logger.error(f"L2 query error: {e}")
            return []

    async def l2_search(self, query: str, limit: int = 10) -> list[dict]:
        """Search L2 semantic memory."""
        if not self._l2_conn:
            return []

        try:
            async with self._l2_conn.session() as session:
                result = await session.run(
                    """
                    MATCH (s)-[r]-(o)
                    WHERE s.name CONTAINS $query OR o.name CONTAINS $query
                    RETURN s.name as subject, type(r) as predicate, o.name as object
                    LIMIT $limit
                    """,
                    query=query,
                    limit=limit,
                )
                records = await result.data()
                return [
                    {
                        "subject": r["subject"],
                        "predicate": r["predicate"],
                        "object": r["object"],
                    }
                    for r in records
                ]
        except Exception as e:
            logger.error(f"L2 search error: {e}")
            return []

    # === L3 Crystal Memory (Skills) ===

    async def l3_list_skills(self) -> list[dict]:
        """List all crystallized skills (L3)."""
        skills = []
        if not self._l3_path:
            return skills

        try:
            import os
            from pathlib import Path

            skills_dir = Path(self._l3_path)
            if skills_dir.exists():
                for skill_file in skills_dir.glob("**/*.md"):
                    skills.append({
                        "name": skill_file.stem,
                        "path": str(skill_file),
                        "modified": datetime.fromtimestamp(
                            skill_file.stat().st_mtime
                        ).isoformat(),
                    })
        except Exception as e:
            logger.error(f"L3 list skills error: {e}")

        return skills

    async def l3_load_skill(self, name: str) -> Optional[str]:
        """Load a crystallized skill by name."""
        if not self._l3_path:
            return None

        try:
            from pathlib import Path

            skill_file = Path(self._l3_path) / f"{name}.md"
            if skill_file.exists():
                return skill_file.read_text()
        except Exception as e:
            logger.error(f"L3 load skill error: {e}")

        return None

    async def l3_save_skill(
        self,
        name: str,
        content: str,
        metadata: Optional[dict] = None,
    ) -> bool:
        """Save a crystallized skill."""
        if not self._l3_path:
            return False

        try:
            from pathlib import Path

            skills_dir = Path(self._l3_path)
            skills_dir.mkdir(parents=True, exist_ok=True)

            skill_file = skills_dir / f"{name}.md"
            skill_file.write_text(content)
            return True
        except Exception as e:
            logger.error(f"L3 save skill error: {e}")
            return False

    # === Memory Operations ===

    async def consolidate(self) -> dict[str, int]:
        """
        Consolidate memories across tiers.

        Returns statistics about consolidation.
        """
        stats = {"l1_entries": len(self._l1_store)}

        # L1 -> L2: Promote important L1 entries to L2
        promoted = 0
        async with self._lock:
            for key, entry in self._l1_store.items():
                if entry.importance > 0.7 and entry.access_count > 3:
                    await self.l2_store(
                        subject=f"memory:{key}",
                        predicate="has_content",
                        object=entry.content,
                    )
                    promoted += 1

        stats["l1_to_l2_promoted"] = promoted

        # L2 stats
        if self._l2_conn:
            try:
                async with self._l2_conn.session() as session:
                    result = await session.run("MATCH (n) RETURN count(n) as count")
                    record = await result.single()
                    stats["l2_entities"] = record["count"] if record else 0
            except Exception:
                stats["l2_entities"] = 0
        else:
            stats["l2_entities"] = 0

        # L3 stats
        skills = await self.l3_list_skills()
        stats["l3_skills"] = len(skills)

        logger.info(f"Memory consolidation complete: {stats}")
        return stats

    async def get_stats(self) -> dict[str, Any]:
        """Get memory system statistics."""
        stats = {
            "initialized": self._initialized,
            "l1": {
                "entries": len(self._l1_store),
                "keys": list(self._l1_store.keys()),
            },
            "l2": {
                "connected": self._l2_conn is not None,
            },
            "l3": {
                "path": self._l3_path,
                "skills_count": len(await self.l3_list_skills()),
            },
        }

        # Get L2 entity count
        if self._l2_conn:
            try:
                async with self._l2_conn.session() as session:
                    result = await session.run("MATCH (n) RETURN count(n) as count")
                    record = await result.single()
                    stats["l2"]["entities"] = record["count"] if record else 0
            except Exception:
                stats["l2"]["entities"] = 0

        return stats

    async def clear_l1(self) -> int:
        """Clear all L1 working memory. Returns count of cleared entries."""
        async with self._lock:
            count = len(self._l1_store)
            self._l1_store.clear()
            return count
