"""
Voice Toolkit - Integrates Hermes's TTS and ASR capabilities.

Provides:
- Text-to-Speech (TTS) using edge-tts
- Speech-to-Text (STT) using faster-whisper
- Feishu voice message sending
"""

import asyncio
import base64
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from app.core.deps import AgentDeps
from app.core.toolkits.base import Toolkit

logger = logging.getLogger(__name__)


@dataclass
class VoiceConfig:
    """Voice configuration."""

    # TTS
    tts_provider: str = "edge"  # edge, openai
    tts_voice: str = "en-US-AriaNeural"
    tts_rate: str = "+0%"
    tts_pitch: str = "+0Hz"

    # STT
    stt_provider: str = "faster-whisper"  # faster-whisper
    whisper_model: str = "base"  # tiny, base, small, medium, large

    # Feishu voice (optional)
    feishu_voice_enabled: bool = False


# Global faster-whisper model cache
_local_model = None
_local_model_name: Optional[str] = None
_model_lock = asyncio.Lock()


def _looks_like_cuda_lib_error(exc: BaseException) -> bool:
    """Heuristic: is this exception a missing/broken CUDA runtime library?"""
    cuda_markers = (
        "CUDA error",
        "libcublas",
        "libcudnn",
        "nvrtc",
        "no CUDA-capable device",
        "CUDA driver version is insufficient",
    )
    msg = str(exc)
    return any(marker in msg for marker in cuda_markers)


async def _load_whisper_model(model_name: str):
    """Load faster-whisper model with graceful CUDA to CPU fallback."""
    global _local_model, _local_model_name

    if _local_model is not None and _local_model_name == model_name:
        return _local_model

    async with _model_lock:
        # Double-check after acquiring lock
        if _local_model is not None and _local_model_name == model_name:
            return _local_model

        try:
            from faster_whisper import WhisperModel
            try:
                _local_model = WhisperModel(model_name, device="auto", compute_type="auto")
            except Exception as exc:
                if not _looks_like_cuda_lib_error(exc):
                    raise
                logger.warning(
                    "faster-whisper CUDA load failed (%s) - falling back to CPU (int8)",
                    exc,
                )
                _local_model = WhisperModel(model_name, device="cpu", compute_type="int8")
            _local_model_name = model_name
            return _local_model
        except ImportError:
            raise RuntimeError("faster-whisper not installed. Run: pip install faster-whisper")


class VoiceToolkit(Toolkit):
    """
    Voice capabilities toolkit.

    Tools:
    - tts: Convert text to speech
    - stt: Convert speech to text
    - feishu_voice: Send voice message via Feishu
    """

    name = "voice"

    @classmethod
    def get_tools(cls) -> list:
        return [
            cls.tts,
            cls.stt,
            cls.feishu_voice,
        ]

    def __init__(self, config: Optional[VoiceConfig] = None):
        self.config = config or VoiceConfig()

    async def tts(
        self,
        ctx: AgentDeps,
        text: str,
        output_file: Optional[str] = None,
        voice: Optional[str] = None,
    ) -> dict:
        """
        Convert text to speech using edge-tts library directly.

        Args:
            text: Text to synthesize
            output_file: Optional output file path (default: temp file)
            voice: Optional voice name (default: from config)
        """
        if not output_file:
            output_file = tempfile.mktemp(suffix=".mp3")

        voice = voice or self.config.tts_voice

        try:
            # Import edge-tts lazily
            import edge_tts

            # Parse rate and pitch from config
            rate = self.config.tts_rate
            pitch = self.config.tts_pitch

            # Use edge-tts async API directly
            communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
            await communicate.save(output_file)

            # Verify file was created
            if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
                return {"error": "TTS generation produced empty file"}

            file_size = os.path.getsize(output_file)

            # Convert to base64 for return
            with open(output_file, "rb") as f:
                audio_b64 = base64.b64encode(f.read()).decode()

            # Clean up temp file
            if output_file.startswith("/tmp"):
                try:
                    os.unlink(output_file)
                except OSError:
                    pass

            return {
                "success": True,
                "output_file": output_file,
                "file_size": file_size,
                "audio_preview": f"data:audio/mp3;base64,{audio_b64[:1000]}...",
                "message": f"TTS generated: {len(text)} chars -> {file_size} bytes",
            }

        except ImportError:
            return {
                "error": "edge-tts not installed. Run: pip install edge-tts"
            }
        except Exception as e:
            logger.exception("TTS generation failed")
            return {"error": str(e)}

    async def stt(
        self,
        ctx: AgentDeps,
        audio_file: str,
        language: Optional[str] = None,
    ) -> dict:
        """
        Convert speech to text using faster-whisper API directly.

        Args:
            audio_file: Path to audio file or URL
            language: Optional language code (e.g., "en", "zh")
        """
        model_name = self.config.whisper_model

        try:
            # Handle URL or local file
            temp_file = None
            if audio_file.startswith("http"):
                # Download audio from URL
                import httpx
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.get(audio_file)
                    response.raise_for_status()
                    temp_file = tempfile.mktemp(suffix=".mp3")
                    with open(temp_file, "wb") as f:
                        f.write(response.content)
                    audio_file = temp_file

            # Ensure file exists
            if not os.path.exists(audio_file):
                return {"error": f"Audio file not found: {audio_file}"}

            # Load model
            model = await _load_whisper_model(model_name)

            # Prepare transcription kwargs
            transcribe_kwargs: dict = {"beam_size": 5}
            if language:
                transcribe_kwargs["language"] = language

            # Run transcription in thread pool to avoid blocking
            def transcribe():
                segments, info = model.transcribe(audio_file, **transcribe_kwargs)
                transcript = " ".join(segment.text.strip() for segment in segments)
                return transcript, info

            transcript, info = await asyncio.to_thread(transcribe)

            # Clean up temp file if we created one
            if temp_file and os.path.exists(temp_file):
                try:
                    os.unlink(temp_file)
                except OSError:
                    pass

            return {
                "success": True,
                "text": transcript,
                "language": info.language if hasattr(info, 'language') else (language or "unknown"),
                "duration": info.duration if hasattr(info, 'duration') else 0,
                "message": f"Transcribed: {len(transcript)} chars",
            }

        except ImportError:
            return {
                "error": "faster-whisper not installed. Run: pip install faster-whisper"
            }
        except Exception as e:
            logger.exception("STT transcription failed")
            return {"error": str(e)}

    async def feishu_voice(
        self,
        ctx: AgentDeps,
        text: str,
        chat_id: str,
        voice: Optional[str] = None,
    ) -> dict:
        """
        Generate TTS and send as voice message via Feishu.

        Args:
            text: Text to convert and send
            chat_id: Feishu chat ID to send to
            voice: Optional voice name
        """
        if not self.config.feishu_voice_enabled:
            return {"error": "Feishu voice not enabled"}

        # Step 1: Generate TTS
        tts_result = await self.tts(ctx, text, voice=voice)
        if "error" in tts_result:
            return tts_result

        audio_file = tts_result["output_file"]

        # Step 2: Convert to opus for Feishu using ffmpeg
        opus_file = tempfile.mktemp(suffix=".opus")

        try:
            import subprocess

            # ffmpeg -i input.mp3 -c:a libopus output.opus
            result = await asyncio.to_thread(
                subprocess.run,
                [
                    "ffmpeg", "-y", "-i", audio_file,
                    "-c:a", "libopus",
                    opus_file,
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                return {"error": f"FFmpeg conversion failed: {result.stderr}"}

            # Clean up mp3
            if audio_file.startswith("/tmp"):
                try:
                    os.unlink(audio_file)
                except OSError:
                    pass

            # Step 3: Return the opus file (actual sending would use Feishu API)
            return {
                "success": True,
                "opus_file": opus_file,
                "message": f"Voice generated, ready to send to {chat_id}",
            }

        except FileNotFoundError:
            return {
                "error": "ffmpeg not installed"
            }
        except Exception as e:
            logger.exception("Feishu voice generation failed")
            return {"error": str(e)}

    async def get_voices(self, ctx: AgentDeps, language: Optional[str] = None) -> dict:
        """
        List available edge-tts voices.

        Args:
            language: Optional language code to filter voices (e.g., "en", "zh")
        """
        try:
            import edge_tts

            voices = await edge_tts.list_voices()

            if language:
                voices = [v for v in voices if v["Locale"].startswith(language.lower())]

            return {
                "success": True,
                "voices": voices[:50],  # Limit for display
                "total": len(voices),
                "message": f"Found {len(voices)} voices",
            }
        except ImportError:
            return {"error": "edge-tts not installed"}
        except Exception as e:
            return {"error": str(e)}
