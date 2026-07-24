# Jarvis — Phase 1 Build Plan (hand this to Claude Code)

**Read `JARVIS-BRIEF.md` first for project context, then this file for what actually
changes in Phase 1.** This plan supersedes the brief's "local Ollama only" constraint —
see §0. It is derived from a corrected deep-research report; the corrections are called
out inline so they don't get re-introduced.

---

## 0. What changed since the brief, and the one blocking assumption

The original brief (2026-07-19) assumed **no Anthropic API key** (Claude.ai is OAuth-only)
and mandated a local Ollama brain. That has changed: the plan now uses the **Claude API**
as the brain, run cost-conservatively.

> ✅ **CONFIRMED (2026-07-21):** AJ has a real Anthropic **API key with credits on the
> account** (not the Claude.ai subscription). Use `ANTHROPIC_API_KEY` (or an `ant auth login`
> profile) — the brain section below is good to build as written.

**Hardware (unchanged, load-bearing):** Intel Arc B580 (12GB, **no CUDA** — Vulkan/OpenVINO/
IPEX only), Ryzen 7800X3D-class, ~32GB RAM, Windows 11, Python 3.14 (some ML libs only build
on 3.12 — a known blocker). Jarvis must **coexist with heavy GPU/CPU work** — do not
monopolize the GPU.

---

## 1. Phase 1 scope (definition of done)

Jarvis listens (wake word), thinks via **Claude Haiku**, speaks back, can be interrupted,
and is grounded in AJ's Obsidian vault **plus its own persistent dated-Markdown memory**.
The existing voice loop, barge-in, and HUD stay as-is.

**In scope:** brain swap (Ollama → cost-conservative Claude), vault-based Markdown memory.
**Explicitly OUT of scope for Phase 1** (later phases): the live-transcript UI rework,
local TTS migration (keep ElevenLabs), wake-word/VAD/AEC upgrades, local embeddings via
OpenVINO, computer control. Do not build these now.

---

## 2. The brain: Ollama → cost-conservative Claude

Replace the local `qwen3:8b` call in `brain_ollama.py` (consumed by `chat.py`'s
`run_turn` → `stream_and_collect`) with the Anthropic SDK. Keep `chat.run_turn`'s
signature and streaming contract identical (`on_delta`, `stop_event`) so `voice_loop.py`
needs no changes.

### 2a. Models (exact IDs — do not append date suffixes)
- **Default brain:** `claude-haiku-4-5` — fast (150–250 tok/s), cheap, ideal for real-time voice.
- **Escalation for hard turns only:** `claude-sonnet-5` (the current top Sonnet — *not*
  `claude-sonnet-4-6`, which the research report used).
- Do **not** use thinking. Haiku 4.5 predates adaptive thinking; omit the `thinking`
  param entirely (a plain, fast response is what a voice reply needs).

### 2b. ❌ DROP the local qwen3:8b router the report proposed
The research report kept `qwen3:8b` as a per-utterance intent router. **Do not build this.**
Reasons (both grounded in this repo's own code): (1) `voice_loop.py` documents that
qwen3:8b prompt-eval alone "can take 5+s" on this machine — routing every utterance through
it before Claude would add seconds of dead air to a voice loop; (2) with prompt caching,
Haiku costs ≈ $5/month at 100 turns/day, so the router saves money that wasn't being spent
while adding VRAM pressure against AJ's primary work.

**Instead, route with cheap deterministic rules** (mirror the existing keyword classifiers
in `voice_loop.py`, e.g. `classify_interrupt`):
- **Handle locally, no API call:** trivial deterministic commands — time/date ("what time is
  it"), "stop/cancel", exit. A small keyword/regex table. Zero tokens.
- **Everything else → Haiku.**
- **Escalate to Sonnet 5** only when a turn is genuinely hard: trigger on an explicit ask
  ("think hard", "use sonnet", "analyze/debug/plan this properly") or a simple heuristic
  (e.g. user message > ~60 words, or contains code). Keep this a single small function;
  default to Haiku when unsure.

### 2c. Prompt caching — the cost mechanism (get the structure right)
Caching cuts cached input tokens to 0.1×. It is a **prefix match**: the cached block must be
byte-stable and come first.

> ⚠️ **MEASURED (2026-07-21) — caching is NOT worth it yet; do not force it.** Haiku 4.5's
> minimum cacheable prefix is **4,096 tokens**; below that, caching silently does nothing
> (`usage.cache_creation_input_tokens: 0`, full price, no error). The current static persona
> is only ~900–1,000 tokens (`SYSTEM_PROMPT_TEMPLATE` 2,648 chars + `SPOKEN_MODE_ADDENDUM`
> 884 chars ≈ 3,532 chars ≈ ~900 tokens); even with daily memory + a pin or two the base
> prefix is ~1,200–1,600 tokens — about **a third of the threshold.**
>
> **Do NOT pad with filler to reach 4,096** — that writes/reads ~2,900 junk tokens every turn
> and costs *more* than it saves. At the real ~1,200-token size the uncached prefix runs
> ~$3–4/month at 100 turns/day on Haiku — negligible. So for Phase 1: **build the prefix in
> the cache-ready structure below (stable-first) but leave `cache_control` OFF** until the
> prefix organically clears 4,096 tokens (larger persona, always-injected memory, several
> pinned wiki pages). Add the one `cache_control` breakpoint the day
> `count_tokens(system_blocks) ≥ 4096`, and confirm it fired via
> `response.usage.cache_read_input_tokens > 0`. The structure matters now; the breakpoint is a
> one-line switch later.

**Required prompt restructure — `chat.py`'s `_build_system_message` currently breaks
caching** by interpolating per-query wiki RAG *into* the system prompt (changes every turn →
never caches). Split it:

1. **Cached prefix (stable, `cache_control: {"type": "ephemeral"}` on the last block):**
   - The static persona/instructions (`SYSTEM_PROMPT_TEMPLATE`, `SPOKEN_MODE_ADDENDUM`, etc.),
     **with the volatile `today` date removed from it** (a date string changes daily and, mid-
     conversation, is fine — but keep it out of the cached prefix; inject the date as a normal
     user-turn preamble or a later block).
   - Pinned vault context (`pins.get_pinned_context()`) — semi-stable within a session.
   - Today's + yesterday's memory summary (see §3) — stable within a session.
   - Pad to ≥ 4,096 tokens if needed (the persona is already large; measure with
     `client.messages.count_tokens`).
2. **Uncached tail (volatile, no cache_control):** per-turn wiki RAG (`rag.get_context`),
   any deeper memory-recall hits, and the conversation history + current user message.

Use the Python SDK streaming helper so the `on_delta`/`stop_event` contract is preserved:

```python
import anthropic
client = anthropic.Anthropic()  # resolves ANTHROPIC_API_KEY or ant-auth profile

def stream_and_collect(system_blocks, messages, on_delta=None, stop_event=None,
                       model="claude-haiku-4-5"):
    parts = []
    with client.messages.stream(
        model=model,
        max_tokens=1024,               # spoken replies are short; keep low
        system=system_blocks,          # list[dict]; last stable block carries cache_control
        messages=messages,             # history + current turn (uncached tail)
    ) as stream:
        for text in stream.text_stream:
            if stop_event is not None and stop_event.is_set():
                break                  # barge-in: keep what was said, stop generating
            parts.append(text)
            if on_delta:
                on_delta(text)
        final = stream.get_final_message()
    # log final.usage.cache_read_input_tokens to confirm caching is live
    return "".join(parts), final
```

Cached-prefix `system` shape:

```python
system_blocks = [
    {"type": "text", "text": STATIC_PERSONA_AND_MEMORY},         # stable, ~900 tok today
    {"type": "text", "text": pinned_and_daily_memory},           # stable within a session
    # NOTE: leave cache_control OFF until count_tokens(system_blocks) >= 4096 (see note above).
    # When it clears the threshold, add "cache_control": {"type": "ephemeral"} to the LAST
    # stable block and verify response.usage.cache_read_input_tokens > 0.
]
```

Cost sanity check (verified against current pricing): Haiku 4.5 = $1/$5 per MTok. At the
current ~1,200-token prefix, **uncached**, ~100 turns/day ≈ **$3–4/month** — caching off is
fine (see the measured note above). If/when the prefix clears 4,096 tokens and caching is
switched on, cached reads drop that portion to $0.10/MTok; the 5-min TTL is fine for
in-session back-and-forth (a >5-min gap just re-writes on the next turn).

### 2d. Cost guardrails (belt-and-suspenders)
- Keep the existing `MAX_HISTORY_MESSAGES` trim (currently 20) so the uncached tail stays bounded.
- `max_tokens=1024` for spoken turns (they're short).
- Optional: a soft daily-spend counter logged to stderr so AJ sees drift early.

---

## 3. Memory: SQLite buffer + persistent dated Markdown in the Obsidian vault

The current `memory.py` is SQLite-only and never touches the vault. Phase 1 adds a
**dual-write** design; keep `memory.py`'s SQLite as-is (it's the fast path) and add a new
module for durable memory.

### 3a. Roles
- **SQLite (`memory.py`, unchanged):** ephemeral rolling buffer of raw turns for the *active*
  session — fast O(1) assembly of the Claude prompt. Not the long-term store.
- **Obsidian dated Markdown (new):** durable, human-readable/editable long-term memory,
  **inside AJ's real vault**.

### 3b. Location & format (per-DAY, one file)
- **CONFIRMED vault path (2026-07-21):** the live Obsidian vault root on this machine is
  **`E:\Obsidian Vault\Alt3red`** (the folder containing `.obsidian/` — ignore the brief's mac
  path and the old `wikibrain` path in project memory). Jarvis's memory folder is therefore
  **`E:\Obsidian Vault\Alt3red\_Jarvis_Memory\`** — the leading underscore keeps it sorted out
  of the way and clearly Jarvis-owned. Also point `rag.py`'s vault root at
  `E:\Obsidian Vault\Alt3red` so wiki grounding reads the same vault.
- One file per **day**, not per session (per-session fragments the graph and hurts search):
  `_Jarvis_Memory/2026-07-21.md`. Sessions within a day are `### Session HH:MM` headers.
- YAML frontmatter for programmatic query:

```markdown
---
date: 2026-07-21
tags: [jarvis/daily-log]
summary: "one-line day summary"
---
### Session 14:32
- <salient fact / decision / preference>
```

### 3c. Write path (salience, not raw transcript)
Do **not** dump raw turns to the vault (filler/STT errors pollute a knowledge base). On
session end — a ~15-min silence timeout **or** an explicit exit — take the SQLite session
log and summarize it into clean bullets (facts, decisions, preferences, action items) with a
cheap Haiku call, then append under a `### Session HH:MM` header in today's file. This
summarize call can use the **Batch API** (50% off) since it's not latency-sensitive; a plain
Haiku call is also fine. Follow the brief's "write-narrow" rule: only ever append to the
Jarvis memory folder — never edit/restructure AJ's other vault files.

### 3d. Read path (tiered, keyword-only for Phase 1)
- **Tier 1 (always):** read today's file + yesterday's `summary` frontmatter into the
  **cached** system prefix (§2c).
- **Tier 2 (on demand):** for questions needing older context, keyword-search across
  `_Jarvis_Memory/*.md` — **reuse the existing `rag.py` keyword + wikilink approach**, don't
  add a vector DB. Append top hits to the **uncached** tail.
- **Defer embeddings/OpenVINO to a later phase.** Keyword retrieval avoids the Intel-GPU
  embedding stack entirely for now and is plenty for a single user's daily logs.

---

## 4. Explicitly unchanged in Phase 1
- `voice_loop.py` — barge-in (soft/hard), wake word, grace window, HUD state feed. Untouched
  except that it now calls the new Claude-backed `chat.run_turn` (same signature).
- `tools/tts.py` — **keep ElevenLabs** (`eleven_flash_v2_5`). Local Kokoro is a later phase.
- `stt.py` — faster-whisper base on CPU. Unchanged.
- `hud.html` / `hud_server.py` — the state visualizer stays; the live-transcript rework is a
  later phase.

---

## 5. Build order within Phase 1
1. Prereqs are confirmed (API key §0, vault path §3b) — no blockers; proceed. `pip install
   anthropic` into the environment; point `rag.py` at `E:\Obsidian Vault\Alt3red`.
2. Swap `brain_ollama.py` → Anthropic SDK; keep `stream_and_collect`'s contract (§2a, §2c).
   Add the deterministic router + Haiku/Sonnet-5 escalation (§2b).
3. Restructure `chat.py`'s `_build_system_message` into cached-prefix + uncached-tail (§2c).
   Verify caching with `usage.cache_read_input_tokens` on turn 2+.
4. Add the vault-memory module: dated-file writer + session-end summarizer (§3b, §3c) and
   Tier-1/Tier-2 read path (§3d). Keep SQLite as the live buffer.
5. Smoke test the full loop: wake word → Haiku reply (cached) → interrupt → memory written
   to today's file on exit → new session reads it back.

## 6. Acceptance checks
- [ ] Prompt is assembled stable-prefix-first (cache-ready structure), `cache_control` left
      OFF while the prefix is < 4,096 tokens (measured ~1,200 today). No filler padding.
- [ ] A trivial "what time is it" makes **no** API call (local route).
- [ ] A hard/explicit turn escalates to `claude-sonnet-5`; everything else stays on Haiku.
- [ ] On exit, a `### Session HH:MM` block with salient bullets appears in
      `_Jarvis_Memory/<today>.md`; no other vault file is modified.
- [ ] A follow-up question about something said yesterday is answered from Tier-1/Tier-2 recall.
- [ ] Barge-in still cuts TTS within ~tens of ms and the partial reply is saved (unchanged behavior).
- [ ] GPU headroom: with the local qwen3 brain gone, VRAM use during a conversation is
      dominated by STT/TTS only — confirm AJ's other work isn't starved.
