// copilot.js - the AI Co-pilot tab: English -> workload, and the verified auto-tuner.

const EXAMPLES = [
  "A busy database server while the nightly backup runs every 800 ms",
  "Gaming PC: a game loading levels, a web browser, and Windows update installing in the background",
  "University file server during exam week with heavy logging and an antivirus scan",
  "Video editing workstation rendering a movie while cloud sync copies files",
];
const PRIO_LABEL = ["HIGH", "MEDIUM", "LOW"];

const Copilot = {
  lastSpec: null,

  init(status) {
    const ex = document.getElementById("c-examples");
    ex.innerHTML = EXAMPLES.map(e => `<span class="chip ex">${esc(e)}</span>`).join("");
    ex.onclick = e => { if (e.target.classList.contains("ex")) document.getElementById("c-text").value = e.target.textContent; };
    document.getElementById("c-generate").onclick = () => this.generate();
    document.getElementById("c-tune").onclick = () => this.tune();
    const sel = document.getElementById("c-objective");
    sel.innerHTML = Object.entries(status.objectives || {}).map(([k, v]) =>
      `<option value="${k}" ${k === "balanced" ? "selected" : ""}>${esc(v)}</option>`).join("");
    document.addEventListener("disk-workload", e => this.showWorkload(e.detail));
    this.showWorkload(Disk.currentWorkload());
  },

  useLlm() { return document.getElementById("c-use-llm").checked; },

  showWorkload(w) {
    document.getElementById("c-tune-workload").textContent = w.label;
  },

  engineLine(res) {
    return `<div class="engine">Answered by <b>${esc(res.engine)}</b>` +
      (res.fallback_reason ? ` · Claude was not used: ${esc(res.fallback_reason)}` : "") + "</div>";
  },

  async generate() {
    const text = document.getElementById("c-text").value;
    const out = document.getElementById("c-scenario-out"), btn = document.getElementById("c-generate");
    btn.disabled = true;
    out.innerHTML = `<div class="out"><span class="spinner"></span>Designing the workload…</div>`;
    try {
      const res = await api("/api/copilot/scenario", { text, use_llm: this.useLlm() });
      this.lastSpec = res.spec;
      const s = res.spec;
      const procRows = s.processes.map(p => `<tr><td>${esc(p.name)}</td><td><span class="prio p${p.priority}">${PRIO_LABEL[p.priority]}</span></td>
        <td class="num">${p.rate} req/s</td><td>cyl ${p.region[0]}–${p.region[1]}</td><td class="reason">${esc(p.why)}</td></tr>`).join("");
      const burstRows = s.bursts.map(b => `<tr><td>${esc(b.name)} <span class="tag">burst</span></td><td><span class="prio p${b.priority}">${PRIO_LABEL[b.priority]}</span></td>
        <td class="num">${b.size} every ${b.every_ms} ms</td><td>cyl ${b.region[0]}–${b.region[1]}</td><td class="reason">${esc(b.why)}</td></tr>`).join("");
      out.innerHTML = `<div class="out">
        ${this.engineLine(res)}
        <h4>${esc(s.title)}</h4><p class="muted">${esc(s.summary)}</p>
        ${res.warnings.length ? `<div class="warnings">⚠ ${res.warnings.map(esc).join("<br>⚠ ")}</div>` : ""}
        <table><tr><th>Process</th><th>Priority</th><th class="num">Load</th><th>Disk region</th><th>Why</th></tr>${procRows}${burstRows}</table>
        <p class="muted">Steady load ${res.load.steady_rate} req/s + bursts ${res.load.burst_rate} req/s on average
          (the disk can serve roughly 200 req/s).</p>
        <div class="actions"><button class="primary" id="c-run">▶ Run it in the Disk Lab</button>
          <button id="c-run-tune">Tune PA-SCAN-BT for it</button></div></div>`;
      document.getElementById("c-run").onclick = () => this.runInLab();
      document.getElementById("c-run-tune").onclick = () => { this.runInLab(false); this.tune(); };
    } catch (e) {
      out.innerHTML = `<div class="out warnings">${esc(e.message)}</div>`;
    } finally { btn.disabled = false; }
  },

  runInLab(switchTab = true) {
    if (!this.lastSpec) return;
    Disk.useCustomSpec(this.lastSpec, this.lastSpec.title.replace(/^Workload: /, ""));
    if (switchTab) { Tabs.show("disk"); setTimeout(() => Disk.player.play(), 300); }
  },

  async tune() {
    const { workload, label } = Disk.currentWorkload();
    if (workload.scenario === "demo") { toast("The 14-request demo is too small to tune; pick another scenario"); return; }
    const out = document.getElementById("c-tune-out"), btn = document.getElementById("c-tune");
    const objective = document.getElementById("c-objective").value;
    btn.disabled = true;
    out.innerHTML = `<div class="out"><span class="spinner"></span>Tuning for <b>${esc(label)}</b>: measuring references, running the grid search` +
      (this.useLlm() ? ", asking Claude for ideas" : "") + ", then verifying every candidate on unseen workloads…</div>";
    try {
      const res = await api("/api/copilot/tune", { workload, objective, use_llm: this.useLlm() });
      const rows = res.candidates.map((c, i) => {
        const ok = c.verdict.startsWith("accepted"), ref = c.verdict === "reference";
        return `<tr class="${i === res.recommended ? "rec" : ""}">
          <td>${esc(c.source)}${i === res.recommended ? " ★" : ""}</td>
          <td class="num">${c.k}</td><td class="num">${c.deadline}</td><td class="num">${c.aging}</td>
          <td class="num">${fmt(c.tune_score)}</td><td class="num">${fmt(c.holdout_score)}</td>
          <td class="num">${fmt(c.holdout.p99_HIGH)}</td><td class="num">${fmt(c.holdout.avg_wait)}</td>
          <td class="${ref ? "" : ok ? "verdict-ok" : "verdict-no"}">${esc(c.verdict)}</td></tr>
          <tr><td colspan="9" class="reason">${esc(c.reasoning)}</td></tr>`;
      }).join("");
      const best = res.candidates[res.recommended];
      const ref = res.reference;
      out.innerHTML = `<div class="out">
        ${this.engineLine(res)}
        <p><b>Objective:</b> ${esc(res.objective)}<br>
          <span class="muted">Score = lower is better. Tuned on seeds ${res.seeds.tuning.join(", ")}; verdicts come from
          unseen seeds ${res.seeds.held_out.join(", ")}. ${res.simulations} simulations in ${res.seconds} s.
          For reference on the unseen seeds: SCAN has HIGH p99 ${fmt(ref.SCAN.p99_HIGH)} ms and avg wait ${fmt(ref.SCAN.avg_wait)} ms;
          LOOK has ${fmt(ref.LOOK.p99_HIGH)} ms and ${fmt(ref.LOOK.avg_wait)} ms.</span></p>
        <table><tr><th>Candidate</th><th class="num">K</th><th class="num">Deadline</th><th class="num">Aging</th>
          <th class="num">Score (tuning)</th><th class="num">Score (unseen)</th><th class="num">HIGH p99</th><th class="num">Avg wait</th><th>Verdict</th></tr>
          ${rows}</table>
        <div class="actions"><button class="primary" id="c-apply">Apply ★ (K=${best.k}, deadline=${best.deadline}, aging=${best.aging}) in the Disk Lab</button></div>
      </div>`;
      document.getElementById("c-apply").onclick = () => {
        Disk.applySettings({ k: best.k, deadline: best.deadline, aging: best.aging });
        Tabs.show("disk");
      };
    } catch (e) {
      out.innerHTML = `<div class="out warnings">${esc(e.message)}</div>`;
    } finally { btn.disabled = false; }
  },
};

// ---------------------------------------------------------------- boot
// Optional URL parameters (handy as bookmarks for a presentation):
//   ?tab=disk|llm|copilot|about   &scenario=burst   &t=2500 (jump to this time, ms)
//   &inject=burst@1500,pagefault@2000   (disk) or flood@4000,chat@5000 (llm)
//   ?tab=copilot&ask=<description>&tune=balanced   (runs the co-pilot straight away)
window.addEventListener("error", e => toast("Script error: " + e.message));
document.addEventListener("DOMContentLoaded", async () => {
  const q = new URLSearchParams(location.search);
  const tab = q.get("tab") || "disk", t = +q.get("t") || 0;
  const injections = (q.get("inject") || "").split(",").filter(Boolean)
    .map(s => { const [kind, at] = s.split("@"); return { kind, t: +at || 0 }; });
  const status = await loadStatus();
  const lab = tab === "llm" ? Llm : Disk;
  if (q.get("scenario")) document.getElementById(tab === "llm" ? "l-scenario" : "d-scenario").value = q.get("scenario");
  Disk.init(status);
  Llm.init(status);
  Copilot.init(status);
  if (tab === "disk" || tab === "llm") {
    lab.applyControls(false);                // read the controls (and the ?scenario value) without loading
    lab.injections = injections;
    await lab.load(false);
  }
  Tabs.show(tab);
  if (t && lab.data) lab.player.seek(t);
  if (q.get("ask")) {
    document.getElementById("c-text").value = q.get("ask");
    await Copilot.generate();
    if (q.get("tune")) { document.getElementById("c-objective").value = q.get("tune"); Copilot.runInLab(false); }
  }
  if (q.get("tune")) await Copilot.tune();
});
