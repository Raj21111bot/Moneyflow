#!/usr/bin/env python3
"""
dashboard_server.py
--------------------
Local viewing server for the Money Flow dashboard. Serves docs/ as static
files (same as `python -m http.server`) and additionally exposes
POST /api/refresh, which runs scripts/fetch_daily.py and best-effort
git add/commit/pushes the result. This is what the dashboard's "Refresh
data" button calls -- only works when the dashboard is being viewed through
this server (i.e. locally, via the desktop shortcut), not on the public
GitHub Pages copy, which is static.

Usage:
    python scripts/dashboard_server.py [port]   # default port 8000
"""

import json
import os
import subprocess
import sys
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(ROOT, "docs")


def run_refresh() -> dict:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "fetch_daily.py")],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=300, env=env,
    )
    output = (result.stdout or "") + (result.stderr or "")
    fetch_ok = result.returncode == 0

    push_note = "no git remote configured"
    try:
        git_ver = subprocess.run(["git", "--version"], cwd=ROOT, capture_output=True, text=True, timeout=10)
        if git_ver.returncode == 0:
            remotes = subprocess.run(["git", "remote"], cwd=ROOT, capture_output=True, text=True, timeout=10)
            if "origin" in (remotes.stdout or "").split():
                subprocess.run(["git", "add", "docs/data/history.json"], cwd=ROOT, capture_output=True, text=True, timeout=30)
                diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT, capture_output=True, timeout=30)
                if diff.returncode != 0:
                    subprocess.run(["git", "commit", "-m", "data: manual refresh update"], cwd=ROOT, capture_output=True, text=True, timeout=30)
                    push = subprocess.run(["git", "push"], cwd=ROOT, capture_output=True, text=True, timeout=60)
                    push_note = "pushed to GitHub" if push.returncode == 0 else f"push failed: {(push.stderr or '').strip()[:200]}"
                else:
                    push_note = "no new data to push"
        else:
            push_note = "git not installed"
    except Exception as e:
        push_note = f"git step skipped: {e}"

    return {"ok": fetch_ok, "output": output.strip(), "push": push_note}


class Handler(SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/api/refresh":
            try:
                result = run_refresh()
            except Exception as e:
                result = {"ok": False, "output": str(e), "push": "not attempted"}
            body = json.dumps(result).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    handler = partial(Handler, directory=DOCS_DIR)
    httpd = HTTPServer(("127.0.0.1", port), handler)
    print(f"Serving {DOCS_DIR} at http://127.0.0.1:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
