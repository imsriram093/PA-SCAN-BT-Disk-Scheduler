# Presentation Guide: how to demo and explain this project

This is your script for showing the project to your faculty. It covers what to say, in which order, what to
click, which numbers to quote, what is genuinely new, and how to answer the hard questions.

---

## 0. Before you walk in (5 minutes)

```bash
pip install -r requirements.txt
python -m unittest discover tests -v     # expect: Ran 44 tests ... OK
python app.py                             # browser opens at http://127.0.0.1:8050
```

* **No internet is needed.** Without an API key the badge in the top-right says *offline engine* and every
  co-pilot feature still works. If you do want Claude live: `pip install anthropic`, set `ANTHROPIC_API_KEY`,
  restart `app.py`, and check that the badge shows the model name.
* Have `results/fig2_wait_by_priority.png` and `results/fig6_ablation.png` open in another window as a backup.
* Bookmarks that jump straight to a moment of the simulation (useful if you are short of time):
  * `http://127.0.0.1:8050/?tab=disk&scenario=demo&t=95`: the 14-request demo, finished
  * `http://127.0.0.1:8050/?tab=disk&scenario=burst&inject=burst@1500&t=1620`: a burst just injected
  * `http://127.0.0.1:8050/?tab=llm&scenario=flood&t=2600`: an LLM flood in progress

---

## 1. The one-sentence pitch

> "SCAN, the elevator algorithm, is efficient but blind: it serves a page fault and a backup job the same way.
> We built **PA-SCAN-BT**, an elevator with three small rules that gives critical I/O a latency bound and stops
> one bursty process from hogging the disk arm. We showed the same idea works for **scheduling an LLM server**,
> and we built a **live lab with an AI co-pilot** whose suggestions are verified by the simulator before they are trusted."

---

## 2. Explaining it simply (the lift analogy)

Use this if the faculty wants intuition before the details.

* **SCAN = a lift** that goes up serving every floor where someone pressed the button, then comes down.
  It moves very little, but everybody is equal.
* **Problem 1, the ambulance (Rule 1, priority guard):** a doctor waiting on floor 3 while the lift goes up to 20.
  Our lift asks before every stop: *"if I make this stop, will the doctor wait too long?"* If yes, it goes to the
  doctor first. If not, it keeps going normally, so it only breaks the elevator order when it has to.
* **Problem 2, the person who pressed every button (Rule 2, burst-throttling):** one passenger presses 40 buttons
  on floors 6–9 and the lift stops 40 times while everyone else waits. Our lift serves at most **K** of one
  person's stops per trip (2K for MEDIUM people). The rest wait for the next trip.
* **Problem 3, never forget anyone (Rule 3, aging):** once a request has waited 150 ms, it can no longer be
  skipped. Nobody starves.
* With all three rules switched off, the algorithm is exactly **LOOK**. That is how we measure what each rule
  contributes (ablation, Figure 6).

---

## 3. The 10-minute live demo (click by click)

| # | Do this | Say this |
|---|---|---|
| 1 | **Disk Lab**, scenario **Demo: 14 requests**, speed **0.02×**, ▶ Play | "Same 14 requests as the textbook-style demo. The head starts at 50, moving up. Red dots are HIGH (page faults), purple is a backup burst at 55–76." |
| 2 | Point at the **red bar** at cylinder 35 in the SCAN lane | "SCAN goes all the way to 199 before it comes back. This page fault waits 79 ms, double its 40 ms deadline. The bar turns red at the deadline." |
| 3 | Point at the PA-SCAN-BT lane and the **decision log** | "Our algorithm turns back for it in time: *HIGH late 0/2*. The log says why: GUARD and THROTTLE. Watch it skip the burst after K = 3 requests." |
| 4 | Click a **GUARD** line in the decision log | "The co-pilot explains any decision in plain English, with the actual numbers." |
| 5 | Scenario **Burst**, speed 0.1×, ▶ Play. Mid-run press **💥 Backup burst** twice | "Now I inject a backup burst live. Watch the queue above the platter fill with purple, and SCAN's red bars grow while it serves the whole burst." |
| 6 | Press **⚡ Page faults** | "Three page faults arrive. PA-SCAN-BT jumps to them; SCAN makes them wait for its sweep." |
| 7 | Point at the **Live scoreboard** | "Green is best. HIGH wait and normal processes are better for us. LOW and the bursty process pay for it. That is deliberate, and we show it rather than hide it." |
| 8 | **LLM Serving Lab**, scenario **Flood**, ▶ Play, press **💬 Chat users** during a flood | "Same three rules on a GPU serving an LLM. Cylinder becomes prompt prefix, seek becomes cache miss, waiting time becomes time-to-first-token. Under a flood, chat users still get their first token fast." |
| 9 | **AI Co-pilot**: click an example → **Generate** → **Run it in the Disk Lab** | "You can describe a workload in English. The LLM writes the workload, and our code clamps every number to a safe range before the simulator sees it." |
| 10 | Back to the co-pilot → **Tune** | "Claude proposes settings and a grid search competes with it. Every candidate is re-tested on random workloads nobody tuned on. Look at the verdict column: accepted *or rejected*. The LLM never gets the last word. The simulator does." |

If time is short, do steps 1–3, 5 and 10.

---

## 4. What is novel (say it precisely, not inflated)

Be honest about what is prior art. It makes the novelty more believable.

| Idea | Prior art (cite it) | What we did that is new |
|---|---|---|
| Deadline jump inside an elevator | SCAN-EDF (Reddy & Wyllie, 1993); Linux *deadline* I/O scheduler | Our guard is **predictive**: it checks "would *the next* sweep step make a HIGH request late?" and only then breaks the sweep. It does not wait for the deadline to expire. |
| Per-process fairness | BFQ (Valente & Checconi, 2010) uses per-process budgets | **Priority-scaled per-sweep quotas** (K for LOW, 2K for MEDIUM, unlimited for HIGH), reset at every turn-around, plus **aging** that lifts the quota. This targets the specific head-hogging-by-burst problem. |
| The combination | n/a | Three rules on one elevator, each switchable, so that **with all rules off it is exactly LOOK**. That gives a clean ablation of each rule's contribution (Figure 6). |
| Cross-domain transfer | vLLM, SGLang (prefix-cache-aware scheduling), VTC fairness (OSDI 2024) | Mapping the disk problem onto **LLM serving**: prefix id = cylinder, cache miss = seek, preemption = arm reversal. We then showed the same rules cut INTERACTIVE p99 TTFT by **93%** under a flood. |
| Working model | Textbook simulators show static charts | A **live lab with event injection**, proven not to rewrite history (an injected event cannot change earlier decisions; tested). |
| LLM *for* the OS | LLM-based auto-tuning is an active research area | A **verified LLM co-pilot**. The LLM proposes, the simulator decides on **held-out** workloads, and every LLM output is clamped by a sanitizer. It also has offline fallbacks, so the system never depends on the LLM. |

**The two-directional story is the creative hook:** *scheduling for LLMs* (llm_serving/) and *LLMs for scheduling*
(the co-pilot), built on the same algorithm.

---

## 5. Numbers to quote (from `results/`, mean of 10 seeds)

* HIGH-priority **p99 wait**: SCAN 98–266 ms → PA-SCAN-BT **44–49 ms** in every scenario (−55% to −82%).
* BURST scenario: HIGH average wait **84 → 31 ms (−63%)**; normal (non-bursty) processes **81 → 67 ms (−18%)**.
* Total head movement: within ±4% of SCAN. The rules cost almost no efficiency.
* The price: all-requests p99 rises 36–57%, paid by LOW-priority work and the bursty process.
* LLM, FLOOD: INTERACTIVE p99 TTFT **4657 → 309 ms**; within the 300 ms SLO **44% → 98%**.

---

## 6. Questions you will probably get

**Q: Isn't this just the Linux deadline scheduler?**
No. Deadline serves expired requests first, *after* they are already late. Our guard predicts lateness one
step ahead, and we add per-sweep, priority-scaled quotas against bursts, which deadline does not have.
Figure 6 (ablation) shows why both are needed: in the burst scenario the guard alone protects HIGH requests
but leaves normal processes at 74.7 ms average wait; with throttling added it drops to 66.8 ms.

**Q: Who pays for the improvement?**
LOW-priority work and the bursty process, mostly in the tail (scoreboard rows in red, all-requests p99 +36–57%).
That is the intended trade: a page fault blocks a CPU, a backup does not.

**Q: Can throttling starve a process?**
No. Rule 3 (aging): after 150 ms a request can no longer be deferred. Also, throttling never leaves the disk idle:
if only throttled requests are ahead, the nearest one is served anyway.

**Q: What happens when the disk is overloaded?**
This is our known limitation, and we tested it (section 7). Above ~200 req/s every algorithm's queue grows without
bound. PA-SCAN-BT keeps HIGH latency low, but its extra seeks are paid for with a much larger average wait.

**Q: Why should we trust an LLM inside an OS?**
We don't, and that is the point of the design. The co-pilot sits *outside* the scheduling path: it suggests,
it never decides. Its workloads are clamped to safe ranges, and its tuning ideas must beat the defaults on
random workloads it never saw (held-out seeds 201–203). The co-pilot output often contains rejected ideas,
and the system shows them as rejected. It also works fully offline.

**Q: Is the live demo the real algorithm or an animation?**
The browser only draws. Every decision comes from the same Python classes as `main.py` (`lab/disk_api.py` calls
`scheduler.simulator.simulate`). The "demo" scenario reproduces `python main.py --demo` exactly; a test checks it.

**Q: How do you know the baseline implementations are correct?**
`tests/test_scheduler.py` reproduces the textbook head-movement answers (FCFS 640, SSTF 236, SCAN 236, C-SCAN 382,
LOOK 299 cylinders for the Silberschatz example).

**Q: Why K = 4 and a 40 ms deadline?**
Figure 7 (sensitivity) sweeps both. The co-pilot's tuner shows that the best setting depends on the workload
and on what you want to optimise. For example, on the burst workload with a "balanced" goal, K = 12 with an
80 ms deadline wins on unseen workloads.

**Q: Is the simulation realistic?**
It uses typical 7200 RPM figures (0.1 ms per cylinder, 4 ms service). The simplifications are listed in the
README: a fixed service time, a non-preemptive seek, and Poisson arrivals. The comparison is fair because every
algorithm gets identical request lists, averaged over 10 seeds.

---

## 7. Honest limitation, with evidence (overload)

We tried to fix the overload weakness and documented why it cannot be fixed for free. Mixed workload at
**220 req/s** (the disk's capacity is about 200 req/s), mean of 10 seeds:

| Variant | HIGH avg | HIGH p99 | All avg | Max wait | Arm movement |
|---|---|---|---|---|---|
| SCAN | 107 | 307 | 107 | 403 | 6,099 |
| LOOK | 101 | 291 | 103 | 394 | 6,059 |
| **PA-SCAN-BT** | **36** | **59** | 331 | 2,367 | 9,620 |
| guard only rescues requests that can still make it | 99 | 379 | 179 | 1,082 | 7,129 |
| that, but only while the backlog is long | 98 | 391 | 188 | 1,159 | 7,233 |
| serve requests on the way to the urgent one | 37 | 59 | 334 | 2,472 | 9,671 |

**Conclusion to say out loud:** every rescue is an extra seek. Under overload, lost disk time compounds into
an ever-growing queue. You can keep HIGH latency low (PA-SCAN-BT) *or* keep the average low (LOOK), but not
both, because the disk simply has no spare capacity. A real system would need admission control (refusing or
delaying work) on top of any scheduler. This is the right "future work" answer.

---

## 8. Suggested report / slide structure

1. Problem: SCAN treats a page fault and a backup the same (show Figure 1).
2. Algorithm: three rules + pseudocode of `select()` from `scheduler/enhanced.py`.
3. Correctness: textbook tests (44 automatic tests in total).
4. Results: Figures 2, 3, 4; the trade-off (who pays).
5. Why each rule matters: ablation (Figure 6); tuning knobs (Figure 7).
6. Generalisation: the same rules on an LLM server (mapping table + LLM Figures 1–3).
7. Working model: live lab screenshots; event injection; the verified AI co-pilot.
8. Limitations: overload (section 7 above), simplified hardware and server models.
9. References (README).
