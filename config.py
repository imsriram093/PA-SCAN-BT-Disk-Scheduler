"""
config.py  -  Every number the simulation uses lives here.

Change a value, re-run `python main.py`, and watch how the results move.
That is the easiest way to run your own experiments for the report.
"""

# ---------------------------------------------------------------------------
# 1. The (simulated) hard disk
# ---------------------------------------------------------------------------
DISK_SIZE = 200                 # cylinders are numbered 0 .. 199 (the textbook size)
                                # If you change it, also scale SEEK_TIME_PER_CYLINDER so a full sweep
                                # stays ~20 ms (e.g. 1000 cylinders -> 0.02 ms). See PROJECT_GUIDE section 14.
INITIAL_HEAD = 100              # where the read/write head starts
INITIAL_DIRECTION = +1          # +1 = moving UP (towards 199), -1 = moving DOWN (towards 0)

# Simplified timing model (1 time unit = 1 millisecond), close to a 7200-RPM hard disk:
SEEK_TIME_PER_CYLINDER = 0.1    # ms to move the arm across ONE cylinder (full stroke = 20 ms)
SERVICE_TIME = 4.0              # ms to read/write once the head is there
                                # (average rotational latency ~4 ms + transfer)

# ---------------------------------------------------------------------------
# 2. Priority classes  (smaller number = more important)
# ---------------------------------------------------------------------------
HIGH, MEDIUM, LOW = 0, 1, 2
PRIORITY_NAMES = {HIGH: "HIGH", MEDIUM: "MEDIUM", LOW: "LOW"}

# ---------------------------------------------------------------------------
# 3. Knobs of the ENHANCED algorithm (PA-SCAN-BT)
# ---------------------------------------------------------------------------
HIGH_DEADLINE = 40.0            # Rule 1: a HIGH request should start within 40 ms of arriving
BURST_THRESHOLD_K = 4           # Rule 2: LOW process -> K requests per sweep, MEDIUM -> 2K
AGING_LIMIT = 150.0             # Rule 3: after waiting 150 ms a request can no longer be throttled

# ---------------------------------------------------------------------------
# 4. Experiment settings
# ---------------------------------------------------------------------------
SEEDS = list(range(1, 11))      # every scenario is run with 10 different random seeds
                                # and the results are averaged (fair + repeatable)
DURATION_MS = 4000.0            # each workload covers 4 seconds of requests

# Load sweep: background arrival rates (requests per second) for the "load vs wait" graph
LOAD_LEVELS = [60, 80, 100, 120, 140, 160]

# Sensitivity sweeps for the "tuning the knobs" graph
K_VALUES = [1, 2, 4, 6, 8, 12, 20]             # burst threshold K
DEADLINE_VALUES = [10, 20, 30, 40, 60, 80, 120] # HIGH deadline in ms

RESULTS_DIR = "results"         # graphs + CSV files are written here
