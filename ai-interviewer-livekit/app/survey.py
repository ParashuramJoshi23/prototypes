"""Survey definitions: load YAML survey files into typed objects."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_SURVEYS_DIR = Path(__file__).resolve().parent.parent / "surveys"
DEFAULT_PERSONA = "a warm, professional interviewer named Riley"
DEFAULT_CLOSING = "Thank you for your time and thoughtful answers."


@dataclass
class Question:
    id: str
    text: str
    intent: str = ""


@dataclass
class Survey:
    id: str
    title: str
    description: str
    questions: list[Question]
    persona: str = DEFAULT_PERSONA
    closing: str = DEFAULT_CLOSING

    @property
    def num_questions(self) -> int:
        return len(self.questions)


def surveys_dir() -> Path:
    return Path(os.getenv("SURVEYS_DIR", DEFAULT_SURVEYS_DIR))


def _parse(data: dict) -> Survey:
    questions = [
        Question(id=q["id"], text=q["text"], intent=q.get("intent", ""))
        for q in data.get("questions", [])
    ]
    return Survey(
        id=data["id"],
        title=data["title"],
        description=data.get("description", ""),
        questions=questions,
        persona=data.get("persona", DEFAULT_PERSONA),
        closing=data.get("closing", DEFAULT_CLOSING),
    )


def load_survey(survey_id: str) -> Survey:
    path = surveys_dir() / f"{survey_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Survey '{survey_id}' not found at {path}")
    return _parse(yaml.safe_load(path.read_text()))


def list_surveys() -> list[Survey]:
    out: list[Survey] = []
    for path in sorted(surveys_dir().glob("*.yaml")):
        try:
            out.append(_parse(yaml.safe_load(path.read_text())))
        except Exception as exc:  # noqa: BLE001 — skip malformed files, keep the rest
            print(f"warning: skipping {path.name}: {exc}")
    return out
