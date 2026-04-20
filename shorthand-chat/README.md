# Shorthand Chat

A simple chat app for shorthand typing and voice input, powered by Claude (via your Claude Max plan — no API key needed).

## Features

- **Shorthand text** — type a few characters (`dr tmrw 9`, `cant slp`, `h ngry`) and Claude understands and responds naturally
- **Voice input** — press the mic button, speak, and the transcript is sent automatically
- **Conversation memory** — Claude remembers the full thread so follow-ups like "yes" or "no" work
- **Clear** — wipe the conversation and start fresh

## Setup

```bash
cd shorthand-chat
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
source .venv/bin/activate
python3 app.py
```

Open **http://localhost:5051** in Chrome or Edge.

> Voice input requires Chrome or Edge (Web Speech API). Text input works in any browser.

## How it works

```
User types / speaks
      │
      │  WebSocket (Socket.IO)
      ▼
  app.py  ──── subprocess ────▶  claude -p "..." --system-prompt "..." --bare
      │                                    │
      │         WebSocket reply            ▼
      └────────────────────────  response text back to browser
```

- `app.py` — Flask + Socket.IO server; one conversation history per socket session
- `llm.py` — formats history as text, calls `claude -p` via subprocess (uses your logged-in Claude Max plan)
- `static/app.js` — Socket.IO client + Web Speech API
- `static/style.css` — large-font, accessible UI

## Shorthand examples

| You type | Claude understands |
|---|---|
| `h ngry` | I am hungry |
| `dr tmrw 9` | Doctor appointment tomorrow at 9 |
| `cant slp` | Can't sleep |
| `hdache` | Headache |
| `call j` | Want to call someone (asks who) |
| `cold` | Feeling cold / has a cold |
| `med` | About medication |
| `tk` | Thank you |
