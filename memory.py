import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path("jarvis.db")


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                call_sid TEXT PRIMARY KEY,
                caller   TEXT NOT NULL,
                client   TEXT NOT NULL,
                started  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                call_sid TEXT NOT NULL,
                role     TEXT NOT NULL,
                content  TEXT NOT NULL,
                ts       TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bookings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                call_sid    TEXT NOT NULL,
                caller      TEXT,
                service     TEXT,
                staff       TEXT,
                event_id    TEXT,
                start_time  TEXT,
                created_at  TEXT NOT NULL
            );
        """)


def start_session(call_sid: str, caller: str, client: str) -> None:
    with _conn() as con:
        con.execute(
            "INSERT OR IGNORE INTO sessions VALUES (?,?,?,?)",
            (call_sid, caller, client, datetime.utcnow().isoformat()),
        )


def append_message(call_sid: str, role: str, content) -> None:
    text = content if isinstance(content, str) else json.dumps(content)
    with _conn() as con:
        con.execute(
            "INSERT INTO messages (call_sid, role, content, ts) VALUES (?,?,?,?)",
            (call_sid, role, text, datetime.utcnow().isoformat()),
        )


def get_history(call_sid: str) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT role, content FROM messages WHERE call_sid=? ORDER BY id",
            (call_sid,),
        ).fetchall()
    messages = []
    for row in rows:
        try:
            content = json.loads(row["content"])
        except (json.JSONDecodeError, TypeError):
            content = row["content"]
        messages.append({"role": row["role"], "content": content})
    return messages


def record_booking(call_sid: str, caller: str, service: str, staff: str,
                   event_id: str, start_time: str) -> None:
    with _conn() as con:
        con.execute(
            "INSERT INTO bookings (call_sid,caller,service,staff,event_id,start_time,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (call_sid, caller, service, staff, event_id, start_time,
             datetime.utcnow().isoformat()),
        )


def get_recent_bookings(client: str, limit: int = 20) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            """SELECT b.*, s.caller, s.client FROM bookings b
               JOIN sessions s ON b.call_sid = s.call_sid
               WHERE s.client = ? ORDER BY b.created_at DESC LIMIT ?""",
            (client, limit),
        ).fetchall()
    return [dict(r) for r in rows]
