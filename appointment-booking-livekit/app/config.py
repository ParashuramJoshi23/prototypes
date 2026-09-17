"""Configuration (env-driven via pydantic-settings)."""
from datetime import time
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict

from .slots import BusinessHours


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Claude model that drives the conversation. Voice is latency-sensitive, so
    # claude-sonnet-5 / claude-haiku-4-5 are reasonable faster/cheaper swaps.
    booking_model: str = "claude-opus-5"

    # --- Google Calendar ---------------------------------------------------
    # "oauth": act as a person (run scripts/authorize_google.py once).
    # "service_account": act as a robot user that the calendar has been shared with.
    google_auth_mode: str = "oauth"
    google_oauth_client_secret_file: str = "credentials/client_secret.json"
    google_oauth_token_file: str = "credentials/token.json"
    google_service_account_file: str = "credentials/service_account.json"
    # Which calendar to read/write. "primary" = the authorised user's own calendar.
    google_calendar_id: str = "primary"
    # Service accounts can't invite attendees without domain-wide delegation, so
    # flip this off in that mode; the customer's details still land in the description.
    calendar_invite_attendees: bool = True

    # --- Booking rules -----------------------------------------------------
    business_name: str = "Northside Dental"
    business_timezone: str = "America/New_York"
    business_open: str = "09:00"
    business_close: str = "17:00"
    business_weekdays: str = "1,2,3,4,5"  # ISO weekday numbers, 1=Mon
    slot_minutes: int = 30  # grid the day is divided into
    appointment_minutes: int = 30  # length of one booking
    min_lead_minutes: int = 60  # never offer a slot sooner than this
    max_days_ahead: int = 30
    max_slots_to_offer: int = 6  # keep spoken lists short

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.business_timezone)

    @property
    def hours(self) -> BusinessHours:
        return BusinessHours(
            open_time=time.fromisoformat(self.business_open),
            close_time=time.fromisoformat(self.business_close),
            tz=self.tz,
            weekdays=frozenset(int(d) for d in self.business_weekdays.split(",") if d.strip()),
        )


settings = Settings()
