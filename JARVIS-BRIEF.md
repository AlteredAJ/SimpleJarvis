# Jarvis — Project Brief (read this first)

**You are a fresh session with no memory of prior conversations. This file is your
entire briefing. Read it fully — and read the existing code in this repo (section 2)
— before writing any code.**

---

## 0. What Jarvis is, in one paragraph

Jarvis is AJ's personal conversational AI — the "brain" project. It's being adapted
from an existing prototype (see section 2) into something different: a daily
assistant that talks naturally and is grounded in AJ's real personal context (his
Obsidian vault/wiki), running on local infrastructure with no cloud LLM subscription
required per query. This is being built BEFORE Pickup (a separate commercial product,
see section 4) on purpose — Jarvis is where we prove out natural conversation +
context-grounding on a forgiving, low-stakes target (talking to AJ) before that same
engine gets trusted in front of a paying customer. Once Jarvis's conversational
engine and context-retrieval pattern work well, they get adapted again into Pickup's
Demo Diner build — a separate codebase, different persona, different data.

---

## 1. Hard constraints (read twice — violating these breaks trust in the whole system)

1. **No Claude API access.** AJ has a Claude subscription (claude.ai / Claude Code),
   which is OAuth-based — there is no Anthropic API key for programmatic use. Jarvis's
   runtime brain must be a **local LLM run via Ollama.** The existing code in this
   repo calls the Anthropic API directly (`agent.py`) — that call must be replaced,
   not kept as a fallback. (AJ can still separately use Claude Code as a development
   tool to help build Jarvis — that's a different thing from Jarvis calling Claude
   at runtime.)
2. **The Obsidian vault is sacred — read-heavy, write-narrow.** AJ's whole life runs
   through an Obsidian vault synced via Obsidian Sync (see section 3). Jarvis should
   use it as **context**: pull relevant pages into the conversation, reason over
   them, reference them. Jarvis must **NOT** reorganize, rename, restructure, delete,
   or bulk-edit wiki files. Any write access it's given must be narrow and explicit,
   following the safe pattern described in section 3. When in doubt, read-only.
3. **This has to actually run on whatever hardware you're on** — confirm CPU/RAM/GPU
   before picking model sizes (see section 5).
4. **Never commit or transmit `.env`.** It's already gitignored in this repo, and it
   currently holds real credentials (Anthropic, ElevenLabs, Twilio, Google) from the
   prior prototype. Some of these (ElevenLabs, Twilio, Google Calendar) may still be
   reusable for the parts of the old code you're keeping — check with AJ before
   assuming a key is stale or before deleting it.

---

## 2. What already exists in this repo — READ THE CODE, this is not a clean start

An earlier build lives here (dated late June–mid July 2026), and it's actually a
prototype of a **business AI front-desk phone bot** — closer to Pickup's Demo Diner
than to the "personal Obsidian brain" concept described below. You are adapting this,
not starting from zero:

| File | What it does now | What happens to it |
|---|---|---|
| `main.py` | FastAPI app; Twilio inbound-call webhooks (`/voice/inbound`, `/voice/respond`), an admin dashboard showing bookings, health check | Telephony (Twilio) is **not needed for Jarvis** — that's a Pickup-specific channel. Either strip it down to a simple chat/voice loop for talking directly to AJ, or keep it behind a flag and add a non-telephony entry point alongside it. Don't delete outright without checking with AJ — the admin dashboard pattern may be worth keeping for a "recent conversations" view. |
| `agent.py` | Builds a system prompt from a YAML business config, calls **Claude API directly** (`anthropic.Anthropic`) with 4 tools (check availability, book appointment, send SMS, request human callback), runs an agentic tool-use loop | **The Claude API call must be replaced with a local Ollama call.** Ollama supports tool-calling for capable models (check current model support — this may have matured further by the time you're reading this). Keep the agentic loop *structure* (dispatch tool → feed result back → loop until done) — it's sound — just swap the model client. |
| `memory.py` | SQLite: sessions, per-call message history, bookings log | Directly reusable. This is exactly the multi-turn conversation memory Jarvis needs; `call_sid` just becomes a generic session/conversation id, no longer literally a Twilio call. |
| `tools/calendar.py` | Google Calendar OAuth, check availability, book appointment | Not core to Jarvis's first milestone (section 6), but it's AJ's own calendar integration and may become genuinely useful later ("what's on my calendar today," "book me a reminder"). Keep it, don't wire it in yet. |
| `tools/sms.py` | Twilio SMS send | Same as calendar — not core, potentially useful later (Jarvis texting AJ a reminder), not a day-one priority. |
| `tools/tts.py` | ElevenLabs TTS (`speak()`, plus `clone_voice()` for one-shot voice cloning) | ElevenLabs works today and is a legitimate fallback (see section 4), but **try a local TTS first** per section 4 — Kokoro-82M. Keep this file as the ElevenLabs path if/when you need the fallback; add a new local-TTS module alongside it rather than deleting this. |
| `tools/config.py` | Loads a YAML business config (`config/demo.yaml` — currently "AJ's Cuts" barbershop demo data) | This whole config shape (business name, hours, services, staff) is Pickup's shape, not Jarvis's. Jarvis's "config" is really AJ's Obsidian vault (section 3), not a YAML file. Don't extend this file for Jarvis — build a separate context-retrieval module instead (section 3). |
| `config/demo.yaml`, `config/template.yaml` | Fake barbershop demo data | **This is Pickup content that ended up in the Jarvis folder.** Leave it here for now (low cost), but it is not Jarvis's config and shouldn't be treated as such. Flag to AJ that this may want to move to `~/Projects/pickup-demo/` eventually to keep the two projects' data separate. |
| `generate_pitch_pdf.py`, `fonts/` | A pitch-deck PDF generator with custom fonts | Business/sales tooling, unrelated to Jarvis's conversational core. Ignore for now. |
| `requirements.txt` | `anthropic`, `elevenlabs`, `twilio`, `google-api-python-client`, `fastapi`, etc. | Drop `anthropic` (no API key available). Add `ollama` (or just call its local HTTP API directly, no special package needed) and whatever local TTS/STT libraries section 4/5 lead you to. Keep `elevenlabs` for the fallback path, `google-api-python-client`/`twilio` for the calendar/SMS tools you're keeping dormant. |

**Bottom line:** the *shape* of this code (FastAPI + an agent loop with tool-calling +
SQLite conversation memory) is a fine skeleton for Jarvis. What has to change is (a)
the brain — Claude API → local Ollama, and (b) the context source — a fake business
YAML → AJ's real Obsidian vault. The telephony/booking/SMS machinery is Pickup-shaped
and should sit dormant, not be deleted, in case it's useful again later or needs to
move to the Pickup repo.

---

## 3. Context source: the Obsidian vault

- AJ's "second brain" is an Obsidian vault, normally at `/Users/ajapaukese/Claude` on
  his main machine, kept in sync across devices via **Obsidian Sync** (a paid Obsidian
  service — not iCloud/Dropbox). **On this new machine, Obsidian Sync needs to be set
  up and pointed at the same vault before Jarvis has anything to read.** If that
  hasn't happened yet, that's the actual first task — ask AJ to confirm Obsidian Sync
  is connected here and tell you the local vault path before building the RAG layer.
- Structure once synced: `wiki/` (synthesized knowledge pages, the main context
  source), `raw/` (immutable source dumps — don't read these for context, they're
  unprocessed), `graphify-out/` (an existing knowledge-graph tool's output — a JSON
  graph + generated Obsidian notes, may be useful for link-aware retrieval).
- **There's already a working, safe pattern for this exact problem** in a sibling
  project called **Local Brain** (`~/Claude/local-brain/`, a local dashboard + chat
  that already does wiki-grounded conversation). A reference copy of its write-up is
  in `context/Local Brain.md` next to this file. Patterns worth reusing:
  - **Keyword RAG + link-following:** rank wiki pages by keyword overlap with the
    query, then follow `[[wikilink]]` references to pull in linked neighbor pages —
    uses the vault's own link structure instead of a vector DB.
  - **Pinned context:** the user can explicitly pin specific pages/notes into every
    future conversation turn (a "primary context" layer above the automatic RAG).
  - **Narrow, explicit writes only:** the one place Local Brain writes back to the
    wiki is a checkbox/checklist sync (toggling a `- [ ]` to `- [x]` on the exact
    line it read it from) — never a rewrite of a whole file, never a restructure.
    If Jarvis needs any write capability (e.g., "journal this"), follow this same
    narrow pattern: one known action, one known line, nothing freeform.

---

## 4. Voice / personality

AJ wants Jarvis to feel human and lively, not robotic — this matters as much as the
correctness of its answers.

- **Miso TTS was the first choice** (misolabs.ai, open source, 110ms latency,
  one-shot voice cloning from a 10s clip) but is **shelved** — it needs 24GB+ VRAM
  and doesn't run on AJ's known hardware. Revisit only if AJ gets GPU access later.
- **ElevenLabs already works in this repo** (`tools/tts.py`, real API key present in
  `.env`) — keep it as the fallback if local TTS quality doesn't clear the bar. It
  costs money per character generated, so it shouldn't be the default if a local
  option is good enough.
- **Prefer a local option first.** A parallel project (Pickup's demo build)
  independently researched this exact problem in July 2026 and landed on
  **Kokoro-82M** — a free, Apache-2.0, 82M-parameter local TTS model, CPU-viable (no
  GPU required), sub-200ms time-to-first-audio, quality reported to rival ElevenLabs
  for a fraction of the resource cost. Full research writeup is referenced in
  `context/PICKUP-DEMO-DESIGN-reference.md`. **Try Kokoro-82M first**, fall back to
  the existing ElevenLabs path only if quality doesn't hold up after tuning.
- Give Jarvis a consistent name/persona and a natural, warm conversational style —
  short replies when spoken, not paragraphs.

---

## 5. LLM / brain

- **Must be local, via Ollama** (no Claude API key available — see constraint #1).
  This directly replaces the `anthropic.Anthropic(...)` call in `agent.py`.
- The same July-2026 research pass (done for Pickup) found **Qwen3 8B** the strongest
  7-9B-class local model for reliability when structured tool-calling matters (vs.
  Llama 3.1 8B). That's a reasonable default to try for Jarvis's brain too, but
  Jarvis's job (open-ended conversation + retrieval-grounded Q&A) is a different
  shape than Pickup's job (narrow tool-calling) — a stronger general-conversation
  model may serve Jarvis better even at slightly worse structured-output reliability.
  Worth a quick side-by-side before committing.
- **Confirm the actual hardware this runs on** before finalizing model size/quant —
  don't assume it matches AJ's other machine. Ask if unclear.

---

## 6. Suggested first milestone (thin vertical slice)

Don't try to build the full second-brain experience on day one. Aim for:

1. Ollama running locally with a chosen model, replacing the Claude API call in
   `agent.py`, still responding sensibly to a basic system prompt (keep the existing
   agentic tool-use loop shape even if the tool list changes).
2. A minimal text (not voice yet) chat loop — reusing `memory.py` as-is for
   conversation history — that does keyword RAG against a small set of real wiki
   pages (once Obsidian Sync is confirmed working here) and answers a real question
   correctly and honestly (refuses to guess on things not in context).
3. Add TTS (try Kokoro-82M first, `tools/tts.py`'s ElevenLabs path as fallback) so a
   reply can be spoken aloud.
4. Add STT (mic input) to close the loop into a real voice conversation.
5. Only after that loop feels good: pinned-context, multi-turn memory polish, any
   write-back capability (narrow, per section 3), and personality/voice tuning.
   Calendar/SMS tools (`tools/calendar.py`, `tools/sms.py`) stay dormant until AJ
   actually wants Jarvis to manage his calendar or send him texts — not a day-one need.

---

## 7. What to ask AJ before writing code, if anything here is ambiguous

- Is Obsidian Sync set up on this machine yet, and what's the local vault path?
- What's the actual hardware spec of this machine (CPU, RAM, GPU/no GPU)?
- Does he want a text-first MVP or is voice-from-day-one a hard requirement?
- Should `config/demo.yaml` and the barbershop-shaped config system move to the
  Pickup repo, or stay here dormant?
- Are the ElevenLabs/Twilio/Google credentials already in `.env` still valid and
  meant to be reused, or should fresh ones be issued?

---

*This brief was packaged 2026-07-19 from a planning session on AJ's other machine,
then corrected the same day after discovering this repo already had a real prototype
(an earlier Pickup-shaped front-desk bot) rather than being empty. Companion
reference copies of relevant wiki pages are in `context/` next to this file — treat
them as point-in-time snapshots, not live data; the real vault (once synced here) is
the source of truth.*
