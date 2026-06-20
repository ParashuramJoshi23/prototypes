"""Token + survey API and static web client host.

Endpoints:
  GET  /api/surveys          -> list available surveys
  POST /api/token            -> mint a LiveKit join token for a chosen survey
  GET  /api/results          -> all recorded interview results
  GET  /api/results/{room}   -> results for one interview room
  GET  /                     -> the browser client (web/index.html)

Run it:
    uvicorn app.token_server:app --reload --port 8000
"""
from __future__ import annotations

import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from livekit import api
from pydantic import BaseModel

from . import db, results
from .survey import list_surveys, load_survey

load_dotenv()

LIVEKIT_URL = os.getenv("LIVEKIT_URL")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    yield
    await db.close_db()


app = FastAPI(title="AI Interviewer (LiveKit)", lifespan=lifespan)


class TokenRequest(BaseModel):
    survey_id: str
    participant_name: str = "Guest"


@app.get("/api/surveys")
def get_surveys() -> list[dict]:
    return [
        {
            "id": s.id,
            "title": s.title,
            "description": s.description,
            "num_questions": s.num_questions,
        }
        for s in list_surveys()
    ]


@app.post("/api/token")
def create_token(req: TokenRequest) -> dict:
    if not (LIVEKIT_URL and LIVEKIT_API_KEY and LIVEKIT_API_SECRET):
        raise HTTPException(
            status_code=500,
            detail="LiveKit not configured. Set LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET.",
        )
    try:
        survey = load_survey(req.survey_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Unknown survey '{req.survey_id}'.")

    room = f"interview-{survey.id}-{uuid.uuid4().hex[:8]}"
    identity = f"{req.participant_name}-{uuid.uuid4().hex[:6]}"

    token = (
        api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        .with_identity(identity)
        .with_name(req.participant_name)
        # The agent reads survey_id from this metadata to pick which survey to run.
        .with_metadata(json.dumps({"survey_id": survey.id}))
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room,
                can_publish=True,
                can_subscribe=True,
            )
        )
        .to_jwt()
    )

    return {
        "server_url": LIVEKIT_URL,
        "token": token,
        "room": room,
        "identity": identity,
        "survey": {"id": survey.id, "title": survey.title, "num_questions": survey.num_questions},
    }


@app.get("/api/results")
async def all_results() -> list[dict]:
    return await results.list_all()


@app.get("/api/results/{room}")
async def room_results(room: str) -> dict:
    rec = await results.get(room)
    if rec is None:
        raise HTTPException(status_code=404, detail="No results recorded for that room yet.")
    return rec


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")
