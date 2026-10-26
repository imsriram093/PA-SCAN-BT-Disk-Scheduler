"""
plots.py  -  COMPONENT 3: the comparison graphs for the LLM-serving project.

Every function receives numbers that llm_main.py already computed and saves
one PNG file into results/llm/. Nothing here changes the results.

The look (fonts, grid, colours, legend helpers) is shared with the disk
project's scheduler/plots.py, so both sets of figures match in the report.
Each policy keeps the SAME colour in every graph.
"""

import os

import matplotlib
import matplotlib.pyplot as plt

from llm_serving import config
from scheduler.plots import INK, INK_2, NEUTRAL, BAND, LINE_A, LINE_B, _key, _bar_labels, _line

COLORS = {
    "PA-SWEEP-BT":  "#2a78d6",   # blue   - our policy
    "PREFIX-SWEEP": "#eb6834",   # orange - the baseline
    "FAIR-SHARE":   "#eda100",   # yellow
    "PRIORITY":     "#e87ba4",   # magenta
    "FCFS":         "#008300",   # green
}


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


# ---------------------------------------------------------------------------
# Figure 1 - TTFT per priority class, baseline vs enhanced
# ---------------------------------------------------------------------------
def ttft_by_priority(summary, scenarios, algorithms=("PREFIX-SWEEP", "PA-SWEEP-BT")):
    """summary[scenario][algorithm] = averaged metrics dict."""
    classes = list(config.PRIORITY_NAMES.values())
    fig, axes = plt.subplots(2, len(scenarios), figsize=(4.6 * len(scenarios), 7.6))
    width = 0.36
    for col, sc in enumerate(scenarios):
        for row, (prefix, label) in enumerate([("ttft", "average TTFT (ms)"), ("p99", "99th-percentile TTFT (ms)")]):
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
    return _save(fig, "fig1_ttft_by_priority.png",
                 "Figure 1 - Time to first token by priority class: PREFIX-SWEEP vs PA-SWEEP-BT",
                 "INTERACTIVE users get their first token much sooner; BATCH work pays part of the price.",
                 legend_handles=[_key(a, COLORS[a]) for a in algorithms])


# ---------------------------------------------------------------------------
# Figure 2 - every policy side by side
# ---------------------------------------------------------------------------
def all_policies(summary_one_scenario, scenario_name):
    panels = [("slo_INTERACTIVE", f"INTERACTIVE TTFT <= {config.TTFT_SLO_MS[config.INTERACTIVE]:g} ms (%)", "{:.1f}"),
              ("p99_INTERACTIVE", "INTERACTIVE p99 TTFT (ms)", "{:,.0f}"),
              ("throughput", "Throughput (output tokens/s)", "{:,.0f}"),
              ("cache_hit_rate", "Prefix-cache hit rate (%)", "{:.1f}"),
              ("latency_BATCH", "BATCH end-to-end latency (ms)", "{:,.0f}")]
    algs = list(summary_one_scenario)
    fig, axes = plt.subplots(1, len(panels), figsize=(17, 4.2))
    for ax, (key, title, fmt) in zip(axes, panels):
        vals = [summary_one_scenario[a][key] for a in algs]
        bars = ax.barh(range(len(algs)), vals, 0.6, color=[COLORS[a] for a in algs], zorder=2)
        _bar_labels(ax, bars, fmt, horizontal=True)
        ax.set_yticks(range(len(algs)), algs if ax is axes[0] else [""] * len(algs))
        ax.invert_yaxis()
        ax.set_title(title, loc="left")
        ax.grid(axis="y", visible=False)
        ax.margins(x=0.25)
    return _save(fig, "fig2_all_policies.png",
                 f"Figure 2 - All policies compared ({scenario_name.upper()} scenario)",
                 f"Mean of {len(config.SEEDS)} runs.")


# ---------------------------------------------------------------------------
# Figure 3 - what happens to chat users during a flood
# ---------------------------------------------------------------------------
def flood_timeline(results, flood_windows):
    """results: {policy_name: SimulationResult} for the SAME flood workload."""
    names = list(results)
    fig, axes = plt.subplots(len(names), 1, figsize=(12, 3.0 * len(names) + 0.4), sharex=True)
    deadline = config.TTFT_SLO_MS[config.INTERACTIVE]
    for ax, name in zip(axes, names):
        res = results[name]
        for start, end in flood_windows:
            ax.axvspan(start / 1000, end / 1000, color=BAND, zorder=0)
        inter = [r for r in res.finished if r.priority == config.INTERACTIVE]
        ax.plot([r.arrival_time / 1000 for r in inter], [r.ttft for r in inter], "o", ms=3.5,
                color=COLORS.get(name, NEUTRAL), zorder=2)
        ax.axhline(deadline, color=INK, lw=1, ls="--", zorder=3)
        late = sum(r.ttft > deadline for r in inter)
        ax.set_title(f"{name}:  {late} of {len(inter)} INTERACTIVE requests missed the "
                     f"{deadline:g} ms TTFT target (worst {max(r.ttft for r in inter):,.0f} ms)", loc="left")
        ax.set_ylabel("TTFT (ms)")
        ax.set_yscale("log")
    axes[-1].set_xlabel("arrival time (s)  -  shaded = the bulk-import tenant is flooding the server")
    handles = [_key(f"{n}: one INTERACTIVE request", COLORS.get(n, NEUTRAL)) for n in names]
    handles.append(_key(f"{deadline:g} ms target", INK, "line"))
    return _save(fig, "fig3_flood_timeline.png",
                 "Figure 3 - INTERACTIVE time to first token during floods (FLOOD scenario, seed 1)",
                 "Without throttling the flood fills the batch and chat users queue behind it.",
                 legend_handles=handles)


# ---------------------------------------------------------------------------
# Figure 4 - load sweep
# ---------------------------------------------------------------------------
def load_sweep(sweep, loads):
    """sweep[policy] = list of averaged metrics, one per load level."""
    panels = [("p99_INTERACTIVE", "INTERACTIVE p99 TTFT (ms)"),
              ("slo_INTERACTIVE", "INTERACTIVE within TTFT target (%)"),
              ("throughput", "Throughput (output tokens/s)")]
    fig, axes = plt.subplots(1, len(panels), figsize=(14, 4.4))
    for ax, (key, title) in zip(axes, panels):
        for alg, rows in sweep.items():
            _line(ax, loads, [m[key] for m in rows], COLORS[alg])
        ax.set_title(title, loc="left")
        ax.set_xlabel("arrival rate (requests / s)")
    return _save(fig, "fig4_load_sweep.png",
                 "Figure 4 - How the policies behave as load grows (MIXED scenario)",
                 "Capacity of the simulated server is roughly 10 requests/s.",
                 legend_handles=[_key(a, COLORS[a], "line") for a in sweep])


# ---------------------------------------------------------------------------
# Figure 5 - ablation
# ---------------------------------------------------------------------------
def ablation(rows):
    """rows: list of (label, averaged metrics, colour)."""
    panels = [("p99_INTERACTIVE", "INTERACTIVE p99 TTFT (ms)", "{:,.0f}"),
              ("ttft_victims", "Normal tenants avg TTFT (ms)", "{:,.0f}"),
              ("ttft_flood", "Flooding tenant avg TTFT (ms)", "{:,.0f}"),
              ("max_ttft", "Worst TTFT (ms)", "{:,.0f}")]
    labels = [label for label, _, _ in rows]
    fig, axes = plt.subplots(1, len(panels), figsize=(16, 0.5 * len(rows) + 2.2))
    for ax, (key, title, fmt) in zip(axes, panels):
        bars = ax.barh(range(len(rows)), [m[key] for _, m, _ in rows], 0.6,
                       color=[c for _, _, c in rows], zorder=2)
        _bar_labels(ax, bars, fmt, horizontal=True)
        ax.set_yticks(range(len(rows)), labels if ax is axes[0] else [""] * len(rows))
        ax.invert_yaxis()
        ax.set_title(title, loc="left")
        ax.grid(axis="y", visible=False)
        ax.margins(x=0.25)
    return _save(fig, "fig5_ablation.png",
                 "Figure 5 - What each rule contributes (FLOOD scenario)",
                 "Rule 1 protects INTERACTIVE users; Rules 2 + 3 protect every normal tenant from the flood.")


# ---------------------------------------------------------------------------
# Figure 6 - sensitivity to the two knobs
# ---------------------------------------------------------------------------
def sensitivity(k_values, k_results, deadlines, d_results):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.4))
    _line(ax1, k_values, [m["ttft_victims"] for m in k_results], LINE_A)
    _line(ax1, k_values, [m["ttft_flood"] for m in k_results], LINE_B)
    ax1.set_title("Burst threshold K (FLOOD scenario): avg TTFT (ms)", loc="left")
    ax1.set_xlabel("K = BATCH admissions per tenant per sweep")
    _line(ax2, deadlines, [m["p99_INTERACTIVE"] for m in d_results], LINE_A)
    _line(ax2, deadlines, [m["latency_BATCH"] / 10 for m in d_results], LINE_B)
    ax2.set_title("TTFT deadline (HEAVY scenario)", loc="left")
    ax2.set_xlabel("Rule 1 deadline (ms)")
    handles = [_key("normal tenants avg TTFT  /  INTERACTIVE p99 TTFT (ms)", LINE_A, "line"),
               _key("flooding tenant avg TTFT  /  BATCH latency ÷ 10 (ms)", LINE_B, "line")]
    return _save(fig, "fig6_sensitivity.png",
                 "Figure 6 - Tuning the two knobs of PA-SWEEP-BT",
                 "Small K protects normal tenants more but slows the flooder; a tight deadline helps chat but "
                 "costs BATCH work.",
                 legend_handles=handles)
