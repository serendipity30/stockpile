#!/usr/bin/env python3
"""Launch the options scanner (Streamlit) and the trading dashboard (Flask)
together, so the dashboard appears in the scanner's "Live Charts" tab.

    uv run run.py

Starts the Flask dashboard on http://localhost:5000 (also reachable
directly), waits for it to come up, then runs the Streamlit scanner on
http://localhost:8501. Both apps' logs stream to this one terminal,
prefixed `[scanner]` and `[dashboard]` so you can tell them apart. Ctrl+C
stops both. If a dashboard is already running on :5000, it is reused (not
restarted), and its logs stay in its own terminal.

To run either app on its own instead:
    uv run streamlit run options-scanner/run_app.py
    uv run trading-dashboard/app.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent


def _dashboard_port() -> int:
    """Dashboard TCP port, overridable via OSC_DASHBOARD_PORT (default 5000)
    for hosts where 5000 is taken. The Flask child and the scanner's Live
    Charts embed read the same var, so all three stay in sync."""
    raw = os.environ.get("OSC_DASHBOARD_PORT", "").strip()
    try:
        port = int(raw)
    except ValueError:
        return 5000
    return port if 1 <= port <= 65535 else 5000


DASHBOARD_PORT = _dashboard_port()
DASHBOARD_URL = f"http://localhost:{DASHBOARD_PORT}"
DASHBOARD_HEALTH = f"http://127.0.0.1:{DASHBOARD_PORT}/api/health"

_print_lock = threading.Lock()


def _pump(stream, prefix: str) -> None:
    """Echo a child process's combined output line-by-line, tagged with a
    prefix. The lock keeps the two apps' lines from interleaving mid-line."""
    for line in iter(stream.readline, ""):
        with _print_lock:
            sys.stdout.write(f"{prefix} {line}")
            sys.stdout.flush()
    stream.close()


def _start_logged(argv: list[str], prefix: str, **popen_kwargs) -> subprocess.Popen:
    """Start a child with its stdout+stderr captured and pumped through
    `_pump` on a daemon thread."""
    proc = subprocess.Popen(
        argv, cwd=REPO_ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, encoding="utf-8", errors="replace",
        **popen_kwargs,
    )
    threading.Thread(target=_pump, args=(proc.stdout, prefix),
                     daemon=True).start()
    return proc


def _probe(timeout: float = 1.0) -> bool:
    """Single health probe of the dashboard."""
    try:
        with urllib.request.urlopen(DASHBOARD_HEALTH, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def _wait_for_dashboard(timeout: float = 15.0) -> bool:
    """Poll until the dashboard answers or we time out."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _probe():
            return True
        time.sleep(0.4)
    return False


def _stop(proc: subprocess.Popen, label: str) -> None:
    """Stop a child process *and all its descendants*, cross-platform.

    A plain ``terminate()`` only signals the immediate child. Streamlit
    spawns a grandchild that holds the :8501 server socket, and on Windows
    our Flask child runs in its own process group — so terminating just the
    top process leaves orphans behind that keep the ports bound and the
    terminal looking hung (the reason Ctrl+C felt like it did nothing).

    Windows: ``taskkill /T /F`` reaps the whole tree. Elsewhere: terminate,
    then escalate to kill if it doesn't exit promptly.
    """
    if proc.poll() is not None:
        return  # already exited
    print(f"[run] Stopping {label} ...")
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    else:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> int:
    dashboard = None  # only set if WE started it (so we only stop ours)

    if _probe():
        print(f"[run] Trading dashboard already running on {DASHBOARD_URL} — "
              "reusing it (its logs stay in its own terminal).")
    else:
        # On Windows, put Flask in a new process group so the console's Ctrl+C
        # doesn't kill it before our own cleanup runs.
        kw = {}
        if sys.platform == "win32":
            kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        print(f"[run] Starting trading dashboard (Flask) on {DASHBOARD_URL} ...")
        dashboard = _start_logged(
            [sys.executable, "trading-dashboard/app.py"], "[dashboard]", **kw,
        )
        if _wait_for_dashboard():
            print("[run] Trading dashboard is up.")
        else:
            print("[run] Warning: dashboard did not become ready in time — "
                  "the Live Charts tab will show a start hint until it is.")

    print("[run] Starting options scanner (Streamlit) on "
          "http://localhost:8501 ...")
    scanner = _start_logged(
        [sys.executable, "-m", "streamlit", "run", "options-scanner/run_app.py"],
        "[scanner]",
    )
    try:
        scanner.wait()  # blocks until Streamlit exits (or Ctrl+C)
    except KeyboardInterrupt:
        print("[run] Ctrl+C received — shutting down ...")
    finally:
        # Tree-kill both children so no Streamlit grandchild or Flask
        # process-group orphan survives to hold a port. `dashboard` is only
        # set when WE started it, so a reused dashboard is left untouched.
        _stop(scanner, "options scanner")
        if dashboard is not None:
            _stop(dashboard, "trading dashboard")
    return 0


if __name__ == "__main__":
    sys.exit(main())
