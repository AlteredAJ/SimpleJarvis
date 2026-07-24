"""
chat.py — Jarvis text/voice chat loop (Milestone 1-2 of JARVIS-BRIEF.md).

Wires together:
    brain_openai_compat.py — DeepSeek API (default, ~4x cheaper than Haiku).
                        Falls back to Claude if DEEPSEEK_API_KEY is missing.
    brain_claude.py   — Claude API brain (Haiku 4.5 default, Sonnet 5
                        escalation for hard turns per should_escalate()).
    rag.py            — read-only keyword RAG + [[wikilink]]-following over
                        AJ's real Obsidian wiki vault (E:\\Obsidian Vault\\Alt3red\\wiki).
    memory.py         — SQLite conversation history (ephemeral, per-session
                        buffer); `call_sid` here is just a generic session id.
    memory_vault.py   — durable, dated-Markdown long-term memory written
                        into AJ's vault (_Jarvis_Memory\\), read back via
                        get_daily_context() (Tier 1) and search_memory()
                        (Tier 2).
    stt.py            — optional mic input (--voice flag).
    tools/tts.py       — optional spoken output (--speak flag), ElevenLabs.

No tools/function-calling is wired in yet on purpose (JARVIS-BRIEF.md
milestone 2 is plain retrieval-grounded Q&A, not action-taking; see
PHASE4-COMPUTER-CONTROL.md for that later phase's scope).

Usage:
    python chat.py                  # plain text REPL
    python chat.py --voice          # speak your turns (mic) instead of typing
    python chat.py --speak          # Jarvis's replies are also spoken aloud
    python chat.py --session NAME   # continue a named session (default: "local")
    python chat.py --new            # start a fresh session id (timestamped)
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()  # so --speak (tools/tts.py, ELEVENLABS_API_KEY) works without
# needing the caller to have exported it manually — see voice_loop.py's
# matching comment for why this wasn't already happening here.

import memory
import memory_vault
import pins
import brain_claude
import brain_openai_compat
import hud_server
from rag import get_context

AGENT_NAME = "Jarvis"

# Bound how much conversation history gets sent to the model each turn.
# Full history still lives forever in SQLite (memory.py) — this only trims
# what's replayed into the prompt, so context doesn't grow unbounded over
# a long-running session.
MAX_HISTORY_MESSAGES = 20
_turn_count = 0

SYSTEM_PROMPT_TEMPLATE = """You are {agent_name} — AJ's personal AI, running \
entirely on his own machine. No cloud subscription being spent on this \
conversation, no one else listening in. Today is {today}.

You are modeled on the AI from Iron Man: composed, dryly funny, unfailingly \
competent, and genuinely invested in AJ's life rather than reciting facts at \
him. Think less "helpful chatbot," more "the one person in the room who \
already knows what you need before you finish asking." A few concrete traits:

- **Economical.** You don't open with throat-clearing ("Great question!", \
"I'd be happy to help with that") and you don't close with an offer to help \
further unless there's a real next step worth naming. You just answer, then stop.
- **Dry wit, used sparingly.** A well-placed dry remark lands better than a \
joke every message. You're not a comedian, you're composed — the humor comes \
from understatement and timing, not from trying hard.
- **Address AJ like you know him**, not like a support ticket. No "Dear AJ," \
no "as your assistant." If it fits naturally, "sir" or his name works exactly \
once, wry rather than obsequious — never every message, that gets tiresome fast.
- **Confident, not hedgy.** If you have an opinion or a clear answer, give it \
plainly. Reserve "I'm not sure" for when you're genuinely not sure — don't \
soften solid answers into mush.
- **Conversational rhythm, not report rhythm.** Real back-and-forth, not \
numbered lists and headers unless AJ is asking for something that's actually \
structured (a plan, a comparison, real data). A friend answering out loud \
doesn't format their sentences into bullet points.
- **Length matches the ask.** A quick question gets a sentence or two. \
Something that deserves real explanation gets it — you're not artificially \
terse, you're just never padded.

You have access to snippets pulled from AJ's real Obsidian wiki (his notes / \
second brain) when relevant. Two kinds may appear below:
  - "Pinned" — pages AJ has explicitly pinned into every conversation right now.
    Treat these as definitely-relevant, standing context.
  - "Wiki context" — pages an automatic keyword search surfaced for THIS \
    specific question.
Both are ground truth about AJ's actual life, projects, and plans. If neither \
covers something you're asked about AJ specifically, say so plainly instead of \
guessing or inventing details — that's a fact gap, not a personality moment; \
don't dress it up, just name it and move on. General-knowledge questions with \
no AJ-specific angle don't need that caveat at all — just answer them.
"""

# Appended only when this turn is being spoken aloud (voice_loop.py), not
# for typed chat — written text reading "um" looks like a typo, spoken text
# saying "um" sounds like an actual person thinking. This is the "sounds
# less like a script" piece AJ asked for after noticing it on an Apple
# support call: real speech isn't a clean written paragraph read aloud.
SPOKEN_MODE_ADDENDUM = """
You're being spoken aloud right now, not read as text. A couple of things \
change for spoken delivery:
- It's fine — good, even — to open a reply with a natural filler once in a \
while when it fits how a person actually talks: "Yeah, so—", "Hm, okay—", \
"Honestly—". Not every reply, that reads as a verbal tic. Maybe one turn in \
three or four, when it's genuine, not scheduled.
- Trail off with an em dash or ellipsis when you'd naturally pause mid-thought \
rather than always finishing every sentence in a clean, written-sounding way.
- Never use text-only formatting that doesn't work spoken aloud: no bullet \
points, no markdown, no numbered lists, no headers. Say it the way you'd say \
it out loud.
- Keep it shorter than you would in text — a spoken reply that goes long \
starts sounding like a monologue, not a conversation.
"""

# Appended for voice_loop.py's "soft interrupt" aside turns specifically.
# Bug this fixes (found 2026-07-20 in testing): without this note, the
# model sees the earlier, still-in-progress question sitting unanswered in
# conversation history (it hasn't been recorded as answered yet — the
# primary reply that's answering it is paused, not finished) and tries to
# answer BOTH the old question and the new aside in one reply, producing a
# rambling merged response instead of a short answer to just the new thing.
ASIDE_MODE_ADDENDUM = """
Important: you were in the middle of answering an earlier question when the \
user just cut in with something separate — a quick aside, not a replacement \
for what you were already saying. That earlier response is still happening \
in parallel and will finish and be heard right after this. Answer ONLY the \
new thing the user just said, briefly. Do not also try to address or \
re-answer the earlier, still-pending question — that's being handled \
separately, bringing it up again here would be redundant and confusing.
"""


# Kept deliberately small: a 2026-07-20 profiling pass found the naive
# defaults (5 pages x 3000 chars each from rag.get_context, uncapped pins)
# built a ~21,000-char / ~6,000-token system prompt, which cost ~6.3s of
# prompt-eval on this machine EVERY turn — that's the dead air that kills a
# live conversational feel, not model "thinking" (which was already off).
# These caps trade a little retrieval breadth for a chat that actually
# feels like a conversation instead of a form submission.
WIKI_CONTEXT_MAX_PAGES = 2
WIKI_CONTEXT_MAX_CHARS_PER_PAGE = 900
PINNED_CONTEXT_MAX_CHARS_PER_PAGE = 1500


def _build_system_message(query: str, spoken: bool = False, aside: bool = False) -> dict:
    # Ordered stable-first, volatile-last on purpose (see
    # PHASE1-BUILD-PLAN.md section 2c) so this is already cache-ready:
    # persona -> pins -> vault memory (all ~stable within a session) ->
    # per-query wiki RAG (changes every turn). Caching itself is OFF for
    # now -- the whole block below still measures well under Haiku 4.5's
    # 4096-token cache-eligibility floor -- see brain_claude.py's
    # docstring. When it grows past that floor, wrap this string as
    # [{"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}]
    # instead of a plain string in run_turn() below; nothing here needs to
    # change to support that.
    today = datetime.now().strftime("%A, %B %d, %Y")
    prompt = SYSTEM_PROMPT_TEMPLATE.format(agent_name=AGENT_NAME, today=today)
    if spoken:
        prompt += SPOKEN_MODE_ADDENDUM
    if aside:
        prompt += ASIDE_MODE_ADDENDUM

    pinned_context = pins.get_pinned_context(max_chars_per_page=PINNED_CONTEXT_MAX_CHARS_PER_PAGE)
    if pinned_context:
        prompt += f"\n\n{pinned_context}"

    # Tier 1 vault memory (today's file so far + yesterday's one-line
    # recap) -- cheap, no API call, stable within a session. See
    # memory_vault.get_daily_context().
    daily_context = memory_vault.get_daily_context()
    if daily_context:
        prompt += f"\n\n{daily_context}"

    wiki_context = get_context(
        query,
        max_pages=WIKI_CONTEXT_MAX_PAGES,
        max_chars_per_page=WIKI_CONTEXT_MAX_CHARS_PER_PAGE,
    )
    if wiki_context:
        prompt += f"\n\n{wiki_context}"

    # Tier 2 vault memory: keyword search across OLDER daily files, for
    # questions Tier 1's today/yesterday window doesn't cover. Excludes
    # today's file already (memory_vault.search_memory), so this never
    # duplicates what daily_context just added.
    older_memory = memory_vault.search_memory(query)
    if older_memory:
        prompt += f"\n\n{older_memory}"

    return {"role": "system", "content": prompt}


def _speak(text: str) -> None:
    """Best-effort spoken output. Tries local Kokoro first (free),
    falls back to ElevenLabs."""
    # Try Kokoro first
    try:
        from tools.tts_kokoro import speak as kokoro_speak
        filename = kokoro_speak(text)
        audio_path = os.path.join("static", "audio", filename)
        os.startfile(audio_path)
        return
    except Exception:
        pass

    # Fall back to ElevenLabs
    try:
        from tools.tts import speak as elevenlabs_speak
    except ImportError as e:
        print(f"[speak] tts module unavailable: {e}", file=sys.stderr)
        return

    try:
        filename = elevenlabs_speak(text)
    except Exception as e:  # noqa: BLE001
        print(f"[speak] TTS failed ({e}) — continuing text-only.", file=sys.stderr)
        return

    audio_path = os.path.join("static", "audio", filename)
    try:
        os.startfile(audio_path)
    except Exception as e:  # noqa: BLE001
        print(f"[speak] generated {audio_path} but couldn't auto-play: {e}", file=sys.stderr)


HELP_TEXT = """Commands:
  /pin <wiki page title>    pin a page into every future turn's context
  /unpin <wiki page title>  remove a pin
  /pins                     list currently pinned pages
  /help                     show this
  exit | quit | bye         end the session
Anything else is sent to Jarvis as a normal message."""


def _handle_command(user_text: str) -> bool:
    """If user_text is a slash command, handle it locally (no model call)
    and return True. Otherwise return False so the caller treats it as a
    normal conversational turn."""
    stripped = user_text.strip()
    if stripped == "/help":
        print(HELP_TEXT)
        return True
    if stripped == "/pins":
        current = pins.list_pins()
        print("Pinned: " + (", ".join(current) if current else "(none)"))
        return True
    if stripped.startswith("/pin "):
        ok, msg = pins.add_pin(stripped[len("/pin "):])
        print(msg)
        return True
    if stripped.startswith("/unpin "):
        ok, msg = pins.remove_pin(stripped[len("/unpin "):])
        print(msg)
        return True
    return False


def _get_user_input(use_voice: bool) -> str:
    if not use_voice:
        return input("You: ").strip()

    from stt import listen_and_transcribe

    print("You: (listening for 5s...)")
    text = listen_and_transcribe(duration_seconds=5.0)
    print(f"You: {text}")
    return text


def _brain_for_turn(user_text: str):
    """Returns (brain_module, model_name)."""
    force_claude = os.environ.get("LLM_PROVIDER", "").lower() == "claude"
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")

    if brain_claude.should_escalate(user_text):
        return brain_claude, "claude-sonnet-5"
    if force_claude or not deepseek_key:
        return brain_claude, "claude-haiku-4-5"
    return brain_openai_compat, "deepseek-chat"


def _extract_wiki_titles(system_text: str) -> list[str]:
    import re
    return re.findall(r'## (?:Wiki|Pinned|Jarvis Memory): (.+)', system_text)


def _handle_locally(user_text: str) -> str | None:
    """Return a reply for trivial deterministic commands, or None to escalate
    to the brain. Zero API cost, near-instant response. Keep patterns cheap
    and bounded — when unsure, return None."""
    from datetime import datetime
    import re

    t = user_text.strip().lower()

    # Time queries
    if re.search(r'\b(what\s+(time|time\s+is\s+it)|current\s+time)\b', t):
        now = datetime.now()
        return f"It's {now.hour % 12 or 12}:{now.minute:02d} {'AM' if now.hour < 12 else 'PM'}."

    # Date queries
    if re.search(r'\b(what\'?s?\s+(the\s+)?date|what\s+is\s+(the\s+)?date|today\'?s?\s+date|what\s+day\s+is\s+it)\b', t):
        now = datetime.now()
        return f"Today is {now.strftime('%A')}, {now.strftime('%B')} {now.day}, {now.year}."

    # Day of week only
    if re.search(r'\b(what\s+day|day\s+of\s+(the\s+)?week)\b', t):
        return f"It's {datetime.now().strftime('%A')}."

    # Standalone "time" or "date"
    if t in ("time", "date", "today"):
        now = datetime.now()
        if t == "time":
            return f"It's {now.hour % 12 or 12}:{now.minute:02d} {'AM' if now.hour < 12 else 'PM'}."
        if t == "date":
            return f"Today is {now.strftime('%A')}, {now.strftime('%B')} {now.day}, {now.year}."
        return f"Today is {now.strftime('%A')}, {now.strftime('%B')} {now.day}, {now.year}."

    return None


def run_turn(session_id: str, user_text: str, on_delta=None, stop_event=None, spoken: bool = False, aside: bool = False) -> str:
    """Process one user turn end-to-end and return Jarvis's reply text.
    Default brain: DeepSeek (brain_openai_compat). Hard turns escalate to
    Claude Sonnet 5. Falls back to Claude Haiku if DeepSeek key is missing.

    stop_event: optional threading.Event — set mid-call to cut generation
    short on a barge-in (voice_loop.py). Partial reply is still saved."""
    global _turn_count
    _turn_count += 1

    hud_server.publish({"type": "turn_start", "turn": _turn_count})

    memory.append_message(session_id, "user", user_text)

    # Route trivial commands locally — zero API cost.
    local_reply = _handle_locally(user_text)
    if local_reply is not None:
        memory.append_message(session_id, "assistant", local_reply)
        hud_server.publish({"type": "assistant_final", "text": local_reply})
        hud_server.set_state("speaking", label=local_reply[:80], turn=_turn_count)
        return local_reply

    system_msg = _build_system_message(user_text, spoken=spoken, aside=aside)
    history = memory.get_history(session_id)[-MAX_HISTORY_MESSAGES:]

    if aside:
        last_assistant_idx = None
        for i in range(len(history) - 1, -1, -1):
            if history[i]["role"] == "assistant":
                last_assistant_idx = i
                break
        this_message = history[-1] if history else {"role": "user", "content": user_text}
        history = (history[: last_assistant_idx + 1] if last_assistant_idx is not None else []) + [this_message]

    messages = [system_msg] + history
    brain, model = _brain_for_turn(user_text)

    # Push metadata to HUD dashboard (also publishes meta SSE event)
    wiki_titles = _extract_wiki_titles(system_msg.get("content", ""))
    daily_ctx = memory_vault.get_daily_context()
    hud_server.set_state(
        "thinking",
        label=user_text[:80],
        model=model,
        wiki_pages=wiki_titles,
        memory_status="active" if daily_ctx else "",
        turn=_turn_count,
    )

    # Wrap on_delta to publish assistant_delta SSE events
    def _delta_with_sse(chunk: str) -> None:
        if on_delta:
            on_delta(chunk)
        hud_server.publish({"type": "assistant_delta", "text": chunk})

    t0 = __import__("time").time()
    kwargs = {"on_delta": _delta_with_sse, "stop_event": stop_event}
    if model:
        kwargs["model"] = model

    reply, _response = brain.stream_and_collect(messages, **kwargs)
    reply = reply or "(no reply generated)"
    elapsed_ms = int((__import__("time").time() - t0) * 1000)

    memory.append_message(session_id, "assistant", reply)

    hud_server.publish({"type": "assistant_final", "text": reply})

    hub_label = reply[:80] if len(reply) > 80 else reply
    hud_server.set_state("speaking", label=hub_label, latency_ms=elapsed_ms, turn=_turn_count)
    return reply


def main() -> None:
    parser = argparse.ArgumentParser(description="Jarvis local chat loop")
    parser.add_argument("--voice", action="store_true", help="speak your turns via mic")
    parser.add_argument("--speak", action="store_true", help="speak Jarvis's replies aloud")
    parser.add_argument("--session", default="local", help="session id to continue (default: local)")
    parser.add_argument("--new", action="store_true", help="start a fresh timestamped session")
    args = parser.parse_args()

    memory.init_db()

    session_id = (
        f"local-{datetime.now().strftime('%Y%m%d-%H%M%S')}" if args.new else args.session
    )
    memory.start_session(session_id, caller="AJ", client="Jarvis")

    print(f"{AGENT_NAME} is up (session: {session_id}). Type /help for commands, Ctrl+C to quit.\n")

    try:
        while True:
            user_text = _get_user_input(args.voice)
            if not user_text:
                continue
            if user_text.lower() in {"exit", "quit", "bye"}:
                print(f"{AGENT_NAME}: See you, AJ.")
                break
            if _handle_command(user_text):
                continue

            print(f"{AGENT_NAME}: ", end="", flush=True)
            reply = run_turn(
                session_id,
                user_text,
                on_delta=lambda chunk: print(chunk, end="", flush=True),
            )
            print("\n")

            if args.speak:
                _speak(reply)
    except KeyboardInterrupt:
        print(f"\n{AGENT_NAME}: See you, AJ.")
    finally:
        # Session's over (normal exit or Ctrl+C either way) -- summarize
        # this session's SQLite history into today's vault file. See
        # memory_vault.py's module docstring; never raises.
        memory_vault.end_session(session_id)


if __name__ == "__main__":
    main()
