/**
 * Shorthand Chat — client-side logic
 *
 * Handles:
 *  - Socket.IO events (send, receive, clear)
 *  - Text input (Enter key + Send button)
 *  - Voice input (Web Speech API → auto-submit on end)
 *  - UI state management (thinking indicator, mic pulse, error display)
 */

(function () {
  "use strict";

  // ── DOM refs ───────────────────────────────────────────────────────────────
  const chatBox      = document.getElementById("chatBox");
  const textInput    = document.getElementById("textInput");
  const sendBtn      = document.getElementById("sendBtn");
  const micBtn       = document.getElementById("micBtn");
  const clearBtn     = document.getElementById("clearBtn");
  const thinkingBar  = document.getElementById("thinkingBar");
  const voiceStatus  = document.getElementById("voiceStatus");
  const interimText  = document.getElementById("interimText");
  const noMicWarning = document.getElementById("noMicWarning");

  // ── Socket.IO ──────────────────────────────────────────────────────────────
  const socket = io();

  socket.on("connect", () => {
    console.log("Connected:", socket.id);
  });

  socket.on("bot_thinking", () => {
    setThinking(true);
  });

  socket.on("bot_message", ({ text }) => {
    setThinking(false);
    appendBubble("bot", text);
    scrollToBottom();
  });

  socket.on("error", ({ message }) => {
    setThinking(false);
    appendBubble("error", "⚠️ " + message);
    scrollToBottom();
  });

  socket.on("history_cleared", () => {
    chatBox.innerHTML = "";
    appendWelcome();
  });

  // ── Send a message ─────────────────────────────────────────────────────────
  function sendMessage(source = "text") {
    const text = textInput.value.trim();
    if (!text) return;

    // Remove welcome message on first send
    const welcome = chatBox.querySelector(".welcome-msg");
    if (welcome) welcome.remove();

    appendBubble("user", text);
    scrollToBottom();

    socket.emit("user_message", { text, source });

    textInput.value = "";
    sendBtn.disabled = true;
    textInput.focus();
  }

  sendBtn.addEventListener("click", () => sendMessage("text"));

  textInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage("text");
    }
  });

  textInput.addEventListener("input", () => {
    sendBtn.disabled = textInput.value.trim() === "";
  });

  clearBtn.addEventListener("click", () => {
    socket.emit("clear_history");
  });

  // ── UI helpers ─────────────────────────────────────────────────────────────
  function appendBubble(type, text) {
    const row = document.createElement("div");
    row.className = `bubble-row ${type}`;

    if (type !== "error") {
      const label = document.createElement("div");
      label.className = "bubble-label";
      label.textContent = type === "user" ? "You" : "Assistant";
      row.appendChild(label);
    }

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;
    row.appendChild(bubble);

    chatBox.appendChild(row);
  }

  function appendWelcome() {
    const div = document.createElement("div");
    div.className = "welcome-msg";
    div.innerHTML =
      'Type a short message or press the mic to speak.<br>' +
      '<span class="welcome-sub">Say or type anything — I\'ll understand.</span>';
    chatBox.appendChild(div);
  }

  function setThinking(on) {
    thinkingBar.classList.toggle("hidden", !on);
    sendBtn.disabled = on;
    if (on) scrollToBottom();
  }

  function scrollToBottom() {
    chatBox.scrollTop = chatBox.scrollHeight;
  }

  // Initial button state
  sendBtn.disabled = true;

  // ── Voice input (Web Speech API) ───────────────────────────────────────────
  const SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;

  if (!SpeechRecognition) {
    // Browser doesn't support it — hide mic, show warning
    micBtn.style.display = "none";
    noMicWarning.classList.remove("hidden");
  } else {
    const recognition = new SpeechRecognition();
    recognition.continuous    = false;   // single utterance per press
    recognition.interimResults = true;   // show live transcript
    recognition.lang           = "en-US";

    let listening = false;

    function setListening(on) {
      listening = on;
      micBtn.classList.toggle("listening", on);
      micBtn.setAttribute("aria-label", on ? "Stop listening" : "Start voice input");
      voiceStatus.classList.toggle("hidden", !on);
      if (!on) interimText.textContent = "";
    }

    micBtn.addEventListener("click", () => {
      if (listening) {
        recognition.stop();
      } else {
        textInput.value = "";
        sendBtn.disabled = true;
        try {
          recognition.start();
          setListening(true);
        } catch (err) {
          console.error("SpeechRecognition start error:", err);
        }
      }
    });

    recognition.addEventListener("result", (event) => {
      let interim = "";
      let final   = "";

      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          final += transcript;
        } else {
          interim += transcript;
        }
      }

      if (final) {
        // Final result — put in input box and auto-send
        textInput.value = final.trim();
        interimText.textContent = "";
      } else {
        // Live preview while speaking
        interimText.textContent = interim;
      }
    });

    recognition.addEventListener("end", () => {
      setListening(false);
      const text = textInput.value.trim();
      if (text) {
        sendMessage("voice");
      }
    });

    recognition.addEventListener("error", (event) => {
      console.error("SpeechRecognition error:", event.error);
      setListening(false);
      if (event.error === "not-allowed") {
        appendBubble(
          "error",
          "Microphone access was denied. Please allow microphone access in your browser settings."
        );
        scrollToBottom();
      }
    });
  }
})();
