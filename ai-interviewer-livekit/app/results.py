"""Results storage.

One JSON file per interview room under ``data/results/<room>.json``. The agent
process is the only writer for a given room; the token server only reads. That
makes cross-process coordination trivial for a prototype — no database needed.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_lock = threading.Lock()


def _results_dir() -> Path:
    d = Path(os.getenv("DATA_DIR", DEFAULT_DATA_DIR)) / "results"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(room: str) -> Path:
    # Room names are server-generated (interview-<survey>-<hex>); guard anyway.
    safe = "".join(c for c in room if c.isalnum() or c in "-_")
    return _results_dir() / f"{safe}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read(room: str) -> Optional[dict[str, Any]]:
    path = _path(room)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _write(room: str, rec: dict[str, Any]) -> None:
    _path(room).write_text(json.dumps(rec, indent=2))


def start_session(room: str, survey_id: str, survey_title: str, participant: str) -> dict:
    with _lock:
        rec = {
            "room": room,
            "survey_id": survey_id,
            "survey_title": survey_title,
            "participant": participant,
            "started_at": _now(),
            "completed_at": None,
            "answers": [],
        }
        _write(room, rec)
        return rec


def record_answer(
    room: str,
    question_id: str,
    question_text: str,
    answer: str,
    sentiment: Optional[str] = None,
) -> None:
    with _lock:
        rec = _read(room) or {
            "room": room,
            "started_at": _now(),
            "completed_at": None,
            "answers": [],
        }
        rec.setdefault("answers", []).append(
            {
                "question_id": question_id,
                "question_text": question_text,
                "answer": answer,
                "sentiment": sentiment,
                "recorded_at": _now(),
            }
        )
        _write(room, rec)


def complete(room: str) -> None:
    with _lock:
        rec = _read(room)
        if rec is not None:
            rec["completed_at"] = _now()
            _write(room, rec)


def get(room: str) -> Optional[dict]:
    with _lock:
        return _read(room)


def list_all() -> list[dict]:
    with _lock:
        out = []
        for path in sorted(_results_dir().glob("*.json")):
            try:
                out.append(json.loads(path.read_text()))
            except Exception:  # noqa: BLE001
                continue
        out.sort(key=lambda r: r.get("started_at", ""), reverse=True)
        return out
