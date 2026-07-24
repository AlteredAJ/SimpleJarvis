"""
pins.py — explicit "pinned context" for Jarvis.

A pin is a wiki page title the user has explicitly chosen to feed into
EVERY future conversation turn, full text (up to a generous cap), on top
of whatever rag.py's automatic keyword retrieval surfaces for that turn's
query. This is the "primary context" layer described in JARVIS-BRIEF.md
section 3 (mirrors Local Brain's pinned-notes feature).

Storage: a flat JSON file (pinned.json) at the repo root — global, not
per-session, since a pin is meant to persist across every conversation
until explicitly unpinned. This is intentionally simple (no DB migration,
no new table) since it's just a list of titles.

Read-only w.r.t. the wiki vault itself — pinning never writes into the
vault, it only writes to this local JSON file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import rag

PINS_PATH = Path(os.environ.get("JARVIS_PINS_PATH", "pinned.json"))


def _load() -> list[str]:
    if not PINS_PATH.exists():
        return []
    try:
        with open(PINS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return list(data) if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save(titles: list[str]) -> None:
    with open(PINS_PATH, "w", encoding="utf-8") as f:
        json.dump(titles, f, indent=2)


def list_pins() -> list[str]:
    return _load()


def add_pin(title: str) -> tuple[bool, str]:
    """Pin a wiki page by exact title. Returns (ok, message).
    Validates the title actually exists in the vault before pinning —
    never pins a page that isn't real."""
    title = title.strip()
    if not title:
        return False, "No title given."

    available = rag.list_page_titles()
    if title not in available:
        # Try a case-insensitive exact match as a small usability nicety.
        matches = [t for t in available if t.lower() == title.lower()]
        if len(matches) == 1:
            title = matches[0]
        else:
            return False, f'No exact wiki page named "{title}" found.'

    pins = _load()
    if title in pins:
        return True, f'"{title}" is already pinned.'

    pins.append(title)
    _save(pins)
    return True, f'Pinned "{title}".'


def remove_pin(title: str) -> tuple[bool, str]:
    title = title.strip()
    pins = _load()
    matches = [t for t in pins if t.lower() == title.lower()]
    if not matches:
        return False, f'"{title}" isn\'t pinned.'
    pins = [t for t in pins if t not in matches]
    _save(pins)
    return True, f'Unpinned "{matches[0]}".'


def get_pinned_context(max_chars_per_page: int = 4000) -> str:
    """Full text of every currently-pinned page, formatted for prompt
    injection the same way rag.get_context() formats its chunks, labeled
    distinctly so the model (and a human reading logs) can tell pinned
    context apart from automatic retrieval."""
    pins = _load()
    if not pins:
        return ""

    chunks = []
    for title in pins:
        content = rag.get_page(title, max_chars=max_chars_per_page)
        if content is None:
            continue  # page was deleted/renamed since being pinned; skip silently
        chunks.append(f"## Pinned: {title}\n{content.strip()}")

    return "\n\n".join(chunks)
