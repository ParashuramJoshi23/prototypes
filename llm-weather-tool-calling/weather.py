"""Hello-world LLM tool calling: let Claude pick a city, call a weather tool,
and return a structured report.

The flow is the simplest possible demonstration of tool use:

    1. We give Claude one tool, `get_weather(city)`, and no input data.
    2. Claude picks a random city from its own knowledge and asks to call the tool.
    3. We execute the tool locally and hand the result back.
    4. Claude returns a structured `WeatherReport` (enforced via structured outputs).

Run:  ANTHROPIC_API_KEY=... python weather.py
"""

import json
import random

import anthropic
from pydantic import BaseModel

MODEL = "claude-opus-4-8"

# The tool Claude can call. The schema is what Claude sees; the implementation
# below is what actually runs when Claude asks for it.
TOOLS = [
    {
        "name": "get_weather",
        "description": "Get the current weather for a city.",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name, e.g. 'Lisbon'"}
            },
            "required": ["city"],
        },
    }
]

CONDITIONS = ["sunny", "partly cloudy", "overcast", "light rain", "thunderstorms", "snow"]


def get_weather(city: str) -> dict:
    """Stand-in weather provider.

    A real implementation would call a weather API here. For a hello-world we
    return plausible mock data — seeded by the city name so repeated calls for
    the same city are consistent.
    """
    rng = random.Random(city.lower())
    return {
        "temperature_c": round(rng.uniform(-5, 38), 1),
        "condition": rng.choice(CONDITIONS),
        "humidity": rng.randint(20, 95),
    }


class WeatherReport(BaseModel):
    """The structured result we ask Claude to produce."""

    city: str
    temperature_c: float
    condition: str
    humidity: int
    weather_summary: str


def run() -> WeatherReport:
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment

    messages = [
        {
            "role": "user",
            "content": (
                "Pick a random city anywhere in the world using your own knowledge "
                "(do not ask me which one). Call the get_weather tool for it, then "
                "return a structured weather report. The weather_summary should be a "
                "short, friendly one-sentence description of the conditions."
            ),
        }
    ]

    # Agentic loop: keep going until Claude stops asking for tools and returns
    # the final structured report.
    while True:
        response = client.messages.parse(
            model=MODEL,
            max_tokens=1024,
            tools=TOOLS,
            messages=messages,
            output_format=WeatherReport,
        )

        if response.stop_reason != "tool_use":
            return response.parsed_output

        # Record Claude's turn (the tool_use request), run each requested tool,
        # and send the results back as a single user message.
        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = get_weather(**block.input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    }
                )

        messages.append({"role": "user", "content": tool_results})


if __name__ == "__main__":
    report = run()
    print(json.dumps(report.model_dump(), indent=2))
