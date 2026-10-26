"""
main.py  -  ONE command runs the whole project.

    python main.py            full benchmark -> tables in the terminal, CSV + graphs in results/
    python main.py --demo     small step-by-step example (great for the viva / live demo)
    python main.py --show     same as the full run, and also opens the graph windows
    python main.py --quick    3 random seeds instead of 10 (faster while you experiment)

What the full run does:
    1. builds identical workloads for each scenario (mixed / burst / heavy)
    2. runs every algorithm on them (FCFS, SSTF, SCAN, C-SCAN, LOOK, PA-SCAN-BT)
    3. averages the metrics over several random seeds
    4. prints comparison tables and writes results/summary_<scenario>.csv
    5. runs the extra experiments (load sweep, ablation, sensitivity)
    6. draws the 7 comparison graphs into results/
"""

import argparse
import csv
import os
import sys

import matplotlib

import config
from scheduler import metrics, workloads
from scheduler.baseline import FCFS, SSTF, SCAN, CSCAN, LOOK
from scheduler.enhanced import PriorityThrottledSCAN
from scheduler.simulator import simulate


def all_algorithms():
    """A fresh instance of every algorithm (fresh = no state left over from a previous run)."""
    return [FCFS(), SSTF(), SCAN(), CSCAN(), LOOK(), PriorityThrottledSCAN()]


def run_many(make_algorithm, scenario, seeds, rate=None):
    """Run one algorithm on `scenario` once per seed, return averaged metrics + per-seed results."""
    per_seed, results = [], []
    for seed in seeds:
        res = simulate(make_algorithm(), workloads.generate(scenario, seed, rate=rate))
        results.append(res)
        per_seed.append(metrics.compute(res))
    return metrics.average(per_seed), results


# ---------------------------------------------------------------------------
# Printing helpers
# ---------------------------------------------------------------------------
TABLE_COLUMNS = [
    ("total_head_movement", "Head move", "{:>10,.0f}"),
    ("avg_wait", "Avg wait", "{:>9.1f}"),
    ("wait_HIGH", "HIGH wait", "{:>10.1f}"),
    ("wait_MEDIUM", "MED wait", "{:>9.1f}"),
    ("wait_LOW", "LOW wait", "{:>9.1f}"),
    ("p99_HIGH", "HIGH p99", "{:>9.1f}"),
    ("p99_wait", "All p99", "{:>8.1f}"),
    ("max_wait", "Max wait", "{:>9.1f}"),
    ("throughput", "Req/s", "{:>7.1f}"),
]


def print_table(title, summary):
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)
    header = f"{'Algorithm':<12}" + "".join(f"{label:>{len(fmt.format(0))}}" for _, label, fmt in TABLE_COLUMNS)
    print(header)
    print("-" * len(header))
    for alg, m in summary.items():
        print(f"{alg:<12}" + "".join(fmt.format(m[key]) for key, _, fmt in TABLE_COLUMNS))
    print("(times in ms, averaged over", len(config.SEEDS), "random seeds)")


def print_improvement(summary, scenario):
    base, new = summary["SCAN"], summary["PA-SCAN-BT"]
    print(f"\nPA-SCAN-BT vs SCAN ({scenario}):  negative % = better")
    keys = [("wait_HIGH", "HIGH-priority avg wait"), ("p99_HIGH", "HIGH-priority p99 wait"),
            ("avg_wait", "All requests avg wait"), ("p99_wait", "All requests p99 wait"),
            ("wait_LOW", "LOW-priority avg wait"), ("total_head_movement", "Total head movement")]
    if scenario == "burst":
        keys += [("wait_victims", "Normal processes avg wait"), ("wait_hog", "Backup (hog) avg wait")]
    for key, label in keys:
        change = 100.0 * (new[key] - base[key]) / base[key]
        print(f"   {label:<28} {base[key]:>9.1f} -> {new[key]:>9.1f}   ({change:+.0f}%)")


def save_csv(summary, scenario):
    path = os.path.join(config.RESULTS_DIR, f"summary_{scenario}.csv")
    keys = [k for k in next(iter(summary.values())) if k != "algorithm"]
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["algorithm"] + keys)
        for alg, m in summary.items():
            writer.writerow([alg] + [round(m[k], 3) for k in keys])
    return path


# ---------------------------------------------------------------------------
# --demo : a tiny example you can explain line by line
# ---------------------------------------------------------------------------
def run_demo():
    reqs = workloads.demo_workload()
    print("DEMO - 14 requests, all arriving at t = 0, head at cylinder 50 moving UP")
    print("  P7 backup  (LOW)    : burst of 8 requests at cylinders 55-76")
    print("  P2 editor  (MEDIUM) : 120, 160")
    print("  P5 indexer (LOW)    : 140, 10")
    print("  P1 kernel  (HIGH)   : 100 (ahead, past the burst), 35 (behind the head)  <- page-fault reads")
    print(f"  Timing: {config.SEEK_TIME_PER_CYLINDER} ms per cylinder moved, {config.SERVICE_TIME} ms to read.")
    print(f"  PA-SCAN-BT settings for this demo: K = 3, HIGH deadline = 40 ms")

    for alg in (SCAN(), PriorityThrottledSCAN(burst_threshold=3, high_deadline=40)):
        res = simulate(alg, reqs, initial_head=50, initial_direction=+1)
        print("\n" + "-" * 96)
        print(f"{alg.name}")
        print("-" * 96)
        print(f"{'#':>2} {'start':>7} {'cyl':>4} {'proc':>5} {'prio':>7} {'moved':>6} {'wait':>7}   why")
        for step in res.trace:
            r = step["request"]
            via = f" (via edge {step['via'][0]})" if step["via"] else ""
            print(f"{step['step']:>2} {r.start_time:>7.1f} {r.track:>4} {'P' + str(r.process_id):>5} "
                  f"{config.PRIORITY_NAMES[r.priority]:>7} {step['distance']:>6} {r.waiting_time:>7.1f}   "
                  f"{step['note'].rstrip('; ') or 'nearest request ahead'}{via}")
        high = [f"cyl {r.track}: {r.waiting_time:.1f} ms" for r in res.served if r.priority == config.HIGH]
        print(f"   Total head movement = {res.total_head_movement} cylinders,"
              f" finished at {res.makespan:.1f} ms.  HIGH requests waited -> {', '.join(high)}")


# ---------------------------------------------------------------------------
# Full benchmark
# ---------------------------------------------------------------------------
def run_benchmark(show):
    from scheduler import plots   # imported here so --demo works even without matplotlib
    os.makedirs(config.RESULTS_DIR, exist_ok=True)
    seeds = config.SEEDS
    scenarios = list(workloads.SCENARIOS)
    summary = {}

    # 1) Main comparison: every algorithm x every scenario x every seed
    for sc in scenarios:
        summary[sc] = {}
        for alg in all_algorithms():
            make = type(alg)
            summary[sc][alg.name], _ = run_many(make, sc, seeds)
        print_table(f"SCENARIO: {sc.upper()}  -  {workloads.SCENARIOS[sc][2]}", summary[sc])
        print_improvement(summary[sc], sc)
        save_csv(summary[sc], sc)

    # 2) Arm-trajectory picture: same burst workload, seed 1
    one_workload = workloads.generate("burst", seeds[0])
    traj = {a.name: simulate(a, one_workload) for a in (SCAN(), PriorityThrottledSCAN())}

    # 3) Per-process waits in the burst scenario (averaged over seeds)
    per_proc = {}
    for make in (SCAN, PriorityThrottledSCAN):
        _, results = run_many(make, "burst", seeds)
        tables = [metrics.per_process_wait(r) for r in results]
        per_proc[make().name] = {pid: sum(t[pid] for t in tables) / len(tables) for pid in tables[0]}

    # 4) Load sweep on the mixed workload
    print("\nRunning load sweep ...")
    sweep = {}
    for make in (SCAN, LOOK, PriorityThrottledSCAN):
        sweep[make().name] = [run_many(make, "mixed", seeds, rate=load)[0] for load in config.LOAD_LEVELS]

    # 5) Ablation study on the burst workload
    print("Running ablation study ...")
    P = PriorityThrottledSCAN
    variants = [
        ("SCAN (baseline)", SCAN, plots.COLORS["SCAN"]),
        ("LOOK = no rules", lambda: P(use_priority=False, use_throttling=False, use_aging=False), plots.NEUTRAL),
        ("+ Rule 1 only (priority guard)", lambda: P(use_throttling=False), plots.NEUTRAL),
        ("+ Rules 2,3 only (throttle+aging)", lambda: P(use_priority=False), plots.NEUTRAL),
        ("PA-SCAN-BT (all 3 rules)", P, plots.COLORS["PA-SCAN-BT"]),
        ("PA-SCAN-BT without aging", lambda: P(use_aging=False), plots.NEUTRAL),
    ]
    ablation_rows = [(label, run_many(make, "burst", seeds)[0], color) for label, make, color in variants]
    print(f"\n{'Ablation (burst scenario)':<36}{'HIGH wait':>10}{'Normal':>9}{'Hog':>9}{'Max':>9}")
    for label, m, _ in ablation_rows:
        print(f"{label:<36}{m['wait_HIGH']:>10.1f}{m['wait_victims']:>9.1f}{m['wait_hog']:>9.1f}{m['max_wait']:>9.1f}")

    # 6) Sensitivity: burst threshold K and HIGH deadline
    print("\nRunning sensitivity sweeps ...")
    k_results = [run_many(lambda k=k: P(burst_threshold=k), "burst", seeds)[0] for k in config.K_VALUES]
    d_results = [run_many(lambda d=d: P(high_deadline=d), "mixed", seeds)[0] for d in config.DEADLINE_VALUES]

    # 7) Graphs
    files = [
        plots.head_trajectory(traj),
        plots.wait_by_priority(summary, scenarios),
        plots.all_algorithms(summary["mixed"], "mixed"),
        plots.per_process(per_proc),
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
    parser = argparse.ArgumentParser(description="Priority-Aware SCAN with Burst-Throttling - disk scheduling simulator")
    parser.add_argument("--demo", action="store_true", help="print a small step-by-step example")
    parser.add_argument("--show", action="store_true", help="open the graphs in windows after saving them")
    parser.add_argument("--quick", action="store_true", help="use 3 seeds instead of 10")
    args = parser.parse_args()

    if args.demo:
        run_demo()
        return
    if not args.show:
        matplotlib.use("Agg")          # draw straight to PNG files, no windows
    if args.quick:
        config.SEEDS = config.SEEDS[:3]
    run_benchmark(args.show)


if __name__ == "__main__":
    sys.exit(main())
