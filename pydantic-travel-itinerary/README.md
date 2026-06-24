# pydantic-travel-itinerary

A tiny prototype showing how to get **structured, schema-validated output** out of
an LLM using [Pydantic](https://docs.pydantic.dev/) and the Anthropic SDK.

There is **no user input**. The model (Claude Opus 4.8) picks a random source city
and destination city from its own knowledge and produces a travel itinerary that
conforms exactly to a fixed schema.

## The schema

Defined as Pydantic models in [`models.py`](./models.py):

```python
class DayPlan(BaseModel):
    day: int
    activities: list[str]

class TravelItinerary(BaseModel):
    source_city: str
    destination: str
    trip_duration_days: int
    budget_category: str
    top_attractions: list[str]
    daily_plan: list[DayPlan]
```

## How it works

`generate_itinerary.py` calls `client.messages.parse(...)` with
`output_format=TravelItinerary`. The SDK:

1. Converts the Pydantic model into a JSON schema.
2. Constrains the model's response to that schema (structured outputs).
3. Validates the response back into a typed `TravelItinerary` instance,
   available on `response.parsed_output`.

If the output doesn't match the schema, Pydantic validation fails loudly — that's
the whole value: you never hand-parse free-form JSON or guess at the shape.

## Run it

```bash
cd pydantic-travel-itinerary
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...   # your Anthropic API key
python generate_itinerary.py
```

Each run prints the itinerary as indented JSON plus a one-line summary. Because the
model chooses the cities, you get a different trip each time.

## Example output

```json
{
  "source_city": "Reykjavik",
  "destination": "Valparaiso",
  "trip_duration_days": 5,
  "budget_category": "mid-range",
  "top_attractions": [
    "Cerro Concepcion",
    "Pablo Neruda's house (La Sebastiana)",
    "the funicular elevators (ascensores)"
  ],
  "daily_plan": [
    {"day": 1, "activities": ["Arrive and settle into Cerro Alegre", "Evening walk along the harbour"]},
    {"day": 2, "activities": ["Ride the historic ascensores", "Street-art tour of the hills"]}
  ]
}
```
