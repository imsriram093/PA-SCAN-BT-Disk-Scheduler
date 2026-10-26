"""
plots.py  -  COMPONENT 3: the comparison graphs.

Every function receives numbers that main.py already computed and saves
one PNG file into the results/ folder. Nothing here changes the results;
it only draws them.

Colour rule: each algorithm keeps the SAME colour in every graph
(SCAN = orange, PA-SCAN-BT = blue, ...) so the reader never has to re-learn them.
"""

import os

import matplotlib
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

import config
from scheduler.workloads import PROCESS_NAMES, BURST_REGION

# ----------------------------------------------------------------- style
COLORS = {
    "PA-SCAN-BT": "#2a78d6",   # blue   - our algorithm
    "SCAN":       "#eb6834",   # orange - the baseline
    "LOOK":       "#1baf7a",   # aqua
    "C-SCAN":     "#eda100",   # yellow
    "SSTF":       "#e87ba4",   # magenta
    "FCFS":       "#008300",   # green
}
NEUTRAL = "#b4b2a9"
INK, INK_2, GRID = "#0b0b0b", "#52514e", "#e4e3de"
BAND = "#f1efe8"
LINE_A, LINE_B = "#1baf7a", "#6250d6"     # non-algorithm series (sensitivity graph)

plt.rcParams.update({
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "axes.edgecolor": GRID,
    "axes.labelcolor": INK_2,
    "axes.titlecolor": INK,
    "axes.titlesize": 10.5,
    "axes.titleweight": "bold",
    "axes.labelsize": 9.5,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.color": GRID,
    "grid.linewidth": 0.8,
    "xtick.color": INK_2,
    "ytick.color": INK_2,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "legend.frameon": False,
    "legend.fontsize": 9,
    "font.size": 9.5,
    "lines.linewidth": 2,
    "lines.solid_capstyle": "round",
})


def _save(fig, filename, title, subtitle=None, legend_handles=None):
    """Add the title block (and an optional bottom legend), lay out, write the PNG."""
    h = fig.get_figheight()
    fig.text(0.008, 1 - 0.18 / h, title, ha="left", va="top", fontsize=13, fontweight="bold", color=INK)
    top = 0.55
    if subtitle:
        fig.text(0.008, 1 - 0.50 / h, subtitle, ha="left", va="top", fontsize=9.5, color=INK_2)
        top = 0.85
    bottom = 0.0
    if legend_handles:
        fig.legend(handles=legend_handles, loc="lower center", ncol=len(legend_handles),
                   bbox_to_anchor=(0.5, 0.005))
        bottom = 0.40
    fig.tight_layout(rect=(0, bottom / h, 1, 1 - top / h))
    path = os.path.join(config.RESULTS_DIR, filename)
    fig.savefig(path, dpi=150)
    if matplotlib.get_backend().lower() == "agg":
        plt.close(fig)
    return path


def _key(label, color, kind="bar"):
    """A legend entry: a colour swatch (bars) or a short line (lines)."""
    if kind == "bar":
        return Line2D([], [], marker="s", ls="", ms=10, color=color, label=label)
    return Line2D([], [], color=color, lw=2, label=label)


def _bar_labels(ax, bars, fmt="{:.0f}", horizontal=False):
    for b in bars:
        if horizontal:
            v = b.get_width()
            ax.annotate(fmt.format(v), (v, b.get_y() + b.get_height() / 2), xytext=(3, 0),
                        textcoords="offset points", va="center", fontsize=8.5, color=INK)
        else:
            v = b.get_height()
            ax.annotate(fmt.format(v), (b.get_x() + b.get_width() / 2, v), xytext=(0, 2),
                        textcoords="offset points", ha="center", fontsize=8.5, color=INK)


def _line(ax, xs, ys, color):
    ax.plot(xs, ys, color=color, zorder=2)
    ax.plot(xs, ys, "o", ms=5.5, color=color, mec="white", mew=1.5, zorder=3)


# ---------------------------------------------------------------------------
# Figure 1 - how the disk arm moves (the classic disk-scheduling picture)
# ---------------------------------------------------------------------------
def head_trajectory(results, window_ms=(0, 1000)):
    """results: {algorithm_name: SimulationResult} for the SAME workload."""
    names = list(results)
    fig, axes = plt.subplots(len(names), 1, figsize=(12, 3.0 * len(names) + 0.4), sharex=True)
    t0, t1 = window_ms
    for ax, name in zip(axes, names):
        res = results[name]
        ax.axhspan(*BURST_REGION, color=BAND, zorder=0)
        ax.annotate("backup\nburst\nregion", (1.005, sum(BURST_REGION) / 2), xycoords=("axes fraction", "data"),
                    va="center", fontsize=8.5, color=INK_2)

        pts = [(t, c) for t, c in res.trajectory if t0 - 5 <= t <= t1 + 5]
        ax.plot([p[0] for p in pts], [p[1] for p in pts], color=COLORS.get(name, NEUTRAL), lw=1.4, zorder=2)

        high = [r for r in res.served if r.priority == config.HIGH and t0 <= r.arrival_time <= t1]
        for r in high:
            ax.plot([r.arrival_time, r.start_time], [r.track, r.track], color=INK, lw=1.2, zorder=3)
            ax.plot(r.start_time, r.track, "o", ms=6, color=INK, mec="white", mew=1.5, zorder=4)
        waits = [r.waiting_time for r in high]
        ax.set_title(f"{name}:  {len(waits)} HIGH requests in this window waited "
                     f"{sum(waits) / len(waits):.0f} ms on average (worst {max(waits):.0f} ms)", loc="left")
        ax.set_ylabel("cylinder")
        ax.set_ylim(-5, config.DISK_SIZE + 5)
        ax.set_xlim(t0, t1)
    axes[-1].set_xlabel("time (ms)  -  the backup process fires a 40-request burst at t = 50 ms and t = 550 ms")
    handles = [_key("SCAN arm position", COLORS["SCAN"], "line"),
               _key("PA-SCAN-BT arm position", COLORS["PA-SCAN-BT"], "line"),
               Line2D([], [], color=INK, lw=1.2, marker="o", ms=6, mec="white", mew=1.5,
                      label="HIGH request: line = waiting, dot = served")]
    return _save(fig, "fig1_head_trajectory.png",
                 "Figure 1 - Disk arm movement over time (BURST scenario, first second)",
                 "SCAN crawls through the burst region in one long pass while everyone else waits. "
                 "PA-SCAN-BT breaks the burst into smaller pieces and keeps visiting the rest of the disk.",
                 legend_handles=handles)


# ---------------------------------------------------------------------------
# Figure 2 - waiting time per priority class, baseline vs enhanced
# ---------------------------------------------------------------------------
def wait_by_priority(summary, scenarios, algorithms=("SCAN", "PA-SCAN-BT")):
    """summary[scenario][algorithm] = averaged metrics dict."""
    classes = list(config.PRIORITY_NAMES.values())
    fig, axes = plt.subplots(2, len(scenarios), figsize=(4.3 * len(scenarios), 7.6))
    width = 0.36
    for col, sc in enumerate(scenarios):
        for row, (prefix, label) in enumerate([("wait", "average wait (ms)"),
                                               ("p99", "99th-percentile wait (ms)")]):
            ax = axes[row][col]
            for i, alg in enumerate(algorithms):
                vals = [summary[sc][alg][f"{prefix}_{c}"] for c in classes]
                xs = [x + (i - 0.5) * width for x in range(len(classes))]
                bars = ax.bar(xs, vals, width * 0.92, color=COLORS[alg], zorder=2)
                _bar_labels(ax, bars)
            ax.set_xticks(range(len(classes)), classes)
            ax.set_ylabel(label if col == 0 else "")
            ax.grid(axis="x", visible=False)
            ax.set_title(f"{sc.upper()} - {'average' if row == 0 else 'worst 1% (p99)'}", loc="left")
            ax.margins(y=0.15)
    return _save(fig, "fig2_wait_by_priority.png",
                 "Figure 2 - Waiting time by priority class: SCAN vs PA-SCAN-BT",
                 "HIGH-priority requests wait far less, in every scenario. Lower-priority work pays part of the price, "
                 "mostly in the tail.",
                 legend_handles=[_key(a, COLORS[a]) for a in algorithms])


# ---------------------------------------------------------------------------
# Figure 3 - every algorithm side by side
# ---------------------------------------------------------------------------
def all_algorithms(summary_one_scenario, scenario_name):
    panels = [("total_head_movement", "Total head movement (cylinders)", "{:,.0f}"),
              ("avg_wait", "Average wait - all requests (ms)", "{:.1f}"),
              ("wait_HIGH", "Average wait - HIGH priority (ms)", "{:.1f}"),
              ("p99_HIGH", "99th-pct wait - HIGH priority (ms)", "{:.1f}")]
    algs = [a for a in summary_one_scenario if a != "FCFS"]
    fig, axes = plt.subplots(1, len(panels), figsize=(15, 4.2))
    for ax, (key, title, fmt) in zip(axes, panels):
        vals = [summary_one_scenario[a][key] for a in algs]
        bars = ax.barh(range(len(algs)), vals, 0.6, color=[COLORS[a] for a in algs], zorder=2)
        _bar_labels(ax, bars, fmt, horizontal=True)
        ax.set_yticks(range(len(algs)), algs if ax is axes[0] else [""] * len(algs))
        ax.invert_yaxis()
        ax.set_title(title, loc="left")
        ax.grid(axis="y", visible=False)
        ax.margins(x=0.22)
    fcfs = summary_one_scenario.get("FCFS")
    note = (f"Mean of {len(config.SEEDS)} runs. FCFS is left out of the bars because it is off the scale "
            f"(average wait {fcfs['avg_wait']:,.0f} ms, head movement {fcfs['total_head_movement']:,.0f} cylinders)."
            if fcfs else None)
    return _save(fig, "fig3_all_algorithms.png",
                 f"Figure 3 - All algorithms compared ({scenario_name.upper()} scenario)", note)


# ---------------------------------------------------------------------------
# Figure 4 - who suffers during a burst?  (per-process fairness)
# ---------------------------------------------------------------------------
def per_process(per_proc, algorithms=("SCAN", "PA-SCAN-BT")):
    """per_proc[algorithm] = {process_id: avg wait}"""
    pids = sorted(per_proc[algorithms[0]])
    labels = [f"P{p}\n{PROCESS_NAMES[p]}".replace(" (burst hog)", "\n(burst hog)") for p in pids]
    fig, ax = plt.subplots(figsize=(12, 5.0))
    width = 0.36
    for i, alg in enumerate(algorithms):
        vals = [per_proc[alg][p] for p in pids]
        xs = [x + (i - 0.5) * width for x in range(len(pids))]
        bars = ax.bar(xs, vals, width * 0.92, color=COLORS[alg], zorder=2)
        _bar_labels(ax, bars)
    ax.set_xticks(range(len(pids)), labels, fontsize=8.5)
    ax.set_ylabel("average wait (ms)")
    ax.grid(axis="x", visible=False)
    ax.margins(y=0.12)
    return _save(fig, "fig4_per_process_wait.png",
                 "Figure 4 - Average wait of each process during bursts (BURST scenario)",
                 "Throttling makes the bursty backup job (P7) wait longer, so the other processes wait less (or about the same).",
                 legend_handles=[_key(a, COLORS[a]) for a in algorithms])


# ---------------------------------------------------------------------------
# Figure 5 - behaviour as the disk gets busier
# ---------------------------------------------------------------------------
def load_sweep(sweep, loads, algorithms=("SCAN", "LOOK", "PA-SCAN-BT")):
    """sweep[algorithm] = list of metric dicts, one per load level."""
    panels = [("wait_HIGH", "HIGH-priority average wait (ms)"),
              ("avg_wait", "All requests - average wait (ms)"),
              ("p99_wait", "All requests - 99th-percentile wait (ms)")]
    fig, axes = plt.subplots(1, len(panels), figsize=(15, 4.6))
    for ax, (key, title) in zip(axes, panels):
        for alg in algorithms:
            _line(ax, loads, [m[key] for m in sweep[alg]], COLORS[alg])
        ax.set_title(title, loc="left")
        ax.set_xlabel("arrival rate (requests / second)")
        ax.set_xticks(loads)
        ax.set_ylim(bottom=0)
    return _save(fig, "fig5_load_sweep.png",
                 "Figure 5 - What happens as the disk gets busier (MIXED workload)",
                 "PA-SCAN-BT keeps HIGH-priority waits lowest at every load. Above ~120 requests/s the price shows up "
                 "as a longer tail for everyone else.",
                 legend_handles=[_key(a, COLORS[a], "line") for a in algorithms])


# ---------------------------------------------------------------------------
# Figure 6 - ablation: how much does each rule contribute?
# ---------------------------------------------------------------------------
def ablation(rows):
    """rows = list of (variant_label, metrics_dict, colour)"""
    panels = [("wait_HIGH", "HIGH-priority avg wait (ms)"),
              ("wait_victims", "Normal processes avg wait (ms)"),
              ("wait_hog", "Backup (hog) avg wait (ms)"),
              ("max_wait", "Worst single wait (ms)")]
    fig, axes = plt.subplots(1, len(panels), figsize=(16, 4.3))
    labels = [r[0] for r in rows]
    for ax, (key, title) in zip(axes, panels):
        vals = [r[1][key] for r in rows]
        bars = ax.barh(range(len(rows)), vals, 0.6, color=[r[2] for r in rows], zorder=2)
        _bar_labels(ax, bars, horizontal=True)
        ax.set_yticks(range(len(rows)), labels if ax is axes[0] else [""] * len(rows))
        ax.invert_yaxis()
        ax.set_title(title, loc="left")
        ax.grid(axis="y", visible=False)
        ax.margins(x=0.22)
    return _save(fig, "fig6_ablation.png",
                 "Figure 6 - Ablation study: switching the rules on one at a time (BURST scenario)",
                 "Rule 1 is what cuts HIGH waits; Rules 2+3 are what protect normal processes. "
                 "Without aging (last row) the backup job starves.")


# ---------------------------------------------------------------------------
# Figure 7 - tuning the two knobs
# ---------------------------------------------------------------------------
def sensitivity(k_values, k_results, d_values, d_results):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 4.7))

    _line(a1, k_values, [m["wait_victims"] for m in k_results], LINE_A)
    _line(a1, k_values, [m["wait_hog"] for m in k_results], LINE_B)
    a1.set_ylim(bottom=0)
    a1.set_xticks(k_values)
    a1.axvline(config.BURST_THRESHOLD_K, color=INK_2, lw=1, zorder=1)
    a1.text(config.BURST_THRESHOLD_K, a1.get_ylim()[1], f" default K = {config.BURST_THRESHOLD_K}",
            va="top", fontsize=8.5, color=INK_2)
    a1.set_title("(a) Burst threshold K  -  BURST scenario", loc="left")
    a1.set_xlabel("K  (LOW-priority requests allowed per process per sweep)")
    a1.set_ylabel("average wait (ms)")
    a1.legend(handles=[_key("normal processes", LINE_A, "line"), _key("backup (hog) process", LINE_B, "line")],
              loc="center right")

    _line(a2, d_values, [m["wait_HIGH"] for m in d_results], LINE_A)
    _line(a2, d_values, [m["avg_wait"] for m in d_results], LINE_B)
    a2.set_ylim(bottom=0)
    a2.set_xticks(d_values)
    a2.axvline(config.HIGH_DEADLINE, color=INK_2, lw=1, zorder=1)
    a2.text(config.HIGH_DEADLINE, a2.get_ylim()[1], f" default = {config.HIGH_DEADLINE:g} ms",
            va="top", fontsize=8.5, color=INK_2)
    a2.set_title("(b) HIGH deadline  -  MIXED scenario", loc="left")
    a2.set_xlabel("HIGH_DEADLINE (ms)")
    a2.set_ylabel("average wait (ms)")
    a2.legend(handles=[_key("HIGH-priority requests", LINE_A, "line"), _key("all requests", LINE_B, "line")],
              loc="lower right")
    return _save(fig, "fig7_sensitivity.png",
                 "Figure 7 - Tuning the two knobs",
                 "A small K protects other processes but slows the hog. "
                 "A tight deadline helps HIGH requests but costs everyone else.")
