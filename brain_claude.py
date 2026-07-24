"""
brain_claude.py -- Claude API backend for Jarvis (Phase 1 brain swap).

Replaces brain_ollama.py as chat.py's model backend. AJ confirmed a real
Anthropic API key with credits on the account (2026-07-21) -- see
PHASE1-BUILD-PLAN.md section 0/2 for the full rationale.

CALL CONTRACT -- kept identical to brain_ollama.stream_and_collect on
purpose, so chat.py and voice_loop.py need no changes beyond the import
line:
    stream_and_collect(messages, on_delta=None, stop_event=None) -> (full_text, response)

messages[0] is the {"role": "system", "content": "..."} dict chat.py's
_build_system_message() builds; everything after is conversation history +
the current turn. The Anthropic Messages API takes `system` as a top-level
request field, not a message -- _split_system() below does that split so
callers don't have to change how they build `messages`.

MODEL ROUTING (see PHASE1-BUILD-PLAN.md section 2b) -- deliberately NOT a
local-model router. The research report that fed this plan proposed
keeping qwen3:8b as a per-utterance intent classifier in front of Claude;
that was dropped on purpose:
  1. voice_loop.py's own comments record qwen3:8b prompt-eval alone taking
     5+ seconds on this machine -- routing every utterance through it
     before Claude even starts would add exactly the dead air this
     codebase has been fighting to remove.
  2. With Haiku 4.5's pricing, 100 escalated turns/day costs ~$3-5/month
     even *without* caching (see below) -- the local router would burn
     VRAM and add latency to save money nobody was going to spend.
Deterministic keyword routing (mirroring the existing HARD_CANCEL_PHRASES
style classifier in voice_loop.py) plus a cheap escalation heuristic here
covers the actual cost-conservatism goal for a fraction of the complexity.

CACHING -- deliberately OFF for now. Haiku 4.5's minimum cacheable prefix
is 4096 tokens; the current Jarvis system prompt measures ~900-1600 tokens
(persona + pins + daily memory), well under that floor. Below the floor,
`cache_control` silently does nothing (cache_creation_input_tokens stays
0, full price every turn, no error) -- and padding the prompt with filler
just to clear 4096 would cost MORE than leaving caching off. See
PHASE1-BUILD-PLAN.md section 2c. When the prompt organically grows past
4096 tokens, flip caching on by passing `system` as a list of blocks with
`cache_control` on the last one instead of a plain string here.
"""

from __future__ import annotations

import re

import anthropic

DEFAULT_MODEL = "claude-haiku-4-5"
ESCALATION_MODEL = "claude-sonnet-5"
MAX_TOKENS = 1024  # spoken replies are short; keep this low

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """Lazy singleton -- resolves ANTHROPIC_API_KEY (or an `ant auth login`
    profile) on first real use, not at import time, so importing this
    module doesn't require credentials to already be configured."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


# Deterministic escalation triggers -- same philosophy as voice_loop.py's
# HARD_CANCEL_PHRASES classifier: a hard keyword list checked in code, not
# left to the model's own judgment about which model should answer it.
_ESCALATION_TRIGGERS = re.compile(
    r"\b("
    r"think (hard|carefully|it through)|think about this|"
    r"use sonnet|"
    r"analyz|debug|"
    r"plan (this|it) (out|properly)|"
    r"deep dive|walk me through|step by step|"
    r"in depth|thoroughly"
    r")\b",
    re.IGNORECASE,
)
_CODE_SHAPE_RE = re.compile(r"```|\bdef \w+\(|\bfunction \w+\(|\bclass \w+\b")


def should_escalate(user_text: str) -> bool:
    """Decides Haiku vs. Sonnet 5 with zero API calls -- see the module
    docstring for why this replaces a local-model router. Defaults to
    False (stay on the cheap/fast model) whenever it's not obviously a
    hard turn; escalation is the exception, not the default."""
    if not user_text:
        return False
    if _ESCALATION_TRIGGERS.search(user_text):
        return True
    if len(user_text.split()) > 60:
        return True
    if _CODE_SHAPE_RE.search(user_text):
        return True
    return False


def _split_system(messages: list[dict]) -> tuple[str, list[dict]]:
    """chat.py hands us [{"role": "system", ...}, *history]. Anthropic
    wants system as a top-level request field, not a message in the list
    -- split it off here so chat.py doesn't need to know that."""
    if messages and messages[0].get("role") == "system":
        return messages[0]["content"], messages[1:]
    return "", messages


def stream_and_collect(
    messages: list[dict],
    on_delta=None,
    stop_event=None,
    model: str | None = None,
) -> tuple[str, object]:
    """Drop-in replacement for brain_ollama.stream_and_collect. Streams
    the reply, calling on_delta(text_chunk) as each piece arrives (for a
    live REPL print or sentence-chunked TTS), and returns
    (full_text, response) once generation finishes or stop_event fires.

    stop_event: checked between deltas. On a barge-in, we stop consuming
    the stream immediately -- whatever was generated up to that point is
    still returned in full_text (so it's saved to memory as what was
    actually said), but we deliberately do NOT call
    stream.get_final_message() on an interrupted stream: that call expects
    a complete message, and the SDK's internal accumulator only holds a
    partial one at that point. Returning a small interrupted-marker dict
    instead avoids depending on unverified SDK behavior for a path that
    matters a lot (a barge-in must never crash the voice loop).

    response: the real Anthropic Message object on a normal completion
    (chat.py only reads full_text today, but response.usage is there if
    you want to log cache_read_input_tokens once caching is switched on --
    see the module docstring), or {"stop_reason": "interrupted"} if the
    stream was cut short.
    """
    system_text, history = _split_system(messages)

    if model is None:
        last_user_text = next(
            (
                m["content"]
                for m in reversed(history)
                if m.get("role") == "user" and isinstance(m.get("content"), str)
            ),
            "",
        )
        model = ESCALATION_MODEL if should_escalate(last_user_text) else DEFAULT_MODEL

    client = _get_client()
    full_text_parts: list[str] = []
    interrupted = False

    stream_kwargs: dict = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "messages": history,
    }
    if system_text:
        stream_kwargs["system"] = system_text

    response: object = {"stop_reason": "interrupted"}
    with client.messages.stream(**stream_kwargs) as stream:
        for text in stream.text_stream:
            if stop_event is not None and stop_event.is_set():
                interrupted = True
                break
            full_text_parts.append(text)
            if on_delta:
                on_delta(text)
        if not interrupted:
            response = stream.get_final_message()
        # else: exiting the `with` block here closes the HTTP stream
        # without waiting for the rest of the generation -- the barge-in
        # equivalent of brain_ollama.chat_stream's stop_event handling.

    full_text = "".join(full_text_parts).strip()
    return full_text, response
