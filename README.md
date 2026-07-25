<div align="center">

<img src="https://img.shields.io/badge/python-3.12%20%7C%203.14-blue" alt="Python">
<img src="https://img.shields.io/badge/license-MIT-green" alt="License">
<img src="https://img.shields.io/badge/platform-Windows%2011-0078D6" alt="Platform">
<img src="https://img.shields.io/badge/TTS-Kokoro%20%7C%20ElevenLabs-orange" alt="TTS">
<img src="https://img.shields.io/badge/brain-DeepSeek%20%7C%20Claude-purple" alt="Brain">

</div>

# Simple Jarvis

Personal conversational AI with real-time voice interaction, live transcript HUD, barge-in interruption, neural wake word, and Obsidian wiki grounding. Runs on local hardware with no cloud subscription required per query.

> Built as the personal companion project to [Pickup](https://github.com/AlteredAJ/) — a commercial AI voice agent for small businesses. Different product, shared engine.

---

## Features

- **Real-time voice loop** — continuous spoken conversation with instant barge-in (hard/soft interrupt classification). Grace window follow-ups, no wake word needed mid-conversation.
- **Live transcript HUD** — cinematic radial waveform with streaming SSE transcript panel. Both sides visible (you + Jarvis), interruption markers, aside sub-lines. Dashboard readouts for model, wiki pages, memory, turn count, and latency.
- **Neural wake word + VAD** — openWakeWord ONNX for `hey jarvis` detection (~18ms inference). Silero VAD for speech activity — replaces crude RMS energy threshold. Zero false positives on ambient noise.
- **LLM routing** — DeepSeek (default, $0.27/MTok input) for normal turns. Claude Sonnet 5 escalation for hard analysis. Claude Haiku fallback. Trivial commands (time, date) handled locally with zero API calls.
- **Local TTS** — Kokoro-82M via Python 3.12 microservice. 54 voices, 3.4x realtime on CPU. Falls back silently to ElevenLabs if Kokoro is down. ONNX + DirectML GPU support verified on Intel Arc B580.
- **Obsidian vault context** — keyword RAG + `[[wikilink]]` following over your live Obsidian vault. Pinned pages injected into every turn. No vector DB, no embeddings — pure keyword overlap.
- **Durable memory** — `_Jarvis_Memory/` folder in your vault. Dated Markdown files, per-session salience summaries (not raw transcripts). Two-tier recall: today + yesterday always, keyword search for older days.
- **Agentic tool loop** — modular brain architecture ready for computer control (Phase 4). Tool-calling scaffold from the original prototype is intact.

---

## Architecture

```
┌──────────────────────────────────────────────┐
│                 voice_loop.py                │
│  wake word → STT → barge-in → TTS playback  │
└──────────┬──────────────────────┬────────────┘
           │                      │
    ┌──────▼──────┐       ┌──────▼──────────┐
    │   chat.py   │       │   hud_server.py  │
    │  brain      │       │  /state polling  │
    │  routing    │       │  /events SSE     │
    └──┬───┬───┬──┘       └──────┬───────────┘
       │   │   │                 │
  ┌────▼┐ ┌▼─┐ ┌▼──────────┐  ┌▼────────────┐
  │deep │ │cl│ │local route │  │  hud.html    │
  │seek │ │au│ │time/date   │  │  waveform +  │
  └─────┘ └──┘ └────────────┘  │  transcript  │
                                └─────────────┘
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│   rag.py     │  │  memory.py   │  │ memory_vault │
│  wiki RAG    │  │  SQLite buf  │  │  .md durable │
└──────────────┘  └──────────────┘  └──────────────┘

┌──────────────────────────────────────────────┐
│  kokoro_server.py  (Python 3.12, port 8880)  │
│  Kokoro-82M ONNX → 16-bit PCM 16kHz          │
└──────────────────────────────────────────────┘
```

---

## Hardware

| Component | Spec |
|-----------|------|
| CPU | Ryzen 7800X3D-class |
| GPU | Intel Arc B580 (12GB, Vulkan/OpenVINO/DirectML only — no CUDA) |
| RAM | ~32 GB |
| OS | Windows 11 |
| Python | 3.14 (main) + 3.12 (Kokoro TTS microservice) |

---

## Installation

### 1. Clone

```bash
git clone https://github.com/AlteredAJ/SimpleJarvis.git
cd SimpleJarvis
```

### 2. Python environment (3.14)

```bash
pip install -r requirements.txt
```

### 3. API keys

Copy `.env.example` to `.env` and fill in:

```env
DEEPSEEK_API_KEY=sk-...          # primary brain (cheap)
ANTHROPIC_API_KEY=sk-ant-...     # escalation brain
ELEVENLABS_API_KEY=sk_...        # TTS fallback (if Kokoro is down)
```

### 4. Kokoro TTS (Python 3.12, optional but recommended)

Kokoro needs Python 3.12 (blis/spacy don't build on 3.14). It runs as a separate microservice:

```bash
# With uv (recommended):
uv venv --python 3.12 kokoro_tts/.venv
uv pip install kokoro-onnx soundfile numpy --python 3.12

# Or directly:
py -3.12 -m pip install kokoro-onnx soundfile numpy

# Download models (~340 MB):
python -c "from urllib.request import urlretrieve; urlretrieve('https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx', 'kokoro_tts/models/kokoro-v1.0.onnx'); urlretrieve('https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin', 'kokoro_tts/models/voices-v1.0.bin')"

# Start server:
py -3.12 kokoro_server.py
```

### 5. Neural wake word models (auto-downloaded)

```bash
python -c "from openwakeword.utils import download_models; download_models(['hey_jarvis_v0.1'])"
```

### 6. Obsidian vault

Set `JARVIS_VAULT_PATH` in `.env` or accept the default:

```env
JARVIS_VAULT_PATH=E:\Obsidian Vault\Alt3red
```

---

## Usage

### One-click launch (recommended)

Double-click `Jarvis.bat` on your desktop. Starts Kokoro + HUD + voice loop. Everything shuts down when you close Jarvis. Zero background processes left behind.

### Manual launch

```bash
# Start Kokoro TTS server (Python 3.12):
py -3.12 kokoro_server.py &

# Start Jarvis voice loop:
python voice_loop.py --new

# Or text-only:
python chat.py --new

# HUD opens at http://localhost:8799/
```

### Launcher CLI

```bash
python launch_jarvis.py              # voice mode
python launch_jarvis.py --text        # text-only
python launch_jarvis.py --no-kokoro   # skip Kokoro, use ElevenLabs
```

### Chat commands

| Command | Action |
|---------|--------|
| `/pin <page>` | Pin a wiki page into every turn's context |
| `/unpin <page>` | Remove a pin |
| `/pins` | List pinned pages |
| `/help` | Show help |
| `exit` / `quit` / `bye` | End session |

### Trivial commands (zero API calls)

"what time is it", "what's the date", "what day is it", "time", "date", "today"

---

## Project structure

```
jarvis/
├── voice_loop.py          # Real-time spoken conversation with barge-in
├── chat.py                # Text/voice chat loop + brain routing
├── launch_jarvis.py       # One-click launcher (starts/kills everything)
├── hud_server.py          # Local HTTP + SSE server for HUD
├── hud.html               # Cinematic waveform + live transcript UI
│
├── brain_openai_compat.py # DeepSeek API (OpenAI-compatible)
├── brain_claude.py        # Claude Haiku / Sonnet 5 escalation
├── brain_ollama.py        # Local Ollama (dormant)
│
├── rag.py                 # Keyword RAG + [[wikilink]] following
├── pins.py                # Pinned wiki page context
├── memory.py              # SQLite conversation buffer
├── memory_vault.py        # Durable dated-Markdown memory in vault
├── stt.py                 # Speech-to-text (faster-whisper)
│
├── tools/
│   ├── tts.py             # ElevenLabs TTS
│   ├── tts_kokoro.py      # Kokoro TTS client (HTTP to microservice)
│   ├── calendar.py        # Google Calendar (dormant)
│   └── sms.py             # Twilio SMS (dormant)
│
├── context/               # Reference snapshots of wiki pages
├── config/                # Demo business configs (Pickup-era, dormant)
├── static/                # Generated audio files
└── fonts/                 # Pitch deck fonts
```

---

## Build phases

| Phase | Status | What |
|-------|--------|------|
| 1 | ✅ | Claude brain, vault memory, pins, wiki RAG, local routing |
| 2 | ✅ | Live transcript HUD, SSE events, interruption rendering, dashboard |
| 3A | ✅ | Kokoro-82M TTS microservice, ElevenLabs fallback |
| 3B | ✅ | openWakeWord + Silero VAD (neural wake word + voice detection) |
| 4 | 📋 | Computer control (tool-calling, file system, whitelist commands) |

---

## License

MIT © 2026 AJ Apau-Kese

Kokoro model: Apache 2.0. openWakeWord: Apache 2.0. Silero VAD: MIT.
