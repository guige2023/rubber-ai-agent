"""
Neo4j Client - Connection management for Neo4j graph database.
"""

import logging
from contextlib import asynccontextmanager
from typing import Optional, AsyncIterator
import json

logger = logging.getLogger(__name__)

# Global client instance
_neo4j_client: Optional["Neo4jClient"] = None


class Neo4jClient:
    """
    Neo4j database client for memory graph storage.

    Handles connection, queries, and transaction management.
    """

    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        username: str = "neo4j",
        password: str = "password",
        database: str = "neo4j",
    ):
        self.uri = uri
        self.username = username
        self.password = password
        self.database = database
        self._driver = None
        self._connected = False

    async def connect(self) -> None:
        """Connect to Neo4j."""
        try:
            from neo4j import AsyncGraphDatabase

            self._driver = AsyncGraphDatabase.driver(
                self.uri,
                auth=(self.username, self.password),
            )
            # Verify connection
            await self._driver.verify_connectivity()
            self._connected = True
            logger.info(f"Connected to Neo4j at {self.uri}")
        except ImportError:
            logger.error("neo4j package not installed. Install with: pip install neo4j>=5.0.0")
            raise
        except Exception as e:
            logger.error(f"Failed to connect to Neo4j: {e}")
            raise

    async def disconnect(self) -> None:
        """Disconnect from Neo4j."""
        if self._driver:
            await self._driver.close()
            self._connected = False
            logger.info("Disconnected from Neo4j")

    @property
    def is_connected(self) -> bool:
        return self._connected

    @asynccontextmanager
    async def session(self) -> AsyncIterator:
        """Get a Neo4j session."""
        if not self._driver:
            raise RuntimeError("Not connected to Neo4j")
        session = self._driver.session(database=self.database)
        try:
            yield session
        finally:
            await session.close()

    async def execute_query(
        self,
        query: str,
        parameters: Optional[dict] = None,
    ) -> list[dict]:
        """
        Execute a Cypher query and return results.

        Args:
            query: Cypher query string
            parameters: Query parameters

        Returns:
            List of result records as dicts
        """
        async with self.session() as session:
            result = await session.run(query, parameters or {})
            records = await result.data()
            return records

    async def execute_write(
        self,
        query: str,
        parameters: Optional[dict] = None,
    ) -> dict:
        """
        Execute a write transaction.

        Args:
            query: Cypher query string
            parameters: Query parameters

        Returns:
            Summary of the write operation
        """
        async with self.session() as session:
            result = await session.run(query, parameters or {})
            summary = await result.consume()
            return {
                "counters": summary.counters,
                "query_type": summary.query_type,
            }

    async def init_schema(self) -> None:
        """
        Initialize Neo4j schema with constraints and indexes.

        Creates:
        - Constraints for unique IDs
        - Indexes for common query patterns
        """
        constraints = [
            # Trace nodes
            "CREATE CONSTRAINT trace_id IF NOT EXISTS FOR (t:Trace) REQUIRE t.id IS UNIQUE",
            # Policy nodes
            "CREATE CONSTRAINT policy_id IF NOT EXISTS FOR (p:Policy) REQUIRE p.id IS UNIQUE",
            # WorldModel nodes
            "CREATE CONSTRAINT worldmodel_id IF NOT EXISTS FOR (w:WorldModel) REQUIRE w.id IS UNIQUE",
            # Skill nodes
            "CREATE CONSTRAINT skill_id IF NOT EXISTS FOR (s:CrystallizedSkill) REQUIRE s.id IS UNIQUE",
            # Session nodes
            "CREATE CONSTRAINT session_id IF NOT EXISTS FOR (s:Session) REQUIRE s.id IS UNIQUE",
        ]

        indexes = [
            "CREATE INDEX trace_session IF NOT EXISTS FOR (t:Trace) ON (t.session_id)",
            "CREATE INDEX trace_created_at IF NOT EXISTS FOR (t:Trace) ON (t.created_at)",
            "CREATE INDEX policy_signature IF NOT EXISTS FOR (p:Policy) ON (p.signature)",
            "CREATE INDEX policy_status IF NOT EXISTS FOR (p:Policy) ON (p.status)",
            "CREATE INDEX skill_eta IF NOT EXISTS FOR (s:CrystallizedSkill) ON (s.eta)",
            "CREATE INDEX worldmodel_confidence IF NOT EXISTS FOR (w:WorldModel) ON (w.confidence)",
        ]

        async with self.session() as session:
            for constraint in constraints:
                try:
                    await session.run(constraint)
                except Exception as e:
                    # Constraint may already exist
                    logger.debug(f"Constraint creation: {e}")

            for index in indexes:
                try:
                    await session.run(index)
                except Exception as e:
                    # Index may already exist
                    logger.debug(f"Index creation: {e}")

        logger.info("Neo4j schema initialized")


def get_neo4j_client() -> Neo4jClient:
    """Get the global Neo4j client instance."""
    global _neo4j_client
    if _neo4j_client is None:
        import os

        _neo4j_client = Neo4jClient(
            uri=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
            username=os.environ.get("NEO4J_USERNAME", "neo4j"),
            password=os.environ.get("NEO4J_PASSWORD", "password"),
            database=os.environ.get("NEO4J_DATABASE", "neo4j"),
        )
    return _neo4j_client


async def init_neo4j() -> Neo4jClient:
    """Initialize and connect the global Neo4j client."""
    client = get_neo4j_client()
    await client.connect()
    await client.init_schema()
    return client
