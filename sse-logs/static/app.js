/**
 * SSE Deployment Logs — client logic
 *
 * Flow
 * ----
 * 1. Page load  → fetch /deployments → populate sidebar
 * 2. Click item → fetch /deployments/<id>/logs → render all lines (no SSE)
 * 3. Click "New" → POST /deployments → open EventSource for live stream
 *    Each `message` event → prependLine()
 *    `done` event         → close EventSource, update badge & dot
 */

(function () {
  "use strict";

  // ── DOM refs ─────────────────────────────────────────────────────────────
  const newBtn      = document.getElementById("newDeployBtn");
  const deployList  = document.getElementById("deployList");
  const logPanel    = document.getElementById("logPanel");
  const deployName  = document.getElementById("deployName");
  const deployId    = document.getElementById("deployId");
  const statusBadge = document.getElementById("statusBadge");
  const clearBtn    = document.getElementById("clearBtn");

  // ── State ────────────────────────────────────────────────────────────────
  let activeId   = null;   // deployment ID currently shown
  let activeES   = null;   // open EventSource (if any)
  let sidebarMap = {};     // id → {li, dot} for sidebar DOM nodes

  // ── Bootstrap ────────────────────────────────────────────────────────────
  loadSidebar();

  // ── Sidebar ───────────────────────────────────────────────────────────────
  async function loadSidebar() {
    const list = await apiFetch("/deployments");
    list.forEach(addSidebarItem);
  }

  function addSidebarItem(meta, prepend = false) {
    // Avoid duplicates
    if (sidebarMap[meta.id]) {
      updateSidebarItem(meta.id, meta.status);
      return;
    }

    const li   = document.createElement("li");
    li.className = "deploy-item";
    li.dataset.id = meta.id;

    const dot  = document.createElement("span");
    dot.className = `deploy-item-dot dot--${meta.status}`;

    const info = document.createElement("div");
    info.className = "deploy-item-info";

    const name = document.createElement("div");
    name.className = "deploy-item-name";
    name.textContent = meta.name;

    const idEl = document.createElement("div");
    idEl.className = "deploy-item-id";
    idEl.textContent = meta.id;

    info.appendChild(name);
    info.appendChild(idEl);
    li.appendChild(dot);
    li.appendChild(info);

    li.addEventListener("click", () => loadDeployment(meta.id));

    if (prepend) {
      deployList.insertBefore(li, deployList.firstChild);
    } else {
      deployList.appendChild(li);
    }

    sidebarMap[meta.id] = { li, dot };
  }

  function updateSidebarItem(id, status) {
    const entry = sidebarMap[id];
    if (!entry) return;
    entry.dot.className = `deploy-item-dot dot--${status}`;
  }

  function setActiveItem(id) {
    Object.values(sidebarMap).forEach(({ li }) => li.classList.remove("active"));
    if (sidebarMap[id]) sidebarMap[id].li.classList.add("active");
  }

  // ── Load past deployment (static) ────────────────────────────────────────
  async function loadDeployment(id) {
    if (id === activeId && activeES) return;   // already streaming this one

    stopStream();
    clearLog();
    setActiveItem(id);
    activeId = id;

    const data = await apiFetch(`/deployments/${id}/logs`);
    if (!data) return;

    setHeader(data.meta.name, data.meta.id, data.meta.status);

    // Render all stored lines — display in chronological order (oldest first =
    // bottom of the prepend stack), so we bulk-insert in reverse then reverse
    // the panel display via CSS flex-direction: column-reverse... actually
    // simpler: insert each line normally (append), then the panel shows oldest
    // at top.  But the requirement is newest-at-top for LIVE lines.
    // Solution: static logs → append (old→new, scroll to top after);
    //           live stream  → prepend each new arrival.
    data.lines.forEach((line) => appendLine(line, false));

    if (data.meta.status === "running") {
      openStream(id, data.lines.length);
    }
  }

  // ── New deployment ────────────────────────────────────────────────────────
  newBtn.addEventListener("click", async () => {
    newBtn.disabled = true;

    const meta = await apiFetch("/deployments", { method: "POST" });
    if (!meta) { newBtn.disabled = false; return; }

    stopStream();
    clearLog();
    setActiveItem(meta.id);
    activeId = meta.id;

    setHeader(meta.name, meta.id, "running");
    addSidebarItem(meta, true);
    setActiveItem(meta.id);

    openStream(meta.id, 0);
    newBtn.disabled = false;
  });

  // ── SSE stream ────────────────────────────────────────────────────────────
  function openStream(id, skipLines) {
    stopStream();

    const es = new EventSource(`/deployments/${id}/stream`);
    activeES = es;

    let linesSeen = 0;

    es.onmessage = (event) => {
      // Skip lines already shown from the static load
      if (linesSeen < skipLines) { linesSeen++; return; }
      linesSeen++;
      prependLine(event.data);
    };

    es.addEventListener("done", () => {
      es.close();
      activeES = null;
      setStatus("complete");
      updateSidebarItem(id, "complete");
    });

    es.addEventListener("error", (e) => {
      // Don't close on transient network hiccups; but do on explicit error event
      if (e.type === "error" && e.data) {
        es.close();
        activeES = null;
        setStatus("failed");
        updateSidebarItem(id, "failed");
      }
    });

    // Fallback: if the EventSource errors out (connection refused etc.)
    es.onerror = () => {
      // EventSource auto-reconnects; only close if deployment is done
      apiFetch(`/deployments/${id}/logs`).then((data) => {
        if (data && data.meta.status !== "running") {
          es.close();
          activeES = null;
          setStatus(data.meta.status);
        }
      });
    };
  }

  function stopStream() {
    if (activeES) { activeES.close(); activeES = null; }
  }

  // ── Log line rendering ────────────────────────────────────────────────────

  function classForLine(text) {
    if (/── Phase:/.test(text))  return "log-line--PHASE";
    if (/\[WARN\]/.test(text))   return "log-line--WARN";
    if (/\[ERROR\]/.test(text))  return "log-line--ERROR";
    if (/finished successfully|complete/i.test(text)) return "log-line--DONE";
    return "log-line--INFO";
  }

  /** Prepend a live-streamed line (newest at top). */
  function prependLine(text) {
    if (!text.trim()) return;
    removeEmptyHint();
    const el = makeLine(text, true);
    logPanel.insertBefore(el, logPanel.firstChild);
  }

  /** Append a line when rendering stored history (oldest at top). */
  function appendLine(text, animate = false) {
    if (!text.trim()) return;
    removeEmptyHint();
    const el = makeLine(text, animate);
    logPanel.appendChild(el);
  }

  function makeLine(text, animate) {
    const el = document.createElement("div");
    el.className = `log-line ${classForLine(text)}${animate ? " log-line--new" : ""}`;
    el.textContent = text;
    if (animate) {
      el.addEventListener("animationend", () => el.classList.remove("log-line--new"), { once: true });
    }
    return el;
  }

  function removeEmptyHint() {
    const hint = logPanel.querySelector(".empty-hint");
    if (hint) hint.remove();
  }

  function clearLog() {
    logPanel.innerHTML = "";
  }

  // ── Header helpers ────────────────────────────────────────────────────────
  function setHeader(name, id, status) {
    deployName.textContent = name;
    deployId.textContent   = `#${id}`;
    setStatus(status);
  }

  function setStatus(status) {
    statusBadge.textContent = status;
    statusBadge.className   = `badge badge--${status}`;
    if (activeId) updateSidebarItem(activeId, status);
  }

  clearBtn.addEventListener("click", clearLog);

  // ── Fetch helper ──────────────────────────────────────────────────────────
  async function apiFetch(url, opts = {}) {
    try {
      const res = await fetch(url, {
        headers: { "Content-Type": "application/json" },
        ...opts,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      console.error("apiFetch error:", err);
      return null;
    }
  }
})();
