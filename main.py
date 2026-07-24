import os
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Form, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from twilio.twiml.voice_response import VoiceResponse, Gather, Play

import memory
from agent import process_speech
from tools.config import load_config
from tools.tts import speak

app = FastAPI(title="Jarvis AI Front Desk")
memory.init_db()

# Serve generated audio files so Twilio can <Play> them
app.mount("/static", StaticFiles(directory="static"), name="static")

CONFIG_PATH = os.getenv("CLIENT_CONFIG", "config/demo.yaml")
BASE_URL    = os.getenv("BASE_URL", "http://localhost:8000")


def _config() -> dict:
    return load_config(CONFIG_PATH)


def _play_url(filename: str) -> str:
    return f"{BASE_URL}/static/audio/{filename}"


# ---------------------------------------------------------------------------
# Twilio voice webhooks
# ---------------------------------------------------------------------------

@app.post("/voice/inbound")
async def inbound_call(
    CallSid: str = Form(...),
    From:    str = Form(...),
):
    """Twilio calls this when a new call comes in."""
    config = _config()
    memory.start_session(CallSid, From, config["name"])

    greeting = config.get(
        "greeting",
        f"Thank you for calling {config['name']}. How can I help you today?",
    )

    audio_file = speak(greeting, voice_id=config.get("voice_id"))

    vr = VoiceResponse()
    gather = Gather(
        input="speech",
        action=f"{BASE_URL}/voice/respond",
        method="POST",
        speech_timeout="auto",
        language="en-US",
    )
    gather.append(Play(_play_url(audio_file)))
    vr.append(gather)
    vr.redirect(f"{BASE_URL}/voice/no-input")

    return Response(content=str(vr), media_type="application/xml")


@app.post("/voice/respond")
async def respond(
    CallSid:      str = Form(...),
    From:         str = Form(...),
    SpeechResult: str = Form(default=""),
    Confidence:   str = Form(default=""),
):
    """Processes caller speech and plays the AI reply."""
    config = _config()
    speech = SpeechResult.strip()

    if not speech:
        return await _gather_again(config, "I didn't catch that. Could you say that again?")

    reply = process_speech(CallSid, From, speech, config)

    # Handoff — speak the message then hang up
    if "callback" in reply.lower() and "staff" in reply.lower():
        audio_file = speak(reply, voice_id=config.get("voice_id"))
        vr = VoiceResponse()
        vr.append(Play(_play_url(audio_file)))
        vr.hangup()
        return Response(content=str(vr), media_type="application/xml")

    return await _gather_again(config, reply)


@app.post("/voice/no-input")
async def no_input():
    config = _config()
    audio_file = speak(
        "I didn't hear anything. Feel free to call back when you're ready. Goodbye!",
        voice_id=config.get("voice_id"),
    )
    vr = VoiceResponse()
    vr.append(Play(_play_url(audio_file)))
    vr.hangup()
    return Response(content=str(vr), media_type="application/xml")


async def _gather_again(config: dict, text: str) -> Response:
    audio_file = speak(text, voice_id=config.get("voice_id"))
    vr = VoiceResponse()
    gather = Gather(
        input="speech",
        action=f"{BASE_URL}/voice/respond",
        method="POST",
        speech_timeout="auto",
        language="en-US",
    )
    gather.append(Play(_play_url(audio_file)))
    vr.append(gather)
    vr.redirect(f"{BASE_URL}/voice/no-input")
    return Response(content=str(vr), media_type="application/xml")


# ---------------------------------------------------------------------------
# Admin dashboard
# ---------------------------------------------------------------------------

@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard():
    config  = _config()
    bookings = memory.get_recent_bookings(config["name"])

    rows = ""
    for b in bookings:
        rows += (
            f"<tr>"
            f"<td>{b.get('start_time', '')[:16].replace('T', ' ')}</td>"
            f"<td>{b.get('service', '')}</td>"
            f"<td>{b.get('caller', '')}</td>"
            f"<td>{b.get('event_id', '')[:12]}...</td>"
            f"</tr>"
        )

    html = f"""<!DOCTYPE html>
<html>
<head>
  <title>{config['name']} — AI Front Desk Admin</title>
  <style>
    body {{ font-family: system-ui; max-width: 900px; margin: 40px auto; padding: 0 20px; }}
    h1 {{ font-size: 1.4rem; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
    th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid #e5e7eb; font-size: 0.9rem; }}
    th {{ background: #f9fafb; font-weight: 600; }}
    .badge {{ background: #dcfce7; color: #166534; padding: 2px 8px; border-radius: 9999px; font-size: 0.75rem; }}
  </style>
</head>
<body>
  <h1>{config['name']} <span class="badge">AI Front Desk</span></h1>
  <p style="color:#6b7280">Recent bookings — {datetime.now().strftime('%b %d, %Y')}</p>
  <table>
    <thead><tr><th>Time</th><th>Service</th><th>Caller</th><th>Event ID</th></tr></thead>
    <tbody>{rows if rows else '<tr><td colspan="4" style="color:#9ca3af">No bookings yet.</td></tr>'}</tbody>
  </table>
</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "client": _config().get("name")}
