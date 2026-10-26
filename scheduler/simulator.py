"""
simulator.py  -  The "clock" of the experiment.

The simulator plays the role of the disk hardware + OS queue:

    1. Requests ARRIVE over time and wait in a pending queue.
    2. Whenever the disk is free, it asks the scheduling algorithm:
           "Here is the queue, the head is at cylinder X - which request next?"
    3. It moves the head there (seek), reads the data (service), records times.
    4. Repeat until every request has been served.

The SAME simulator runs EVERY algorithm on the SAME list of requests,
so the only thing that changes between runs is the decision rule.
That is what makes the comparison fair.
"""

from dataclasses import dataclass, field

import config


@dataclass
class SimulationResult:
    algorithm: str
    served: list                      # requests in the order they were served (with times filled in)
    trajectory: list                  # (time, cylinder) points -> used to draw the head-movement graph
    total_head_movement: int          # sum of |cylinder_i - cylinder_(i-1)|
    makespan: float                   # time when the last request finished
    direction_changes: int = 0        # how many times the arm reversed
    trace: list = field(default_factory=list)  # human-readable steps (used by --demo)


def simulate(scheduler, requests,
             disk_size=config.DISK_SIZE,
             initial_head=config.INITIAL_HEAD,
             initial_direction=config.INITIAL_DIRECTION,
             seek_time=config.SEEK_TIME_PER_CYLINDER,
             service_time=config.SERVICE_TIME):
    """Run one scheduling algorithm on one workload and return what happened."""

    # Work on fresh copies so the original workload can be reused by other algorithms.
    incoming = sorted((r.fresh_copy() for r in requests),
                      key=lambda r: (r.arrival_time, r.request_id))
    scheduler.reset(initial_head, initial_direction, disk_size)

    pending = []                 # requests that have arrived but are not served yet
    served = []
    trace = []
    time = 0.0
    head = initial_head
    total_movement = 0
    trajectory = [(0.0, head)]
    next_arrival = 0             # index into `incoming`

    while len(served) < len(incoming):
        # (1) Admit every request that has arrived by now.
        while next_arrival < len(incoming) and incoming[next_arrival].arrival_time <= time:
            pending.append(incoming[next_arrival])
            next_arrival += 1

        # (2) Nothing to do? The disk sits idle until the next request arrives.
        if not pending:
            time = incoming[next_arrival].arrival_time
            trajectory.append((time, head))
            continue

        # (3) Ask the algorithm for its decision.
        #     `via` = cylinders the head must pass through first
        #     (e.g. SCAN must touch the disk edge before it turns around).
        request, via = scheduler.select(pending, head, time)
        pending.remove(request)

        # (4) Move the head (seek) - possibly via the disk edge.
        distance = 0
        for stop in list(via) + [request.track]:
            step = abs(stop - head)
            distance += step
            time += step * seek_time
            head = stop
            trajectory.append((time, head))

        # (5) Serve the request (rotational latency + transfer).
        request.seek_distance = distance
        request.start_time = time
        time += service_time
        request.finish_time = time
        trajectory.append((time, head))

        total_movement += distance
        served.append(request)
        trace.append({
            "step": len(served),
            "request": request,
            "via": list(via),
            "distance": distance,
            "head_after": head,
            "queue_len": len(pending),
            "note": getattr(scheduler, "last_note", ""),
        })

    return SimulationResult(
        algorithm=scheduler.name,
        served=served,
        trajectory=trajectory,
        total_head_movement=total_movement,
        makespan=time,
        direction_changes=_count_direction_changes(trajectory),
        trace=trace,
    )


def _count_direction_changes(trajectory):
    """Count how many times the head reversed direction (UP->DOWN or DOWN->UP)."""
    changes, last_dir, last_pos = 0, 0, trajectory[0][1]
    for _, pos in trajectory[1:]:
        if pos == last_pos:
            continue
        d = 1 if pos > last_pos else -1
        if last_dir and d != last_dir:
            changes += 1
        last_dir, last_pos = d, pos
    return changes
