"""
The `scheduler` package: everything except the entry point (main.py) and the settings (config.py).

    request.py    - the Request "ticket"
    baseline.py   - COMPONENT 1: FCFS, SSTF, SCAN (baseline), C-SCAN, LOOK
    enhanced.py   - COMPONENT 2: PA-SCAN-BT (our improved algorithm)
    simulator.py  - runs any algorithm on any workload, records times
    workloads.py  - generates the test request streams
    metrics.py    - turns a simulation result into numbers
    plots.py      - COMPONENT 3: comparison graphs
"""
