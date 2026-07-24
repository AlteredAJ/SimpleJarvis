"""
voice_loop.py — real-time spoken conversation with barge-in interruption.

This is the piece that makes Jarvis interruptible mid-sentence the way a
real person is, instead of finishing a canned line before it'll listen
again — AND smart about it: not every interruption should nuke whatever
Jarvis was in the middle of saying. Two kinds of interruption:

    HARD ("stop", "wait", "actually", "never mind", ...): the user is
    correcting or redirecting Jarvis. Cancel the reply outright, treat
    what they said as a fresh turn. See classify_interrupt().

    SOFT (everything else): treated as a quick aside, not a takeover. The
    primary reply PAUSES (not cancels) the instant speech is detected,
    gets classified, and — if soft — the aside is answered on a separate
    audio stream while the primary generation (which was never actually
    cancelled, just backed up while paused) resumes right where it left
    off once the aside is done. See speak_reply_with_interrupts(),
    run_quick_aside(), and _speak_turn() for how these fit together.

Why not just run both simultaneously start-to-finish? Measured on this
machine: a single GPU can't cheaply run two independent generations at
once. With Ollama's default OLLAMA_NUM_PARALLEL=1, a concurrent aside
request got queued behind the primary (0.49s solo -> 3.08s concurrent).
Bumping to OLLAMA_NUM_PARALLEL=2 (now set as a permanent Windows user env
var) fixed that specifically for the "pause primary, run aside alone,
resume primary" pattern used here — the aside gets the GPU essentially to
itself while the primary is paused, which is why pause-then-resume (not
true simultaneous dual-generation) is the design.

Underlying mechanics (still true, now serving both hard and soft paths):
    1. Ollama generation, streamed sentence-by-sentence (via chat.run_turn's
       on_delta + brain_ollama's stop_event, both already built for this).
    2. ElevenLabs TTS + sounddevice playback of each finished sentence,
       via Speaker — playback checks for an interrupt/pause flag between
       small sub-chunks, so "stop"/"pause" takes effect within ~tens of ms,
       not "after this file finishes playing."
    3. A background mic monitor (Listener) that runs the WHOLE time Jarvis
       is speaking, watching for the user's voice. The instant it fires,
       the primary thread pauses itself and waits for a verdict — the SAME
       audio stream that was already recording (so the user's first word
       isn't lost — Listener starts capturing from before the trigger
       fires, not after) keeps recording until they stop talking, then
       gets transcribed and classified.

HARDWARE / ACOUSTIC CAVEAT — read before relying on this:
    Barge-in detection here is simple energy-threshold VAD (root-mean-square
    of each audio block), not a trained voice-activity model and not real
    acoustic echo cancellation (AEC). That means Jarvis's OWN voice, if it
    leaks into the mic, can in principle trigger a false "interruption."
    On THIS machine the default devices are a HyperX Quadcast (a standalone
    desk mic, not a laptop mic sitting next to the speakers) for input and
    Arctis Nova Pro HEADPHONES (not open speakers) for output — that
    combination has much less acoustic coupling than a laptop's built-in
    mic+speakers, which is why this is viable at all without real AEC. If
    AJ ever switches to speaker output, expect false self-interruptions and
    revisit this (proper fix is either a headset mic close to the mouth,
    or real AEC, which is out of scope here).

USAGE:
    python voice_loop.py                  # continuous spoken conversation
    python voice_loop.py --session NAME   # continue a named session
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import threading
import time
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()  # populates os.environ from .env — main.py already did this for
# the Twilio-era code, but chat.py/voice_loop.py are new entry points that
# never called it, so ELEVENLABS_API_KEY (and anything else in .env) wasn't
# actually reaching os.environ.get() calls below until this was added.

import numpy as np
import sounddevice as sd

import chat
import hud_server
import memory
import memory_vault
import stt
import tray
from elevenlabs.client import ElevenLabs

AGENT_NAME = chat.AGENT_NAME

SAMPLE_RATE = 16000  # matches stt.py's Whisper input expectation
BLOCK_FRAMES = 512  # ~32ms per block at 16kHz — small enough for fast interrupt reaction

# --- Barge-in VAD tuning ---------------------------------------------------
# RMS threshold (on float32 samples in [-1, 1]) above which a block counts
# as "voice-like." First live test (2026-07-20) reported interruptions not
# reliably stopping speech — lowered from 0.02, since a threshold tuned too
# conservatively (to avoid self-echo false triggers) will just as easily
# miss real interrupt attempts at normal talking volume. Raise this back up
# if it starts false-triggering on breathing/ambient noise instead.
VAD_RMS_THRESHOLD = 0.012
# Consecutive voice-like blocks required before it counts as a genuine
# interruption (debounce against a single loud click/cough). At ~32ms/block,
# 4 blocks ~= 130ms of sustained voice before it fires (was 6 / ~190ms —
# tightened for a faster, more reliable reaction).
VAD_TRIGGER_BLOCKS = 4
# After the user stops talking (this many consecutive quiet blocks), stop
# capturing and transcribe what was recorded. ~700ms of silence = done talking.
VAD_ENDPOINT_SILENCE_BLOCKS = 22
# Hard cap so a stuck-open mic / background noise can't record forever.
MAX_CAPTURE_SECONDS = 20.0

# How long after Jarvis finishes a reply to keep listening for a natural
# follow-up WITHOUT requiring the wake word again — added 2026-07-20 after
# live feedback that requiring "Jarvis" before every single turn felt wrong
# for back-and-forth conversation. Re-opens after every reply given within
# the window, so a real conversation can run indefinitely without ever
# re-invoking the wake word; only silence for this long falls back to
# requiring it.
GRACE_WINDOW_SECONDS = 4.5

ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "hpp4J3VqNfWAUOO0d1Us")  # Bella
ELEVENLABS_MODEL = "eleven_flash_v2_5"

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# --- Wake word ---------------------------------------------------------
# Only gates the IDLE listening loop (starting a fresh interaction from
# silence) — deliberately NOT applied to barge-ins mid-conversation. Having
# to re-say "Jarvis" every time you cut in would defeat the whole point of
# the interruption system: real back-and-forth doesn't re-address the other
# person by name every sentence.
WAKE_WORD = "jarvis"
# Loose variants Whisper's base model plausibly mishears "Jarvis" as —
# small model, short word, worth a little slack rather than requiring a
# perfect transcription every time.
_WAKE_WORD_RE = re.compile(r"\bjarvis\b|\bjarv[ie]s\b|\bjar[- ]?vis\b", re.IGNORECASE)


def contains_wake_word(text: str) -> bool:
    return bool(_WAKE_WORD_RE.search(text))


def strip_wake_word(text: str) -> str:
    """Removes the wake word (and any immediately-following filler
    punctuation/comma) from the start of an utterance, leaving whatever
    command followed it. "Jarvis, what time is it" -> "what time is it".
    If the wake word isn't at the start (e.g. said mid-sentence), only the
    matched word itself is removed, wherever it is."""
    stripped = _WAKE_WORD_RE.sub("", text, count=1)
    return stripped.strip(" ,.-!?").strip()


class Listener:
    """Continuously records mic audio into a growing buffer while armed, and
    exposes an Event that fires once sustained voice-like energy is seen.
    Capturing starts at construction time (not at trigger time) specifically
    so the user's first word isn't lost while we're still deciding "is this
    really speech" — by the time VAD_TRIGGER_BLOCKS confirms it, those first
    blocks are already sitting in the buffer.
    """

    # How often to re-transcribe the growing buffer while streaming_transcribe
    # is on. Benchmarked 2026-07-20: faster-whisper "base" transcribes a
    # ~3.4s clip in ~0.44s on this CPU — re-running every 0.6s during active
    # speech is a real but acceptable CPU cost for realistic utterance
    # lengths (a few seconds), not the minutes-long case where re-processing
    # the whole growing buffer from scratch each time would get wasteful.
    STREAMING_TRANSCRIBE_INTERVAL = 0.6
    # A partial result counts as "fresh enough to use as final" if it ran
    # within this long before endpoint silence fired — avoids a redundant
    # final full-buffer pass in the common case (this IS the actual latency
    # win: skipping the "one more transcription after you stop talking"
    # tail), while still falling back to a fresh transcribe if the last
    # partial is stale for some reason (e.g. transcription itself was slow).
    STREAMING_FRESHNESS_WINDOW = 1.2

    def __init__(
        self,
        device: int | str | None = None,
        hud_feed: bool = False,
        streaming_transcribe: bool = False,
    ):
        self.speech_detected = threading.Event()
        self._chunks: list[np.ndarray] = []
        self._voice_run = 0
        self._silence_run = 0
        self._triggered_at: float | None = None
        self._lock = threading.Lock()
        self._hud_feed = hud_feed  # only the "waiting for the user" idle listener
        # feeds the HUD's level meter — a barge-in monitor running silently
        # in the background while Jarvis talks shouldn't visually compete
        # with the speaking animation until an interruption actually fires.
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=BLOCK_FRAMES,
            device=device,
            callback=self._on_block,
        )
        self._start_time = time.time()
        self._stream.start()

        self.partial_text = ""
        self._partial_lock = threading.Lock()
        self._last_transcribe_time = 0.0
        self._closed = threading.Event()
        self._streaming_thread: threading.Thread | None = None
        if streaming_transcribe:
            self._streaming_thread = threading.Thread(target=self._streaming_loop, daemon=True)
            self._streaming_thread.start()

    def _streaming_loop(self) -> None:
        """Background loop: while speech is happening, periodically
        re-transcribe the buffer-so-far and push it live to the HUD as
        captions. Only runs once speech_detected has fired — no point
        transcribing silence/ambient noise before there's anything said."""
        while not self._closed.is_set():
            time.sleep(self.STREAMING_TRANSCRIBE_INTERVAL)
            if self._closed.is_set():
                return
            if not self.speech_detected.is_set():
                continue
            audio = self.get_audio()
            if len(audio) < SAMPLE_RATE * 0.3:  # too little to bother with
                continue
            try:
                text = stt.transcribe_array(audio, sample_rate=SAMPLE_RATE).strip()
            except Exception:  # noqa: BLE001 - a partial-transcribe hiccup shouldn't kill capture
                continue
            if self._closed.is_set():
                return
            with self._partial_lock:
                self.partial_text = text
                self._last_transcribe_time = time.time()
            if text:
                hud_server.set_state("listening", label=text)
                hud_server.publish({"type": "user_partial", "text": text})

    def get_fresh_partial(self) -> str | None:
        """Returns the last partial transcription if it's recent enough to
        trust as the final result (see STREAMING_FRESHNESS_WINDOW), else
        None — callers should fall back to a fresh full transcribe."""
        with self._partial_lock:
            if not self.partial_text:
                return None
            age = time.time() - self._last_transcribe_time
            return self.partial_text if age < self.STREAMING_FRESHNESS_WINDOW else None

    def _on_block(self, indata, frames, time_info, status):  # noqa: ANN001 - sounddevice callback signature
        block = indata[:, 0].copy()
        with self._lock:
            self._chunks.append(block)

        rms = float(np.sqrt(np.mean(np.square(block))))
        if self._hud_feed:
            hud_server.set_level(rms)
        if rms >= VAD_RMS_THRESHOLD:
            self._voice_run += 1
            self._silence_run = 0
            if self._voice_run >= VAD_TRIGGER_BLOCKS and not self.speech_detected.is_set():
                self._triggered_at = time.time()
                self.speech_detected.set()
                print(f"[voice][VAD] speech_detected fired (rms={rms:.4f}, threshold={VAD_RMS_THRESHOLD})", file=sys.stderr)
        else:
            self._silence_run += 1
            self._voice_run = 0

    def wait_for_endpoint(self, max_seconds: float = MAX_CAPTURE_SECONDS) -> None:
        """Block until the user has been quiet for VAD_ENDPOINT_SILENCE_BLOCKS
        blocks after having spoken, or max_seconds elapses. Call this after
        speech_detected fires (or when doing a normal, non-barge-in listen)."""
        deadline = time.time() + max_seconds
        while time.time() < deadline:
            if self.speech_detected.is_set() and self._silence_run >= VAD_ENDPOINT_SILENCE_BLOCKS:
                return
            time.sleep(0.02)

    def wait_for_speech(self, max_seconds: float = MAX_CAPTURE_SECONDS) -> bool:
        """Block until speech_detected fires or max_seconds elapses (normal,
        non-barge-in listening: waiting for the user to start talking at
        all). Returns True if speech was detected."""
        return self.speech_detected.wait(timeout=max_seconds)

    def get_audio(self) -> np.ndarray:
        with self._lock:
            if not self._chunks:
                return np.zeros(0, dtype=np.float32)
            return np.concatenate(self._chunks)

    def close(self) -> None:
        self._closed.set()
        self._stream.stop()
        self._stream.close()
        if self._streaming_thread is not None:
            self._streaming_thread.join(timeout=2.0)


class Speaker:
    """Plays 16-bit PCM audio via sounddevice, in small enough sub-chunks
    that .stop() takes effect within roughly one sub-chunk's duration (a
    few tens of ms), not "after the current file finishes." That immediacy
    is the whole point — a real interruption has to actually cut the audio,
    not just queue a stop for later."""

    SUBCHUNK_FRAMES = 1024

    def __init__(self, samplerate: int = SAMPLE_RATE, hud_feed: bool = False):
        self.samplerate = samplerate
        self._interrupted = threading.Event()
        self._paused = threading.Event()
        self._hud_feed = hud_feed
        self._stream = sd.OutputStream(samplerate=samplerate, channels=1, dtype="int16")
        self._stream.start()

    def play_pcm(self, pcm_bytes: bytes) -> bool:
        """Play raw 16-bit mono PCM. Returns False if playback was cut short
        by an interruption (hard cancel), True if it played to completion —
        which includes having been paused and resumed partway through; a
        pause is not a cancellation, so it still counts as "completed."""
        samples = np.frombuffer(pcm_bytes, dtype=np.int16)
        for start in range(0, len(samples), self.SUBCHUNK_FRAMES):
            if self._interrupted.is_set():
                if self._hud_feed:
                    hud_server.set_level(0.0)
                return False
            while self._paused.is_set():
                if self._interrupted.is_set():
                    return False
                time.sleep(0.02)
            chunk = samples[start:start + self.SUBCHUNK_FRAMES]
            if self._hud_feed:
                # int16 -> roughly the same 0-1ish RMS scale the mic side
                # uses (float32 in [-1,1]), so the HUD's level scaling works
                # the same regardless of which side (mic or speaker) is
                # driving it.
                hud_server.set_level(float(np.sqrt(np.mean(np.square(chunk.astype(np.float32) / 32768.0)))))
            self._stream.write(chunk.reshape(-1, 1))
        if self._hud_feed:
            hud_server.set_level(0.0)
        return True

    def interrupt(self) -> None:
        self._interrupted.set()

    def reset(self) -> None:
        self._interrupted.clear()
        self._paused.clear()

    def pause(self) -> None:
        """Mute immediately without discarding anything — the write loop in
        play_pcm() blocks between sub-chunks while paused, so whatever
        sentence is mid-playback just... waits, right where it was."""
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    def close(self) -> None:
        self._stream.stop()
        self._stream.close()


# --- Interrupt classification -----------------------------------------
# Deterministic, code-is-the-source-of-truth keyword classifier — same
# philosophy as PICKUP-DEMO-DESIGN-reference.md's escalation.py (a hard
# trigger phrase list checked in code, not left to an 8B model's judgment
# to catch reliably live). "hard" = the user is correcting/stopping Jarvis,
# cancel the reply and start fresh on what they just said. Anything else
# defaults to "soft" = treat it as a quick aside: pause, answer it, resume
# the original reply — don't destroy work in progress over ambiguity.
HARD_CANCEL_PHRASES = [
    "stop", "wait", "actually", "never mind", "nevermind",
    "hold on", "cancel that", "scratch that", "forget it", "no no no",
]


def classify_interrupt(text: str) -> str:
    t = text.lower().strip()
    for phrase in HARD_CANCEL_PHRASES:
        if phrase in t:
            return "hard"
    return "soft"


class InterruptState:
    """Coordinates a barge-in between the primary-reply thread (which pauses
    itself the instant speech is detected — talking over the user is wrong
    regardless of what they're about to say) and the main thread, which
    captures + transcribes + classifies the interruption and then unblocks
    the primary thread with a verdict.

    speech_detected is literally the same Event as the Listener's — passed
    in, not duplicated, so there's one source of truth for "is the user
    talking right now."

    KNOWN LIMITATION: this supports one interruption per reply. After a
    soft interrupt resolves, the primary reply resumes to completion
    without re-arming barge-in detection for a second interruption within
    that same reply. A second interruption gets picked up on the NEXT turn.
    Good enough for v1; revisit if AJ finds himself double-interrupting in
    practice."""

    def __init__(self, speech_detected: threading.Event):
        self.speech_detected = speech_detected
        self.classified = threading.Event()
        self.verdict: str | None = None  # "hard" | "soft", set once classified


def _synthesize_pcm(client: ElevenLabs, text: str) -> bytes:
    """Blocking call to ElevenLabs, returns raw 16-bit PCM bytes at
    SAMPLE_RATE. Uses output_format=pcm_16000 specifically so no decoding
    step (mp3->PCM) is needed before handing it to sounddevice."""
    chunks = client.text_to_speech.stream(
        voice_id=ELEVENLABS_VOICE_ID,
        text=text,
        model_id=ELEVENLABS_MODEL,
        output_format="pcm_16000",
    )
    return b"".join(chunks)


def speak_reply_with_interrupts(
    client: ElevenLabs,
    speaker: Speaker,
    istate: InterruptState,
    gen_stop_event: threading.Event,
    text_stream_fn,
) -> tuple[str, str | None]:
    """Drives text_stream_fn (a callable taking on_delta + stop_event,
    matching chat.run_turn's signature), speaking each completed sentence
    as it arrives. Runs in its own thread (see run()) so the main thread is
    free to capture/transcribe/classify a barge-in concurrently.

    On istate.speech_detected firing: pauses audio immediately (regardless
    of what the classification turns out to be — don't keep talking over
    someone while you decide whether they meant to interrupt), then BLOCKS
    on istate.classified, waiting for the main thread's verdict:
        "hard" -> cancels generation (gen_stop_event) and stops here. The
                  caller treats whatever the user said as a fresh new turn.
        "soft" -> resumes exactly where it paused. Generation was never
                  cancelled — it just backed up while paused — so the reply
                  finishes normally, unaware anything happened.

    Returns (full_reply_text, verdict) where verdict is None if the reply
    completed with no interruption at all.
    """
    sentence_buffer: list[str] = []
    full_text_parts: list[str] = []
    spoken_chars: int = 0
    final_verdict: str | None = None
    resolved = False  # have we already acted on an interrupt for this reply?

    def resolve_interrupt_if_needed() -> bool:
        """Call before doing anything (append text, synthesize, play).
        Returns False if the caller should stop (hard cancel), True to
        proceed. Handles BOTH possible orderings of the race between
        generation and classification:
          - speech_detected fires WHILE we're already mid-generation ->
            we pause and wait for classification (the "normal" case).
          - speech_detected fires AND gets classified during prompt-eval,
            entirely before our first on_delta call even happens (verified
            2026-07-20: prompt-eval alone can take 5+s, plenty of time for
            VAD + STT + classification to finish before a single token has
            streamed) -> by the time we get our first look, `classified` is
            ALREADY set. Gating on "speech_detected AND NOT YET classified"
            (the original version of this function) missed this case
            entirely: that condition is false, so it fell through and
            generated the whole reply as if nothing had happened. Fix:
            resolve on speech_detected alone, and rely on
            istate.classified.wait() being a no-op if already set — same
            code path handles both orderings correctly.
        Resolves exactly once per reply (repeated calls after resolution
        just return the cached verdict) — without that, every subsequent
        delta after a "soft" resolution would re-pause/re-resume for
        nothing, since speech_detected is never cleared once set."""
        nonlocal final_verdict, resolved
        if resolved:
            return final_verdict != "hard"
        if not istate.speech_detected.is_set():
            return True
        resolved = True
        print("[voice][interrupt] primary noticed speech_detected — pausing", file=sys.stderr)
        hud_server.set_state("listening")  # paused to hear what they're saying
        speaker.pause()  # no-op if nothing has played yet (still mid prompt-eval) — harmless
        istate.classified.wait()  # returns immediately if already classified
        final_verdict = istate.verdict
        print(f"[voice][interrupt] classified as '{final_verdict}' — {'cancelling' if final_verdict == 'hard' else 'resuming'}", file=sys.stderr)
        if istate.verdict == "hard":
            gen_stop_event.set()
            return False
        speaker.resume()
        return True

    def flush_sentence(sentence: str) -> bool:
        """Synthesize + play one sentence. Returns False if the caller
        should stop (hard cancel only)."""
        if not resolve_interrupt_if_needed():
            return False
        nonlocal spoken_chars
        spoken_chars += len(sentence)
        try:
            pcm = _synthesize_pcm(client, sentence)
        except Exception as e:  # noqa: BLE001
            print(f"[voice] TTS failed for a sentence ({e}); skipping audio for it.", file=sys.stderr)
            return True
        hud_server.set_state("speaking", label=sentence[:70])
        return speaker.play_pcm(pcm)

    def on_delta(chunk: str) -> None:
        # Check on EVERY delta, not just at sentence boundaries — a long
        # first sentence would otherwise let generation run unchecked
        # until it finally hits a period.
        if not resolve_interrupt_if_needed():
            return
        full_text_parts.append(chunk)
        sentence_buffer.append(chunk)
        joined = "".join(sentence_buffer)
        parts = _SENTENCE_SPLIT_RE.split(joined)
        if len(parts) > 1:
            for complete in parts[:-1]:
                complete = complete.strip()
                if complete and not flush_sentence(complete):
                    return
            sentence_buffer.clear()
            sentence_buffer.append(parts[-1])

    text_stream_fn(on_delta=on_delta, stop_event=gen_stop_event)

    if final_verdict != "hard":
        trailing = "".join(sentence_buffer).strip()
        if trailing:
            flush_sentence(trailing)

    full_text = "".join(full_text_parts).strip()
    if final_verdict == "hard":
        hud_server.publish({"type": "interrupted", "at_char": spoken_chars})
        hud_server.publish({"type": "assistant_final", "text": full_text})

    return full_text, final_verdict


def run_quick_aside(session_id: str, text: str, client: ElevenLabs, speaker: Speaker) -> str:
    """A fast, standalone turn for a 'soft' interruption. Reuses chat.run_turn
    as-is (same persona/memory/RAG as any other turn — an aside shouldn't
    feel like a different, dumber Jarvis) but speaks through its OWN Speaker
    instance so it can play concurrently with the paused-then-resuming
    primary reply on a separate audio stream, rather than the two fighting
    over one OutputStream. Runs on the SAME Ollama model as the primary —
    OLLAMA_NUM_PARALLEL=2 (set up specifically for this) is what makes this
    genuinely concurrent instead of queued behind the primary; see the
    empirical comparison in this session's history for why a second,
    separately-loaded model was rejected instead (reload thrashing on this
    machine's default OLLAMA_MAX_LOADED_MODELS).

    NOTE: some sentence-buffering logic here duplicates
    speak_reply_with_interrupts' — kept simple/separate on purpose since
    this path has no pause/resume/interrupt state to coordinate at all,
    it's just "generate and speak," which doesn't warrant sharing the more
    complex function's machinery.
    """
    full_text_parts: list[str] = []
    sentence_buffer: list[str] = []

    hud_server.publish({"type": "aside_start", "text": text})

    def speak_one(sentence: str) -> None:
        try:
            pcm = _synthesize_pcm(client, sentence)
            hud_server.set_state("aside", label=sentence[:70])
            speaker.play_pcm(pcm)
        except Exception as e:  # noqa: BLE001
            print(f"[voice] aside TTS failed ({e}); skipping audio for it.", file=sys.stderr)

    def on_delta(chunk: str) -> None:
        full_text_parts.append(chunk)
        hud_server.publish({"type": "aside_delta", "text": chunk})
        sentence_buffer.append(chunk)
        joined = "".join(sentence_buffer)
        parts = _SENTENCE_SPLIT_RE.split(joined)
        if len(parts) > 1:
            for complete in parts[:-1]:
                complete = complete.strip()
                if complete:
                    speak_one(complete)
            sentence_buffer.clear()
            sentence_buffer.append(parts[-1])

    chat.run_turn(session_id, text, on_delta=on_delta, spoken=True, aside=True)

    trailing = "".join(sentence_buffer).strip()
    if trailing:
        speak_one(trailing)

    full = "".join(full_text_parts).strip()
    hud_server.publish({"type": "aside_final", "text": full})
    return full


def _speak_turn(client: ElevenLabs, speaker: Speaker, session_id: str, user_text: str) -> None:
    """Orchestrates one full turn: speak the primary reply while watching
    for a barge-in concurrently. On a hard cancel, recurses into a fresh
    turn with whatever the user said. On a soft interrupt, dispatches the
    aside on a separate Speaker while the primary (paused, not cancelled)
    resumes as soon as classification lands. Prints the whole exchange
    itself, including any recursive turns, since there can be more than one
    reply in flight/printed per call to this function.
    """
    hud_server.set_state("thinking")
    barge_listener = Listener(streaming_transcribe=True)
    istate = InterruptState(barge_listener.speech_detected)
    gen_stop_event = threading.Event()
    speaker.reset()

    primary_result: dict = {}

    def stream_fn(on_delta, stop_event, _sid=session_id, _text=user_text):
        chat.run_turn(_sid, _text, on_delta=on_delta, stop_event=stop_event, spoken=True)

    def primary_worker() -> None:
        text, verdict = speak_reply_with_interrupts(client, speaker, istate, gen_stop_event, stream_fn)
        primary_result["text"] = text
        primary_result["verdict"] = verdict

    print(f"{AGENT_NAME}: ", end="", flush=True)
    primary_thread = threading.Thread(target=primary_worker)
    primary_thread.start()

    # This thread's job while the primary runs: watch for a barge-in. Poll
    # rather than a single blocking wait so we notice as soon as the
    # primary finishes naturally too (nothing to wait for at that point).
    while primary_thread.is_alive():
        if istate.speech_detected.wait(timeout=0.05):
            break

    # Race condition fixed 2026-07-20: speech_detected firing and the
    # primary finishing naturally are two independent clocks. If the
    # primary completed a full, uninterrupted reply microseconds before the
    # (test) trigger fired, the loop above still exits and speech_detected
    # can still read True here even though there's nothing left to pause —
    # on_delta never got another chance to notice it. Re-checking is_alive()
    # here distinguishes "still running, actually blocked on this" from
    # "already done, this flag is stale" — a genuine interrupt only counts
    # if the primary thread is still around to have actually paused for it.
    if istate.speech_detected.is_set() and primary_thread.is_alive():
        print("[voice][interrupt] main thread saw speech_detected + primary still alive — handling", file=sys.stderr)
        barge_listener.wait_for_endpoint()
        interrupt_text = barge_listener.get_fresh_partial()
        if interrupt_text is None:
            audio = barge_listener.get_audio()
            interrupt_text = stt.transcribe_array(audio, sample_rate=SAMPLE_RATE).strip()
        if interrupt_text:
            hud_server.publish({"type": "user_final", "text": interrupt_text})
        print(f"[voice][interrupt] transcribed interruption: {interrupt_text!r}", file=sys.stderr)

        # Empty transcription (a cough, a click, ambient noise past the VAD
        # threshold) has nothing to act on — treat it as soft-with-nothing-
        # to-say so the primary just resumes rather than aborting on noise.
        verdict = classify_interrupt(interrupt_text) if interrupt_text else "soft"
        istate.verdict = verdict
        if verdict == "hard":
            # Fire the HUD flash before unblocking the primary — the actual
            # cancel (istate.classified.set(), right below) isn't delayed by
            # this, it's just a state write. The VISIBLE hold happens later
            # (after primary_thread.join(), which will be near-instant once
            # cancelled) so the flash reads clearly without adding real
            # latency to the interrupt reaction itself.
            hud_server.set_state("interrupted", label=interrupt_text[:70])
        istate.classified.set()  # unblocks the primary thread now

        if verdict == "soft" and interrupt_text:
            aside_speaker = Speaker(hud_feed=True)
            print(f"\nYou (aside): {interrupt_text}")
            print(f"{AGENT_NAME} (aside): ", end="", flush=True)
            aside_reply = run_quick_aside(session_id, interrupt_text, client, aside_speaker)
            print(aside_reply)
            aside_speaker.close()

        primary_thread.join()
        barge_listener.close()
        reply_text = primary_result.get("text", "")

        if verdict == "hard" and interrupt_text:
            print(reply_text)
            print(f"You: {interrupt_text}")
            time.sleep(0.35)  # let the "interrupted" flash actually be seen
            _speak_turn(client, speaker, session_id, interrupt_text)  # recurse: fresh turn
            return

        print(reply_text)
        return

    primary_thread.join()
    barge_listener.close()
    print(primary_result.get("text", ""))


def _open_hud_window(url: str) -> None:
    """Opens the HUD in a borderless app-mode browser window (no tabs/
    address bar — reads as a HUD, not 'a browser is open'). Tries Edge
    (default on Windows 11) then Chrome; falls back to the OS default
    browser opener (normal window, still functional, just not borderless)
    if neither is found. Never raises — a missing HUD window shouldn't
    crash the actual voice loop."""
    import shutil
    import subprocess

    candidates = [
        shutil.which("msedge"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        shutil.which("chrome"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ]
    for exe in candidates:
        if exe and os.path.exists(exe):
            try:
                subprocess.Popen([exe, f"--app={url}", "--window-size=460,560"])
                return
            except OSError:
                continue
    try:
        os.startfile(url)  # fallback: normal browser window
    except OSError as e:
        print(f"[voice] couldn't open the HUD window automatically ({e}) — open {url} manually.", file=sys.stderr)


def run(session_id: str) -> None:
    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not api_key:
        print(
            "ELEVENLABS_API_KEY is not set in .env — voice_loop.py needs real "
            "speech output to have anything to interrupt. Set it and retry.",
            file=sys.stderr,
        )
        return

    client = ElevenLabs(api_key=api_key)
    memory.init_db()
    memory.start_session(session_id, caller="AJ", client="Jarvis")

    hud_url = hud_server.start()
    _open_hud_window(hud_url)
    tray.start()

    speaker = Speaker(hud_feed=True)
    print(f"{AGENT_NAME} (voice) is up — session: {session_id}. Ctrl+C to quit.\n")

    try:
        while True:
            # --- Wait for the wake word ----------------------------------
            hud_server.set_state("idle")
            listener = Listener(hud_feed=True, streaming_transcribe=True)
            print("(listening for 'Jarvis'...)")
            got_speech = listener.wait_for_speech(max_seconds=MAX_CAPTURE_SECONDS)
            if not got_speech:
                listener.close()
                continue
            hud_server.set_state("listening")
            listener.wait_for_endpoint()
            heard = listener.get_fresh_partial()
            if heard is None:
                audio = listener.get_audio()
                heard = stt.transcribe_array(audio, sample_rate=SAMPLE_RATE)
            listener.close()
            hud_server.set_level(0.0)
            if heard:
                hud_server.publish({"type": "user_final", "text": heard})
            if not contains_wake_word(heard):
                # Not addressed to Jarvis (could be AJ talking to someone
                # else, TV audio, anything) — say nothing, don't log it,
                # just go back to waiting. This is the whole point of the
                # wake word: ambient speech shouldn't turn into a turn.
                continue

            hud_server.set_state("thinking")
            command = strip_wake_word(heard)

            if not command:
                # Just "Jarvis" alone — acknowledge briefly, then capture
                # the actual command as its own follow-up utterance (no
                # wake word needed for this immediate next thing).
                print("You: Jarvis")
                hud_server.set_state("speaking", label="Yes?")
                try:
                    ack_pcm = _synthesize_pcm(client, "Yes?")
                    speaker.play_pcm(ack_pcm)
                except Exception as e:  # noqa: BLE001
                    print(f"[voice] ack TTS failed ({e})", file=sys.stderr)

                hud_server.set_state("idle")
                follow_listener = Listener(hud_feed=True, streaming_transcribe=True)
                got_follow_up = follow_listener.wait_for_speech(max_seconds=8.0)
                if not got_follow_up:
                    follow_listener.close()
                    continue
                hud_server.set_state("listening")
                follow_listener.wait_for_endpoint()
                command = follow_listener.get_fresh_partial()
                if command is None:
                    follow_audio = follow_listener.get_audio()
                    command = stt.transcribe_array(follow_audio, sample_rate=SAMPLE_RATE).strip()
                follow_listener.close()
                hud_server.set_level(0.0)
                if command:
                    hud_server.publish({"type": "user_final", "text": command})
                hud_server.set_state("thinking")
                if not command:
                    continue

            print(f"You: {command}")
            if command.strip().lower() in {"exit", "quit", "bye"}:
                hud_server.set_state("idle")
                print(f"{AGENT_NAME}: See you, AJ.")
                break

            # --- Speak the reply. Runs in its own thread so THIS thread is
            # free to watch for a barge-in concurrently and, on a soft one,
            # dispatch the aside while the primary is still going. Prints
            # everything itself (including recursing into a fresh turn on a
            # hard cancel), so nothing to do here but call it. ------------
            _speak_turn(client, speaker, session_id, command)

            # --- Continuation grace window ---------------------------------
            # After a reply, real conversation doesn't require re-addressing
            # the other person by name for the next thing you say. Give a
            # few seconds where a follow-up is heard WITHOUT the wake word;
            # keep extending it turn-by-turn as long as AJ keeps talking,
            # only falling back to requiring "Jarvis" once this window
            # actually elapses with silence.
            while True:
                hud_server.set_state("idle", label="(still listening — no wake word needed)")
                grace_listener = Listener(hud_feed=True, streaming_transcribe=True)
                got_follow_up = grace_listener.wait_for_speech(max_seconds=GRACE_WINDOW_SECONDS)
                if not got_follow_up:
                    grace_listener.close()
                    break  # window elapsed in silence — back to requiring "Jarvis"

                hud_server.set_state("listening")
                grace_listener.wait_for_endpoint()
                follow_up = grace_listener.get_fresh_partial()
                if follow_up is None:
                    follow_audio = grace_listener.get_audio()
                    follow_up = stt.transcribe_array(follow_audio, sample_rate=SAMPLE_RATE).strip()
                grace_listener.close()
                hud_server.set_level(0.0)
                if follow_up:
                    hud_server.publish({"type": "user_final", "text": follow_up})
                if not follow_up:
                    continue  # false trigger (noise/breath) — stay in the grace window

                print(f"You: {follow_up}")
                if follow_up.strip().lower() in {"exit", "quit", "bye"}:
                    hud_server.set_state("idle")
                    print(f"{AGENT_NAME}: See you, AJ.")
                    return
                hud_server.set_state("thinking")
                _speak_turn(client, speaker, session_id, follow_up)
                # loop back: another grace window opens after THIS reply too

    except KeyboardInterrupt:
        print(f"\n{AGENT_NAME}: See you, AJ.")
    finally:
        hud_server.set_state("idle")
        speaker.close()
        # Session's over (normal exit or Ctrl+C either way) -- summarize
        # this session's SQLite history into today's vault file. See
        # memory_vault.py's module docstring; never raises.
        memory_vault.end_session(session_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Jarvis real-time voice loop with barge-in")
    parser.add_argument("--session", default="local", help="session id to continue (default: local)")
    parser.add_argument("--new", action="store_true", help="start a fresh timestamped session")
    args = parser.parse_args()

    session_id = (
        f"local-{datetime.now().strftime('%Y%m%d-%H%M%S')}" if args.new else args.session
    )
    run(session_id)


if __name__ == "__main__":
    main()
