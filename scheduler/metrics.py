"""
metrics.py  -  Turns a SimulationResult into the numbers we compare.

Metric                 Meaning                                              Better
---------------------  ---------------------------------------------------  ------
total_head_movement    cylinders the arm travelled in total                 lower
avg_seek_distance      head movement / number of requests                   lower
avg_wait               average (start - arrival) over all requests          lower
avg_turnaround         average (finish - arrival)                           lower
wait_HIGH/MEDIUM/LOW   average wait inside each priority class              lower
p99_wait               99% of requests waited less than this                lower
max_wait               the single worst wait  -> starvation indicator       lower
wait_std               spread of waiting times (predictability)             lower
throughput             requests completed per second                        higher
direction_changes      how many times the arm reversed                      (info)
wait_victims           avg wait of the NORMAL processes (not the hog)       lower
p99_victims            99th-percentile wait of the normal processes         lower
wait_hog               avg wait of the bursty backup process                (info)
"""

import statistics

import config
from scheduler.workloads import BACKUP_PID


def _percentile(values, pct):
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(pct / 100 * len(ordered))) - 1))
    return ordered[index]


def compute(result):
    served = result.served
    n = len(served)
    waits = [r.waiting_time for r in served]

    m = {
        "algorithm": result.algorithm,
        "requests": n,
        "total_head_movement": result.total_head_movement,
        "avg_seek_distance": result.total_head_movement / n,
        "avg_wait": statistics.mean(waits),
        "avg_turnaround": statistics.mean(r.turnaround_time for r in served),
        "p99_wait": _percentile(waits, 99),
        "max_wait": max(waits),
        "wait_std": statistics.pstdev(waits),
        "throughput": n / (result.makespan / 1000.0),
        "direction_changes": result.direction_changes,
    }

    for level, label in config.PRIORITY_NAMES.items():
        group = [r.waiting_time for r in served if r.priority == level]
        m[f"wait_{label}"] = statistics.mean(group) if group else 0.0
        m[f"p99_{label}"] = _percentile(group, 99) if group else 0.0

    victims = [r.waiting_time for r in served if r.process_id != BACKUP_PID]
    hog = [r.waiting_time for r in served if r.process_id == BACKUP_PID]
    m["wait_victims"] = statistics.mean(victims) if victims else 0.0
    m["p99_victims"] = _percentile(victims, 99) if victims else 0.0
    m["wait_hog"] = statistics.mean(hog) if hog else 0.0
    return m


def average(metric_dicts):
    """Average a list of metric dictionaries (one per random seed)."""
    out = {"algorithm": metric_dicts[0]["algorithm"]}
    for key, value in metric_dicts[0].items():
        if isinstance(value, (int, float)):
            out[key] = statistics.mean(d[key] for d in metric_dicts)
    return out


def per_process_wait(result):
    """Average waiting time of every process (used for the fairness graph)."""
    groups = {}
    for r in result.served:
        groups.setdefault(r.process_id, []).append(r.waiting_time)
    return {pid: statistics.mean(w) for pid, w in sorted(groups.items())}
