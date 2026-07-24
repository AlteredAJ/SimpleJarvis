# Jarvis — Phase 2 Build Plan: Live Transcript + UI Rework

**Revised 2026-07-23** — dashboard panels + DeepSeek brain added since original write.
See §3.5 (new meta events) and §6 (updated layout).

**Prereq: Phase 1 landed (Claude brain + vault memory).** Read `PHASE1-BUILD-PLAN.md` and
`JARVIS-BRIEF.md` first. This phase reworks the surface only — the brain, memory, voice
loop, and barge-in logic are untouched.

---

## 1. Goal (definition of done)

The HUD gains a **live, dual-sided, streaming transcript** beside the existing state
visualizer, with **interruption-aware rendering**. Specifically:
- Text appears **token-by-token as it's generated/spoken** (like watching a Claude reply
  build), not dumped at the end.
- Both sides are clearly separated: AJ's transcribed speech and Jarvis's replies.
- When AJ barges in, the transcript **preserves the original line AND marks exactly where it
  was cut off** — the specific pain point AJ called out.
- The existing radial-waveform visualizer (idle/listening/thinking/speaking/aside/interrupted)
  keeps running alongside it as one coherent interface.

---

## 2. What exists today (don't rebuild it)
- `hud_server.py` — stdlib `ThreadingHTTPServer`. Two channels:
  - `GET /state` polling (~60ms) for waveform `level` + state/color + **dashboard metadata**
    (`model`, `wiki_pages`, `memory_status`, `turn`, `latency_ms`). Already wired from
    `chat.py`'s `run_turn` and supports `set_state(state, label, **meta)`.
  - No SSE yet — this phase adds `GET /events`.
- `hud.html` — `<canvas>` radial waveform (cinematic: filled bezier wave, dual-layer bars,
  6 orbiting particles, hex core, holographic scanlines) + 4 CSS-positioned **dashboard
  readout panels** (brain/wiki/memory/turn) overlaid on the canvas + `#status` + `#subinfo`
  label. **No transcript panel yet.**
- `voice_loop.py` already produces everything a transcript needs: streaming STT partials
  (`Listener.partial_text`, also pushed to HUD `label`), `chat.run_turn`'s token-level
  `on_delta`, the soft/hard interrupt verdict, and the aside path. **Wire these into
  transcript events rather than inventing new plumbing.**

---

## 3. Transport: add SSE, keep it dependency-free (do NOT add flask/websockets)
The research report's recommendation — **Server-Sent Events over WebSockets** — is correct
here: the transcript is a unidirectional server→client push, and SSE needs no handshake/
reconnect state machine. **But don't pull in a framework.** SSE is a plain
`text/event-stream` HTTP response and can be served from the existing stdlib
`ThreadingHTTPServer` — matching `hud_server.py`'s explicit "no websockets/flask" design.

Two channels, both stdlib:
- **Keep `GET /state` polling** for the waveform `level` — it's high-frequency and lossy-OK
  (a dropped 50ms sample doesn't matter).
- **Add `GET /events` (SSE)** for the transcript, where every token matters. Handler holds
  the connection open and writes `data: {json}\n\n` per event; the browser uses the native
  `EventSource` API. Back it with a thread-safe queue (or a subscriber list) that
  `voice_loop.py` / `chat.py` publish to.

SSE handler sketch (stdlib, in `hud_server.py`):
```python
def do_GET(self):
    if self.path == "/events":
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        q = _subscribe()                       # per-connection queue
        try:
            while True:
                evt = q.get()                  # blocks; heartbeat every ~15s
                self.wfile.write(f"data: {json.dumps(evt)}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            _unsubscribe(q)
        return
```

### 3.5. Dashboard metadata via SSE (added 2026-07-23)

The dashboard readout panels (`model`, `wiki_pages`, `memory_status`, `turn`, `latency_ms`)
currently update via polling (`GET /state`). During a live turn, `chat.py` calls
`hud_server.set_state("thinking", ..., model=..., wiki_pages=..., turn=...)` and the HUD
picks it up on the next poll tick.

For Phase 2, keep polling for the waveform `level` (high-frequency, lossy-OK), but also
**broadcast metadata changes as SSE events** so the dashboard panels update instantly
alongside transcript streaming. Add a `meta` event type:

```python
hud_server.publish({"type": "meta", "model": "deepseek-chat", "wiki_pages": ["Now", "Investing"], "turn": 3, "memory_status": "active"})
```

The HUD's dashboard `updateDashboard()` switches from polling `current` to consuming the
last-seen meta event — zero-lag dashboard updates during turns.

## 4. Event model (publish these from the voice loop)

Add `hud_server.publish(event)` and emit a small, typed set. Map them onto the moments
that already exist in `voice_loop.py` / `chat.run_turn`:

| Event | Emit when | Payload |
|---|---|---|
| `turn_start` | new user turn begins (before thinking) | `{turn: N}` — clears prior bubbles, sets turn boundary |
| `meta` | dashboard metadata changes (brain/wiki/memory/turn/latency) | `{model, wiki_pages, memory_status, turn, latency_ms}` |
| `user_partial` | `Listener` streaming re-transcribe fires | `{text}` (replaces current partial) |
| `user_final` | endpoint reached, final STT text | `{text}` |
| `assistant_delta` | each `on_delta` chunk from `chat.run_turn` | `{text}` (append) |
| `assistant_final` | reply completes normally | `{text}` (full), also emits meta update |
| `interrupted` | hard-cancel verdict fires | `{at_char}` — index in the current assistant line where TTS was cut |
| `aside_start` / `aside_delta` / `aside_final` | soft-interrupt aside path (`run_quick_aside`) | `{text}` |

`at_char` for the interruption marker: the transcript already knows how much was **spoken**
vs generated — `voice_loop.speak_reply_with_interrupts` flushes sentence-by-sentence and
`Speaker.play_pcm` stops mid-sub-chunk on interrupt. Track cumulative characters actually
handed to `play_pcm` before the cut; that's the cut point.

**Where to track spoken characters** (implementation note, 2026-07-23):
In `speak_reply_with_interrupts`, `flush_sentence(sentence)` calls `_synthesize_pcm` then
`speaker.play_pcm(pcm)`. Add a `spoken_chars` counter that increments by `len(sentence)`
BEFORE `play_pcm` — so if `play_pcm` returns `False` (interrupted), `spoken_chars` already
holds the count of characters that made it to audio. Pass this value in the `interrupted`
event payload as `at_char`. On hard cancel, also emit `assistant_final` with the full
generated text so the transcript can render the dimmed remainder after the cut point.

## 5. Interruption rendering (the specific ask)
On an `interrupted` event, the frontend keeps the assistant line and marks the boundary —
the industry pattern (LiveKit/Pipecat/OpenAI Realtime, per the report): render the spoken
prefix normally, then **grey/dim the un-spoken remainder** and append an explicit
**`— [interrupted]`** marker. Example target rendering:

```
You:     what's the status of the local server
Jarvis:  the primary server is running fine, but the backup is experien— [interrupted]
You:     actually just tell me about the backup
```

Optional refinement: keep the full generated text available on hover (so AJ can see what it
*was* going to say), but the default view is spoken-prefix + dimmed-cut. Distinguish
**hard** interrupts (cut marker, new user turn) from **soft asides** (the aside renders as
its own indented sub-line, primary reply resumes — don't mark the primary as interrupted).

## 6. Frontend (keep it vanilla)
- Stay with vanilla JS + the existing `<canvas>` loop in `hud.html` — no React/Preact.
- **Layout (updated 2026-07-23):** the existing HUD has a centered waveform canvas (420px)
  with 4 dashboard readout panels overlaid at corners. Phase 2 adds a **transcript panel**
  below the waveform/readouts — a scrolling `<div id="transcript">` populated from
  `EventSource('/events')`. The visualizer + dashboard keep running at full 60fps via
  `requestAnimationFrame`; the transcript runs independently via SSE.
- Streaming append: on `assistant_delta`, append to the current assistant bubble's text
  node (no full re-render). Auto-scroll to bottom unless the user has scrolled up.
- Reuse the existing per-state CSS colors (`--listening`, `--speaking`, `--interrupted`,
  `--aside`) so the transcript and the waveform read as one system.
- On `meta` events, update the dashboard panels instantly (bypass the polling refresh).

## 7. Acceptance checks
- [ ] Assistant text streams into the transcript token-by-token, matching TTS timing.
- [ ] AJ's speech shows as a live partial (STT streaming), then finalizes on endpoint.
- [ ] A hard barge-in leaves the original assistant line visible with a clear cut marker at
      the right word; the new user turn appears below.
- [ ] A soft aside renders as its own indented sub-line and the primary reply resumes without
      a cut marker.
- [ ] Dashboard panels update via SSE `meta` events — zero lag during turns.
- [ ] The waveform visualizer is unaffected (still 60fps, still audio-reactive).
- [ ] No new pip dependency added (`http.server` SSE, native `EventSource`).
