"""Voice provider helpers: thin wrappers around Deepgram STT and ElevenLabs TTS."""

import asyncio
from collections.abc import AsyncIterator
import logging
from typing import Any
from urllib.parse import urlencode

import httpx
import websockets

from backend.config import settings

logger = logging.getLogger(__name__)


class VoiceError(Exception):
    """Raised when STT or TTS provider configuration or streaming fails."""


def build_deepgram_url(
    language: str = "en",
    encoding: str | None = None,
    sample_rate: int | None = None,
) -> str:
    """Build the Deepgram streaming WebSocket URL with endpointing and interim results."""
    query: dict[str, Any] = {
        "model": "nova-2",
        "language": language,
        "interim_results": "true",
        "endpointing": "250",
        "utterance_end_ms": "1000",
        "vad_events": "true",
        "smart_format": "true",
    }
    if encoding:
        query["encoding"] = encoding
    if sample_rate:
        query["sample_rate"] = str(sample_rate)
    return f"wss://api.deepgram.com/v1/listen?{urlencode(query)}"


async def connect_deepgram(
    language: str = "en",
    encoding: str | None = None,
    sample_rate: int | None = None,
):
    """Open an authenticated streaming WebSocket connection to Deepgram."""
    if not settings.deepgram_api_key or settings.deepgram_api_key == "your_deepgram_api_key_here":
        raise VoiceError("DEEPGRAM_API_KEY is not configured in .env")

    url = build_deepgram_url(language, encoding=encoding, sample_rate=sample_rate)
    headers = {"Authorization": f"Token {settings.deepgram_api_key}"}
    try:
        return await websockets.connect(url, additional_headers=headers, open_timeout=15)
    except Exception as exc:
        logger.warning("Failed to connect to Deepgram (%s): %s", type(exc).__name__, str(exc))
        raise VoiceError("Unable to connect to speech-to-text service.") from exc


async def stream_elevenlabs_tts(
    text: str,
    cancel_event: asyncio.Event | None = None,
    output_format: str | None = None,
) -> AsyncIterator[bytes]:
    """Stream audio chunks from ElevenLabs for the given reply text."""
    if not settings.elevenlabs_api_key or settings.elevenlabs_api_key == "your_elevenlabs_api_key_here":
        raise VoiceError("ELEVENLABS_API_KEY is not configured in .env")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{settings.elevenlabs_voice_id}/stream?optimize_streaming_latency=3"
    if output_format:
        url = f"{url}&output_format={output_format}"
    headers = {
        "xi-api-key": settings.elevenlabs_api_key,
        "Content-Type": "application/json",
        "Accept": "audio/basic" if output_format == "ulaw_8000" else "audio/mpeg",
    }
    payload = {
        "text": text,
        "model_id": "eleven_flash_v2_5",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                if response.status_code >= 400:
                    logger.warning("ElevenLabs returned status %s", response.status_code)
                    raise VoiceError("Text-to-speech service returned an error.")
                async for chunk in response.aiter_bytes(chunk_size=4096):
                    if cancel_event is not None and cancel_event.is_set():
                        break
                    if chunk:
                        yield chunk
    except httpx.TimeoutException as exc:
        logger.warning("ElevenLabs request timed out")
        raise VoiceError("Text-to-speech service timed out.") from exc
    except httpx.HTTPError as exc:
        logger.warning("ElevenLabs HTTP error: %s", type(exc).__name__)
        raise VoiceError("Unable to reach text-to-speech service.") from exc
