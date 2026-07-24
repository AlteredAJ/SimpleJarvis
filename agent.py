import json
import os
from datetime import datetime

import anthropic

from memory import append_message, get_history
from tools.calendar import check_availability, book_appointment
from tools.sms import send_sms
from tools.config import get_business_info

_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

TOOLS = [
    {
        "name": "check_availability",
        "description": (
            "Check open appointment slots on a given date. "
            "Use this when the caller asks about availability or wants to book."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format",
                },
                "duration_minutes": {
                    "type": "integer",
                    "description": "Length of the appointment in minutes",
                    "default": 60,
                },
            },
            "required": ["date"],
        },
    },
    {
        "name": "book_appointment",
        "description": "Book an appointment on the calendar after the caller confirms a time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary":      {"type": "string", "description": "Event title, e.g. 'Haircut — Marcus'"},
                "start_iso":    {"type": "string", "description": "Start time in ISO 8601 format"},
                "end_iso":      {"type": "string", "description": "End time in ISO 8601 format"},
                "caller_name":  {"type": "string", "description": "Caller's name"},
                "caller_phone": {"type": "string", "description": "Caller's phone number"},
                "description":  {"type": "string", "description": "Service or notes"},
            },
            "required": ["summary", "start_iso", "end_iso"],
        },
    },
    {
        "name": "send_confirmation_sms",
        "description": "Send an SMS confirmation to the caller after booking.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to":   {"type": "string", "description": "Caller's phone number in E.164 format"},
                "body": {"type": "string", "description": "Message text"},
            },
            "required": ["to", "body"],
        },
    },
    {
        "name": "request_human_callback",
        "description": (
            "Use when the caller asks to speak to a human, has a complaint, "
            "or the request is too complex to handle. Logs the request for a callback."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason":      {"type": "string", "description": "Why a human is needed"},
                "caller_name": {"type": "string"},
                "caller_phone": {"type": "string"},
            },
            "required": ["reason"],
        },
    },
]


def _build_system_prompt(config: dict) -> list[dict]:
    business_info = get_business_info(config)
    today = datetime.now().strftime("%A, %B %d, %Y")
    greeting_name = config.get("agent_name", "the front desk assistant")
    business_name = config["name"]

    prompt_text = f"""You are {greeting_name}, the AI front desk assistant for {business_name}.
Today is {today}.

Your job is to answer calls professionally, answer questions about the business, and book appointments.
Always be warm, concise, and helpful. You are speaking on a phone call — keep responses short and natural.
Do not read out long lists. Offer 2-3 options at a time.

When booking:
1. Ask what service they want
2. Ask their preferred date
3. Check availability with check_availability
4. Offer up to 3 time slots
5. Confirm their name and phone
6. Book with book_appointment
7. Send an SMS confirmation with send_confirmation_sms

If the caller asks to speak to a human or you cannot help, use request_human_callback.

{business_info}
"""
    return [
        {
            "type": "text",
            "text": prompt_text,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def _dispatch_tool(name: str, inputs: dict, call_sid: str, caller: str) -> str:
    if name == "check_availability":
        slots = check_availability(
            inputs["date"], inputs.get("duration_minutes", 60)
        )
        if not slots:
            return "No open slots found on that date."
        labels = ", ".join(s["label"] for s in slots)
        return f"Available times on {inputs['date']}: {labels}"

    if name == "book_appointment":
        result = book_appointment(
            summary=inputs["summary"],
            start_iso=inputs["start_iso"],
            end_iso=inputs["end_iso"],
            caller_name=inputs.get("caller_name", ""),
            caller_phone=inputs.get("caller_phone", caller),
            description=inputs.get("description", ""),
        )
        from memory import record_booking
        record_booking(
            call_sid=call_sid,
            caller=caller,
            service=inputs.get("description", inputs["summary"]),
            staff="",
            event_id=result["event_id"],
            start_time=inputs["start_iso"],
        )
        return f"Appointment booked. Event ID: {result['event_id']}"

    if name == "send_confirmation_sms":
        sid = send_sms(inputs["to"], inputs["body"])
        return f"SMS sent (SID: {sid})"

    if name == "request_human_callback":
        return (
            f"Callback request logged: {inputs['reason']}. "
            f"Staff will call {inputs.get('caller_phone', caller)} back shortly."
        )

    return f"Unknown tool: {name}"


def process_speech(
    call_sid: str,
    caller: str,
    speech_text: str,
    config: dict,
) -> str:
    """
    Takes caller's speech, runs it through Claude with tool use,
    and returns the text response to speak back.
    """
    append_message(call_sid, "user", speech_text)
    history = get_history(call_sid)

    system = _build_system_prompt(config)

    # Agentic loop — keeps going until Claude stops calling tools
    messages = history
    while True:
        response = _client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system=system,
            tools=TOOLS,
            messages=messages,
        )

        # Collect any text blocks for the final spoken reply
        text_parts = [b.text for b in response.content if b.type == "text"]

        if response.stop_reason != "tool_use":
            reply = " ".join(text_parts).strip()
            append_message(call_sid, "assistant", reply)
            return reply

        # Process tool calls
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result_text = _dispatch_tool(block.name, block.input, call_sid, caller)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result_text,
            })

        # Feed tool results back and loop
        messages = messages + [
            {"role": "assistant", "content": response.content},
            {"role": "user",      "content": tool_results},
        ]
