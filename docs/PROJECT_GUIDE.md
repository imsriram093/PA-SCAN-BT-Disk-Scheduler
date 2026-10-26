# Project Guide: Priority-Aware SCAN with Burst-Throttling

This guide assumes you know nothing about disk scheduling. Read it top to bottom once and you will
understand every line of the project, be able to run it, and be ready for the viva.

**Contents**

1. [The project in one minute](#1-the-project-in-one-minute)
2. [Background: how a hard disk works](#2-background-how-a-hard-disk-works)
3. [The classic algorithms (with the textbook example)](#3-the-classic-algorithms)
4. [The two problems with SCAN](#4-the-two-problems-with-scan)
5. [Our algorithm: PA-SCAN-BT](#5-our-algorithm-pa-scan-bt)
6. [The demo, step by step](#6-the-demo-step-by-step)
7. [How the experiment works](#7-how-the-experiment-works)
8. [Walking through the code](#8-walking-through-the-code)
9. [Reading the results](#9-reading-the-results)
10. [One file or many files?](#10-one-file-or-many-files)
11. [What to do, in order (your checklist)](#11-what-to-do-in-order)
12. [Viva questions and answers](#12-viva-questions-and-answers)
13. [Writing the report](#13-writing-the-report)
14. [Experiments you can try](#14-experiments-you-can-try)
15. [Glossary](#15-glossary)

---

## 1. The project in one minute

The faculty asked for three things:

1. **A baseline algorithm.** We use **SCAN**, the "elevator" disk-scheduling algorithm from the textbook.
2. **An enhanced variant.** We built **PA-SCAN-BT**: SCAN plus three rules (priority guard, burst-throttling, aging).
3. **Comparison graphs.** The program runs both on identical workloads and draws 7 graphs.

We do **not** modify a real operating system. We write a **simulator**: a Python program that pretends to be a
disk, feeds it thousands of fake requests, and measures how long each one waits. This is the standard way
scheduling algorithms are studied, and it is what the problem statement expects.

**Headline result:** HIGH-priority requests wait 32–63% less on average, and their worst-case (99th
percentile) wait drops from 98–266 ms to about 45 ms. Normal processes wait 18% less during bursts.
In exchange, low-priority work and the bursty process wait longer.

---

## 2. Background: how a hard disk works

```
         spindle (spins at 7200 RPM)
             │
     ┌───────┼───────┐        A platter is divided into concentric rings called TRACKS.
     │  ┌────┼────┐  │        The same track on every platter forms a CYLINDER.
     │  │  ┌─┼─┐  │  │        Cylinders are numbered 0 (outer edge) ... 199 (inner edge) in our model.
     │  │  │ ● │  │  │
     │  │  └───┘  │  │        The READ/WRITE HEAD sits on an ARM that swings in and out
     │  └─────────┘  │        to reach the cylinder it needs.
     └───────────────┘
            ▲
            └── arm + head
```

Reading one piece of data takes three steps:

| Step | Name | In our simulation |
|---|---|---|
| Move the arm to the right cylinder | **Seek time** | 0.1 ms per cylinder moved (a full sweep 0→199 is about 20 ms) |
| Wait for the data to spin under the head | **Rotational latency** | included in a fixed 4 ms. At 7200 RPM one turn is 8.33 ms, so on average you wait half a turn, about 4.17 ms |
| Actually read or write it | **Transfer time** | included in the same 4 ms |

Seek time is the only part the operating system can reduce, and it does that by **choosing the order**
in which waiting requests are served. Many processes send requests at the same time, they pile up in a
queue, and the **disk scheduler** decides which one goes next. That decision is what this project is about.

---

## 3. The classic algorithms

The textbook example (Silberschatz, *Operating System Concepts*) uses a queue of requests for cylinders
**98, 183, 37, 122, 14, 124, 65, 67**, with the head at **53**. "Head movement" is the total number of
cylinders the arm travels. Lower is better. Our test file checks that the code reproduces every number below.

| Algorithm | Rule | Service order | Head movement |
|---|---|---|---|
| **FCFS** | First come, first served | 98, 183, 37, 122, 14, 124, 65, 67 | **640** |
| **SSTF** | Always go to the closest request | 65, 67, 37, 14, 98, 122, 124, 183 | **236** |
| **SCAN** (moving toward 0) | Sweep to one end, serving everything on the way, then sweep back | 37, 14, *(edge 0)*, 65, 67, 98, 122, 124, 183 | **236** |
| **C-SCAN** (moving up) | Sweep up only. At the top, jump back to 0 and sweep up again | 65, 67, 98, 122, 124, 183, *(199→0)*, 14, 37 | **382** (we count the jump back) |
| **LOOK** (moving up) | Like SCAN, but turn at the last request instead of the edge | 65, 67, 98, 122, 124, 183, 37, 14 | **299** |

```
SCAN with the head at 53 moving toward 0:

  0    14      37     53      65 67           98          122 124                  183     199
  |----●-------●------▲-------●--●------------●-----------●---●--------------------●-------|
  ◄────────────────── start
  └── touch the edge, turn around ──────────────────────────────────────────────────►
```

Why it matters:

* **FCFS** is fair but makes the arm zig-zag all over the disk.
* **SSTF** is efficient but unfair. A request far from the "busy" area can wait forever (**starvation**).
* **SCAN** is the classic compromise. Like a lift in a building, it never goes back and forth, so every
  request is reached within about two sweeps. This is our **baseline**.
* **C-SCAN** and **LOOK** are well-known refinements, included as extra reference points.

---

## 4. The two problems with SCAN

SCAN treats every request the same. Two things go wrong in a real system.

**Problem 1: no priority awareness.** When your program touches memory that was swapped out (a
**page fault**), it freezes until the disk reads that page. That read is critical. A background
antivirus scan can wait. SCAN doesn't know the difference. If the page-fault request is *behind* the head,
it waits for the arm to finish the whole sweep and come back. In our burst experiment, the average HIGH
request under SCAN waited 84 ms, and the worst 1% waited more than 265 ms.

**Problem 2: burst hostage.** A backup program suddenly asks for 40 blocks, all close together
(cylinders 60–90). When SCAN's sweep reaches that area it serves all 40 in a row: 40 × 4 ms = 160 ms
during which everything else waits. One greedy process has taken the disk hostage. Figure 1 shows this
clearly: the orange SCAN line crawls through the shaded band for a long time.

---

## 5. Our algorithm: PA-SCAN-BT

PA-SCAN-BT is still an elevator. Before every move it applies three rules.

### Rule 1: Priority guard (a deadline for HIGH requests)

Every HIGH request should start within `HIGH_DEADLINE` = 40 ms of arriving. Before taking the next
normal elevator step, the scheduler asks:

> "If I serve the next request in sweep order first, will any HIGH request miss its deadline?"

* **No:** continue the normal sweep. Efficiency is preserved.
* **Yes:** override the elevator and go straight to the most urgent HIGH request, turning around if it
  is behind.

This is "just in time" priority: the arm only breaks its sweep when it has to. The idea comes from
real systems: **SCAN-EDF** (Reddy & Wyllie, 1993) and Linux's **deadline I/O scheduler** both keep
elevator order until a deadline is about to be missed.

### Rule 2: Burst-throttling (a quota per sweep)

During one sweep (one pass in one direction), each process may have at most:

| Process priority | Quota per sweep |
|---|---|
| LOW | K requests (K = 4) |
| MEDIUM | 2 × K = 8 requests |
| HIGH | unlimited (never delay a page fault) |

Extra requests are **deferred**: the arm passes over them and serves them on a later sweep. Each time the
arm turns around, every quota resets. Two safety details:

* Throttling never makes the disk sit idle. If *only* deferred requests are ahead, the nearest one is
  served anyway.
* Throttling never makes the arm turn early. It only skips.

### Rule 3: Aging (no starvation)

Rule 2 delays a process on purpose, and without a limit it could delay it forever. So: **a request that
has waited longer than `AGING_LIMIT` = 150 ms can no longer be deferred.** In the ablation study,
turning aging off makes the backup process's worst wait jump from 470 ms to over 2,500 ms. That is
starvation, and Rule 3 is what prevents it.

### Turning around: LOOK-style

The enhanced algorithm turns at the last request instead of travelling to the disk edge for nothing,
like real "elevator" schedulers. With all three rules switched off, PA-SCAN-BT is exactly LOOK.
A test checks this.

### Pseudo-code (put this in your report)

```
function SELECT(queue, head, now):
    # Step A: normal elevator step, with throttling (Rules 2 and 3)
    ahead ← requests in the queue that lie in the current direction
    if ahead is empty:
        reverse direction; reset every process's quota          # a new sweep starts
        ahead ← requests in the queue that lie in the new direction
    allowed ← requests in ahead that are NOT deferred
    plan ← nearest request in (allowed, or ahead if allowed is empty)

    # Step B: priority guard (Rule 1)
    for each HIGH request h in the queue, h ≠ plan:
        reach ← finish time of plan + travel time from plan to h
        if reach > h.arrival_time + HIGH_DEADLINE:  mark h "at risk"
    if any request is at risk:
        plan ← the at-risk request with the earliest deadline
        if plan is behind the head: reverse direction; reset quotas

    served_this_sweep[plan.process] += 1
    return plan

deferred(r)  = throttling is on
               AND r has waited ≤ AGING_LIMIT                    # Rule 3
               AND served_this_sweep[r.process] ≥ quota(r)       # Rule 2
quota(r)     = ∞ if HIGH,  2K if MEDIUM,  K if LOW
```

### Why not just "always serve HIGH first"?

That was the first design we tried. It is the obvious idea, but it backfired. Every time the arm skips
nearby requests to chase a HIGH one, those skipped requests need another visit. The elevator loses its
efficiency, the queue grows, and **everyone** waits longer. In our early experiments, a version that always
jumped to the highest-priority request roughly doubled the average waiting time under load. The deadline
guard (Rule 1) gets most of the benefit for HIGH requests while breaking the sweep far less often. This
is a good point to make in your viva: it shows you tested the design and didn't just guess.

---

## 6. The demo, step by step

Run `python main.py --demo`. Fourteen requests arrive at t = 0, the head is at 50 moving UP,
K = 3 and the deadline is 40 ms:

* **P7 backup (LOW):** a burst of 8 requests at cylinders 55, 58, 61, 64, 67, 70, 73, 76
* **P2 editor (MEDIUM):** 120, 160
* **P5 indexer (LOW):** 140, 10
* **P1 kernel (HIGH):** 100 (ahead, but past the burst) and 35 (behind the head)

**SCAN:** serves all 8 backup requests first (55→76), then 100, 120, 140, 160, travels to the edge (199),
comes back to 35, then 10.
→ HIGH request at 100 waited **37.0 ms**, HIGH request at 35 waited **79.3 ms**. Head movement 338.

**PA-SCAN-BT:**

| # | Cylinder | Why |
|---|---|---|
| 1–3 | 55, 58, 61 | normal sweep, the backup process uses its quota of 3 |
| 4 | 100 (HIGH) | the other 5 backup requests are **deferred** (Rule 2), so the arm moves on |
| 5 | 120 | normal sweep. The guard checks that cylinder 35 can still be reached within 40 ms: yes |
| 6 | 35 (HIGH) | **priority guard**: serving 140 first would make cylinder 35 late, so the arm turns around now (Rule 1) |
| 7 | 10 | continue downward |
| 8–10 | 64, 67, 70 | new sweep, so new quota: the backup gets 3 more |
| 11–12 | 140, 160 | the remaining 2 backup requests are deferred again |
| 13–14 | 76, 73 | last sweep, finishing the backup |

→ HIGH requests waited **17.0 ms** and **35.5 ms** (both inside the 40 ms deadline). Head movement 417.

Notice the trade-off: the arm travelled more (417 vs 338 cylinders) and the backup job finished later.
That is the price of protecting the critical requests.

---

## 7. How the experiment works

### The simulator (`scheduler/simulator.py`)

```
time = 0, head = 100
repeat until every request is served:
    1. move every request with arrival_time ≤ time into the pending queue
    2. if the queue is empty → jump time forward to the next arrival (disk idle)
    3. ask the algorithm: select(pending, head, time) → which request next?
    4. seek: time += |cylinder − head| × 0.1 ms
    5. record start_time; time += 4 ms (read); record finish_time
```

Every algorithm runs inside the **same** simulator on the **same** list of requests. The only thing
that changes is the `select()` decision, so the comparison is fair.

### The workloads (`scheduler/workloads.py`)

Six imaginary background processes send requests at random times (a **Poisson process**: requests arrive
independently at a given average rate, the standard way to model this):

| Process | Priority | Share of traffic | Cylinders |
|---|---|---|---|
| P1 kernel-pager | HIGH | 10% | anywhere |
| P2 text-editor | MEDIUM | 15% | anywhere |
| P3 web-browser | MEDIUM | 15% | anywhere |
| P4 log-writer | LOW | 20% | 140–199 |
| P5 file-indexer | LOW | 20% | anywhere |
| P6 antivirus-scan | LOW | 20% | anywhere |
| P7 backup *(BURST scenario only)* | LOW | 40 requests in 2 ms, every 500 ms | 60–90 |

Three scenarios, 4 seconds of requests each:

* **MIXED:** 130 requests/s. A normal busy system.
* **BURST:** 100 requests/s plus the backup process. The "hostage" situation.
* **HEAVY:** 160 requests/s. Close to what the disk can handle.

Each scenario is generated with **10 different random seeds** and the results are averaged. A seed
makes "random" repeatable: seed 1 always produces exactly the same workload. That is why your numbers
will match ours exactly.

A useful fact for the viva: at these loads the arm is moving or reading 97–99% of the time. Reading alone
takes 53% (MIXED), 72% (BURST) and 62% (HEAVY). Seeking fills the rest. That is why the order of
service matters so much.

### The metrics (`scheduler/metrics.py`)

| Metric | Meaning | Better |
|---|---|---|
| Total head movement | cylinders the arm travelled in total | lower |
| Waiting time | `start_time − arrival_time`: queueing plus seeking to it | lower |
| Turnaround time | `finish_time − arrival_time` (= wait + 4 ms) | lower |
| Average wait per class | separate averages for HIGH, MEDIUM, LOW | lower |
| p99 wait | 99% of requests waited less than this; shows the **worst cases** | lower |
| Max wait | the single worst wait, a **starvation** indicator | lower |
| Throughput | requests completed per second | higher |
| Normal-process wait | average wait of everything except the bursty backup | lower |

Why p99 and not just the average? Averages hide unlucky requests. A system where 99 requests take 1 ms
and one takes 10 seconds has a fine average and a terrible user experience. Real systems are judged by
their tails.

---

## 8. Walking through the code

Read the files in this order. Each one is short and commented.

| # | File | What to look for |
|---|---|---|
| 1 | `config.py` | All the numbers. Change them here, never inside the code. |
| 2 | `scheduler/request.py` | The `Request` "ticket": `track`, `priority`, `arrival_time`, plus `start_time`/`finish_time` filled in later. `fresh_copy()` lets every algorithm receive identical, unserved input. |
| 3 | `scheduler/baseline.py` | The `Scheduler` parent class and the five classic algorithms. Each one is a few lines inside `select()`. Start with `SCAN`. |
| 4 | `scheduler/simulator.py` | `simulate()`: the loop from section 7. Note the `via` list: SCAN uses it to touch the disk edge before turning. |
| 5 | `scheduler/enhanced.py` | Our algorithm. `select()` calls `_elevator_choice()` (Rules 2+3), then `_high_request_at_risk()` (Rule 1). |
| 6 | `scheduler/workloads.py` | `generate(scenario, seed)` and `demo_workload()`. |
| 7 | `scheduler/metrics.py` | `compute()` turns one run into a dictionary of numbers. `average()` merges the 10 seeds. |
| 8 | `main.py` | `run_benchmark()`: the 7 experiments in order. `run_demo()`: the step-by-step example. |
| 9 | `scheduler/plots.py` | One function per figure. |
| 10 | `tests/test_scheduler.py` | 14 automatic checks, including the textbook numbers from section 3. |

How the pieces connect:

```
main.py
  ├─ workloads.generate("burst", seed) ──► list of Request
  ├─ simulate(SCAN(), requests)        ──► SimulationResult ─┐
  ├─ simulate(PA-SCAN-BT, requests)    ──► SimulationResult ─┤
  │                                                          ▼
  ├─ metrics.compute(result) ──► {"avg_wait": .., "wait_HIGH": .., ...}
  ├─ print tables + save results/summary_*.csv
  └─ plots.*(...) ──► results/fig*.png
```

The design idea that makes this clean: **every algorithm has the same interface**
(`reset()` and `select()`). The simulator doesn't know or care which algorithm it is running. In OOP
terms this is *polymorphism*, and it is exactly how real kernels plug in different I/O schedulers.

---

## 9. Reading the results

Run `python main.py`. The terminal prints a table per scenario and a "PA-SCAN-BT vs SCAN" summary.

| Metric (PA-SCAN-BT vs SCAN) | MIXED | BURST | HEAVY |
|---|---|---|---|
| HIGH-priority average wait | **−32%** | **−63%** | **−32%** |
| HIGH-priority p99 wait | **−55%** (98 → 44 ms) | **−82%** (266 → 49 ms) | **−61%** (122 → 48 ms) |
| Normal processes' average wait | n/a | **−18%** | n/a |
| All requests, average wait | −9% | +32% | +11% |
| All requests, p99 wait | +36% | +48% | +57% |
| Total head movement | −4% | +1% | −1% |

**How to explain these honestly** (examiners respect this more than "everything got better"):

* **What improved:** critical requests now have a predictable bound. Their worst case is about 45 ms in
  every scenario, where SCAN ranged from 98 to 266 ms. During bursts, the six normal processes wait
  less because the backup can't hog the disk.
* **What it cost:** a scheduler can't create disk time out of nothing. If some requests go first, others
  go later. Low-priority work and the bursty backup absorb the cost, mostly in their worst cases (p99).
  In BURST the overall average rises because the backup process sends about 45% of all requests, and it
  is deliberately slowed down.
* **Efficiency was kept:** total head movement stays within ±4% of SCAN, so the disk isn't wasting time.

What each figure says:

| Figure | Key message |
|---|---|
| **Fig 1** Arm trajectory | SCAN crawls through the burst region while HIGH requests (black lines) wait; PA-SCAN-BT breaks the burst into pieces and the black lines are short. |
| **Fig 2** Wait by priority | HIGH bars drop sharply in every scenario. The bottom row (p99) shows the cost moving to lower priorities. |
| **Fig 3** All algorithms | Where PA-SCAN-BT sits among the textbook algorithms. It has the lowest HIGH wait of all, and C-SCAN is the slowest of the SCAN family in this setup. |
| **Fig 4** Per process | Every process except the backup waits less or about the same. Throttling transfers the pain to the process that caused it. |
| **Fig 5** Load sweep | HIGH waits stay lowest at every load. Above about 120 requests/s the tail cost for everyone else grows quickly. That is the limit of the approach. |
| **Fig 6** Ablation | Rule 1 alone cuts HIGH waits; Rules 2+3 alone protect normal processes. Without aging, the worst wait reaches about 2.5 seconds: starvation. |
| **Fig 7** Sensitivity | (a) Small K protects others but slows the backup, and K = 4 is near the knee of the curve. (b) A tighter deadline helps HIGH but costs everyone; 40 ms is a middle setting. |

---

## 10. One file or many files?

Gemini told you one file is enough, and that's not wrong: a single 400-line script would satisfy the
three requirements. We split it into small files anyway because:

* each faculty requirement maps to **one file** (`baseline.py`, `enhanced.py`, `plots.py`), which makes it
  easy to show the examiner "here is component 1, here is component 2…";
* the tests can import the algorithms without running the whole benchmark;
* each file is short enough to explain in a viva.

Running it is still **one command**: `python main.py`. If your faculty insists on a single file, you can
paste the modules into one file in the order of section 8, and it will work the same.

---

## 11. What to do, in order

1. **Install Python** 3.8 or newer from python.org (on Windows, tick "Add Python to PATH").
2. **Unzip** the project folder and open it in VS Code (or any editor).
3. Open a terminal in the folder and run `pip install -r requirements.txt`.
4. Run `python main.py --demo`. Read the output next to section 6 of this guide until each line makes sense.
5. Run `python main.py`. Open the `results/` folder and look at each figure next to section 9.
6. Run `python -m unittest discover tests -v`. All 14 tests should say `ok`.
7. Read the code in the order of section 8. Change one number in `config.py` (try `BURST_THRESHOLD_K = 8`)
   and re-run, to see that you can control it.
8. **Put it on GitHub** (many faculties ask for a link). The README already displays the graphs.
9. **Write the report** (section 13) using the figures and the CSV tables.
10. **Prepare the viva** (section 12). Practise the 3-minute live demo:
    `--demo` → explain two rows → `python main.py` → show Fig 1, Fig 2, Fig 6.

---

## 12. Viva questions and answers

**Q1. What is disk scheduling and why do we need it?**
Many processes send I/O requests faster than the disk can serve them, so requests queue up. The disk
scheduler picks the order. A good order reduces seek time (the slowest controllable part), and also
decides who waits and for how long, which affects fairness and responsiveness.

**Q2. Seek time vs rotational latency vs transfer time?**
Seek is moving the arm to the cylinder. Rotational latency is waiting for the sector to spin under the
head (about half a rotation on average, ~4.17 ms at 7200 RPM). Transfer is reading the bits. Scheduling
mainly reduces seek time.

**Q3. Why is SCAN called the elevator algorithm?**
Like a lift, it moves in one direction serving every request on the way, then reverses. It never zig-zags,
so every request is reached within about two sweeps.

**Q4. SCAN vs C-SCAN vs LOOK?**
SCAN sweeps both ways and goes to the disk edge. C-SCAN serves only one way and jumps back, giving more
uniform waits. LOOK is SCAN that turns at the last request instead of the edge. Textbook example:
SCAN 236, C-SCAN 382 (with the return jump), LOOK 299 cylinders.

**Q5. Why can SSTF starve requests?**
It always picks the closest request. If new requests keep arriving near the head, a far-away request
is never the closest, so it can wait forever.

**Q6. What problems does your project solve?**
SCAN ignores priority, so critical I/O waits behind bulk work. And SCAN lets one bursty process monopolise
the head in its region. We solve these with a priority guard and a per-process quota, plus aging to
prevent the starvation that a quota could cause.

**Q7. Explain your three rules.** See section 5. One sentence each:
deadline guard for HIGH; K (or 2K) requests per process per sweep; requests older than 150 ms can't be throttled.

**Q8. Why a deadline instead of always serving HIGH first?**
We tried strict priority first. Skipping requests to chase HIGH ones destroys the elevator's efficiency,
and average waits roughly doubled under load. The deadline guard only breaks the sweep when a HIGH
request would actually be late.

**Q9. Why are HIGH requests exempt from throttling?**
They are system-critical (page faults, journal writes). Delaying them stalls whole programs. HIGH traffic
is also small (10%), so it can't monopolise the disk.

**Q10. How did you choose K = 4 and the 40 ms deadline?**
From the sensitivity experiment (Figure 7). Below K = 4, normal processes get no further benefit (at K = 1 they even
get worse) while the backup keeps slowing down. 40 ms halves HIGH tail latency without the large cost of tighter deadlines.
Both are configurable in `config.py`.

**Q11. Doesn't priority scheduling cause starvation?**
It can. Rule 3 (aging) is our answer, and the ablation study proves it works: without aging, the worst
wait is about 2,559 ms; with aging, about 470 ms.

**Q12. Your overall average wait got worse in two scenarios. Is your algorithm worse?**
It is a deliberate trade-off. A work-conserving scheduler can't reduce everyone's wait at once: if HIGH
requests go first, others go later. We moved waiting from critical and normal processes to background and
bursty work, and kept head movement within ±4% of SCAN. In MIXED, the average actually improved by 9%.

**Q13. Why a simulator and not a real OS?**
Changing a kernel's I/O scheduler needs kernel programming and real disks, and the results can't be
repeated exactly. A simulator gives identical inputs to every algorithm, runs in seconds, and lets us
measure everything. It is the standard method for this kind of study.

**Q14. Why 10 random seeds?**
One random workload could be lucky or unlucky for one algorithm. Averaging 10 different workloads gives
a fair result, and fixed seeds make it repeatable.

**Q15. What is the time complexity of `select()`?**
O(n) per decision, where n is the number of waiting requests: we scan the queue for the nearest request
and for at-risk HIGH requests. Real kernels keep requests in sorted trees (Linux uses red-black trees),
which makes most decisions O(log n).

**Q16. What does p99 mean and why report it?**
The value below which 99% of waits fall. It shows the worst cases, which averages hide and users notice.

**Q17. Does this apply to SSDs?**
Partly. SSDs have no moving arm, so seek-based ordering doesn't matter. Priority and fairness between
processes still do, which is why Linux still offers `mq-deadline` and `BFQ` for SSDs: for latency and
fairness rather than to reduce seeking.

**Q18. Is anything like this used in real operating systems?**
Yes. Linux's deadline scheduler keeps elevator order but jumps to requests whose deadline expires
(like Rule 1). BFQ gives each process a budget (like Rule 2). `ionice` lets users set real-time,
best-effort or idle I/O classes (like our priorities).

**Q19. Limitations?**
Simplified timing (linear seek, constant 4 ms read), synthetic workloads instead of real traces, no
request merging or caching, single disk. The HIGH deadline is a soft target: under extreme overload it
can still be missed. Most importantly, the priority guard assumes a sweep is short compared with the
deadline. If the disk is overloaded and one sweep takes longer than the deadline (try `DISK_SIZE = 1000`
without changing the seek time), the guard keeps turning the arm around and PA-SCAN-BT does much worse
than SCAN. A production version would need overload protection, for example switching the guard off
when the queue is very long.

**Q20. Future work?**
Replay real I/O traces, model a non-linear seek curve, adapt K automatically to load, or throttle by disk
region instead of by process.

---

## 13. Writing the report

A structure that fits this project (about 12–20 pages):

1. **Abstract** (150 words): problem, idea, headline numbers.
2. **Introduction**: why disk scheduling matters; the two problems with SCAN.
3. **Background**: FCFS, SSTF, SCAN, C-SCAN, LOOK, with the textbook example table from section 3.
4. **Proposed algorithm**: the three rules, the pseudo-code from section 5, and a flowchart
   (draw it from the pseudo-code: one box per step, one diamond per "if").
5. **Implementation**: folder structure, class diagram (`Scheduler` → `SCAN`, `LOOK`, ..., `PriorityThrottledSCAN`),
   and the simulator loop.
6. **Experimental setup**: the assumptions table from the README, the process table from section 7,
   the three scenarios, the metrics, 10 seeds.
7. **Results**: Figures 1–5, the results table from section 9, and one paragraph per figure.
8. **Ablation and sensitivity**: Figures 6 and 7.
9. **Discussion**: the trade-off (section 9, "how to explain these honestly") and the limitations (Q19).
10. **Conclusion and future work.**
11. **References**: the list in the README.

Screenshots worth including: the `--demo` terminal output and the unit tests passing.

---

## 14. Experiments you can try

Change a value in `config.py`, run `python main.py --quick`, and compare.

| Change | What you should see |
|---|---|
| `BURST_THRESHOLD_K = 1` | Too much throttling backfires: the backup waits longer *and* normal processes get worse (about 83 vs 67 ms) |
| `HIGH_DEADLINE = 15.0` | HIGH waits drop further, everyone else waits longer |
| `AGING_LIMIT = 1000.0` | The backup's worst wait grows: aging is weaker |
| `SERVICE_TIME = 1.0` (a faster disk) | Queues stay short, so HIGH requests are rarely at risk and PA-SCAN-BT behaves almost exactly like LOOK. SCAN's trips to the disk edge become its biggest cost |
| `DISK_SIZE = 1000` **and** `SEEK_TIME_PER_CYLINDER = 0.02` | Same 20 ms full sweep, finer grain. Results stay almost the same: a good robustness check for the report |
| `DISK_SIZE = 1000` alone | Each sweep now takes 100 ms, longer than the 40 ms deadline. The disk is overloaded and PA-SCAN-BT does **much worse** than SCAN (see Q19) |
| A new scenario in `workloads.SCENARIOS` | e.g. `"light": (60, False, "Light load")`. It appears in every table automatically |

---

## 15. Glossary

| Term | Meaning |
|---|---|
| **Cylinder / track** | A ring of data on the disk; our disk has cylinders 0–199 |
| **Head / arm** | The part that reads and writes; it moves between cylinders |
| **Seek** | Moving the head to another cylinder |
| **Sweep** | One pass of the head in one direction |
| **Request** | One read or write asked for by a process |
| **Priority class** | HIGH (critical), MEDIUM (interactive), LOW (background) |
| **Deadline** | The latest time a HIGH request should start (arrival + 40 ms) |
| **Throttling** | Limiting how much one process can get served per sweep |
| **Deferred request** | A request skipped this sweep because its process used its quota |
| **Aging** | Giving old requests extra rights so they can't wait forever |
| **Starvation** | A request waiting indefinitely |
| **Poisson arrivals** | Requests arriving independently at random times with a fixed average rate |
| **Seed** | The number that makes a "random" workload repeatable |
| **p99** | 99th percentile: 99% of values are below it |
| **Ablation study** | Switching parts of a design off one at a time to measure each part's effect |
| **Work-conserving** | A scheduler that never leaves the disk idle while requests are waiting |
