"""Unit tests for the pure slot arithmetic (no Google, no LiveKit)."""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.slots import BusinessHours, Interval, compute_free_slots, parse_local, spoken_date, spoken_time

TZ = ZoneInfo("America/New_York")
HOURS = BusinessHours(open_time=time(9, 0), close_time=time(12, 0), tz=TZ)
MONDAY = date(2026, 9, 21)


def at(hh: int, mm: int = 0, day: date = MONDAY) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=TZ)


def test_empty_calendar_yields_every_slot():
    slots = compute_free_slots(MONDAY, [], HOURS, slot_minutes=30, duration_minutes=30)
    assert slots == [at(9), at(9, 30), at(10), at(10, 30), at(11), at(11, 30)]


def test_busy_block_removes_overlapping_slots():
    busy = [Interval(at(9, 45), at(10, 15))]  # straddles 9:30 and 10:00 slots
    slots = compute_free_slots(MONDAY, busy, HOURS, 30, 30)
    assert slots == [at(9), at(10, 30), at(11), at(11, 30)]


def test_busy_in_other_timezone_is_compared_as_instant():
    # 13:45–14:15 UTC == 09:45–10:15 New York (EDT)
    utc = ZoneInfo("UTC")
    busy = [Interval(datetime(2026, 9, 21, 13, 45, tzinfo=utc), datetime(2026, 9, 21, 14, 15, tzinfo=utc))]
    slots = compute_free_slots(MONDAY, busy, HOURS, 30, 30)
    assert at(9, 30) not in slots and at(10) not in slots
    assert at(9) in slots


def test_longer_appointment_than_grid_needs_room_before_close():
    slots = compute_free_slots(MONDAY, [], HOURS, slot_minutes=30, duration_minutes=60)
    assert slots[-1] == at(11)  # 11:30 + 60 min would run past noon


def test_closed_day_has_no_slots():
    sunday = date(2026, 9, 20)
    assert compute_free_slots(sunday, [], HOURS, 30, 30) == []


def test_now_and_lead_time_drop_past_slots():
    now = at(9, 40)
    slots = compute_free_slots(MONDAY, [], HOURS, 30, 30, now=now, min_lead_minutes=30)
    # earliest bookable = 10:10, so first offered slot is 10:30
    assert slots == [at(10, 30), at(11), at(11, 30)]


def test_now_in_other_timezone():
    now_utc = datetime(2026, 9, 21, 14, 0, tzinfo=ZoneInfo("UTC"))  # 10:00 NY
    slots = compute_free_slots(MONDAY, [], HOURS, 30, 30, now=now_utc)
    assert slots[0] == at(10)


def test_adjacent_busy_block_does_not_touch_neighbours():
    busy = [Interval(at(10), at(10, 30))]
    slots = compute_free_slots(MONDAY, busy, HOURS, 30, 30)
    assert at(9, 30) in slots and at(10, 30) in slots and at(10) not in slots


def test_parse_local_and_spoken_helpers():
    dt = parse_local("2026-09-21", "14:05", TZ)
    assert dt == at(14, 5)
    assert spoken_time(dt) == "2:05 PM"
    assert spoken_date(dt) == "Monday, September 21"


def test_parse_local_rejects_garbage():
    with pytest.raises(ValueError):
        parse_local("2026-09-21", "2pm", TZ)
