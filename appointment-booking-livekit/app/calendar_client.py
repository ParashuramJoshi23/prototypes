"""Thin async wrapper around the Google Calendar v3 API.

The official ``google-api-python-client`` is synchronous (it blocks on HTTP),
so every call is pushed onto a worker thread with ``asyncio.to_thread`` to
keep the voice pipeline's event loop free. Think of it as a receptionist who
puts the caller on hold for a second while flipping through the paper diary.

Two ways to authenticate (``GOOGLE_AUTH_MODE``):
  * ``oauth``            – act as a real Google user. Run ``scripts/authorize_google.py``
                           once to produce ``token.json``; it refreshes itself after that.
  * ``service_account``  – act as a robot identity. Share the target calendar with
                           the service account's email ("Make changes to events").

Quick check from the shell (prints tomorrow's free slots):
    python -m app.calendar_client
    python -m app.calendar_client 2026-09-22
"""
from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .config import settings
from .slots import Interval, compute_free_slots

logger = logging.getLogger("booking.calendar")

# events: create/list/delete; readonly: freebusy queries.
SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
]


@dataclass(frozen=True)
class Appointment:
    event_id: str
    summary: str
    start: datetime
    end: datetime
    html_link: str | None = None
    description: str | None = None


class CalendarUnavailable(RuntimeError):
    """Raised when Google rejects a call or credentials are missing."""


def _load_credentials():
    if settings.google_auth_mode == "service_account":
        path = Path(settings.google_service_account_file)
        if not path.exists():
            raise CalendarUnavailable(f"service account file not found: {path}")
        return service_account.Credentials.from_service_account_file(str(path), scopes=SCOPES)

    token_path = Path(settings.google_oauth_token_file)
    if not token_path.exists():
        raise CalendarUnavailable(
            f"OAuth token not found at {token_path}. Run: python scripts/authorize_google.py"
        )
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json())
    if not creds.valid:
        raise CalendarUnavailable("OAuth token invalid; re-run scripts/authorize_google.py")
    return creds


class CalendarClient:
    """One instance per agent process; the underlying service object is reusable."""

    def __init__(self) -> None:
        self._service = None

    def _svc(self):
        if self._service is None:
            self._service = build(
                "calendar", "v3", credentials=_load_credentials(), cache_discovery=False
            )
        return self._service

    # -- reads -------------------------------------------------------------

    def _busy_sync(self, start: datetime, end: datetime) -> list[Interval]:
        body = {
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "timeZone": settings.business_timezone,
            "items": [{"id": settings.google_calendar_id}],
        }
        resp = self._svc().freebusy().query(body=body).execute()
        cal = resp["calendars"].get(settings.google_calendar_id, {})
        if cal.get("errors"):
            raise CalendarUnavailable(f"freebusy error: {cal['errors']}")
        return [
            Interval(datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"]))
            for b in cal.get("busy", [])
        ]

    async def free_slots(self, day: date, now: datetime | None = None) -> list[datetime]:
        window = settings.hours.window_for(day)
        if window is None:
            return []
        busy = await asyncio.to_thread(self._busy_sync, window.start, window.end)
        return compute_free_slots(
            day,
            busy,
            settings.hours,
            settings.slot_minutes,
            settings.appointment_minutes,
            now=now or datetime.now(settings.tz),
            min_lead_minutes=settings.min_lead_minutes,
        )

    async def is_free(self, start: datetime) -> bool:
        """Re-check one slot right before writing — freebusy can go stale mid-call."""
        end = start + timedelta(minutes=settings.appointment_minutes)
        busy = await asyncio.to_thread(self._busy_sync, start, end)
        return not any(Interval(start, end).overlaps(b) for b in busy)

    def _list_sync(self, start: datetime, end: datetime, query: str | None) -> list[Appointment]:
        kwargs = dict(
            calendarId=settings.google_calendar_id,
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=50,
        )
        if query:
            kwargs["q"] = query
        items = self._svc().events().list(**kwargs).execute().get("items", [])
        out: list[Appointment] = []
        for ev in items:
            s, e = ev.get("start", {}), ev.get("end", {})
            if "dateTime" not in s:  # skip all-day events
                continue
            out.append(
                Appointment(
                    event_id=ev["id"],
                    summary=ev.get("summary", "(no title)"),
                    start=datetime.fromisoformat(s["dateTime"]).astimezone(settings.tz),
                    end=datetime.fromisoformat(e["dateTime"]).astimezone(settings.tz),
                    html_link=ev.get("htmlLink"),
                    description=ev.get("description"),
                )
            )
        return out

    async def upcoming(self, query: str | None = None, days: int | None = None) -> list[Appointment]:
        now = datetime.now(settings.tz)
        end = now + timedelta(days=days or settings.max_days_ahead)
        return await asyncio.to_thread(self._list_sync, now, end, query)

    # -- writes ------------------------------------------------------------

    def _insert_sync(self, body: dict, send_updates: str) -> Appointment:
        ev = (
            self._svc()
            .events()
            .insert(calendarId=settings.google_calendar_id, body=body, sendUpdates=send_updates)
            .execute()
        )
        return Appointment(
            event_id=ev["id"],
            summary=ev["summary"],
            start=datetime.fromisoformat(ev["start"]["dateTime"]).astimezone(settings.tz),
            end=datetime.fromisoformat(ev["end"]["dateTime"]).astimezone(settings.tz),
            html_link=ev.get("htmlLink"),
            description=ev.get("description"),
        )

    async def book(
        self,
        start: datetime,
        customer_name: str,
        customer_email: str | None = None,
        customer_phone: str | None = None,
        reason: str | None = None,
    ) -> Appointment:
        end = start + timedelta(minutes=settings.appointment_minutes)
        description_lines = [f"Booked by voice agent for {customer_name}."]
        if customer_email:
            description_lines.append(f"Email: {customer_email}")
        if customer_phone:
            description_lines.append(f"Phone: {customer_phone}")
        if reason:
            description_lines.append(f"Reason: {reason}")
        body: dict = {
            "summary": f"{settings.business_name}: {customer_name}",
            "description": "\n".join(description_lines),
            "start": {"dateTime": start.isoformat(), "timeZone": settings.business_timezone},
            "end": {"dateTime": end.isoformat(), "timeZone": settings.business_timezone},
            # Tag events so the agent can tell its own bookings apart from other entries.
            "extendedProperties": {"private": {"booked_by": "livekit-agent"}},
        }
        send_updates = "none"
        if customer_email and settings.calendar_invite_attendees:
            body["attendees"] = [{"email": customer_email, "displayName": customer_name}]
            send_updates = "all"
        try:
            return await asyncio.to_thread(self._insert_sync, body, send_updates)
        except HttpError as exc:
            logger.exception("calendar insert failed")
            raise CalendarUnavailable(f"Google Calendar rejected the booking: {exc.reason}") from exc

    def _delete_sync(self, event_id: str) -> None:
        self._svc().events().delete(
            calendarId=settings.google_calendar_id, eventId=event_id, sendUpdates="all"
        ).execute()

    async def cancel(self, event_id: str) -> None:
        try:
            await asyncio.to_thread(self._delete_sync, event_id)
        except HttpError as exc:
            if exc.resp.status in (404, 410):
                return  # already gone — treat as cancelled
            logger.exception("calendar delete failed")
            raise CalendarUnavailable(f"Google Calendar rejected the cancellation: {exc.reason}") from exc


async def _main(argv: list[str]) -> None:
    from dotenv import load_dotenv

    load_dotenv()
    day = date.fromisoformat(argv[0]) if argv else date.today() + timedelta(days=1)
    client = CalendarClient()
    slots = await client.free_slots(day)
    print(f"{len(slots)} free {settings.appointment_minutes}-minute slots on {day} ({settings.business_timezone}):")
    for s in slots:
        print("  ", s.strftime("%H:%M"))


if __name__ == "__main__":
    asyncio.run(_main(sys.argv[1:]))
