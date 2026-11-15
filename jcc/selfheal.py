"""Problems JARVIS finds in itself are fixed by itself, where that is safe. The service runs this every minute.

- A background helper that stopped (saving coding chats, memory sync, maintenance, the helper that listens for
  "Hey JARVIS" and the shortcuts) is started again. One that keeps stopping (three times in an hour) is left stopped and
  reported instead, so nothing loops.
- A coding job that failed for a passing reason (the network, a time-out, a rate limit, an AI that was overloaded) carries
  on by itself from where it stopped, once, a couple of minutes later. One that failed for another reason waits for its
  owner's Continue, with its work kept.
- (Interrupted jobs carry on by themselves: jcc/resilience.py. The inbox watcher is started again by the service.)

What needs its owner (a key that is wrong, a microphone they muted, a change to review) is never "fixed" behind their
back: it stays reported, with its one-click fix. Each fix is written down (self-heal.json), and /status shows them.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

from jcc import system
from jcc.vault import Vault, atomic_write, parse_frontmatter

HELPERS = (("jcc.local_history", "local-history.lock", "local-history.log", "Saving your coding chats"),
           ("jcc.cloud_memory", "cloud-worker.lock", "cloud-memory.log", "Memory sync"),
           ("jcc.maintenance", "maintenance.lock", "maintenance.log", "Maintenance"),
           ("jcc.tray", "tray.lock", "", "The helper for “Hey JARVIS” and the shortcuts"))
TRANSIENT = re.compile(r"timed? ?out|timeout|network|connection (?:reset|refused|aborted|error)|temporar|rate.?limit|\b429\b|\b50[234]\b|"
                       r"overloaded|could not be reached|ECONNRESET|ETIMEDOUT|service unavailable|try again later", re.I)
RESTARTS_PER_HOUR = 3
FAILED_WAIT_S = 120


def _file(cfg) -> Path:
    return cfg.state_dir / "self-heal.json"


def _load(cfg) -> dict:
    try:
        data = json.loads(_file(cfg).read_text("utf-8"))
    except (OSError, ValueError):
        data = {}
    return {"fixed": data.get("fixed") if isinstance(data.get("fixed"), list) else [],
            "restarts": data.get("restarts") if isinstance(data.get("restarts"), dict) else {},
            "gave_up": data.get("gave_up") if isinstance(data.get("gave_up"), dict) else {}}


def recent(cfg, limit: int = 12) -> dict:
    data = _load(cfg)
    return {"fixed": list(reversed(data["fixed"]))[:limit], "gave_up": data["gave_up"]}


def _held(path: Path) -> bool:
    from jcc.connections import _held as held
    return path.exists() and held(path)


def _start_helper(cfg, module: str, log_name: str) -> None:
    import os
    from jcc.config import ROOT
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    python = system.background_python()
    out = (cfg.state_dir / log_name).open("a", encoding="utf-8") if log_name else subprocess.DEVNULL
    try:
        subprocess.Popen([python, "-m", module], cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                         creationflags=system.no_window(), **system.own_group())
    finally:
        if log_name:
            out.close()


def helpers(cfg, data: dict, now: float, start=None) -> list[dict]:
    """Start again a helper that is not running (each helper holds its lock while it runs)."""
    start = start or _start_helper
    fixed = []
    for module, lock_name, log_name, label in HELPERS:
        if module == "jcc.tray" and system.kind() not in ("windows", "mac"):
            continue
        lock = cfg.state_dir / lock_name
        if not lock.exists() or _held(lock):
            continue                    # (never started on this computer, or running)
        times = [t for t in data["restarts"].get(module, []) if now - t < 3600]
        if len(times) >= RESTARTS_PER_HOUR:
            data["gave_up"][module] = {"label": label, "at": now, "why": "It keeps stopping, so it was left stopped. Restart JARVIS, or see "
                                                                          + (log_name or "the tray") + " in JARVIS's data folder."}
            continue
        start(cfg, module, log_name)
        data["restarts"][module] = times + [now]
        data["gave_up"].pop(module, None)
        fixed.append({"at": now, "what": label + " had stopped", "done": "Started it again."})
    return fixed


def failed_jobs(cfg, now: float, carry_on=None) -> list[dict]:
    """A job that failed for a passing reason carries on by itself, once, from where it stopped."""
    from jcc import job_control
    carry_on = carry_on or job_control.carry_on
    fixed = []
    folder = Path(cfg.vault) / "Jobs"
    for path in sorted(folder.glob("*.md"), reverse=True)[:60] if folder.is_dir() else []:
        try:
            fm, _ = parse_frontmatter(path.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        rid = str(fm.get("id") or path.stem)
        if fm.get("status") != "failed" or fm.get("kind", "job") != "job" or int(fm.get("auto_resumes") or 0) >= 1:
            continue
        if now - path.stat().st_mtime < FAILED_WAIT_S:
            continue
        log = cfg.jobs_root / rid / "output.log"
        said = log.read_text("utf-8", errors="replace")[-3000:] if log.exists() else ""
        if not TRANSIENT.search(said):
            continue
        try:
            carry_on(cfg, rid, "")
        except ValueError:
            continue
        vault = Vault(cfg.vault)
        fm2, body = parse_frontmatter(vault.read(f"Jobs/{rid}.md") or "")
        from jcc.vault import render_note
        fm2["auto_resumes"] = int(fm2.get("auto_resumes") or 0) + 1
        vault.write(f"Jobs/{rid}.md", render_note(fm2, body))
        fixed.append({"at": now, "what": "A job failed for a passing reason (" + TRANSIENT.search(said).group(0) + "): " + str(fm.get("task", ""))[:80],
                      "done": "It carries on from where it stopped.", "job": rid})
    return fixed


def run(cfg, now: float | None = None, start=None, carry_on=None) -> list[dict]:
    """One round: what was found and fixed (also kept in self-heal.json)."""
    now = time.time() if now is None else now
    data = _load(cfg)
    fixed = helpers(cfg, data, now, start) + failed_jobs(cfg, now, carry_on)
    if fixed or data["gave_up"]:
        data["fixed"] = (data["fixed"] + fixed)[-50:]
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        atomic_write(_file(cfg), json.dumps(data, indent=1))
    return fixed
