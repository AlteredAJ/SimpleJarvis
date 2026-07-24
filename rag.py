"""
rag.py — Keyword RAG + link-following retrieval over AJ's Obsidian wiki vault.

No vector DB, no embeddings, no external API. Pure stdlib.

Pipeline:
  1. Load every .md file under the vault's wiki/ folder (read-only).
  2. Score each page by tokenized keyword overlap between the query and
     the page's title + body (title matches weighted higher).
  3. Take the top `max_pages` scoring pages, then follow [[wikilinks]]
     found inside them to pull in directly-linked "neighbor" pages that
     exist as real files in the vault (deduped against what's already
     selected, capped at max_pages total).
  4. Concatenate into a single labeled context string, each page body
     truncated to `max_chars_per_page`.
  5. If nothing scores above zero, return "" — never force in
     irrelevant pages, never fabricate content.

This module never opens vault files in write/append mode and never
modifies anything under the vault path.
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Tuple

# Default vault location. Can be overridden via the WIKI_VAULT_PATH env var
# (read at call time, not import time, so tests can monkeypatch os.environ).
# CONFIRMED 2026-07-21: the live, Obsidian-synced vault on this machine is
# E:\Obsidian Vault\Alt3red (has a current wiki\ subfolder) -- the old
# odysseus\wikibrain path was a stale decoy copy, never the real vault.
DEFAULT_VAULT_PATH = (
    r"E:\Obsidian Vault\Alt3red\wiki"
)

_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")
_TOKEN_RE = re.compile(r"[a-z0-9']+")

# Generic English stopwords, kept short on purpose — this is keyword
# overlap scoring, not a full NLP stack.
_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "of", "to", "in",
    "on", "for", "with", "is", "are", "was", "were", "be", "been", "being",
    "this", "that", "these", "those", "it", "its", "as", "at", "by", "from",
    "about", "into", "over", "after", "before", "between", "out", "up",
    "down", "what", "when", "where", "who", "which", "why", "how", "do",
    "does", "did", "my", "me", "i", "you", "your", "we", "our", "me",
}


def _vault_path() -> str:
    return os.environ.get("WIKI_VAULT_PATH", DEFAULT_VAULT_PATH)


def _tokenize(text: str) -> List[str]:
    return [
        tok for tok in _TOKEN_RE.findall(text.lower())
        if tok not in _STOPWORDS and len(tok) > 1
    ]


def _load_pages(vault_path: str) -> Dict[str, str]:
    """Return {title: raw_content} for every .md file directly under vault_path.

    title == filename without the .md extension (matches Obsidian wikilink
    convention). Read-only: files are opened with 'r' only.
    """
    pages: Dict[str, str] = {}
    if not os.path.isdir(vault_path):
        return pages

    for entry in os.listdir(vault_path):
        if not entry.lower().endswith(".md"):
            continue
        full_path = os.path.join(vault_path, entry)
        if not os.path.isfile(full_path):
            continue
        title = entry[: -len(".md")]
        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                pages[title] = f.read()
        except OSError:
            continue
    return pages


def _score_page(query_tokens: List[str], title: str, content: str) -> float:
    if not query_tokens:
        return 0.0

    query_set = set(query_tokens)

    title_tokens = _tokenize(title)
    title_hits = sum(1 for t in title_tokens if t in query_set)
    # Also credit partial/substring title matches (e.g. query "med school"
    # against title "Med School Application").
    title_lower = title.lower()
    substring_bonus = 0.0
    for tok in query_set:
        if len(tok) > 2 and tok in title_lower:
            substring_bonus += 1.0

    body_tokens = _tokenize(content)
    body_hits = sum(1 for t in body_tokens if t in query_set)

    # Title matches weighted much higher than body matches, and body score
    # is normalized a bit by log-ish scaling so huge files don't win purely
    # on length.
    score = (title_hits * 5.0) + (substring_bonus * 3.0) + body_hits * 1.0
    return score


def _extract_wikilinks(content: str) -> List[str]:
    links = []
    for match in _WIKILINK_RE.finditer(content):
        name = match.group(1).strip()
        if name:
            links.append(name)
    return links


def _format_chunk(title: str, content: str, max_chars_per_page: int) -> str:
    body = content.strip()
    if len(body) > max_chars_per_page:
        body = body[:max_chars_per_page].rstrip() + "\n...[truncated]"
    return f"## Wiki: {title}\n{body}"


def list_page_titles() -> List[str]:
    """Return every page title (filename minus .md) currently in the vault.
    Read-only, same loader as get_context(). Used by pins.py to validate
    that a title a user wants to pin actually exists before pinning it."""
    return sorted(_load_pages(_vault_path()).keys())


def get_page(title: str, max_chars: int | None = None) -> str | None:
    """Return the raw content of a single page by exact title, or None if
    it doesn't exist. Read-only. Used by pins.py to pull full pinned-page
    text without duplicating the vault-loading logic."""
    pages = _load_pages(_vault_path())
    content = pages.get(title)
    if content is None:
        return None
    if max_chars is not None and len(content) > max_chars:
        return content[:max_chars].rstrip() + "\n...[truncated]"
    return content


def get_context(query: str, max_pages: int = 5, max_chars_per_page: int = 3000) -> str:
    """Retrieve wiki context relevant to `query`.

    Returns a single string with each selected page labeled as
    "## Wiki: <title>", or "" if nothing in the vault scores above zero
    for this query.
    """
    if not query or not query.strip():
        return ""

    vault_path = _vault_path()
    pages = _load_pages(vault_path)
    if not pages:
        return ""

    query_tokens = _tokenize(query)
    if not query_tokens:
        return ""

    scored: List[Tuple[float, str]] = []
    for title, content in pages.items():
        score = _score_page(query_tokens, title, content)
        if score > 0:
            scored.append((score, title))

    if not scored:
        return ""

    scored.sort(key=lambda pair: (-pair[0], pair[1].lower()))
    top_titles = [title for _, title in scored[:max_pages]]

    selected: List[str] = list(top_titles)
    selected_set = set(selected)

    # Link-following: pull in neighbor pages referenced via [[wikilink]]
    # inside the top-scoring pages, if they exist as real files and we
    # still have room under max_pages.
    if len(selected) < max_pages:
        for title in top_titles:
            if len(selected) >= max_pages:
                break
            content = pages.get(title, "")
            for link_name in _extract_wikilinks(content):
                if len(selected) >= max_pages:
                    break
                if link_name in selected_set:
                    continue
                if link_name in pages:
                    selected.append(link_name)
                    selected_set.add(link_name)

    chunks = [
        _format_chunk(title, pages[title], max_chars_per_page)
        for title in selected
    ]
    return "\n\n".join(chunks)
