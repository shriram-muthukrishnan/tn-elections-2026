// api.js — all backend calls in one place
const BASE = "";  // same origin, FastAPI serves both

export async function fetchConstituencies() {
  const r = await fetch(`${BASE}/api/constituencies`);
  if (!r.ok) throw new Error("Failed to load constituencies");
  return r.json();
}

export async function fetchConstituency(constNo) {
  const r = await fetch(`${BASE}/api/constituencies/${constNo}`);
  if (!r.ok) throw new Error(`Failed to load constituency ${constNo}`);
  return r.json();
}

export async function fetchSummary() {
  const r = await fetch(`${BASE}/api/summary`);
  if (!r.ok) throw new Error("Failed to load summary");
  return r.json();
}

export async function fetchParties() {
  const r = await fetch(`${BASE}/api/parties`);
  if (!r.ok) throw new Error("Failed to load parties");
  return r.json();
}

export async function sendChat(messages) {
  const r = await fetch(`${BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages: messages.slice(-10) }),
  });
  if (!r.ok) {
    let detail = `HTTP ${r.status}`;
    try { detail = (await r.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return r.json();
}
