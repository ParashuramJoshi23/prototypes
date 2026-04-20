"""
LLM integration via the local `claude` CLI (Claude Max plan — no API key needed).

Each call formats the full conversation history as text and passes it to
`claude -p` in non-interactive / bare mode.  The `--bare` flag skips all
Claude Code overhead (hooks, LSP, memory) so responses are fast.
"""

import shutil
import subprocess

SYSTEM_PROMPT = """You are a warm, patient assistant helping an elderly person communicate with their family.

The person types in shorthand or abbreviated messages. Your job is to:
1. Understand what they mean from context — do NOT explain your interpretation back to them
2. Respond helpfully, warmly, and briefly to what they most likely meant
3. Use plain language. Short sentences. No jargon, no bullet points, no long paragraphs
4. If the message is truly ambiguous, ask ONE short, simple clarifying question
5. Be warm and caring — like a helpful family member who genuinely wants to help

Examples of shorthand you may see:
- "h ngry" → they are hungry
- "dr tmrw 9" → doctor appointment tomorrow at 9
- "cant slp" → can't sleep
- "call j" → want to call someone whose name starts with J
- "med" → asking about medication or need to take medicine
- "wtr" → wants water
- "tk" or "tq" → thank you
- "hdache" → headache
- "cold" → feeling cold, or has a cold

Keep responses under 3 sentences. Always be gentle and warm."""


def ask_claude(history: list[dict]) -> str:
    """
    Call the claude CLI with the full conversation history.

    history: list of {"role": "user"|"assistant", "content": str}
             The last entry must be the new user message.
    """
    if not shutil.which("claude"):
        raise RuntimeError(
            "claude CLI not found in PATH. "
            "Make sure Claude Code is installed and on your PATH."
        )

    prompt = _format_history(history)

    result = subprocess.run(
        [
            "claude", "-p", prompt,
            "--system-prompt", SYSTEM_PROMPT,
            "--output-format", "text",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        error_detail = result.stderr.strip() or "unknown error"
        raise RuntimeError(f"claude CLI error: {error_detail}")

    reply = result.stdout.strip()
    if not reply:
        raise RuntimeError("claude CLI returned an empty response")

    return reply


def _format_history(history: list[dict]) -> str:
    """
    Serialise the conversation history as plain text so Claude has context.

    For the very first message (no prior turns) just send it directly.
    For subsequent messages, include prior turns then call out the latest message.
    """
    if len(history) == 1:
        return history[0]["content"]

    lines = []
    for msg in history[:-1]:
        role = "User" if msg["role"] == "user" else "Assistant"
        lines.append(f"{role}: {msg['content']}")

    lines.append("")
    lines.append(f"Latest message from User: {history[-1]['content']}")
    return "\n".join(lines)
