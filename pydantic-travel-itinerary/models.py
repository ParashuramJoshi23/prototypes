"""Pydantic models defining the fixed schema for a generated travel itinerary.

The whole point of this prototype is to see how Pydantic lets us pin an LLM's
output to a known shape. We hand these models to the Anthropic SDK's
`messages.parse()` helper, which converts them to a JSON schema, constrains the
model's response to it, and validates the result back into typed objects.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DayPlan(BaseModel):
    """A single day's plan within the itinerary."""

    day: int = Field(..., ge=1, description="1-indexed day number of the trip.")
    activities: list[str] = Field(
        ...,
        min_length=1,
        description="Ordered list of activities for the day.",
    )


class TravelItinerary(BaseModel):
    """The fixed schema the model must adhere to."""

    source_city: str = Field(..., description="The randomly chosen origin city.")
    destination: str = Field(..., description="The randomly chosen destination city.")
    trip_duration_days: int = Field(..., ge=1, description="Length of the trip in days.")
    budget_category: str = Field(
        ...,
        description="Overall budget tier, e.g. 'budget', 'mid-range', or 'luxury'.",
    )
    top_attractions: list[str] = Field(
        ...,
        min_length=1,
        description="Headline attractions at the destination.",
    )
    daily_plan: list[DayPlan] = Field(
        ...,
        min_length=1,
        description="Per-day breakdown; one entry per trip day.",
    )
