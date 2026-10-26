"""
simulator.py  -  The clock: plays the role of the GPU serving engine.

It works like a continuous-batching engine (vLLM, TGI, SGLang):

    1. Requests ARRIVE over time and wait in a queue.
    2. Before every step the engine asks the scheduling policy
           "here is the queue - who joins the batch next?"
       and keeps admitting while the batch, the KV memory and the prefill
       budget have room. (A policy may ask to preempt a running request.)
    3. It runs one step: running requests produce one token each, new ones
       are prefilled and produce their first token.
    4. Finished requests leave and free their memory. Repeat.

The SAME simulator runs EVERY policy on the SAME list of requests,
so the only thing that changes between runs is the admission decision.
"""

from dataclasses import dataclass, field

from llm_serving.server import PrefixCache, ServerSpec


@dataclass
class SimulationResult:
    algorithm: str
    finished: list                    # requests in the order they finished (with times filled in)
    makespan: float                   # time when the last request finished
    steps: int                        # forward passes run
    preemptions: int                  # requests pushed out of the batch
    cache_hits: int                   # admissions whose prefix was cached
    admissions: int                   # admissions in total (re-admissions included)
    prefill_tokens: int               # prompt tokens actually computed
    timeline: list = field(default_factory=list)   # (time, running, waiting) after every step
    trace: list = field(default_factory=list)      # human-readable steps (used by --demo)


def prefill_cost(request, cache):
    """Prompt tokens that must be computed to (re-)admit `request`.
    A preempted request also recomputes the tokens it had already generated."""
    shared = 0 if cache.contains(request.prefix_id) else request.prefix_tokens
    return shared + request.prompt_tokens + request.generated


def simulate(scheduler, requests, server=None, keep_trace=False):
    """Run one policy on one workload and return what happened."""
    server = server or ServerSpec()

    # Work on fresh copies so the original workload can be reused by other policies.
    incoming = sorted((r.fresh_copy() for r in requests),
                      key=lambda r: (r.arrival_time, r.request_id))
    scheduler.reset()
    cache = PrefixCache(server.prefix_cache_tokens)

    waiting, running, finished = [], [], []
    timeline, trace = [], []
    time = 0.0
    kv_used = 0
    next_arrival = 0
    steps = preemptions = cache_hits = admissions = total_prefill = 0

    while len(finished) < len(incoming):
        # (1) Admit every request that has arrived by now into the queue.
        while next_arrival < len(incoming) and incoming[next_arrival].arrival_time <= time:
            waiting.append(incoming[next_arrival])
            next_arrival += 1

        # (2) Nothing to do? The GPU sits idle until the next request arrives.
        if not waiting and not running:
            time = incoming[next_arrival].arrival_time
            continue

        # (3) Admission: ask the policy, keep going while there is room.
        decoding = list(running)          # already running -> they decode this step
        admitted, preempted, notes, hits = [], [], [], []
        step_start = time
        step_prefill = 0
        while waiting:
            cand = scheduler.pick(waiting, time)
            cost = prefill_cost(cand, cache)
            if step_prefill and step_prefill + cost > server.max_prefill_tokens:
                break                     # prefill budget used up (a huge prompt may go alone)

            def fits():
                return (len(running) < server.max_seqs
                        and kv_used + cand.kv_tokens <= server.kv_cache_tokens)

            while not fits():
                victim = scheduler.victim(cand, decoding, time)
                if victim is None:
                    break
                running.remove(victim)
                decoding.remove(victim)
                kv_used -= victim.kv_tokens
                victim.preemptions += 1
                waiting.append(victim)
                preempted.append(victim)
                preemptions += 1
            if not fits():
                break                     # no room this step: try again next step

            waiting.remove(cand)
            cand.cache_hit = cache.lookup(cand.prefix_id, cand.prefix_tokens)
            cache_hits += cand.cache_hit
            admissions += 1
            step_prefill += cost
            if cand.admit_time is None:
                cand.admit_time = time
            scheduler.on_admit(cand, time)
            running.append(cand)
            admitted.append(cand)
            kv_used += cand.kv_tokens
            notes.append(getattr(scheduler, "last_note", ""))
            hits.append(cand.cache_hit)

        if not running:
            raise ValueError("a waiting request can never fit on this server "
                             "(prompt + output larger than the KV cache)")

        # (4) Run one step.
        time += server.step_time(len(decoding), step_prefill)
        steps += 1
        total_prefill += step_prefill
        still_running = []
        for r in running:
            r.generated += 1
            if r.first_token_time is None:
                r.first_token_time = time
            if r.generated >= r.output_tokens:
                r.finish_time = time
                finished.append(r)
                kv_used -= r.kv_tokens
            else:
                still_running.append(r)
        running = still_running
        timeline.append((time, len(running), len(waiting)))

        if keep_trace and (admitted or preempted):
            trace.append({
                "step": steps,
                "start_time": step_start,
                "end_time": time,
                "admitted": list(zip(admitted, notes)),
                "cache_hits": hits,               # parallel to "admitted"
                "preempted": preempted,
                "prefill_tokens": step_prefill,
                "running": len(running),
                "waiting": len(waiting),
            })

    return SimulationResult(
        algorithm=scheduler.name,
        finished=finished,
        makespan=time,
        steps=steps,
        preemptions=preemptions,
        cache_hits=cache_hits,
        admissions=admissions,
        prefill_tokens=total_prefill,
        timeline=timeline,
        trace=trace,
    )
