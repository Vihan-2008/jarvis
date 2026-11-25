"""JARVIS's own way into Outlook on this PC, for work and school accounts too: no admin approval, no password, no key.

Classic Outlook lets programs on the same PC use the mail it already has, through its object model. JARVIS reaches it
through one fixed PowerShell script (outlook_bridge.ps1) that does a short list of things and nothing else: list the
accounts, list or search a folder, read one message, read the calendar, send one new email. The model never writes
PowerShell, a filter or an item's ID: it asks for one of those things, and this module builds the request.

The new Outlook gives other apps no way in. It shows the same mailbox as classic Outlook, so classic Outlook does the
work in the background while the owner keeps using the new one. Where only the new Outlook is installed, JARVIS writes
the email in it as a draft and sends it after the owner's yes (jcc/mailer.py), and cannot read mail there.

Nothing here runs until the owner switches it on in JARVIS's own settings, and then only for the accounts they ticked:
the assistant can neither switch it on nor tick an account. Every send is asked about. Mail never goes into a log or a
file: what is kept is whether it is on, which accounts, what Outlook last said went wrong (a fixed code), and when.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from jcc.vault import atomic_write, read_json

BRIDGE = Path(__file__).with_name("outlook_bridge.ps1")
STATE = "outlook.json"
READ_WAIT, START_WAIT, SEND_WAIT = 20.0, 45.0, 60.0       # seconds: a read; anything while Outlook may be starting; a send
COLD = 25.0                                                # more for a send that has to start Outlook first
SENT_WAIT = 35                                             # how long the bridge watches Sent Items after Send
MOST_LISTED, MOST_BODY, MOST_RESULT, PREVIEW = 25, 12000, 30000, 200
CALENDAR_DAYS, SEARCH_DAYS = 31, 30
ADDRESS = re.compile(r"[^@\s,;<>\"']+@[^@\s,;<>\"']+\.[^@\s,;<>\"']+")
FOLDERS = {"inbox": "Inbox", "sent": "Sent Items", "drafts": "Drafts"}

OFF = "Outlook is not switched on in JARVIS. Only the user can switch it on: Settings, Email, Outlook on this PC. Nothing was read."
BUSY = "Outlook is busy with another request. Try again in a moment."
SLOW = ("Outlook did not answer in time. It may be asking something in its own window (which profile to use, a sign-in, or whether "
        "to let a program use it): tell the user to open classic Outlook and answer it, then try again.")
PROBLEMS = {
    "no-classic": "Classic Outlook is not installed on this PC, so JARVIS cannot reach Outlook.",
    "blocked": "This PC does not let JARVIS talk to Outlook: the organisation's settings stop it. JARVIS cannot change that.",
    "start-failed": "Outlook could not be started. Tell the user to open classic Outlook once and see whether it is asking something.",
    "not-allowed": "That account is not one the user let JARVIS use.",
    "no-account": "That account is no longer in Outlook on this PC.",
    "no-answer": SLOW,
    "bad-recipient": "Outlook did not recognise one of the addresses it was to go to.",
    "failed": "Outlook could not do that.",
    "unknown": "JARVIS asked Outlook for something it does not know.",
}
_lock = threading.Lock()
_handles: dict[str, tuple[str, str, str]] = {}           # "m3" -> (store, entry, account): the model never sees an item's real ID
_count = [0]


class OutlookError(ValueError):
    pass


# ------------------------------------------------------------------ the owner's choices (switched on from JARVIS's settings only)
def settings(cfg) -> dict:
    saved = read_json(cfg.state_dir / STATE, {})
    saved = saved if isinstance(saved, dict) else {}
    found = [{"address": str(row.get("address", "")).lower()[:200], "name": str(row.get("name", ""))[:120]}
             for row in saved.get("found") or [] if isinstance(row, dict) and ADDRESS.fullmatch(str(row.get("address", "")))]
    ticked = [str(a).lower() for a in saved.get("accounts") or [] if ADDRESS.fullmatch(str(a))]
    last = saved.get("last") if isinstance(saved.get("last"), dict) else {}
    return {"on": saved.get("on") is True, "accounts": ticked, "found": found,
            "last": {"problem": str(last.get("problem") or "")[:40], "at": last.get("at") or 0}}


def ticked(cfg) -> list[str]:
    """The accounts JARVIS may use now: none while Outlook is switched off."""
    saved = settings(cfg)
    return saved["accounts"] if saved["on"] else []


def _save(cfg, **changes) -> dict:
    current = {**settings(cfg), **changes}
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(cfg.state_dir / STATE, json.dumps(current))
    return current


def _note(cfg, problem: str = "") -> None:
    """What Outlook last said went wrong, as a fixed code (never its words, which could hold mail)."""
    if (cfg.state_dir / STATE).exists():
        _save(cfg, last={"problem": problem if problem in PROBLEMS else ("failed" if problem else ""), "at": time.time()})


def switch(cfg, on: bool, run=None) -> dict:
    """The owner switches Outlook on or off (JARVIS's settings, Email). Switching on asks Outlook which accounts it has:
    one account is ticked at once; with several, none are ticked until the owner chooses."""
    if on is not True:
        _save(cfg, on=False)
        return {**public(cfg), "message": "Switched off. JARVIS no longer touches Outlook."}
    found = _accounts_of(_checked(_ask({"op": "status"}, run, START_WAIT, cfg)))
    if not found:
        _save(cfg, on=False, found=[], accounts=[])
        raise OutlookError("Classic Outlook has no account yet. Open it once, add your account, then switch this on again.")
    addresses = [row["address"] for row in found]
    keep = [a for a in settings(cfg)["accounts"] if a in addresses]
    _save(cfg, on=True, found=found, accounts=keep or (addresses if len(addresses) == 1 else []))
    return public(cfg)


def choose_accounts(cfg, accounts) -> dict:
    """The owner ticks the accounts JARVIS may read and send from: only accounts Outlook itself has."""
    saved = settings(cfg)
    known = {row["address"] for row in saved["found"]}
    wanted = [str(a).strip().lower() for a in (accounts or []) if isinstance(a, str)]
    if any(a not in known for a in wanted):
        raise OutlookError("That account is not in Outlook on this PC. Press Check to look again.")
    _save(cfg, accounts=sorted(set(wanted), key=wanted.index))
    return public(cfg)


def public(cfg) -> dict:
    """What the settings page shows: never anything from inside the mailbox."""
    saved = settings(cfg)
    return {"on": saved["on"], "accounts": saved["accounts"], "found": saved["found"]}


def check(cfg, run=None) -> dict:
    """Ask Outlook which accounts it has, now (the Check button)."""
    try:
        found = _accounts_of(_checked(_ask({"op": "status"}, run, START_WAIT, cfg)))
    except OutlookError as problem:
        return {"ok": False, "status": str(problem)[:300]}
    if (cfg.state_dir / STATE).exists():
        _save(cfg, found=found)
    if not found:
        return {"ok": False, "status": "Outlook answered, but has no account yet. Open classic Outlook and add your account."}
    gone = [a for a in ticked(cfg) if a not in {row["address"] for row in found}]
    if gone:
        return {"ok": False, "status": f"{gone[0]} is no longer in Outlook. Add it back in classic Outlook, or choose another account in "
                                       "Settings › Email."}
    return {"ok": True, "status": f"Outlook answered · {len(found)} account{'s' if len(found) != 1 else ''} found"}


def _accounts_of(answer: dict) -> list[dict]:
    rows = []
    for row in answer.get("accounts") or []:
        address = str((row or {}).get("address", "")).strip().lower()
        if ADDRESS.fullmatch(address) and address not in {r["address"] for r in rows}:
            rows.append({"address": address[:200], "name": " ".join(str(row.get("name", "")).split())[:120]})
    return rows[:20]


# ------------------------------------------------------------------ what is on this PC (the registry only: Outlook is never started for this)
def detect() -> dict:
    from jcc import system
    if system.kind() != "windows":
        return {"windows": False}
    import winreg

    def subkeys(hive, path):
        try:
            with winreg.OpenKey(hive, path) as key:
                return [winreg.EnumKey(key, i) for i in range(winreg.QueryInfoKey(key)[0])]
        except OSError:
            return None

    def value(hive, path, name):
        try:
            with winreg.OpenKey(hive, path) as key:
                return winreg.QueryValueEx(key, name)[0]
        except OSError:
            return None

    app_path = r"Software\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE"
    classic = subkeys(winreg.HKEY_CLASSES_ROOT, r"Outlook.Application\CLSID") is not None and any(
        subkeys(hive, app_path) is not None for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER))
    office = r"Software\Microsoft\Office\16.0\Outlook"
    accounts = any(subkeys(winreg.HKEY_CURRENT_USER, office + "\\Profiles\\" + name + r"\9375CFF0413111d3B88A00104B2A6676")
                   for name in subkeys(winreg.HKEY_CURRENT_USER, office + r"\Profiles") or [])
    packages = subkeys(winreg.HKEY_CURRENT_USER, r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages") or []
    new = any(name.startswith("Microsoft.OutlookForWindows_") for name in packages) or \
        os.path.exists(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps", "olk.exe"))
    switched = value(winreg.HKEY_CURRENT_USER, office + r"\Preferences", "UseNewOutlook") == 1
    return {"windows": True, "classic": classic, "new": new, "accounts": accounts, "switched": switched}


NAME = "Outlook on this PC"
ABOUT = ("For work and school accounts. Reads your mail and calendar and sends email through classic Outlook on this PC. It uses the "
         "account already signed in there, so it needs no password, no key and no admin approval.")
ON_DETAIL = ("JARVIS uses only these accounts and asks you before every send. It works through classic Outlook in the background, "
             "so you can keep using the new Outlook.")
BYPASS_DETAIL = ("JARVIS uses only these accounts. Permissions are set to Bypass, so it sends without asking you first. It works through "
                 "classic Outlook in the background, so you can keep using the new Outlook.")
INSTALL = "Install classic Outlook (it comes with Microsoft 365) and add your account to it."


def _on_detail(cfg) -> str:
    """What the card says once Outlook is on: true to how much the owner chose to be asked."""
    try:
        from jcc import assistant
        bypass = assistant.settings(cfg).get("ask") == "bypass"
    except Exception:  # noqa: BLE001 - (the card never fails over this)
        bypass = False
    return BYPASS_DETAIL if bypass else ON_DETAIL


def card(cfg, seen: dict | None = None) -> dict | None:
    """The Outlook line in Connections, from the registry and the saved choices only. None off Windows."""
    seen = detect() if seen is None else seen
    if not seen.get("windows"):
        return None
    item = {"id": "outlook", "group": "hands", "name": NAME, "about": ABOUT}
    if not seen.get("classic"):
        if seen.get("new"):
            return {**item, "state": "off", "status": "Only the new Outlook is on this PC",
                    "detail": "The new Outlook gives other apps no way in, so JARVIS cannot read mail there. It can still write an email in it "
                              "for you.",
                    "how": "To let JARVIS read your mail and calendar, install classic Outlook (it comes with Microsoft 365) and add your account "
                           "to it. You can keep using the new Outlook.",
                    "how_here": "The new Outlook gives other apps no way in, so JARVIS cannot read mail there. To use this, install classic "
                                "Outlook (it comes with Microsoft 365) and add your account to it. You can keep using the new Outlook."}
        return {**item, "state": "off", "status": "Outlook is not installed on this PC", "how_here": INSTALL}
    saved = settings(cfg)
    if not saved["on"]:
        if not seen.get("accounts"):
            return {**item, "state": "off", "status": "Classic Outlook has no account yet",
                    "how": "Open classic Outlook once and add your work or school account. Then come back here.", "open": "email"}
        return {**item, "state": "off", "status": "Not switched on", "detail": "JARVIS does not touch Outlook until you switch it on.", "open": "email"}
    on = {**item, "open": "email", "check": True}
    if seen.get("switched"):
        return {**on, "state": "problem", "status": "Outlook is set to open the new Outlook",
                "how": "Open \"Outlook (classic)\" from the Start menu, or turn off the New Outlook switch. Then press Check."}
    if not saved["accounts"]:
        return {**on, "state": "problem", "status": "No account chosen", "how": "Press Change and choose the account JARVIS may use.",
                "how_here": "JARVIS does not use Outlook until you switch on an account above."}       # (how_here: on the Email settings page)
    problem = saved["last"]["problem"]
    known = {row["address"] for row in saved["found"]}
    gone = [a for a in saved["accounts"] if known and a not in known]
    if problem in ("no-answer", "start-failed"):
        return {**on, "state": "problem", "status": "Outlook did not answer",
                "how": "Open classic Outlook and see if it is asking you something: which profile to use, a sign-in, or whether to let a "
                       "program use it. Answer it, then press Check."}
    if problem == "blocked":
        return {**on, "state": "problem", "status": "This PC does not let JARVIS talk to Outlook",
                "how": "Your organisation's settings stop it. JARVIS cannot change that."}
    if gone or problem == "no-account":
        who = gone[0] if gone else "An account"
        return {**on, "state": "problem", "status": f"{who} is no longer in Outlook",
                "how": "Add it back in classic Outlook, or press Change and choose another account.",
                "how_here": "Add it back in classic Outlook, or switch on another account above."}
    status = "On · " + (saved["accounts"][0] if len(saved["accounts"]) == 1 else f"{len(saved['accounts'])} accounts")
    return {**on, "state": "ok", "status": status, "detail": _on_detail(cfg)}


# ------------------------------------------------------------------ talking to Outlook (one request at a time)
_POLICY = re.compile(r"execution polic|running scripts is disabled|AuthorizationManager|blocked by group policy|application control", re.I)


def _powershell(argv: list[str], text: str, timeout: float) -> str:
    done = subprocess.run(argv, input=text, capture_output=True, text=True, encoding="ascii", errors="replace", timeout=timeout,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if not (done.stdout or "").strip() and _POLICY.search(done.stderr or ""):
        # (the PC's own rules stop the bridge from running at all: only its error, never anything from Outlook, is looked at)
        return base64.b64encode(json.dumps({"ok": False, "problem": "blocked"}).encode()).decode()
    return done.stdout or ""


def _lines(text) -> list[dict]:
    if isinstance(text, bytes):
        text = text.decode("ascii", "replace")
    out = []
    for line in str(text or "").splitlines():
        try:
            value = json.loads(base64.b64decode(line.strip(), validate=True).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(value, dict):
            out.append(value)
    return out


def _ask(request: dict, run=None, timeout: float = READ_WAIT, cfg=None, ping: bool = False) -> dict:
    """One request to classic Outlook through the bridge. The request goes in on standard input, never on the command line.
    Returns the bridge's answer (with "stage" set when a send had begun); raises OutlookError."""
    from jcc import system
    if run is None and request.get("op") != "ping" and os.environ.get("JCC_NO_SCREEN"):
        raise OutlookError("Outlook is not reached from tests and previews.")      # (as the real screen is not: see jcc/assistant.py look)
    if run is None and system.kind() != "windows":
        raise OutlookError("Outlook on this PC is reached on Windows only.")
    if not _lock.acquire(blocking=False):
        raise OutlookError(BUSY)
    began, stage, problem, answer = time.time(), "", "", {}
    try:
        if run is None and request.get("op") != "ping" and not _running():
            # Outlook is not open, so the bridge starts it (without a window) first: usual when the owner uses the new Outlook.
            timeout = timeout + COLD if request.get("op") == "send" else max(timeout, START_WAIT)
        argv = ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(BRIDGE)]
        payload = base64.b64encode(json.dumps(request, ensure_ascii=False).encode("utf-8")).decode("ascii")
        try:
            out = (run or _powershell)(argv, payload, timeout)
        except subprocess.TimeoutExpired as late:
            stage = "sending" if any(row.get("stage") == "sending" for row in _lines(late.output)) else ""
            problem = "no-answer"
            return {"ok": False, "problem": "no-answer", "stage": stage}
        except OSError:
            problem = "failed"
            raise OutlookError("PowerShell could not be started, so Outlook could not be reached.") from None
        rows = _lines(out)
        stage = "sending" if any(row.get("stage") == "sending" for row in rows) else ""
        answer = next((row for row in reversed(rows) if "ok" in row), None)
        if answer is None:
            problem = "failed"
            return {"ok": False, "problem": "failed", "stage": stage}
        if answer.get("ok") is not True:
            problem = str(answer.get("problem") or "failed")
        return {**answer, "stage": stage}
    finally:
        _lock.release()
        if cfg is not None and not ping:
            _note(cfg, problem)
            rows = (answer or {}).get("messages") or (answer or {}).get("events") or (answer or {}).get("accounts")
            _log(cfg, str(request.get("op", "")), str(request.get("account", "")), problem or "ok", time.time() - began,
                 len(rows) if isinstance(rows, list) else None)


def _running() -> bool:
    """Is classic Outlook open right now? (Only its process name is looked at.)"""
    try:
        done = subprocess.run(["tasklist", "/FI", "IMAGENAME eq OUTLOOK.EXE", "/NH", "/FO", "CSV"], capture_output=True, text=True,
                              errors="replace", timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return '"outlook.exe"' in (done.stdout or "").lower()
    except (OSError, subprocess.SubprocessError):
        return False


JUST_STARTED = "\n(Outlook was only just started, so the newest mail may still be arriving.)"


def _checked(answer: dict) -> dict:
    if answer.get("ok") is not True:
        raise OutlookError(PROBLEMS.get(str(answer.get("problem")), PROBLEMS["failed"]))
    return answer


def _log(cfg, op: str, account: str, outcome: str, seconds: float, count: int | None = None) -> None:
    """What was done, for which account, and how it went: never a word of the mail itself."""
    try:
        path = cfg.state_dir / "logs" / "outlook.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > 300_000:
            path.replace(path.with_name("outlook.old.jsonl"))
        row = {"at": round(time.time()), "op": op[:12], "account": account[:200] if ADDRESS.fullmatch(account) else "",
               "outcome": outcome[:20], "seconds": round(seconds, 1), **({"count": count} if count is not None else {})}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
    except OSError:
        pass


# ------------------------------------------------------------------ which account
def account_for(cfg, said: str = "") -> str:
    """The ticked account the request is about: the one named, or the only one. Raises OutlookError otherwise."""
    allowed = ticked(cfg)
    if not settings(cfg)["on"]:
        raise OutlookError(OFF)
    if not allowed:
        raise OutlookError("No Outlook account is chosen yet. Only the user can choose one: Settings, Email, Outlook on this PC.")
    said = " ".join(str(said or "").lower().split())
    if not said:
        if len(allowed) == 1:
            return allowed[0]
        raise OutlookError("Say which Outlook account: " + _either(allowed) + ".")
    named = ADDRESS.search(said)
    if named:
        if named.group(0) in allowed:
            return named.group(0)
        raise OutlookError(f"{named.group(0)} is not an account the user let JARVIS use. It may use: {_either(allowed)}.")
    words = [w for w in re.findall(r"[a-z0-9][a-z0-9.\-_]+", said) if w not in ("outlook", "my", "the", "account", "email", "mail", "work", "school")]
    matches = [a for a in allowed if words and all(w in a for w in words)]
    if len(matches) == 1:
        return matches[0]
    if len(allowed) == 1 and not words:
        return allowed[0]
    raise OutlookError("Say which Outlook account: " + _either(allowed) + ".")


def _either(addresses) -> str:
    rows = list(addresses)
    return rows[0] if len(rows) == 1 else ", ".join(rows[:-1]) + " or " + rows[-1]


# ------------------------------------------------------------------ reading (results are other people's writing: the caller wraps them)
def _day(text, field: str):
    text = str(text or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text[:19])
    except ValueError:
        raise OutlookError(f"{field} should be a date like 2026-11-20.") from None


def _when(text) -> str:
    try:
        return datetime.fromisoformat(str(text)[:19]).strftime("%a %d %b %Y %H:%M")
    except ValueError:
        return ""


def _clip(text, most: int) -> str:
    return " ".join(str(text or "").split())[:most]


def forget_handles() -> None:
    _handles.clear()
    _count[0] = 0


def _handle(store: str, entry: str, account: str) -> str:
    for key, value in _handles.items():
        if value == (store, entry, account):
            return key
    _count[0] += 1
    key = f"m{_count[0]}"
    _handles[key] = (store, entry, account)
    while len(_handles) > 500:
        _handles.pop(next(iter(_handles)))
    return key


def look(cfg, action: str, account: str = "", folder: str = "inbox", query: str = "", from_person: str = "", unread: bool = False,
         since: str = "", until: str = "", limit: int = 10, id: str = "", run=None) -> str:   # noqa: A002 - the tool's own word
    """The use_outlook tool: accounts, list, read or calendar. Returns text for the model (wrapped as untrusted by the caller)."""
    action = str(action or "").strip().lower()
    if action == "accounts":
        allowed = ticked(cfg)
        if not settings(cfg)["on"]:
            raise OutlookError(OFF)
        return ("JARVIS may use these Outlook accounts: " + ", ".join(allowed) + ".") if allowed else \
            "No Outlook account is chosen yet. Only the user can choose one: Settings, Email, Outlook on this PC."
    if action == "read":
        return _read(cfg, str(id or "").strip(), run)
    if action == "calendar":
        return _calendar(cfg, account, since, until, run)
    if action != "list":
        raise OutlookError("action is accounts, list, read or calendar.")
    who = account_for(cfg, account)
    folder = str(folder or "inbox").lower()
    if folder not in FOLDERS:
        raise OutlookError("folder is inbox, sent or drafts.")
    start, end = _day(since, "since"), _day(until, "until")
    try:
        most = max(1, min(int(limit or 10), MOST_LISTED))
    except (TypeError, ValueError):
        most = 10
    request = {"op": "list", "account": who, "allowed": ticked(cfg), "folder": folder, "limit": most, "unread": bool(unread),
               "query": _clip(query, 120), "from_person": _clip(from_person, 120),
               "since": start.isoformat() if start else "", "until": end.isoformat() if end else ""}
    got = _checked(_ask(request, run, READ_WAIT, cfg))
    rows, cold = got.get("messages") or [], JUST_STARTED if got.get("started") is True else ""
    lines = []
    for row in rows[:most]:
        if not isinstance(row, dict):
            continue
        key = _handle(str(row.get("store", "")), str(row.get("entry", "")), who)
        sender = _clip(row.get("from"), 120) + (f" <{_clip(row.get('address'), 200)}>" if row.get("address") else "")
        lines.append(f"[{key}] {_when(row.get('when'))} · From: {sender} · Subject: {_clip(row.get('subject'), 200)}" +
                     (" · unread" if row.get("unread") else "") + (f"\n    {_clip(row.get('preview'), PREVIEW)}" if row.get("preview") else ""))
    head = f"Outlook, {who}, {FOLDERS[folder]}: " + (f"{len(lines)} message{'s' if len(lines) != 1 else ''}, newest first. "
                                                      "Use action read with an id in [brackets] to read one." if lines else "nothing matched.")
    return (head + cold + ("\n" + "\n".join(lines) if lines else ""))[:MOST_RESULT]


def _read(cfg, key: str, run=None) -> str:
    if not settings(cfg)["on"]:
        raise OutlookError(OFF)
    found = _handles.get(key)
    if not found:
        raise OutlookError("That id is not one JARVIS listed. List the folder again and use an id in [brackets].")
    store, entry, who = found
    if who not in ticked(cfg):
        raise OutlookError(PROBLEMS["not-allowed"])
    got = _checked(_ask({"op": "read", "account": who, "allowed": ticked(cfg), "store": store, "entry": entry}, run, READ_WAIT, cfg))
    body = str(got.get("body") or "")
    cut = got.get("cut") is True or len(body) > MOST_BODY
    files = [_clip(name, 120) for name in got.get("attachments") or []][:30]
    head = [f"From: {_clip(got.get('from'), 120)}" + (f" <{_clip(got.get('address'), 200)}>" if got.get("address") else ""),
            f"To: {_clip(got.get('to'), 600)}"] + ([f"Cc: {_clip(got.get('cc'), 600)}"] if got.get("cc") else []) + \
           [f"Date: {_when(got.get('when'))}", f"Subject: {_clip(got.get('subject'), 300)}"] + \
           ([f"Attachments (not opened): {', '.join(files)}"] if files else [])
    return ("\n".join(head) + "\n\n" + body[:MOST_BODY].strip() + ("\n(cut short)" if cut else ""))[:MOST_RESULT]


def _calendar(cfg, account: str, since: str, until: str, run=None) -> str:
    who = account_for(cfg, account)
    start = _day(since, "since") or datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    end = _day(until, "until") or start + timedelta(days=7)
    if end <= start:
        end = start + timedelta(days=1)
    end = min(end, start + timedelta(days=CALENDAR_DAYS))
    got = _checked(_ask({"op": "calendar", "account": who, "allowed": ticked(cfg), "from": start.isoformat(), "to": end.isoformat()},
                        run, READ_WAIT, cfg))
    rows, cold = got.get("events") or [], JUST_STARTED.replace("newest mail", "latest changes") if got.get("started") is True else ""
    lines = []
    for row in rows[:50]:
        if not isinstance(row, dict):
            continue
        lines.append(f"- {_when(row.get('start'))} to {_when(row.get('end'))}" + (" (all day)" if row.get("all_day") else "") +
                     f" · {_clip(row.get('subject'), 200)}" + (f" · at {_clip(row.get('where'), 120)}" if row.get("where") else "") +
                     (f" · organiser {_clip(row.get('organizer'), 120)}" if row.get("organizer") else ""))
    head = f"Outlook calendar, {who}, {start:%a %d %b} to {end:%a %d %b %Y}: " + (f"{len(lines)} event{'s' if len(lines) != 1 else ''}." if lines else "nothing.")
    return (head + cold + ("\n" + "\n".join(lines) if lines else ""))[:MOST_RESULT]


# ------------------------------------------------------------------ sending (only after the owner's yes: jcc/policy.py asks first)
def send(cfg, account: str, to: str, subject: str, body: str, run=None) -> dict:
    """Send one new email from one ticked account. Returns {"sent": True | False | None, "address", "problem"}:
    None means Outlook was told to send it but it was not seen in Sent Items, so it must not be sent again."""
    account = str(account or "").lower()
    if account not in ticked(cfg):
        return {"sent": False, "problem": PROBLEMS["not-allowed"] if settings(cfg)["on"] else OFF}
    to = "; ".join(part.strip() for part in re.split(r"[,;]", str(to)) if part.strip())       # (Outlook separates addresses with ;)
    request = {"op": "send", "account": account, "allowed": ticked(cfg), "to": to[:2000], "subject": str(subject)[:300],
               "body": str(body)[:20000], "wait": SENT_WAIT}
    try:
        answer = _ask(request, run, SEND_WAIT, cfg)
    except OutlookError as problem:
        return {"sent": False, "problem": str(problem)}
    if answer.get("ok") is not True:
        if answer.get("stage") == "sending":
            return {"sent": None, "address": account}
        return {"sent": False, "problem": PROBLEMS.get(str(answer.get("problem")), PROBLEMS["failed"])}
    if answer.get("problem") == "wrong-account":
        return {"sent": False, "wrong": True, "other": _clip(answer.get("other"), 200) or "another account", "address": account}
    if answer.get("sent") is False and answer.get("problem") == "bad-recipient":
        return {"sent": False, "problem": PROBLEMS["bad-recipient"], "address": account}
    if answer.get("sent") is True:
        return {"sent": True, "address": account}
    return {"sent": None, "address": account}


def ping(run=None) -> dict:
    """Is PowerShell there and answering in the bridge's own way? Outlook is not touched."""
    return _ask({"op": "ping"}, run, READ_WAIT, None, ping=True)
