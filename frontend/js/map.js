// map.js — D3 map rendering and interaction
import { fetchConstituency } from "./api.js";
import { openPanel, closePanel } from "./panel.js";

let svg, g, zoom, path;
let constituencyData = {};   // const_no → API row
let activeFilter = null;     // party abbr currently filtered, null = all

export function initMap(geoJson, constituencies) {
  // Index election data by const_no
  constituencies.forEach(c => { constituencyData[c.const_no] = c; });

  const wrap = document.getElementById("map-wrap");
  const W = wrap.clientWidth, H = wrap.clientHeight;

  svg  = d3.select("#map");
  const proj = d3.geoMercator().fitExtent([[20, 20], [W - 20, H - 20]], geoJson);
  path = d3.geoPath().projection(proj);

  zoom = d3.zoom()
    .scaleExtent([0.7, 30])
    .on("zoom", ev => {
      g.attr("transform", ev.transform);
      const s = ev.transform.k;
      d3.selectAll(".c-path")
        .style("stroke-width", (0.5 / s) + "px");
      d3.selectAll(".c-label")
        .style("display", s >= 4 ? null : "none")
        .style("font-size", (3.5 / s) + "px");
    });

  svg.call(zoom);
  g = svg.append("g");

  // Constituency polygons
  g.selectAll(".c-path")
    .data(geoJson.features)
    .join("path")
    .attr("class", "c-path")
    .attr("d", path)
    .attr("fill", d => fillColor(d))
    .on("mousemove", (ev, d) => showTooltip(ev, d))
    .on("mouseleave", hideTooltip)
    .on("click", (ev, d) => { ev.stopPropagation(); onConstClick(d); });

  // Labels — visible only when zoomed in
  g.selectAll(".c-label")
    .data(geoJson.features)
    .join("text")
    .attr("class", "c-label")
    .attr("x", d => path.centroid(d)[0])
    .attr("y", d => path.centroid(d)[1])
    .style("display", "none")
    .text(d => {
      const n = d.properties.AC_NAME || d.properties.NAME || "";
      return n.length > 11 ? n.slice(0, 10) + "…" : n;
    });

  // Click map background = deselect
  svg.on("click", () => { deselect(); closePanel(); });

  // Zoom controls
  document.getElementById("btn-in").onclick  = () => svg.transition().duration(300).call(zoom.scaleBy, 1.6);
  document.getElementById("btn-out").onclick = () => svg.transition().duration(300).call(zoom.scaleBy, 0.625);
  document.getElementById("btn-rst").onclick = () => svg.transition().duration(500).call(zoom.transform, d3.zoomIdentity);

  // Handle window resize
  window.addEventListener("resize", () => {
    const nw = wrap.clientWidth, nh = wrap.clientHeight;
    const np = d3.geoMercator().fitExtent([[20, 20],[nw-20,nh-20]], geoJson);
    path = d3.geoPath().projection(np);
    d3.selectAll(".c-path").attr("d", path);
    d3.selectAll(".c-label")
      .attr("x", d => path.centroid(d)[0])
      .attr("y", d => path.centroid(d)[1]);
  });
}

function getElecData(feature) {
  const p   = feature.properties;
  const no  = p.AC_NO  || p.ac_no  || p.CONST_NO;
  const nm  = (p.AC_NAME || p.NAME || "").toUpperCase().trim();
  return constituencyData[no] || Object.values(constituencyData).find(c => c.name.toUpperCase() === nm);
}

function fillColor(feature) {
  const ed = getElecData(feature);
  if (!ed) return "#d4cfca";
  if (activeFilter && ed.winning_party !== activeFilter) return "#e8e4df";
  return ed.color_hex || "#d4cfca";
}

// Called from legend click
export function filterByParty(partyAbbr) {
  activeFilter = activeFilter === partyAbbr ? null : partyAbbr;
  d3.selectAll(".c-path").attr("fill", d => fillColor(d));
  // Update legend active state
  document.querySelectorAll(".leg-row").forEach(el => {
    el.classList.toggle("active", el.dataset.party === activeFilter);
  });
}

function onConstClick(feature) {
  deselect();
  d3.selectAll(".c-path").filter(f => f === feature).classed("selected", true);
  const ed = getElecData(feature);
  const name = feature.properties.AC_NAME || feature.properties.NAME || "";
  const no   = feature.properties.AC_NO   || feature.properties.ac_no;
  openPanel(name, no, ed);
}

function deselect() {
  d3.selectAll(".c-path").classed("selected", false);
}

// ── Tooltip ───────────────────────────────────────────────────
const tip = document.getElementById("tip");

function showTooltip(ev, feature) {
  const ed   = getElecData(feature);
  const name = feature.properties.AC_NAME || feature.properties.NAME || "";
  let html = `<div class="tip-name">${name}</div>`;
  if (ed) {
    html += `<div class="tip-cand">
      <span class="tip-dot" style="background:${ed.color_hex}"></span>
      ${ed.winning_candidate} · <strong>${ed.winning_party}</strong>
    </div>
    <div class="tip-margin">Margin: ${ed.winning_margin?.toLocaleString("en-IN")} votes</div>`;
  } else {
    html += `<div class="tip-cand">No data</div>`;
  }
  tip.innerHTML = html;
  tip.classList.add("show");
  moveTip(ev);
}

document.addEventListener("mousemove", ev => { if (tip.classList.contains("show")) moveTip(ev); });

function moveTip(ev) {
  const vw = window.innerWidth, vh = window.innerHeight;
  const tw = 220, th = 80;
  tip.style.left = (ev.clientX + 14 + tw > vw ? ev.clientX - tw - 10 : ev.clientX + 14) + "px";
  tip.style.top  = (ev.clientY + th > vh ? ev.clientY - th - 10 : ev.clientY + 8) + "px";
}

function hideTooltip() { tip.classList.remove("show"); }
