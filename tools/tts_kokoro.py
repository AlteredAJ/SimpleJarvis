"""
tools/tts_kokoro.py — local Kokoro TTS via microservice (Python 3.12, port 8880).

Sends text to the Kokoro TTS server, saves the returned WAV to static/audio/,
and returns the filename. Falls back silently to tools/tts.py (ElevenLabs)
if the Kokoro server is unreachable or returns an error.

The Kokoro server runs in a separate Python 3.12 process — see
kokoro_server.py at the repo root sibling (kokoro_tts/).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import httpx

AUDIO_DIR = Path("static/audio")
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

KOKORO_URL = os.environ.get("KOKORO_URL", "http://localhost:8880")
KOKORO_VOICE = os.environ.get("KOKORO_VOICE", "af_sarah")
KOKORO_SPEED = float(os.environ.get("KOKORO_SPEED", "1.05"))
KOKORO_ENABLED = os.environ.get("KOKORO_ENABLED", "1") not in ("0", "false", "no")


def speak(text: str, voice: str | None = None) -> str:
    """Generate speech via local Kokoro server. Returns the filename in
    static/audio/ (e.g. 'kokoro_abc123.wav'). Raises httpx.ConnectError
    if the server is not running — callers should catch this and fall
    back to ElevenLabs."""
    if not KOKORO_ENABLED:
        raise httpx.ConnectError("Kokoro disabled via KOKORO_ENABLED")

    payload = {
        "input": text,
        "voice": voice or KOKORO_VOICE,
        "speed": KOKORO_SPEED,
    }

    with httpx.Client(timeout=30) as client:
        resp = client.post(
            f"{KOKORO_URL}/v1/audio/speech",
            json=payload,
        )
        resp.raise_for_status()

    filename = f"kokoro_{uuid4().hex[:12]}.wav"
    path = AUDIO_DIR / filename
    path.write_bytes(resp.content)
    return filename
