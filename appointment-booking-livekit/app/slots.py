"""Pure slot arithmetic: turn a day's busy blocks into bookable start times.

Nothing here touches the network, so it's the part that gets unit-tested. The
calendar client feeds it busy intervals (from Google's freebusy endpoint) and
the agent turns the result into speech.

Mental model: business hours are a ruler marked every ``slot_minutes``; a slot
is bookable when the whole tick (start -> start + duration) is inside hours,
in the future, and doesn't overlap any busy block.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime

    def overlaps(self, other: "Interval") -> bool:
        return self.start < other.end and other.start < self.end


@dataclass(frozen=True)
class BusinessHours:
    open_time: time
    close_time: time
    tz: ZoneInfo
    # ISO weekday numbers (1 = Monday ... 7 = Sunday) on which bookings are taken.
    weekdays: frozenset[int] = frozenset({1, 2, 3, 4, 5})

    def window_for(self, day: date) -> Interval | None:
        """The open->close interval on ``day`` (tz-aware), or None if closed."""
        if day.isoweekday() not in self.weekdays:
            return None
        return Interval(
            datetime.combine(day, self.open_time, tzinfo=self.tz),
            datetime.combine(day, self.close_time, tzinfo=self.tz),
        )


def compute_free_slots(
    day: date,
    busy: list[Interval],
    hours: BusinessHours,
    slot_minutes: int,
    duration_minutes: int,
    now: datetime | None = None,
    min_lead_minutes: int = 0,
) -> list[datetime]:
    """Return bookable slot start times on ``day``, in the business timezone.

    ``busy`` intervals may be in any timezone; they're compared as absolute instants.
    Slots that begin before ``now + min_lead_minutes`` are dropped so the agent
    never offers a time that's already passed (or is about to).
    """
    window = hours.window_for(day)
    if window is None:
        return []

    earliest = None
    if now is not None:
        earliest = now.astimezone(hours.tz) + timedelta(minutes=min_lead_minutes)

    step = timedelta(minutes=slot_minutes)
    length = timedelta(minutes=duration_minutes)
    free: list[datetime] = []
    cursor = window.start
    while cursor + length <= window.end:
        candidate = Interval(cursor, cursor + length)
        if (earliest is None or cursor >= earliest) and not any(
            candidate.overlaps(b) for b in busy
        ):
            free.append(cursor)
        cursor += step
    return free


def parse_local(day: str, hhmm: str, tz: ZoneInfo) -> datetime:
    """Combine ``YYYY-MM-DD`` and ``HH:MM`` strings into a tz-aware datetime."""
    return datetime.combine(date.fromisoformat(day), time.fromisoformat(hhmm), tzinfo=tz)


def spoken_time(dt: datetime) -> str:
    """'2:30 PM' style, the way a receptionist would say it (no leading zero)."""
    return dt.strftime("%I:%M %p").lstrip("0")


def spoken_date(dt: datetime) -> str:
    """'Tuesday, September 22' — no year, no ordinal; TTS reads this cleanly."""
    return dt.strftime("%A, %B ") + str(dt.day)
