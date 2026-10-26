"""
workloads.py  -  Generates the test data (synthetic LLM request streams).

A workload is a list of Request objects from a few imaginary tenants. Each
tenant has a priority, a share of the traffic, its own shared prefixes
(system prompts or documents) and typical prompt / output lengths.
Arrivals are a Poisson process, and a fixed random SEED makes every
workload repeatable, so every policy sees exactly the same requests.

Scenarios
---------
mixed  : normal API traffic, mixed priorities (8 requests/s, ~80% of capacity)
flood  : lighter traffic + one tenant that dumps 30 same-prefix BATCH requests
         every 10 s (the LLM version of the disk project's backup burst)
heavy  : mixed traffic close to the server's capacity (9.5 requests/s)
demo   : a handful of hand-made requests used by `python llm_main.py --demo`
"""

import random

from llm_serving import config
from llm_serving.request import Request

INTERACTIVE, STANDARD, BATCH = config.INTERACTIVE, config.STANDARD, config.BATCH

# (tenant_id, name, priority, share of traffic, prefix ids, prefix tokens, own prompt range, output range)
TENANTS = [
    (1, "chat-app",        INTERACTIVE, 0.20, list(range(0, 4)),   800, (50, 400),   (30, 200)),
    (2, "code-assistant",  INTERACTIVE, 0.10, list(range(4, 8)),  1500, (200, 1500), (20, 120)),
    (3, "rag-search",      STANDARD,    0.25, list(range(8, 24)) + list(range(26, 38)), 2000, (300, 1000), (50, 250)),
    (4, "agent-workflows", STANDARD,    0.15, list(range(38, 46)), 1200, (100, 800),  (50, 300)),
    (5, "eval-batch",      BATCH,       0.15, list(range(46, 54)), 1000, (200, 1200), (100, 400)),
    (6, "summarizer",      BATCH,       0.15, list(range(54, 64)),  500, (1000, 3000), (100, 300)),
]
FLOOD_TENANT = 7   # the flooding tenant in the flood scenario
FLOOD_PREFIXES, FLOOD_PREFIX_TOKENS = [24, 25], 1500   # in the middle of the prefix range, like the disk burst
FLOOD_FIRST_MS, FLOOD_EVERY_MS, FLOOD_SPAN_MS, FLOOD_SIZE = 2000.0, 10_000.0, 500.0, 30
TENANT_NAMES = {tid: name for tid, name, *_ in TENANTS}
TENANT_NAMES[FLOOD_TENANT] = "bulk-import (flood)"


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
    """Requests from the six 'normal' tenants."""
    raw = []
    for tid, _, prio, share, prefixes, prefix_tokens, prompt, output in TENANTS:
        for t in _poisson_arrivals(rng, total_rate * share, duration_ms):
            raw.append((t, tid, prio, rng.choice(prefixes), prefix_tokens,
                        rng.randint(*prompt), rng.randint(*output)))
    return raw


def flood_windows(duration_ms=config.DURATION_MS):
    """(start, end) of every flood in ms (also used to shade the timeline graph)."""
    windows, start = [], FLOOD_FIRST_MS
    while start < duration_ms:
        windows.append((start, start + FLOOD_SPAN_MS))
        start += FLOOD_EVERY_MS
    return windows


def _floods(rng, duration_ms):
    """The bulk-import tenant: every FLOOD_EVERY_MS it sends FLOOD_SIZE BATCH requests
    within FLOOD_SPAN_MS, all sharing two prefixes (so they are all cache hits)."""
    raw = []
    for start, end in flood_windows(duration_ms):
        for _ in range(FLOOD_SIZE):
            raw.append((rng.uniform(start, end), FLOOD_TENANT, BATCH, rng.choice(FLOOD_PREFIXES),
                        FLOOD_PREFIX_TOKENS, rng.randint(500, 1500), rng.randint(150, 400)))
    return raw


def _to_requests(raw):
    raw.sort()
    return [Request(i, tid, prio, round(t, 3), prefix, prefix_tokens, prompt, output)
            for i, (t, tid, prio, prefix, prefix_tokens, prompt, output) in enumerate(raw)]


SCENARIOS = {
    # name      (background requests/sec, add floods?, description)
    "mixed": (8.0, False, "Mixed priorities, moderate load (8 requests/s)"),
    "flood": (5.0, True,  "5 requests/s + a tenant flooding 30 same-prefix BATCH requests every 10 s"),
    "heavy": (9.5, False, "Mixed priorities, heavy load (9.5 requests/s)"),
}


def generate(scenario, seed, rate=None, duration_ms=config.DURATION_MS):
    """Build one workload. `rate` overrides the background requests per second."""
    rng = random.Random(seed)
    default_rate, with_floods, _ = SCENARIOS[scenario]
    raw = _background(rng, rate or default_rate, duration_ms)
    if with_floods:
        raw += _floods(rng, duration_ms)
    return _to_requests(raw)


def demo_workload():
    """Small, hand-made example for a 4-slot server (see llm_main.py --demo).
    Tenant 7 floods 6 BATCH requests on prefix 24 at t = 0; two chat users
    (INTERACTIVE) arrive a little later."""
    spec = [
        # tenant, priority, arrival, prefix, prefix tokens, own prompt, output
        (7, BATCH,       0.0, 24, 1500, 500, 60),
        (7, BATCH,       0.0, 24, 1500, 500, 60),
        (7, BATCH,       0.0, 24, 1500, 500, 60),
        (7, BATCH,       0.0, 24, 1500, 500, 60),
        (7, BATCH,       0.0, 24, 1500, 500, 60),
        (7, BATCH,       0.0, 24, 1500, 500, 60),
        (3, STANDARD,    0.0, 30, 2000, 300, 40),
        (5, BATCH,       0.0, 50, 1000, 300, 30),
        (1, INTERACTIVE, 5.0,  2,  800, 100, 20),
        (1, INTERACTIVE, 40.0, 3,  800, 100, 20),
    ]
    return [Request(i, tid, prio, t, prefix, ptok, prompt, out)
            for i, (tid, prio, t, prefix, ptok, prompt, out) in enumerate(spec)]
