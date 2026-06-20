"""LiveKit voice agent that conducts a survey as a spoken interview.

Pipeline: Deepgram (speech-to-text) -> Claude (LLM, via livekit-plugins-anthropic)
-> Cartesia (text-to-speech), with Silero VAD and the multilingual turn detector.

The survey to run is selected per call: the token server puts ``{"survey_id": ...}``
in the participant's token metadata, and this worker reads it on connect.

Run it:
    python -m app.agent download-files   # one-time: fetch VAD + turn-detector models
    python -m app.agent dev              # connect to your LiveKit project and wait for calls
"""
from __future__ import annotations

import json
import logging
import os

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    RunContext,
    WorkerOptions,
    cli,
    function_tool,
)
from livekit.plugins import anthropic, cartesia, deepgram, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from . import results
from .prompts import build_instructions
from .survey import Survey, list_surveys, load_survey

load_dotenv()
logger = logging.getLogger("interviewer")

# Default per repo guidance; override with INTERVIEWER_MODEL. For latency- or
# cost-sensitive voice use, claude-sonnet-4-6 or claude-haiku-4-5 respond faster.
MODEL = os.getenv("INTERVIEWER_MODEL", "claude-opus-4-8")


class InterviewAgent(Agent):
    def __init__(self, survey: Survey, room_name: str) -> None:
        super().__init__(instructions=build_instructions(survey))
        self.survey = survey
        self.room_name = room_name
        self._by_id = {q.id: q for q in survey.questions}

    @function_tool()
    async def record_answer(
        self,
        context: RunContext,
        question_id: str,
        answer: str,
        sentiment: str = "neutral",
    ) -> str:
        """Save the participant's answer to one survey question.

        Call this right after the participant has finished answering a question
        (including any follow-up clarification), before asking the next one.

        Args:
            question_id: The id of the question being answered (from the survey list).
            answer: A concise summary, in the participant's own words, of their answer.
            sentiment: Overall tone of the answer: positive, neutral, or negative.
        """
        question = self._by_id.get(question_id)
        results.record_answer(
            self.room_name,
            question_id,
            question.text if question else question_id,
            answer,
            sentiment,
        )
        logger.info("recorded answer for %s in room %s", question_id, self.room_name)
        return f"Recorded answer for {question_id}."

    @function_tool()
    async def complete_interview(self, context: RunContext) -> str:
        """Mark the interview complete.

        Call this once every survey question has been asked and recorded, just
        before you deliver the closing line and say goodbye.
        """
        results.complete(self.room_name)
        logger.info("interview complete for room %s", self.room_name)
        return "Interview recorded as complete."


def _resolve_survey(metadata: str | None) -> Survey:
    survey_id = None
    if metadata:
        try:
            survey_id = json.loads(metadata).get("survey_id")
        except (ValueError, AttributeError):
            survey_id = None
    if survey_id:
        return load_survey(survey_id)
    surveys = list_surveys()
    if not surveys:
        raise RuntimeError("No surveys found in the surveys/ directory.")
    logger.warning("no survey_id in participant metadata; defaulting to %s", surveys[0].id)
    return surveys[0]


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    participant = await ctx.wait_for_participant()
    survey = _resolve_survey(participant.metadata)
    logger.info("starting survey '%s' in room %s", survey.id, ctx.room.name)
    results.start_session(ctx.room.name, survey.id, survey.title, participant.identity)

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=anthropic.LLM(model=MODEL),
        tts=cartesia.TTS(),
        vad=silero.VAD.load(),
        turn_detection=MultilingualModel(),
    )

    await session.start(
        agent=InterviewAgent(survey, ctx.room.name),
        room=ctx.room,
    )

    await session.generate_reply(
        instructions=(
            f"Greet the participant, introduce yourself as {survey.persona}, and explain "
            f"in one sentence that this is a short voice survey of {survey.num_questions} "
            f"questions about '{survey.title}'. Then ask the very first question. Keep it brief."
        )
    )


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
