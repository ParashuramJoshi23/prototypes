"""CalendarClient against a fake Google service: checks request bodies and
response parsing without touching the network or needing credentials."""
import asyncio
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from app import calendar_client as cc
from app.config import settings

TZ = ZoneInfo("America/New_York")


class _Call:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class FakeService:
    """Records every call and replays canned responses."""

    def __init__(self, busy=None, items=None):
        self.calls: list[tuple[str, dict]] = []
        self._busy = busy or []
        self._items = items or []

    def freebusy(self):
        svc = self

        class FB:
            def query(self, body):
                svc.calls.append(("freebusy", body))
                return _Call({"calendars": {settings.google_calendar_id: {"busy": svc._busy}}})

        return FB()

    def events(self):
        svc = self

        class EV:
            def list(self, **kw):
                svc.calls.append(("list", kw))
                return _Call({"items": svc._items})

            def insert(self, calendarId, body, sendUpdates):
                svc.calls.append(("insert", {"calendarId": calendarId, "body": body, "sendUpdates": sendUpdates}))
                return _Call({"id": "evt123", "summary": body["summary"], "start": body["start"], "end": body["end"], "htmlLink": "http://x"})

            def delete(self, calendarId, eventId, sendUpdates):
                svc.calls.append(("delete", {"calendarId": calendarId, "eventId": eventId}))
                return _Call(None)

        return EV()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "business_timezone", "America/New_York")
    monkeypatch.setattr(settings, "business_open", "09:00")
    monkeypatch.setattr(settings, "business_close", "12:00")
    monkeypatch.setattr(settings, "slot_minutes", 30)
    monkeypatch.setattr(settings, "appointment_minutes", 30)
    monkeypatch.setattr(settings, "min_lead_minutes", 0)
    c = cc.CalendarClient()
    return c


def _wire(client, fake):
    client._service = fake
    return fake


def test_free_slots_uses_business_window_and_drops_busy(client):
    # Google returns UTC instants; 14:00–14:30Z == 10:00–10:30 New York in September.
    fake = _wire(client, FakeService(busy=[{"start": "2026-09-21T14:00:00Z", "end": "2026-09-21T14:30:00Z"}]))
    now = datetime(2026, 9, 20, 8, 0, tzinfo=TZ)
    slots = asyncio.run(client.free_slots(date(2026, 9, 21), now=now))

    name, body = fake.calls[0]
    assert name == "freebusy"
    assert body["timeMin"] == "2026-09-21T09:00:00-04:00"
    assert body["timeMax"] == "2026-09-21T12:00:00-04:00"
    assert body["items"] == [{"id": settings.google_calendar_id}]
    assert [s.strftime("%H:%M") for s in slots] == ["09:00", "09:30", "10:30", "11:00", "11:30"]


def test_free_slots_on_closed_day_skips_google(client):
    fake = _wire(client, FakeService())
    assert asyncio.run(client.free_slots(date(2026, 9, 20))) == []  # Sunday
    assert fake.calls == []


def test_book_builds_event_and_invites_when_email_given(client, monkeypatch):
    monkeypatch.setattr(settings, "calendar_invite_attendees", True)
    fake = _wire(client, FakeService())
    start = datetime.combine(date(2026, 9, 21), time(10, 30), tzinfo=TZ)
    appt = asyncio.run(client.book(start, "Ada Lovelace", customer_email="ada@example.com", reason="cleaning"))

    name, call = fake.calls[0]
    assert name == "insert"
    body = call["body"]
    assert body["start"] == {"dateTime": "2026-09-21T10:30:00-04:00", "timeZone": "America/New_York"}
    assert body["end"]["dateTime"] == "2026-09-21T11:00:00-04:00"
    assert body["attendees"] == [{"email": "ada@example.com", "displayName": "Ada Lovelace"}]
    assert call["sendUpdates"] == "all"
    assert "Reason: cleaning" in body["description"]
    assert body["extendedProperties"]["private"]["booked_by"] == "livekit-agent"
    assert appt.event_id == "evt123" and appt.start == start


def test_book_without_invites_for_service_accounts(client, monkeypatch):
    monkeypatch.setattr(settings, "calendar_invite_attendees", False)
    fake = _wire(client, FakeService())
    start = datetime.combine(date(2026, 9, 21), time(10, 30), tzinfo=TZ)
    asyncio.run(client.book(start, "Ada", customer_email="ada@example.com"))
    _, call = fake.calls[0]
    assert "attendees" not in call["body"]
    assert call["sendUpdates"] == "none"
    assert "ada@example.com" in call["body"]["description"]


def test_upcoming_parses_timed_events_and_skips_all_day(client):
    fake = _wire(client, FakeService(items=[
        {"id": "a", "summary": "Northside Dental: Ada", "start": {"dateTime": "2026-09-21T14:00:00Z"}, "end": {"dateTime": "2026-09-21T14:30:00Z"}},
        {"id": "b", "summary": "Holiday", "start": {"date": "2026-09-22"}, "end": {"date": "2026-09-23"}},
    ]))
    found = asyncio.run(client.upcoming(query="Ada"))
    _, kw = fake.calls[0]
    assert kw["q"] == "Ada" and kw["singleEvents"] is True and kw["orderBy"] == "startTime"
    assert [a.event_id for a in found] == ["a"]
    assert found[0].start.strftime("%H:%M %Z") == "10:00 EDT"


def test_cancel_treats_missing_event_as_done(client):
    class Resp:
        status = 404
        reason = "Not Found"

    class Gone(FakeService):
        def events(self):
            class EV:
                def delete(self, **kw):
                    raise cc.HttpError(Resp(), b"gone")
            return EV()

    _wire(client, Gone())
    asyncio.run(client.cancel("nope"))  # must not raise


def test_freebusy_calendar_error_surfaces_as_unavailable(client):
    class Broken(FakeService):
        def freebusy(self):
            class FB:
                def query(self, body):
                    return _Call({"calendars": {settings.google_calendar_id: {"errors": [{"reason": "notFound"}]}}})
            return FB()

    _wire(client, Broken())
    with pytest.raises(cc.CalendarUnavailable):
        asyncio.run(client.free_slots(date(2026, 9, 21)))
