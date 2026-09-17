"""Token API and static web client host.

Endpoints:
  POST /api/token          -> mint a LiveKit join token for a new call
  GET  /api/appointments   -> upcoming events on the booking calendar (to verify a call worked)
  GET  /                   -> the browser client (web/index.html)

Run it:
    uvicorn app.token_server:app --reload --port 8000
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from livekit import api
from pydantic import BaseModel

from .calendar_client import CalendarClient, CalendarUnavailable
from .config import settings

load_dotenv()

LIVEKIT_URL = os.getenv("LIVEKIT_URL")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="Appointment Booking Agent (LiveKit)")
calendar = CalendarClient()


class TokenRequest(BaseModel):
    participant_name: str = "Caller"


@app.post("/api/token")
def create_token(req: TokenRequest) -> dict:
    if not (LIVEKIT_URL and LIVEKIT_API_KEY and LIVEKIT_API_SECRET):
        raise HTTPException(
            status_code=500,
            detail="LiveKit not configured. Set LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET.",
        )
    room = f"booking-{uuid.uuid4().hex[:8]}"
    identity = f"{req.participant_name}-{uuid.uuid4().hex[:6]}"
    token = (
        api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        .with_identity(identity)
        .with_name(req.participant_name)
        .with_grants(api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True))
        .to_jwt()
    )
    return {
        "server_url": LIVEKIT_URL,
        "token": token,
        "room": room,
        "identity": identity,
        "business": settings.business_name,
    }


@app.get("/api/appointments")
async def upcoming_appointments(days: int = 7) -> list[dict]:
    try:
        found = await calendar.upcoming(days=days)
    except CalendarUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return [
        {
            "event_id": a.event_id,
            "summary": a.summary,
            "start": a.start.isoformat(),
            "end": a.end.isoformat(),
            "link": a.html_link,
            "description": a.description,
        }
        for a in found
    ]


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")
