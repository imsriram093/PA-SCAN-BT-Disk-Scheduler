
"""
app.py  -  Start the LIVE LAB: the interactive working model of the project.

    python app.py                 starts the lab and opens it in your browser
    python app.py --port 9000     use another port
    python app.py --no-browser    just start the server

What you get (all in the browser, no internet needed):
    Disk Lab      SCAN vs PA-SCAN-BT (or any 4 algorithms) animated side by side.
                  Click "Backup burst" or "Page faults" while it runs and watch
                  how each algorithm reacts. Click a decision to have it explained.
    LLM Lab       The same three rules scheduling a GPU serving an LLM:
                  watch the batch slots, the prefix "head" and time-to-first-token.
    AI Co-pilot   Describe a workload in English and run it; let an LLM propose
                  tuning values that the simulator then verifies on unseen workloads.

The co-pilot uses Claude when `pip install anthropic` has been done and an
ANTHROPIC_API_KEY is set; otherwise it uses its offline engines automatically.
"""

import argparse
import sys
import threading
import webbrowser

from lab.server import serve


def main():
    parser = argparse.ArgumentParser(description="PA-SCAN-BT live lab")
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    args = parser.parse_args()

    try:
        server = serve(args.port)
    except OSError:
        print(f"Port {args.port} is busy. Try: python app.py --port {args.port + 1}")
        return 1
    url = f"http://127.0.0.1:{args.port}/"
    print(f"PA-SCAN-BT live lab running at {url}   (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(0.8, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
