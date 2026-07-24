import os
import uuid
from pathlib import Path

from elevenlabs.client import ElevenLabs

# Bella — Professional, Bright, Warm. Default front desk voice.
# Swap voice_id in the client's config/demo.yaml to override per-client.
DEFAULT_VOICE_ID = "hpp4J3VqNfWAUOO0d1Us"  # Bella
DEFAULT_MODEL    = "eleven_flash_v2_5"       # ~75ms TTFB, best for real-time

AUDIO_DIR = Path("static/audio")
AUDIO_DIR.mkdir(parents=True, exist_ok=True)


def speak(text: str, voice_id: str | None = None) -> str:
    """
    Generates speech from text using ElevenLabs Flash v2.5.
    Saves the audio to a static file and returns the filename.
    The caller is responsible for serving it and building the full URL.
    """
    client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])

    audio = client.text_to_speech.convert(
        text=text,
        voice_id=voice_id or os.getenv("ELEVENLABS_VOICE_ID", DEFAULT_VOICE_ID),
        model_id=DEFAULT_MODEL,
        output_format="mp3_44100_128",
    )

    filename = f"{uuid.uuid4().hex}.mp3"
    path = AUDIO_DIR / filename
    with open(path, "wb") as f:
        for chunk in audio:
            if chunk:
                f.write(chunk)

    return filename


def clone_voice(name: str, audio_path: str, description: str = "") -> str:
    """
    Clones a voice from an audio file (10+ seconds recommended).
    Returns the new voice_id to store in the client's config.
    """
    client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
    with open(audio_path, "rb") as f:
        voice = client.voices.add(
            name=name,
            description=description,
            files=[f],
        )
    return voice.voice_id
