// panel.js — side panel open/close and content rendering
import { fetchConstituency } from "./api.js";

const panel     = document.getElementById("panel");
const panelBody = document.getElementById("panel-inner");

export function closePanel() {
  panel.classList.add("closed");
}

// Delegated click handler: any element with class "p-close" inside the panel closes it.
// Works for content re-rendered via innerHTML.
panel.addEventListener("click", (ev) => {
  if (ev.target.closest(".p-close")) {
    closePanel();
  }
});

export async function openPanel(name, constNo, mapData) {
  panel.classList.remove("closed");

  // Show skeleton while loading
  panelBody.innerHTML = `
    <div class="p-head">
      <button class="p-close" type="button" aria-label="Close">✕</button>
      <div class="p-no">CONSTITUENCY · ${constNo}</div>
      <div class="p-name">${name}</div>
      <div class="p-loading">Loading results…</div>
    </div>`;

  try {
    const data = await fetchConstituency(constNo);
    renderPanel(data);
  } catch (e) {
    panelBody.innerHTML = `
      <div class="p-head">
        <button class="p-close" type="button" aria-label="Close">✕</button>
        <div class="p-name">${name}</div>
        <div class="p-error">Failed to load results. Check your connection.</div>
      </div>`;
  }
}

function fmt(n) {
  return n == null ? "—" : Number(n).toLocaleString("en-IN");
}

function renderPanel(d) {
  const totalVotes = d.total_votes_polled || 0;

  const candidateRows = (d.candidates || [])
    .sort((a, b) => b.total_votes - a.total_votes)
    .map(c => {
      const pct      = totalVotes > 0 ? (c.total_votes / totalVotes * 100) : 0;
      const barColor = c.is_nota ? "#bbb" : c.is_independent ? "#888" : (c.color_hex || "#888");
      const label    = c.is_nota ? "None of the Above" : c.is_independent ? "Independent" : (c.party_full || c.party_abbr);
      return `
        <div class="cand">
          <div class="ct">
            <div class="cl">
              <div class="cn ${c.is_winner ? "won" : ""}">${c.is_winner ? "✓ " : ""}${c.candidate_name}</div>
              <div class="cp">${label}</div>
            </div>
            <div class="cr">
              <div class="cv">${fmt(c.total_votes)}</div>
              <div class="cpct">${pct.toFixed(1)}%</div>
            </div>
          </div>
          <div class="bar-bg">
            <div class="bar-fill" style="width:${pct.toFixed(1)}%;background:${barColor}"></div>
          </div>
        </div>`;
    }).join("");

  panelBody.innerHTML = `
    <div class="p-head">
      <button class="p-close" type="button" aria-label="Close">✕</button>
      <div class="p-no">CONSTITUENCY · ${d.const_no}</div>
      <div class="p-name">${d.name}</div>
      <div class="p-badge">
        <span class="p-bdot" style="background:${d.color_hex}"></span>
        <span class="p-bname">${d.winning_candidate}</span>
        <span class="p-bparty">${d.winning_party}</span>
      </div>
      <div class="p-stats">
        <div class="p-stat"><div class="p-sv">${fmt(d.winning_margin)}</div><div class="p-sl">MARGIN</div></div>
        <div class="p-stat"><div class="p-sv">${fmt(totalVotes)}</div><div class="p-sl">TOTAL VOTES</div></div>
        <div class="p-stat"><div class="p-sv">${d.candidates?.length ?? "—"}</div><div class="p-sl">CANDIDATES</div></div>
      </div>
    </div>
    <div class="p-body">
      <div class="p-sec-title">All candidates</div>
      ${candidateRows}
    </div>`;
}
