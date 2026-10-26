"""
tests/test_lab.py  -  Checks for the live lab (lab/) and its AI co-pilot.

Run with:   python -m unittest tests.test_lab -v

None of these tests calls the Claude API: they test the offline engines and the
safety checks that sit between ANY language model and the simulator.
"""

import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from lab import copilot, disk_api, llm_api
from lab.disk_api import LabError
from lab.server import serve
from scheduler import workloads


def disk(injections=(), algorithms=("SCAN", "PA-SCAN-BT"), scenario="burst"):
    return disk_api.run({"algorithms": list(algorithms), "workload": {"scenario": scenario, "seed": 2},
                         "injections": list(injections)})


class LiveInjection(unittest.TestCase):
    """The lab's central promise: an event injected at time t cannot change anything before t."""

    def test_disk_history_before_injection_is_unchanged(self):
        t = 1500.0
        before = disk()
        after = disk([{"kind": "burst", "t": t}, {"kind": "pagefault", "t": t}])
        for b, a in zip(before["runs"], after["runs"]):
            served_before = [(i, s) for i, s in enumerate(b["start"]) if s < t]
            served_after = [(i, a["start"][i]) for i, s in served_before]
            self.assertEqual(served_before, served_after, b["name"])
            self.assertEqual([p for p in b["trajectory"] if p[0] < t], [p for p in a["trajectory"] if p[0] < t])

    def test_injected_requests_are_added_and_served(self):
        res = disk([{"kind": "burst", "t": 1000}, {"kind": "pagefault", "t": 2000}])
        base = len(disk()["requests"])
        self.assertEqual(len(res["requests"]), base + 40 + 3)
        self.assertIn(disk_api.INJECTED_BURST_PID, res["bursty"])
        for run in res["runs"]:
            for rid, pid, track, arrival, prio in res["requests"]:
                self.assertGreaterEqual(run["start"][rid], arrival)

    def test_same_request_gives_same_answer(self):
        inj = [{"kind": "burst", "t": 700}]
        self.assertEqual(json.dumps(disk(inj)), json.dumps(disk(inj)))

    def test_llm_history_before_injection_is_unchanged(self):
        t = 6000.0
        payload = {"algorithms": ["PREFIX-SWEEP", "PA-SWEEP-BT"], "workload": {"scenario": "flood", "seed": 1}}
        before = llm_api.run(payload)
        after = llm_api.run(dict(payload, injections=[{"kind": "chat", "t": t}, {"kind": "flood", "t": t}]))
        for b, a in zip(before["runs"], after["runs"]):
            early = [i for i, f in enumerate(b["first"]) if f < t]
            self.assertEqual([b["first"][i] for i in early], [a["first"][i] for i in early], b["name"])

    def test_bad_input_is_rejected_with_a_message(self):
        with self.assertRaises(LabError):
            disk(algorithms=["NOPE"])
        with self.assertRaises(LabError):
            disk([{"kind": "meteor", "t": 0}])


class LabMatchesTheBenchmark(unittest.TestCase):

    def test_demo_scenario_reproduces_main_demo(self):
        """The lab's demo must give the same HIGH waits as `python main.py --demo`."""
        res = disk_api.run({"algorithms": ["SCAN", "PA-SCAN-BT"], "workload": {"scenario": "demo"},
                            "settings": {"k": 3, "deadline": 40, "aging": 150}})
        high = [r[0] for r in res["requests"] if r[4] == config.HIGH]
        scan, pa = res["runs"]
        self.assertGreater(max(scan["start"][i] for i in high), 40.0)     # SCAN misses the deadline
        self.assertLessEqual(max(pa["start"][i] for i in high), 40.0)     # PA-SCAN-BT meets it
        self.assertEqual(scan["trajectory"][0][1], disk_api.DEMO_HEAD)

    def test_llm_segments_are_consistent(self):
        res = llm_api.run({"algorithms": ["PA-SWEEP-BT"], "workload": {"scenario": "flood", "seed": 3}})
        run = res["runs"][0]
        per_request = {}
        for rid, a, b in run["segments"]:
            self.assertLessEqual(a, b)
            per_request.setdefault(rid, []).append((a, b))
        self.assertEqual(sorted(per_request), list(range(len(res["requests"]))))
        for rid, segs in per_request.items():
            segs.sort()
            self.assertAlmostEqual(segs[-1][1], run["finish"][rid], places=2)   # last stay ends at finish
            for (a1, b1), (a2, _) in zip(segs, segs[1:]):
                self.assertLessEqual(b1, a2)                                      # stays never overlap


class CustomWorkloads(unittest.TestCase):

    SPEC = {"processes": [{"name": "db", "priority": config.MEDIUM, "rate": 50, "region": [20, 80]},
                          {"name": "pager", "priority": config.HIGH, "rate": 15, "region": [0, 199]}],
            "bursts": [{"name": "backup", "priority": config.LOW, "every_ms": 600, "size": 30, "region": [100, 120]}]}

    def test_generate_custom(self):
        a = workloads.generate_custom(self.SPEC, seed=4)
        b = workloads.generate_custom(self.SPEC, seed=4)
        self.assertEqual([(r.track, r.arrival_time) for r in a], [(r.track, r.arrival_time) for r in b])
        self.assertEqual({r.process_id for r in a}, {1, 2, 3})
        self.assertTrue(all(20 <= r.track <= 80 for r in a if r.process_id == 1))
        self.assertTrue(all(100 <= r.track <= 120 and r.priority == config.LOW for r in a if r.process_id == 3))

    def test_custom_spec_runs_in_the_lab(self):
        res = disk_api.run({"algorithms": ["SCAN", "PA-SCAN-BT"], "workload": {"spec": self.SPEC, "seed": 1}})
        self.assertEqual(res["bursty"], [3])
        self.assertEqual(res["processes"][1][0], "db")


class CopilotGuardrails(unittest.TestCase):
    """Whatever a language model returns, the simulator only ever sees safe values."""

    def test_sanitize_clamps_everything(self):
        raw = {"title": "x" * 500, "processes": [
            {"name": "evil", "priority": "ROOT", "rate_per_sec": 1e9, "region_start": -50, "region_end": 9999, "why": ""}],
            "bursts": [{"name": "b", "priority": "LOW", "every_ms": 1, "size": 10**6, "region_start": 300, "region_end": 5}]}
        spec, warnings = copilot.sanitize_spec(raw)
        p = spec["processes"][0]
        self.assertEqual(p["priority"], config.LOW)                  # unknown priority -> LOW
        self.assertEqual(p["region"], [0, config.DISK_SIZE - 1])
        b = spec["bursts"][0]
        self.assertLessEqual(b["size"], 80)
        self.assertGreaterEqual(b["every_ms"], 200)
        self.assertLessEqual(b["region"][1], config.DISK_SIZE - 1)
        self.assertLessEqual(len(spec["title"]), 80)
        self.assertTrue(any(q["priority"] == config.HIGH for q in spec["processes"]))   # a HIGH process is added
        total = sum(q["rate"] for q in spec["processes"]) + sum(q["size"] * 1000 / q["every_ms"] for q in spec["bursts"])
        self.assertLessEqual(total, copilot.MAX_TOTAL_RATE + 1)
        self.assertTrue(warnings)
        workloads.generate_custom(spec, seed=1, duration_ms=500)    # and it really runs

    def test_offline_scenario_engine(self):
        res = copilot.scenario_from_text("A busy database server while the nightly backup runs every 800 ms",
                                         use_llm=False)
        spec = res["spec"]
        names = [p["name"] for p in spec["processes"]]
        self.assertIn("database", names)
        self.assertEqual(len(names), len(set(names)))                         # no duplicates
        self.assertEqual([b["name"] for b in spec["bursts"]], ["backup"])
        self.assertEqual(spec["bursts"][0]["every_ms"], 800)
        self.assertTrue(any(p["priority"] == config.HIGH for p in spec["processes"]))
        self.assertLess(res["load"]["steady_rate"] + res["load"]["burst_rate"], 200)   # below capacity

    def test_empty_description_is_rejected(self):
        with self.assertRaises(LabError):
            copilot.scenario_from_text("   ", use_llm=False)

    def test_falls_back_to_offline_when_claude_is_unavailable(self):
        saved = copilot._state["disabled"]
        copilot._state["disabled"] = "test: Claude switched off"
        try:
            res = copilot.scenario_from_text("gaming pc with windows update", use_llm=True)
            self.assertEqual(res["engine"], "offline keyword engine")
            self.assertEqual(res["fallback_reason"], "test: Claude switched off")
            ex = copilot.explain({"note": "PRIORITY GUARD: ...", "time": 10.0, "chosen": {"track": 5}}, use_llm=True)
            self.assertIn("Rule 1", ex["text"])
        finally:
            copilot._state["disabled"] = saved

    def test_offline_explanations_name_the_rule(self):
        guard = copilot.explain({"note": "PRIORITY GUARD: HIGH request at cylinder 35 would miss its 40 ms deadline "
                                          "-> go there now (turn around)", "time": 27.0, "head": 120,
                                 "chosen": {"track": 35, "process": "kernel-pager", "waited": 27.0}}, use_llm=False)
        self.assertIn("Rule 1", guard["text"])
        self.assertIn("reversed", guard["text"])
        throttle = copilot.explain({"note": "36 request(s) ahead deferred by throttling", "time": 70.0,
                                    "chosen": {"track": 120}}, use_llm=False)
        self.assertIn("Rule 2", throttle["text"])
        self.assertIn("36", throttle["text"])


class VerifiedTuner(unittest.TestCase):

    def test_tuner_only_recommends_what_wins_on_unseen_seeds(self):
        res = copilot.tune({"scenario": "burst"}, "balanced", use_llm=False)
        rows = res["candidates"]
        self.assertEqual(rows[0]["source"], "default settings")
        best = rows[res["recommended"]]
        self.assertLessEqual(best["holdout_score"], rows[0]["holdout_score"])
        for r in rows[1:]:
            accepted = r["verdict"].startswith("accepted")
            self.assertEqual(accepted, r["holdout_score"] < rows[0]["holdout_score"])
        self.assertTrue(set(res["seeds"]["tuning"]).isdisjoint(res["seeds"]["held_out"]))

    def test_unknown_objective(self):
        with self.assertRaises(LabError):
            copilot.tune({"scenario": "burst"}, "fastest-ever", use_llm=False)


class HttpServer(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.server = serve(0)                                   # port 0 = any free port
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def post(self, path, body):
        req = urllib.request.Request(self.url + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    def test_page_and_api(self):
        with urllib.request.urlopen(self.url + "/") as r:
            self.assertIn(b"PA-SCAN-BT Live Lab", r.read())
        res = self.post("/api/disk/run", {"algorithms": ["LOOK"], "workload": {"scenario": "mixed", "seed": 1}})
        self.assertEqual(res["runs"][0]["name"], "LOOK")

    def test_errors_are_json(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/disk/run", {"algorithms": ["NOPE"]})
        self.assertEqual(ctx.exception.code, 400)
        self.assertIn("NOPE", json.loads(ctx.exception.read())["error"])
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/nothing", {})
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
