"""
brain_openai_compat.py -- OpenAI-compatible API backend (DeepSeek default).

Same stream_and_collect contract as brain_claude.py -- drop-in for chat.py.
Uses httpx (already in requirements.txt), no openai pip package needed.

Providers:
  - DeepSeek (default): https://api.deepseek.com/v1, 4x cheaper than Haiku
  - Any OpenAI-compatible endpoint via LLM_BASE_URL env var

Env vars:
  DEEPSEEK_API_KEY    -- required
  LLM_PROVIDER        -- "deepseek" (default) | "openai"
  LLM_BASE_URL        -- override the API base URL
  LLM_MODEL           -- override the model name (default: deepseek-chat)
"""

from __future__ import annotations

import json
import os

import httpx

DEEPSEEK_BASE = "https://api.deepseek.com/v1"
DEFAULT_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")
DEFAULT_MAX_TOKENS = 1024


def _api_key() -> str:
    provider = os.environ.get("LLM_PROVIDER", "deepseek")
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key and provider == "openai":
        key = os.environ.get("OPENAI_API_KEY", "")
    return key


def _base_url() -> str:
    return os.environ.get("LLM_BASE_URL", DEEPSEEK_BASE)


def _split_system(messages: list[dict]) -> tuple[str, list[dict]]:
    if messages and messages[0].get("role") == "system":
        return messages[0]["content"], messages[1:]
    return "", messages


def stream_and_collect(
    messages: list[dict],
    on_delta=None,
    stop_event=None,
    model: str | None = None,
) -> tuple[str, object]:
    system_text, history = _split_system(messages)

    if system_text:
        messages = [{"role": "system", "content": system_text}] + history
    else:
        messages = history

    payload = {
        "model": model or DEFAULT_MODEL,
        "messages": messages,
        "max_tokens": DEFAULT_MAX_TOKENS,
        "stream": True,
    }

    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }

    full_text_parts: list[str] = []
    interrupted = False
    last_raw: dict = {}

    with httpx.Client(timeout=120) as client:
        with client.stream(
            "POST",
            f"{_base_url()}/chat/completions",
            json=payload,
            headers=headers,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if stop_event is not None and stop_event.is_set():
                    interrupted = True
                    break
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[len("data: "):]
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                last_raw = chunk
                delta = (
                    chunk.get("choices", [{}])[0]
                    .get("delta", {})
                    .get("content", "")
                )
                if delta:
                    full_text_parts.append(delta)
                    if on_delta:
                        on_delta(delta)

    full_text = "".join(full_text_parts).strip()

    response = (
        {"stop_reason": "interrupted"}
        if interrupted
        else {"stop_reason": "end_turn", "raw": last_raw}
    )

    return full_text, response
