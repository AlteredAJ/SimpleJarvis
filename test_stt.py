"""
test_stt.py - Round-trip test for stt.transcribe_file().

Since there's no live mic input available in this environment, this test
uses Windows' built-in SAPI text-to-speech engine to generate a WAV file
from a known sentence (test.wav, generated via PowerShell beforehand),
then runs transcribe_file() on it and compares against the known input.

This is a genuine end-to-end test of the transcription path (audio file ->
faster-whisper -> text), even without exercising the live-mic recording
code in listen_and_transcribe().
"""

from stt import transcribe_file

KNOWN_SENTENCE = "The quick brown fox jumps over the lazy dog"
AUDIO_PATH = "test.wav"


def main() -> None:
    print(f"Known sentence:      {KNOWN_SENTENCE!r}")
    result = transcribe_file(AUDIO_PATH)
    print(f"Transcribed output:  {result!r}")

    known_words = set(KNOWN_SENTENCE.lower().split())
    result_words = set(result.lower().replace(".", "").replace(",", "").split())
    overlap = known_words & result_words
    print(f"Word overlap: {len(overlap)}/{len(known_words)} -> {sorted(overlap)}")


if __name__ == "__main__":
    main()
