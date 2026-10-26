"""
workloads.py  -  Generates the test data (synthetic disk request streams).

A workload is simply a list of Request objects. We build it from a few
imaginary processes, each with a priority, a request rate and a favourite
part of the disk. Arrivals are random (a Poisson process - the standard way
to model "requests arrive independently at some average rate").

Using a fixed random SEED means the same workload is produced every time,
so every algorithm sees exactly the same requests and results are repeatable.

Scenarios
---------
mixed  : normal multi-programming load, mixed priorities, random tracks
burst  : mixed load + one "backup" process that dumps big bursts of requests
         into a small region of the disk (the head-hogging problem)
heavy  : mixed load pushed close to the disk's maximum capacity
demo   : 14 hand-made requests used by `python main.py --demo`
"""

import random

import config
from scheduler.request import Request

HIGH, MEDIUM, LOW = config.HIGH, config.MEDIUM, config.LOW

LAST = config.DISK_SIZE - 1
# Cylinder ranges are fractions of the disk, so changing DISK_SIZE in config.py just works.
BURST_REGION = (int(0.30 * config.DISK_SIZE), int(0.45 * config.DISK_SIZE))   # 60-90 on a 200-cylinder disk

# (process_id, name, priority, share of the total arrival rate, (low_track, high_track))
BACKGROUND_PROCESSES = [
    (1, "kernel-pager",   HIGH,   0.10, (0, LAST)),
    (2, "text-editor",    MEDIUM, 0.15, (0, LAST)),
    (3, "web-browser",    MEDIUM, 0.15, (0, LAST)),
    (4, "log-writer",     LOW,    0.20, (int(0.70 * config.DISK_SIZE), LAST)),   # 140-199
    (5, "file-indexer",   LOW,    0.20, (0, LAST)),
    (6, "antivirus-scan", LOW,    0.20, (0, LAST)),
]
BACKUP_PID = 7   # the bursty "hog" process in the burst scenario
PROCESS_NAMES = {pid: name for pid, name, *_ in BACKGROUND_PROCESSES}
PROCESS_NAMES[BACKUP_PID] = "backup (burst hog)"


def _poisson_arrivals(rng, rate_per_sec, duration_ms):
    """Random arrival times with the given average rate (exponential gaps)."""
    times, t = [], 0.0
    rate_per_ms = rate_per_sec / 1000.0
    while True:
        t += rng.expovariate(rate_per_ms)
        if t >= duration_ms:
            return times
        times.append(t)


def _background(rng, total_rate, duration_ms):
    """Requests from the six 'normal' processes."""
    raw = []
    for pid, _, prio, share, (lo, hi) in BACKGROUND_PROCESSES:
        for t in _poisson_arrivals(rng, total_rate * share, duration_ms):
            raw.append((t, pid, rng.randint(lo, hi), prio))
    return raw


def _bursts(rng, duration_ms, burst_every_ms=500.0, burst_size=40, region=BURST_REGION,
            pid=BACKUP_PID, priority=LOW):
    """The backup process: every `burst_every_ms` it fires `burst_size` LOW
    requests within ~2 ms, all inside a narrow band of cylinders.
    40 requests x 4 ms = 160 ms of disk time demanded in one go."""
    raw, start = [], 50.0
    while start < duration_ms:
        for _ in range(burst_size):
            raw.append((start + rng.uniform(0, 2.0), pid, rng.randint(*region), priority))
        start += burst_every_ms
    return raw


def _to_requests(raw):
    raw.sort()
    return [Request(i, pid, track, round(t, 3), prio)
            for i, (t, pid, track, prio) in enumerate(raw)]


SCENARIOS = {
    # name      (background requests/sec, add bursts?, description)
    "mixed": (130, False, "Mixed priorities, moderate load (130 requests/s)"),
    "burst": (100, True,  "100 requests/s + a backup process firing 40-request bursts every 500 ms"),
    "heavy": (160, False, "Mixed priorities, heavy load (160 requests/s)"),
}


def generate(scenario, seed, rate=None, duration_ms=config.DURATION_MS):
    """Build one workload. `rate` overrides the background requests per second."""
    rng = random.Random(seed)
    default_rate, with_bursts, _ = SCENARIOS[scenario]
    raw = _background(rng, rate or default_rate, duration_ms)
    if with_bursts:
        raw += _bursts(rng, duration_ms)
    return _to_requests(raw)


def generate_custom(spec, seed, duration_ms=config.DURATION_MS):
    """Build a workload from a custom spec (used by the live lab and its AI co-pilot).

    spec = {"processes": [{"name", "priority", "rate", "region": (lo, hi)}, ...],
            "bursts":    [{"name", "priority", "every_ms", "size", "region": (lo, hi)}, ...]}
    Process ids are 1, 2, ... in the order listed (processes first, then bursts).
    """
    rng = random.Random(seed)
    raw, pid = [], 0
    for p in spec["processes"]:
        pid += 1
        for t in _poisson_arrivals(rng, p["rate"], duration_ms):
            raw.append((t, pid, rng.randint(*p["region"]), p["priority"]))
    for b in spec.get("bursts", []):
        pid += 1
        raw += _bursts(rng, duration_ms, b["every_ms"], b["size"], tuple(b["region"]), pid, b["priority"])
    return _to_requests(raw)


def demo_workload():
    """Small, hand-made example (everything arrives at t = 0, head at 50 moving UP).
    Process 7 is a 'backup' burst of 8 LOW requests packed between cylinders 55-76."""
    spec = [
        # pid, track, priority
        (7, 55, LOW), (7, 58, LOW), (7, 61, LOW), (7, 64, LOW),
        (7, 67, LOW), (7, 70, LOW), (7, 73, LOW), (7, 76, LOW),
        (2, 120, MEDIUM), (2, 160, MEDIUM),
        (5, 140, LOW), (5, 10, LOW),
        (1, 100, HIGH), (1, 35, HIGH),
    ]
    return [Request(i, pid, track, 0.0, prio) for i, (pid, track, prio) in enumerate(spec)]
