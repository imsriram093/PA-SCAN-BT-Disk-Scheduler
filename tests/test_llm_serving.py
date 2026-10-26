"""
tests/test_llm_serving.py  -  Proof that the LLM-serving simulator is correct.

Run with:   python -m unittest discover tests -v

Timing used by the hand-worked examples (defaults from llm_serving/config.py):
    step time = 6 ms + 0.25 ms x running requests + 0.02 ms x prompt tokens prefilled
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_serving import config, workloads
from llm_serving.baseline import FCFS, StrictPriority, FairShare, PrefixSweep
from llm_serving.enhanced import PriorityThrottledSweep
from llm_serving.request import Request
from llm_serving.server import PrefixCache, ServerSpec
from llm_serving.simulator import simulate

INTERACTIVE, STANDARD, BATCH = config.INTERACTIVE, config.STANDARD, config.BATCH


def req(i, prefix, priority=BATCH, tenant=1, arrival=0.0, prefix_tokens=100, prompt=100, output=1):
    return Request(i, tenant, priority, arrival, prefix, prefix_tokens, prompt, output)


def finish_order(result):
    return [r.request_id for r in result.finished]


class ServerModel(unittest.TestCase):

    def test_single_request_timing(self):
        # step 1: prefill 200 tokens -> 6 + 4 = 10 ms (first token)
        # steps 2, 3: one request decoding -> 6.25 ms each
        res = simulate(FCFS(), [req(0, 5, output=3)])
        r = res.finished[0]
        self.assertAlmostEqual(r.first_token_time, 10.0)
        self.assertAlmostEqual(r.finish_time, 22.5)
        self.assertEqual(res.steps, 3)

    def test_prefix_cache_is_lru(self):
        cache = PrefixCache(300)
        self.assertFalse(cache.lookup(1, 100))
        self.assertFalse(cache.lookup(2, 100))
        self.assertTrue(cache.lookup(1, 100))       # 1 is now the most recently used
        self.assertFalse(cache.lookup(3, 150))      # needs room -> evicts 2, not 1
        self.assertTrue(cache.contains(1))
        self.assertFalse(cache.contains(2))
        self.assertEqual(cache.used, 250)

    def test_cache_hit_skips_shared_prefix(self):
        # Same prefix twice: 200 tokens for the first, only 100 for the second.
        res = simulate(FCFS(), [req(0, 7), req(1, 7)])
        self.assertEqual(res.prefill_tokens, 300)
        self.assertEqual(res.cache_hits, 1)


class BaselineOrder(unittest.TestCase):
    one_slot = ServerSpec(max_seqs=1)

    def test_fcfs_and_priority(self):
        reqs = [req(0, 1, BATCH), req(1, 2, INTERACTIVE), req(2, 3, STANDARD)]
        self.assertEqual(finish_order(simulate(FCFS(), reqs, server=self.one_slot)), [0, 1, 2])
        self.assertEqual(finish_order(simulate(StrictPriority(), reqs, server=self.one_slot)), [1, 2, 0])

    def test_prefix_sweep_is_look(self):
        # Head starts at prefix 0 moving UP. Prefix 5 arrives after the sweep has passed it.
        reqs = [req(0, 40), req(1, 10), req(2, 30), req(3, 5, arrival=1.0)]
        res = simulate(PrefixSweep(), reqs, server=self.one_slot)
        self.assertEqual([r.prefix_id for r in res.finished], [10, 30, 40, 5])

    def test_fair_share_alternates_tenants(self):
        reqs = [req(0, 1, tenant=1), req(1, 1, tenant=1), req(2, 9, tenant=2), req(3, 9, tenant=2)]
        res = simulate(FairShare(), reqs, server=self.one_slot)
        self.assertEqual([r.tenant_id for r in res.finished], [1, 2, 1, 2])


class EnhancedRules(unittest.TestCase):
    one_slot = ServerSpec(max_seqs=1)

    def test_all_rules_off_equals_prefix_sweep(self):
        work = workloads.generate("flood", seed=1, duration_ms=5000)
        base = simulate(PrefixSweep(), work)
        off = simulate(PriorityThrottledSweep(use_guard=False, use_preemption=False,
                                              use_throttling=False, use_aging=False), work)
        self.assertEqual(finish_order(base), finish_order(off))
        self.assertAlmostEqual(base.makespan, off.makespan)

    def test_throttling_breaks_up_a_flood(self):
        # Tenant 7 floods 6 requests on prefix 24; tenant 5 has one on prefix 30.
        reqs = [req(i, 24, tenant=7) for i in range(6)] + [req(6, 30, tenant=5)]
        plain = simulate(PrefixSweep(), reqs, server=self.one_slot)
        pa = simulate(PriorityThrottledSweep(burst_threshold=2, use_guard=False), reqs, server=self.one_slot)
        self.assertEqual(finish_order(plain).index(6), 6)    # waits for the whole flood
        self.assertEqual(finish_order(pa).index(6), 2)       # gets in after K = 2 flood requests

    def test_aging_lifts_throttling(self):
        pa = PriorityThrottledSweep(burst_threshold=2)
        pa.reset()
        pa.admitted_this_sweep[7] = 2
        r = req(0, 24, tenant=7)
        self.assertTrue(pa.is_deferred(r, now=100.0))
        self.assertFalse(pa.is_deferred(r, now=config.AGING_LIMIT_MS + 1))

    def test_guard_preempts_for_interactive(self):
        # Two long BATCH jobs fill a 2-slot server; a chat request arrives at t = 1 ms.
        two = ServerSpec(max_seqs=2)
        reqs = [req(0, 50, BATCH, prefix_tokens=1000, output=100),
                req(1, 51, BATCH, prefix_tokens=1000, output=100),
                req(2, 2, INTERACTIVE, arrival=1.0, prefix_tokens=800, output=5)]
        plain = simulate(PrefixSweep(), reqs, server=two)
        pa = simulate(PriorityThrottledSweep(ttft_deadline=100, server=two), reqs, server=two)

        def chat(res):
            return next(r for r in res.finished if r.request_id == 2)
        self.assertGreater(chat(plain).ttft, 300)      # waits for a BATCH job to finish
        self.assertLess(chat(pa).ttft, 100)            # guard preempts and meets the deadline
        self.assertEqual(pa.preemptions, 1)
        for r in pa.finished:                          # the victim still completes fully
            self.assertEqual(r.generated, r.output_tokens)


class Invariants(unittest.TestCase):

    def test_every_policy_finishes_every_request(self):
        work = workloads.generate("flood", seed=2, duration_ms=5000)
        for policy in (FCFS(), StrictPriority(), FairShare(), PrefixSweep(), PriorityThrottledSweep()):
            res = simulate(policy, work)
            self.assertEqual(len(res.finished), len(work), policy.name)
            for r in res.finished:
                self.assertEqual(r.generated, r.output_tokens)
                self.assertGreater(r.ttft, 0)
                self.assertGreaterEqual(r.finish_time, r.first_token_time)

    def test_workloads_are_repeatable(self):
        a = workloads.generate("mixed", seed=3, duration_ms=3000)
        b = workloads.generate("mixed", seed=3, duration_ms=3000)
        self.assertEqual([(r.arrival_time, r.prefix_id, r.output_tokens) for r in a],
                         [(r.arrival_time, r.prefix_id, r.output_tokens) for r in b])


if __name__ == "__main__":
    unittest.main()
