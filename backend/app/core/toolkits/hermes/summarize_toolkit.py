"""
Summarize Toolkit - URL/file/YouTube summarization.

Integrates native summarization using LLM providers with proper
chunked processing for large content.
"""

import asyncio
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.core.deps import AgentDeps
from app.core.toolkits.base import Toolkit

logger = logging.getLogger(__name__)

# Content size limits
MAX_CONTENT_SIZE = 2_000_000  # 2M chars - refuse entirely above this
CHUNK_THRESHOLD = 500_000     # 500k chars - use chunked processing above this
CHUNK_SIZE = 100_000          # 100k chars per chunk
MAX_OUTPUT_SIZE = 5000        # Hard cap on final output size


@dataclass
class SummarizeConfig:
    """Summarize configuration."""

    # LLM provider
    provider: str = "openai"  # openai, anthropic, gemini, xai
    model: str = "gpt-4o-mini"

    # API keys
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    xai_api_key: Optional[str] = None

    # API base URLs (for proxies)
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_base_url: str = "https://api.anthropic.com/v1"

    # Optional services
    firecrawl_api_key: Optional[str] = None
    apify_api_key: Optional[str] = None


class SummarizeToolkit(Toolkit):
    """
    Summarization toolkit.

    Tools:
    - summarize_url: Summarize a URL
    - summarize_file: Summarize a local file
    - summarize_youtube: Summarize a YouTube video
    - extract_content: Extract raw content without summarization
    """

    name = "summarize"

    @classmethod
    def get_tools(cls) -> list:
        return [
            cls.summarize_url,
            cls.summarize_file,
            cls.summarize_youtube,
            cls.extract_content,
        ]

    def __init__(self, config: Optional[SummarizeConfig] = None):
        self.config = config or SummarizeConfig()

    async def summarize_url(
        self,
        ctx: AgentDeps,
        url: str,
        prompt: Optional[str] = None,
        use_firecrawl: bool = True,
    ) -> dict:
        """
        Summarize content from a URL.

        Args:
            url: URL to summarize
            prompt: Optional custom prompt
            use_firecrawl: Use Firecrawl for better extraction
        """
        # First, extract content
        extract_result = await self.extract_content(ctx, url)

        if "error" in extract_result:
            return extract_result

        content = extract_result.get("content", "")

        if not content:
            return {"error": "No content extracted from URL"}

        # Summarize using LLM
        return await self._summarize_text(
            content,
            prompt or f"Summarize this content from {url}",
        )

    async def summarize_file(
        self,
        ctx: AgentDeps,
        file_path: str,
        prompt: Optional[str] = None,
    ) -> dict:
        """
        Summarize a local file.

        Args:
            file_path: Path to file
            prompt: Optional custom prompt
        """
        if not os.path.exists(file_path):
            return {"error": f"File not found: {file_path}"}

        # Read file content
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            return {"error": f"Failed to read file: {e}"}

        # Truncate if too large
        if len(content) > MAX_CONTENT_SIZE:
            content = content[:MAX_CONTENT_SIZE] + "\n\n[Truncated]"

        # Summarize using LLM
        return await self._summarize_text(
            content,
            prompt or f"Summarize this file: {file_path}",
        )

    async def summarize_youtube(
        self,
        ctx: AgentDeps,
        url: str,
        prompt: Optional[str] = None,
        use_apify: bool = True,
    ) -> dict:
        """
        Summarize a YouTube video by extracting transcript.

        Args:
            url: YouTube URL
            prompt: Optional custom prompt
            use_apify: Use Apify for transcript extraction
        """
        # Try to get transcript via YouTube transcript API or scrape
        transcript_text = await self._get_youtube_transcript(url)

        if not transcript_text:
            return {
                "error": "Could not extract transcript from YouTube video. "
                        "The video may not have captions or may be unavailable."
            }

        # Summarize using LLM
        return await self._summarize_text(
            transcript_text,
            prompt or f"Summarize this YouTube video: {url}",
        )

    async def extract_content(
        self,
        ctx: AgentDeps,
        url: str,
        mode: str = "content",
    ) -> dict:
        """
        Extract raw content from URL without summarization.

        Args:
            url: URL to extract from
            mode: "content" (text), "markdown", "html"
        """
        # Use httpx.AsyncClient for async HTTP requests
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            try:
                response = await client.get(url)
                response.raise_for_status()

                if mode == "html":
                    return {
                        "content": response.text,
                        "url": url,
                        "content_type": "html",
                    }

                # Extract text from HTML
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(response.text, "html.parser")

                # Remove script and style elements
                for script in soup(["script", "style"]):
                    script.decompose()

                text = soup.get_text(separator="\n", strip=True)

                # Clean up whitespace
                lines = [line.strip() for line in text.split("\n") if line.strip()]
                text = "\n".join(lines)

                return {
                    "content": text[:MAX_CONTENT_SIZE] if len(text) > MAX_CONTENT_SIZE else text,
                    "url": url,
                    "content_type": mode,
                    "message": f"Extracted {len(text)} chars",
                }

            except ImportError:
                return {"error": "beautifulsoup4 not installed: pip install beautifulsoup4"}
            except httpx.HTTPError as e:
                return {"error": f"HTTP error fetching URL: {e}"}
            except Exception as e:
                logger.exception("Content extraction failed")
                return {"error": str(e)}

    async def _get_youtube_transcript(self, url: str) -> Optional[str]:
        """
        Extract transcript from YouTube video using ytb Transparency project's API.

        Returns:
            Transcript text or None if extraction failed
        """
        try:
            # Extract video ID from URL
            video_id = self._extract_youtube_id(url)
            if not video_id:
                return None

            # Try ytb Transparency API (no auth required)
            api_url = f"https://ytb.twm.sh/transcript/{video_id}"

            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(api_url)
                if response.status_code == 200:
                    data = response.json()
                    if "transcript" in data:
                        return data["transcript"]

            return None

        except Exception as e:
            logger.debug("YouTube transcript extraction failed: %s", e)
            return None

    def _extract_youtube_id(self, url: str) -> Optional[str]:
        """Extract YouTube video ID from URL."""
        import re
        patterns = [
            r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})',
            r'youtube\.com/shorts/([a-zA-Z0-9_-]{11})',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    async def _summarize_text(self, text: str, prompt: str) -> dict:
        """
        Summarize text using LLM API with chunked processing for large content.

        Args:
            text: Text to summarize
            prompt: Summarization prompt/instruction

        Returns:
            Summary result dict
        """
        content_len = len(text)

        # Refuse if content is absurdly large
        if content_len > MAX_CONTENT_SIZE:
            size_mb = content_len / 1_000_000
            return {
                "error": f"Content too large to process: {size_mb:.1f}MB. "
                         f"Maximum is {MAX_CONTENT_SIZE // 1_000_000}MB."
            }

        try:
            # Check if we need chunked processing
            if content_len > CHUNK_THRESHOLD:
                return await self._summarize_chunked(text, prompt)

            # Standard single-pass processing
            return await self._summarize_single(text, prompt)

        except Exception as e:
            logger.exception("Summarization failed")
            return {
                "error": f"Summarization failed: {str(e)}",
                "chars_processed": content_len,
            }

    async def _summarize_single(self, text: str, prompt: str) -> dict:
        """Make a single LLM call to summarize content."""
        # Build messages
        system_prompt = """You are an expert content analyst. Create a comprehensive yet concise summary that preserves all important information while dramatically reducing bulk.

Create a well-structured markdown summary that includes:
1. Key excerpts (quotes, code snippets, important facts) in their original format
2. Comprehensive summary of all other important information
3. Proper markdown formatting with headers, bullets, and emphasis

Your goal is to preserve ALL important information while reducing length."""

        user_prompt = f"""{prompt}

CONTENT TO PROCESS:
{text}

Create a markdown summary that captures all key information."""

        # Call LLM
        response_text = await self._call_llm(system_prompt, user_prompt)

        if not response_text:
            return {
                "error": "LLM returned empty response",
                "chars_processed": len(text),
            }

        # Enforce output cap
        if len(response_text) > MAX_OUTPUT_SIZE:
            response_text = response_text[:MAX_OUTPUT_SIZE] + "\n\n[... summary truncated ...]"

        return {
            "success": True,
            "summary": response_text,
            "source": "llm_api",
            "chars_processed": len(text),
            "summary_length": len(response_text),
        }

    async def _summarize_chunked(self, text: str, prompt: str) -> dict:
        """
        Process large content by chunking, summarizing each chunk in parallel,
        then synthesizing the summaries.
        """
        # Split content into chunks
        chunks = []
        for i in range(0, len(text), CHUNK_SIZE):
            chunk = text[i:i + CHUNK_SIZE]
            chunks.append(chunk)

        logger.info("Summarizing %d chars in %d chunks", len(text), len(chunks))

        # Summarize each chunk in parallel
        async def summarize_chunk(chunk_idx: int, chunk_content: str) -> tuple[int, Optional[str]]:
            """Summarize a single chunk."""
            try:
                chunk_info = f"[Processing chunk {chunk_idx + 1} of {len(chunks)}]"
                system_prompt = """You are an expert content analyst processing a SECTION of a larger document. Your job is to extract and summarize the key information from THIS SECTION ONLY.

Important guidelines for chunk processing:
1. Do NOT write introductions or conclusions - this is a partial document
2. Focus on extracting ALL key facts, figures, data points, and insights from this section
3. Preserve important quotes, code snippets, and specific details verbatim
4. Use bullet points and structured formatting for easy synthesis later"""

                user_prompt = f"""Extract key information from this SECTION of a larger document:

{chunk_info}

SECTION CONTENT:
{chunk_content}

Extract all important information from this section in a structured format."""

                summary = await self._call_llm(system_prompt, user_prompt)
                return chunk_idx, summary
            except Exception as e:
                logger.warning("Chunk %d/%d failed: %s", chunk_idx + 1, len(chunks), str(e)[:50])
                return chunk_idx, None

        # Run all chunk summarizations in parallel
        tasks = [summarize_chunk(i, chunk) for i, chunk in enumerate(chunks)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions, collect successful summaries in order
        successful_results = []
        for result_item in results:
            if isinstance(result_item, BaseException):
                logger.warning("Chunk summarization task failed: %s", result_item)
                continue
            successful_results.append(result_item)

        summaries = []
        for chunk_idx, summary in sorted(successful_results, key=lambda x: x[0]):
            if summary:
                summaries.append(f"## Section {chunk_idx + 1}\n{summary}")

        if not summaries:
            return {
                "error": "All chunk summarizations failed",
                "chars_processed": len(text),
            }

        # If only one chunk succeeded, just return it
        if len(summaries) == 1:
            result = summaries[0]
            if len(result) > MAX_OUTPUT_SIZE:
                result = result[:MAX_OUTPUT_SIZE] + "\n\n[... truncated ...]"
            return {
                "success": True,
                "summary": result,
                "source": "llm_api_chunked",
                "chars_processed": len(text),
            }

        # Synthesize the summaries
        combined = "\n\n---\n\n".join(summaries)

        synthesis_prompt = f"""You have been given summaries of different sections of a large document.
Synthesize these into ONE cohesive, comprehensive summary that:
1. Removes redundancy between sections
2. Preserves all key facts, figures, and actionable information
3. Is well-organized with clear structure
4. Is under {MAX_OUTPUT_SIZE} characters

SECTION SUMMARIES:
{combined}

Create a single, unified markdown summary."""

        final_summary = await self._call_llm(
            "You synthesize multiple summaries into one cohesive summary.",
            synthesis_prompt
        )

        if not final_summary:
            # Fall back to concatenated summaries
            fallback = "\n\n".join(summaries)
            if len(fallback) > MAX_OUTPUT_SIZE:
                fallback = fallback[:MAX_OUTPUT_SIZE] + "\n\n[... truncated ...]"
            return {
                "success": True,
                "summary": fallback,
                "source": "llm_api_concatenated",
                "chars_processed": len(text),
            }

        # Enforce hard cap
        if len(final_summary) > MAX_OUTPUT_SIZE:
            final_summary = final_summary[:MAX_OUTPUT_SIZE] + "\n\n[... summary truncated ...]"

        return {
            "success": True,
            "summary": final_summary,
            "source": "llm_api_synthesized",
            "chars_processed": len(text),
            "chunks_processed": len(summaries),
        }

    async def _call_llm(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """
        Make an LLM API call using httpx.AsyncClient.

        Args:
            system_prompt: System prompt
            user_prompt: User prompt

        Returns:
            LLM response text or None on failure
        """
        provider = self.config.provider.lower()

        if provider == "openai":
            return await self._call_openai(system_prompt, user_prompt)
        elif provider == "anthropic":
            return await self._call_anthropic(system_prompt, user_prompt)
        elif provider == "xai":
            return await self._call_xai(system_prompt, user_prompt)
        else:
            # Default to OpenAI-compatible API
            return await self._call_openai(system_prompt, user_prompt)

    async def _call_openai(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """Call OpenAI-compatible API."""
        api_key = self.config.openai_api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            logger.error("No OpenAI API key configured")
            return None

        base_url = self.config.openai_base_url

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 20000,
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

                # Handle different response formats
                if "choices" in data and len(data["choices"]) > 0:
                    return data["choices"][0]["message"]["content"]
                elif "content" in data:
                    return data["content"]

                return None

        except httpx.HTTPError as e:
            logger.error("OpenAI API call failed: %s", e)
            return None

    async def _call_anthropic(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """Call Anthropic API."""
        api_key = self.config.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            logger.error("No Anthropic API key configured")
            return None

        base_url = self.config.anthropic_base_url

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.config.model,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 8192,
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{base_url}/messages",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

                if "content" in data and len(data["content"]) > 0:
                    return data["content"][0]["text"]

                return None

        except httpx.HTTPError as e:
            logger.error("Anthropic API call failed: %s", e)
            return None

    async def _call_xai(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """Call xAI API."""
        api_key = self.config.xai_api_key or os.environ.get("XAI_API_KEY")
        if not api_key:
            logger.error("No xAI API key configured")
            return None

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 20000,
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    "https://api.x.ai/v1/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

                if "choices" in data and len(data["choices"]) > 0:
                    return data["choices"][0]["message"]["content"]

                return None

        except httpx.HTTPError as e:
            logger.error("xAI API call failed: %s", e)
            return None
