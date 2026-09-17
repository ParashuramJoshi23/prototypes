"""One-time OAuth consent flow for the booking calendar.

Opens a browser, asks you to grant Calendar access, and writes a refreshable
token to GOOGLE_OAUTH_TOKEN_FILE (default credentials/token.json). After this
the agent can run unattended; the token refreshes itself.

Prereq: download an OAuth "Desktop app" client from Google Cloud Console and
save it to GOOGLE_OAUTH_CLIENT_SECRET_FILE (default credentials/client_secret.json).

    python scripts/authorize_google.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

from app.calendar_client import SCOPES  # noqa: E402
from app.config import settings  # noqa: E402


def main() -> None:
    secret = Path(settings.google_oauth_client_secret_file)
    if not secret.exists():
        sys.exit(f"Client secret not found at {secret}. Download it from Google Cloud Console first.")
    flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
    creds = flow.run_local_server(port=0)
    out = Path(settings.google_oauth_token_file)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(creds.to_json())
    print(f"Saved token to {out}. The agent will now use calendar '{settings.google_calendar_id}'.")


if __name__ == "__main__":
    main()
