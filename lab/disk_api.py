"""
lab/disk_api.py  -  The disk half of the live lab.

The browser never runs a scheduling algorithm itself. It asks this module, which
    1. builds a workload (a built-in scenario, or a custom spec from the co-pilot),
    2. adds the events the user injected while watching ("backup burst", "page faults"),
    3. runs the chosen algorithms with the SAME simulator as main.py,
    4. packs the result into small arrays the browser can animate.

Why live injection is honest: a scheduler only sees requests that have already
arrived. A burst injected at time t therefore cannot change any decision taken
before t, so the browser can re-run the simulation and simply carry on animating
from t. What you see before and after the click is one consistent simulation.
"""

import random

import config
from scheduler import workloads
from scheduler.baseline import FCFS, SSTF, SCAN, CSCAN, LOOK
from scheduler.enhanced import PriorityThrottledSCAN
from scheduler.request import Request
from scheduler.simulator import simulate

HIGH, MEDIUM, LOW = config.HIGH, config.MEDIUM, config.LOW

LAB_DURATION_MS = 8000.0        # each lab run covers 8 s of arrivals
MAX_ALGORITHMS = 4
MAX_INJECTIONS = 60

ALGORITHMS = {
    "FCFS": FCFS, "SSTF": SSTF, "SCAN": SCAN, "C-SCAN": CSCAN, "LOOK": LOOK,
    "PA-SCAN-BT": PriorityThrottledSCAN,
}

# Process ids used for requests the user injects (kept apart from workload ids)
INJECTED_BURST_PID = 90
INJECTED_FAULT_PID = 91
INJECTIONS = {
    #  kind         (pid,                 name,                         priority, how many, region,                    spread ms)
    "burst":     (INJECTED_BURST_PID, "injected backup burst",      LOW,  40, workloads.BURST_REGION,          2.0),
    "pagefault": (INJECTED_FAULT_PID, "injected page faults",       HIGH,  3, (0, config.DISK_SIZE - 1),       1.0),
}


class LabError(ValueError):
    """Bad input from the browser (reported back as a readable message)."""


# ---------------------------------------------------------------------------
# Workload
# ---------------------------------------------------------------------------
DEMO_HEAD = 50          # main.py --demo starts the head at cylinder 50, moving UP


def build_workload(workload, duration_ms=LAB_DURATION_MS):
    """workload = {"scenario": "burst", "seed": 1}  or  {"spec": {...}, "seed": 1}.
    Returns (requests, {pid: (name, priority)}, bursty process ids, initial head)."""
    seed = int(workload.get("seed", 1))
    if workload.get("spec"):
        spec = workload["spec"]
        requests = workloads.generate_custom(spec, seed, duration_ms)
        listed = list(spec["processes"]) + list(spec.get("bursts", []))
        processes = {i + 1: (p["name"], p["priority"]) for i, p in enumerate(listed)}
        bursty = list(range(len(spec["processes"]) + 1, len(listed) + 1))
        return requests, processes, bursty, config.INITIAL_HEAD

    processes = {pid: (name, prio) for pid, name, prio, *_ in workloads.BACKGROUND_PROCESSES}
    processes[workloads.BACKUP_PID] = (workloads.PROCESS_NAMES[workloads.BACKUP_PID], LOW)
    scenario = workload.get("scenario", "mixed")
    if scenario == "demo":                        # the 14-request walkthrough of main.py --demo
        return workloads.demo_workload(), processes, [workloads.BACKUP_PID], DEMO_HEAD
    if scenario not in workloads.SCENARIOS:
        raise LabError(f"unknown scenario '{scenario}'")
    requests = workloads.generate(scenario, seed, duration_ms=duration_ms)
    if not workloads.SCENARIOS[scenario][1]:
        del processes[workloads.BACKUP_PID]
    bursty = [workloads.BACKUP_PID] if workloads.SCENARIOS[scenario][1] else []
    return requests, processes, bursty, config.INITIAL_HEAD


def add_injections(requests, processes, injections, seed):
    """Append the user's injected requests. Their ids come after the workload's,
    and each injection has its own seeded RNG, so re-sending the same list
    always rebuilds exactly the same requests."""
    if len(injections) > MAX_INJECTIONS:
        raise LabError(f"at most {MAX_INJECTIONS} injections per run")
    out = list(requests)
    next_id = len(out)
    for i, inj in enumerate(injections):
        kind = inj.get("kind")
        if kind not in INJECTIONS:
            raise LabError(f"unknown injection '{kind}'")
        pid, name, prio, count, (lo, hi), spread = INJECTIONS[kind]
        t = max(0.0, float(inj.get("t", 0.0)))
        rng = random.Random(f"{seed}/{i}/{kind}")
        for _ in range(count):
            out.append(Request(next_id, pid, rng.randint(lo, hi), round(t + rng.uniform(0, spread), 3), prio))
            next_id += 1
        processes[pid] = (name, prio)
    return out


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------
def make_algorithm(name, settings):
    if name not in ALGORITHMS:
        raise LabError(f"unknown algorithm '{name}'")
    if name == "PA-SCAN-BT":
        return PriorityThrottledSCAN(burst_threshold=int(settings.get("k", config.BURST_THRESHOLD_K)),
                                     high_deadline=float(settings.get("deadline", config.HIGH_DEADLINE)),
                                     aging_limit=float(settings.get("aging", config.AGING_LIMIT)))
    return ALGORITHMS[name]()


def _decisions(result, head):
    """The interesting decisions (rule firings) with the time the choice was made
    and where the head was, for the browser's decision log."""
    out = []
    for step in result.trace:
        r, note = step["request"], step["note"]
        decided_at = r.start_time - step["distance"] * config.SEEK_TIME_PER_CYLINDER
        if "PRIORITY GUARD" in note or "deferred" in note:
            out.append([round(decided_at, 3), r.request_id, head, note.rstrip("; ")])
        head = step["head_after"]
    return out


def run(payload):
    """Entry point for POST /api/disk/run."""
    names = payload.get("algorithms") or ["SCAN", "PA-SCAN-BT"]
    if not 1 <= len(names) <= MAX_ALGORITHMS:
        raise LabError(f"choose 1 to {MAX_ALGORITHMS} algorithms")
    settings = payload.get("settings", {})
    workload = payload.get("workload", {"scenario": "mixed", "seed": 1})

    base, processes, bursty, head = build_workload(workload)
    injections = payload.get("injections", [])
    requests = add_injections(base, processes, injections, workload.get("seed", 1))
    if any(inj.get("kind") == "burst" for inj in injections):
        bursty.append(INJECTED_BURST_PID)
    by_id = sorted(requests, key=lambda r: r.request_id)

    runs = []
    for name in names:
        res = simulate(make_algorithm(name, settings), requests, initial_head=head)
        start = [0.0] * len(by_id)
        for r in res.served:
            start[r.request_id] = round(r.start_time, 3)
        runs.append({
            "name": res.algorithm,
            "start": start,
            "trajectory": [[round(t, 3), c] for t, c in res.trajectory],
            "decisions": _decisions(res, head),
            "makespan": round(res.makespan, 3),
        })

    return {
        "duration": max(r.arrival_time for r in requests) if workload.get("scenario") == "demo" else LAB_DURATION_MS,
        "bursty": bursty,
        "disk_size": config.DISK_SIZE,
        "service_time": config.SERVICE_TIME,
        "seek_time": config.SEEK_TIME_PER_CYLINDER,
        "deadline": float(settings.get("deadline", config.HIGH_DEADLINE)),
        "requests": [[r.request_id, r.process_id, r.track, r.arrival_time, r.priority] for r in by_id],
        "processes": {pid: [name, prio] for pid, (name, prio) in processes.items()},
        "runs": runs,
    }
