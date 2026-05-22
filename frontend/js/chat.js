// chat.js — floating chat panel for "Ask me on TN elections 2026"
import { sendChat } from "/js/api.js";

const STORAGE_KEY = "tn2026.chat.history";

const SUGGESTIONS = [
  "Who won Coimbatore South and by how much?",
  "How did DMK perform overall?",
  "முதல்வர் தனது தொகுதியில் வெற்றி பெற்றாரா?",
  "Which were the closest contests?",
];

let history = [];      // [{role, content}]
let isSending = false;

// ── DOM refs ────────────────────────────────────────────────
let elBtn, elPanel, elList, elInput, elSend, elClear, elClose;

export function initChat() {
  mountDom();
  loadHistory();
  render();

  elBtn.addEventListener("click", openPanel);
  elClose.addEventListener("click", closePanel);
  elClear.addEventListener("click", clearHistory);
  elSend.addEventListener("click", onSend);
  elInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  });
  elInput.addEventListener("input", autosize);
}

function mountDom() {
  const wrap = document.createElement("div");
  wrap.innerHTML = `
    <button id="chat-fab" title="Ask me on TN elections 2026">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
      </svg>
      <span>Ask me on TN elections 2026</span>
    </button>
    <div id="chat-panel" class="closed" aria-hidden="true">
      <div class="ch-head">
        <div class="ch-title">Ask me on TN elections 2026</div>
        <button class="ch-iconbtn" id="chat-clear" title="Clear conversation">⟲</button>
        <button class="ch-iconbtn" id="chat-close" title="Close">×</button>
      </div>
      <div class="ch-list" id="chat-list"></div>
      <div class="ch-input-wrap">
        <textarea id="chat-input" rows="1"
                  placeholder="Ask in English or தமிழ்…"
                  maxlength="2000"></textarea>
        <button id="chat-send" title="Send">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="22" y1="2" x2="11" y2="13"/>
            <polygon points="22 2 15 22 11 13 2 9 22 2"/>
          </svg>
        </button>
      </div>
    </div>
  `;
  document.body.appendChild(wrap);

  elBtn   = document.getElementById("chat-fab");
  elPanel = document.getElementById("chat-panel");
  elList  = document.getElementById("chat-list");
  elInput = document.getElementById("chat-input");
  elSend  = document.getElementById("chat-send");
  elClear = document.getElementById("chat-clear");
  elClose = document.getElementById("chat-close");
}

// ── State ───────────────────────────────────────────────────
function loadHistory() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (raw) history = JSON.parse(raw) || [];
  } catch {
    history = [];
  }
}

function saveHistory() {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(history));
  } catch {}
}

function clearHistory() {
  if (history.length && !confirm("Clear this conversation?")) return;
  history = [];
  saveHistory();
  render();
  elInput.focus();
}

// ── UI ──────────────────────────────────────────────────────
function openPanel() {
  elPanel.classList.remove("closed");
  elPanel.setAttribute("aria-hidden", "false");
  elBtn.classList.add("hidden");
  setTimeout(() => elInput.focus(), 200);
  scrollToBottom();
}

function closePanel() {
  elPanel.classList.add("closed");
  elPanel.setAttribute("aria-hidden", "true");
  elBtn.classList.remove("hidden");
}

function render() {
  elList.innerHTML = "";
  if (history.length === 0) {
    const empty = document.createElement("div");
    empty.className = "ch-empty";
    empty.innerHTML = `
      <div class="ch-empty-title">Ask anything about the 2026 TN election results.</div>
      <div class="ch-empty-sub">Try one of these:</div>
      <div class="ch-suggest"></div>
    `;
    const sug = empty.querySelector(".ch-suggest");
    SUGGESTIONS.forEach(s => {
      const b = document.createElement("button");
      b.className = "ch-chip";
      b.textContent = s;
      b.addEventListener("click", () => {
        elInput.value = s;
        autosize();
        onSend();
      });
      sug.appendChild(b);
    });
    elList.appendChild(empty);
    return;
  }
  history.forEach(m => elList.appendChild(bubble(m.role, m.content)));
  scrollToBottom();
}

function bubble(role, content, opts = {}) {
  const b = document.createElement("div");
  b.className = `ch-msg ch-${role}` + (opts.error ? " ch-err" : "");
  // preserve line breaks; escape HTML
  b.textContent = content;
  return b;
}

function loadingBubble() {
  const b = document.createElement("div");
  b.className = "ch-msg ch-assistant ch-loading";
  b.innerHTML = `<span class="ch-dot"></span><span class="ch-dot"></span><span class="ch-dot"></span>`;
  return b;
}

function scrollToBottom() {
  requestAnimationFrame(() => { elList.scrollTop = elList.scrollHeight; });
}

function autosize() {
  elInput.style.height = "auto";
  const max = 120;
  elInput.style.height = Math.min(elInput.scrollHeight, max) + "px";
}

// ── Send / receive ──────────────────────────────────────────
async function onSend() {
  if (isSending) return;
  const text = elInput.value.trim();
  if (!text) return;

  history.push({ role: "user", content: text });
  saveHistory();
  elInput.value = "";
  autosize();
  render();

  isSending = true;
  elSend.disabled = true;
  const loader = loadingBubble();
  elList.appendChild(loader);
  scrollToBottom();

  try {
    const data = await sendChat(history);
    loader.remove();
    history.push({ role: "assistant", content: data.reply || "(empty reply)" });
    saveHistory();
    render();
  } catch (err) {
    loader.remove();
    const msg = `Couldn't get a response: ${err.message}`;
    elList.appendChild(bubble("assistant", msg, { error: true }));
    scrollToBottom();
  } finally {
    isSending = false;
    elSend.disabled = false;
    elInput.focus();
  }
}
