"""
baseline.py  -  COMPONENT 1: the reference scheduling policies.

Every policy answers ONE question, asked by the simulator before each step
while there is room in the batch:  "which waiting request should join next?"

Each policy is a small class with the same methods:
    reset()                           -> forget everything before a new run
    pick(waiting, now)                -> the request to admit next (no side effects)
    on_admit(request, now)            -> told when the pick really joined the batch
    victim(candidate, running, now)   -> a running request to push out so `candidate`
                                         fits, or None (only PA-SWEEP-BT preempts)

pick() must not change state, because the simulator may find that the pick
does not fit this step and ask again next step. State changes go in on_admit().

Policies
--------
FCFS          first come, first served - the default of most serving engines
PRIORITY      strict priority (INTERACTIVE > STANDARD > BATCH), FCFS inside a class
FAIR-SHARE    the tenant that has received the fewest tokens goes first
              (a simplified "Virtual Token Counter", Sheng et al., OSDI 2024)
PREFIX-SWEEP  THE BASELINE: the elevator (LOOK) over prefix ids. Requests that
              share a prefix are admitted together, so the prefix cache hits often.
"""

from collections import defaultdict

UP, DOWN = +1, -1


def _by_arrival(r):
    return (r.arrival_time, r.request_id)


class Scheduler:
    """Common parent class."""
    name = "base"

    def reset(self):
        self.last_note = ""

    def pick(self, waiting, now):
        raise NotImplementedError

    def on_admit(self, request, now):
        pass

    def victim(self, candidate, running, now):
        return None


# ---------------------------------------------------------------------------
class FCFS(Scheduler):
    """First-Come-First-Served: admit strictly in arrival order."""
    name = "FCFS"

    def pick(self, waiting, now):
        return min(waiting, key=_by_arrival)


# ---------------------------------------------------------------------------
class StrictPriority(Scheduler):
    """Most important class first; FCFS inside a class. BATCH can starve."""
    name = "PRIORITY"

    def pick(self, waiting, now):
        return min(waiting, key=lambda r: (r.priority,) + _by_arrival(r))


# ---------------------------------------------------------------------------
class FairShare(Scheduler):
    """Tenant with the fewest tokens served so far goes first (prompt + output tokens)."""
    name = "FAIR-SHARE"

    def reset(self):
        super().reset()
        self.served_tokens = defaultdict(int)

    def pick(self, waiting, now):
        return min(waiting, key=lambda r: (self.served_tokens[r.tenant_id],) + _by_arrival(r))

    def on_admit(self, request, now):
        if request.preemptions == 0:      # count a request once, not again when re-admitted
            self.served_tokens[request.tenant_id] += request.prompt_len + request.output_tokens


# ---------------------------------------------------------------------------
class PrefixSweep(Scheduler):
    """
    PREFIX-SWEEP (THE BASELINE) - LOOK, with prefix ids as cylinders.
    The "head" is the prefix id admitted last. Admit the nearest request ahead
    in the current direction; when nothing is ahead, turn around.
    Same-prefix requests sit at distance 0, so they are admitted back to back
    while their prefix is still cached. No priorities, no fairness limits.
    """
    name = "PREFIX-SWEEP"

    def reset(self):
        super().reset()
        self.head = 0
        self.direction = UP

    def _ahead(self, waiting):
        return [r for r in waiting if (r.prefix_id - self.head) * self.direction >= 0]

    def _nearest(self, requests):
        """Closest prefix to the head; ties broken by who arrived first."""
        return min(requests, key=lambda r: (abs(r.prefix_id - self.head),) + _by_arrival(r))

    def pick(self, waiting, now):
        ahead = self._ahead(waiting)
        if not ahead:
            # Turning around changes no result by itself, so it is safe inside pick().
            self.direction = -self.direction
            ahead = self._ahead(waiting)
        return self._nearest(ahead)

    def on_admit(self, request, now):
        self.head = request.prefix_id
