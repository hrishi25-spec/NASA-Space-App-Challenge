#!/usr/bin/env python3
"""Pyro-Harmony -- one-command launcher for Linux, macOS and Windows.

Creates the backend virtualenv, installs whatever is missing, starts the API and
the Vite dev server, waits until both answer, then opens the app.  Ctrl+C stops
everything, including the node/esbuild children npm would otherwise orphan.

Only the Python standard library is used, so this runs on a bare interpreter:

    python run.py              # set up + run
    python run.py --no-open    # don't open a browser
    ./start.sh                 # Linux / macOS wrapper
    start.bat                  # Windows wrapper

Deliberate portability choices:
  * servers are launched as real executables (venv python, node + vite.js), never
    through a shell, so Windows .cmd/.bat quoting can't bite us;
  * npm is only needed for the one-off dependency install, and that call falls
    back to a shell invocation if the shim refuses to launch directly;
  * child trees are killed with taskkill on Windows and process groups elsewhere;
  * every path is built with pathlib and every wait is a loop with a deadline.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "firecal" / "backend"
FRONTEND = ROOT / "firecal" / "frontend"
VENV = BACKEND / ".venv"
VITE_JS = FRONTEND / "node_modules" / "vite" / "bin" / "vite.js"
API_PORT = 8000
API_URL = f"http://127.0.0.1:{API_PORT}"
WEB_PORT = 5173
MIN_PYTHON = (3, 10)
MIN_NODE = 18
IS_WIN = os.name == "nt"


# ------------------------------------------------------------------ console output
def _enable_ansi() -> bool:
    if not IS_WIN:
        return True
    try:  # Windows 10+ needs virtual-terminal processing switched on first
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        return True
    except Exception:
        return False


ANSI = _enable_ansi() and sys.stdout.isatty()
CYAN, MAGENTA, GREEN, YELLOW, RED, DIM, OFF = (
    ("\033[96m", "\033[95m", "\033[92m", "\033[93m", "\033[91m", "\033[2m", "\033[0m")
    if ANSI else ("", "", "", "", "", "", ""))


def log(msg: str = "") -> None:
    print(msg, flush=True)


def step(msg: str) -> None:
    log(f"{DIM}  {msg}{OFF}")


def die(msg: str, hint: str = "") -> None:
    log(f"\n{RED}ERROR:{OFF} {msg}")
    if hint:
        log(f"\n{hint}")
    sys.exit(1)


# ------------------------------------------------------------------ platform glue
def venv_python() -> Path:
    """Windows keeps venv executables in Scripts/, POSIX in bin/."""
    return VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")


def run_cmd(cmd, cwd=None) -> int:
    """Run to completion, tolerating Windows' .cmd/.bat shims."""
    args = [str(c) for c in cmd]
    try:
        return subprocess.run(args, cwd=str(cwd) if cwd else None, check=False).returncode
    except OSError:
        quoted = " ".join(f'"{a}"' if " " in a else a for a in args)
        return subprocess.run(quoted, cwd=str(cwd) if cwd else None,
                              shell=True, check=False).returncode


def which(*names):
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def _on_terminate(signum, frame) -> None:
    """Turn SIGTERM (kill, closed terminal) into the same path as Ctrl+C."""
    raise KeyboardInterrupt


def port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0


# ------------------------------------------------------------------ pre-flight
def check_python() -> None:
    if sys.version_info < MIN_PYTHON:
        die(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required, but this is "
            f"Python {sys.version_info.major}.{sys.version_info.minor}.",
            "Install a current Python from https://www.python.org/downloads/ and run the launcher with it.")


def find_node() -> str:
    node = which("node")
    if not node:
        die("Node.js was not found on PATH.",
            "Install the LTS from https://nodejs.org/ (npm is bundled), reopen your terminal and retry.")
    try:
        out = subprocess.run([node, "-v"], capture_output=True, text=True, check=True).stdout.strip()
        major = int(out.lstrip("v").split(".")[0])
        if major < MIN_NODE:
            die(f"Node.js {MIN_NODE}+ is required, but this is {out}.",
                "Install the LTS from https://nodejs.org/ and retry.")
    except (ValueError, subprocess.SubprocessError):
        step("Could not read the Node.js version; continuing anyway.")
    return node


def ensure_venv() -> None:
    if venv_python().exists():
        return
    step("Creating the backend virtualenv (first run only) ...")
    if run_cmd([sys.executable, "-m", "venv", VENV]) != 0 or not venv_python().exists():
        shutil.rmtree(VENV, ignore_errors=True)
        die("Could not create a virtualenv.",
            "On Debian/Ubuntu install the venv module first:  sudo apt install python3-venv\n"
            "On other systems reinstall Python with the venv/pip options enabled.")


def ensure_python_deps() -> None:
    if run_cmd([venv_python(), "-c",
                "import fastapi, uvicorn, pandas, numpy, sklearn, scipy, requests, multipart"]) == 0:
        return
    step("Installing backend packages (first run only, a few minutes) ...")
    pip = [venv_python(), "-m", "pip", "install", "-q", "--disable-pip-version-check",
           "-r", BACKEND / "requirements.txt"]
    if run_cmd(pip) == 0:
        return
    # A system Python upgrade is the usual cause: the venv's interpreter is gone.
    step("pip failed -- rebuilding the virtualenv (a system Python upgrade can break it) ...")
    shutil.rmtree(VENV, ignore_errors=True)
    ensure_venv()
    if run_cmd(pip) != 0:
        die("Could not install the backend packages.",
            "Check your network or proxy, then retry. Manual equivalent:\n"
            f'  "{venv_python()}" -m pip install -r "{BACKEND / "requirements.txt"}"')


def ensure_node_deps() -> None:
    if VITE_JS.exists():
        return
    npm = which("npm", "npm.cmd")
    if not npm:
        die("Frontend packages are missing and npm was not found on PATH.",
            "Install Node.js LTS from https://nodejs.org/, reopen your terminal and retry.")
    step("Installing frontend packages (first run only) ...")
    if run_cmd([npm, "install", "--no-audit", "--no-fund"], cwd=FRONTEND) != 0:
        die("npm install failed.",
            f"Check your network or proxy, then retry:\n  cd \"{FRONTEND}\" && npm install")


# ------------------------------------------------------------------ child processes
URL_RE = re.compile(r"https?://(?:localhost|127\.0\.0\.1):(\d+)")
_url_lock = threading.Lock()
_web_port = {"value": 0}


def _pump(proc: subprocess.Popen, label: str, colour: str) -> None:
    """Echo a child's output with a prefix, and sniff the dev server's port."""
    try:
        for raw in proc.stdout:
            line = raw.rstrip()
            if line:
                print(f"{colour}[{label}]{OFF} {line}", flush=True)
            match = URL_RE.search(line)
            if match:
                with _url_lock:
                    _web_port["value"] = int(match.group(1))
    except Exception:
        pass


def spawn(cmd, cwd: Path, label: str, colour: str) -> subprocess.Popen:
    kwargs = {}
    if IS_WIN:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True   # own process group, so we can signal the whole tree
    proc = subprocess.Popen([str(c) for c in cmd], cwd=str(cwd), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            text=True, errors="replace", bufsize=1, **kwargs)
    threading.Thread(target=_pump, args=(proc, label, colour), daemon=True).start()
    return proc


def kill_tree(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    if IS_WIN:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True, check=False)
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def reachable(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            return r.status < 500
    except Exception:
        return False


def wait_for(proc: subprocess.Popen, url: str, timeout: float = 120.0) -> bool:
    """Wait for a URL to answer, giving up early if the process already died."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if reachable(url):
            return True
        if proc.poll() is not None:
            return False
        time.sleep(0.4)
    return False


def web_url(proc: subprocess.Popen, timeout: float = 120.0) -> str:
    """The dev server may pick a different port if 5173 is taken -- trust its own output."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with _url_lock:
            port = _web_port["value"]
        if port and reachable(f"http://127.0.0.1:{port}"):
            return f"http://127.0.0.1:{port}"
        if proc.poll() is not None:
            return ""
        time.sleep(0.3)
    return f"http://127.0.0.1:{WEB_PORT}"


# ------------------------------------------------------------------ main
def main() -> int:
    parser = argparse.ArgumentParser(description="Set up and run Pyro-Harmony.")
    parser.add_argument("--no-open", action="store_true", help="do not open a browser")
    args = parser.parse_args()

    # `kill`/closed terminals send SIGTERM, which would otherwise skip the cleanup in
    # `finally` and leave the servers orphaned. Route it through the same path as Ctrl+C.
    try:
        signal.signal(signal.SIGTERM, _on_terminate)
    except (AttributeError, ValueError, OSError):
        pass

    log("")
    log(f"  {GREEN}Pyro-Harmony{OFF}  burning-activity console")
    log(f"  {DIM}{sys.platform} | CPython {sys.version.split()[0]}{OFF}")
    log("")

    check_python()
    node = find_node()

    for port, name in ((API_PORT, "backend"), (WEB_PORT, "frontend")):
        if port_busy(port):
            log(f"{YELLOW}  warning:{OFF} port {port} is already in use -- another {name} may be running.")

    ensure_venv()
    ensure_python_deps()
    ensure_node_deps()

    api = web = None
    try:
        log("")
        step("Starting the API and the dev server ...")
        api = spawn([venv_python(), "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
                     "--port", str(API_PORT)], BACKEND, "api", CYAN)
        if not wait_for(api, f"{API_URL}/meta"):
            log(f"{RED}  the API never answered on {API_URL}/meta{OFF}")
            log("  see the [api] lines above for the traceback")
            return 1

        web = spawn([node, VITE_JS], FRONTEND, "web", MAGENTA)
        url = web_url(web)
        if not url:
            log(f"{RED}  the dev server exited before it was ready{OFF}")
            log("  see the [web] lines above for the reason")
            return 1

        log("")
        log(f"  {GREEN}ready{OFF}  {url}")
        log(f"  {DIM}api      {API_URL}{OFF}")
        log(f"  {DIM}stop     Ctrl+C{OFF}")
        log("")
        if not args.no_open:
            threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()

        while True:                       # stay up until Ctrl+C or a child dies
            for proc, name in ((api, "API"), (web, "dev server")):
                code = proc.poll()
                if code is not None:
                    log(f"\n{YELLOW}the {name} exited (code {code}) -- shutting the rest down{OFF}")
                    return code or 0
            time.sleep(0.4)
    except KeyboardInterrupt:
        log("\n  stopping ...")
        return 0
    finally:
        for proc in (web, api):
            kill_tree(proc)


if __name__ == "__main__":
    sys.exit(main())
