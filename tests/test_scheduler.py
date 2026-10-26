"""
tests/test_scheduler.py  -  Proof that the code is correct.

Run with:   python -m unittest discover tests -v

The first tests use the classic textbook example (Silberschatz, "Operating
System Concepts", disk-scheduling chapter): head at 53, queue
98, 183, 37, 122, 14, 124, 65, 67. If our FCFS/SSTF/SCAN/C-SCAN/LOOK give the
textbook answers, the baseline implementations are right.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from scheduler import workloads
from scheduler.baseline import FCFS, SSTF, SCAN, CSCAN, LOOK
from scheduler.enhanced import PriorityThrottledSCAN
from scheduler.request import Request
from scheduler.simulator import simulate

TEXTBOOK = [98, 183, 37, 122, 14, 124, 65, 67]


def textbook_requests():
    return [Request(i, 1, track, 0.0, config.LOW) for i, track in enumerate(TEXTBOOK)]


def run(alg, requests, head=53, direction=+1):
    return simulate(alg, requests, initial_head=head, initial_direction=direction)


class TextbookAnswers(unittest.TestCase):
    """Head movement must match the textbook for every baseline algorithm."""

    def test_fcfs(self):
        res = run(FCFS(), textbook_requests())
        self.assertEqual(res.total_head_movement, 640)
        self.assertEqual([r.track for r in res.served], TEXTBOOK)

    def test_sstf(self):
        res = run(SSTF(), textbook_requests())
        self.assertEqual(res.total_head_movement, 236)
        self.assertEqual([r.track for r in res.served], [65, 67, 37, 14, 98, 122, 124, 183])

    def test_scan_moving_towards_zero(self):
        res = run(SCAN(), textbook_requests(), direction=-1)
        self.assertEqual(res.total_head_movement, 236)            # 53->0 = 53, then 0->183 = 183
        self.assertEqual([r.track for r in res.served], [37, 14, 65, 67, 98, 122, 124, 183])

    def test_cscan(self):
        res = run(CSCAN(), textbook_requests())
        self.assertEqual(res.total_head_movement, 382)            # 53->199 + 199->0 + 0->37
        self.assertEqual([r.track for r in res.served], [65, 67, 98, 122, 124, 183, 14, 37])

    def test_look(self):
        res = run(LOOK(), textbook_requests())
        self.assertEqual(res.total_head_movement, 299)            # 53->183 + 183->14
        self.assertEqual([r.track for r in res.served], [65, 67, 98, 122, 124, 183, 37, 14])


class EnhancedAlgorithm(unittest.TestCase):

    def test_with_all_rules_off_it_is_exactly_look(self):
        work = workloads.generate("burst", seed=3)
        plain = simulate(LOOK(), work)
        off = simulate(PriorityThrottledSCAN(use_priority=False, use_throttling=False, use_aging=False), work)
        self.assertEqual([r.request_id for r in plain.served], [r.request_id for r in off.served])

    def test_priority_guard_meets_deadline_in_demo(self):
        res = simulate(PriorityThrottledSCAN(burst_threshold=3, high_deadline=40),
                       workloads.demo_workload(), initial_head=50, initial_direction=+1)
        for r in res.served:
            if r.priority == config.HIGH:
                self.assertLessEqual(r.waiting_time, 40.0)

    def test_scan_misses_the_same_deadline(self):
        """Sanity check that the demo really shows a problem for the baseline."""
        res = simulate(SCAN(), workloads.demo_workload(), initial_head=50, initial_direction=+1)
        worst_high = max(r.waiting_time for r in res.served if r.priority == config.HIGH)
        self.assertGreater(worst_high, 40.0)

    def test_throttling_stops_the_burst_after_k(self):
        """With K = 3, the backup process (P7) may get only 3 requests in a row in the first sweep."""
        res = simulate(PriorityThrottledSCAN(burst_threshold=3, use_priority=False),
                       workloads.demo_workload(), initial_head=50, initial_direction=+1)
        first_four = [r.process_id for r in res.served[:4]]
        self.assertEqual(first_four[:3], [7, 7, 7])
        self.assertNotEqual(first_four[3], 7)

    def test_high_priority_improves_on_every_scenario(self):
        for scenario in workloads.SCENARIOS:
            work = workloads.generate(scenario, seed=1)
            base = simulate(SCAN(), work).served
            new = simulate(PriorityThrottledSCAN(), work).served
            avg = lambda served: sum(r.waiting_time for r in served if r.priority == config.HIGH) / \
                sum(1 for r in served if r.priority == config.HIGH)
            self.assertLess(avg(new), avg(base), scenario)


class Simulator(unittest.TestCase):

    def test_every_request_served_exactly_once(self):
        work = workloads.generate("burst", seed=7)
        for alg in (FCFS(), SSTF(), SCAN(), CSCAN(), LOOK(), PriorityThrottledSCAN()):
            res = simulate(alg, work)
            ids = sorted(r.request_id for r in res.served)
            self.assertEqual(ids, list(range(len(work))), alg.name)

    def test_no_request_starts_before_it_arrives(self):
        work = workloads.generate("heavy", seed=2)
        for alg in (SCAN(), PriorityThrottledSCAN()):
            for r in simulate(alg, work).served:
                self.assertGreaterEqual(r.start_time, r.arrival_time)

    def test_results_are_repeatable(self):
        a = simulate(PriorityThrottledSCAN(), workloads.generate("mixed", seed=5))
        b = simulate(PriorityThrottledSCAN(), workloads.generate("mixed", seed=5))
        self.assertEqual(a.total_head_movement, b.total_head_movement)
        self.assertEqual([r.request_id for r in a.served], [r.request_id for r in b.served])

    def test_original_workload_is_not_modified(self):
        work = workloads.generate("mixed", seed=4)
        simulate(SCAN(), work)
        self.assertTrue(all(r.start_time is None for r in work))


if __name__ == "__main__":
    unittest.main()
