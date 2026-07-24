import os
from twilio.rest import Client


def send_sms(to: str, body: str) -> str:
    """Sends an SMS and returns the message SID."""
    client = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])
    msg = client.messages.create(
        to=to,
        from_=os.environ["TWILIO_PHONE_NUMBER"],
        body=body,
    )
    return msg.sid
