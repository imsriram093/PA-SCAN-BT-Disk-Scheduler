"""
metrics.py  -  Turns a SimulationResult into the numbers we compare.

Metric                    Meaning                                                  Better
------------------------  -------------------------------------------------------  ------
ttft_INTERACTIVE/...      average Time To First Token inside each priority class   lower
p99_INTERACTIVE/...       99% of that class got its first token faster than this   lower
slo_INTERACTIVE           share of INTERACTIVE requests with TTFT <= 300 ms (%)    higher
slo_STANDARD              share of STANDARD requests with TTFT <= 2000 ms (%)      higher
avg_ttft / p99_ttft       over all requests                                        lower
max_ttft                  the single worst TTFT  -> starvation indicator           lower
avg_latency               arrival -> last token, all requests                      lower
latency_BATCH             end-to-end latency of BATCH work (the price we pay)      lower
avg_tpot                  ms per output token after the first (streaming speed)    lower
throughput                output tokens per second                                 higher
cache_hit_rate            admissions whose prefix was cached (%)                   higher
preemptions               requests pushed out of the batch                         (info)
ttft_victims              avg TTFT of the normal tenants (not the flooder)         lower
ttft_flood                avg TTFT of the flooding tenant                          (info)
"""

import statistics

from llm_serving import config
from llm_serving.workloads import FLOOD_TENANT


def _percentile(values, pct):
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(pct / 100 * len(ordered))) - 1))
    return ordered[index]


def compute(result):
    done = result.finished
    ttfts = [r.ttft for r in done]

    m = {
        "algorithm": result.algorithm,
        "requests": len(done),
        "avg_ttft": statistics.mean(ttfts),
        "p99_ttft": _percentile(ttfts, 99),
        "max_ttft": max(ttfts),
        "avg_latency": statistics.mean(r.latency for r in done),
        "avg_tpot": statistics.mean(r.tpot for r in done),
        "throughput": sum(r.output_tokens for r in done) / (result.makespan / 1000.0),
        "cache_hit_rate": 100.0 * result.cache_hits / result.admissions,
        "preemptions": result.preemptions,
    }

    for prio, name in config.PRIORITY_NAMES.items():
        group = [r for r in done if r.priority == prio]
        if group:
            m[f"ttft_{name}"] = statistics.mean(r.ttft for r in group)
            m[f"p99_{name}"] = _percentile([r.ttft for r in group], 99)
            m[f"latency_{name}"] = statistics.mean(r.latency for r in group)
        else:
            m[f"ttft_{name}"] = m[f"p99_{name}"] = m[f"latency_{name}"] = 0.0
        if prio in config.TTFT_SLO_MS:
            slo = config.TTFT_SLO_MS[prio]
            m[f"slo_{name}"] = 100.0 * sum(r.ttft <= slo for r in group) / len(group) if group else 100.0

    victims = [r.ttft for r in done if r.tenant_id != FLOOD_TENANT]
    flood = [r.ttft for r in done if r.tenant_id == FLOOD_TENANT]
    m["ttft_victims"] = statistics.mean(victims)
    m["p99_victims"] = _percentile(victims, 99)
    m["ttft_flood"] = statistics.mean(flood) if flood else 0.0
    return m


def average(metric_dicts):
    """Mean of each numeric metric over several seeds."""
    out = {"algorithm": metric_dicts[0]["algorithm"]}
    for key in metric_dicts[0]:
        if key != "algorithm":
            out[key] = statistics.mean(d[key] for d in metric_dicts)
    return out


def per_tenant_ttft(result):
    """Average TTFT of every tenant (used for the fairness graph)."""
    groups = {}
    for r in result.finished:
        groups.setdefault(r.tenant_id, []).append(r.ttft)
    return {tid: statistics.mean(t) for tid, t in sorted(groups.items())}
