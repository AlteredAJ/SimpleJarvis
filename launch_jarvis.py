r"""
Jarvis Launcher — one-click start/stop. No background leftovers.

Run this instead of voice_loop.py directly. It:
  1. Starts Kokoro TTS + HUD server as subprocesses
  2. Opens the HUD browser window
  3. Launches the voice loop (or text chat)
  4. When Jarvis exits, kills all subprocesses — nothing left running

Usage:
    python launch_jarvis.py              # voice mode
    python launch_jarvis.py --text        # text-only mode
    python launch_jarvis.py --no-kokoro   # skip Kokoro, use ElevenLabs

Desktop shortcut (Windows):
    Create a .bat file on the desktop containing:
        python C:/Users/Altered/Claude/jarvis_extracted/jarvis/launch_jarvis.py
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
import webbrowser
from datetime import datetime

JARVIS_DIR = r"C:\Users\Altered\Claude\jarvis_extracted\jarvis"
KOKORO_SERVER = r"C:\Users\Altered\Claude\kokoro_tts\kokoro_server.py"
PY312 = r"C:\Users\Altered\AppData\Local\Programs\Python\Python312\python.exe"
HUD_URL = "http://localhost:8799/"

_procs: list[subprocess.Popen] = []


def _start(name: str, args: list[str], cwd: str | None = None) -> subprocess.Popen:
    print(f"  [{name}] starting...", flush=True)
    proc = subprocess.Popen(
        args,
        cwd=cwd,
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _procs.append(proc)
    return proc


def _cleanup() -> None:
    """Kill all child processes. Called on exit/Ctrl+C."""
    for p in _procs:
        try:
            p.terminate()
        except Exception:
            pass
    # Give them a moment to exit, then force-kill
    time.sleep(0.3)
    for p in _procs:
        try:
            if p.poll() is None:
                p.kill()
        except Exception:
            pass
    _procs.clear()


def _signal_handler(signum, frame) -> None:
    print("\nShutting down...", flush=True)
    _cleanup()
    sys.exit(0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Jarvis one-click launcher")
    parser.add_argument("--text", action="store_true", help="text-only mode")
    parser.add_argument("--no-kokoro", action="store_true", help="skip Kokoro TTS")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    print("=" * 45)
    print("  JARVIS LAUNCHER")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 45)

    session_id = f"local-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    print(f"  Session: {session_id}")
    print()

    try:
        # 1. Kokoro TTS (Python 3.12)
        if not args.no_kokoro:
            _start("Kokoro", [PY312, KOKORO_SERVER])
            time.sleep(4)

        # 2. HUD server (Python 3.14, which is default)
        _start("HUD", [sys.executable, "-c",
            "import hud_server; url = hud_server.start(); "
            "import time; print(f'HUD at {url}', flush=True); "
            "while True: time.sleep(10)"
        ], cwd=JARVIS_DIR)
        time.sleep(1)
        webbrowser.open(HUD_URL)

        # 3. Main Jarvis process (runs in foreground until exit)
        jarvis_cmd = [sys.executable, "voice_loop.py", "--session", session_id]
        if args.text:
            jarvis_cmd = [sys.executable, "chat.py", "--session", session_id]

        print(f"  [Jarvis] starting {'text' if args.text else 'voice'} loop...")
        print(f"  HUD: {HUD_URL}")
        print("  Type 'exit' or Ctrl+C to quit.")
        print("-" * 45)

        # Run Jarvis in foreground — user interacts here
        result = subprocess.run(
            jarvis_cmd,
            cwd=JARVIS_DIR,
            creationflags=subprocess.CREATE_NEW_CONSOLE if not args.text else 0,
        )

        print("-" * 45)
        print(f"  Jarvis exited (code {result.returncode}).")

    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        print("  Cleaning up background processes...")
        _cleanup()
        print("  Done. Nothing left running.")
        print("=" * 45)


if __name__ == "__main__":
    main()
