"""
Web Search Toolkit - Hermes's web search and extraction.

Provides:
- Web search (Tavily, Exa, Brave, DuckDuckGo)
- Content extraction (Firecrawl)
- Web crawling
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.core.deps import AgentDeps
from app.core.toolkits.base import Toolkit

logger = logging.getLogger(__name__)


@dataclass
class WebSearchConfig:
    """Web search configuration."""

    # Backend provider
    backend: str = "auto"  # auto, tavily, exa, firecrawl, brave, ddgs

    # API keys
    tavily_api_key: Optional[str] = None
    exa_api_key: Optional[str] = None
    firecrawl_api_key: Optional[str] = None
    brave_api_key: Optional[str] = None
    parallel_api_key: Optional[str] = None

    # Settings
    max_results: int = 10
    search_timeout: int = 30


class WebSearchToolkit(Toolkit):
    """
    Web search and extraction toolkit.

    Tools:
    - web_search: Search the web
    - web_extract: Extract content from URLs
    - web_crawl: Crawl a website with LLM guidance
    """

    name = "web_search"

    @classmethod
    def get_tools(cls) -> list:
        return [
            cls.web_search,
            cls.web_extract,
            cls.web_crawl,
        ]

    def __init__(self, config: Optional[WebSearchConfig] = None):
        self.config = config or WebSearchConfig()

    def _get_backend(self) -> str:
        """Determine which web backend to use."""
        if self.config.backend != "auto":
            return self.config.backend

        # Auto-detect from available API keys
        if self.config.firecrawl_api_key or os.environ.get("FIRECRAWL_API_KEY"):
            return "firecrawl"
        if self.config.tavily_api_key or os.environ.get("TAVILY_API_KEY"):
            return "tavily"
        if self.config.exa_api_key or os.environ.get("EXA_API_KEY"):
            return "exa"
        if self.config.parallel_api_key or os.environ.get("PARALLEL_API_KEY"):
            return "parallel"
        if self.config.brave_api_key or os.environ.get("BRAVE_SEARCH_API_KEY"):
            return "brave"

        return "ddgs"  # Default to DuckDuckGo

    async def web_search(
        self,
        ctx: AgentDeps,
        query: str,
        limit: int = 10,
    ) -> dict:
        """
        Search the web.

        Args:
            query: Search query
            limit: Maximum number of results
        """
        limit = min(limit, self.config.max_results)
        backend = self._get_backend()

        # Try the selected backend, fall back to others
        if backend == "tavily":
            result = await self._search_tavily(query, limit)
            if "error" not in result:
                return result
            # Fall through to try others

        if backend == "exa":
            result = await self._search_exa(query, limit)
            if "error" not in result:
                return result

        if backend == "parallel":
            result = await self._search_parallel(query, limit)
            if "error" not in result:
                return result

        if backend == "firecrawl":
            result = await self._search_firecrawl(query, limit)
            if "error" not in result:
                return result

        if backend == "brave":
            result = await self._search_brave(query, limit)
            if "error" not in result:
                return result

        # Default to DuckDuckGo
        return await self._search_ddgs(query, limit)

    async def web_extract(
        self,
        ctx: AgentDeps,
        urls: list[str],
        prompt: Optional[str] = None,
        use_llm: bool = True,
    ) -> dict:
        """
        Extract content from URLs.

        Args:
            urls: List of URLs to extract from
            prompt: Optional prompt for LLM processing
            use_llm: Whether to use LLM for summarization
        """
        backend = self._get_backend()

        # Try firecrawl first for best results
        if self.config.firecrawl_api_key or os.environ.get("FIRECRAWL_API_KEY"):
            result = await self._extract_firecrawl(urls, prompt, use_llm)
            if "error" not in result:
                return result

        if backend == "tavily" and (self.config.tavily_api_key or os.environ.get("TAVILY_API_KEY")):
            result = await self._extract_tavily(urls, prompt)
            if "error" not in result:
                return result

        if backend == "parallel" and (self.config.parallel_api_key or os.environ.get("PARALLEL_API_KEY")):
            result = await self._extract_parallel(urls)
            if "error" not in result:
                return result

        if backend == "exa" and (self.config.exa_api_key or os.environ.get("EXA_API_KEY")):
            result = await self._extract_exa(urls)
            if "error" not in result:
                return result

        # Fall back to basic extraction
        return await self._extract_basic(urls)

    async def web_crawl(
        self,
        ctx: AgentDeps,
        url: str,
        instructions: str,
        depth: str = "basic",
    ) -> dict:
        """
        Crawl a website with LLM-guided extraction.

        Args:
            url: Starting URL
            instructions: What to extract (LLM instructions)
            depth: "basic" or "advanced"
        """
        if self.config.firecrawl_api_key or os.environ.get("FIRECRAWL_API_KEY"):
            return await self._crawl_firecrawl(url, instructions, depth)

        if self.config.tavily_api_key or os.environ.get("TAVILY_API_KEY"):
            return await self._crawl_tavily(url, instructions, depth)

        return {
            "error": "Web crawl requires Firecrawl or Tavily API key. "
                    "Set FIRECRAWL_API_KEY or TAVILY_API_KEY environment variable."
        }

    # === Search Providers ===

    async def _search_tavily(self, query: str, limit: int) -> dict:
        """Search using Tavily API."""
        api_key = self.config.tavily_api_key or os.environ.get("TAVILY_API_KEY")
        if not api_key:
            return {"error": "Tavily API key not configured"}

        try:
            async with httpx.AsyncClient(timeout=self.config.search_timeout) as client:
                response = await client.post(
                    "https://api.tavily.com/search",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "query": query,
                        "max_results": limit,
                        "include_answer": True,
                        "include_raw_content": False,
                    },
                )
                response.raise_for_status()
                data = response.json()

                results = [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "description": r.get("description", ""),
                        "score": r.get("score", 0),
                    }
                    for r in data.get("results", [])
                ]

                return {
                    "success": True,
                    "query": query,
                    "answer": data.get("answer"),
                    "results": results,
                    "total_results": len(results),
                    "source": "tavily",
                }

        except httpx.HTTPError as e:
            return {"error": f"Tavily search failed: {e}"}
        except Exception as e:
            logger.exception("Tavily search failed")
            return {"error": f"Tavily search failed: {e}"}

    async def _search_exa(self, query: str, limit: int) -> dict:
        """Search using Exa API."""
        api_key = self.config.exa_api_key or os.environ.get("EXA_API_KEY")
        if not api_key:
            return {"error": "Exa API key not configured"}

        try:
            async with httpx.AsyncClient(timeout=self.config.search_timeout) as client:
                response = await client.post(
                    "https://api.exa.ai/search",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "query": query,
                        "numResults": limit,
                        "text": {"maxCharacters": 1000},
                    },
                )
                response.raise_for_status()
                data = response.json()

                results = [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "description": r.get("text", "")[:500],
                        "score": r.get("score", 0),
                    }
                    for r in data.get("results", [])
                ]

                return {
                    "success": True,
                    "query": query,
                    "results": results,
                    "total_results": len(results),
                    "source": "exa",
                }

        except httpx.HTTPError as e:
            return {"error": f"Exa search failed: {e}"}
        except Exception as e:
            logger.exception("Exa search failed")
            return {"error": f"Exa search failed: {e}"}

    async def _search_parallel(self, query: str, limit: int) -> dict:
        """Search using Parallel API."""
        api_key = self.config.parallel_api_key or os.environ.get("PARALLEL_API_KEY")
        if not api_key:
            return {"error": "Parallel API key not configured"}

        try:
            async with httpx.AsyncClient(timeout=self.config.search_timeout) as client:
                response = await client.post(
                    "https://api.parallel.ai/v1/search",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "query": query,
                        "limit": limit,
                    },
                )
                response.raise_for_status()
                data = response.json()

                results = [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "description": r.get("snippet", ""),
                    }
                    for r in data.get("results", [])
                ]

                return {
                    "success": True,
                    "query": query,
                    "results": results,
                    "total_results": len(results),
                    "source": "parallel",
                }

        except httpx.HTTPError as e:
            return {"error": f"Parallel search failed: {e}"}
        except Exception as e:
            logger.exception("Parallel search failed")
            return {"error": f"Parallel search failed: {e}"}

    async def _search_firecrawl(self, query: str, limit: int) -> dict:
        """Search using Firecrawl API."""
        api_key = self.config.firecrawl_api_key or os.environ.get("FIRECRAWL_API_KEY")
        if not api_key:
            return {"error": "Firecrawl API key not configured"}

        try:
            async with httpx.AsyncClient(timeout=self.config.search_timeout) as client:
                response = await client.post(
                    "https://api.firecrawl.dev/v0/search",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "query": query,
                        "limit": limit,
                    },
                )
                response.raise_for_status()
                data = response.json()

                results = [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "description": r.get("description", ""),
                    }
                    for r in data.get("data", [])
                ]

                return {
                    "success": True,
                    "query": query,
                    "results": results,
                    "total_results": len(results),
                    "source": "firecrawl",
                }

        except httpx.HTTPError as e:
            return {"error": f"Firecrawl search failed: {e}"}
        except Exception as e:
            logger.exception("Firecrawl search failed")
            return {"error": f"Firecrawl search failed: {e}"}

    async def _search_brave(self, query: str, limit: int) -> dict:
        """Search using Brave Search API."""
        api_key = self.config.brave_api_key or os.environ.get("BRAVE_SEARCH_API_KEY")
        if not api_key:
            return {"error": "Brave Search API key not configured"}

        try:
            async with httpx.AsyncClient(timeout=self.config.search_timeout) as client:
                response = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Accept": "application/json",
                    },
                    params={
                        "q": query,
                        "count": min(limit, 20),
                    },
                )
                response.raise_for_status()
                data = response.json()

                web_results = data.get("web", {}).get("results", [])
                results = [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "description": r.get("description", ""),
                    }
                    for r in web_results[:limit]
                ]

                return {
                    "success": True,
                    "query": query,
                    "results": results,
                    "total_results": len(results),
                    "source": "brave",
                }

        except httpx.HTTPError as e:
            return {"error": f"Brave search failed: {e}"}
        except Exception as e:
            logger.exception("Brave search failed")
            return {"error": f"Brave search failed: {e}"}

    async def _search_ddgs(self, query: str, limit: int) -> dict:
        """Search using DuckDuckGo."""
        try:
            from duckduckgo_search import AsyncDDGS

            async with AsyncDDGS() as ddgs:
                results = []
                async for r in ddgs.text(query, max_results=limit):
                    results.append({
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "description": r.get("body", ""),
                    })

                return {
                    "success": True,
                    "query": query,
                    "results": results,
                    "total_results": len(results),
                    "source": "duckduckgo",
                }

        except ImportError:
            return {
                "error": "duckduckgo-search not installed. Run: pip install duckduckgo-search"
            }
        except Exception as e:
            logger.exception("DuckDuckGo search failed")
            return {"error": f"DuckDuckGo search failed: {e}"}

    # === Extraction Providers ===

    async def _extract_firecrawl(
        self,
        urls: list[str],
        prompt: Optional[str],
        use_llm: bool,
    ) -> dict:
        """Extract using Firecrawl."""
        api_key = self.config.firecrawl_api_key or os.environ.get("FIRECRAWL_API_KEY")
        if not api_key:
            return {"error": "Firecrawl API key not configured"}

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    "https://api.firecrawl.dev/v0/extract",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "urls": urls,
                        "prompt": prompt,
                        "onlyMainContent": True,
                    },
                )
                response.raise_for_status()
                data = response.json()

                return {
                    "success": True,
                    "data": data.get("data", []),
                    "source": "firecrawl",
                }

        except httpx.HTTPError as e:
            return {"error": f"Firecrawl extraction failed: {e}"}
        except Exception as e:
            logger.exception("Firecrawl extraction failed")
            return {"error": f"Firecrawl extraction failed: {e}"}

    async def _extract_tavily(
        self,
        urls: list[str],
        prompt: Optional[str],
    ) -> dict:
        """Extract using Tavily."""
        api_key = self.config.tavily_api_key or os.environ.get("TAVILY_API_KEY")
        if not api_key:
            return {"error": "Tavily API key not configured"}

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    "https://api.tavily.com/extract",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "urls": urls,
                        "prompt": prompt,
                    },
                )
                response.raise_for_status()
                data = response.json()

                return {
                    "success": True,
                    "data": data.get("results", []),
                    "source": "tavily",
                }

        except httpx.HTTPError as e:
            return {"error": f"Tavily extraction failed: {e}"}
        except Exception as e:
            logger.exception("Tavily extraction failed")
            return {"error": f"Tavily extraction failed: {e}"}

    async def _extract_parallel(self, urls: list[str]) -> dict:
        """Extract using Parallel API."""
        api_key = self.config.parallel_api_key or os.environ.get("PARALLEL_API_KEY")
        if not api_key:
            return {"error": "Parallel API key not configured"}

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    "https://api.parallel.ai/v1/extract",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "urls": urls,
                    },
                )
                response.raise_for_status()
                data = response.json()

                return {
                    "success": True,
                    "data": data.get("results", []),
                    "source": "parallel",
                }

        except httpx.HTTPError as e:
            return {"error": f"Parallel extraction failed: {e}"}
        except Exception as e:
            logger.exception("Parallel extraction failed")
            return {"error": f"Parallel extraction failed: {e}"}

    async def _extract_exa(self, urls: list[str]) -> dict:
        """Extract using Exa API."""
        api_key = self.config.exa_api_key or os.environ.get("EXA_API_KEY")
        if not api_key:
            return {"error": "Exa API key not configured"}

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    "https://api.exa.ai/extract",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "urls": urls,
                    },
                )
                response.raise_for_status()
                data = response.json()

                return {
                    "success": True,
                    "data": data.get("results", []),
                    "source": "exa",
                }

        except httpx.HTTPError as e:
            return {"error": f"Exa extraction failed: {e}"}
        except Exception as e:
            logger.exception("Exa extraction failed")
            return {"error": f"Exa extraction failed: {e}"}

    async def _extract_basic(self, urls: list[str]) -> dict:
        """Basic extraction without LLM using httpx."""
        results = []

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            for url in urls:
                try:
                    response = await client.get(url)
                    response.raise_for_status()

                    from bs4 import BeautifulSoup

                    soup = BeautifulSoup(response.text, "html.parser")

                    # Remove script and style elements
                    for element in soup(["script", "style"]):
                        element.decompose()

                    text = soup.get_text(separator="\n", strip=True)
                    lines = [line for line in text.split("\n") if line.strip()]
                    text = "\n".join(lines[:100])  # First 100 lines

                    results.append({
                        "url": url,
                        "content": text[:5000],
                        "title": soup.title.string if soup.title else "",
                    })
                except Exception as e:
                    results.append({
                        "url": url,
                        "error": str(e),
                    })

        return {
            "success": True,
            "data": results,
            "source": "basic",
        }

    # === Crawl Providers ===

    async def _crawl_firecrawl(
        self,
        url: str,
        instructions: str,
        depth: str,
    ) -> dict:
        """Crawl using Firecrawl."""
        api_key = self.config.firecrawl_api_key or os.environ.get("FIRECRAWL_API_KEY")
        if not api_key:
            return {"error": "Firecrawl API key not configured"}

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    "https://api.firecrawl.dev/v0/crawl",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "url": url,
                        "prompt": instructions,
                        "depth": depth,
                        "onlyMainContent": True,
                    },
                )
                response.raise_for_status()
                data = response.json()

                return {
                    "success": True,
                    "data": data.get("data", []),
                    "source": "firecrawl_crawl",
                }

        except httpx.HTTPError as e:
            return {"error": f"Firecrawl crawl failed: {e}"}
        except Exception as e:
            logger.exception("Firecrawl crawl failed")
            return {"error": f"Firecrawl crawl failed: {e}"}

    async def _crawl_tavily(
        self,
        url: str,
        instructions: str,
        depth: str,
    ) -> dict:
        """Crawl using Tavily."""
        api_key = self.config.tavily_api_key or os.environ.get("TAVILY_API_KEY")
        if not api_key:
            return {"error": "Tavily API key not configured"}

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    "https://api.tavily.com/crawl",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "urls": [url],
                        "prompt": instructions,
                        "crawl_depth": 1 if depth == "basic" else 3,
                    },
                )
                response.raise_for_status()
                data = response.json()

                return {
                    "success": True,
                    "data": data.get("results", []),
                    "source": "tavily_crawl",
                }

        except httpx.HTTPError as e:
            return {"error": f"Tavily crawl failed: {e}"}
        except Exception as e:
            logger.exception("Tavily crawl failed")
            return {"error": f"Tavily crawl failed: {e}"}
