"""
enhanced.py  -  COMPONENT 2: our improved policy.

    PA-SWEEP-BT = Priority-Aware prefix SWEEP with Burst-Throttling

It is PA-SCAN-BT from the disk project, moved onto an LLM server.
At its heart it is still an elevator over prefix ids (PREFIX-SWEEP), so
requests that share a prompt prefix are admitted together and the prefix
cache stays effective. On top of that it adds the same three rules:

  RULE 1 - TTFT GUARD  (deadline for INTERACTIVE requests)
      An INTERACTIVE request (a user watching a chat window) should get its
      first token within TTFT_DEADLINE_MS. Before each normal sweep pick the
      policy asks:
          "If this request waits GUARD_LOOKAHEAD_STEPS more steps, will it
           miss its deadline?"
      If yes, the sweep is overridden and the most urgent such request is
      admitted now. If the batch is full, the guard PREEMPTS a running
      request of lower priority (BATCH first, then STANDARD; the one that is
      cheapest to recompute). The victim goes back to the queue and its
      tokens are recomputed when it is re-admitted - this is how vLLM
      preempts. This is the "arm jumps to the urgent request" move.
      The guard does not move the sweep position, so the sweep resumes
      where it was.

  RULE 2 - BURST-THROTTLING  (priority-scaled quota per sweep)
      In one sweep a tenant may have at most
            K requests admitted     if it is BATCH,
            2 x K                   if it is STANDARD,
            unlimited               if it is INTERACTIVE.
      Extra requests are DEFERRED to a later sweep. A tenant that floods the
      server with hundreds of same-prefix requests (which PREFIX-SWEEP loves,
      because they are all cache hits) can no longer fill the whole batch.
      Throttling never leaves a slot empty: if only deferred requests are
      ahead, the nearest of them is admitted anyway.

  RULE 3 - AGING  (no starvation)
      A request that has waited longer than AGING_LIMIT_MS can no longer be
      deferred by Rule 2, and a request that has already been preempted
      MAX_PREEMPTIONS times can no longer be preempted by Rule 1.

Each rule can be switched off (use_guard / use_preemption / use_throttling /
use_aging). With all of them off the policy is exactly PREFIX-SWEEP - which
lets the benchmark measure what each rule contributes (the ablation graph).
"""

from collections import defaultdict

from llm_serving import config
from llm_serving.baseline import PrefixSweep
from llm_serving.server import ServerSpec

INTERACTIVE, STANDARD, BATCH = config.INTERACTIVE, config.STANDARD, config.BATCH


class PriorityThrottledSweep(PrefixSweep):
    name = "PA-SWEEP-BT"

    def __init__(self,
                 burst_threshold=config.BURST_THRESHOLD_K,
                 ttft_deadline=config.TTFT_DEADLINE_MS,
                 lookahead_steps=config.GUARD_LOOKAHEAD_STEPS,
                 aging_limit=config.AGING_LIMIT_MS,
                 max_preemptions=config.MAX_PREEMPTIONS,
                 use_guard=True,
                 use_preemption=True,
                 use_throttling=True,
                 use_aging=True,
                 server=None,
                 name=None):
        self.k = burst_threshold
        self.ttft_deadline = ttft_deadline
        self.lookahead_steps = lookahead_steps
        self.aging_limit = aging_limit
        self.max_preemptions = max_preemptions
        self.use_guard = use_guard
        self.use_preemption = use_preemption
        self.use_throttling = use_throttling
        self.use_aging = use_aging
        self.server = server or ServerSpec()   # needed to predict how long a step takes
        if name:
            self.name = name

    # ------------------------------------------------------------------ state
    def reset(self):
        super().reset()
        self.admitted_this_sweep = defaultdict(int)   # tenant_id -> admissions in this sweep
        self.guard_pick = None                        # request the guard chose (if any)
        self.guard_admissions = 0

    def _turn_around(self):
        """Reverse direction. A new sweep starts, so every tenant gets a fresh quota."""
        self.direction = -self.direction
        self.admitted_this_sweep.clear()

    # ------------------------------------------------------------- RULE 2 + 3
    def quota(self, request):
        """How many requests this request's tenant may have admitted in one sweep."""
        return {INTERACTIVE: float("inf"), STANDARD: 2 * self.k, BATCH: self.k}[request.priority]

    def is_deferred(self, request, now):
        """True if Rule 2 says 'not in this sweep' and Rule 3 does not rescue it."""
        if not self.use_throttling:
            return False
        if self.use_aging and now - request.arrival_time > self.aging_limit:
            return False                                         # RULE 3: waited too long
        return self.admitted_this_sweep[request.tenant_id] >= self.quota(request)

    # ----------------------------------------------------------- the elevator
    def _sweep_choice(self, waiting, now):
        """PREFIX-SWEEP, but deferred (throttled) requests are passed over."""
        for _ in range(2):
            ahead = self._ahead(waiting)
            if ahead:
                allowed = [r for r in ahead if not self.is_deferred(r, now)]
                if len(allowed) < len(ahead):
                    self.last_note += f"{len(ahead) - len(allowed)} request(s) ahead deferred by throttling; "
                # Never leave a slot empty because of throttling.
                return self._nearest(allowed or ahead)
            self._turn_around()                     # nothing ahead -> LOOK-style turn
            self.last_note += "nothing ahead -> turn around; "
        return self._nearest(waiting)               # (unreachable; safety net)

    # --------------------------------------------------------------- RULE 1
    def _at_risk(self, waiting, now):
        """The most urgent INTERACTIVE request that would miss its deadline if it waited
        `lookahead_steps` more full steps - or None if every one of them is safe."""
        s = self.server
        full_step = s.step_time(s.max_seqs, 0)
        urgent = None
        for r in waiting:
            if r.priority != INTERACTIVE or r.first_token_time is not None:
                continue
            own_step = s.step_time(s.max_seqs, r.prompt_len)        # assume a cache miss (safe side)
            if now + self.lookahead_steps * full_step + own_step > r.arrival_time + self.ttft_deadline:
                if urgent is None or (r.arrival_time, r.request_id) < (urgent.arrival_time, urgent.request_id):
                    urgent = r                                      # earliest deadline first
        return urgent

    # --------------------------------------------------------------- decisions
    def pick(self, waiting, now):
        self.last_note = ""
        self.guard_pick = self._at_risk(waiting, now) if self.use_guard else None
        if self.guard_pick is not None:
            self.last_note += (f"TTFT GUARD: INTERACTIVE request #{self.guard_pick.request_id} would miss "
                               f"its {self.ttft_deadline:g} ms deadline -> admit now; ")
            return self.guard_pick
        return self._sweep_choice(waiting, now)

    def on_admit(self, request, now):
        if request is self.guard_pick:
            self.guard_admissions += 1          # out-of-band: the sweep position does not move
            return
        self.head = request.prefix_id
        self.admitted_this_sweep[request.tenant_id] += 1

    def victim(self, candidate, running, now):
        """Rule 1 (preemption): free room for an urgent INTERACTIVE request."""
        if not (self.use_preemption and candidate is self.guard_pick):
            return None
        options = [r for r in running
                   if r.priority > candidate.priority
                   and not (self.use_aging and r.preemptions >= self.max_preemptions)]
        if not options:
            return None
        # Lowest priority first; among those, the one cheapest to recompute later.
        chosen = min(options, key=lambda r: (-r.priority, r.prompt_len + r.generated, r.request_id))
        self.last_note += f"preempt #{chosen.request_id} ({config.PRIORITY_NAMES[chosen.priority]}); "
        return chosen
