"""
tray.py — Windows system tray icon for Jarvis.

Shows at a glance whether Jarvis is running in the background (no console
window needs to stay visible/foreground) and what it's currently doing —
mirrors the HUD's state colors so the two stay consistent: idle/listening/
thinking/speaking/aside/interrupted. Right-click menu: open the HUD window,
or quit Jarvis cleanly (stops the whole process, not just the tray icon).

Polls hud_server.get_state() on a slow interval (1s) — a tray icon doesn't
need the HUD's ~20fps responsiveness, it's a glance-at indicator, not a
live visualization.
"""

from __future__ import annotations

import os
import threading
import time
import webbrowser

import pystray
from PIL import Image, ImageDraw

import hud_server

STATE_COLOR = {
    "idle": (43, 111, 168),
    "listening": (53, 209, 196),
    "thinking": (185, 138, 240),
    "speaking": (79, 209, 255),
    "aside": (255, 180, 84),
    "interrupted": (255, 77, 94),
}
DEFAULT_COLOR = STATE_COLOR["idle"]

_icon_cache: dict[tuple[int, int, int], Image.Image] = {}


def _make_icon_image(color: tuple[int, int, int]) -> Image.Image:
    """A simple filled circle with a darker ring — cheap to generate,
    reads clearly at 16-32px tray-icon size. Cached per color since there
    are only 6 possible states, no need to redraw every poll."""
    if color in _icon_cache:
        return _icon_cache[color]
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = 6
    draw.ellipse([pad, pad, size - pad, size - pad], fill=(*color, 255))
    ring = tuple(max(0, c - 60) for c in color)
    draw.ellipse([pad, pad, size - pad, size - pad], outline=(*ring, 255), width=4)
    _icon_cache[color] = img
    return img


def _open_hud(icon, item) -> None:  # noqa: ANN001 - pystray callback signature
    url = hud_server.start()  # no-op if already started, returns the same URL
    webbrowser.open(url)


def _quit(icon, item) -> None:  # noqa: ANN001 - pystray callback signature
    icon.stop()
    os._exit(0)  # hard-exit the whole process, not just this thread — quitting
    # from the tray should actually stop Jarvis, not leave the voice loop
    # running headless with no visible way to reach it anymore.


def start() -> pystray.Icon:
    """Starts the tray icon on a background thread and returns the
    pystray.Icon object. Safe to call once per process (voice_loop.py's
    run() calls this at startup, same pattern as hud_server.start())."""
    initial_state = hud_server.get_state()
    icon = pystray.Icon(
        "jarvis",
        _make_icon_image(STATE_COLOR.get(initial_state["state"], DEFAULT_COLOR)),
        "Jarvis — idle",
        menu=pystray.Menu(
            pystray.MenuItem("Open HUD", _open_hud),
            pystray.MenuItem("Quit Jarvis", _quit),
        ),
    )

    def poll_loop() -> None:
        last_state = None
        while True:
            state = hud_server.get_state()
            s = state.get("state", "idle")
            if s != last_state:
                icon.icon = _make_icon_image(STATE_COLOR.get(s, DEFAULT_COLOR))
                label = state.get("label", "")
                icon.title = f"Jarvis — {s}" + (f': "{label[:40]}"' if label else "")
                last_state = s
            time.sleep(1.0)

    threading.Thread(target=poll_loop, daemon=True).start()
    threading.Thread(target=icon.run, daemon=True).start()
    return icon
