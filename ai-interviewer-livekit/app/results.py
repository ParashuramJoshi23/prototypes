"""Results storage, backed by Postgres (asyncpg).

Two tables: ``interviews`` (one row per room) and ``answers`` (one row per
recorded answer). The agent worker writes; the token server reads. All
functions are async and use the shared pool from ``app.db``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from .db import get_pool


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


async def start_session(
    room: str, survey_id: str, survey_title: str, participant: str
) -> None:
    await get_pool().execute(
        """
        INSERT INTO interviews (room, survey_id, survey_title, participant)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (room) DO NOTHING
        """,
        room,
        survey_id,
        survey_title,
        participant,
    )


async def record_answer(
    room: str,
    question_id: str,
    question_text: str,
    answer: str,
    sentiment: Optional[str] = None,
) -> None:
    await get_pool().execute(
        """
        INSERT INTO answers (room, question_id, question_text, answer, sentiment)
        VALUES ($1, $2, $3, $4, $5)
        """,
        room,
        question_id,
        question_text,
        answer,
        sentiment,
    )


async def complete(room: str) -> None:
    await get_pool().execute(
        "UPDATE interviews SET completed_at = NOW() WHERE room = $1", room
    )


def _interview_dict(row: Any, answers: list[Any]) -> dict:
    return {
        "room": row["room"],
        "survey_id": row["survey_id"],
        "survey_title": row["survey_title"],
        "participant": row["participant"],
        "started_at": _iso(row["started_at"]),
        "completed_at": _iso(row["completed_at"]),
        "answers": [
            {
                "question_id": a["question_id"],
                "question_text": a["question_text"],
                "answer": a["answer"],
                "sentiment": a["sentiment"],
                "recorded_at": _iso(a["recorded_at"]),
            }
            for a in answers
        ],
    }


async def get(room: str) -> Optional[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM interviews WHERE room = $1", room)
        if row is None:
            return None
        answers = await conn.fetch(
            "SELECT * FROM answers WHERE room = $1 ORDER BY recorded_at, id", room
        )
        return _interview_dict(row, answers)


async def list_all() -> list[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM interviews ORDER BY started_at DESC")
        answers = await conn.fetch("SELECT * FROM answers ORDER BY recorded_at, id")
    grouped: dict[str, list] = {}
    for a in answers:
        grouped.setdefault(a["room"], []).append(a)
    return [_interview_dict(r, grouped.get(r["room"], [])) for r in rows]
