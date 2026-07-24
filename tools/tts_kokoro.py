"""
Local TTS via Kokoro-82M (Apache-2.0, CPU-viable, no GPU required).

STATUS: NOT IMPLEMENTED — blocked on this machine's Python version.

Blocker (investigated 2026-07-20):
    `pip install kokoro` was run against C:\\Python314\\python.exe (Python 3.14.6,
    the only interpreter on PATH via the `python` command / `py -0` default).
    torch itself has a cp314 Windows wheel now (torch-2.13.0-cp314-cp314-win_amd64.whl
    resolved fine), so torch is NOT the blocker as originally suspected.

    The actual failure is deeper in kokoro's dependency chain:
        kokoro -> misaki[en] -> spacy -> thinc -> blis

    `blis` (a thinc/spacy BLAS-binding dependency) has no cp314 wheel on PyPI, so pip
    falls back to building it from source. That source build fails while Cython-
    compiling blis's .pyx files against the NumPy C-API pulled in by the build:

        Error compiling Cython file:
        ...
        numpy/__init__.pxd:12:13: Error in compile-time expression:
        ValueError: invalid literal for int() with base 10: 'Build aborted: the NumPy Cython...'
        ...
        blis\\py.pyx:39:18: no suitable method found
        blis\\py.pyx:57:16: Python objects cannot be cast to pointers of primitive types
        ...

    Root cause: blis's bundled Cython/.pyx code is incompatible with the newer NumPy
    Cython API that gets installed as a build dependency under Python 3.14 (no pinned/
    prebuilt wheel exists yet for cp314). This is a packaging problem in the
    spacy/thinc/blis stack, not something fixable by retrying or flags.

    Full pip output saved during investigation showed three chained failures:
        ERROR: Failed to build 'blis' when getting requirements to build wheel
        ERROR: Failed to build 'thinc' when installing build dependencies for thinc
        ERROR: Failed to build 'spacy' when installing build dependencies for spacy

Environment check performed:
    `py -0p` on this machine shows two interpreters:
        C:\\Python314\\python.exe                                  (3.14.6, default)
        C:\\Users\\Altered\\AppData\\Local\\Programs\\Python\\Python312\\python.exe  (3.12)

    Python 3.12 is already installed and should have prebuilt wheels available for
    blis/spacy/thinc (these packages have long-standing cp312 wheel support), which
    would very likely unblock `pip install kokoro` without any source builds.

Recommendation:
    Create a separate venv under Python 3.12
    (e.g. `C:\\Users\\Altered\\AppData\\Local\\Programs\\Python\\Python312\\python.exe -m venv .venv-tts`)
    and run `pip install kokoro` there. Once confirmed working, either:
      (a) shell out / call this module's logic from a subprocess running under that
          3.12 venv, or
      (b) run the whole jarvis TTS-serving component under 3.12 instead of 3.14.
    This file intentionally does NOT fake an implementation — see `speak()` below.
"""

from pathlib import Path

AUDIO_DIR = Path("static/audio")
AUDIO_DIR.mkdir(parents=True, exist_ok=True)


def speak(text: str, voice_id: str | None = None) -> str:
    """
    Generates speech from text using a local Kokoro-82M model.
    Saves the audio to a static file and returns the filename.

    NOT IMPLEMENTED on this machine: `pip install kokoro` fails under the
    system Python (3.14.6) because a transitive dependency (misaki[en] ->
    spacy -> thinc -> blis) has no cp314 wheel and fails to build from source
    (Cython/NumPy C-API incompatibility in blis). See module docstring above
    for the full chain and the exact pip error captured during investigation.

    Unblocking this requires installing/using Python 3.12 (already present at
    C:\\Users\\Altered\\AppData\\Local\\Programs\\Python\\Python312\\python.exe on
    this machine) for the kokoro dependency, e.g. via a dedicated venv, rather
    than forcing a source build under 3.14.

    Until that's done, `tools/tts.py` (ElevenLabs-based) remains the working
    TTS path and is untouched.
    """
    raise NotImplementedError(
        "kokoro is not installed: pip install fails on Python 3.14.6 here "
        "because 'blis' (spacy/thinc dependency of misaki[en]) has no cp314 "
        "wheel and fails to build from source (Cython/NumPy C-API mismatch). "
        "Python 3.12 is available on this machine at "
        r"C:\Users\Altered\AppData\Local\Programs\Python\Python312\python.exe "
        "and should be used instead (e.g. via a dedicated venv) to unblock "
        "kokoro installation. See this module's docstring for the full error "
        "chain captured during investigation."
    )
