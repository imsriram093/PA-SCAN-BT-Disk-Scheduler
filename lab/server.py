"""
lab/server.py  -  A tiny web server for the live lab (Python standard library only).

    GET  /                       the dashboard (lab/static/index.html)
    GET  /api/status             which co-pilot engine is active
    POST /api/disk/run           run disk algorithms on a workload (+ injected events)
    POST /api/llm/run            run LLM-serving policies on a workload (+ injected events)
    POST /api/copilot/scenario   English -> workload spec
    POST /api/copilot/explain    explain one scheduler decision
    POST /api/copilot/tune       verified auto-tuning of K / deadline / aging

It listens on 127.0.0.1 only, so nobody else on the network can reach it.
"""

import json
import os
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from lab import copilot, disk_api, llm_api
from lab.disk_api import LabError

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
MAX_BODY = 1_000_000

ROUTES = {
    "/api/disk/run": disk_api.run,
    "/api/llm/run": llm_api.run,
    "/api/copilot/scenario": lambda p: copilot.scenario_from_text(p.get("text", ""), p.get("use_llm", True)),
    "/api/copilot/explain": lambda p: copilot.explain(p.get("context", {}), p.get("use_llm", True)),
    "/api/copilot/tune": lambda p: copilot.tune(p.get("workload", {}), p.get("objective", "balanced"),
                                                p.get("use_llm", True)),
}


class LabHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def log_message(self, fmt, *args):          # keep the terminal quiet except for API calls
        if self.path.startswith("/api/"):
            super().log_message(fmt, *args)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _json(self, status, body):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/status":
            return self._json(200, {"copilot": copilot.status(),
                                    "objectives": copilot.OBJECTIVES,
                                    "disk_algorithms": list(disk_api.ALGORITHMS),
                                    "llm_policies": list(llm_api.POLICIES)})
        if self.path.startswith("/api/"):
            return self._json(404, {"error": "unknown endpoint"})
        return super().do_GET()

    def do_POST(self):
        handler = ROUTES.get(self.path)
        if handler is None:
            return self._json(404, {"error": "unknown endpoint"})
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_BODY:
            return self._json(413, {"error": "request too large"})
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            return self._json(200, handler(payload))
        except (LabError, ValueError, KeyError, TypeError) as e:
            return self._json(400, {"error": str(e) or type(e).__name__})
        except Exception as e:                       # never kill the demo; show the error in the page
            traceback.print_exc()
            return self._json(500, {"error": f"{type(e).__name__}: {e}"})


def serve(port=8050):
    server = ThreadingHTTPServer(("127.0.0.1", port), LabHandler)
    return server
