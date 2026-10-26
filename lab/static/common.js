// common.js - helpers shared by the Disk Lab, the LLM Lab and the AI Co-pilot.
// The browser only DRAWS. Every scheduling decision is made by the Python code
// (scheduler/ and llm_serving/) through the /api endpoints.

// Read colours from CSS custom properties so there is one source of truth.
// Fallbacks match the CYBER OBSIDIAN: ICE CIRCUIT palette in style.css.
function _css(prop, fb) {
  try { return getComputedStyle(document.documentElement).getPropertyValue(prop).trim() || fb; }
  catch { return fb; }
}
const COLORS = {
  get prio() {
    // Cache after first access (DOM must be ready)
    const v = [_css("--hi","#FF2D55"), _css("--mid","#FFC400"), _css("--lo","#8B93FF")];
    Object.defineProperty(this, "prio", { value: v }); return v;
  },
  get hog()      { const v = _css("--burst","#FF3DF2");      Object.defineProperty(this,"hog",{value:v});      return v; },
  get head()     { const v = _css("--cyan","#00E5FF");       Object.defineProperty(this,"head",{value:v});     return v; },
  get arm()      { const v = _css("--ice","#EAF6FF");        Object.defineProperty(this,"arm",{value:v});      return v; },
  get grid()     { const v = "rgba(255,255,255,0.06)";       Object.defineProperty(this,"grid",{value:v});     return v; },
  get axis()     { const v = _css("--text-faint","#586C82"); Object.defineProperty(this,"axis",{value:v});     return v; },
  get text()     { const v = _css("--ice","#EAF6FF");        Object.defineProperty(this,"text",{value:v});     return v; },
  get muted()    { const v = _css("--text-dim","#8EA3B8");   Object.defineProperty(this,"muted",{value:v});    return v; },
  get late()     { const v = _css("--hi","#FF2D55");         Object.defineProperty(this,"late",{value:v});     return v; },
  get panel2()   { const v = _css("--bg-2","#0E1520");       Object.defineProperty(this,"panel2",{value:v});   return v; },
  get bg1()      { const v = _css("--bg-1","#080D14");       Object.defineProperty(this,"bg1",{value:v});      return v; },
  get fontMono() { const v = _css("--font-mono","'JetBrains Mono', monospace"); Object.defineProperty(this,"fontMono",{value:v}); return v; },
  get fontUi()   { const v = _css("--font-ui","'Rajdhani', sans-serif");         Object.defineProperty(this,"fontUi",{value:v});   return v; },
};
const PRIO_NAMES = ["HIGH", "MEDIUM", "LOW"];
const LLM_PRIO_NAMES = ["INTERACTIVE", "STANDARD", "BATCH"];

async function api(path, body) {
  const opts = body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  };
  const res = await fetch(path, opts);
  let json;
  try { json = await res.json(); } catch { throw new Error(`server error ${res.status}`); }
  if (!res.ok) throw new Error(json.error || res.statusText);
  return json;
}

// Same percentile rule as metrics.py, so the browser and the CSV files agree.
function percentile(values, pct) {
  if (!values.length) return NaN;
  const s = [...values].sort((a, b) => a - b);
  const i = Math.max(0, Math.min(s.length - 1, Math.round(pct / 100 * s.length) - 1));
  return s[i];
}
function mean(values) { return values.length ? values.reduce((a, b) => a + b, 0) / values.length : NaN; }
function fmt(x, d = 1) { return Number.isFinite(x) ? x.toFixed(d) : "–"; }
function esc(s) {
  return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Largest index i with arr[i][0] <= t (arr sorted by [0]); -1 if none.
function lastAtOrBefore(arr, t) {
  let lo = 0, hi = arr.length - 1, ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (arr[mid][0] <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return ans;
}

function setupCanvas(canvas, height) {
  const dpr = window.devicePixelRatio || 1;
  const w = Math.max(200, canvas.clientWidth);
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(height * dpr)) {
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(height * dpr);
    canvas.style.height = height + "px";
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, height);
  return { ctx, w, h: height };
}

let toastTimer = null;
function toast(msg, ok = false) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = "toast" + (ok ? " ok" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 4000);
}

// Build the algorithm checkboxes.
function buildChecks(container, names, selected, max, onChange) {
  container.innerHTML = "";
  for (const n of names) {
    const lab = document.createElement("label");
    lab.innerHTML = `<input type="checkbox" value="${esc(n)}" ${selected.includes(n) ? "checked" : ""}> ${esc(n)}`;
    container.appendChild(lab);
  }
  container.addEventListener("change", e => {
    const checked = [...container.querySelectorAll("input:checked")].map(i => i.value);
    if (checked.length > max || checked.length === 0) {
      e.target.checked = !e.target.checked;
      toast(checked.length === 0 ? "Keep at least one selected" : `At most ${max} at once`);
      return;
    }
    onChange(checked);
  });
}

function bindRange(id, onInput) {
  const el = document.getElementById(id), out = document.getElementById(id + "-out");
  el.addEventListener("input", () => { out.textContent = el.value; if (onInput) onInput(+el.value); });
  return el;
}

// Scoreboard: rows = metrics, columns = algorithms; the best value is green.
function renderScoreboard(table, names, rows) {
  let html = "<tr><th>Metric</th>" + names.map(n => `<th>${esc(n)}</th>`).join("") + "</tr>";
  for (const row of rows) {
    const vals = row.values;
    const finite = row.rank === false ? [] : vals.filter(Number.isFinite);   // rank:false = information only
    const best = finite.length > 1 ? (row.higher ? Math.max(...finite) : Math.min(...finite)) : NaN;
    const worst = finite.length > 1 ? (row.higher ? Math.min(...finite) : Math.max(...finite)) : NaN;
    html += `<tr><td>${esc(row.label)}</td>` + vals.map(v => {
      const cls = !Number.isFinite(v) || best === worst ? "" : v === best ? "best" : v === worst ? "worst" : "";
      return `<td class="${cls}">${row.format ? row.format(v) : fmt(v)}</td>`;
    }).join("") + "</tr>";
  }
  table.innerHTML = html;
}

// A simple playback clock. `lab` must provide end(), frame(T) and onEnd().
class Player {
  constructor(lab, playBtn) {
    this.lab = lab; this.btn = playBtn; this.T = 0; this.speed = 0.1; this.playing = false; this.last = null;
    this.tick = this.tick.bind(this);
  }
  play() {
    if (this.T >= this.lab.end()) this.T = 0;
    this.playing = true; this.last = null; this.btn.textContent = "❚❚ Pause";
    requestAnimationFrame(this.tick);
  }
  pause() { this.playing = false; this.btn.textContent = "▶ Play"; }
  toggle() { this.playing ? this.pause() : this.play(); }
  seek(T) { this.T = Math.max(0, Math.min(T, this.lab.end())); this.lab.frame(this.T, true); }
  tick(now) {
    if (!this.playing) return;
    if (this.last !== null) {
      const dt = Math.min(100, now - this.last);         // ms of wall-clock; cap after tab switches
      this.T += dt * this.speed;
      if (this.T >= this.lab.end()) { this.T = this.lab.end(); this.pause(); }
    }
    this.last = now;
    this.lab.frame(this.T, false);
    if (this.playing) requestAnimationFrame(this.tick);
  }
}

// Tabs
const Tabs = {
  listeners: [],
  init() {
    for (const btn of document.querySelectorAll(".tab")) btn.addEventListener("click", () => this.show(btn.dataset.tab));
  },
  show(name) {
    for (const b of document.querySelectorAll(".tab")) b.classList.toggle("active", b.dataset.tab === name);
    for (const p of document.querySelectorAll(".tabpane")) p.classList.toggle("active", p.id === "tab-" + name);
    for (const fn of this.listeners) fn(name);
  },
  onChange(fn) { this.listeners.push(fn); },
};

const Status = { copilot: null, objectives: {} };
async function loadStatus() {
  try {
    const s = await api("/api/status");
    Object.assign(Status, s);
    const badge = document.getElementById("copilot-badge");
    badge.textContent = "co-pilot: " + s.copilot.reason;
    badge.classList.toggle("on", s.copilot.online);
    badge.title = s.copilot.reason;
  } catch (e) { toast("Cannot reach the lab server: " + e.message); }
  return Status;
}

const ThemeManager = {
  init() {
    let t = "ice";
    try { t = localStorage.getItem("pa-scan-theme") || "ice"; } catch {}
    this.set(t);
    document.querySelectorAll("[data-set-theme]").forEach(b => {
      b.addEventListener("click", () => this.set(b.dataset.setTheme));
    });
  },
  set(theme) {
    if (!theme || theme === "ice") {
      document.documentElement.removeAttribute("data-theme");
    } else {
      document.documentElement.setAttribute("data-theme", theme);
    }
    try { localStorage.setItem("pa-scan-theme", theme || "ice"); } catch {}
    document.querySelectorAll("[data-set-theme]").forEach(b => {
      b.classList.toggle("active", (b.dataset.setTheme || "ice") === (theme || "ice"));
    });
  }
};

document.addEventListener("DOMContentLoaded", () => {
  Tabs.init();
  ThemeManager.init();
});
