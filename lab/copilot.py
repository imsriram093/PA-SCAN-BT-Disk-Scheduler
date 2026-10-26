"""
lab/copilot.py  -  The AI co-pilot: an LLM working FOR the operating system.

The rest of the project is about scheduling FOR LLMs (llm_serving/). This file
goes the other way and uses an LLM (Claude) to help a human work with the disk
scheduler. It has three features:

  1. SCENARIO FROM ENGLISH   "a database server during the nightly backup"
                             -> a validated workload spec the simulator can run
  2. EXPLAIN A DECISION      "why did the arm turn around at t = 812 ms?"
                             -> a short plain-English answer naming the rule
  3. VERIFIED AUTO-TUNER     the LLM proposes values for K / deadline / aging,
                             and the SIMULATOR decides whether to accept them

The design rule behind all three: the LLM is never trusted blindly.
  - Its workload specs are clamped to safe ranges before they are used.
  - Its tuning ideas are re-measured on held-out random seeds it never saw,
    and are rejected if they do not beat the default settings there.
    ("the LLM proposes, the simulator disposes")
  - Every feature has an OFFLINE engine (keyword parser, rule templates,
    grid search), so the demo still works with no internet and no API key.

Claude is used only if the `anthropic` package is installed and credentials are
available (e.g. the ANTHROPIC_API_KEY environment variable). Otherwise, or if a
call fails, the offline engine answers and the reply says so.
"""

import json
import os
import re
import time

import config
from lab.disk_api import LabError
from scheduler import metrics, workloads
from scheduler.baseline import SCAN, LOOK
from scheduler.enhanced import PriorityThrottledSCAN
from scheduler.simulator import simulate

HIGH, MEDIUM, LOW = config.HIGH, config.MEDIUM, config.LOW
PRIORITY_BY_NAME = {"HIGH": HIGH, "MEDIUM": MEDIUM, "LOW": LOW}
LAST = config.DISK_SIZE - 1

MODEL = "claude-opus-5-5"
_state = {"client": None, "disabled": None}     # disabled = reason string after a failed call


# ---------------------------------------------------------------------------
# Talking to Claude
# ---------------------------------------------------------------------------
def status():
    """What the co-pilot will use, for the badge in the browser."""
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return {"online": False, "reason": "offline engine (pip install anthropic to enable Claude)"}
    if _state["disabled"]:
        return {"online": False, "reason": f"offline engine ({_state['disabled']})"}
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
            or os.environ.get("ANTHROPIC_PROFILE")):
        return {"online": True, "reason": f"{MODEL} (no API key in the environment; will try a saved login)"}
    return {"online": True, "reason": MODEL}


def _ask_claude(system, user, schema=None, max_tokens=8000):
    """One Claude request. Returns parsed JSON when `schema` is given, else text.
    Raises RuntimeError with a short reason on any failure."""
    if _state["disabled"]:
        raise RuntimeError(_state["disabled"])
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("anthropic package not installed")

    output_config = {"effort": "low"}          # short, simple tasks: keep the live demo snappy
    if schema:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    try:
        if _state["client"] is None:
            _state["client"] = anthropic.Anthropic(timeout=60.0)
        response = _state["client"].beta.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config=output_config,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
        _state["disabled"] = "no valid Claude credentials"
        raise RuntimeError(_state["disabled"])
    except anthropic.APIConnectionError:
        raise RuntimeError("could not reach the Claude API (offline?)")
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Claude API error {e.status_code}")
    except anthropic.AnthropicError as e:
        raise RuntimeError(f"Claude client error: {e}")

    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined this request")
    text = "".join(b.text for b in response.content if b.type == "text")
    if not schema:
        return text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError("Claude returned malformed JSON")


DISK_MODEL_FACTS = f"""The simulated hard disk has {config.DISK_SIZE} cylinders (0-{LAST}).
Moving the arm costs {config.SEEK_TIME_PER_CYLINDER} ms per cylinder (full stroke 20 ms) and serving
a request costs {config.SERVICE_TIME} ms, so the disk handles roughly 200 requests/s in total.
Each process has a fixed priority:
  HIGH   = latency-critical I/O: page faults, file-system journal commits (should start within 40 ms)
  MEDIUM = interactive applications: editors, browsers, databases answering users
  LOW    = background work: backups, indexing, antivirus scans, log writing, updates
A process sends requests at an average rate (Poisson arrivals) to a range of cylinders.
A "burst" process instead dumps `size` requests at once every `every_ms` ms into a narrow
cylinder range - this is the head-hogging behaviour PA-SCAN-BT throttles.
PA-SCAN-BT = elevator (LOOK) + Rule 1 priority guard (HIGH deadline) + Rule 2 burst-throttling
(K requests per sweep for a LOW process, 2K for MEDIUM) + Rule 3 aging (a request older than the
aging limit can no longer be throttled)."""


# ---------------------------------------------------------------------------
# 1. Scenario from English
# ---------------------------------------------------------------------------
_PROCESS_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "priority": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
        "rate_per_sec": {"type": "number"},
        "region_start": {"type": "integer"},
        "region_end": {"type": "integer"},
        "why": {"type": "string"},
    },
    "required": ["name", "priority", "rate_per_sec", "region_start", "region_end", "why"],
    "additionalProperties": False,
}
_BURST_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "priority": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
        "every_ms": {"type": "number"},
        "size": {"type": "integer"},
        "region_start": {"type": "integer"},
        "region_end": {"type": "integer"},
        "why": {"type": "string"},
    },
    "required": ["name", "priority", "every_ms", "size", "region_start", "region_end", "why"],
    "additionalProperties": False,
}
SCENARIO_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "processes": {"type": "array", "items": _PROCESS_SCHEMA},
        "bursts": {"type": "array", "items": _BURST_SCHEMA},
    },
    "required": ["title", "summary", "processes", "bursts"],
    "additionalProperties": False,
}
SCENARIO_SYSTEM = f"""You turn a plain-English description of a computer's workload into a disk
workload for an operating-systems teaching simulator.

{DISK_MODEL_FACTS}

Rules for the spec you return:
- 2 to 8 steady processes and 0 to 3 burst processes. Give processes short names (e.g. "kernel-pager").
- The TOTAL load = steady rates + each burst's average rate (size * 1000 / every_ms). Keep it between
  80 and 180 requests/s so the scenario is busy but not hopelessly overloaded (above ~200 req/s the
  queue grows without bound for every algorithm), unless the description clearly asks for overload.
- Bursts: size 10-80, every_ms 200-3000, narrow cylinder range (10-40 cylinders wide).
- Use cylinder regions to model locality (a database lives in one area, logs at the end of the disk).
- Include at least one HIGH process (page faults happen on every real system).
- `summary`: 1-2 sentences saying what the scenario will show about the schedulers.
- `why`: a few words per process explaining the choice."""


MAX_TOTAL_RATE = 220.0      # requests/s, steady + average burst rate
MAX_BURST_RATE = 120.0      # requests/s from all bursts together (the built-in burst scenario has 80)


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def sanitize_spec(raw):
    """Turn an (untrusted) spec into a safe one. Returns (spec, warnings).
    The spec format is the one scheduler.workloads.generate_custom() expects,
    plus display fields (title, summary, why)."""
    warnings = []
    processes, bursts = [], []
    for p in list(raw.get("processes", []))[:8]:
        lo = _clamp(int(p.get("region_start", 0)), 0, LAST)
        hi = _clamp(int(p.get("region_end", LAST)), 0, LAST)
        processes.append({
            "name": str(p.get("name", "process"))[:32],
            "priority": PRIORITY_BY_NAME.get(str(p.get("priority", "LOW")).upper(), LOW),
            "rate": round(_clamp(float(p.get("rate_per_sec", 20)), 1.0, 150.0), 1),
            "region": [min(lo, hi), max(lo, hi)],
            "why": str(p.get("why", ""))[:120],
        })
    for b in list(raw.get("bursts", []))[:3]:
        lo = _clamp(int(b.get("region_start", 60)), 0, LAST)
        hi = _clamp(int(b.get("region_end", 90)), 0, LAST)
        bursts.append({
            "name": str(b.get("name", "burst"))[:32],
            "priority": PRIORITY_BY_NAME.get(str(b.get("priority", "LOW")).upper(), LOW),
            "every_ms": round(_clamp(float(b.get("every_ms", 500)), 200.0, 3000.0)),
            "size": _clamp(int(b.get("size", 40)), 5, 80),
            "region": [min(lo, hi), max(lo, hi)],
            "why": str(b.get("why", ""))[:120],
        })
    if not processes:
        warnings.append("no steady processes were given, so a default mixed workload was added")
        processes = [_template_process(t) for t in DEFAULT_TEMPLATES]
    if not any(p["priority"] == HIGH for p in processes + bursts):
        warnings.append("no HIGH-priority process was given, so a kernel page-fault process was added")
        processes.append(_template_process(TEMPLATES[0]))

    # Hard ceiling: the disk serves ~200 req/s; allow mild overload but not a runaway queue.
    bursts_rate = sum(b["size"] * 1000.0 / b["every_ms"] for b in bursts)
    if bursts_rate > MAX_BURST_RATE:                 # bursts alone may not swamp the disk: space them out
        for b in bursts:
            b["every_ms"] = round(b["every_ms"] * bursts_rate / MAX_BURST_RATE)
        warnings.append(f"bursts averaged {bursts_rate:.0f} req/s; they were spaced out to {MAX_BURST_RATE:.0f} req/s")
        bursts_rate = sum(b["size"] * 1000.0 / b["every_ms"] for b in bursts)
    steady = sum(p["rate"] for p in processes)
    if steady + bursts_rate > MAX_TOTAL_RATE:
        scale = max(20.0, MAX_TOTAL_RATE - bursts_rate) / steady
        for p in processes:
            p["rate"] = round(max(1.0, p["rate"] * scale), 1)
        warnings.append(f"total load {steady + bursts_rate:.0f} req/s is far above the disk's ~200 req/s capacity; "
                        f"steady rates were scaled down")

    spec = {
        "title": str(raw.get("title", "Custom workload"))[:80],
        "summary": str(raw.get("summary", ""))[:400],
        "processes": processes,
        "bursts": bursts,
    }
    return spec, warnings


# ---- offline engine: keyword templates ------------------------------------
#  (keywords, name, priority, rate/s, region)
TEMPLATES = [
    (("page fault", "page faults", "paging", "pager", "kernel", "swap", "swapping", "memory", "ram"),
     "kernel-pager", HIGH, 14, (0, LAST)),
    (("journal", "filesystem", "file system", "metadata", "fsync", "commit"),
     "fs-journal", HIGH, 8, (0, 25)),
    (("database", "db", "sql", "mysql", "postgres", "oracle", "server", "transactions"),
     "database", MEDIUM, 40, (20, 80)),
    (("browser", "web", "chrome", "firefox", "browsing"), "web-browser", MEDIUM, 20, (0, LAST)),
    (("editor", "ide", "office", "word", "excel", "coding", "vscode"), "text-editor", MEDIUM, 15, (0, LAST)),
    (("video", "stream", "streaming", "movie", "media", "netflix", "youtube", "music", "render", "rendering"),
     "media-player", MEDIUM, 30, (110, 170)),
    (("game", "gaming", "games"), "game-loader", MEDIUM, 25, (60, 140)),
    (("compile", "compiling", "build", "building", "compiler", "make"), "compiler", LOW, 30, (0, LAST)),
    (("antivirus", "virus", "malware", "defender", "scanner"), "antivirus-scan", LOW, 30, (0, LAST)),
    (("index", "indexing", "indexer", "search"), "file-indexer", LOW, 25, (0, LAST)),
    (("log", "logs", "logging", "logger"), "log-writer", LOW, 25, (140, LAST)),
    (("download", "downloads", "downloading", "torrent"), "downloader", LOW, 35, (150, LAST)),
]
DEFAULT_TEMPLATES = [TEMPLATES[0], TEMPLATES[3], TEMPLATES[4], TEMPLATES[8], TEMPLATES[9], TEMPLATES[10]]
#  (keywords, name, priority, every ms, size, region)
BURST_TEMPLATES = [
    (("backup", "backups", "snapshot"), "backup", LOW, 500, 40, (60, 90)),
    (("copy", "copying", "sync", "syncing", "dropbox", "onedrive", "cloud"), "file-sync", LOW, 700, 30, (100, 130)),
    (("update", "updates", "install", "installing", "patch"), "os-update", LOW, 900, 50, (20, 50)),
]
HEAVY_WORDS = ("heavy", "busy", "overloaded", "overload", "stress", "peak", "rush", "lots", "many")
LIGHT_WORDS = ("light", "idle", "quiet", "calm", "few")


def _has(text, words):
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)


def _template_process(t):
    _, name, prio, rate, region = t
    return {"name": name, "priority": prio, "rate": float(rate), "region": list(region),
            "why": "keyword match (offline engine)"}


def _offline_scenario(text):
    low = text.lower()
    processes = [_template_process(t) for t in TEMPLATES if _has(low, t[0])]
    bursts = [{"name": n, "priority": p, "every_ms": every, "size": size, "region": list(region),
               "why": "keyword match (offline engine)"}
              for words, n, p, every, size, region in BURST_TEMPLATES if _has(low, words)]
    notes = []
    if not processes:
        processes = [_template_process(t) for t in DEFAULT_TEMPLATES]
        notes.append("no known process keywords, so a default desktop mix was used")
    elif len(processes) < 3:          # keep the disk busy enough to show a difference
        have = {p["name"] for p in processes}
        processes += [_template_process(t) for t in (TEMPLATES[8], TEMPLATES[9], TEMPLATES[3])
                      if t[1] not in have][:3 - len(processes)]
    if not any(p["priority"] == HIGH for p in processes):
        processes.append(_template_process(TEMPLATES[0]))
        notes.append("kernel page faults (HIGH) added, since every real system has them")

    m = re.search(r"every\s+(\d+(?:\.\d+)?)\s*(ms|milliseconds?|s|sec|seconds?)\b", low)
    if m and bursts:
        every = float(m.group(1)) * (1 if m.group(2).startswith("m") else 1000)
        for b in bursts:
            b["every_ms"] = every

    # The disk serves about 200 req/s. Budget the TOTAL load (steady + average burst rate) like the
    # built-in scenarios: ~150 normal (mixed 130, burst 100+80), ~175 heavy (heavy 160), ~100 light.
    total = 175.0 if _has(low, HEAVY_WORDS) else 100.0 if _has(low, LIGHT_WORDS) else 150.0
    burst_rate = sum(b["size"] * 1000.0 / b["every_ms"] for b in bursts)
    target = max(40.0, total - burst_rate)
    steady = sum(p["rate"] for p in processes)
    for p in processes:
        p["rate"] = round(p["rate"] * target / steady, 1)

    names = ", ".join(p["name"] for p in processes + bursts)
    short = text.strip() if len(text.strip()) <= 60 else text.strip()[:60].rsplit(" ", 1)[0] + "..."
    raw = {
        "title": "Workload: " + short,
        "summary": f"Built by the offline keyword engine from: {names}. " + "; ".join(notes),
        "processes": [dict(p, priority=config.PRIORITY_NAMES[p["priority"]], rate_per_sec=p["rate"],
                           region_start=p["region"][0], region_end=p["region"][1]) for p in processes],
        "bursts": [dict(b, priority=config.PRIORITY_NAMES[b["priority"]],
                        region_start=b["region"][0], region_end=b["region"][1]) for b in bursts],
    }
    return raw


def scenario_from_text(text, use_llm=True):
    """Entry point for POST /api/copilot/scenario."""
    text = (text or "").strip()
    if not text:
        raise LabError("describe a workload first")
    if len(text) > 1000:
        raise LabError("please keep the description under 1000 characters")
    engine, fallback_reason = "offline keyword engine", None
    raw = None
    if use_llm:
        try:
            raw = _ask_claude(SCENARIO_SYSTEM, text, SCENARIO_SCHEMA)
            engine = f"Claude ({MODEL})"
        except RuntimeError as e:
            fallback_reason = str(e)
    if raw is None:
        raw = _offline_scenario(text)
    spec, warnings = sanitize_spec(raw)
    total = sum(p["rate"] for p in spec["processes"])
    burst_load = sum(b["size"] * 1000.0 / b["every_ms"] for b in spec["bursts"])
    return {"engine": engine, "fallback_reason": fallback_reason, "spec": spec, "warnings": warnings,
            "load": {"steady_rate": round(total, 1), "burst_rate": round(burst_load, 1)}}


# ---------------------------------------------------------------------------
# 2. Explain a decision
# ---------------------------------------------------------------------------
EXPLAIN_SYSTEM = f"""You explain one decision of a disk-scheduling algorithm to an operating-systems
student who is presenting the project to their professor.

{DISK_MODEL_FACTS}

You get the decision as JSON: the time, where the arm was, which request it chose, the scheduler's
own internal note, and a snapshot of the waiting queue. Write 3-5 plain sentences (under 110 words):
which rule fired, the concrete numbers that made it fire, and what plain SCAN would have done
instead and why that would be worse. No headings, no bullet points, no markdown."""


def _offline_explain(ctx):
    note = ctx.get("note", "")
    c = ctx.get("chosen", {})
    s = ctx.get("settings", {})
    k, deadline, aging = s.get("k", config.BURST_THRESHOLD_K), s.get("deadline", config.HIGH_DEADLINE), \
        s.get("aging", config.AGING_LIMIT)
    t, head = ctx.get("time", 0), ctx.get("head", "?")
    parts = []
    if "PRIORITY GUARD" in note:
        turned = "turn around" in note
        parts.append(
            f"At t = {t:.1f} ms the arm was at cylinder {head}. Rule 1 (priority guard) checked whether serving the "
            f"next request in sweep order would still let every HIGH request start within its {deadline:g} ms deadline. "
            f"It would not: the HIGH request at cylinder {c.get('track')} from {c.get('process', 'a HIGH process')} "
            f"had already waited {c.get('waited', 0):.1f} ms, so the elevator was overridden and the arm went straight "
            f"there{' and reversed direction' if turned else ''}. "
            f"Plain SCAN would have kept sweeping and only reached it on a later pass, missing the deadline.")
    if "deferred" in note:
        n = re.search(r"(\d+) request", note)
        parts.append(
            f"Rule 2 (burst-throttling) passed over {n.group(1) if n else 'some'} request(s) directly ahead, because "
            f"their process had already used its quota for this sweep ({k} per sweep for LOW, {2 * k} for MEDIUM). "
            f"The arm served cylinder {c.get('track')} ({c.get('process', '?')}) instead, so one bursty process "
            f"cannot hold the head in its region. The skipped requests are not lost: they are served on a later sweep, "
            f"or as soon as they have waited {aging:g} ms (Rule 3, aging). SCAN would have served the whole burst first.")
    if not parts:
        parts.append(f"At t = {t:.1f} ms the arm simply continued its sweep and took the nearest request ahead "
                     f"(cylinder {c.get('track')}). No PA-SCAN-BT rule needed to step in.")
    return " ".join(parts)


def explain(ctx, use_llm=True):
    """Entry point for POST /api/copilot/explain."""
    if use_llm:
        try:
            text = _ask_claude(EXPLAIN_SYSTEM, json.dumps(ctx, indent=1), max_tokens=4000)
            return {"engine": f"Claude ({MODEL})", "fallback_reason": None, "text": text}
        except RuntimeError as e:
            return {"engine": "offline rule templates", "fallback_reason": str(e), "text": _offline_explain(ctx)}
    return {"engine": "offline rule templates", "fallback_reason": None, "text": _offline_explain(ctx)}


# ---------------------------------------------------------------------------
# 3. Verified auto-tuner
# ---------------------------------------------------------------------------
TUNE_SEEDS = [101, 102, 103]        # the tuner may look at these
HOLDOUT_SEEDS = [201, 202, 203]     # nobody tunes on these: they decide what is accepted
K_GRID = [1, 2, 3, 4, 6, 8, 12]
DEADLINE_GRID = [20, 30, 40, 60, 80]
HIGH_SLO_MS = 50.0

OBJECTIVES = {
    "protect":  "Protect HIGH: lowest HIGH-priority p99 wait (average wait only breaks ties)",
    "balanced": "Balanced: lowest HIGH p99 wait, but average wait may be at most 10% above LOOK's",
    "efficient": f"Efficient: lowest average wait, as long as HIGH p99 wait stays under {HIGH_SLO_MS:g} ms",
}


def _score(objective, m, look):
    """Lower is better. `look` = LOOK's metrics on the same seeds (the efficiency reference)."""
    if objective == "protect":
        return m["p99_HIGH"] + 0.05 * m["avg_wait"]
    if objective == "balanced":
        over = max(0.0, 100.0 * (m["avg_wait"] / look["avg_wait"] - 1.0) - 10.0)     # % above the +10% budget
        return m["p99_HIGH"] + 5.0 * over
    return m["avg_wait"] + 5.0 * max(0.0, m["p99_HIGH"] - HIGH_SLO_MS)


def _requests(workload, seed):
    if workload.get("spec"):
        return workloads.generate_custom(workload["spec"], seed, config.DURATION_MS)
    scenario = workload.get("scenario", "mixed")
    if scenario not in workloads.SCENARIOS:
        raise LabError(f"unknown scenario '{scenario}'")
    return workloads.generate(scenario, seed)


def _measure(make, workload, seeds):
    return metrics.average([metrics.compute(simulate(make(), _requests(workload, s))) for s in seeds])


def _pa(k, deadline, aging):
    return lambda: PriorityThrottledSCAN(burst_threshold=k, high_deadline=deadline, aging_limit=aging)


TUNE_SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "k": {"type": "integer"},
                    "deadline_ms": {"type": "number"},
                    "aging_ms": {"type": "number"},
                    "reasoning": {"type": "string"},
                },
                "required": ["k", "deadline_ms", "aging_ms", "reasoning"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["candidates"],
    "additionalProperties": False,
}
TUNE_SYSTEM = f"""You tune the PA-SCAN-BT disk scheduler for a given workload and objective.

{DISK_MODEL_FACTS}

Knobs: K (burst threshold, integer 1-20), the HIGH deadline in ms (10-200; a tighter deadline makes the
guard fire earlier and more often, costing extra arm movement), and the aging limit in ms (50-1000; lower
means throttled requests are rescued sooner). Known behaviour: small K protects normal processes from
bursty ones but hurts the bursty process; a deadline much shorter than one full sweep (20 ms) makes the
guard reverse the arm too often.

Propose exactly 3 distinct candidate settings that you expect to score best on the objective, each with
one or two sentences of reasoning based on the measurements you are given. Your candidates will be
re-measured on unseen random workloads, and rejected if they do not beat the default settings."""


def _workload_label(workload):
    if workload.get("spec"):
        s = workload["spec"]
        procs = "; ".join(f"{p['name']} {config.PRIORITY_NAMES[p['priority']]} {p['rate']} req/s cyl "
                          f"{p['region'][0]}-{p['region'][1]}" for p in s["processes"])
        bursts = "; ".join(f"{b['name']} {b['size']} {config.PRIORITY_NAMES[b['priority']]} requests every "
                           f"{b['every_ms']} ms into cyl {b['region'][0]}-{b['region'][1]}" for b in s["bursts"])
        return f"{s.get('title', 'custom')}. Processes: {procs}. Bursts: {bursts or 'none'}."
    sc = workload.get("scenario", "mixed")
    return f"built-in scenario '{sc}': {workloads.SCENARIOS[sc][2]}"


KEYS = ("wait_HIGH", "p99_HIGH", "avg_wait", "p99_wait", "max_wait", "wait_LOW", "total_head_movement")


def _brief(m):
    return {k: round(m[k], 1) for k in KEYS}


def tune(workload, objective="balanced", use_llm=True):
    """Entry point for POST /api/copilot/tune."""
    if objective not in OBJECTIVES:
        raise LabError(f"unknown objective '{objective}'")
    t0 = time.time()
    sims = 0

    # Reference points on the tuning seeds
    look = _measure(LOOK, workload, TUNE_SEEDS)
    scan = _measure(SCAN, workload, TUNE_SEEDS)
    default_cfg = (config.BURST_THRESHOLD_K, config.HIGH_DEADLINE, config.AGING_LIMIT)
    default = _measure(_pa(*default_cfg), workload, TUNE_SEEDS)
    sims += 3 * len(TUNE_SEEDS)

    # Classical baseline tuner: exhaustive grid search on the tuning seeds
    best_grid, best_grid_score = None, float("inf")
    for k in K_GRID:
        for d in DEADLINE_GRID:
            s = _score(objective, _measure(_pa(k, d, config.AGING_LIMIT), workload, TUNE_SEEDS), look)
            sims += len(TUNE_SEEDS)
            if s < best_grid_score:
                best_grid, best_grid_score = (k, float(d), config.AGING_LIMIT), s

    candidates = [{"source": "default settings", "cfg": default_cfg, "reasoning": "the values in config.py"},
                  {"source": f"grid search ({len(K_GRID) * len(DEADLINE_GRID)} settings)", "cfg": best_grid,
                   "reasoning": "best of the exhaustive K x deadline grid on the tuning seeds"}]

    engine, fallback_reason = "offline (grid search only)", None
    if use_llm:
        prompt = json.dumps({
            "workload": _workload_label(workload),
            "objective": OBJECTIVES[objective],
            "measurements_on_tuning_workloads_ms": {
                "SCAN": _brief(scan), "LOOK": _brief(look),
                f"PA-SCAN-BT default (K={default_cfg[0]}, deadline={default_cfg[1]:g}, aging={default_cfg[2]:g})":
                    _brief(default),
            },
        }, indent=1)
        try:
            proposal = _ask_claude(TUNE_SYSTEM, prompt, TUNE_SCHEMA)
            engine = f"Claude ({MODEL}) + simulator verification"
            for i, c in enumerate(proposal.get("candidates", [])[:3]):
                cfg = (_clamp(int(c.get("k", 4)), 1, 20),
                       float(_clamp(float(c.get("deadline_ms", 40)), 10.0, 200.0)),
                       float(_clamp(float(c.get("aging_ms", 150)), 50.0, 1000.0)))
                candidates.append({"source": f"Claude idea #{i + 1}", "cfg": cfg,
                                   "reasoning": str(c.get("reasoning", ""))[:400]})
        except RuntimeError as e:
            fallback_reason = str(e)

    # Verification: every candidate is scored on the tuning seeds AND on held-out seeds
    look_hold = _measure(LOOK, workload, HOLDOUT_SEEDS)
    sims += len(HOLDOUT_SEEDS)
    rows = []
    for c in candidates:
        k, d, a = c["cfg"]
        m_tune = _measure(_pa(k, d, a), workload, TUNE_SEEDS)
        m_hold = _measure(_pa(k, d, a), workload, HOLDOUT_SEEDS)
        sims += len(TUNE_SEEDS) + len(HOLDOUT_SEEDS)
        rows.append({"source": c["source"], "k": k, "deadline": d, "aging": a, "reasoning": c["reasoning"],
                     "tune_score": round(_score(objective, m_tune, look), 2),
                     "holdout_score": round(_score(objective, m_hold, look_hold), 2),
                     "holdout": _brief(m_hold)})

    base = rows[0]["holdout_score"]
    for r in rows[1:]:
        gain = 100.0 * (base - r["holdout_score"]) / base if base else 0.0
        if r["holdout_score"] < base:
            r["verdict"] = f"accepted: {gain:.0f}% better than default on unseen workloads"
        else:
            r["verdict"] = f"rejected: {-gain:.0f}% worse than default on unseen workloads"
    rows[0]["verdict"] = "reference"
    best = min(range(len(rows)), key=lambda i: rows[i]["holdout_score"])

    return {
        "engine": engine,
        "fallback_reason": fallback_reason,
        "objective": OBJECTIVES[objective],
        "reference": {"SCAN": _brief(_measure(SCAN, workload, HOLDOUT_SEEDS)), "LOOK": _brief(look_hold)},
        "candidates": rows,
        "recommended": best,
        "simulations": sims + len(HOLDOUT_SEEDS),
        "seconds": round(time.time() - t0, 1),
        "seeds": {"tuning": TUNE_SEEDS, "held_out": HOLDOUT_SEEDS},
    }
