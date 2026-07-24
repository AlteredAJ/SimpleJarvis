---
type: reference
tags: [setup, wiki-brain, graphify, obsidian, claude]
---

# Setup — Wiki-Brain & Graphify

## Vault

**Path:** `/Users/ajapaukese/Claude`
**Obsidian vault** is open here. Graphify outputs live in `graphify-out/`.

## Graphify

- Installed via `python3.12 -m pip install graphifyy`
- Latest: v0.5.0 (installed 2026-04-26)
- Knowledge graph lives at `~/.claude/graphify-out/graph.json`
- Obsidian-ready notes generated at `/Users/ajapaukese/Claude/graphify-out/obsidian/`
- Use `python3` in shell → resolves to old Python 3.7. Always use `python3.12` explicitly.

## Agent Tools (Token-Saving Research Scrapers)

Installed to reduce Claude's token spend on research/scraping tasks:

| Tool | Version | Installed | Repo | Purpose |
|---|---|---|---|---|
| Scrapling | 0.4.11 | 2026-07-04 | https://github.com/D4Vinci/Scrapling | Adaptive self-healing web scraper (static/semi-static pages) |
| Agent Reach | 1.5.0 | 2026-07-04 | https://github.com/Panniantong/agent-reach | Multi-source reach: YouTube transcripts, GitHub, RSS, Exa semantic search, Bilibili, etc. |

**Installation:**
- Scrapling: `python3.12 -m pip install scrapling`
- Agent Reach: `python3.12 -m pip install git+https://github.com/Panniantong/agent-reach.git`

**Availability:** Both land in `/Users/ajapaukese/Library/Python/3.12/bin/` which is added to PATH in `~/.zshrc` (2026-07-04).

## Wiki-Brain

- Cadence: **rebuild every 7 days**, lint every 30 days
- SessionEnd hook: `~/.claude/skills/wiki-brain/hooks/session-end.sh`
- Configured in `~/.claude/settings.json`

## CLAUDE.md (Global)

Context Navigation block added to `~/.claude/CLAUDE.md`. Claude queries the graph before reading raw files.

## Folder Structure

```
/Users/ajapaukese/Claude/
  wiki/           ← synthesized knowledge pages (here)
  raw/            ← drop source files here to ingest
  graphify-out/
    obsidian/     ← node notes for Obsidian graph view
    graph.json    ← GraphRAG-ready graph
    graph.html    ← interactive viz (open in browser)
  Legal Stuff/
    Traffic Tickets/
  School/
    Spring 2026/
```

## Known Issues

- `graph.html` won't render if opened as `file://` with CDN blocked → serve locally: `cd ~/.claude/graphify-out && python3.12 -m http.server 8888`
- Obsidian graph was empty because `--obsidian` flag was never run — fixed by running `to_obsidian()` manually
