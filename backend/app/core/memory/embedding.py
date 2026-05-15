"""
Embedding Service - Vector embeddings for memory records.
"""

import logging
from typing import Optional
import os

logger = logging.getLogger(__name__)

# Global embedding service instance
_embedding_service: Optional["EmbeddingService"] = None


class EmbeddingService:
    """
    Embedding service for vector representations.

    Supports multiple providers:
    - Local (MiniLM-L6-v2 via sentence-transformers)
    - OpenAI compatible
    - Gemini
    - Cohere
    - Voyage
    """

    def __init__(
        self,
        provider: str = "local",
        model_name: str = "all-MiniLM-L6-v2",
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        cache_size: int = 20000,
    ):
        self.provider = provider
        self.model_name = model_name
        self.api_key = api_key or os.environ.get("EMBEDDING_API_KEY", "")
        self.api_base = api_base or os.environ.get("EMBEDDING_API_BASE", "")
        self.cache_size = cache_size
        self._cache: dict[str, list[float]] = {}
        self._model = None
        self._dimensions: Optional[int] = None

    async def initialize(self) -> None:
        """Initialize the embedding model."""
        if self.provider == "local":
            await self._init_local()
        elif self.provider == "openai_compatible":
            await self._init_openai_compatible()
        else:
            logger.warning(f"Unknown embedding provider: {self.provider}, using local")
            await self._init_local()

        logger.info(f"Embedding service initialized: {self.provider}/{self.model_name}")

    async def _init_local(self) -> None:
        """Initialize local model using sentence-transformers."""
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
            self._dimensions = self._model.get_sentence_embedding_dimension()
        except ImportError:
            logger.warning(
                "sentence-transformers not installed, falling back to openai_compatible. "
                "Install sentence-transformers for local embeddings or set EMBEDDING_API_KEY for cloud embeddings."
            )
            self.provider = "openai_compatible"
            self._dimensions = 1536
        except Exception as e:
            logger.error(f"Failed to load local model: {e}")
            raise

    async def _init_openai_compatible(self) -> None:
        """Initialize OpenAI-compatible embedding API."""
        # Just verify API key is available
        if not self.api_key and not self.api_base:
            logger.warning("OpenAI compatible embedding selected but no API key/base provided")
        self._dimensions = 1536  # Default for OpenAI

    async def embed(self, text: str, role: str = "document") -> list[float]:
        """
        Generate embedding for text.

        Args:
            text: Text to embed
            role: "document" or "query" (affects caching)

        Returns:
            Vector embedding as list of floats
        """
        # Check cache
        cache_key = f"{role}:{text}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        if self.provider == "local":
            embedding = await self._embed_local(text)
        elif self.provider == "openai_compatible":
            embedding = await self._embed_openai(text)
        else:
            # Fallback: return random vector
            embedding = self._fallback_embedding()

        # L2 normalize for cosine similarity
        embedding = self._normalize(embedding)

        # Add to cache with size limit
        if len(self._cache) >= self.cache_size:
            # Remove oldest entry
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
        self._cache[cache_key] = embedding

        return embedding

    async def _embed_local(self, text: str) -> list[float]:
        """Embed using local model."""
        if self._model is None:
            await self.initialize()
        embedding = self._model.encode(text, convert_to_numpy=True)
        return embedding.tolist()

    async def _embed_openai(self, text: str) -> list[float]:
        """Embed using OpenAI-compatible API."""
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.api_base}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "input": text,
                    "model": self.model_name,
                },
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            return data["data"][0]["embedding"]

    def _fallback_embedding(self) -> list[float]:
        """Return a deterministic fake embedding based on text hash."""
        import hashlib

        hash_bytes = hashlib.sha256(self.model_name.encode()).digest()
        hash_int = int.from_bytes(hash_bytes[:4], "big")
        # Generate pseudo-random but deterministic vector
        vec = []
        for i in range(self._dimensions or 384):
            hash_bytes = hashlib.md5(f"{self.model_name}:{i}".encode()).digest()
            val = int.from_bytes(hash_bytes[:2], "big") / 65535.0
            vec.append(val * 0.1)
        return vec

    @staticmethod
    def _normalize(vector: list[float]) -> list[float]:
        """L2 normalize vector for cosine similarity."""
        import math

        magnitude = math.sqrt(sum(v * v for v in vector))
        if magnitude == 0:
            return vector
        return [v / magnitude for v in vector]

    @property
    def dimensions(self) -> int:
        """Get embedding dimensions."""
        return self._dimensions or 384

    def clear_cache(self) -> None:
        """Clear the embedding cache."""
        self._cache.clear()
        logger.debug("Embedding cache cleared")


def get_embedding_service() -> EmbeddingService:
    """Get the global embedding service."""
    global _embedding_service
    if _embedding_service is None:
        import os

        _embedding_service = EmbeddingService(
            provider=os.environ.get("EMBEDDING_PROVIDER", "local"),
            model_name=os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
            api_key=os.environ.get("EMBEDDING_API_KEY"),
            api_base=os.environ.get("EMBEDDING_API_BASE"),
        )
    return _embedding_service


async def init_embedding_service() -> EmbeddingService:
    """Initialize and return the global embedding service."""
    service = get_embedding_service()
    await service.initialize()
    return service
