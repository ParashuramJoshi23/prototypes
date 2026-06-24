"""Generate a structured travel itinerary using Claude + Pydantic.

No user input: the model picks a random source city and destination city from
its own knowledge, then produces an itinerary that conforms exactly to the
`TravelItinerary` schema.

Run:
    export ANTHROPIC_API_KEY=sk-ant-...
    python generate_itinerary.py
"""

from __future__ import annotations

import json

import anthropic

from models import TravelItinerary

MODEL = "claude-opus-4-8"

# Adaptive thinking has no temperature knob on Opus 4.8, so we get variety by
# explicitly asking the model to surprise us with the city pairing each run.
PROMPT = """\
Invent a travel itinerary entirely from your own knowledge — there is no user input.

First, pick a random SOURCE city and a random DESTINATION city anywhere in the world.
Surprise me: avoid the obvious tourist-hub pairings and choose somewhere you have
not picked before in this conversation. The source and destination must be different
cities in different countries.

Then build a realistic itinerary for a traveller going from the source to the
destination. Choose a sensible trip length (3-10 days), assign a budget category,
list the destination's top attractions, and lay out a day-by-day plan with one
entry per day of the trip. Make the number of daily_plan entries equal to
trip_duration_days, with day numbers running 1..N in order.
"""


def generate() -> TravelItinerary:
    """Ask Claude for an itinerary and return it as a validated Pydantic object."""
    client = anthropic.Anthropic()

    response = client.messages.parse(
        model=MODEL,
        max_tokens=4096,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": PROMPT}],
        output_format=TravelItinerary,
    )

    # `parsed_output` is a validated TravelItinerary instance (or None on refusal).
    itinerary = response.parsed_output
    if itinerary is None:
        raise RuntimeError(
            f"Model did not return a parseable itinerary (stop_reason={response.stop_reason})."
        )
    return itinerary


def main() -> None:
    itinerary = generate()

    # Pretty-print as JSON — this is the structured output the prototype is about.
    print(json.dumps(itinerary.model_dump(), indent=2))

    # And a short human-readable summary to show the typed object in use.
    print(
        f"\n{itinerary.source_city} -> {itinerary.destination} "
        f"({itinerary.trip_duration_days} days, {itinerary.budget_category})"
    )


if __name__ == "__main__":
    main()
