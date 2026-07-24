"""
Local TTS via Miso TTS 8B (misolabs.ai / MisoLabsAI/MisoTTS on GitHub).

STATUS: NOT IMPLEMENTED — hardware-blocked on this machine, confirmed via
the actual repo (not just secondhand notes), 2026-07-20.

Hardware requirement (from https://github.com/MisoLabsAI/MisoTTS):
    | Precision       | VRAM needed | Example GPUs           |
    |-----------------|-------------|------------------------|
    | bfloat16/fp16   | 24 GB       | RTX 3090/4090, A5000   |
    | float32         | 40 GB+      | A100, A6000, H100      |
    CPU is technically supported but "slow" and still needs ~20-40GB RAM.

This machine has an Intel Arc B580 with 12GB VRAM — half of the minimum
bf16/fp16 requirement, and the repo's inference code only documents a CUDA
path (`load_miso_8b(device="cuda")`); Intel Arc / Vulkan / DirectML are not
mentioned anywhere in the repo. This isn't a "might be tight" situation,
it's a hard no on current hardware — same conclusion JARVIS-BRIEF.md already
reached before this repo existed on this machine ("shelved... needs 24GB+
VRAM"). No install was attempted; there's nothing to gain from trying a
~30-40GB model download that's architecturally CUDA-only against a non-CUDA
12GB GPU.

If AJ gets access to a CUDA GPU with >=24GB VRAM later, this is what
`speak()` needs to actually do (from the repo's documented API):

    from generator import load_miso_8b
    generator = load_miso_8b(device="cuda")
    audio = generator.generate(text=text, speaker=0, context=[])
    # `context` accepts Segment objects with prompt audio for voice cloning.

Setup would be (per the repo):
    git clone https://github.com/MisoLabsAI/MisoTTS.git
    cd MisoTTS && uv sync --python 3.10   # or: pip install -e . in a 3.10 venv
    # first run downloads ~30-40GB of weights from Hugging Face

Streaming support is not documented in the repo — likely a request/response
model like the stub below, not a token-by-token stream like ElevenLabs'
streaming endpoint. Voice cloning IS supported (via `context`), which
matters for a "sounds like a specific person" ask later.

Until CUDA hardware is available, `tools/tts.py` (ElevenLabs) is the
speech path — see also `voice_loop.py` for the interruptible playback +
barge-in wiring, which is written against `tools/tts.py`'s interface and
will work unchanged with this module once it's real (same speak() shape).
"""

from pathlib import Path

AUDIO_DIR = Path("static/audio")
AUDIO_DIR.mkdir(parents=True, exist_ok=True)


def speak(text: str, voice_id: str | None = None) -> str:
    """
    Generates speech from text using a local Miso TTS 8B model.
    Saves the audio to a static file and returns the filename.

    NOT IMPLEMENTED on this machine: Miso TTS 8B requires a CUDA GPU with
    >=24GB VRAM (bf16/fp16) per its own repo's hardware table. This machine's
    Intel Arc B580 has 12GB VRAM and no CUDA support — the repo's inference
    path is CUDA-only (`load_miso_8b(device="cuda")`), with no documented
    Vulkan/DirectML/Intel path. See module docstring for the full picture
    and what real hardware would unblock this.
    """
    raise NotImplementedError(
        "Miso TTS 8B needs a CUDA GPU with >=24GB VRAM (per "
        "github.com/MisoLabsAI/MisoTTS's own hardware table); this machine's "
        "Intel Arc B580 (12GB, non-CUDA) doesn't meet that. No install was "
        "attempted — see this module's docstring for what real hardware "
        "would unblock it and the exact API to call once available. "
        "tools/tts.py (ElevenLabs) is the working speech path today."
    )
