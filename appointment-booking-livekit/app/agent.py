"""LiveKit voice agent that books appointments into Google Calendar.

Pipeline: Deepgram (speech-to-text) -> Claude (LLM, via livekit-plugins-anthropic)
-> Cartesia (text-to-speech), with Silero VAD and the multilingual turn detector.

Claude decides *what* to do (which day, which time, whether the caller said yes);
the function tools below are the only way it can touch the calendar, and each one
re-validates inputs and re-checks availability before writing. Think of Claude as
the receptionist and the tools as the locked appointment book it has to ask for.

Run it:
    python -m app.agent download-files   # one-time: fetch VAD + turn-detector models
    python -m app.agent dev              # connect to your LiveKit project and wait for calls
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

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

from .calendar_client import Appointment, CalendarClient, CalendarUnavailable
from .config import settings
from .prompts import build_instructions
from .slots import parse_local, spoken_date, spoken_time

load_dotenv()
logger = logging.getLogger("booking")

# One client per worker process; the Google service object is safe to reuse.
calendar = CalendarClient()


def _describe(appt: Appointment) -> str:
    return f"{spoken_date(appt.start)} at {spoken_time(appt.start)} (id {appt.event_id})"


def _validate_day(day_str: str) -> date | str:
    """Return a date, or a human-readable reason the LLM should relay/adjust."""
    try:
        day = date.fromisoformat(day_str)
    except ValueError:
        return f"'{day_str}' is not a valid ISO date (expected YYYY-MM-DD)."
    today = datetime.now(settings.tz).date()
    if day < today:
        return f"{day.isoformat()} is in the past. Today is {today.isoformat()}."
    if day > today + timedelta(days=settings.max_days_ahead):
        return f"We only book up to {settings.max_days_ahead} days ahead."
    if settings.hours.window_for(day) is None:
        return f"We are closed on {spoken_date(datetime.combine(day, datetime.min.time()))}."
    return day


class BookingAgent(Agent):
    def __init__(self, room_name: str) -> None:
        super().__init__(instructions=build_instructions(datetime.now(settings.tz)))
        self.room_name = room_name
        # Bookings made during *this* call, so a quick "actually, cancel that"
        # doesn't require a lookup round-trip.
        self.booked_this_call: dict[str, Appointment] = {}

    @function_tool()
    async def get_available_slots(self, context: RunContext, day: str) -> str:
        """List open appointment start times on a given day.

        Call this before offering any times to the caller. Offer at most three
        of the returned times at once.

        Args:
            day: The requested date in ISO format, YYYY-MM-DD (resolve phrases
                like "tomorrow" or "next Friday" to a concrete date first).
        """
        resolved = _validate_day(day)
        if isinstance(resolved, str):
            return resolved
        try:
            slots = await calendar.free_slots(resolved)
        except CalendarUnavailable as exc:
            logger.warning("calendar unavailable: %s", exc)
            return "The calendar system is unavailable right now."
        if not slots:
            return f"No free slots on {spoken_date(datetime.combine(resolved, datetime.min.time()))}."
        shown = slots[: settings.max_slots_to_offer]
        times = ", ".join(f"{spoken_time(s)} ({s.strftime('%H:%M')})" for s in shown)
        more = f" and {len(slots) - len(shown)} more later in the day" if len(slots) > len(shown) else ""
        return f"Free {settings.appointment_minutes}-minute slots on {resolved.isoformat()}: {times}{more}."

    @function_tool()
    async def book_appointment(
        self,
        context: RunContext,
        day: str,
        start_time: str,
        customer_name: str,
        customer_email: str | None = None,
        customer_phone: str | None = None,
        reason: str | None = None,
    ) -> str:
        """Create the appointment in the calendar.

        Only call this after reading the day, time, and name back to the caller
        and hearing an explicit yes. The slot is re-checked right before writing,
        so if someone else took it in the meantime you'll get alternatives back.

        Args:
            day: ISO date, YYYY-MM-DD.
            start_time: 24-hour start time, HH:MM, taken from get_available_slots.
            customer_name: The caller's full name as they gave it.
            customer_email: Email for the calendar invite, if the caller provided one.
            customer_phone: Phone number, if the caller provided one.
            reason: One short phrase describing the purpose of the visit, if given.
        """
        resolved = _validate_day(day)
        if isinstance(resolved, str):
            return resolved
        try:
            start = parse_local(day, start_time, settings.tz)
        except ValueError:
            return f"'{start_time}' is not a valid HH:MM time."
        if not customer_name.strip():
            return "A customer name is required before booking."

        try:
            if not await calendar.is_free(start):
                alternatives = await calendar.free_slots(resolved)
                alt = ", ".join(spoken_time(s) for s in alternatives[:3]) or "none"
                return (
                    f"That slot was just taken. Nearest alternatives on {resolved.isoformat()}: {alt}."
                )
            appt = await calendar.book(
                start,
                customer_name.strip(),
                customer_email=customer_email,
                customer_phone=customer_phone,
                reason=reason,
            )
        except CalendarUnavailable as exc:
            logger.warning("booking failed: %s", exc)
            return "The calendar system is unavailable right now; nothing was booked."

        self.booked_this_call[appt.event_id] = appt
        logger.info("booked %s for %s in room %s", appt.event_id, customer_name, self.room_name)
        invite = " A calendar invite has been sent." if customer_email and settings.calendar_invite_attendees else ""
        return f"Booked: {_describe(appt)} for {customer_name}.{invite}"

    @function_tool()
    async def find_appointments(self, context: RunContext, name_or_email: str) -> str:
        """Look up upcoming appointments for a caller by name or email.

        Args:
            name_or_email: The caller's name or email address to search for.
        """
        try:
            found = await calendar.upcoming(query=name_or_email.strip())
        except CalendarUnavailable as exc:
            logger.warning("lookup failed: %s", exc)
            return "The calendar system is unavailable right now."
        if not found:
            return f"No upcoming appointments found for '{name_or_email}'."
        lines = [f"{a.summary}: {_describe(a)}" for a in found[:5]]
        return "Upcoming appointments: " + "; ".join(lines)

    @function_tool()
    async def cancel_appointment(self, context: RunContext, event_id: str) -> str:
        """Cancel an appointment by its calendar event id.

        Get the id from find_appointments (or from a booking made earlier in
        this call). Read the appointment back and get a clear yes before calling.

        Args:
            event_id: The calendar event id of the appointment to cancel.
        """
        try:
            await calendar.cancel(event_id)
        except CalendarUnavailable as exc:
            logger.warning("cancel failed: %s", exc)
            return "The calendar system is unavailable right now; nothing was cancelled."
        appt = self.booked_this_call.pop(event_id, None)
        logger.info("cancelled %s in room %s", event_id, self.room_name)
        if appt:
            return f"Cancelled the appointment on {_describe(appt)}."
        return f"Cancelled appointment {event_id}."


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    participant = await ctx.wait_for_participant()
    logger.info("call from %s in room %s", participant.identity, ctx.room.name)

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=anthropic.LLM(model=settings.booking_model),
        tts=cartesia.TTS(),
        vad=silero.VAD.load(),
        turn_detection=MultilingualModel(),
    )

    await session.start(agent=BookingAgent(ctx.room.name), room=ctx.room)

    await session.generate_reply(
        instructions=(
            f"Greet the caller, say you're the receptionist at {settings.business_name}, "
            "and ask how you can help with their appointment today. One short sentence."
        )
    )


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
