# llm-weather-tool-calling

The simplest possible "hello world" for **LLM tool calling**: Claude picks a
random city on its own, calls a `get_weather` tool, and returns a structured
report.

## What it does

There is no user input — the whole run is driven by the model:

1. Claude is given one tool, `get_weather(city)`, and asked to pick a random city.
2. Claude chooses a city from its own knowledge and requests the tool call.
3. The script runs `get_weather` locally and hands the result back.
4. Claude returns a `WeatherReport` — its shape is enforced via structured outputs.

```
get_weather(city: str) -> {temperature_c: float, condition: str, humidity: int}
```

Final structured output:

```
city: str
temperature_c: float
condition: str
humidity: int
weather_summary: str
```

The weather data is mocked (seeded by city name) so the example runs without a
real weather API — swap the body of `get_weather` for a real call if you want
live data.

## Run

```bash
cd llm-weather-tool-calling
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python weather.py
```

Example output:

```json
{
  "city": "Reykjavik",
  "temperature_c": 4.2,
  "condition": "light rain",
  "humidity": 81,
  "weather_summary": "Cool and drizzly in Reykjavik today — bring a jacket."
}
```

## How the tool-calling loop works

`weather.py` runs a minimal agentic loop with `client.messages.parse()`:

- Each turn, Claude either asks to use a tool (`stop_reason == "tool_use"`) or
  returns the final answer.
- On a tool request, we execute the tool, append the result as a
  `tool_result`, and loop again.
- When Claude is done, `response.parsed_output` is a validated `WeatherReport`
  (a Pydantic model), thanks to structured outputs.

Uses the Anthropic Python SDK against `claude-opus-4-8`.
