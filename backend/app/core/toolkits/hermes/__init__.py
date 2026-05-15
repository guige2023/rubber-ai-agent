"""
Hermes Integration Toolkit - Bridges Hermes agent capabilities to RabAiAgent.

This module integrates:
- Browser automation (computer use)
- Web search and extraction
- Voice/TTS capabilities
- Advanced file operations
"""

from .browser_toolkit import BrowserToolkit
from .voice_toolkit import VoiceToolkit
from .summarize_toolkit import SummarizeToolkit
from .web_search_toolkit import WebSearchToolkit

__all__ = [
    "BrowserToolkit",
    "VoiceToolkit",
    "SummarizeToolkit",
    "WebSearchToolkit",
]
