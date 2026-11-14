"""Launch JARVIS in an app window of its own (Edge on Windows, a Chromium-family browser elsewhere); run the backend
without a console."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from jcc import system
from jcc.config import ROOT, load

URL = "http://127.0.0.1:8765/"


def ready() -> bool:
    """Is JARVIS itself answering on its port? Its page, served by a program of this Windows account: a program of
    another account that got to the port first is not JARVIS, whatever page it shows, and its page is never opened."""
    import http.client
    from urllib.parse import urlparse
    from jcc import peer
    port = urlparse(URL).port or 80
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        conn.request("GET", "/")
        if peer.answered_by_me(conn.sock.getsockname()[1], port) is False:      # (asked while the connection is open)
            return False
        return b"<title>JARVIS" in conn.getresponse().read(4096)
    except (OSError, http.client.HTTPException, AttributeError):
        return False
    finally:
        conn.close()


def edge_path() -> Path | None:
    candidates = [Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
                  Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Microsoft/Edge/Application/msedge.exe"]
    return next((p for p in candidates if p.exists()), None)


def window_browser() -> Path | None:
    """The browser that shows the app in a window of its own: Edge on Windows, as always; elsewhere the best
    Chromium-family browser found (Chrome, Edge, Brave, Chromium). None when there is none: the default browser is used."""
    if system.kind() == "windows":
        return edge_path()
    found = system.browsers()
    return Path(found[0]) if found else None


def tell(text: str, run=None) -> None:
    """Show the owner a sentence when the app could not start: a message box on Windows, an alert on a Mac. The text
    is handed to AppleScript as an argument, never written into its source, so nothing in it can run."""
    run = run or subprocess.run
    print(text, flush=True)
    if system.kind() == "windows":
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, "JARVIS", 0x10)
    elif system.kind() == "mac":
        try:
            run(["osascript", "-e", "on run argv", "-e", "display alert \"JARVIS\" message (item 1 of argv) as critical",
                 "-e", "end run", text], capture_output=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired):
            pass


# Every part JARVIS starts here runs on its own (in a session of its own, off Windows). On a Mac, JARVIS.app's launcher
# is a job of macOS's own, and when the launcher has done its work and ends, macOS ends everything still in the
# launcher's group with it: opened from its icon, JARVIS's service stopped a moment after it had started, and the
# window could not connect (opened from Terminal it kept running). Windows needs nothing: its programs run on.
def _alone() -> dict:
    return {"creationflags": system.no_window(), **system.own_group()}


def _helper(python: str, module: str, cfg, log_name: str, env: dict) -> None:
    with (cfg.state_dir / log_name).open("a", encoding="utf-8") as log:
        subprocess.Popen([python, "-m", module], cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, **_alone())


def main(background: bool = False, listen: bool = False) -> int:
    cfg = load()
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    python = system.background_python()
    _helper(python, "jcc.local_history", cfg, "local-history.log", env)
    _helper(python, "jcc.cloud_memory", cfg, "cloud-memory.log", env)
    _helper(python, "jcc.maintenance", cfg, "maintenance.log", env)
    if system.kind() in ("windows", "mac"):
        # Windows: the tray icon and the Ctrl+Alt+J shortcut. A Mac: the helper that listens for "Hey JARVIS".
        # Either exits at once if another copy is already running.
        subprocess.Popen([python, "-m", "jcc.tray"], cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **_alone())
    if not ready():
        # A signed update that was fetched in the background is installed now, before anything of JARVIS runs: the
        # install helper (jcc/update_helper.py) installs it and starts JARVIS again the way it was asked to start.
        try:
            from jcc import updates
            if updates.install_at_start(cfg):
                updates.start_install(cfg, start="background" if background else "listen" if listen else "window")
                return 0
        except Exception:  # noqa: BLE001 - an update that cannot be started now must never keep JARVIS from starting
            pass
        with (cfg.state_dir / "service.log").open("a", encoding="utf-8") as log:
            subprocess.Popen([python, "-m", "jcc", "gui", "--no-browser"], cwd=ROOT,
                             env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, **_alone())
        # (Its first start on a new computer takes longest: Python prepares every file of the app once.)
        for _ in range(240):
            if ready():
                break
            time.sleep(0.25)
        else:
            if not background:
                tell(f"Could not start JARVIS. See {cfg.state_dir / 'service.log'}")
            return 1
    if background:
        return 0
    browser = window_browser()
    if browser:
        from jcc import placement                # the size and place it had last time, made to fit this screen
        subprocess.Popen([str(browser), "--app=" + URL + ("?listen" if listen else ""), *placement.profile(cfg, URL), *placement.arguments(cfg, full=not listen)],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **system.own_group())
    else:
        import webbrowser
        webbrowser.open(URL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--background" in sys.argv, "--listen" in sys.argv))
