"""
hud_server.py — local status feed + SSE transcript events for the Jarvis HUD.

Two channels (both stdlib, no dependencies):
  - GET /state     — polling (~60ms) for waveform level + state color + dashboard metadata
  - GET /events    — SSE push for transcript tokens + meta changes (Phase 2)

voice_loop.py / chat.py push state via set_state()/set_level() and publish
transcript events via publish(). The HUD page consumes both.

Shared state is a plain dict guarded by a lock; SSE uses a subscriber list
with per-connection queues + a background heartbeat thread.
"""

from __future__ import annotations

import json
import queue
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_lock = threading.Lock()
_state = {"state": "idle", "level": 0.0, "label": ""}

HUD_HTML_PATH = Path(__file__).parent / "hud.html"

# --- SSE subscriber list ---
_subscribers: list[queue.Queue] = []
_sub_lock = threading.Lock()
_heartbeat_active = False


def _start_heartbeat() -> None:
    """Keep SSE connections alive with a comment every 15s (browsers
    may time out idle EventSource connections)."""
    global _heartbeat_active
    if _heartbeat_active:
        return
    _heartbeat_active = True

    def _beat() -> None:
        while True:
            time.sleep(15)
            with _sub_lock:
                dead = []
                for q in _subscribers:
                    try:
                        q.put_nowait(None)  # heartbeat sentinel
                    except queue.Full:
                        dead.append(q)
                for q in dead:
                    _subscribers.remove(q)

    t = threading.Thread(target=_beat, daemon=True)
    t.start()


def _subscribe() -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=256)
    with _sub_lock:
        _subscribers.append(q)
    _start_heartbeat()
    return q


def _unsubscribe(q: queue.Queue) -> None:
    with _sub_lock:
        if q in _subscribers:
            _subscribers.remove(q)


def publish(event: dict) -> None:
    """Push a transcript event to all connected SSE clients.
    event is a dict with at least {'type': '...'} — see PHASE2-TRANSCRIPT-UI.md §4
    for the full event catalog."""
    with _sub_lock:
        dead = []
        for q in _subscribers:
            try:
                q.put_nowait(event)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _subscribers.remove(q)


# --- Public API ---

def set_state(state: str, label: str = "", **meta) -> None:
    """state: 'idle' | 'listening' | 'thinking' | 'speaking' | 'aside' | 'interrupted'.
    Extra kwargs become metadata rendered in the HUD dashboard panels (model, wiki_pages,
    turn, tool, latency_ms, memory_status). Keys not passed keep their last value.

    Also publishes a 'meta' SSE event so the transcript panel updates dashboard
    readouts instantly alongside streaming text."""
    with _lock:
        merged = {k: v for k, v in meta.items() if v}  # skip empty strings
        _state["state"] = state
        _state["label"] = label
        _state.update(merged)

    if merged:
        merged["type"] = "meta"
        publish(merged)


def set_level(level: float) -> None:
    """level: 0.0-1.0ish RMS reading, raw is fine — the HUD clamps/scales it."""
    with _lock:
        _state["level"] = level


def get_state() -> dict:
    with _lock:
        return dict(_state)


# --- HTTP handler ---

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: A002
        pass

    def do_GET(self):
        if self.path == "/state":
            body = json.dumps(get_state()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            q = _subscribe()
            try:
                while True:
                    evt = q.get()
                    if evt is None:  # heartbeat
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
                        continue
                    line = f"data: {json.dumps(evt)}\n\n".encode("utf-8")
                    self.wfile.write(line)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                _unsubscribe(q)
            return

        if self.path in ("/", "/hud.html"):
            try:
                body = HUD_HTML_PATH.read_bytes()
            except OSError:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_error(404)


# --- Server lifecycle ---

_server: ThreadingHTTPServer | None = None


def start(port: int = 8799) -> str:
    """Starts the HUD server on a background daemon thread. Returns the URL
    to open. Safe to call once per process (voice_loop.py calls this at
    startup)."""
    global _server
    if _server is not None:
        return f"http://localhost:{port}/"
    _server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    _server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    thread = threading.Thread(target=_server.serve_forever, daemon=True)
    thread.start()
    return f"http://localhost:{port}/"
