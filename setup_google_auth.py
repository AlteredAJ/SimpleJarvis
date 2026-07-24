"""
Run this once to authorize Google Calendar access.
It opens a browser for OAuth and saves the token locally.

Usage: python setup_google_auth.py
"""
import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/calendar"]

creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "google_credentials.json")
token_file  = os.getenv("GOOGLE_TOKEN_FILE",       "google_token.json")

if not Path(creds_file).exists():
    print(f"ERROR: {creds_file} not found.")
    print("Download it from Google Cloud Console → APIs & Services → Credentials → OAuth 2.0 Client → Download JSON")
    raise SystemExit(1)

flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
creds = flow.run_local_server(port=0)
Path(token_file).write_text(creds.to_json())
print(f"Token saved to {token_file} — you're good to go.")
