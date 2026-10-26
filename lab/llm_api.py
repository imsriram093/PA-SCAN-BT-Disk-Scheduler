"""
lab/llm_api.py  -  The LLM-serving half of the live lab.

Same idea as lab/disk_api.py: build a workload, add what the user injected
("flood", "chat users"), run the chosen policies with the SAME simulator as
llm_main.py, and pack the result so the browser can redraw the GPU batch.
"""

import random

from llm_serving import config, workloads
from llm_serving.baseline import FCFS, StrictPriority, FairShare, PrefixSweep
from llm_serving.enhanced import PriorityThrottledSweep
from llm_serving.request import Request
from llm_serving.simulator import simulate
from lab.disk_api import LabError

INTERACTIVE, STANDARD, BATCH = config.INTERACTIVE, config.STANDARD, config.BATCH

LAB_DURATION_MS = 30_000.0
MAX_POLICIES = 4
MAX_INJECTIONS = 40

POLICIES = {
    "FCFS": FCFS, "PRIORITY": StrictPriority, "FAIR-SHARE": FairShare,
    "PREFIX-SWEEP": PrefixSweep, "PA-SWEEP-BT": PriorityThrottledSweep,
}
SWEEP_POLICIES = {"PREFIX-SWEEP", "PA-SWEEP-BT"}     # the ones that have a "head" to draw

INJECTED_FLOOD_TENANT = 90
INJECTED_CHAT_TENANT = 91
TENANT_PRIORITY = {tid: prio for tid, _, prio, *_ in workloads.TENANTS}
TENANT_PRIORITY[workloads.FLOOD_TENANT] = BATCH
TENANT_PRIORITY[INJECTED_FLOOD_TENANT] = BATCH
TENANT_PRIORITY[INJECTED_CHAT_TENANT] = INTERACTIVE
TENANT_NAMES = dict(workloads.TENANT_NAMES)
TENANT_NAMES[INJECTED_FLOOD_TENANT] = "injected flood"
TENANT_NAMES[INJECTED_CHAT_TENANT] = "injected chat users"


def _inject(rng, kind, t, rid):
    """Requests for one injection, starting at time t with ids from rid."""
    if kind == "flood":       # 30 same-prefix BATCH requests within 0.5 s (like the flood scenario)
        return [Request(rid + i, INJECTED_FLOOD_TENANT, BATCH, round(t + rng.uniform(0, 500.0), 3),
                        rng.choice(workloads.FLOOD_PREFIXES), workloads.FLOOD_PREFIX_TOKENS,
                        rng.randint(500, 1500), rng.randint(150, 400))
                for i in range(workloads.FLOOD_SIZE)]
    if kind == "chat":        # 5 people open the chat app at once
        return [Request(rid + i, INJECTED_CHAT_TENANT, INTERACTIVE, round(t + rng.uniform(0, 100.0), 3),
                        rng.randrange(0, 4), 800, rng.randint(50, 400), rng.randint(30, 200))
                for i in range(5)]
    raise LabError(f"unknown injection '{kind}'")


def _segments(result):
    """When each request was in the batch: [request_id, admitted_at, left_at] rows.
    A preempted request has several rows. Admissions are at the START of a step."""
    finish = {r.request_id: r.finish_time for r in result.finished}
    open_at, rows = {}, []
    for step in result.trace:
        for r in step["preempted"]:                         # preemptions happen before admissions
            rows.append([r.request_id, round(open_at.pop(r.request_id), 3), round(step["start_time"], 3)])
        for r, _ in step["admitted"]:
            open_at[r.request_id] = step["start_time"]
    for rid, t in open_at.items():
        rows.append([rid, round(t, 3), round(finish[rid], 3)])
    return rows


def run(payload):
    """Entry point for POST /api/llm/run."""
    names = payload.get("algorithms") or ["PREFIX-SWEEP", "PA-SWEEP-BT"]
    if not 1 <= len(names) <= MAX_POLICIES:
        raise LabError(f"choose 1 to {MAX_POLICIES} policies")
    settings = payload.get("settings", {})
    workload = payload.get("workload", {"scenario": "flood", "seed": 1})
    seed = int(workload.get("seed", 1))
    scenario = workload.get("scenario", "flood")
    if scenario not in workloads.SCENARIOS:
        raise LabError(f"unknown scenario '{scenario}'")

    requests = workloads.generate(scenario, seed, duration_ms=LAB_DURATION_MS)
    injections = payload.get("injections", [])
    if len(injections) > MAX_INJECTIONS:
        raise LabError(f"at most {MAX_INJECTIONS} injections per run")
    for i, inj in enumerate(injections):
        rng = random.Random(f"{seed}/{i}/{inj.get('kind')}")
        requests += _inject(rng, inj.get("kind"), max(0.0, float(inj.get("t", 0.0))), len(requests))

    runs = []
    for name in names:
        if name not in POLICIES:
            raise LabError(f"unknown policy '{name}'")
        if name == "PA-SWEEP-BT":
            policy = PriorityThrottledSweep(burst_threshold=int(settings.get("k", config.BURST_THRESHOLD_K)),
                                            ttft_deadline=float(settings.get("deadline", config.TTFT_DEADLINE_MS)))
        else:
            policy = POLICIES[name]()
        res = simulate(policy, requests, keep_trace=True)

        first = [0.0] * len(requests)
        finish = [0.0] * len(requests)
        for r in res.finished:
            first[r.request_id] = round(r.first_token_time, 3)
            finish[r.request_id] = round(r.finish_time, 3)

        head, admissions, decisions = [], [], []
        for step in res.trace:
            t = round(step["start_time"], 3)
            throttle_logged = False                  # one throttling line per step is enough
            for (r, note), hit in zip(step["admitted"], step["cache_hits"]):
                admissions.append([t, r.request_id, int(hit)])
                if name in SWEEP_POLICIES and not note.startswith("TTFT GUARD"):
                    head.append([t, r.prefix_id])
                if "GUARD" in note or "preempt" in note:
                    decisions.append([t, r.request_id, note.rstrip("; ")])
                elif "deferred" in note and not throttle_logged:
                    decisions.append([t, r.request_id, note.rstrip("; ")])
                    throttle_logged = True

        runs.append({
            "name": res.algorithm,
            "first": first,
            "finish": finish,
            "segments": _segments(res),
            "head": head,
            "admissions": admissions,
            "decisions": decisions,
            "makespan": round(res.makespan, 3),
        })

    return {
        "duration": LAB_DURATION_MS,
        "num_prefixes": config.NUM_PREFIXES,
        "max_seqs": config.MAX_BATCH_SEQS,
        "slo": {config.PRIORITY_NAMES[p]: v for p, v in config.TTFT_SLO_MS.items()},
        "deadline": float(settings.get("deadline", config.TTFT_DEADLINE_MS)),
        "requests": [[r.request_id, r.tenant_id, r.priority, r.arrival_time, r.prefix_id,
                      r.prompt_len, r.output_tokens] for r in requests],
        "tenants": {tid: [TENANT_NAMES.get(tid, f"tenant {tid}"), TENANT_PRIORITY.get(tid, BATCH)]
                    for tid in sorted({r.tenant_id for r in requests})},
        "flood_tenants": [workloads.FLOOD_TENANT, INJECTED_FLOOD_TENANT],
        "runs": runs,
    }
