"""
memory_vault.py -- persistent, human-readable Jarvis memory, living inside
AJ's real Obsidian vault. See PHASE1-BUILD-PLAN.md section 3 for the full
design this implements.

ROLE SPLIT (don't conflate these two stores):
  - memory.py (SQLite) stays exactly as it is: the fast, ephemeral,
    per-session buffer memory.py's get_history()/append_message() already
    handle, used to assemble the live conversation prompt each turn.
  - THIS module is the durable, long-term store: one dated Markdown file
    per day, written ONLY inside a dedicated vault subfolder
    (_Jarvis_Memory/) -- never touching any other file in AJ's vault, per
    JARVIS-BRIEF.md's "read-heavy, write-narrow" rule. One file per day
    (not per session) so the vault doesn't fragment into dozens of tiny
    session files -- sessions within a day are just headers inside it.

WRITE PATH (salience, never a raw transcript dump): call end_session() when
a session is genuinely over (exit/quit/bye, Ctrl+C, or process shutdown).
It pulls that session's raw turns out of SQLite, asks Claude Haiku for a
short salience summary (facts/decisions/preferences/action items -- never
"the user said X, then I said Y"), and appends it under a
"### Session HH:MM" header in today's file. Filler, false starts, and STT
noise never reach the vault.

READ PATH -- tiered, matching PHASE1-BUILD-PLAN.md section 3d:
  - Tier 1 (get_daily_context, always, no API call): today's file so far +
    yesterday's one-line frontmatter summary. Cheap enough to inject into
    every turn's system prompt.
  - Tier 2 (search_memory, on demand): keyword search across older daily
    files, reusing the same keyword-overlap approach as rag.py -- no
    vector DB, no embeddings, nothing that needs the Arc B580's GPU. This
    is deliberately deferred to a later phase for anything fancier
    (OpenVINO embeddings, etc.) -- keyword search is plenty for one
    person's daily logs.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from pathlib import Path

import anthropic

import memory

# CONFIRMED 2026-07-21: the live Obsidian vault root on this machine.
VAULT_ROOT = Path(os.environ.get("JARVIS_VAULT_PATH", r"E:\Obsidian Vault\Alt3red"))
MEMORY_DIR = VAULT_ROOT / "_Jarvis_Memory"

_SUMMARY_MODEL = "claude-haiku-4-5"
_FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n\n?", re.DOTALL)

_TOKEN_RE = re.compile(r"[a-z0-9']+")
_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "of", "to", "in",
    "on", "for", "with", "is", "are", "was", "were", "be", "been", "being",
    "this", "that", "these", "those", "it", "its", "as", "at", "by", "from",
    "what", "when", "where", "who", "which", "why", "how", "do", "does",
    "did", "my", "me", "i", "you", "your", "we", "our",
}


def _tokenize(text: str) -> set[str]:
    return {
        t for t in _TOKEN_RE.findall(text.lower())
        if t not in _STOPWORDS and len(t) > 1
    }


def _day_path(day: datetime) -> Path:
    return MEMORY_DIR / f"{day.strftime('%Y-%m-%d')}.md"


def _ensure_frontmatter(path: Path, date_str: str) -> None:
    if path.exists():
        return
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ndate: {date_str}\ntags: [jarvis/daily-log]\n---\n\n",
        encoding="utf-8",
    )


def _strip_frontmatter(text: str) -> str:
    return _FRONTMATTER_RE.sub("", text, count=1)


def _read_frontmatter_summary(path: Path) -> str:
    """Best-effort pull of a `summary:` frontmatter line out of a daily
    file. Returns "" if the file or the field doesn't exist -- this is a
    nicety, not something that should ever raise."""
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    match = re.search(r'^summary:\s*"?(.*?)"?\s*$', text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def summarize_session(messages: list[dict]) -> str:
    """One cheap Claude Haiku call: raw session turns in, clean salience
    bullets out. Never a verbatim transcript -- conversational filler and
    STT errors would otherwise pollute a knowledge base meant to be
    read/searched later. Returns "" on empty input or any failure --
    summarization is best-effort and must never crash a session end."""
    if not messages:
        return ""

    transcript = "\n".join(
        f"{m['role']}: {m['content']}"
        for m in messages
        if isinstance(m.get("content"), str) and m["content"].strip()
    )
    if not transcript.strip():
        return ""

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=_SUMMARY_MODEL,
            max_tokens=400,
            system=(
                "Extract only what's worth remembering long-term from this "
                "conversation: concrete facts, decisions, preferences, and "
                "action items. Write terse Markdown bullet points, one per "
                "line, no preamble, no restating the obvious. If truly "
                "nothing is worth remembering, reply with exactly: "
                "(nothing notable)"
            ),
            messages=[{"role": "user", "content": transcript}],
        )
        text = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()
        return "" if text == "(nothing notable)" else text
    except Exception:  # noqa: BLE001 - best-effort; a bad summary is not worth crashing over
        return ""


def append_session_summary(bullets: str, when: datetime | None = None) -> None:
    """Appends `bullets` under a "### Session HH:MM" header in the daily
    file for `when` (defaults to now). No-op on empty input -- an empty
    session isn't worth a header with nothing under it."""
    if not bullets.strip():
        return
    when = when or datetime.now()
    path = _day_path(when)
    _ensure_frontmatter(path, when.strftime("%Y-%m-%d"))
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"### Session {when.strftime('%H:%M')}\n{bullets.strip()}\n\n")


def end_session(session_id: str) -> None:
    """Call once a session is genuinely ending (exit/quit/bye,
    KeyboardInterrupt, or a finally block at process shutdown). Reads the
    session's raw turns out of SQLite (memory.py), summarizes them, and
    appends to today's vault file. Never raises -- a memory-write failure
    must never take down the voice loop or the text REPL.
    """
    try:
        history = memory.get_history(session_id)
        bullets = summarize_session(history)
        append_session_summary(bullets)
    except Exception:  # noqa: BLE001 - see docstring
        pass


def get_daily_context(max_chars: int = 1500) -> str:
    """Tier 1 recall (see module docstring): today's file so far, plus
    yesterday's one-line frontmatter summary. No API call -- just two file
    reads. Returns "" if there's nothing yet (e.g. a brand new install)."""
    now = datetime.now()
    parts: list[str] = []

    yesterday_summary = _read_frontmatter_summary(_day_path(now - timedelta(days=1)))
    if yesterday_summary:
        parts.append(f"Yesterday: {yesterday_summary}")

    today_path = _day_path(now)
    if today_path.exists():
        try:
            today_text = today_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            today_text = ""
        body = _strip_frontmatter(today_text).strip()
        if body:
            parts.append(f"Today so far:\n{body}")

    if not parts:
        return ""

    text = "\n\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n...[truncated]"
    return f"## Jarvis Memory (recent)\n{text}"


def search_memory(query: str, max_files: int = 3, max_chars_per_file: int = 800) -> str:
    """Tier 2 recall (see module docstring): keyword search across OLDER
    daily files (today is excluded -- Tier 1 already covers it), same
    keyword-overlap approach as rag.py. Returns "" if the query is empty,
    the memory folder doesn't exist yet, or nothing scores above zero --
    never force in irrelevant days."""
    if not query or not MEMORY_DIR.is_dir():
        return ""

    query_tokens = _tokenize(query)
    if not query_tokens:
        return ""

    today_name = _day_path(datetime.now()).name
    scored: list[tuple[int, Path]] = []
    for path in MEMORY_DIR.glob("*.md"):
        if path.name == today_name:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hits = sum(1 for t in _tokenize(text) if t in query_tokens)
        if hits > 0:
            scored.append((hits, path))

    if not scored:
        return ""

    scored.sort(key=lambda pair: -pair[0])
    top = scored[:max_files]

    chunks = []
    for _, path in top:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        body = _strip_frontmatter(text).strip()
        if len(body) > max_chars_per_file:
            body = body[:max_chars_per_file].rstrip() + "\n...[truncated]"
        chunks.append(f"## Memory: {path.stem}\n{body}")

    return "\n\n".join(chunks)
