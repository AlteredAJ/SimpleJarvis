"""
brain_ollama.py — local Ollama backend for Jarvis, shaped to drop into an
agentic tool-use loop the same way agent.py's Anthropic-based loop works.

WHY THIS EXISTS
----------------
agent.py talks to the Anthropic Messages API and consumes the response as:

    response.content        -> list of content BLOCKS (objects)
        block.type           -> "text" | "tool_use"
        block.text            (when type == "text")
        block.name             (when type == "tool_use")
        block.input             (when type == "tool_use", already-parsed dict)
        block.id                (when type == "tool_use", used to match tool_result)
    response.stop_reason    -> "tool_use" when the model wants to call a tool,
                                something else (e.g. "end_turn") when it's done.

This module talks to a local Ollama server instead (default
http://localhost:11434) and returns a plain dict shaped so a near-identical
loop can consume it. The only difference from agent.py's pattern is that
blocks here are DICTS, not objects with attributes — so callers use
block["type"] instead of block.type. Everything else (the shape, the
field names, the branching logic) mirrors agent.py on purpose.

RETURN SHAPE OF chat()
-----------------------
    {
        "content": [
            # zero or more text blocks, e.g.:
            {"type": "text", "text": "..."},

            # zero or more tool_use blocks, e.g.:
            {"type": "tool_use", "id": "call_xxxx", "name": "get_weather",
             "input": {"location": "Paris"}},
        ],
        "stop_reason": "tool_use" | "end_turn",
        "raw": {...},   # the full, unmodified Ollama /api/chat response, for debugging
    }

A caller loop looks almost identical to agent.py's:

    while True:
        response = chat(messages, tools=TOOLS)
        text_parts = [b["text"] for b in response["content"] if b["type"] == "text"]

        if response["stop_reason"] != "tool_use":
            reply = " ".join(text_parts).strip()
            return reply

        tool_results = []
        for block in response["content"]:
            if block["type"] != "tool_use":
                continue
            result_text = dispatch_tool(block["name"], block["input"])
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block["id"],
                "content": result_text,
            })

        messages = messages + [
            {"role": "assistant", "content": text_parts_or_tool_calls...},
            {"role": "user", "content": tool_results},
        ]

    Note: unlike Anthropic, Ollama's /api/chat expects the assistant turn's
    tool calls to be re-sent as a normal {"role": "assistant", "tool_calls": [...]}
    message and each tool result as its own {"role": "tool", "content": "..."}
    message (OpenAI-style), NOT as Anthropic-style "tool_result" content
    blocks nested in a user message. See `format_tool_result_message()` and
    `format_assistant_message()` below — use those instead of hand-rolling
    the follow-up messages if you want them to round-trip correctly through
    Ollama.

TOOL-CALLING SUPPORT — VERIFIED, NOT A FALLBACK
-------------------------------------------------
qwen3:8b (the model this module defaults to) DOES support Ollama's native
/api/chat `tools` parameter (OpenAI function-calling-style schema). This was
verified directly against this machine's Ollama 0.32.0 install: a tool-bearing
request against qwen3:8b returned a proper
    message.tool_calls = [{"function": {"name": "get_weather", "arguments": {"location": "Paris"}}}]
with message.content == "" and a separate message.thinking field containing
qwen3's chain-of-thought (qwen3 is a "thinking" model; see NOTES below).

This module uses REAL tool-calling via the `tools` param — it does NOT use
a prompting+JSON-parsing fallback. That fallback code path is not implemented
here. If you swap in a model that does not support function calling (e.g.
llama3.2:3b, which does NOT reliably honor the `tools` param), tool_calls
will simply come back empty even when tools are supplied — chat() does not
detect this or fall back automatically. Verify tool support per-model before
relying on it.

NOTES ON qwen3:8b "thinking" OUTPUT
--------------------------------------
qwen3 models emit a `thinking` field in the response message (their
reasoning trace) separate from `content`. This module does NOT surface
`thinking` as a content block (Anthropic's block-list model has no
equivalent by default) — it's dropped, but available on response["raw"]
if you want to log or inspect it.

HTTP CLIENT
-----------
Uses httpx (already in requirements.txt), synchronous client, against
http://localhost:11434/api/chat. No API key — purely local.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")
DEFAULT_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "120"))


def chat(
    messages: list[dict],
    tools: list[dict] | None = None,
    model: str | None = None,
    think: bool = False,
) -> dict:
    """
    Send a chat request to the local Ollama server and return an
    Anthropic-agent.py-shaped dict. See module docstring for the exact shape.

    messages: OpenAI/Ollama-style list of {"role": ..., "content": ...} dicts.
              role is one of "system", "user", "assistant", "tool".
    tools:    optional list of OpenAI-function-style tool specs, e.g.:
                  {
                      "type": "function",
                      "function": {
                          "name": "get_weather",
                          "description": "...",
                          "parameters": {"type": "object", "properties": {...}, "required": [...]},
                      },
                  }
              Pass None/[] for pure conversation with no tool use.
    model:    Ollama model tag to use. Defaults to DEFAULT_MODEL (qwen3:8b),
              overridable via the OLLAMA_MODEL env var or this argument.
    think:    qwen3:8b is a "thinking" model — by default Ollama runs an
              extended chain-of-thought pass before answering, which measured
              ~7-8s of added latency per turn on this machine (vs. ~0.5-1s
              with it off) for zero benefit on casual conversation. Defaults
              to False here for a responsive, live-feeling chat. Pass True
              for questions that actually benefit from deeper reasoning
              (e.g. complex multi-step analysis) — it's a genuine accuracy/
              latency tradeoff, not a bug being worked around.

    Returns:  {"content": [...], "stop_reason": "tool_use"|"end_turn", "raw": {...}}

    Raises:   httpx.HTTPStatusError if Ollama returns a non-2xx response,
              httpx.ConnectError if the local Ollama server isn't running.
    """
    payload: dict[str, Any] = {
        "model": model or DEFAULT_MODEL,
        "messages": messages,
        "stream": False,
        "think": think,
    }
    if tools:
        payload["tools"] = tools

    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        resp = client.post(f"{OLLAMA_HOST}/api/chat", json=payload)
        resp.raise_for_status()
        raw = resp.json()

    message = raw.get("message", {}) or {}
    content_blocks: list[dict] = []

    text = message.get("content") or ""
    if text:
        content_blocks.append({"type": "text", "text": text})

    tool_calls = message.get("tool_calls") or []
    for call in tool_calls:
        fn = call.get("function", {}) or {}
        content_blocks.append(
            {
                "type": "tool_use",
                "id": call.get("id") or f"call_{fn.get('name', 'unknown')}",
                "name": fn.get("name"),
                "input": fn.get("arguments") or {},
            }
        )

    stop_reason = "tool_use" if tool_calls else "end_turn"

    return {
        "content": content_blocks,
        "stop_reason": stop_reason,
        "raw": raw,
    }


def chat_stream(
    messages: list[dict],
    model: str | None = None,
    think: bool = False,
    stop_event=None,
):
    """
    Streaming variant of chat() for plain conversation (no tools — tool
    calls don't arrive incrementally in a way worth streaming, so callers
    that need tool use should use chat() instead).

    Yields plain text deltas (str) as they arrive from Ollama, so a caller
    can print them live instead of waiting for the full reply. This is what
    makes a text REPL feel like a live conversation instead of a request/
    response form — the model already generates token-by-token internally,
    stream=False just throws that away and waits for the end.

    stop_event: optional threading.Event. Checked before consuming each
    incoming line; if set, the loop breaks immediately, the HTTP stream is
    closed (via the `with client.stream(...)` context manager exiting), and
    the returned response dict has stop_reason="interrupted". This is what
    lets a barge-in ("Jarvis, stop") actually cut generation short instead
    of just muting audio while the model keeps burning GPU time on a reply
    nobody's going to hear the rest of. See voice_loop.py for the caller
    that sets this.

    After the last delta, the generator's StopIteration.value carries the
    same response dict shape chat() returns (content blocks + stop_reason +
    raw), for callers that also want the final structured result (e.g. to
    append to conversation history). Simpler in practice: use
    `stream_and_collect()` below, which drives this generator for you and
    returns (full_text, response_dict).
    """
    payload: dict[str, Any] = {
        "model": model or DEFAULT_MODEL,
        "messages": messages,
        "stream": True,
        "think": think,
    }

    full_text_parts: list[str] = []
    last_raw: dict = {}
    interrupted = False

    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        with client.stream("POST", f"{OLLAMA_HOST}/api/chat", json=payload) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if stop_event is not None and stop_event.is_set():
                    interrupted = True
                    break
                if not line:
                    continue
                chunk = json.loads(line)
                last_raw = chunk
                delta = (chunk.get("message") or {}).get("content") or ""
                if delta:
                    full_text_parts.append(delta)
                    yield delta

    full_text = "".join(full_text_parts)
    content_blocks = [{"type": "text", "text": full_text}] if full_text else []
    return {
        "content": content_blocks,
        "stop_reason": "interrupted" if interrupted else "end_turn",
        "raw": last_raw,
    }


def stream_and_collect(
    messages: list[dict],
    model: str | None = None,
    think: bool = False,
    on_delta=None,
    stop_event=None,
) -> tuple[str, dict]:
    """
    Drives chat_stream() to completion (or interruption) and returns
    (full_text, response_dict) — the ergonomic way to use streaming without
    dealing with generator return-value plumbing. Pass on_delta(text_chunk)
    to get called as each piece arrives (e.g. print it, or feed it to a
    sentence-chunked TTS queue). full_text/response_dict come back once
    generation is done OR stop_event fires mid-stream — check
    response_dict["stop_reason"] == "interrupted" to tell the difference
    from a normal completion; full_text will be whatever was generated up
    to the interruption point, not empty.
    """
    gen = chat_stream(messages, model=model, think=think, stop_event=stop_event)
    try:
        while True:
            delta = next(gen)
            if on_delta:
                on_delta(delta)
    except StopIteration as stop:
        response = stop.value or {"content": [], "stop_reason": "end_turn", "raw": {}}

    text_parts = [b["text"] for b in response["content"] if b["type"] == "text"]
    return " ".join(text_parts).strip(), response


def format_assistant_message(response: dict) -> dict:
    """
    Build the {"role": "assistant", ...} message to append to `messages`
    after a chat() call, suitable for feeding back into Ollama on the next
    turn. Ollama expects tool calls back in OpenAI "tool_calls" shape, not
    Anthropic content blocks.
    """
    text_parts = [b["text"] for b in response["content"] if b["type"] == "text"]
    tool_use_blocks = [b for b in response["content"] if b["type"] == "tool_use"]

    msg: dict[str, Any] = {"role": "assistant", "content": " ".join(text_parts)}
    if tool_use_blocks:
        msg["tool_calls"] = [
            {
                "id": b["id"],
                "function": {"name": b["name"], "arguments": b["input"]},
            }
            for b in tool_use_blocks
        ]
    return msg


def format_tool_result_message(tool_use_id: str, name: str, content: str) -> dict:
    """
    Build a single {"role": "tool", ...} message for one tool result, in the
    shape Ollama's /api/chat expects. Ollama (OpenAI-style) wants ONE "tool"
    message per result, not a batched Anthropic-style "tool_result" content
    block — call this once per tool call and append each message.
    """
    return {
        "role": "tool",
        "tool_call_id": tool_use_id,
        "name": name,
        "content": content,
    }
