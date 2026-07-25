<div align="center">

<img src="https://img.shields.io/badge/python-3.12%20%7C%203.14-blue" alt="Python">
<img src="https://img.shields.io/badge/license-MIT-green" alt="License">
<img src="https://img.shields.io/badge/platform-Windows%2011-0078D6" alt="Platform">
<img src="https://img.shields.io/badge/TTS-Kokoro%20%7C%20ElevenLabs-orange" alt="TTS">
<img src="https://img.shields.io/badge/brain-DeepSeek%20%7C%20Claude-purple" alt="Brain">
<img src="https://img.shields.io/github/stars/AlteredAJ/SimpleJarvis?style=social" alt="Stars">

</div>

# Simple Jarvis

Personal conversational AI with real-time voice interaction, live transcript HUD, barge-in interruption, and Obsidian wiki grounding. Runs on local hardware — no cloud subscription required per query.

> Looking for the commercial version? [Pickup](https://github.com/AlteredAJ/) is the AI voice agent for small businesses. Same engine, different persona.

## Key Capabilities

- **Voice-first conversation** — continuous spoken dialogue with instant barge-in (hard/soft interrupts) and grace-window follow-ups
- **Live cinematic HUD** — radial waveform, streaming transcript with both sides visible, interruption markers, dashboard readouts
- **Neural wake word + VAD** — openWakeWord (`hey jarvis`) + Silero VAD. Zero false positives on ambient noise
- **Smart brain routing** — DeepSeek for everyday (cheap), Claude Sonnet 5 for hard analysis, local routing for time/date (zero API cost)
- **Local TTS** — Kokoro-82M (free, 54 voices, 3.4x realtime) with ElevenLabs fallback
- **Obsidian vault grounding** — keyword RAG + `[[wikilink]]` following over your personal wiki. No vector DB needed

## 🚀 Quick Start

**Prerequisites:** Python 3.12+ (3.14 for main, 3.12 for Kokoro), a mic, and an API key.

```bash
# 1. Clone
git clone https://github.com/AlteredAJ/SimpleJarvis.git
cd SimpleJarvis

# 2. Install
pip install -r requirements.txt
python -c "from openwakeword.utils import download_models; download_models(['hey_jarvis_v0.1'])"

# 3. Set your API key
cp .env.example .env
# Edit .env — add DEEPSEEK_API_KEY (or ANTHROPIC_API_KEY)

# 4. (Optional) Start Kokoro TTS for free local speech
py -3.12 -m pip install kokoro-onnx soundfile numpy
# Download model files (~340MB) — see full install below

# 5. Launch
python launch_jarvis.py --text   # text-only, no mic setup needed
python launch_jarvis.py          # full voice mode
```

HUD opens at `http://localhost:8799/`. Type `exit` or Ctrl+C to quit. All background processes die with it — nothing left running.

**Double-click:** `Jarvis.bat` on your desktop does all of the above.

## ✨ Features

### Voice Loop

Continuous spoken conversation with real-time barge-in interruption. Two kinds: **hard** ("stop", "wait", "actually") cancels the reply and starts fresh. **soft** (anything else) pauses, answers the aside, and resumes the primary reply from where it stopped.

- Wake word (`hey jarvis`) gates idle listening — ambient speech is ignored
- Grace window after each reply — follow-ups don't need the wake word
- Streaming STT (faster-whisper) + streaming TTS (Kokoro/ElevenLabs)

### Live Transcript HUD

Cinematic radial waveform with a scrolling transcript panel. Both sides visible — your speech on the left, Jarvis's reply on the right.

- Token-by-token streaming as Jarvis generates
- Hard interruption shows a cut marker: `the backup is experien— [interrupted]` with dimmed remainder on hover
- Soft asides render as indented sub-lines
- Dashboard panels: brain model (DeepSeek/Claude), wiki pages loaded, memory status, turn count + latency

### Brain Routing

| Turn type | Model | Cost (per MTok input) |
|-----------|-------|----------------------|
| Everyday conversation | DeepSeek V3 | $0.27 |
| Hard analysis ("think hard", "analyze", code) | Claude Sonnet 5 | $3.00 |
| Fallback (no DeepSeek key) | Claude Haiku 4.5 | $1.00 |
| Trivial (time, date) | Local, zero API | Free |

All routing is code-based (deterministic keyword matching, not an ML model). Wrong routing doesn't break anything — it just uses a different model.

### Wiki Grounding

Keyword RAG over your live Obsidian vault — finds relevant pages by tokenized keyword overlap, then follows `[[wikilinks]]` to pull in connected pages. Pinned pages inject into every turn.

- **Read-only** — never modifies vault files outside of `_Jarvis_Memory/`
- **Tiered memory** — today + yesterday always loaded; keyword search for older days
- **Salience summaries** — session-end summaries (facts, decisions, preferences), never raw transcripts

### Tools & Extensibility

Agentic tool loop scaffold is intact from the original prototype. Dormant tools ready for activation:

- `tools/calendar.py` — Google Calendar OAuth (check availability, book appointments)
- `tools/sms.py` — Twilio SMS (confirmation messages)
- `tools/tts_kokoro.py` — Kokoro TTS client (HTTP to Python 3.12 microservice)
- Computer control (Phase 4) — typed tool-calling with safety gates

## 📦 Full Installation

### Kokoro TTS (Python 3.12 microservice)

Kokoro-82M runs in a separate Python 3.12 process (blis/spacy don't build on 3.14). It's optional — ElevenLabs works without it.

```bash
mkdir -p kokoro_tts/models
py -3.12 -m pip install kokoro-onnx soundfile numpy

# Download models (~340MB):
python -c "
from urllib.request import urlretrieve
base = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0'
urlretrieve(f'{base}/kokoro-v1.0.onnx', 'kokoro_tts/models/kokoro-v1.0.onnx')
urlretrieve(f'{base}/voices-v1.0.bin', 'kokoro_tts/models/voices-v1.0.bin')
"

# Start server (keep running in background):
py -3.12 kokoro_server.py
```

54 voices available. Default: `af_sarah` (female, warm). Set `KOKORO_VOICE` in `.env` to change.

### GPU acceleration (Intel Arc B580)

```bash
pip install onnxruntime-directml
```

Kokoro uses CPU by default (3.4x realtime, already fast enough for conversation). Set `ONNX_PROVIDER=DmlExecutionProvider` to try GPU — note that Kokoro's ConvTranspose op is not DML-compatible on the current version.

### Environment variables

```env
# Brain
DEEPSEEK_API_KEY=sk-...           # primary (cheap, default)
ANTHROPIC_API_KEY=sk-ant-...      # escalation + fallback

# TTS
ELEVENLABS_API_KEY=sk_...         # fallback if Kokoro is down
ELEVENLABS_VOICE_ID=...           # default: Daniel (British)
KOKORO_URL=http://localhost:8880   # Kokoro microservice
KOKORO_VOICE=af_sarah             # default voice for Kokoro
KOKORO_ENABLED=1                  # set 0 to force ElevenLabs

# Vault
JARVIS_VAULT_PATH=E:\Obsidian Vault\Alt3red
WIKI_VAULT_PATH=E:\Obsidian Vault\Alt3red\wiki

# Routing
LLM_PROVIDER=deepseek             # "deepseek" | "claude" | "openai"
LLM_MODEL=deepseek-chat           # override model name
```

## 🖥️ HUD Dashboard

The HUD opens in your default browser at `http://localhost:8799/`. It shows:

- **Waveform** — cinematic radial ring with hex core, orbiting particles, and holographic scanlines. Changes color per state (idle/listening/thinking/speaking/aside/interrupted)
- **Dashboard panels** — brain model, wiki pages loaded, memory status, turn count, latency
- **Live transcript** — streaming token-by-token from SSE events. Both sides visible. Interruption markers on hard barge-in

No React, no frameworks. Vanilla JS canvas + `EventSource`.

## 📋 Usage

### Chat commands

| Command | Action |
|---------|--------|
| `/pin <page>` | Pin a wiki page into every turn's context |
| `/unpin <page>` | Remove a pin |
| `/pins` | List pinned pages |
| `/help` | Show help |
| `exit` | End session (summarizes to vault memory) |

### Trivial commands (zero API calls)

"what time is it" · "what's the date" · "what day is it" · "time" · "date" · "today"

### Launcher

```bash
python launch_jarvis.py              # voice mode
python launch_jarvis.py --text        # text-only
python launch_jarvis.py --no-kokoro   # skip Kokoro, use ElevenLabs
```

## 📂 Project Structure

```
SimpleJarvis/
├── voice_loop.py          # Real-time spoken conversation with barge-in
├── chat.py                # Text/voice loop + brain routing + local commands
├── launch_jarvis.py       # One-click launcher (starts/kills all processes)
├── hud_server.py          # HTTP + SSE server for HUD
├── hud.html               # Cinematic waveform + live transcript UI
├── kokoro_server.py       # Kokoro-82M TTS microservice (Python 3.12)
│
├── brain_openai_compat.py # DeepSeek API (OpenAI-compatible)
├── brain_claude.py        # Claude Haiku / Sonnet 5 escalation
├── brain_ollama.py        # Local Ollama (dormant)
│
├── rag.py                 # Keyword RAG + [[wikilink]] following
├── pins.py                # Pinned wiki page context
├── memory.py              # SQLite conversation buffer
├── memory_vault.py        # Durable dated-Markdown memory in Obsidian vault
├── stt.py                 # Speech-to-text (faster-whisper)
│
├── tools/
│   ├── tts.py             # ElevenLabs TTS
│   ├── tts_kokoro.py      # Kokoro TTS client (HTTP to microservice)
│   ├── calendar.py        # Google Calendar (dormant)
│   └── sms.py             # Twilio SMS (dormant)
│
├── config/                # Demo business configs (Pickup-era, dormant)
├── context/               # Reference wiki snapshots
├── static/                # Generated audio files
└── fonts/                 # Pitch deck fonts
```

## 🗺️ Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| 1 | ✅ | Claude brain, vault memory, pin system, wiki RAG, local routing |
| 2 | ✅ | Live transcript HUD, SSE events, interruption rendering, dashboard panels |
| 3A | ✅ | Kokoro-82M TTS microservice with ElevenLabs fallback |
| 3B | ✅ | openWakeWord + Silero VAD (neural wake word + voice activity detection) |
| 4 | 📋 | Computer control — typed tool-calling, file system access, calendar/SMS tools |

## 🤝 Contributing

Issues and PRs welcome. Check `JARVIS-BRIEF.md` for project context and `PHASE*.md` for build plans before contributing code.

## 📄 License

MIT © 2026 AJ Apau-Kese

Kokoro model: Apache 2.0 · openWakeWord: Apache 2.0 · Silero VAD: MIT
