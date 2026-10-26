// disk.js - the Disk Lab: SCAN vs PA-SCAN-BT (or any 4 algorithms) animated side by side.
//
// Each lane shows, for one algorithm at the current time T:
//   - the QUEUE: waiting requests stacked above their cylinder
//   - the PLATTER with the arm's current position
//   - a WATERFALL of the last few hundred ms: the arm's path (time runs downward),
//     served requests as dots, and every HIGH request's wait as a vertical bar that
//     turns red once it is past its deadline. SCAN grows long red bars; PA-SCAN-BT should not.

const Disk = {
  data: null, R: null, runs: [],
  algorithms: ["SCAN", "PA-SCAN-BT"],
  workload: { scenario: "burst", seed: 1 },
  workloadLabel: "burst (built-in)",
  settings: { k: 4, deadline: 40, aging: 150 },
  injections: [],
  busy: false,
  window: 250,                 // ms of history shown in the waterfall
  lastUi: -1, lastT: 0, logT: -1,
  player: null,

  init(status) {
    this.player = new Player(this, document.getElementById("d-play"));
    buildChecks(document.getElementById("d-algos"), status.disk_algorithms || ["FCFS", "SSTF", "SCAN", "C-SCAN", "LOOK", "PA-SCAN-BT"],
      this.algorithms, 4, names => { this.algorithms = names; this.load(false); });
    bindRange("d-k"); bindRange("d-deadline"); bindRange("d-aging");

    document.getElementById("d-play").onclick = () => this.player.toggle();
    document.getElementById("d-restart").onclick = () => { this.player.seek(0); this.player.play(); };
    document.getElementById("d-speed").onchange = e => { this.player.speed = +e.target.value; };
    document.getElementById("d-apply").onclick = () => this.applyControls();
    document.getElementById("d-scenario").onchange = () => this.applyControls();
    document.getElementById("d-seed").onchange = () => this.applyControls();
    document.getElementById("d-inj-burst").onclick = () => this.inject("burst");
    document.getElementById("d-inj-fault").onclick = () => this.inject("pagefault");
    const scrub = document.getElementById("d-scrub");
    scrub.addEventListener("input", () => { this.player.pause(); this.player.seek(scrub.value / 1000 * this.end()); });
    window.addEventListener("resize", () => this.data && this.frame(this.player.T, true));
    Tabs.onChange(name => {
      if (name !== "disk") this.player.pause();
      else if (!this.data) this.load(false); else this.frame(this.player.T, true);
    });

    this.player.speed = +document.getElementById("d-speed").value;
  },

  // ------------------------------------------------------------ controls
  applyControls(reload = true) {
    const sc = document.getElementById("d-scenario").value;
    const seed = +document.getElementById("d-seed").value || 1;
    if (sc === "custom") this.workload = { spec: this.workload.spec, seed };
    else {
      this.workload = { scenario: sc, seed };
      this.workloadLabel = `${sc} (built-in)`;
      document.getElementById("d-custom-note").classList.add("hidden");
    }
    if (sc === "demo") {                       // the viva walkthrough: K = 3, slow, whole run visible
      this.setSlider("d-k", 3);
      document.getElementById("d-speed").value = "0.02"; this.player.speed = 0.02;
      this.window = 100;
    } else this.window = 250;
    this.settings = { k: +document.getElementById("d-k").value, deadline: +document.getElementById("d-deadline").value,
                      aging: +document.getElementById("d-aging").value };
    this.injections = [];
    if (reload) this.load(false);
    document.dispatchEvent(new CustomEvent("disk-workload", { detail: this.currentWorkload() }));
  },
  setSlider(id, v) { const el = document.getElementById(id); el.value = v; document.getElementById(id + "-out").textContent = v; },

  // Used by the co-pilot.
  useCustomSpec(spec, label) {
    const opt = document.querySelector('#d-scenario option[value="custom"]');
    opt.disabled = false; opt.textContent = "Custom: " + label.slice(0, 40);
    document.getElementById("d-scenario").value = "custom";
    this.workload = { spec, seed: +document.getElementById("d-seed").value || 1 };
    this.workloadLabel = label;
    const note = document.getElementById("d-custom-note");
    note.textContent = "Custom workload from the AI Co-pilot: " + label;
    note.classList.remove("hidden");
    this.applyControls();
  },
  applySettings(s) {
    this.setSlider("d-k", s.k); this.setSlider("d-deadline", s.deadline); this.setSlider("d-aging", s.aging);
    if (!this.algorithms.includes("PA-SCAN-BT")) this.algorithms = [...this.algorithms.slice(0, 3), "PA-SCAN-BT"];
    this.applyControls();
  },
  currentWorkload() { return { workload: this.workload, label: this.workloadLabel }; },

  async inject(kind) {
    if (!this.data || this.busy) return;
    if (this.workload.scenario === "demo") { toast("Pick a non-demo scenario to inject events"); return; }
    this.injections.push({ kind, t: +this.player.T.toFixed(3) });
    await this.load(true);
    toast(kind === "burst" ? `💥 40-request backup burst injected at t = ${this.player.T.toFixed(0)} ms`
                           : `⚡ 3 page faults (HIGH) injected at t = ${this.player.T.toFixed(0)} ms`, true);
  },

  // ------------------------------------------------------------ data
  async load(keepTime) {
    this.busy = true;
    for (const id of ["d-inj-burst", "d-inj-fault", "d-apply"]) document.getElementById(id).disabled = true;
    try {
      const data = await api("/api/disk/run", {
        algorithms: this.algorithms, workload: this.workload, settings: this.settings, injections: this.injections,
      });
      this.prepare(data);
      if (!keepTime) { this.player.pause(); this.player.T = 0; }
      this.frame(this.player.T, true);
    } catch (e) {
      toast("Disk Lab: " + e.message);
      if (keepTime) this.injections.pop();
    } finally {
      this.busy = false;
      for (const id of ["d-inj-burst", "d-inj-fault", "d-apply"]) document.getElementById(id).disabled = false;
    }
  },

  prepare(data) {
    this.data = data;
    const n = data.requests.length;
    const R = { pid: new Int32Array(n), track: new Int32Array(n), arr: new Float64Array(n), prio: new Int8Array(n), hog: new Uint8Array(n) };
    const bursty = new Set(data.bursty);
    for (const [id, pid, track, arr, prio] of data.requests) {
      R.pid[id] = pid; R.track[id] = track; R.arr[id] = arr; R.prio[id] = prio; R.hog[id] = bursty.has(pid) ? 1 : 0;
    }
    this.R = R;
    this.runs = data.runs.map(run => {
      const order = [...Array(n).keys()].sort((a, b) => run.start[a] - run.start[b]);
      const cum = [0];
      for (let i = 1; i < run.trajectory.length; i++) cum.push(cum[i - 1] + Math.abs(run.trajectory[i][1] - run.trajectory[i - 1][1]));
      return { ...run, order, cum, statT: Infinity };
    });
    this.buildLanes();
    this.logT = -1;
  },

  end() {
    if (!this.data) return 1;
    return Math.max(this.data.duration, ...this.runs.map(r => r.makespan));
  },

  buildLanes() {
    const box = document.getElementById("d-lanes");
    box.innerHTML = "";
    for (const run of this.runs) {
      const lane = document.createElement("div");
      const ours = run.name === "PA-SCAN-BT";
      lane.className = "lane" + (ours ? " hero" : "");
      lane.innerHTML = `<header><span class="name">${esc(run.name)}</span>
        <span class="tag">${ours ? "our algorithm" : run.name === "SCAN" ? "baseline" : "reference"}</span>
        <div class="chips"></div></header><canvas></canvas>`;
      box.appendChild(lane);
      run.laneEl = lane;
      run.canvas = lane.querySelector("canvas");
      run.chips = lane.querySelector(".chips");
    }
  },

  // ------------------------------------------------------------ statistics at time T
  stats(run, T) {
    if (T < run.statT) {               // moved backwards: start again
      run.p = 0; run.statT = 0;
      run.st = { prio: [[], [], []], all: [], normal: [], hog: [], misses: 0, max: 0 };
    }
    const R = this.R, st = run.st, dl = this.data.deadline;
    while (run.p < run.order.length) {
      const id = run.order[run.p], s = run.start[id];
      if (s > T) break;
      const w = s - R.arr[id];
      st.prio[R.prio[id]].push(w); st.all.push(w);
      (R.hog[id] ? st.hog : st.normal).push(w);
      if (R.prio[id] === 0 && w > dl) st.misses++;
      if (w > st.max) st.max = w;
      run.p++;
    }
    run.statT = T;
    return st;
  },

  headAt(run, T) {
    const tr = run.trajectory, i = lastAtOrBefore(tr, T);
    if (i < 0) return { pos: tr[0][1], moved: 0 };
    if (i >= tr.length - 1) return { pos: tr[i][1], moved: run.cum[i] };
    const [t0, c0] = tr[i], [t1, c1] = tr[i + 1];
    const pos = t1 > t0 ? c0 + (c1 - c0) * (T - t0) / (t1 - t0) : c1;
    return { pos, moved: run.cum[i] + Math.abs(pos - c0) };
  },

  // ------------------------------------------------------------ drawing
  frame(T, force) {
    if (!this.data) return;
    const H = this.runs.length <= 2 ? 300 : 236;
    for (const run of this.runs) this.drawLane(run, T, H);
    document.getElementById("d-clock").textContent = `t = ${T.toFixed(1)} ms`;
    const scrub = document.getElementById("d-scrub");
    if (document.activeElement !== scrub) scrub.value = Math.round(T / this.end() * 1000);
    const now = performance.now();
    if (force || now - this.lastUi > 200) { this.lastUi = now; this.updateUi(T, force); }
  },

  drawLane(run, T, H) {
    const { ctx, w, h } = setupCanvas(run.canvas, H);
    const R = this.R, size = this.data.disk_size, n = R.track.length;
    const L = 52, RM = 14, plotW = w - L - RM;
    const x = c => L + c / (size - 1) * plotW;
    const qBase = 70, platY = 84, top = 104, bottom = h - 24;
    const W = this.window, t0 = T - W;
    const y = t => top + (t - t0) / W * (bottom - top);
    const colorOf = id => R.hog[id] ? COLORS.hog : COLORS.prio[R.prio[id]];

    // grid + labels
    ctx.font = "11px " + COLORS.fontMono;
    ctx.fillStyle = COLORS.muted; ctx.strokeStyle = COLORS.grid; ctx.lineWidth = 1;
    for (const c of [0, 50, 100, 150, size - 1]) {
      ctx.beginPath(); ctx.setLineDash([2, 4]); ctx.moveTo(x(c), top); ctx.lineTo(x(c), bottom); ctx.stroke();
      ctx.setLineDash([]); ctx.textAlign = "center"; ctx.fillText(c, x(c), h - 8);
    }
    ctx.font = "11px " + COLORS.fontUi;
    ctx.textAlign = "left";
    ctx.fillText("queue", 4, qBase - 4);
    ctx.fillText(`−${W} ms`, 4, top + 9);
    ctx.fillText("now", 4, bottom);
    ctx.fillText("time ↓", 4, (top + bottom) / 2);

    // ---- queue (waiting requests stacked by cylinder)
    const buckets = 100, bw = plotW / buckets;
    const r = Math.max(1.6, Math.min(3, bw / 2.3)), step = 2 * r + 0.8;
    const maxStack = Math.floor((qBase - 6) / step);
    const stacks = new Array(buckets).fill(null).map(() => []);
    let waiting = 0;
    for (let id = 0; id < n; id++) {
      if (R.arr[id] <= T && run.start[id] > T) {
        waiting++;
        stacks[Math.min(buckets - 1, Math.floor(R.track[id] / size * buckets))].push(id);
      }
    }
    for (let b = 0; b < buckets; b++) {
      const st = stacks[b];
      if (!st.length) continue;
      st.sort((a, c) => R.prio[a] - R.prio[c] || R.hog[a] - R.hog[c]);
      const cx = L + (b + 0.5) * bw;
      for (let k = 0; k < Math.min(st.length, maxStack); k++) {
        const id = st[k];
        const py = qBase - r - k * step;
        const prio = R.prio[id];
        const isHog = R.hog[id];
        if (isHog) {
          ctx.fillStyle = COLORS.hog;
          ctx.fillRect(cx - r, py - r, r * 2, r * 2);
        } else if (prio === 0) {
          // HIGH: #FF2D55 fill + white 1.5px outline + ▲ marker
          ctx.fillStyle = COLORS.prio[0];
          ctx.beginPath();
          ctx.moveTo(cx, py - r - 0.5);
          ctx.lineTo(cx - r - 0.5, py + r);
          ctx.lineTo(cx + r + 0.5, py + r);
          ctx.closePath();
          ctx.fill();
          ctx.strokeStyle = "#FFFFFF";
          ctx.lineWidth = 1.4;
          ctx.stroke();
        } else if (prio === 1) {
          // MEDIUM: #F5F5F7 (white) fill + ● marker
          ctx.fillStyle = COLORS.prio[1];
          ctx.beginPath();
          ctx.arc(cx, py, r, 0, 7);
          ctx.fill();
        } else {
          // LOW: #7C8296 (steel grey) fill + ▽ marker
          ctx.fillStyle = COLORS.prio[2];
          ctx.beginPath();
          ctx.moveTo(cx - r, py - r);
          ctx.lineTo(cx + r, py - r);
          ctx.lineTo(cx, py + r + 0.5);
          ctx.closePath();
          ctx.fill();
        }
      }
      if (st.length > maxStack) { ctx.fillStyle = COLORS.text; ctx.textAlign = "center"; ctx.fillText("+", cx, 9); }
    }
    run.waiting = waiting;

    // ---- platter + arm (dark steel rings #16202E -> #0B111A, arm and sweep head = ICE WHITE with cyan glow)
    const head = this.headAt(run, T);
    run.moved = head.moved;
    const platGrad = ctx.createLinearGradient(0, platY - 5, 0, platY + 5);
    platGrad.addColorStop(0, "#16202E"); platGrad.addColorStop(1, "#0B111A");
    ctx.fillStyle = platGrad; ctx.strokeStyle = "#1C2B3D"; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.roundRect(x(0) - 4, platY - 5, plotW + 8, 10, 2); ctx.fill(); ctx.stroke();

    // Faint radar-sweep rotation on platter (off under reduced motion)
    if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      const swX = L + ((T * 0.05) % 1) * plotW;
      const swG = ctx.createLinearGradient(swX - 25, platY, swX + 25, platY);
      swG.addColorStop(0, "transparent");
      swG.addColorStop(0.5, "rgba(0, 229, 255, 0.12)");
      swG.addColorStop(1, "transparent");
      ctx.fillStyle = swG;
      ctx.fillRect(x(0) - 4, platY - 5, plotW + 8, 10);
    }

    const hx = x(head.pos);
    ctx.save();
    ctx.shadowColor = COLORS.head; ctx.shadowBlur = 10;
    ctx.fillStyle = COLORS.arm; // ICE WHITE sweep head with cyan glow
    ctx.beginPath(); ctx.moveTo(hx, platY - 8); ctx.lineTo(hx - 7, platY - 17); ctx.lineTo(hx + 7, platY - 17); ctx.fill();
    ctx.fillRect(hx - 1.5, platY - 6, 3, 12); // ICE WHITE arm
    ctx.restore();

    // ---- waterfall: HIGH waits as bars (orange until deadline, late = solid #FF2D55 with pulsing white glow and '!' tag)
    const dl = this.data.deadline;
    ctx.lineWidth = 3; ctx.lineCap = "butt";
    for (let id = 0; id < n; id++) {
      if (R.prio[id] !== 0) continue;
      const a = R.arr[id], s = Math.min(run.start[id], T);
      if (a > T || s < t0) continue;
      const xa = x(R.track[id]), from = Math.max(a, t0), mid = Math.min(s, a + dl);
      if (mid > from) {
        ctx.strokeStyle = COLORS.prio[1]; ctx.beginPath(); ctx.moveTo(xa, y(from)); ctx.lineTo(xa, y(mid)); ctx.stroke();
      }
      if (s > a + dl) {
        ctx.save();
        ctx.shadowColor = "#FFFFFF"; ctx.shadowBlur = 8;
        ctx.strokeStyle = COLORS.late; ctx.lineWidth = 3.5;
        ctx.beginPath(); ctx.moveTo(xa, y(Math.max(a + dl, t0))); ctx.lineTo(xa, y(s)); ctx.stroke();
        ctx.fillStyle = "#FFFFFF";
        ctx.font = "bold 10px " + COLORS.fontMono;
        ctx.fillText("!", xa + 4, y(Math.max(a + dl, t0)) + 9);
        ctx.restore();
      }
    }

    // ---- waterfall: the arm's path (white arm with red glow)
    const tr = run.trajectory;
    let i = Math.max(0, lastAtOrBefore(tr, t0));
    ctx.save();
    ctx.shadowColor = COLORS.head; ctx.shadowBlur = 6;
    ctx.strokeStyle = COLORS.arm; ctx.lineWidth = 1.6; ctx.beginPath();
    const startPos = this.headAt(run, Math.max(t0, 0)).pos;
    ctx.moveTo(x(startPos), y(Math.max(t0, 0)));
    for (i = i + 1; i < tr.length && tr[i][0] <= T; i++) ctx.lineTo(x(tr[i][1]), y(tr[i][0]));
    ctx.lineTo(hx, y(T));
    ctx.stroke();
    ctx.restore();

    // ---- served requests in the window (shape cues)
    for (let id = 0; id < n; id++) {
      const s = run.start[id];
      if (s < t0 || s > T) continue;
      const prio = R.prio[id];
      const isHog = R.hog[id];
      const sx = x(R.track[id]), sy = y(s);
      if (isHog) {
        ctx.fillStyle = COLORS.hog;
        ctx.fillRect(sx - 2, sy - 2, 4, 4);
      } else if (prio === 0) {
        ctx.fillStyle = COLORS.prio[0];
        ctx.beginPath(); ctx.moveTo(sx, sy - 3.5); ctx.lineTo(sx - 3.5, sy + 3.5); ctx.lineTo(sx + 3.5, sy + 3.5); ctx.closePath(); ctx.fill();
        ctx.strokeStyle = "#FFFFFF"; ctx.lineWidth = 1.2; ctx.stroke();
      } else if (prio === 1) {
        ctx.fillStyle = COLORS.prio[1];
        ctx.beginPath(); ctx.arc(sx, sy, 2.5, 0, 7); ctx.fill();
      } else {
        ctx.fillStyle = COLORS.prio[2];
        ctx.beginPath(); ctx.moveTo(sx - 2.5, sy - 2.5); ctx.lineTo(sx + 2.5, sy - 2.5); ctx.lineTo(sx, sy + 3); ctx.closePath(); ctx.fill();
      }
    }
    ctx.save();
    ctx.shadowColor = COLORS.head; ctx.shadowBlur = 8;
    ctx.fillStyle = COLORS.arm;
    ctx.beginPath(); ctx.arc(hx, y(T), 4, 0, 7); ctx.fill();
    ctx.restore();
  },

  // ------------------------------------------------------------ chips, scoreboard, log
  updateUi(T, force) {
    const names = this.runs.map(r => r.name);
    const S = this.runs.map(run => this.stats(run, T));
    const pct = (st) => st.prio[0].length ? 100 * st.misses / st.prio[0].length : NaN;
    this.runs.forEach((run, i) => {
      const st = S[i];
      run.chips.innerHTML = [
        `HIGH avg <b>${fmt(mean(st.prio[0]))}</b> ms`,
        `<span class="chip chip-inverted">HIGH p99 <b>${fmt(percentile(st.prio[0], 99))}</b> ms</span>`,
        `<span title="HIGH requests that started later than the deadline">HIGH late <b>${st.misses}/${st.prio[0].length}</b></span>`,
        `all avg <b>${fmt(mean(st.all))}</b> ms`,
        `queue <b>${run.waiting ?? 0}</b>`,
        `arm moved <b>${Math.round(run.moved || 0)}</b> cyl`,
      ].map((c, k) => c.startsWith("<span class=\"chip") ? c : `<span class="chip${k === 2 && st.misses > 0 ? " warn" : ""}">${c}</span>`).join("");
      if (run.laneEl) {
        if (st.misses > (run.prevMisses || 0)) {
          run.laneEl.classList.remove("missed-flash");
          void run.laneEl.offsetWidth;
          run.laneEl.classList.add("missed-flash");
        }
        run.prevMisses = st.misses;
      }
    });
    const hasHog = this.data.bursty.length > 0;
    const rows = [
      { label: "HIGH avg wait (ms)", values: S.map(s => mean(s.prio[0])) },
      { label: "HIGH p99 wait (ms)", values: S.map(s => percentile(s.prio[0], 99)) },
      { label: `HIGH later than ${this.data.deadline} ms (%)`, values: S.map(pct) },
      { label: "MEDIUM avg wait (ms)", values: S.map(s => mean(s.prio[1])) },
      { label: "LOW avg wait (ms)", values: S.map(s => mean(s.prio[2])) },
    ];
    if (hasHog) {
      rows.push({ label: "Normal processes avg (ms)", values: S.map(s => mean(s.normal)) });
      rows.push({ label: "Bursty process avg (ms)", values: S.map(s => mean(s.hog)) });
    }
    rows.push(
      { label: "All requests avg wait (ms)", values: S.map(s => mean(s.all)) },
      { label: "All requests p99 wait (ms)", values: S.map(s => percentile(s.all, 99)) },
      { label: "Max wait (ms)", values: S.map(s => s.all.length ? s.max : NaN) },
      { label: "Arm movement (cylinders)", values: this.runs.map(r => r.moved), format: v => fmt(v, 0) },
      { label: "Requests served", values: S.map(s => s.all.length), higher: true, format: v => fmt(v, 0) },
    );
    renderScoreboard(document.getElementById("d-table"), names, rows);
    this.updateLog(T, force);
  },

  updateLog(T, force) {
    const ul = document.getElementById("d-log");
    const R = this.R, procs = this.data.processes;
    const multi = this.runs.filter(r => r.decisions.length).length > 1;
    if (force || T < this.logT) {                     // rebuild from scratch
      ul.innerHTML = "";
      this.runs.forEach(r => { r.d = 0; });
    }
    const fresh = [];
    this.runs.forEach((run, ri) => {
      while (run.d < run.decisions.length && run.decisions[run.d][0] <= T) fresh.push([ri, run.d++]);
    });
    fresh.sort((a, b) => this.runs[a[0]].decisions[a[1]][0] - this.runs[b[0]].decisions[b[1]][0]);
    for (const [ri, di] of fresh.slice(-200)) {
      const [t, id, head, note] = this.runs[ri].decisions[di];
      const guard = note.includes("PRIORITY GUARD");
      const proc = procs[R.pid[id]] ? procs[R.pid[id]][0] : `P${R.pid[id]}`;
      const li = document.createElement("li");
      li.className = guard ? "guard" : "throttle";
      const skipped = (note.match(/(\d+) request\(s\) ahead deferred/) || [])[1];
      li.innerHTML = `<span class="t">${t.toFixed(1)} ms</span>${multi ? `[${esc(this.runs[ri].name)}] ` : ""}` +
        (guard ? `<span class="k">GUARD</span> arm ${head} → cyl ${R.track[id]} · ${esc(proc)} (HIGH) had waited ${(t - R.arr[id]).toFixed(1)} ms` +
                 (note.includes("turn around") ? " · reversed" : "")
               : `<span class="k">THROTTLE</span> skipped ${skipped || "some"} over-quota request(s) · served cyl ${R.track[id]} (${esc(proc)})`);
      li.onclick = () => { for (const x of ul.querySelectorAll(".sel")) x.classList.remove("sel"); li.classList.add("sel"); this.explain(ri, di); };
      ul.prepend(li);
    }
    while (ul.children.length > 200) ul.lastChild.remove();
    this.logT = T;
  },

  async explain(ri, di) {
    const run = this.runs[ri], R = this.R, procs = this.data.processes;
    const [t, id, head, note] = run.decisions[di];
    const name = pid => (procs[pid] ? procs[pid][0] : `P${pid}`);
    const waiting = [];
    for (let j = 0; j < R.track.length; j++) if (j !== id && R.arr[j] <= t && run.start[j] > t) waiting.push(j);
    const byPrio = { HIGH: 0, MEDIUM: 0, LOW: 0 }, byProc = {};
    for (const j of waiting) { byPrio[PRIO_NAMES[R.prio[j]]]++; byProc[name(R.pid[j])] = (byProc[name(R.pid[j])] || 0) + 1; }
    const context = {
      algorithm: run.name, time: t, head, note,
      chosen: { track: R.track[id], process: name(R.pid[id]), priority: PRIO_NAMES[R.prio[id]], waited: t - R.arr[id] },
      settings: this.settings,
      queue: {
        waiting: waiting.length, by_priority: byPrio,
        high_requests: waiting.filter(j => R.prio[j] === 0).map(j => ({ track: R.track[j], waited_ms: +(t - R.arr[j]).toFixed(1) }))
          .sort((a, b) => b.waited_ms - a.waited_ms).slice(0, 6),
        busiest_processes: Object.entries(byProc).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([n, c]) => ({ name: n, waiting: c })),
      },
    };
    const box = document.getElementById("d-explain");
    box.classList.remove("hidden");
    box.innerHTML = `<span class="spinner"></span>Explaining the decision at t = ${t.toFixed(1)} ms…`;
    try {
      const res = await api("/api/copilot/explain", { context, use_llm: document.getElementById("c-use-llm").checked });
      box.innerHTML = `${esc(res.text)}<div class="eng">explained by ${esc(res.engine)}` +
        (res.fallback_reason ? ` · Claude unavailable: ${esc(res.fallback_reason)}` : "") + "</div>";
    } catch (e) { box.textContent = "Could not explain: " + e.message; }
  },
};
