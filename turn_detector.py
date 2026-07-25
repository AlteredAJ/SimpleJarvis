"""
turn_detector.py — heuristic semantic turn detection for voice conversation.

Replaces the fixed silence-gap endpoint wait with text-aware completion
prediction. Runs on the streaming STT partial text — no audio analysis,
no extra models, sub-1ms per call.

How it works:
  1. Watches the streaming partial transcription from faster-whisper.
  2. Scores sentence completeness via deterministic heuristics:
     - Punctuation (. ! ?) = high confidence
     - Sentence-final cue phrases ("you know?", "right?") = medium
     - Noun + verb + N words = low confidence
     - Stable text (no new tokens) for > threshold = time-based fallback
  3. When confidence crosses the threshold, signals "turn complete"
     — the voice loop responds immediately without waiting for VAD silence.

This cuts the ~350ms silence-gap from response latency.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class TurnResult:
    complete: bool
    confidence: float  # 0.0–1.0
    reason: str = ""

    def __bool__(self) -> bool:
        return self.complete


# Sentence-terminal punctuation
_TERMINATORS = {".", "!", "?", '."', '!"', '?"', ".'", "!'", "?'"}

# Final-bridging phrases that signal the speaker is yielding the floor
_YIELD_PHRASES = {
    "you know", "you know what i mean", "you see",
    "right", "got it", "okay", "alright",
    "go ahead", "what do you think",
    "does that make sense", "make sense",
    "or something", "or whatever", "and stuff",
    "so yeah", "so anyway",
    "thanks", "thank you",
    "that's it", "that is it", "that's all",
}

# Words that strongly suggest a question (boosts confidence when at/near end)
_QUESTION_MARKERS = {
    "what", "when", "where", "who", "why", "how",
    "can", "could", "would", "will", "should",
    "is", "are", "was", "were", "do", "does", "did",
    "have", "has", "had",
    "any", "anyone", "anything",
}

# Minimum word count before we even consider a turn complete
_MIN_WORDS = 3


class TurnDetector:
    """Tracks streaming partial text and predicts turn completion."""

    def __init__(
        self,
        punctuation_threshold: float = 0.85,
        cue_threshold: float = 0.7,
        structural_threshold: float = 0.55,
        stability_threshold: float = 0.4,
        stability_ms: float = 900,  # time with no new tokens before we consider stable
    ):
        self.punctuation_threshold = punctuation_threshold
        self.cue_threshold = cue_threshold
        self.structural_threshold = structural_threshold
        self.stability_threshold = stability_threshold
        self.stability_ms = stability_ms

        self._last_text: str = ""
        self._last_update: float = 0.0

    def process(self, partial_text: str, now: float | None = None) -> TurnResult:
        """Call on every streaming partial update. Returns TurnResult
        — check .complete or bool(result) to decide if it's time to respond.

        partial_text: the current best-guess transcription from STT
        now: optional timestamp (uses time.time() if not given)
        """
        if now is None:
            now = time.time()

        text = partial_text.strip()
        if not text:
            self._last_update = now
            return TurnResult(complete=False, confidence=0.0, reason="empty")

        # Track when this text was last updated
        if text != self._last_text:
            self._last_text = text
            self._last_update = now

        words = text.split()
        word_count = len(words)

        if word_count < _MIN_WORDS:
            return TurnResult(complete=False, confidence=0.0, reason="too short")

        # --- Heuristic 1: Sentence-terminal punctuation ---
        last_char = text[-1]
        if last_char in _TERMINATORS or (len(text) > 1 and text[-2:] in _TERMINATORS):
            return TurnResult(
                complete=True,
                confidence=self.punctuation_threshold,
                reason="terminal punctuation",
            )

        # --- Heuristic 2: Cue phrases at/near the end ---
        text_lower = text.lower().rstrip(".!?,\"'_ ")
        for phrase in _YIELD_PHRASES:
            if text_lower.endswith(phrase):
                return TurnResult(
                    complete=True,
                    confidence=self.cue_threshold,
                    reason=f"yield phrase: '{phrase}'",
                )

        # --- Heuristic 3: Structural completeness ---
        structural = self._score_structure(words, text_lower)
        elapsed = (now - self._last_update) * 1000

        # Strong structure + has been stable for a bit → likely done
        if structural >= 0.7 and elapsed > self.stability_ms:
            return TurnResult(
                complete=True,
                confidence=self.structural_threshold,
                reason=(f"structural ({structural:.2f}) + " f"stable {elapsed:.0f}ms"),
            )

        # --- Heuristic 4: Stability fallback ---
        # If the text hasn't changed in a while, assume the user is done
        # (but at lower confidence — could be mid-thought pause)
        if elapsed > self.stability_ms * 2:
            return TurnResult(
                complete=True,
                confidence=self.stability_threshold,
                reason=f"stable {elapsed:.0f}ms (fallback)",
            )

        return TurnResult(
            complete=False,
            confidence=structural * 0.5,
            reason=f"incomplete ({word_count} words, stable {elapsed:.0f}ms)",
        )

    @staticmethod
    def _score_structure(words: list[str], text_lower: str) -> float:
        """Heuristic structural completeness score (0.0–1.0).
        Higher = more likely a complete utterance."""
        n = len(words)

        # Has a verb-like word somewhere in the utterance
        has_verb = any(
            w.endswith(("ing", "ed", "es", "s"))
            or w in {"is", "are", "was", "were", "be", "been", "have", "has", "had",
                     "do", "does", "did", "can", "could", "will", "would", "should",
                     "get", "got", "go", "went", "make", "made", "know", "think",
                     "want", "need", "like", "see", "say", "tell", "mean"}
            for w in words
        )
        if not has_verb:
            return 0.2

        # Has a subject-like word
        has_subject = any(
            w.lower() in {"i", "you", "he", "she", "it", "we", "they",
                          "that", "this", "there", "the"}
            for w in words
        )

        # Question structure (inverted verb-subject or question word start)
        is_question = (
            text_lower.split()[0] in _QUESTION_MARKERS
            or text_lower.startswith(("is ", "are ", "do ", "does ", "can "))
        )
        if is_question:
            # Questions are more likely complete once they have a verb
            return 0.7 + (0.1 * min(n / 8, 1.0))

        # General completeness: subject + verb + at least a few words
        score = 0.3
        if has_subject:
            score += 0.2
        if n >= 4:
            score += 0.2
        if n >= 6:
            score += 0.15
        if n >= 10:
            score += 0.15
        # Last word looks like a noun/completion word
        if words[-1].lower() in {"up", "down", "out", "now", "today", "tomorrow",
                                  "there", "here", "done", "good", "fine", "okay"}:
            score += 0.1

        return min(score, 1.0)

    def reset(self) -> None:
        """Call at the start of a new utterance."""
        self._last_text = ""
        self._last_update = 0.0
