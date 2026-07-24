"""
stt.py - Speech-to-text module for Jarvis.

Uses faster-whisper (CPU, int8 compute) for transcription and sounddevice
for microphone capture.

Dependencies (already installed in this environment):
    pip install faster-whisper sounddevice
"""

from __future__ import annotations

import tempfile
import wave
import os

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

# Lazily-initialized singleton model instance so repeated calls don't reload
# the model from disk every time.
_model: WhisperModel | None = None

_MODEL_SIZE = "base"
_DEVICE = "cpu"
_COMPUTE_TYPE = "int8"

_SAMPLE_RATE = 16000  # Whisper expects 16kHz mono audio
_CHANNELS = 1


def _get_model() -> WhisperModel:
    """Return a cached WhisperModel instance, creating it on first use."""
    global _model
    if _model is None:
        _model = WhisperModel(_MODEL_SIZE, device=_DEVICE, compute_type=_COMPUTE_TYPE)
    return _model


def transcribe_file(audio_path: str) -> str:
    """Transcribe an existing audio file to text using faster-whisper.

    Args:
        audio_path: Path to an audio file (wav, mp3, etc.) to transcribe.

    Returns:
        The transcribed text, stripped of leading/trailing whitespace.
    """
    model = _get_model()
    segments, _info = model.transcribe(audio_path)
    text = "".join(segment.text for segment in segments)
    return text.strip()


def transcribe_array(audio: "np.ndarray", sample_rate: int = _SAMPLE_RATE) -> str:
    """Transcribe an in-memory audio array directly, no temp file needed.

    Args:
        audio: mono audio samples, either int16 or float32. faster-whisper
            expects float32 in [-1, 1], so int16 input is normalized here.
        sample_rate: must be 16000 (Whisper's expected rate) unless you've
            resampled elsewhere — this function does not resample.

    Returns:
        The transcribed text, stripped of leading/trailing whitespace.

    Added for voice_loop.py's barge-in capture, which accumulates audio in
    a numpy buffer via a live InputStream and needs to transcribe it without
    a round-trip through disk on every turn.
    """
    if audio.dtype != np.float32:
        audio = audio.astype(np.float32) / 32768.0

    model = _get_model()
    segments, _info = model.transcribe(audio, language="en")
    text = "".join(segment.text for segment in segments)
    return text.strip()


def listen_and_transcribe(duration_seconds: float = 5.0) -> str:
    """Record audio from the default microphone and transcribe it.

    Args:
        duration_seconds: How many seconds of audio to record from the
            default input device.

    Returns:
        The transcribed text, stripped of leading/trailing whitespace.
    """
    recording = sd.rec(
        int(duration_seconds * _SAMPLE_RATE),
        samplerate=_SAMPLE_RATE,
        channels=_CHANNELS,
        dtype="int16",
    )
    sd.wait()

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
        tmp_path = tmp_file.name

    try:
        with wave.open(tmp_path, "wb") as wf:
            wf.setnchannels(_CHANNELS)
            wf.setsampwidth(2)  # int16 = 2 bytes
            wf.setframerate(_SAMPLE_RATE)
            wf.writeframes(np.asarray(recording, dtype=np.int16).tobytes())

        return transcribe_file(tmp_path)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
