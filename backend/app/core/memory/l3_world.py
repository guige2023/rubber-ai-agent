"""
L3 World Model - Compressed environmental cognition.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .neo4j_client import Neo4jClient, get_neo4j_client

logger = logging.getLogger(__name__)


@dataclass
class WorldModel:
    """
    World Model - compressed representation of environmental knowledge.

    Derived from L2 policies, captures:
    - Environment topology (what exists and how it's structured)
    - Inference rules (cause-effect relationships)
    - Constraints (what can/cannot be done)
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    domain_key: str = ""  # Key for grouping related models
    environment: str = ""  # Description of environment structure
    inference_rules: str = ""  # Inferred cause-effect relationships
    constraints: str = ""  # What cannot be done
    confidence: float = 0.0  # Confidence score (0-1)
    policy_ids: list[str] = field(default_factory=list)  # Source policies
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict = field(default_factory=dict)


class WorldModelMemory:
    """
    L3 World Model Memory - stores environmental cognition.

    World models are abstractions derived from L2 policies,
    representing higher-level understanding of the environment.
    """

    def __init__(self, client: Optional[Neo4jClient] = None):
        self._client = client

    @property
    def client(self) -> Neo4jClient:
        if self._client is None:
            self._client = get_neo4j_client()
        return self._client

    async def add_world_model(self, model: WorldModel) -> WorldModel:
        """Add a new world model."""
        query = """
        CREATE (w:WorldModel {
            id: $id,
            domain_key: $domain_key,
            environment: $environment,
            inference_rules: $inference_rules,
            constraints: $constraints,
            confidence: $confidence,
            policy_ids: $policy_ids,
            created_at: datetime($created_at),
            updated_at: datetime($updated_at),
            metadata: $metadata
        })
        RETURN w
        """

        params = {
            "id": model.id,
            "domain_key": model.domain_key,
            "environment": model.environment,
            "inference_rules": model.inference_rules,
            "constraints": model.constraints,
            "confidence": model.confidence,
            "policy_ids": str(model.policy_ids),
            "created_at": model.created_at.isoformat(),
            "updated_at": model.updated_at.isoformat(),
            "metadata": str(model.metadata),
        }

        await self.client.execute_write(query, params)

        # Create relationships to source policies
        for policy_id in model.policy_ids:
            rel_query = """
            MATCH (w:WorldModel {id: $world_id})
            MATCH (p:Policy {id: $policy_id})
            CREATE (w)-[:DERIVED_FROM]->(p)
            """
            await self.client.execute_write(
                rel_query,
                {"world_id": model.id, "policy_id": policy_id},
            )

        logger.info(f"Created world model {model.id} for domain {model.domain_key}")
        return model

    async def get_by_domain(self, domain_key: str) -> list[WorldModel]:
        """Get world models for a domain."""
        query = """
        MATCH (w:WorldModel {domain_key: $domain_key})
        RETURN w
        ORDER BY w.confidence DESC
        """

        results = await self.client.execute_query(query, {"domain_key": domain_key})

        models = []
        for record in results:
            w = record.get("w", {})
            models.append(
                WorldModel(
                    id=w.get("id", ""),
                    domain_key=w.get("domain_key", ""),
                    environment=w.get("environment", ""),
                    inference_rules=w.get("inference_rules", ""),
                    constraints=w.get("constraints", ""),
                    confidence=float(w.get("confidence", 0.0)),
                    created_at=datetime.fromisoformat(w.get("created_at", datetime.utcnow().isoformat())),
                )
            )
        return models

    async def get_high_confidence(self, min_confidence: float = 0.7) -> list[WorldModel]:
        """Get world models above confidence threshold."""
        query = """
        MATCH (w:WorldModel)
        WHERE w.confidence >= $min_confidence
        RETURN w
        ORDER BY w.confidence DESC
        """

        results = await self.client.execute_query(
            query,
            {"min_confidence": min_confidence},
        )

        models = []
        for record in results:
            w = record.get("w", {})
            models.append(
                WorldModel(
                    id=w.get("id", ""),
                    domain_key=w.get("domain_key", ""),
                    environment=w.get("environment", ""),
                    inference_rules=w.get("inference_rules", ""),
                    constraints=w.get("constraints", ""),
                    confidence=float(w.get("confidence", 0.0)),
                )
            )
        return models

    async def update_confidence(
        self,
        model_id: str,
        new_confidence: float,
    ) -> bool:
        """Update a world model's confidence."""
        query = """
        MATCH (w:WorldModel {id: $id})
        SET w.confidence = $confidence,
            w.updated_at = datetime()
        """

        result = await self.client.execute_write(
            query,
            {"id": model_id, "confidence": new_confidence},
        )

        return result.get("counters", {}).get("properties_set", 0) > 0

    async def merge_into_existing(
        self,
        source_model_id: str,
        target_model_id: str,
    ) -> bool:
        """
        Merge source model into target model.

        Combines the source's policies into the target and removes source.
        """
        # Update target with source's policies
        merge_query = """
        MATCH (source:WorldModel {id: $source_id})
        MATCH (target:WorldModel {id: $target_id})
        SET target.policy_ids = target.policy_ids + source.policy_ids,
            target.confidence = (target.confidence + source.confidence) / 2,
            target.updated_at = datetime()
        WITH source
        // Create links from source's policies to target
        MATCH (source)-[r:DERIVED_FROM]->(p:Policy)
        MERGE (target)-[:DERIVED_FROM]->(p)
        DELETE r
        DELETE source
        """

        try:
            await self.client.execute_write(
                merge_query,
                {"source_id": source_model_id, "target_id": target_model_id},
            )
            return True
        except Exception as e:
            logger.error(f"Failed to merge world models: {e}")
            return False
