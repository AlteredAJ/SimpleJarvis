# Jarvis — Phase 3 Build Plan: Voice Quality + Wake-Word/Interruption Robustness

**Prereq: Phases 1–2 landed.** Read `PHASE1-BUILD-PLAN.md` and `JARVIS-BRIEF.md` first.
Two independent tracks here — local TTS (voice quality) and the audio front-end (wake word,
VAD, echo cancellation). They can ship in either order.

> ⚠️ **VERSION NUMBERS TO VERIFY BEFORE PINNING.** The research report cited specific
> versions that could not be confirmed and may be hallucinated. **Confirm each exists on
> PyPI/GitHub for this hardware before committing to it:** "Silero VAD v6" (v5 was the last
> confirmed — check the actual latest), `pywebrtc-audio` (confirm the exact package/owner for
> WebRTC AEC3 Python bindings), and `openWakeWord v0.6.0`. Kokoro's RTF/latency numbers on
> the Arc B580 are also unverified — benchmark on the real machine, don't trust the report's
> figures.

> ⚠️ **INTEL ARC — NO CUDA.** Every model here must run via Vulkan/**OpenVINO**/ONNX-Runtime,
> never CUDA wheels (they fail silently or fall back to slow CPU). Install
> `onnxruntime-openvino` / `intel-extension-for-pytorch`, not `onnxruntime-gpu`.

---

## Track A — Local TTS (voice quality; AJ's #1 voice priority)

### Current state
`tools/tts.py` = ElevenLabs (`eleven_flash_v2_5`), high quality but per-character cost and
network latency. A local **Kokoro-82M** path was attempted and **shelved** — blocked by the
Python 3.14 interpreter (`spacy`/`blis` don't build on 3.14; they need 3.12).

### Recommendation: Kokoro via an isolated Python 3.12 microservice
Don't try to make Kokoro import into the main 3.14 process. **Decouple it as a local
service**, which cleanly sidesteps the 3.14 blocker:
- Run **Kokoro-FastAPI** in a dedicated **Python 3.12** venv managed by `uv`
  (`uv run --python 3.12 …`), exposing an OpenAI-compatible speech endpoint on
  `http://localhost:8880`.
- The main Jarvis process (3.14) streams reply text to that port and gets streaming PCM/WAV
  back — same shape `voice_loop.py` already expects from `_synthesize_pcm`.
- On the Arc B580, run Kokoro through **ONNX/OpenVINO** execution providers
  (`onnxruntime-openvino`), not PyTorch-CUDA. It's small (<~500MB VRAM claimed — verify), so
  it leaves the GPU free for AJ's other work.

### Keep ElevenLabs as the fallback
Leave `tools/tts.py` intact as the fallback path. Add a new local-TTS module alongside it
(mirror the brief's "add, don't delete" rule). Default to Kokoro **only after** its quality
clears the bar in a side-by-side against ElevenLabs on this machine — voice quality is the
priority, so don't downgrade blindly to save money.

### Persona voice
Kokoro supports voicepack blending (weighted mixes of voice embeddings) to define a
consistent, bespoke "Friday/Jarvis" voice that can't drift with an upstream API. Pin one
blend and reuse it.

---

## Track B — Wake word, VAD, and echo cancellation (interruption robustness)

### Current state
`voice_loop.py` uses **energy-threshold RMS VAD** (`VAD_RMS_THRESHOLD`) plus a Whisper
keyword match for the wake word. There is **no acoustic echo cancellation** — it only works
today because AJ uses a **HyperX Quadcast** (desk mic) + **closed Arctis Nova Pro
headphones**, which have low acoustic coupling. The code explicitly warns this breaks with
open speakers.

### B1 — Wake word: openWakeWord (replace the Whisper keyword match)
- **openWakeWord** (verify version) — lightweight mel-spectrogram neural wake-word model,
  runs on the Ryzen CPU via **ONNX Runtime** (<1% CPU idle), no GPU/VRAM. Replaces the crude
  energy-VAD + Whisper-keyword gate for starting a fresh interaction.
- If its audio-backend deps don't build on 3.14, **co-host it in the same Python 3.12 `uv`
  venv as Kokoro** (Track A) — one isolated service for both.
- Runner-up **Picovoice Porcupine** rejected: proprietary license + periodic cloud
  validation conflicts with a fully-local, private assistant.

### B2 — VAD: Silero (replace RMS energy threshold)
- Swap the raw RMS threshold in `voice_loop.Listener` for **Silero VAD** (verify latest
  version). ~2MB, evaluates 30ms chunks in <1ms on one CPU thread, robust to ambient noise
  without hand-tuning `VAD_RMS_THRESHOLD`. This directly improves barge-in reliability.

### B3 — AEC: WebRTC AEC3 (kill self-interruption)
- Add **WebRTC AEC3** via a Python binding (verify the exact package). Pipeline:
  1. TTS playback (Kokoro/ElevenLabs output) → speakers **and** → AEC3 as the *far-end*
     reference.
  2. Mic input → AEC3 as the *near-end* capture.
  3. AEC3 subtracts the TTS waveform from the mic in real time → clean stream.
  4. Clean stream → Silero VAD. Speech detected on the cleaned stream is **guaranteed** to be
     AJ, not Jarvis's own voice leaking in — eliminating false self-interruptions.
- Tune `stream_delay_ms` to this audio interface's latency.
- **Priority note:** with the current Quadcast + closed-headphones setup, self-interruption
  is already low-risk, so AEC is a robustness upgrade, not a blocker. It becomes essential
  the moment AJ switches to open speaker output.

### Resource budget (all CPU, ~0 VRAM)
AEC3 <50MB / <5ms, Silero ~2MB / <1ms, openWakeWord <100MB / ~80ms — all on the Ryzen,
nothing on the GPU. Coexists with AJ's work.

## Acceptance checks
- [ ] Kokoro runs in an isolated 3.12 `uv` service on the Arc B580 via OpenVINO/ONNX (no CUDA
      wheel, no 3.14 spacy/blis error); main process streams text→PCM over localhost.
- [ ] Kokoro voice quality judged against ElevenLabs on this machine before making it default.
- [ ] "Hey Jarvis" wakes reliably via openWakeWord at <1% idle CPU; ambient speech doesn't.
- [ ] Silero VAD replaces the RMS threshold; barge-in fires on real speech, not on noise.
- [ ] With TTS playing through **speakers**, Jarvis no longer interrupts itself (AEC3 working).
- [ ] All pinned versions verified to exist before install.
