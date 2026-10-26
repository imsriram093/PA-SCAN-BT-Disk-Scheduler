# Project Status

*Snapshot taken 2026-10-24.* This file says what is finished, what the latest numbers are, and what is
still left to do. For an explanation of the algorithm itself, read [`PROJECT_GUIDE.md`](PROJECT_GUIDE.md).
For the demo script and likely questions, read [`PRESENTATION_GUIDE.md`](PRESENTATION_GUIDE.md).

## At a glance

| Part | State |
|---|---|
| Disk scheduler: baseline (`scheduler/baseline.py`) | ✅ Done: FCFS, SSTF, SCAN, C-SCAN, LOOK |
| Disk scheduler: enhanced (`scheduler/enhanced.py`) | ✅ Done: PA-SCAN-BT (priority guard, burst-throttling, aging) |
| Disk scheduler: comparison graphs (`scheduler/plots.py`) | ✅ Done: 7 figures + 3 CSV tables in `results/` |
| Extension: LLM serving scheduler (`llm_serving/`) | ✅ Done: PA-SWEEP-BT vs 4 policies, 6 figures + 3 CSVs in `results/llm/` |
| **Live lab / working model (`app.py`, `lab/`)** | ✅ New: Disk Lab + LLM Lab with live event injection, decision log |
| **AI co-pilot (`lab/copilot.py`)** | ✅ New: English → workload, decision explanations, verified auto-tuner; Claude or offline |
| Tests | ✅ 44 / 44 pass (14 disk + 12 LLM + 18 lab), about 2 s |
| Results up to date | ✅ The benchmark code paths did not change on 2026-10-24 (only additions), so `results/` is still current |
| README / presentation guide | ✅ Updated 2026-10-24 |
| Beginner guide (`PROJECT_GUIDE.md`) | ⚠️ Covers the disk project only; the LLM extension and the lab are covered in README + presentation guide |
| Version control / GitHub | ❌ The folder is not a git repository yet |
| Report | ⏳ Not in the repo (structure suggested in `PRESENTATION_GUIDE.md` section 8) |

## How to check it yourself

```bash
pip install -r requirements.txt
python -m unittest discover tests -v      # expect: Ran 44 tests ... OK
python app.py                             # the live lab at http://127.0.0.1:8050
python main.py                            # disk benchmark, ~10 s, rewrites results/
python llm_main.py                        # LLM benchmark, rewrites results/llm/
python main.py --demo                     # 14-request walkthrough in the terminal
python llm_main.py --demo                 # 10-request walkthrough on a 4-slot server
```

Checked on Python 3.11 (Windows 11). The lab has been checked in Microsoft Edge (headless screenshots of all
three main tabs).

## What changed on 2026-10-24

* **`app.py` + `lab/`**: an interactive working model. It runs the same simulators as the benchmarks, through a
  standard-library web server on 127.0.0.1. Events injected while it runs (backup burst, page faults, LLM flood,
  chat users) are re-simulated; decisions before the injection time provably do not change (`tests/test_lab.py`).
* **`lab/copilot.py`**: the AI co-pilot. It uses `claude-opus-5-5` when the `anthropic` package and credentials
  are present, and falls back to offline engines otherwise. LLM output is sanitised (ranges, total load ≤ 220 req/s,
  bursts ≤ 120 req/s, a HIGH process is always present). Tuning ideas are accepted only if they beat the default
  settings on held-out seeds.
* `scheduler/workloads.py`: added `generate_custom()` (custom process mixes); `_bursts()` takes a pid and a priority
  (the defaults keep the old behaviour, so the benchmark numbers are unchanged).
* `llm_serving/simulator.py`: the trace now records each step's start time and cache hits (used by the lab to
  redraw the GPU batch). Nothing else changed.

## Latest results

### Disk: PA-SCAN-BT vs SCAN (10 seeds, `results/summary_*.csv`)

| Metric | MIXED | BURST | HEAVY |
|---|---|---|---|
| HIGH avg wait (ms) | 34.6 → 23.7 (−32%) | 84.3 → 30.8 (−63%) | 41.5 → 28.1 (−32%) |
| HIGH p99 wait (ms) | 97.8 → 43.8 (−55%) | 265.5 → 48.6 (−82%) | 121.7 → 47.9 (−61%) |
| Non-bursty processes, avg wait (ms) | n/a | 81.2 → 66.8 (−18%) | n/a |
| All requests, p99 wait (ms) | 103.7 → 141.5 (+36%) | 270.2 → 399.4 (+48%) | 129.9 → 203.4 (+57%) |
| Total head movement | −4% | +1% | −1% |

### LLM serving: PA-SWEEP-BT vs PREFIX-SWEEP (5 seeds, `results/llm/summary_*.csv`)

| Metric | FLOOD | HEAVY |
|---|---|---|
| INTERACTIVE avg TTFT (ms) | 1230 → 161 (−87%) | 134 → 79 (−41%) |
| INTERACTIVE p99 TTFT (ms) | 4657 → 309 (−93%) | 1031 → 270 (−74%) |
| INTERACTIVE within 300 ms SLO | 43.9% → 97.8% | 88.2% → 99.5% |
| Non-flooding tenants, avg TTFT (ms) | 1125 → 608 (−46%) | n/a |
| Flooding tenant, avg TTFT (ms) | 828 → 1173 (+42%) | n/a |
| STANDARD p99 TTFT (ms) | 3819 → 2972 (−22%) | 668 → 995 (+49%) |
| Prefix-cache hit rate | 65.9% → 68.9% | 55.4% → 57.2% |
| Preemptions per run | 0 → 15.8 | 0 → 10 |

### Overload experiment (2026-10-24, not in `results/`)

Four variants of the priority guard were tried at 180–220 req/s (feasibility-only rescue, load-gated rescue,
reversal-free rescue, serving requests on the way). None removes the trade-off; the table and the explanation
are in `PRESENTATION_GUIDE.md` section 7. PA-SCAN-BT is unchanged.

## Open items

1. **The LLM `mixed` scenario does not separate the policies.** At 8 req/s nothing ever queues, so all five
   policies give the same numbers. Present it as "light load: every policy is equivalent", or raise its rate.
2. **`PROJECT_GUIDE.md`** could get a short section on the LLM extension and the lab (the README and the
   presentation guide cover both already).
3. **Put the project under git and on GitHub.** `.gitignore` already excludes `venv/` and `__pycache__/`.
4. **Write the report** (structure in `PRESENTATION_GUIDE.md` section 8).
5. **Rehearse the demo** with `PRESENTATION_GUIDE.md` section 3 (about 10 minutes).

## Known limitations

* **Disk:** under overload (load above about 200 req/s), the guard's extra seeks increase the average wait
  sharply. HIGH stays protected, but everyone else pays (see the overload experiment above).
* **LLM:** the server model is deliberately simple. There is no chunked prefill, and each request reserves KV
  memory for its full output when it is admitted.
* **Co-pilot:** Claude's explanations are generated text. The scheduler's own decision note is shown next to it,
  and nothing the co-pilot says changes a scheduling decision.
