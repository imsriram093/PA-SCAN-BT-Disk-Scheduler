"""
enhanced.py  -  COMPONENT 2: our improved algorithm.

    PA-SCAN-BT = Priority-Aware SCAN with Burst-Throttling

At its heart it is still an elevator: the arm sweeps in one direction and
serves the NEAREST request ahead of it. It turns around at the last request
(LOOK-style) instead of wasting time travelling to the disk edge.
On top of that it adds three small rules:

  RULE 1 - PRIORITY GUARD  (deadline for HIGH-priority requests)
      Every HIGH request (page fault, file-system journal, ...) must start
      within HIGH_DEADLINE ms of arriving. Before each normal elevator step
      the scheduler asks:
          "If I serve the next request in sweep order first, will any HIGH
           request miss its deadline?"
      If yes, the elevator is overridden and the arm goes straight to the
      most urgent HIGH request (turning around if it is behind).
      If no, the normal sweep continues - so priority costs as little
      efficiency as possible. (This is the idea behind real-time disk
      schedulers such as SCAN-EDF and Linux's "deadline" I/O scheduler.)

  RULE 2 - BURST-THROTTLING  (priority-scaled quota per sweep)
      In one sweep a process may get at most
            K requests        if it is LOW priority,
            2 x K requests    if it is MEDIUM priority,
            unlimited         if it is HIGH priority.
      Extra requests are DEFERRED: the arm passes over them and they are
      served on a later sweep. One greedy process can no longer hold the
      head "hostage" in its little region of the disk.
      Throttling never makes the disk idle or turn early: if only deferred
      requests are ahead, the nearest of them is served anyway.

  RULE 3 - AGING  (no starvation)
      A request that has waited longer than AGING_LIMIT ms can no longer be
      deferred by Rule 2. Throttled processes are slowed down, never starved.

Each rule can be switched off (use_priority / use_throttling / use_aging).
With all three off, the algorithm is exactly LOOK - which lets the benchmark
measure how much each rule contributes (the "ablation study" graph).
"""

from collections import defaultdict

import config
from scheduler.baseline import Scheduler

HIGH, MEDIUM, LOW = config.HIGH, config.MEDIUM, config.LOW


class PriorityThrottledSCAN(Scheduler):
    name = "PA-SCAN-BT"

    def __init__(self,
                 burst_threshold=config.BURST_THRESHOLD_K,
                 high_deadline=config.HIGH_DEADLINE,
                 aging_limit=config.AGING_LIMIT,
                 use_priority=True,
                 use_throttling=True,
                 use_aging=True,
                 seek_time=config.SEEK_TIME_PER_CYLINDER,
                 service_time=config.SERVICE_TIME,
                 name=None):
        self.k = burst_threshold
        self.high_deadline = high_deadline
        self.aging_limit = aging_limit
        self.use_priority = use_priority
        self.use_throttling = use_throttling
        self.use_aging = use_aging
        self.seek_time = seek_time          # needed to predict when the head reaches a request
        self.service_time = service_time
        if name:
            self.name = name

    # ------------------------------------------------------------------ state
    def reset(self, head, direction, disk_size):
        super().reset(head, direction, disk_size)
        self.served_this_sweep = defaultdict(int)   # process_id -> requests served in this sweep
        self.last_note = ""                         # why the last decision was made (for --demo)

    def _turn_around(self):
        """Reverse direction. A new sweep starts, so every process gets a fresh quota."""
        self.direction = -self.direction
        self.served_this_sweep.clear()

    # ------------------------------------------------------------- RULE 2 + 3
    def quota(self, request):
        """How many requests this request's process may have served in one sweep."""
        return {HIGH: float("inf"), MEDIUM: 2 * self.k, LOW: self.k}[request.priority]

    def is_deferred(self, request, now):
        """True if Rule 2 says 'not in this sweep' and Rule 3 does not rescue it."""
        if not self.use_throttling:
            return False
        if self.use_aging and now - request.arrival_time > self.aging_limit:
            return False                                         # RULE 3: waited too long
        return self.served_this_sweep[request.process_id] >= self.quota(request)

    # ----------------------------------------------------------- the elevator
    def _elevator_choice(self, pending, head, now):
        """Plain LOOK, but deferred (throttled) requests are passed over."""
        for _ in range(2):
            ahead = self._ahead(pending, head)
            if ahead:
                allowed = [r for r in ahead if not self.is_deferred(r, now)]
                if len(allowed) < len(ahead):
                    self.last_note += f"{len(ahead) - len(allowed)} request(s) ahead deferred by throttling; "
                # Never idle because of throttling: if only deferred ones are ahead, take one anyway.
                return self._nearest(allowed or ahead, head)
            self._turn_around()                     # nothing ahead -> LOOK-style turn
            self.last_note += "nothing ahead -> turn around; "
        return self._nearest(pending, head)         # (unreachable; safety net)

    # --------------------------------------------------------------- RULE 1
    def _high_request_at_risk(self, pending, head, now, planned):
        """Return the most urgent HIGH request that would miss its deadline
        if we served `planned` first - or None if every HIGH request is safe."""
        finish_planned = now + abs(planned.track - head) * self.seek_time + self.service_time
        at_risk = []
        for r in pending:
            if r is planned or r.priority != HIGH:
                continue
            reach_time = finish_planned + abs(r.track - planned.track) * self.seek_time
            deadline = r.arrival_time + self.high_deadline
            if reach_time > deadline:
                at_risk.append((deadline, abs(r.track - head), r))
        if not at_risk:
            return None
        return min(at_risk, key=lambda item: (item[0], item[1]))[2]   # earliest deadline first

    # --------------------------------------------------------------- decision
    def select(self, pending, head, now):
        self.last_note = ""
        choice = self._elevator_choice(pending, head, now)

        if self.use_priority:
            urgent = self._high_request_at_risk(pending, head, now, choice)
            if urgent is not None:
                behind = (urgent.track - head) * self.direction < 0
                if behind:
                    self._turn_around()
                self.last_note += (f"PRIORITY GUARD: HIGH request at cylinder {urgent.track} would miss "
                                   f"its {self.high_deadline:g} ms deadline -> go there now"
                                   f"{' (turn around)' if behind else ''}; ")
                choice = urgent

        self.served_this_sweep[choice.process_id] += 1
        return choice, []
