"""
llm_serving/config.py  -  Every number the LLM-serving simulation uses lives here.

Same idea as the disk project's config.py: change a value, re-run
`python llm_main.py`, and watch how the results move.

How the disk ideas map onto LLM serving
---------------------------------------
    disk project                      LLM serving project
    --------------------------------  ---------------------------------------------
    cylinder number                   prefix id (which shared system prompt /
                                      document the request starts with)
    head position                     prefix id the scheduler admitted last
    seek cost                         prefix-cache miss (re-computing a shared prompt)
    process                           tenant (a customer / app calling the API)
    HIGH / MEDIUM / LOW               INTERACTIVE / STANDARD / BATCH
    "start" of a request              first output token (TTFT = time to first token)
    backup process burst              a tenant flooding the server with requests
"""

# ---------------------------------------------------------------------------
# 1. The (simulated) GPU server  - roughly a 7-8B model on one 80 GB GPU
# ---------------------------------------------------------------------------
# The server runs in STEPS (one forward pass of the model). In every step:
#   - every running request generates ONE output token  (decode)
#   - newly admitted requests have their prompt processed (prefill) and
#     produce their FIRST token at the end of the step
# Step time (1 time unit = 1 millisecond):
#   STEP_BASE_MS + DECODE_MS_PER_SEQ * running requests + PREFILL_MS_PER_TOKEN * prompt tokens prefilled
STEP_BASE_MS = 6.0              # fixed cost of one forward pass
DECODE_MS_PER_SEQ = 0.25        # extra cost per request in the batch (full batch of 32 -> 14 ms / step)
PREFILL_MS_PER_TOKEN = 0.02     # 50,000 prompt tokens / second

MAX_BATCH_SEQS = 32             # at most 32 requests in the batch at once
KV_CACHE_TOKENS = 80_000        # memory for running requests (prompt + output tokens of each)
MAX_PREFILL_TOKENS = 8192       # at most this many prompt tokens are prefilled in one step
PREFIX_CACHE_TOKENS = 40_000    # LRU cache of shared prefixes (a hit skips re-computing the prefix)

NUM_PREFIXES = 64               # prefix ids 0 .. 63  (the "cylinders" of this project)

# ---------------------------------------------------------------------------
# 2. Priority classes  (smaller number = more important)
# ---------------------------------------------------------------------------
INTERACTIVE, STANDARD, BATCH = 0, 1, 2
PRIORITY_NAMES = {INTERACTIVE: "INTERACTIVE", STANDARD: "STANDARD", BATCH: "BATCH"}

# Service-level objectives (SLOs) used to score the results
TTFT_SLO_MS = {INTERACTIVE: 300.0, STANDARD: 2000.0}   # BATCH has no latency SLO

# ---------------------------------------------------------------------------
# 3. Knobs of the ENHANCED algorithm (PA-SWEEP-BT)
# ---------------------------------------------------------------------------
TTFT_DEADLINE_MS = 300.0        # Rule 1: an INTERACTIVE request should get its first token within 300 ms
GUARD_LOOKAHEAD_STEPS = 3       # Rule 1: act when waiting this many more steps would miss the deadline
MAX_PREEMPTIONS = 2             # Rule 1: a running request is pushed out of the batch at most twice
BURST_THRESHOLD_K = 3           # Rule 2: BATCH tenant -> K admissions per sweep, STANDARD -> 2K
AGING_LIMIT_MS = 5000.0         # Rule 3: after waiting 5 s a request can no longer be throttled

# ---------------------------------------------------------------------------
# 4. Experiment settings
# ---------------------------------------------------------------------------
SEEDS = list(range(1, 6))       # every scenario is run with 5 random seeds and averaged
DURATION_MS = 30_000.0          # each workload covers 30 seconds of arrivals

LOAD_LEVELS = [5, 6, 7, 8, 9, 10, 11]          # requests / second for the load-sweep graph
K_VALUES = [1, 2, 3, 5, 8, 12]                 # burst threshold K
DEADLINE_VALUES = [100, 200, 300, 500, 800]    # INTERACTIVE TTFT deadline in ms

RESULTS_DIR = "results/llm"     # graphs + CSV files are written here
