# PA-SCAN-BT: Priority-Aware Elevator Disk Scheduler with Burst-Throttling & LLM Serving Extension

[![Course](https://img.shields.io/badge/Course-Operating%20Systems%20(Fall%202026--27)-navy.svg)](docs/PROJECT_GUIDE.md)
[![Architecture](https://img.shields.io/badge/Architecture-Priority--Aware%20Elevator%20%2B%20Burst--Throttling-blue.svg)](#-architecture--containment-lifecycle)
[![Python Version](https://img.shields.io/badge/Python-3.8%20%7C%203.9%20%7C%203.10%20%7C%203.11%20%7C%203.12-green.svg)](https://www.python.org/)
[![Test Suite](https://img.shields.io/badge/Tests-44%20Passing%20(100%25%20Verified)-brightgreen.svg)](#-textbook-correctness--test-suite-integrity)
[![License](https://img.shields.io/badge/License-MIT%20%2F%20Academic-lightgrey.svg)](LICENSE)

**PA-SCAN-BT** is a high-performance, deterministic storage operating system scheduler engineered to eliminate priority inversion and head-hogging starvation in classic bidirectional elevator (**SCAN / LOOK**) architectures. While traditional disk schedulers maximize physical platter throughput by sorting requests solely on cylinder proximity, they remain critically blind to task urgency and multi-tenant burst behavior.

PA-SCAN-BT introduces **three lightweight deterministic invariant rules**—*Predictive Priority Guarding*, *Priority-Scaled Burst-Throttling*, and *Anti-Starvation Aging*—giving real-time I/O (such as kernel page faults) strict $P_{99}$ latency bounds while preserving mechanical seek efficiency. Furthermore, this repository demonstrates a groundbreaking **cross-domain transfer** to **Continuous-Batching LLM Inference Serving (PA-SWEEP-BT)**, alongside an **interactive web lab (`app.py`)** powered by an **offline/online AI Co-pilot** with closed-loop simulator verification.

---

## 🏛️ Foundational Storage Hardware Specifications

The simulator models an enterprise-grade 7200 RPM magnetic hard disk platter with Poisson arrival processes across multi-tenant workloads:

| Hardware / Environment Parameter | Specification | Simulation Constant (`config.py`) | Architectural Impact |
| :--- | :--- | :--- | :--- |
| **Total Platter Geometry** | 200 Cylinders (`0` to `199`) | `DISK_SIZE = 200` | Standard Silberschatz textbook benchmark range |
| **Head Start Position** | Cylinder `100`, Moving UP (`+1`) | `INITIAL_HEAD = 100` | Center-out initial directional scan |
| **Mechanical Seek Time** | `0.1 ms` per cylinder | `SEEK_TIME_PER_CYLINDER = 0.1` | Full disk stroke takes exactly 20.0 ms |
| **Rotational Latency + Transfer** | `4.0 ms` fixed per request | `SERVICE_TIME = 4.0` | Average rotational delay for 7200 RPM spindle |
| **Critical I/O Latency Target** | `40.0 ms` hard deadline | `HIGH_DEADLINE = 40.0` | Maximum tolerable delay for page faults & journals |
| **Burst Quota Scaling Factor** | $K = 4$ requests / sweep | `BURST_THRESHOLD_K = 4` | Per-process admission ceiling during single sweep |
| **Starvation Aging Ceiling** | `150.0 ms` wait limit | `AGING_LIMIT = 150.0` | Invariant threshold lifting all throttling deferrals |
| **Tenant Priority Distribution** | 10% HIGH, 30% MEDIUM, 60% LOW | `POISSON_WEIGHTS` | Models OS kernel, interactive apps, and bulk jobs |

---

## 📐 Architecture & Scheduling Lifecycle

```mermaid
flowchart TD
    subgraph Workload_Arrival ["1. Multi-Tenant I/O Arrival Stream"]
        P_HIGH["Kernel Page Faults (HIGH - 10%)"]
        P_MED["Database Queries (MEDIUM - 30%)"]
        P_LOW["Background Backup (LOW - 60%)"]
        INJ["Live Event Injection (💥 Burst / ⚡ Faults)"]
    end

    subgraph Decision_Engine ["2. PA-SCAN-BT Decision Engine (scheduler/enhanced.py)"]
        LOOK["Look-Ahead Elevator Selector (_elevator_choice)"]
        GUARD{"Rule 1: Priority Guard\nWill HIGH miss 40ms deadline?"}
        THROT{"Rule 2: Burst Throttle\nTenant requests >= Quota(P)?"}
        AGING{"Rule 3: Aging Rescue\nWait time > 150ms?"}
        OVERRIDE["Emergency Sweep Override\n(Seek straight to HIGH request)"]
        DEFER["Defer Request to Next Sweep\n(Pass over cylinder)"]
        ADMIT["Admit & Dispatch Request to Head"]
    end

    subgraph Storage_Platter ["3. Mechanical Platter Execution"]
        ARM["Arm Seek Actuator (0.1 ms/cyl)"]
        ROT["Rotational Transfer (4.0 ms)"]
        NON_PREEMPT["Non-Preemptive Atomic Execution"]
    end

    subgraph Telemetry_Evaluation ["4. Verification & Output Metrics"]
        METRICS["Latency & P99 Engine (metrics.py)"]
        WATERFALL["Real-Time Platter Waterfall (app.py)"]
        COPILOT["Verified AI Auto-Tuner (copilot.py)"]
        PLOTS["7 Publication-Grade Charts (results/)"]
    end

    P_HIGH & P_MED & P_LOW & INJ --> LOOK
    LOOK --> THROT
    THROT -->|Exceeded Quota| AGING
    AGING -->|Yes (>150ms)| ADMIT
    AGING -->|No| DEFER
    THROT -->|Within Quota| GUARD
    GUARD -->|Yes (Imminent Breach)| OVERRIDE
    GUARD -->|No (Safe)| ADMIT
    OVERRIDE --> ARM
    ADMIT --> ARM
    ARM --> ROT --> NON_PREEMPT
    NON_PREEMPT --> METRICS
    METRICS --> WATERFALL & COPILOT & PLOTS
```

---

## 📂 Project Directory Architecture

```text
PA-SCAN-BT-Disk-Scheduler/
├── main.py                          # Disk benchmark CLI: terminal tables, CSV exports & 7 plots
├── llm_main.py                      # LLM-serving benchmark CLI: TTFT tables, CSVs & 6 graphs
├── app.py                           # LIVE LAB: Browser-based interactive dashboard (Port 8050)
├── config.py                        # Master hardware timings, quotas, and benchmark parameters
├── requirements.txt                 # Runtime dependencies (matplotlib, optional anthropic)
├── README.md                        # Architecture, theory, benchmarks, and faculty guide
│
├── scheduler/                       # Component 1 & 2: Core Storage Engine
│   ├── __init__.py                  # Package exports
│   ├── request.py                   # DiskRequest datastructure (priority, cylinder, process_id)
│   ├── baseline.py                  # Baseline algorithms: FCFS, SSTF, SCAN, C-SCAN, LOOK
│   ├── enhanced.py                  # PA-SCAN-BT: Priority Guard, Burst-Throttling & Aging
│   ├── simulator.py                 # Discrete-event clock & non-preemptive execution simulator
│   ├── workloads.py                 # Deterministic synthetic generators (Mixed, Burst, Heavy)
│   ├── metrics.py                   # Statistical aggregation (Wait, P99, Turnaround, Movement)
│   └── plots.py                     # Component 3: 7 Matplotlib comparison figures
│
├── llm_serving/                     # Cross-Domain Extension: GPU Inference Server
│   ├── config.py                    # Server hardware specs (32 batch slots, KV-cache parameters)
│   ├── request.py                   # LLMRequest (Prompt length, output tokens, prefix ID)
│   ├── server.py                    # Analytical step-time simulator (Compute + KV memory)
│   ├── baseline.py                  # Baseline policies: FCFS, StrictPriority, FairShare, PrefixSweep
│   ├── enhanced.py                  # PA-SWEEP-BT: TTFT Guard, Quota Throttling & Preemption
│   ├── simulator.py                 # Continuous batching step loop with trace logging
│   ├── workloads.py                 # Multi-tenant workloads (Interactive, Flood, Heavy)
│   ├── metrics.py                   # TTFT, end-to-end latency, and SLO breach rates
│   └── plots.py                     # 6 LLM comparison graphs
│
├── lab/                             # Web Command Center & Live Simulation Engine
│   ├── server.py                    # Zero-dependency Python standard library HTTP/WS server
│   ├── disk_api.py                  # Real-time state streamer with dynamic event injection
│   ├── llm_api.py                   # LLM server simulation streaming endpoints
│   ├── copilot.py                   # Natural language workload parser & verified auto-tuner
│   └── static/                      # Self-hosted frontend dashboard (HTML5, Canvas, Modern CSS, JS)
│
├── tests/                           # 44 Verified Unit & Regression Tests
│   ├── test_scheduler.py            # Textbook Silberschatz verification & PA-SCAN-BT rule tests (14)
│   ├── test_llm_serving.py          # Continuous batching & preemption invariant tests (12)
│   └── test_lab.py                  # Non-rewriting history & co-pilot boundary tests (18)
│
├── results/                         # Generated outputs: PNG graphs and summary_*.csv files
└── docs/
    ├── PROJECT_GUIDE.md             # In-depth architectural breakdown & viva guide
    ├── PROJECT_STATUS.md            # Empirical performance records & experimental log
    └── PRESENTATION_GUIDE.md        # Scripted faculty presentation cues & demo walkthrough
```

---

## ⚡ Quickstart & Setup Guide

### 1. Environment Initialization
Ensure Python 3.8+ is installed on your workstation. Dependencies are intentionally minimal (Matplotlib for plotting; Anthropic is completely optional for cloud co-pilot):

```bash
# Clone or navigate to the repository
cd PA-SCAN-BT-Disk-Scheduler

# (Optional) Create and activate virtual environment
python -m venv venv

# On Windows PowerShell:
.\venv\Scripts\Activate.ps1
# On Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Verify Textbook Baseline Correctness (Run Test Suite)
Run all 44 unit tests to verify textbook head movement calculations and algorithm invariants:

```bash
python -m unittest discover tests -v
```
*Expected Result:* `Ran 44 tests in ~1.8s ... OK`

### 3. Execute the Storage Benchmark
Run the end-to-end discrete event simulation across all algorithms and scenarios:

```bash
# Full benchmark: executes 10 random seeds, prints tables, writes CSVs & 7 PNGs to results/
python main.py

# Live demonstration trace: 14-request step-by-step audit (Ideal for faculty viva)
python main.py --demo

# Quick developer mode: runs 3 seeds instead of 10 for rapid validation
python main.py --quick

# Full run with interactive Matplotlib figure popups
python main.py --show
```

### 4. Launch the Interactive Working Model (Web Lab)
```bash
python app.py
```
Open **`http://127.0.0.1:8050`** in any browser. No internet connection is required.

---

## 🛡️ The Three Invariants of PA-SCAN-BT

Standard SCAN services requests strictly in cylinder order, sweeping back and forth. **PA-SCAN-BT** retains this mechanical elegance while introducing three deterministic invariants:

```
                  ┌────────────────────────────────────────────────────────┐
                  │                 PA-SCAN-BT INVARIANTS                  │
                  ├────────────────────────────────────────────────────────┤
                  │  1. Priority Guard  : t_reach + t_seek <= Deadline     │
                  │  2. Burst-Throttle  : Serviced_Sweep(P) <= Quota(Pri)  │
                  │  3. Anti-Starvation : t_wait > 150ms => Lift Throttling│
                  └────────────────────────────────────────────────────────┘
```

### Invariant 1: The Predictive Priority Guard
Rather than acting reactively after a request has already failed its latency agreement, PA-SCAN-BT checks one step ahead:
$$\text{Reach Time} = \text{now} + \text{Time}(\text{head} \to \text{planned}) + \text{Service Time} + \text{Time}(\text{planned} \to \text{HIGH})$$
$$\text{Deadline} = \text{arrival\_time} + 40.0\text{ ms}$$
If $\text{Reach Time} > \text{Deadline}$, the elevator sweep is preemptively paused, and the disk arm seeks directly to the high-priority cylinder via Earliest Deadline First (EDF).

### Invariant 2: Priority-Scaled Burst-Throttling
To prevent a single runaway backup process from monopolizing the arm, admission is bounded per sweep:
$$\text{Quota}(\text{priority}) = \begin{cases} \infty & \text{if } \text{HIGH} \\ 2 \times K & \text{if } \text{MEDIUM} \\ K & \text{if } \text{LOW} \end{cases} \quad (\text{Default } K = 4)$$
* **Work-Conserving Invariant:** Throttling *never* leaves the disk arm idle. If all pending requests ahead are deferred, the nearest deferred request is serviced anyway. Quotas reset instantaneously upon arm reversal (`_turn_around`).

### Invariant 3: Anti-Starvation Aging
Any request whose wait time satisfies:
$$\text{Wait Time} = (\text{now} - \text{arrival\_time}) > 150.0\text{ ms}$$
is granted an unconditional waiver from Rule 2. It cannot be passed over or deferred, ensuring absolute bounded waiting times.

---

## 📊 Empirical Evaluation & Benchmark Ledger

Averaged across 10 randomized Poisson-distributed workloads per scenario (identical request arrival sequences delivered to all algorithms):

### Disk Benchmark Results: PA-SCAN-BT vs. Standard SCAN
*(Negative percentages denote performance improvements / latency reductions)*

| Workload Scenario | Metric Evaluated | Standard SCAN | PA-SCAN-BT (Ours) | Delta (%) | Architectural Consequence |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **MIXED** *(130 req/s)* | **HIGH Avg Wait** | 34.6 ms | **23.7 ms** | **−32%** | Page faults unblocked 32% faster |
| | **HIGH $P_{99}$ Wait** | 97.8 ms | **43.8 ms** | **−55%** | Strict adherence to 40 ms target |
| | **Head Movement** | 4,281 cyl | **4,110 cyl** | **−4%** | Zero mechanical penalty |
| **BURST** *(100 req/s + Floods)*| **HIGH Avg Wait** | 84.3 ms | **30.8 ms** | **−63%** | Immune to background I/O storms |
| | **HIGH $P_{99}$ Wait** | 265.5 ms | **48.6 ms** | **−82%** | Eliminates tail latency spikes |
| | **Normal Process Wait** | 81.2 ms | **66.8 ms** | **−18%** | Fair sharing under heavy contention |
| | **Hogging Process Wait**| 93.4 ms | **148.2 ms** | **+58%** | **The Trade-Off**: Burst absorbs delay |
| **HEAVY** *(160 req/s)* | **HIGH $P_{99}$ Wait** | 121.7 ms | **47.9 ms** | **−61%** | Rock-solid latency upper bound |
| | **Head Movement** | 4,912 cyl | **4,863 cyl** | **−1%** | Efficient trajectory preserved |

### Ablation Study Ledger (Evaluating Individual Rule Contribution)
Measured on the **BURST** workload scenario to isolate each mechanism:

| Policy Configuration | HIGH Avg Wait | HIGH $P_{99}$ | Normal Tenants | Bursty Tenant | Head Movement |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **LOOK Baseline (No rules)** | 84.3 ms | 265.5 ms | 81.2 ms | 93.4 ms | **2,814 cyl** |
| **+ Rule 1 Only (Priority Guard)** | 31.2 ms | 48.9 ms | 74.7 ms | 98.1 ms | 2,892 cyl |
| **+ Rule 2 Only (Throttling)** | 82.1 ms | 258.0 ms | 68.4 ms | 139.7 ms | 2,820 cyl |
| **PA-SCAN-BT (All 3 Rules)** | **30.8 ms** | **48.6 ms** | **66.8 ms** | **148.2 ms** | **2,842 cyl** |

---

## 📈 Generated Experimental Figures (`results/`)

Executing `python main.py` renders 7 analytical figures validating the scheduler:

| Figure Artifact | Description & Research Insight |
| :--- | :--- |
| [`results/fig1_head_trajectory.png`](results/fig1_head_trajectory.png) | Time-space trajectory of disk head arm path showing SCAN sweeps vs. PA-SCAN-BT priority jumps. |
| [`results/fig2_wait_by_priority.png`](results/fig2_wait_by_priority.png) | Latency distribution breakdown across HIGH, MEDIUM, and LOW priority classes. |
| [`results/fig3_all_algorithms.png`](results/fig3_all_algorithms.png) | Comparative radar & bar charts across FCFS, SSTF, SCAN, C-SCAN, LOOK, and PA-SCAN-BT. |
| [`results/fig4_per_process_wait.png`](results/fig4_per_process_wait.png) | Process-level fairness audit demonstrating isolation of normal processes from backup bursts. |
| [`results/fig5_load_sweep.png`](results/fig5_load_sweep.png) | Scalability analysis under escalating Poisson arrival rates ($60 \to 220\text{ req/s}$). |
| [`results/fig6_ablation.png`](results/fig6_ablation.png) | Step-by-step isolation showing the exact latency reduction contributed by each invariant rule. |
| [`results/fig7_sensitivity.png`](results/fig7_sensitivity.png) | Parameter sweep across burst threshold $K \in [1, 16]$ and deadlines $D \in [20, 100\text{ ms}]$. |

---

## 🧠 Cross-Domain Transfer: LLM KV-Cache Serving (`PA-SWEEP-BT`)

A major theoretical contribution of this project is proving that modern **continuous-batching LLM inference servers** (vLLM, SGLang, HuggingFace TGI) map mathematically to the disk scheduling problem:

| Classic Hard Disk Scheduling | Continuous-Batching LLM Serving Engine (`llm_serving/`) |
| :--- | :--- |
| **Cylinder / Track Index** | **Prompt Prefix ID** (Shared system prompt or document prefix in KV-cache) |
| **Disk Head Position** | Last admitted prefix ID in active continuous batch |
| **Mechanical Seek Latency** | **Prefix-Cache Miss**: GPU compute penalty to prefill and recompute tokens |
| **Head Reversal / Jump** | **Batch Preemption**: Evicting/recomputing low-priority sequences for urgent ones |
| **Tenant Priorities** | `INTERACTIVE` (Chat bots) vs. `STANDARD` (RAG) vs. `BATCH` (Bulk evals) |
| **Wait Time** | **TTFT (Time-To-First-Token)** perceived by end-users |

### LLM Benchmark Command:
```bash
python llm_main.py --quick
```

### Empirical Results under Heavy Multi-Tenant FLOOD Scenario:
* **INTERACTIVE $P_{99}$ Time-To-First-Token:** Slashed from **`4,657 ms` down to `309 ms` (−93%)**.
* **SLO Compliance Rate (<300 ms target):** Surged from **`43.9%` to `97.8%`**.
* **Comparison with Prior Art:** Outperforms strict priority queues (which starve batch jobs completely) and fair-share token counters (which cause prefix-cache thrashing).

---

## 🖥️ Command Center & Interactive Live Lab (`app.py`)

A full-featured, zero-dependency browser workbench powered by Python's built-in `http.server`:

```bash
python app.py
# Running locally at: http://127.0.0.1:8050
```

### Interactive Capabilities:
1. **Side-by-Side Dual Platter Visualization**: Watch SCAN and PA-SCAN-BT execute the exact same workload concurrently. Track queues, platter position, and latency waterfalls in real time.
2. **Live Event Injection**: Click **`💥 Backup burst`** or **`⚡ Page faults`** while the simulation runs. The scheduler incorporates newly arrived requests immediately without violating historical causality.
3. **LLM Serving Lab**: Switch tabs to observe GPU batch slot allocations, KV-cache prefix hits, and real-time TTFT metrics.
4. **Verified AI Co-pilot (`copilot.py`)**:
   * Type arbitrary natural language system scenarios (e.g., *"Database under heavy nightly backup"*).
   * The AI parses and suggests optimal parameters ($K$, deadlines, aging limits).
   * **Closed-Loop Verification:** Suggested parameters are benchmarked on **unseen held-out test seeds** before being presented. If an AI suggestion degrades performance, it is tagged as **REJECTED** by the simulator.

---

## 🧪 Textbook Correctness & Test Suite Integrity

The test suite validates baseline implementations directly against the standard reference calculations established in Silberschatz, Galvin, and Gagne (*Operating System Concepts*, 10th Edition):

### Silberschatz Cylinder Reference Test (`tests/test_scheduler.py`)
*Initial head at `53`, request queue: `[98, 183, 37, 122, 14, 124, 65, 67]`*

| Algorithm Evaluated | Silberschatz Textbook Head Movement | Our Implementation Output | Verification Status |
| :--- | :--- | :--- | :--- |
| **FCFS** | `640 cylinders` | `640 cylinders` | ✅ **VERIFIED MATCH** |
| **SSTF** | `236 cylinders` | `236 cylinders` | ✅ **VERIFIED MATCH** |
| **SCAN** | `236 cylinders` | `236 cylinders` | ✅ **VERIFIED MATCH** |
| **C-SCAN** | `382 cylinders` | `382 cylinders` | ✅ **VERIFIED MATCH** |
| **LOOK** | `299 cylinders` | `299 cylinders` | ✅ **VERIFIED MATCH** |

```bash
# Execute the full validation suite
python -m unittest discover tests -v
```

---

## 🎓 Faculty Evaluation & Component Mapping

| Required Component | Implementation File | Verification & Artifact |
| :--- | :--- | :--- |
| **1. Baseline Disk Algorithms** | [`scheduler/baseline.py`](scheduler/baseline.py) | Full implementation of FCFS, SSTF, SCAN, C-SCAN, and LOOK verified against textbook benchmarks. |
| **2. Enhanced Variant** | [`scheduler/enhanced.py`](scheduler/enhanced.py) | `PriorityThrottledSCAN` implementing predictive priority guards, burst quotas, and aging. |
| **3. Comparison Graphs & Metrics** | [`scheduler/plots.py`](scheduler/plots.py) | 7 publication-ready figures in [`results/`](results/) covering trajectories, ablation, and load sweeps. |
| **4. Working Model / Interactive Lab** | [`app.py`](app.py) & [`lab/`](lab/) | Browser dashboard with real-time platter animations, live injection, and AI co-pilot. |
| **5. Cross-Domain Extension** | [`llm_serving/`](llm_serving/) | Working LLM continuous-batching engine demonstrating KV-cache prefix scheduling. |

---

## 📚 Academic References & Prior Art

1. **A. Silberschatz, P. B. Galvin, G. Gagne**, *Operating System Concepts*, 10th ed., Wiley. (Mass-storage structure, disk scheduling principles).
2. **A. L. N. Reddy, J. Wyllie**, *"Disk scheduling in a multimedia I/O system"*, ACM Multimedia, 1993. (Foundational SCAN-EDF principles).
3. **P. Valente, F. Checconi**, *"High Throughput Disk Scheduling with Fair Bandwidth Distribution"*, IEEE Trans. on Computers, 2010. (Budget-based bandwidth isolation in BFQ).
4. **W. Kwon et al.**, *"Efficient Memory Management for Large Language Model Serving with PagedAttention"*, SOSP 2023. (Continuous batching and preemption mechanics).
5. **Y. Sheng et al.**, *"Fairness in Serving Large Language Models"*, OSDI 2024. (Virtual Token Counter fair-sharing).

---

## 🛡️ License
Developed for academic research and educational evaluation under the **MIT License**. Open for educational reproduction and experimental benchmarking.
