"""
llm_main.py  -  ONE command runs the LLM-serving version of the project.

    python llm_main.py            full benchmark -> tables in the terminal, CSV + graphs in results/llm/
    python llm_main.py --demo     small step-by-step example on a 4-slot server
    python llm_main.py --show     same as the full run, and also opens the graph windows
    python llm_main.py --quick    2 random seeds instead of 5 (faster while you experiment)

What the full run does:
    1. builds identical workloads for each scenario (mixed / flood / heavy)
    2. runs every policy on them (FCFS, PRIORITY, FAIR-SHARE, PREFIX-SWEEP, PA-SWEEP-BT)
    3. averages the metrics over several random seeds
    4. prints comparison tables and writes results/llm/summary_<scenario>.csv
    5. runs the extra experiments (flood timeline, load sweep, ablation, sensitivity)
    6. draws the 6 comparison graphs into results/llm/
"""

import argparse
import csv
import os
import sys

import matplotlib

from llm_serving import config, metrics, workloads
from llm_serving.baseline import FCFS, StrictPriority, FairShare, PrefixSweep
from llm_serving.enhanced import PriorityThrottledSweep
from llm_serving.server import ServerSpec
from llm_serving.simulator import simulate


def all_policies():
    """A fresh instance of every policy (fresh = no state left over from a previous run)."""
    return [FCFS(), StrictPriority(), FairShare(), PrefixSweep(), PriorityThrottledSweep()]


def run_many(make_policy, scenario, seeds, rate=None):
    """Run one policy on `scenario` once per seed, return averaged metrics + per-seed results."""
    per_seed, results = [], []
    for seed in seeds:
        res = simulate(make_policy(), workloads.generate(scenario, seed, rate=rate))
        results.append(res)
        per_seed.append(metrics.compute(res))
    return metrics.average(per_seed), results


# ---------------------------------------------------------------------------
# Printing helpers
# ---------------------------------------------------------------------------
TABLE_COLUMNS = [
    ("ttft_INTERACTIVE", "INT ttft", "{:>9.0f}"),
    ("p99_INTERACTIVE", "INT p99", "{:>9.0f}"),
    ("slo_INTERACTIVE", "INT SLO%", "{:>9.1f}"),
    ("ttft_STANDARD", "STD ttft", "{:>9.0f}"),
    ("slo_STANDARD", "STD SLO%", "{:>9.1f}"),
    ("ttft_BATCH", "BAT ttft", "{:>9.0f}"),
    ("latency_BATCH", "BAT e2e", "{:>9.0f}"),
    ("max_ttft", "Max ttft", "{:>9.0f}"),
    ("throughput", "Tok/s", "{:>7.0f}"),
    ("cache_hit_rate", "Hit%", "{:>6.1f}"),
    ("preemptions", "Preempt", "{:>8.1f}"),
]


def print_table(title, summary):
    print("\n" + "=" * 110)
    print(title)
    print("=" * 110)
    header = f"{'Policy':<14}" + "".join(f"{label:>{len(fmt.format(0))}}" for _, label, fmt in TABLE_COLUMNS)
    print(header)
    print("-" * len(header))
    for alg, m in summary.items():
        print(f"{alg:<14}" + "".join(fmt.format(m[key]) for key, _, fmt in TABLE_COLUMNS))
    print("(times in ms, averaged over", len(config.SEEDS), "random seeds; SLO% = share within the TTFT target)")


def print_improvement(summary, scenario):
    base, new = summary["PREFIX-SWEEP"], summary["PA-SWEEP-BT"]
    print(f"\nPA-SWEEP-BT vs PREFIX-SWEEP ({scenario}):  negative % = better (lower is better for times)")
    keys = [("ttft_INTERACTIVE", "INTERACTIVE avg TTFT"), ("p99_INTERACTIVE", "INTERACTIVE p99 TTFT"),
            ("ttft_STANDARD", "STANDARD avg TTFT"), ("avg_ttft", "All requests avg TTFT"),
            ("latency_BATCH", "BATCH end-to-end latency")]
    if scenario == "flood":
        keys += [("ttft_victims", "Normal tenants avg TTFT"), ("ttft_flood", "Flooding tenant avg TTFT")]
    for key, label in keys:
        change = 100.0 * (new[key] - base[key]) / base[key] if base[key] else 0.0
        print(f"   {label:<28} {base[key]:>9.1f} -> {new[key]:>9.1f}   ({change:+.0f}%)")
    for key, label in [("slo_INTERACTIVE", "INTERACTIVE within target"), ("throughput", "Throughput (tokens/s)"),
                       ("cache_hit_rate", "Prefix-cache hit rate")]:
        print(f"   {label:<28} {base[key]:>9.1f} -> {new[key]:>9.1f}   (higher is better)")


def save_csv(summary, scenario):
    path = os.path.join(config.RESULTS_DIR, f"summary_{scenario}.csv")
    keys = [k for k in next(iter(summary.values())) if k != "algorithm"]
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["policy"] + keys)
        for alg, m in summary.items():
            writer.writerow([alg] + [round(m[k], 3) for k in keys])
    return path


# ---------------------------------------------------------------------------
# --demo : a tiny example you can explain line by line
# ---------------------------------------------------------------------------
def run_demo():
    reqs = workloads.demo_workload()
    tiny = ServerSpec(max_seqs=4)
    print("DEMO - a server with only 4 batch slots")
    print("  t=0    tenant 7 bulk-import (BATCH)   : 6 requests, all on prefix 24, 60 output tokens each")
    print("  t=0    tenant 3 rag-search (STANDARD) : 1 request on prefix 30")
    print("  t=0    tenant 5 eval-batch (BATCH)    : 1 request on prefix 50")
    print("  t=5    tenant 1 chat-app (INTERACTIVE): prefix 2      t=40: another one on prefix 3")
    print("  The sweep starts at prefix 0 moving UP.  PA-SWEEP-BT settings: K = 2, TTFT deadline = 150 ms")

    for alg in (PrefixSweep(), PriorityThrottledSweep(burst_threshold=2, ttft_deadline=150, server=tiny)):
        res = simulate(alg, reqs, server=tiny, keep_trace=True)
        print("\n" + "-" * 100)
        print(alg.name)
        print("-" * 100)
        print(f"{'step':>4} {'ends at':>8}  {'admitted (request: tenant, priority, prefix)':<52} why")
        for step in res.trace:
            for r in step["preempted"]:
                print(f"{step['step']:>4} {'':>8}  preempted #{r.request_id} (T{r.tenant_id} "
                      f"{config.PRIORITY_NAMES[r.priority]}) -> back to the queue")
            for r, note in step["admitted"]:
                what = (f"#{r.request_id}: T{r.tenant_id} {config.PRIORITY_NAMES[r.priority]:<11} prefix {r.prefix_id:>2}"
                        f"{' (cache hit)' if r.cache_hit else ''}")
                print(f"{step['step']:>4} {step['end_time']:>8.1f}  {what:<52} "
                      f"{note.rstrip('; ') or 'nearest prefix ahead'}")
        chat = [f"#{r.request_id}: {r.ttft:.0f} ms" for r in sorted(res.finished, key=lambda r: r.request_id)
                if r.priority == config.INTERACTIVE]
        print(f"   Finished at {res.makespan:.0f} ms, {res.preemptions} preemption(s). "
              f"INTERACTIVE time to first token -> {', '.join(chat)}")


# ---------------------------------------------------------------------------
# Full benchmark
# ---------------------------------------------------------------------------
def run_benchmark(show):
    from llm_serving import plots   # imported here so --demo works even without matplotlib
    os.makedirs(config.RESULTS_DIR, exist_ok=True)
    seeds = config.SEEDS
    scenarios = list(workloads.SCENARIOS)
    summary = {}

    # 1) Main comparison: every policy x every scenario x every seed
    for sc in scenarios:
        summary[sc] = {}
        for alg in all_policies():
            summary[sc][alg.name], _ = run_many(type(alg), sc, seeds)
        print_table(f"SCENARIO: {sc.upper()}  -  {workloads.SCENARIOS[sc][2]}", summary[sc])
        print_improvement(summary[sc], sc)
        save_csv(summary[sc], sc)

    # 2) Flood timeline: same flood workload, seed 1
    one_workload = workloads.generate("flood", seeds[0])
    timeline = {a.name: simulate(a, one_workload) for a in (PrefixSweep(), PriorityThrottledSweep())}

    # 3) Load sweep on the mixed workload
    print("\nRunning load sweep ...")
    sweep = {}
    for make in (FCFS, PrefixSweep, PriorityThrottledSweep):
        sweep[make().name] = [run_many(make, "mixed", seeds, rate=load)[0] for load in config.LOAD_LEVELS]

    # 4) Ablation study on the flood workload
    print("Running ablation study ...")
    P = PriorityThrottledSweep
    variants = [
        ("PREFIX-SWEEP = no rules", PrefixSweep, plots.COLORS["PREFIX-SWEEP"]),
        ("+ Rule 1 guard, no preemption", lambda: P(use_preemption=False, use_throttling=False), plots.NEUTRAL),
        ("+ Rule 1 guard + preemption", lambda: P(use_throttling=False), plots.NEUTRAL),
        ("+ Rules 2,3 only (throttle+aging)", lambda: P(use_guard=False), plots.NEUTRAL),
        ("PA-SWEEP-BT (all 3 rules)", P, plots.COLORS["PA-SWEEP-BT"]),
        ("PA-SWEEP-BT without aging", lambda: P(use_aging=False), plots.NEUTRAL),
    ]
    ablation_rows = [(label, run_many(make, "flood", seeds)[0], color) for label, make, color in variants]
    print(f"\n{'Ablation (flood scenario)':<36}{'INT p99':>9}{'Normal':>9}{'Flood':>9}{'Max':>9}{'Preempt':>9}")
    for label, m, _ in ablation_rows:
        print(f"{label:<36}{m['p99_INTERACTIVE']:>9.0f}{m['ttft_victims']:>9.0f}{m['ttft_flood']:>9.0f}"
              f"{m['max_ttft']:>9.0f}{m['preemptions']:>9.1f}")

    # 5) Sensitivity: burst threshold K and TTFT deadline
    print("\nRunning sensitivity sweeps ...")
    k_results = [run_many(lambda k=k: P(burst_threshold=k), "flood", seeds)[0] for k in config.K_VALUES]
    d_results = [run_many(lambda d=d: P(ttft_deadline=d), "heavy", seeds)[0] for d in config.DEADLINE_VALUES]

    # 6) Graphs
    files = [
        plots.ttft_by_priority(summary, scenarios),
        plots.all_policies(summary["flood"], "flood"),
        plots.flood_timeline(timeline, workloads.flood_windows()),
        plots.load_sweep(sweep, config.LOAD_LEVELS),
        plots.ablation(ablation_rows),
        plots.sensitivity(config.K_VALUES, k_results, config.DEADLINE_VALUES, d_results),
    ]
    print("\nSaved:")
    for f in files + [os.path.join(config.RESULTS_DIR, f"summary_{sc}.csv") for sc in scenarios]:
        print("   ", f)
    if show:
        import matplotlib.pyplot as plt
        plt.show()


def main():
    parser = argparse.ArgumentParser(description="PA-SWEEP-BT - LLM inference serving scheduler simulator")
    parser.add_argument("--demo", action="store_true", help="print a small step-by-step example")
    parser.add_argument("--show", action="store_true", help="open the graphs in windows after saving them")
    parser.add_argument("--quick", action="store_true", help="use 2 seeds instead of 5")
    args = parser.parse_args()

    if args.demo:
        run_demo()
        return
    if not args.show:
        matplotlib.use("Agg")          # draw straight to PNG files, no windows
    if args.quick:
        config.SEEDS = config.SEEDS[:2]
    run_benchmark(args.show)


if __name__ == "__main__":
    sys.exit(main())