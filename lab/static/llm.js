// llm.js - the LLM Serving Lab: the same three rules scheduling a continuous-batching LLM server.
//
// Each lane shows, for one policy at time T:
//   - the GPU BATCH: 32 slots; a coloured cell is a running request, its fill = output progress
//   - the WAITING requests stacked above their prefix id (the "cylinders" of this problem)
//   - ▲ the sweep head (the prefix the elevator admitted last), for the sweep policies

const TENANT_BANDS = [            // prefix ranges of the built-in tenants (llm_serving/workloads.py)
  [0, 3, 0], [4, 7, 0], [8, 23, 1], [24, 25, 2], [26, 37, 1], [38, 45, 1], [46, 53, 2], [54, 63, 2],
];

const Llm = {
  data: null, R: null, runs: [],
  algorithms: ["PREFIX-SWEEP", "PA-SWEEP-BT"],
  workload: { scenario: "flood", seed: 1 },
  settings: { k: 3, deadline: 300 },
  injections: [],
  busy: false, lastUi: -1, logT: -1,
  player: null,

  init(status) {
    this.player = new Player(this, document.getElementById("l-play"));
    buildChecks(document.getElementById("l-algos"), status.llm_policies || ["FCFS", "PRIORITY", "FAIR-SHARE", "PREFIX-SWEEP", "PA-SWEEP-BT"],
      this.algorithms, 4, names => { this.algorithms = names; this.load(false); });
    bindRange("l-k"); bindRange("l-deadline");
    document.getElementById("l-play").onclick = () => this.player.toggle();
    document.getElementById("l-restart").onclick = () => { this.player.seek(0); this.player.play(); };
    document.getElementById("l-speed").onchange = e => { this.player.speed = +e.target.value; };
    document.getElementById("l-apply").onclick = () => this.applyControls();
    document.getElementById("l-scenario").onchange = () => this.applyControls();
    document.getElementById("l-seed").onchange = () => this.applyControls();
    document.getElementById("l-inj-flood").onclick = () => this.inject("flood");
    document.getElementById("l-inj-chat").onclick = () => this.inject("chat");
    const scrub = document.getElementById("l-scrub");
    scrub.addEventListener("input", () => { this.player.pause(); this.player.seek(scrub.value / 1000 * this.end()); });
    window.addEventListener("resize", () => this.data && this.frame(this.player.T, true));
    Tabs.onChange(name => {
      if (name !== "llm") this.player.pause();
      else if (!this.data) this.load(false); else this.frame(this.player.T, true);
    });
    this.player.speed = +document.getElementById("l-speed").value;
  },

  applyControls(reload = true) {
    this.workload = { scenario: document.getElementById("l-scenario").value, seed: +document.getElementById("l-seed").value || 1 };
    this.settings = { k: +document.getElementById("l-k").value, deadline: +document.getElementById("l-deadline").value };
    this.injections = [];
    if (reload) this.load(false);
  },

  async inject(kind) {
    if (!this.data || this.busy) return;
    this.injections.push({ kind, t: +this.player.T.toFixed(3) });
    await this.load(true);
    toast(kind === "flood" ? `🌊 30 BATCH requests flooded in at t = ${(this.player.T / 1000).toFixed(2)} s`
                           : `💬 5 chat users arrived at t = ${(this.player.T / 1000).toFixed(2)} s`, true);
  },

  async load(keepTime) {
    this.busy = true;
    for (const id of ["l-inj-flood", "l-inj-chat", "l-apply"]) document.getElementById(id).disabled = true;
    try {
      const data = await api("/api/llm/run", {
        algorithms: this.algorithms, workload: this.workload, settings: this.settings, injections: this.injections,
      });
      this.prepare(data);
      if (!keepTime) { this.player.pause(); this.player.T = 0; }
      this.frame(this.player.T, true);
    } catch (e) {
      toast("LLM Lab: " + e.message);
      if (keepTime) this.injections.pop();
    } finally {
      this.busy = false;
      for (const id of ["l-inj-flood", "l-inj-chat", "l-apply"]) document.getElementById(id).disabled = false;
    }
  },

  prepare(data) {
    this.data = data;
    const n = data.requests.length;
    const R = { tenant: new Int32Array(n), prio: new Int8Array(n), arr: new Float64Array(n), prefix: new Int32Array(n), flood: new Uint8Array(n) };
    const flood = new Set(data.flood_tenants);
    for (const [id, tenant, prio, arr, prefix] of data.requests) {
      R.tenant[id] = tenant; R.prio[id] = prio; R.arr[id] = arr; R.prefix[id] = prefix; R.flood[id] = flood.has(tenant) ? 1 : 0;
    }
    this.R = R;
    this.runs = data.runs.map(run => {
      // Give every stay in the batch a fixed slot, so cells do not jump around.
      const segs = run.segments.map(([id, a, b]) => ({ id, a, b, slot: 0 }));
      const events = [];
      segs.forEach((s, i) => { events.push([s.a, 1, i]); events.push([s.b, 0, i]); });
      events.sort((p, q) => p[0] - q[0] || p[1] - q[1]);     // leaving before joining at the same instant
      const free = [...Array(data.max_seqs).keys()];
      for (const [, kind, i] of events) {
        if (kind === 1) { free.sort((p, q) => p - q); segs[i].slot = free.length ? free.shift() : 0; }
        else free.push(segs[i].slot);
      }
      const preempts = segs.filter(s => s.b < run.finish[s.id] - 1e-6).map(s => s.b).sort((p, q) => p - q);
      const order = [...Array(n).keys()].sort((p, q) => run.first[p] - run.first[q]);
      const hitMap = new Uint8Array(n);
      if (run.admissions) {
        for (const adm of run.admissions) if (adm[2]) hitMap[adm[1]] = 1;
      }
      return { ...run, segs, preempts, order, hitMap, statT: Infinity };
    });
    this.buildLanes();
    this.logT = -1;
  },

  end() { return this.data ? Math.max(this.data.duration, ...this.runs.map(r => r.makespan)) : 1; },

  buildLanes() {
    const box = document.getElementById("l-lanes");
    box.innerHTML = "";
    for (const run of this.runs) {
      const ours = run.name === "PA-SWEEP-BT";
      const lane = document.createElement("div");
      lane.className = "lane" + (ours ? " hero" : "");
      lane.innerHTML = `<header><span class="name">${esc(run.name)}</span>
        <span class="tag">${ours ? "our policy" : run.name === "PREFIX-SWEEP" ? "baseline" : "reference"}</span>
        <div class="chips"></div></header><canvas></canvas>`;
      box.appendChild(lane);
      run.canvas = lane.querySelector("canvas");
      run.chips = lane.querySelector(".chips");
    }
  },

  stats(run, T) {
    if (T < run.statT) {
      run.p = 0; run.pa = 0; run.pp = 0; run.statT = 0;
      run.st = { prio: [[], [], []], normal: [], flood: [], slo: [0, 0], hits: 0, adm: 0, preempt: 0, done: 0 };
    }
    const R = this.R, st = run.st, slo = this.data.slo;
    while (run.p < run.order.length && run.first[run.order[run.p]] <= T) {
      const id = run.order[run.p++], ttft = run.first[id] - R.arr[id];
      st.prio[R.prio[id]].push(ttft);
      (R.flood[id] ? st.flood : st.normal).push(ttft);
      if (R.prio[id] === 0 && ttft <= slo.INTERACTIVE) st.slo[0]++;
      if (R.prio[id] === 1 && ttft <= slo.STANDARD) st.slo[1]++;
    }
    while (run.pa < run.admissions.length && run.admissions[run.pa][0] <= T) { st.hits += run.admissions[run.pa][2]; st.adm++; run.pa++; }
    while (run.pp < run.preempts.length && run.preempts[run.pp] <= T) { st.preempt++; run.pp++; }
    run.statT = T;
    return st;
  },

  frame(T, force) {
    if (!this.data) return;
    for (const run of this.runs) this.drawLane(run, T);
    document.getElementById("l-clock").textContent = `t = ${(T / 1000).toFixed(2)} s`;
    const scrub = document.getElementById("l-scrub");
    if (document.activeElement !== scrub) scrub.value = Math.round(T / this.end() * 1000);
    const now = performance.now();
    if (force || now - this.lastUi > 200) { this.lastUi = now; this.updateUi(T, force); }
  },

  drawLane(run, T) {
    const { ctx, w, h } = setupCanvas(run.canvas, 186);
    const R = this.R, n = R.prio.length, P = this.data.num_prefixes;
    const colorOf = id => R.flood[id] ? COLORS.hog : COLORS.prio[R.prio[id]];
    ctx.font = "11px " + COLORS.fontMono;

    // ---- GPU batch grid (occupied = priority colour, cache hit = thin white inner border)
    const cols = 8, cell = 24, gap = 4, gx = 8, gy = 24;
    const inBatch = new Uint8Array(n);
    let running = 0;
    for (let s = 0; s < this.data.max_seqs; s++) {
      const cx = gx + (s % cols) * (cell + gap), cy = gy + Math.floor(s / cols) * (cell + gap);
      ctx.fillStyle = COLORS.panel2; ctx.strokeStyle = "#1C2B3D"; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.roundRect(cx, cy, cell, cell, 2); ctx.fill(); ctx.stroke();
    }
    for (const seg of run.segs) {
      if (!(seg.a <= T && T < seg.b)) continue;
      inBatch[seg.id] = 1; running++;
      const s = seg.slot, cx = gx + (s % cols) * (cell + gap), cy = gy + Math.floor(s / cols) * (cell + gap);
      const f = run.first[seg.id], fin = run.finish[seg.id];
      const prog = T < f ? 0.06 : Math.min(1, (T - f) / Math.max(1, fin - f));
      const col = colorOf(seg.id);
      ctx.fillStyle = col + "33";
      ctx.beginPath(); ctx.roundRect(cx, cy, cell, cell, 2); ctx.fill();
      ctx.fillStyle = col;
      ctx.fillRect(cx + 2, cy + cell - 2 - (cell - 4) * prog, cell - 4, (cell - 4) * prog);
      ctx.strokeStyle = col; ctx.lineWidth = 1.2;
      ctx.beginPath(); ctx.roundRect(cx, cy, cell, cell, 2); ctx.stroke();
      if (run.hitMap && run.hitMap[seg.id]) {
        // cache hit: thin white inner border
        ctx.strokeStyle = "#FFFFFF"; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.roundRect(cx + 2, cy + 2, cell - 4, cell - 4, 1); ctx.stroke();
      }
    }
    run.running = running;
    ctx.font = "11px " + COLORS.fontUi;
    ctx.fillStyle = COLORS.muted; ctx.textAlign = "left";
    ctx.fillText(`GPU batch  ${running}/${this.data.max_seqs}`, gx, 14);

    // ---- waiting requests by prefix id
    const L = gx + cols * (cell + gap) + 36, RM = 12, plotW = w - L - RM, base = 136;
    const colW = plotW / P, x = p => L + (p + 0.5) * colW;
    const r = Math.max(1.6, Math.min(3.2, colW / 2.4)), step = 2 * r + 0.8, maxStack = Math.floor((base - 22) / step);
    const stacks = new Array(P).fill(null).map(() => []);
    const waitCount = [0, 0, 0];
    for (let id = 0; id < n; id++) {
      if (R.arr[id] <= T && run.finish[id] > T && !inBatch[id]) { stacks[R.prefix[id]].push(id); waitCount[R.prio[id]]++; }
    }
    run.waitCount = waitCount;
    for (let p = 0; p < P; p++) {
      const st = stacks[p].sort((a, b) => R.prio[a] - R.prio[b]);
      for (let k = 0; k < Math.min(st.length, maxStack); k++) {
        const id = st[k];
        const py = base - r - k * step;
        const prio = R.prio[id];
        const isFlood = R.flood[id];
        if (isFlood) {
          ctx.fillStyle = COLORS.hog;
          ctx.fillRect(x(p) - r, py - r, r * 2, r * 2);
        } else if (prio === 0) {
          // INTERACTIVE: ▲ marker with #FF2D55 fill + white outline
          ctx.fillStyle = COLORS.prio[0];
          ctx.beginPath();
          ctx.moveTo(x(p), py - r - 0.5);
          ctx.lineTo(x(p) - r - 0.5, py + r);
          ctx.lineTo(x(p) + r + 0.5, py + r);
          ctx.closePath();
          ctx.fill();
          ctx.strokeStyle = "#FFFFFF";
          ctx.lineWidth = 1.4;
          ctx.stroke();
        } else if (prio === 1) {
          // STANDARD: ● marker with #F5F5F7 fill
          ctx.fillStyle = COLORS.prio[1];
          ctx.beginPath(); ctx.arc(x(p), py, r, 0, 7); ctx.fill();
        } else {
          // BATCH: ▽ marker with #7C8296 fill
          ctx.fillStyle = COLORS.prio[2];
          ctx.beginPath();
          ctx.moveTo(x(p) - r, py - r);
          ctx.lineTo(x(p) + r, py - r);
          ctx.lineTo(x(p), py + r + 0.5);
          ctx.closePath();
          ctx.fill();
        }
      }
      if (st.length > maxStack) { ctx.fillStyle = COLORS.text; ctx.textAlign = "center"; ctx.fillText(`+${st.length - maxStack}`, x(p), 12); }
    }
    // axis + tenant bands (which prefixes belong to which priority class)
    ctx.strokeStyle = COLORS.axis; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(L, base + 1); ctx.lineTo(L + plotW, base + 1); ctx.stroke();
    for (const [a, b, prio] of TENANT_BANDS) {
      ctx.fillStyle = (a === 24 ? COLORS.hog : COLORS.prio[prio]) + "88";
      ctx.fillRect(L + a * colW + 1, base + 4, (b - a + 1) * colW - 2, 3);
    }
    ctx.font = "11px " + COLORS.fontMono;
    ctx.fillStyle = COLORS.muted; ctx.textAlign = "center";
    for (const p of [0, 16, 32, 48, 63]) ctx.fillText(p, x(p), base + 30);
    ctx.font = "11px " + COLORS.fontUi;
    ctx.textAlign = "left";
    ctx.fillText("prefix id →", L, h - 4);
    ctx.fillText(`waiting: ${waitCount[0]} interactive · ${waitCount[1]} standard · ${waitCount[2]} batch`, L + 70, h - 4);

    // sweep head
    if (run.head.length) {
      const i = lastAtOrBefore(run.head, T);
      if (i >= 0) {
        const hx = x(run.head[i][1]);
        ctx.save();
        ctx.shadowColor = COLORS.head; ctx.shadowBlur = 8;
        ctx.fillStyle = COLORS.head;
        ctx.beginPath(); ctx.moveTo(hx, base + 9); ctx.lineTo(hx - 6, base + 19); ctx.lineTo(hx + 6, base + 19); ctx.fill();
        ctx.restore();
      }
    }
  },

  updateUi(T, force) {
    const S = this.runs.map(run => this.stats(run, T));
    const sloPct = (st, k) => st.prio[k].length ? 100 * st.slo[k] / st.prio[k].length : NaN;
    this.runs.forEach((run, i) => {
      const st = S[i];
      run.chips.innerHTML = [
        `chat TTFT avg <b>${fmt(mean(st.prio[0]), 0)}</b> ms`,
        `<span class="chip chip-inverted">chat p99 <b>${fmt(percentile(st.prio[0], 99), 0)}</b> ms</span>`,
        `<span class="chip chip-inverted">chat ≤ ${this.data.slo.INTERACTIVE} ms <b>${fmt(sloPct(st, 0), 0)}%</b></span>`,
        `cache hits <b>${fmt(st.adm ? 100 * st.hits / st.adm : NaN, 0)}%</b>`,
        `preempted <b>${st.preempt}</b>`,
      ].map(c => c.startsWith("<span class=\"chip") ? c : `<span class="chip">${c}</span>`).join("");
    });
    const hasFlood = S.some(s => s.flood.length);
    const rows = [
      { label: "INTERACTIVE avg TTFT (ms)", values: S.map(s => mean(s.prio[0])) },
      { label: "INTERACTIVE p99 TTFT (ms)", values: S.map(s => percentile(s.prio[0], 99)) },
      { label: `INTERACTIVE within ${this.data.slo.INTERACTIVE} ms (%)`, values: S.map(s => sloPct(s, 0)), higher: true },
      { label: "STANDARD avg TTFT (ms)", values: S.map(s => mean(s.prio[1])) },
      { label: "STANDARD p99 TTFT (ms)", values: S.map(s => percentile(s.prio[1], 99)) },
      { label: "BATCH avg TTFT (ms)", values: S.map(s => mean(s.prio[2])) },
    ];
    if (hasFlood) {
      rows.push({ label: "Non-flooding tenants avg TTFT (ms)", values: S.map(s => mean(s.normal)) });
      rows.push({ label: "Flooding tenant avg TTFT (ms)", values: S.map(s => mean(s.flood)), rank: false });
    }
    rows.push(
      { label: "Prefix-cache hit rate (%)", values: S.map(s => s.adm ? 100 * s.hits / s.adm : NaN), higher: true },
      { label: "Preemptions", values: S.map(s => s.preempt), rank: false, format: v => fmt(v, 0) },
      { label: "Requests with first token", values: S.map(s => s.prio[0].length + s.prio[1].length + s.prio[2].length),
        higher: true, format: v => fmt(v, 0) },
    );
    renderScoreboard(document.getElementById("l-table"), this.runs.map(r => r.name), rows);
    this.updateLog(T, force);
  },

  updateLog(T, force) {
    const ul = document.getElementById("l-log"), R = this.R, tenants = this.data.tenants;
    const multi = this.runs.filter(r => r.decisions.length).length > 1;
    if (force || T < this.logT) { ul.innerHTML = ""; this.runs.forEach(r => { r.d = 0; }); }
    const fresh = [];
    this.runs.forEach((run, ri) => {
      while (run.d < run.decisions.length && run.decisions[run.d][0] <= T) fresh.push([ri, run.d++]);
    });
    fresh.sort((a, b) => this.runs[a[0]].decisions[a[1]][0] - this.runs[b[0]].decisions[b[1]][0]);
    for (const [ri, di] of fresh.slice(-200)) {
      const [t, id, note] = this.runs[ri].decisions[di];
      const guard = note.includes("GUARD"), pre = note.match(/preempt #(\d+) \((\w+)\)/);
      const tenant = tenants[R.tenant[id]] ? tenants[R.tenant[id]][0] : `tenant ${R.tenant[id]}`;
      const li = document.createElement("li");
      li.className = guard ? (pre ? "preempt" : "guard") : "throttle";
      const skipped = (note.match(/(\d+) request\(s\) ahead deferred/) || [])[1];
      li.innerHTML = `<span class="t">${(t / 1000).toFixed(3)} s</span>${multi ? `[${esc(this.runs[ri].name)}] ` : ""}` +
        (guard ? `<span class="k">GUARD</span> admit #${id} (${esc(tenant)}) after ${(t - R.arr[id]).toFixed(0)} ms` +
                 (pre ? ` · <span class="k">PREEMPT</span> #${pre[1]} (${pre[2]})` : "")
               : `<span class="k">THROTTLE</span> skipped ${skipped || "some"} over-quota request(s) · admitted #${id} (${esc(tenant)})`);
      ul.prepend(li);
    }
    while (ul.children.length > 200) ul.lastChild.remove();
    this.logT = T;
  },
};
