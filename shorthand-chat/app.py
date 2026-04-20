"""
Shorthand chat — Flask + Socket.IO server.

Clients connect over WebSocket.  Each socket session gets its own
conversation history so the LLM has context across turns.
"""

from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

from llm import ask_claude

app = Flask(__name__)
app.config["SECRET_KEY"] = "shorthand-chat-dev-secret"

# threading mode: each socket handler runs in its own thread.
# The subprocess call to claude CLI blocks that thread while waiting,
# which is fine — other connections continue to be served normally.
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

# Per-session conversation history
# {sid: [{"role": "user"|"assistant", "content": str}]}
_history: dict[str, list[dict]] = {}


# ─── HTTP ────────────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return render_template("index.html")


# ─── Socket.IO events ────────────────────────────────────────────────────────

@socketio.on("connect")
def on_connect():
    _history[request.sid] = []


@socketio.on("disconnect")
def on_disconnect():
    _history.pop(request.sid, None)


@socketio.on("user_message")
def on_user_message(data):
    sid = request.sid
    text = (data.get("text") or "").strip()
    if not text:
        return

    history = _history.setdefault(sid, [])
    history.append({"role": "user", "content": text})

    # Emit a "thinking" signal so the UI can show a loading indicator
    emit("bot_thinking", {})

    try:
        reply = ask_claude(history)
        history.append({"role": "assistant", "content": reply})
        emit("bot_message", {"text": reply})
    except Exception as exc:
        # Roll back the user message so the history stays consistent
        history.pop()
        emit("error", {"message": str(exc)})


@socketio.on("clear_history")
def on_clear_history():
    _history[request.sid] = []
    emit("history_cleared", {})


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Starting shorthand chat on http://127.0.0.1:5051")
    socketio.run(app, debug=False, port=5051, host="0.0.0.0", allow_unsafe_werkzeug=True)
