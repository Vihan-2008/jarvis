"""What every agent is doing, in one list.

With several agents at work (a coding job, a planner and its builder, the assistant answering in a chat, a trial in the
Court, a pack being scanned) their owner had to open each conversation in turn to find out how each was getting on.
This gathers them: who is working, on what, what it is doing this moment, since when; what is waiting for its owner;
what is set to happen later (timers, reminders and the owner's routines); and what has just finished.

Only reads what the app already keeps. Nothing here starts, stops or changes anything.
"""
from __future__ import annotations

import re
import time

from jcc.redact import redact
from jcc.vault import parse_frontmatter

JOB = re.compile(r"\d{8}-\d{6}-[a-f0-9]{4}")
AT_WORK = ("running",)
NEEDS_OWNER = ("needs_approval",)
HELD = ("queued", "paused")
RECENT = 30 * 60               # "just finished": in the last half hour


def _short(text, most: int = 140) -> str:
    """One line, with anything secret hidden; a long one is cut at the end of a word and says so."""
    text = redact(" ".join(str(text or "").split()))
    if len(text) <= most:
        return text
    cut = text[:most - 1]
    return (cut[:cut.rfind(" ")] if " " in cut[most // 2:] else cut).rstrip(" ,;:.") + "\u2026"


def _started(rid: str) -> float | None:
    """When a request was made: its name is its date and time."""
    try:
        return time.mktime(time.strptime(rid[:15], "%Y%m%d-%H%M%S"))
    except (ValueError, OverflowError):
        return None


def _jobs(cfg, now: float, routine_chats: dict | None = None) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """The coding jobs: at work, waiting for their owner, held up, and just finished. A job that one of the owner's
    routines started says which routine (its chat is the routine's chat)."""
    from jcc import activity, live
    working, waiting, held, recent = [], [], [], []
    folder = cfg.vault / "Jobs"
    for path in sorted(folder.glob("*.md"), reverse=True)[:60] if folder.exists() else []:
        if not JOB.fullmatch(path.stem):
            continue
        try:
            fm, _ = parse_frontmatter(path.read_text("utf-8"))
        except (OSError, ValueError):
            continue                                  # a note that cannot be read this moment is left out, not fatal
        status = str(fm.get("status") or "")
        project = cfg.projects.get(str(fm.get("project_key") or ""))
        row = {"kind": "job", "id": path.stem, "who": " · ".join(str(v) for v in (fm.get("agent"), fm.get("model")) if v) or "coding agent",
               "title": _short(fm.get("task")), "project": project.name if project else "", "chat": str(fm.get("chat_id") or ""), "state": status,
               "since": _started(path.stem), "doing": ""}
        if row["chat"] and row["chat"] in (routine_chats or {}):
            row["routine"] = _short(routine_chats[row["chat"]], 80)
        if status in AT_WORK:
            try:
                steps = live.read(cfg, path.stem)["steps"]
                last = (activity.events(cfg, path.stem) or [None])[-1]
            except (OSError, ValueError):
                steps, last = [], None
            row["doing"] = _short(steps[-1]["text"] if steps else (last or {}).get("message") or "Working")
            if not fm.get("agent") and last and last.get("agent"):
                row["who"] = " · ".join(str(v) for v in (last.get("agent"), last.get("model")) if v)
            working.append(row)
        elif status in NEEDS_OWNER:
            from jcc import job_control
            asked = None if fm.get("blocked_by") else job_control.asked(cfg, path.stem)
            if asked is not None:
                # It stopped and asked its owner for something: the question is shown with a way to answer it.
                row.update(doing="Asks you: " + _short(asked["text"], 110), ask={"job": path.stem, **asked})
            else:
                row["doing"] = "Never done automatically: " + _short(fm["blocked_by"], 80) if fm.get("blocked_by") else "Waiting for your review before it is merged"
                row["review"] = not fm.get("blocked_by")       # a change to look at (and not something a job may never do by itself)
            waiting.append(row)
        elif status in HELD:
            row["doing"] = _short(fm.get("wait_reason") or fm.get("skipped") or ("Paused" if status == "paused" else "Waiting for a coding agent to be free"))
            held.append(row)
        elif status in ("done", "failed", "cancelled"):
            try:
                ended = path.stat().st_mtime
            except OSError:
                continue
            if now - ended <= RECENT:
                row.update(doing={"done": "Finished", "failed": "Did not finish", "cancelled": "Cancelled by you"}[status] +
                           (": merged" if fm.get("merged") else ""), since=ended)
                recent.append(row)
    return working, waiting, held, recent


def _assistant(turns) -> list[dict]:
    rows = []
    for turn in turns or []:
        rows.append({"kind": "assistant", "id": str(getattr(turn, "id", "")), "who": str(getattr(turn, "model", "") or "assistant"),
                     "title": _short(getattr(turn, "text", "")) or "Answering", "project": "", "chat": str(getattr(turn, "chat", "")),
                     "state": "running", "since": getattr(turn, "started", None), "doing": _short(getattr(turn, "doing", "")) or ("Speaking with you" if getattr(turn, "spoken", False) else "Thinking")})
    return rows


def _pairs(cfg) -> tuple[list[dict], list[dict]]:
    from jcc import pairing
    working, waiting = [], []
    for pair in pairing.listing(cfg):
        if pair["status"] not in ("planning", "building", "waiting", "halted"):
            continue
        project = cfg.projects.get(str(pair.get("project") or ""))
        row = {"kind": "pair", "id": pair["id"], "who": "planner " + str(pair.get("answered_by") or pair.get("planner") or "") + " with a builder",
               "title": _short(pair.get("goal")), "project": project.name if project else "", "chat": "", "state": pair["status"], "since": pair.get("created"),
               "doing": _short(pair.get("now")) or "Working", "steps": [pair.get("done", 0), pair.get("steps", 0)]}
        if isinstance(pair.get("ask"), dict):
            row["ask"] = {"job": str(pair["ask"].get("job") or ""), "text": str(pair["ask"].get("text") or ""), "mark": str(pair["ask"].get("mark") or "")}
        (working if pair["status"] in ("planning", "building") else waiting).append(row)
    return working, waiting


def _court(cfg) -> tuple[list[dict], list[dict]]:
    from jcc import court
    working, waiting = [], []
    for session in court.listing(cfg):
        if session["status"] not in ("in_session", "halted"):
            continue
        row = {"kind": "court", "id": session["id"], "who": "the Court of JARVIS", "title": _short(session.get("idea")), "project": "", "chat": "",
               "state": session["status"], "since": session.get("created"), "doing": _short(session.get("now")) or "In session"}
        (working if session["status"] == "in_session" else waiting).append(row)
    return working, waiting


def _later(cfg, now: float) -> list[dict]:
    """What is set to happen by itself: timers and reminders, the next few."""
    try:
        from jcc.reminders import Reminders
        rows = Reminders(cfg).listing()
    except Exception:  # noqa: BLE001 - the list of what is at work must not fail over a reminder that cannot be read
        return []
    return [{"kind": "timer" if row.get("text") == "Timer" else "reminder", "id": str(row.get("id") or ""), "who": "", "title": _short(row.get("text")) or "Timer",
             "project": "", "chat": "", "state": "set", "since": None, "due": row.get("due"), "doing": ""} for row in sorted(rows, key=lambda r: r.get("due") or 0)[:8]
            if (row.get("due") or 0) >= now - 5]


def _routines(cfg) -> tuple[list[dict], dict]:
    """The owner's routines that are on, soonest first, and which chat belongs to which routine."""
    try:
        from jcc import routines
        rows = [{**row, "title": _short(row["title"], 80), "who": "", "project": "", "chat": "", "since": None} for row in routines.scheduled(cfg)]
        return rows, routines.by_chat(cfg)
    except Exception:  # noqa: BLE001 - the list of what is at work must not fail over a routine that cannot be read
        return [], {}


def overview(cfg, turns=None, scan: dict | None = None, now: float | None = None) -> dict:
    """Everything that is at work, waiting, set for later or just finished. `turns`: the assistant's own answers in
    progress; `scan`: what the skills library is doing."""
    now = now or time.time()
    scheduled, routine_chats = _routines(cfg)
    working, waiting, held, recent = _jobs(cfg, now, routine_chats)
    pairs_working, pairs_waiting = _pairs(cfg)
    court_working, court_waiting = _court(cfg)
    working = _assistant(turns) + pairs_working + working + court_working
    if isinstance(scan, dict) and scan.get("status") == "working":
        working.append({"kind": "scan", "id": "skills", "who": "SkillSpector", "title": "Scanning " + _short(scan.get("source"), 80), "project": "", "chat": "",
                        "state": "running", "since": scan.get("at"), "doing": _short(scan.get("step")) or "Fetching and scanning"})
    # A builder's job of a pair is listed under its pair as well as by itself: the pair's own line says so.
    return {"at": now, "working": working, "waiting": pairs_waiting + waiting + court_waiting, "held": held, "later": _later(cfg, now), "scheduled": scheduled,
            "recent": sorted(recent, key=lambda r: r.get("since") or 0, reverse=True)[:8]}
