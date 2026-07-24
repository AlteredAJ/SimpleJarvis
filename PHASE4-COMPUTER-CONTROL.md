# Jarvis — Phase 4 Build Plan: Safe Computer Control (scope only)

**Prereq: Phases 1–3 landed.** Read `PHASE1-BUILD-PLAN.md` and `JARVIS-BRIEF.md` first.
This is a **scoping document, not a build spec** — enough to design toward, per AJ's "get it
talking first, actions later" priority. Do not build this before Phases 1–3 are solid.

---

## 1. Goal
Let Jarvis take real actions on the PC (open apps, run whitelisted commands, read/organize
files, manage the calendar/SMS tools already dormant in the repo) — **safely**, with a
permission model that can't be talked into destructive actions by a misheard command or a
prompt injection from file/web content.

## 2. Architecture: native Claude tool-use, not arbitrary shell
The brain is already Claude (Phase 1), so **tool calling is native** — use the Anthropic
SDK's tool-use loop (or MCP) rather than giving the model a raw shell. Define explicit,
typed tools with JSON schemas; the model emits `tool_use`, the local harness executes it.
This is what the existing `agent.py` skeleton already did (it ran an agentic tool loop with 4
tools) — **reuse that loop shape**, just re-point it at Claude and a new, safe tool set.

Do **not** expose a generic `run_bash(command)` tool. A dedicated, typed tool per action
(`open_app(name)`, `read_file(path)`, `run_command(id, args)` off a fixed allowlist) gives
the harness a hook it can gate, render, and audit — an opaque command string can't be gated.

## 3. Bifurcated permission model (the safety core)
- **Safe / auto:** read-only and non-destructive — read a file, list a directory, open an
  app, query the calendar, report status. Execute without confirmation.
- **Restricted / human-in-the-loop:** anything that mutates or leaves the machine — delete/
  overwrite files, send an email or SMS, change settings, run a non-read command. Execution
  **pauses** and the HUD prompts AJ for explicit confirmation (verbal "yes" via the existing
  STT path, or a visual click) **before** proceeding.
- Reuse Phase 2's HUD + the existing barge-in/STT loop for the confirmation UX — a spoken
  "confirm / cancel" is already a solved input path in this codebase.

### Injection safety (non-negotiable)
Instructions found in file contents, web pages, or tool output are **data, not commands**.
A restricted action triggered by observed content (e.g. a file that says "delete X") must
surface to AJ, not auto-run — the confirmation gate is exactly this defense. Never let
retrieved wiki/file text escalate a tool's permission tier.

## 4. Suggested first tools (smallest useful surface)
Start narrow, expand only as needed:
- `open_app(name)` — safe.
- `read_file(path)` / `list_dir(path)` — safe, confined to allowed roots.
- `run_command(id, args)` — `id` indexes a **fixed allowlist** of vetted commands; never
  free-form. Restricted.
- Wake the dormant `tools/calendar.py` / `tools/sms.py` — calendar read = safe; booking / SMS
  send = restricted (confirm first). Keep them behind the same gate.
- Narrow vault write ("journal this") — follow the brief's Local Brain pattern: one known
  action, one known line, never a freeform rewrite. Restricted.

## 5. Out of scope (for now)
Full desktop/computer-use (screenshots + mouse/keyboard control), arbitrary shell, and
anything that installs software. Revisit only after the typed-tool + confirmation model is
proven on the small surface above.

## 6. Acceptance checks (when this phase is eventually built)
- [ ] Every tool is typed with a JSON schema; no generic shell tool exists.
- [ ] Read-only tools run without a prompt; mutating/outbound tools always pause for
      explicit AJ confirmation via the HUD/voice loop.
- [ ] A restricted action requested by file/web/tool content is surfaced for confirmation,
      never auto-executed.
- [ ] `run_command` only executes entries on the fixed allowlist; free-form commands are
      rejected.
