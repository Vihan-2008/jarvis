"""Routines: something the owner wants done again and again, at the times they chose.

"Every morning at 8, tell me what is on my calendar." "Every 2 hours, run the tests of my project and fix what fails."
A routine is a request, the project it is about (or none), whether it is answered in a chat or is a coding job in the
project, which agent should do it, and when. Each run is an ordinary message in the routine's own chat, so its whole
history is in one place.

A routine never gets more rights than a message typed by its owner. Each run is sent through the very same path as a
typed message (GuiState.send_chat), so every approval, review, limit and guard applies to it as it would to the owner's
own words. A run that needs its owner's yes simply waits for it, and shows as waiting; nothing here answers for them.

The rules this file keeps, because a timer that misfires can do the same work twice:

- A slot is fired at most once. Under a lock that other processes see too, the file is read again, the slot is written
  down and the next one is set BEFORE the run is started. Whoever ticks next finds it written down and leaves it.
- After a time when the app was off, one run is started for the latest slot that was missed, never a burst of them.
- While the last run is still going, a slot that comes due is skipped and says so: runs never pile up.
- A run that was written down but never started (the app was closed at that moment) is marked as failed. It is not
  started again by itself, because it may have started after all; its owner can press Retry.
- After 5 runs in a row have failed, the routine pauses itself and says so.

Times are local (time.localtime, time.mktime), and `now` is passed in everywhere so that tests are exact.
"""
from __future__ import annotations

import contextlib
import json
import math
import os
import re
import secrets as _rand
import threading
import time
from pathlib import Path

from jcc.lock import InstanceLock
from jcc.redact import redact
from jcc.vault import atomic_write

ID = re.compile(r"rt-\d{8}-\d{6}-[0-9a-f]{4}")
JOB = re.compile(r"\d{8}-\d{6}-[0-9a-f]{4}")
CHAT = re.compile(r"\d{8}-\d{6}-[0-9a-f]{4,12}")
CLOCK = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")

MOST = 50                    # routines kept at once
RUNS_KEPT = 30               # runs kept for each routine, newest last
FAILURES_TO_PAUSE = 5        # failed runs in a row after which a routine pauses itself
STALE_START = 120            # seconds a run may be "starting" without a job before it is taken as never started
NO_NOTE = 600                # seconds a started job may go without a job note before it is taken as failed
SHORTEST, LONGEST = 5, 10080  # minutes between runs of an "every" schedule: five minutes to a week
NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
GOING = ("starting", "running", "waiting")
NEVER_STARTED = "It did not start: the app was closed just then."
SELF_PAUSED = "Paused after 5 runs in a row failed."
SKIPPED = "Skipped: the last run is still going."

# Slots of an "every" schedule are counted from a fixed Monday midnight, local time: "every 2 hours" runs at even
# hours and "every week" on Monday at midnight, and a slot never drifts by how late a tick happened to come.
_ANCHOR = time.mktime((2000, 1, 3, 0, 0, 0, 0, 0, -1))

_lock = threading.RLock()     # threads of this process; the lock file is for other processes
_sending: set[tuple[str, float]] = set()    # runs this process is starting this moment: not "never started", only slow


class RoutineError(ValueError):
    """Something the owner is told, in a plain sentence."""


# ---------------------------------------------------------------------- schedules
def check_schedule(schedule) -> dict:
    """The schedule in its one accepted shape, or a plain sentence saying what is wrong with it."""
    if not isinstance(schedule, dict):
        raise RoutineError("Choose when it runs: every so many minutes, or every day at a time.")
    if schedule.get("kind") == "every":
        minutes = schedule.get("minutes")
        if isinstance(minutes, bool) or not isinstance(minutes, int) or not SHORTEST <= minutes <= LONGEST:
            raise RoutineError("A routine can run every 5 minutes at the most, and once a week at the least.")
        return {"kind": "every", "minutes": minutes}
    if schedule.get("kind") == "daily":
        at = schedule.get("at")
        if not isinstance(at, str) or not CLOCK.fullmatch(at):
            raise RoutineError("Give the time of day as hours and minutes, like 08:00 or 17:30.")
        days = schedule.get("days") or []
        if not isinstance(days, list) or not all(isinstance(d, int) and not isinstance(d, bool) and 0 <= d <= 6 for d in days):
            raise RoutineError("Those are not days of the week.")
        days = sorted(set(days))
        return {"kind": "daily", "at": at, "days": [] if len(days) == 7 else days}
    raise RoutineError("Choose when it runs: every so many minutes, or every day at a time.")


def next_slot(schedule: dict, after: float) -> float:
    """The first time the schedule comes round after `after` (never at `after` itself)."""
    schedule = check_schedule(schedule)
    if schedule["kind"] == "every":
        step = schedule["minutes"] * 60
        return _ANCHOR + (math.floor((after - _ANCHOR) / step) + 1) * step
    hour, minute = (int(part) for part in schedule["at"].split(":"))
    day = time.localtime(after)
    for ahead in range(9):
        # mktime puts a day past the end of a month into the next one, and works out summer time by itself (-1).
        at = time.mktime((day.tm_year, day.tm_mon, day.tm_mday + ahead, hour, minute, 0, 0, 0, -1))
        if at > after and (not schedule["days"] or time.localtime(at).tm_wday in schedule["days"]):
            return at
    raise RoutineError("That schedule never comes round.")      # (not reached: a week always holds a chosen day)


def _latest(schedule: dict, due: float, now: float) -> float:
    """The latest slot at or before `now`, starting from the slot `due` that came due first. A long time off is a few
    sums for an "every" schedule, and at most one step a day for a daily one."""
    if schedule["kind"] == "every":
        step = schedule["minutes"] * 60
        return due + math.floor((now - due) / step) * step
    slot = due
    for _ in range(4000):
        following = next_slot(schedule, slot)
        if following > now:
            break
        slot = following
    return slot


def _plural(day: int) -> str:
    return NAMES[day] + "s"


def in_words(schedule) -> str:
    """The schedule said plainly: "Every 2 hours", "Every day at 08:00", "Mondays and Thursdays at 17:30"."""
    try:
        schedule = check_schedule(schedule)
    except RoutineError:
        return "Not set"
    if schedule["kind"] == "every":
        minutes = schedule["minutes"]
        if minutes == 10080:
            return "Every week"
        for size, one, many in ((1440, "day", "days"), (60, "hour", "hours"), (1, "minute", "minutes")):
            if minutes % size == 0:
                count = minutes // size
                return "Every " + one if count == 1 else f"Every {count} {many}"
    days, at = schedule["days"], schedule["at"]
    if not days:
        return "Every day at " + at
    if days == [0, 1, 2, 3, 4]:
        return "Weekdays at " + at
    if days == [5, 6]:
        return "Weekends at " + at
    names = [_plural(d) for d in days]
    joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return joined + " at " + at


# ---------------------------------------------------------------------- the file
def _folder(cfg) -> Path:
    return cfg.state_dir / "routines"


def _path(cfg) -> Path:
    return _folder(cfg) / "routines.json"


@contextlib.contextmanager
def _held(cfg, wait: float = 5.0):
    """Hold the routines for a moment, against other threads of this app and against another copy of it. With
    `wait` 0, whoever finds them held does not wait: someone else is doing the same work right now."""
    if not (_lock.acquire(timeout=wait) if wait > 0 else _lock.acquire(blocking=False)):
        raise RoutineError("The routines are being changed right now. Try again in a moment.")
    try:
        lock, until = InstanceLock(_folder(cfg) / "tick.lock"), time.monotonic() + wait
        while not lock.acquire():
            if time.monotonic() >= until:
                raise RoutineError("The routines are being changed right now. Try again in a moment.")
            time.sleep(0.05)
        try:
            yield
        finally:
            lock.release()
    finally:
        _lock.release()


def _load(cfg, mend: bool = True) -> list[dict]:
    """The routines as saved. A file that cannot be understood is put aside (kept, under another name) and the app
    goes on with none, rather than stop every routine over it. Only reads (`mend` False) leave even that file alone."""
    path = _path(cfg)
    try:
        text = path.read_text("utf-8")
    except FileNotFoundError:
        return []
    except OSError:
        raise RoutineError("The routines cannot be read this moment. Try again in a moment.") from None
    try:
        data = json.loads(text)
        rows = data["routines"]
        if not isinstance(rows, list):
            raise TypeError
    except (ValueError, TypeError, KeyError):
        if mend:
            with contextlib.suppress(OSError):
                os.replace(path, path.with_name("routines.damaged.json"))
        return []
    return [r for r in rows if isinstance(r, dict) and isinstance(r.get("id"), str) and ID.fullmatch(r["id"])][:MOST]


def _store(cfg, routines: list[dict]) -> None:
    atomic_write(_path(cfg), json.dumps({"routines": routines}, ensure_ascii=False))


def _find(routines: list[dict], ident) -> dict:
    # The id is checked for its exact shape before it is looked for: it comes from the page.
    if not isinstance(ident, str) or not ID.fullmatch(ident):
        raise RoutineError("That is not a routine of this app.")
    for routine in routines:
        if routine["id"] == ident:
            return routine
    raise RoutineError("There is no such routine. It may have been removed.")


# ---------------------------------------------------------------------- runs
def _record(routine: dict, run: dict) -> dict:
    """Add a run, keep the latest few, and keep `last` the latest."""
    routine["runs"] = ([r for r in routine.get("runs") or [] if isinstance(r, dict)] + [run])[-RUNS_KEPT:]
    routine["last"] = run
    return run


def _current(routine: dict) -> dict | None:
    """The latest run that was really started (a skipped slot is not a run of its own)."""
    for run in reversed(routine.get("runs") or []):
        if isinstance(run, dict) and run.get("status") != "skipped":
            return run
    return None


def _never_started(routine: dict, run: dict, now: float) -> bool:
    return (run.get("status") == "starting" and not JOB.fullmatch(str(run.get("job") or "")) and now - float(run.get("started") or 0) > STALE_START
            and (routine.get("id"), run.get("slot")) not in _sending)


def run_state(cfg, routine: dict, run: dict, now: float) -> str:
    """How one run is doing, from its job note as the security check reads its fix: starting, running, waiting (for
    its owner: a review or a question), failed, cancelled, done, or skipped."""
    status = str(run.get("status") or "")
    if status in ("skipped", "failed", "cancelled"):
        return status
    job = str(run.get("job") or "")
    if not JOB.fullmatch(job):
        return "failed" if _never_started(routine, run, now) else "starting"
    from jcc import receipts
    from jcc.vault import Vault, parse_frontmatter
    vault = Vault(cfg.vault)
    text = vault.read(f"Jobs/{job}.md")
    if not text:
        # No job was made of it (a request answered at once, or not yet written): what its receipt says, if anything.
        loaded = receipts.load(vault, job)
        said = str((loaded or ({}, ""))[0].get("status") or "")
        if said in ("done", "failed", "cancelled"):
            return said
        return "starting" if now - float(run.get("started") or 0) < NO_NOTE else "failed"
    said = str(parse_frontmatter(text)[0].get("status") or "")
    if said in ("needs_approval", "paused"):
        return "waiting"
    if said in ("done", "failed", "cancelled"):
        return said
    return "running"


def _going(cfg, routine: dict, now: float) -> bool:
    run = _current(routine)
    return bool(run) and run_state(cfg, routine, run, now) in GOING


def _failing(cfg, routine: dict, now: float) -> bool:
    """Whether the last few runs since the routine was last resumed have all failed."""
    since = float(routine.get("resumed") or 0)
    runs = [r for r in routine.get("runs") or [] if isinstance(r, dict) and r.get("status") != "skipped" and float(r.get("started") or 0) >= since]
    last = runs[-FAILURES_TO_PAUSE:]
    return len(last) == FAILURES_TO_PAUSE and all(run_state(cfg, routine, r, now) == "failed" for r in last)


def _pause_failing(routine: dict) -> None:
    routine.update(enabled=False, next=None)
    if isinstance(routine.get("last"), dict):
        routine["last"]["note"] = SELF_PAUSED
        if routine.get("runs"):
            routine["runs"][-1] = routine["last"]


def _recover(routine: dict, now: float) -> None:
    """A run written down but never started (the app was closed at that very moment) is marked as failed. It is not
    started again by itself: it may have started after all, and doing a thing twice is worse than once too few."""
    for run in routine.get("runs") or []:
        if isinstance(run, dict) and _never_started(routine, run, now):
            run.update(status="failed", note=NEVER_STARTED)
    runs = routine.get("runs") or []
    if runs:
        routine["last"] = runs[-1]


def _said(problem: BaseException) -> str:
    """Why a run could not be started, in a sentence, with anything secret hidden."""
    words = " ".join(str(problem).split()) if isinstance(problem, ValueError) else "something went wrong (" + type(problem).__name__ + ")"
    return ("It could not be started: " + redact(words or "no reason was given"))[:300]


def _begin(routine: dict, slot: float, now: float, manual: bool = False) -> dict:
    run = {"slot": slot, "started": now, "job": "", "status": "starting", "note": ""}
    if manual:
        run["manual"] = True
    _record(routine, run)
    _sending.add((routine["id"], slot))
    return dict(routine)


def _fire(cfg, routine: dict, slot: float, send, now: float) -> None:
    """Start the run that was written down, and write down how that went. `routine` is as it was when the slot was
    written down; the file is read again to write the result."""
    key = (routine["id"], slot)
    try:
        chat = ""
        try:
            got = send(dict(routine))
            job = str((got or {}).get("job") or "")
            chat = str((got or {}).get("chat") or "")
            if not JOB.fullmatch(job):
                raise RoutineError("no job was made of it.")
            outcome = {"job": job, "status": "started", "note": ""}
        except Exception as problem:  # noqa: BLE001 - whatever went wrong, it is written down and the routine carries on
            outcome = {"status": "failed", "note": _said(problem)}
        with contextlib.suppress(RoutineError), _held(cfg, wait=30):
            routines = _load(cfg)
            saved = next((r for r in routines if r["id"] == routine["id"]), None)
            run = next((r for r in (saved or {}).get("runs") or [] if isinstance(r, dict) and r.get("slot") == slot), None)
            if saved is None or run is None:
                return                                   # (removed meanwhile: nothing to write down)
            cancelled = run.get("status") == "cancelled"
            run.update({k: v for k, v in outcome.items() if not (cancelled and k == "status")})
            if cancelled and outcome.get("job"):
                _stop_quietly(cfg, outcome["job"])       # its owner cancelled it while it was being started
            if CHAT.fullmatch(chat) and saved.get("chat") != chat:
                saved["chat"] = chat
            saved["last"] = saved["runs"][-1]
            if outcome["status"] == "failed" and _failing(cfg, saved, now):
                _pause_failing(saved)
            _store(cfg, routines)
    finally:
        _sending.discard(key)


def _stop_quietly(cfg, job: str) -> None:
    from jcc import job_control
    with contextlib.suppress(ValueError, OSError):
        job_control.apply(cfg, job, "cancel")


# ---------------------------------------------------------------------- the ticker
def _due(cfg, routine: dict, now: float) -> float | None:
    """Whether a slot of this routine is due now. If so, it is written down (and `next` moved on) and its slot given
    back; a slot that cannot be run (the last run is still going) is written down as skipped."""
    _recover(routine, now)
    due = routine.get("next")
    if not routine.get("enabled") or due is None or float(due) > now:
        return None
    if _failing(cfg, routine, now):
        _pause_failing(routine)
        return None
    schedule = check_schedule(routine.get("schedule"))
    slot = _latest(schedule, float(due), now)
    routine["next"] = next_slot(schedule, now)            # (only the latest missed slot is run: never a burst)
    if any(isinstance(r, dict) and r.get("slot") == slot for r in routine.get("runs") or []):
        return None                                       # already written down: whoever wrote it starts it
    if _going(cfg, routine, now):
        _record(routine, {"slot": slot, "started": now, "job": "", "status": "skipped", "note": SKIPPED})
        return None
    _begin(routine, slot, now)
    return slot


def tick(cfg, send, now: float | None = None) -> list[str]:
    """Start a run of each routine that is due. Called every few seconds by the app; `send(routine)` starts a run and
    gives back {"job", "chat"}. Gives back the ids of the routines a run was started for."""
    now = time.time() if now is None else now
    firing = []
    try:
        with _held(cfg, wait=0):
            routines = _load(cfg)
            before = json.dumps(routines, sort_keys=True)
            for routine in routines:
                try:
                    slot = _due(cfg, routine, now)
                except (ValueError, TypeError, KeyError, OverflowError):
                    continue                              # one routine that cannot be understood does not stop the others
                if slot is not None:
                    firing.append((dict(routine), slot))
            if json.dumps(routines, sort_keys=True) != before:
                _store(cfg, routines)
    except RoutineError:
        return []                                         # someone else is ticking right now, or the file is busy
    for routine, slot in firing:
        _fire(cfg, routine, slot, send, now)
    return [routine["id"] for routine, _ in firing]


# ---------------------------------------------------------------------- what the owner does
def _text(value, shortest: int, longest: int, what: str) -> str:
    if not isinstance(value, str):
        raise RoutineError(f"Give the {what}.")
    value = value.strip()
    if not shortest <= len(value) <= longest:
        raise RoutineError(f"The {what} must be {shortest} to {longest:,} characters.")
    return value


def _checked(cfg, given: dict) -> dict:
    name = re.sub(r"[\x00-\x1f\x7f]+", " ", _text(given.get("name"), 1, 80, "name"))
    what = redact(_text(given.get("what"), 3, 4000, "request"))
    project = given.get("project") or ""
    if not isinstance(project, str) or (project and project not in cfg.projects):
        raise RoutineError("That is not one of your projects.")
    mode = given.get("mode") or "ask"
    if mode not in ("ask", "build"):
        raise RoutineError("Choose whether it answers you in a chat or changes code in a project.")
    if mode == "build" and not project:
        raise RoutineError("Changing code needs a project. Choose one, or have it answer you in a chat.")
    agent = given.get("agent") or "auto"
    usable = [n for n, a in cfg.agents.items() if getattr(a, "enabled", True)]
    if agent != "auto" and agent not in usable:
        raise RoutineError("Choose Auto or one of your agents that is turned on.")
    return {"name": redact(name), "what": what, "project": project, "mode": mode, "agent": agent, "schedule": check_schedule(given.get("schedule"))}


def _new_id(routines: list[dict], now: float) -> str:
    taken = {r["id"] for r in routines}
    while True:
        ident = "rt-" + time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + "-" + _rand.token_hex(2)
        if ident not in taken:
            return ident


def save(cfg, given, now: float | None = None) -> dict:
    """Make a routine, or change one (`given["id"]`). Changing when it runs works out its next run afresh."""
    now = time.time() if now is None else now
    if not isinstance(given, dict):
        raise RoutineError("Say what the routine should do and when.")
    fields = _checked(cfg, given)
    with _held(cfg):
        routines = _load(cfg)
        if given.get("id"):
            routine = _find(routines, given["id"])
            moved = routine.get("schedule") != fields["schedule"]
            routine.update(fields)
            if moved and routine.get("enabled"):
                routine["next"] = next_slot(fields["schedule"], now)
        else:
            if len(routines) >= MOST:
                raise RoutineError(f"You have {MOST} routines, which is as many as JARVIS keeps. Remove one first.")
            routine = {"id": _new_id(routines, now), **fields, "enabled": True, "created": now, "next": next_slot(fields["schedule"], now),
                       "chat": "", "last": None, "runs": []}
            routines.append(routine)
        _store(cfg, routines)
        return dict(routine)


def _change(cfg, ident, how) -> dict:
    with _held(cfg):
        routines = _load(cfg)
        routine = _find(routines, ident)
        how(routine, routines)
        _store(cfg, routines)
        return dict(routine)


def pause(cfg, ident) -> dict:
    """No more runs until it is resumed. A run that is going goes on (Cancel stops it)."""
    return _change(cfg, ident, lambda r, _: r.update(enabled=False, next=None))


def resume(cfg, ident, now: float | None = None) -> dict:
    """Runs again from the next slot to come: nothing is made up for the time it was paused, and failures from before
    it was paused are not counted against it again."""
    now = time.time() if now is None else now
    return _change(cfg, ident, lambda r, _: r.update(enabled=True, next=next_slot(check_schedule(r.get("schedule")), now), resumed=now))


def remove(cfg, ident) -> None:
    """Remove the routine. Its chat and the jobs it started stay, as any chat does."""
    _change(cfg, ident, lambda r, routines: routines.remove(r))


def _start_now(cfg, ident, send, now: float, allowed) -> dict:
    with _held(cfg):
        routines = _load(cfg)
        routine = _find(routines, ident)
        _recover(routine, now)
        if _going(cfg, routine, now):
            raise RoutineError("The last run is still going. Wait for it to end, or cancel it.")
        allowed(routine)
        snapshot = _begin(routine, now, now, manual=True)
        _store(cfg, routines)
    _fire(cfg, snapshot, now, send, now)
    return get(cfg, ident)


def run_now(cfg, ident, send, now: float | None = None) -> dict:
    """One run at once (not while the last one is still going). When it runs next is not changed."""
    return _start_now(cfg, ident, send, time.time() if now is None else now, lambda routine: None)


def retry(cfg, ident, send, now: float | None = None) -> dict:
    """Run again after a run that failed, was cancelled or did not start. It is a new run of its own."""
    now = time.time() if now is None else now

    def allowed(routine):
        run = _current(routine)
        if not run or run_state(cfg, routine, run, now) not in ("failed", "cancelled"):
            raise RoutineError("Retry is for a run that failed, was cancelled or did not start.")
    return _start_now(cfg, ident, send, now, allowed)


def cancel(cfg, ident, stop=None, now: float | None = None) -> dict:
    """Stop the run that is going, through the job's own controls (`stop(cfg, job, "cancel")`). A job that has ended
    by itself meanwhile cannot be controlled any more: then it is said that it had already ended."""
    now = time.time() if now is None else now
    if stop is None:
        from jcc.job_control import apply as stop
    with _held(cfg):
        routines = _load(cfg)
        routine = _find(routines, ident)
        run = _current(routine)
        if not run or run_state(cfg, routine, run, now) not in GOING:
            raise RoutineError("No run of this routine is going.")
        job = str(run.get("job") or "")
        if JOB.fullmatch(job):
            try:
                stop(cfg, job, "cancel")
            except ValueError as problem:
                if "cannot be controlled" not in str(problem) and "not found" not in str(problem):
                    raise RoutineError(str(problem)) from None
                # It ended by itself a moment ago: its own note says how, and that is what is shown.
                return {**shown(cfg, routine, now), "said": "It had already ended."}
        run.update(status="cancelled", note="Cancelled by you.")    # (one still being started is stopped as soon as its job is known)
        routine["last"] = routine["runs"][-1]
        _store(cfg, routines)
        return {**shown(cfg, routine, now), "said": "The run was cancelled."}


# ---------------------------------------------------------------------- what the page shows
def _word(cfg, routine: dict, now: float) -> str:
    """The routine's state in one word for the page."""
    run = _current(routine)
    state = run_state(cfg, routine, run, now) if run else ""
    if state in ("starting", "running"):
        return "running"
    if state == "waiting":
        return "waiting"
    if not routine.get("enabled"):
        return "paused"
    if state in ("failed", "cancelled"):
        return "failed"
    return "done" if state == "done" else "scheduled"


def shown(cfg, routine: dict, now: float) -> dict:
    """A routine as the page shows it: with its state, its schedule in words, and each run's state."""
    runs = [{**r, "state": run_state(cfg, routine, r, now)} for r in routine.get("runs") or [] if isinstance(r, dict)]
    current = next((r for r in reversed(runs) if r.get("status") != "skipped"), None)
    state = _word(cfg, routine, now)
    return {**routine, "runs": runs, "last": runs[-1] if runs else None, "state": state, "in_words": in_words(routine.get("schedule")),
            "can_cancel": state in ("running", "waiting"), "can_retry": bool(current) and current["state"] in ("failed", "cancelled") and state not in ("running", "waiting")}


def get(cfg, ident, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    with _lock:
        return shown(cfg, _find(_load(cfg, mend=False), ident), now)


def listing(cfg, now: float | None = None) -> list[dict]:
    """Every routine, as the page shows it. A file that cannot be read this moment shows none, and says nothing worse."""
    now = time.time() if now is None else now
    try:
        routines = _load(cfg, mend=False)
    except RoutineError:
        return []
    return [shown(cfg, r, now) for r in routines]


def scheduled(cfg) -> list[dict]:
    """The rows of the Agents panel's "Scheduled" part: each routine that is on, soonest first."""
    rows = []
    for routine in listing(cfg):
        if routine.get("enabled") and routine.get("next") is not None:
            rows.append({"kind": "routine", "id": routine["id"], "title": routine.get("name") or "Routine", "doing": routine["in_words"],
                         "next": routine["next"], "state": "scheduled"})
    return sorted(rows, key=lambda r: r["next"])


def by_chat(cfg) -> dict[str, str]:
    """Which routine each routine chat belongs to: its chat id to its name."""
    try:
        return {r["chat"]: str(r.get("name") or "") for r in _load(cfg, mend=False) if isinstance(r.get("chat"), str) and r["chat"]}
    except RoutineError:
        return {}
