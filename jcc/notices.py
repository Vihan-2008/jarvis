"""The Windows notification for work JARVIS finished, could not finish, paused, or needs an OK on. One owner for all of it.

Whatever learns that some work ended (an answer in a chat, here in the service, or a background job, in its own process)
calls finished(). It leaves a small note in state_dir/notices/. The tray helper (jcc/tray.py) picks the note up within four
seconds and shows it as JARVIS's own notification, under the name "JARVIS". A click opens JARVIS at that chat.

A note says only what kind of ending it was and which chat it belongs to. The words shown are the fixed ones in COPY:
what the owner asked never reaches the desktop. When the tray helper is not running, a plain PowerShell balloon with the
same fixed words is shown instead.

The window does its own part: a toast inside the app and the finished sound (jcc/static/nova-audio.js, finishPlan). So:
- no notification while the window is in front;
- a silent one while it is open behind other windows (the window plays the sound);
- one with Windows' own sound when it is closed.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path

from jcc.vault import atomic_write

FOLDER = "notices"
AUMID = "JarvisCommand.JARVIS"            # the name Windows files JARVIS's notifications under (registered by the tray helper)
COPY = {                                  # (title, text)
    "done": ("JARVIS finished", "JARVIS finished a task."),
    "needs_approval": ("JARVIS needs your OK", "JARVIS needs your OK to continue."),
    "failed": ("JARVIS could not finish", "A task did not finish. Open JARVIS to see why."),
    "paused": ("JARVIS paused a task", "A task is paused. Work so far is kept."),
}
FOCUS_SECONDS = 12       # a window in front says so every five seconds (jcc/static/assistant.js -> state_dir/ui-active)
TRAY_SECONDS = 15        # the tray helper marks that it is running every four seconds (state_dir/tray-alive)
QUICK = 5.0              # a chat answer quicker than this needs no notification: the owner has only just asked
KEEP = 24 * 3600         # how long a shown note's marker is kept, so the same ending is never shown twice
CHAT = re.compile(r"[A-Za-z0-9_.-]{1,80}")
RANK = {"needs_approval": 0, "failed": 1, "paused": 2, "done": 3}     # several at once: the most urgent is the one said
NAME = 60                # the longest a chat's name is in a notification


def _fresh(path: Path, seconds: float, now: float) -> bool:
    try:
        return now - path.stat().st_mtime < seconds
    except OSError:
        return False


def focused(cfg, now: float | None = None) -> bool:
    """Is a JARVIS window in front, right now?"""
    return _fresh(cfg.state_dir / "ui-active", FOCUS_SECONDS, time.time() if now is None else now)


def tray_running(cfg, now: float | None = None) -> bool:
    return _fresh(cfg.state_dir / "tray-alive", TRAY_SECONDS, time.time() if now is None else now)


def _name(ident: str, status: str) -> str:
    return hashlib.sha256(f"{ident}|{status}".encode()).hexdigest()[:24]


def finished(cfg, ident: str, status: str, *, chat: str = "", seconds: float | None = None, background: bool = True,
             spoken: bool = False, now: float | None = None) -> str:
    """Tell the owner that some work ended, if they need telling. Returns what happened: "queued" (for the tray helper),
    "balloon" (the fallback), or why nothing was shown."""
    if status not in COPY:
        return "ignored"                                  # (stopped by the owner: they know)
    from jcc.learning import settings
    if not settings(cfg).get("desktop_alerts", True):
        return "off"
    now = time.time() if now is None else now
    if spoken:
        return "spoken"                                   # (a spoken answer: the owner is listening to it)
    if focused(cfg, now):
        return "focused"                                  # (the window shows it, and plays the sound)
    if not background and status == "done" and seconds is not None and seconds < QUICK:
        return "quick"
    folder = cfg.state_dir / FOLDER
    name = _name(str(ident), status)
    if (folder / f"{name}.json").exists() or (folder / f"{name}.shown").exists():
        return "duplicate"
    if tray_running(cfg, now):
        folder.mkdir(parents=True, exist_ok=True)
        atomic_write(folder / f"{name}.json", json.dumps({"status": status, "chat": chat if CHAT.fullmatch(chat or "") else "",
                                                          "at": now}))
        return "queued"
    if os.name != "nt" or os.environ.get("JCC_NO_CREDMAN"):
        return "no-tray"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.shown").write_text("", "utf-8")
    title, text = COPY[status]
    # Fixed strings only, from COPY: nothing the owner wrote enters a shell or a notification.
    script = ("Add-Type -AssemblyName System.Windows.Forms; $n=New-Object System.Windows.Forms.NotifyIcon; "
              "$n.Icon=[System.Drawing.SystemIcons]::Information; $n.Visible=$true; "
              f"$n.BalloonTipTitle='{title}'; $n.BalloonTipText='{text}'; $n.ShowBalloonTip(5000); Start-Sleep -Seconds 6; $n.Dispose()")
    subprocess.Popen(["powershell.exe", "-NoProfile", "-EncodedCommand", base64.b64encode(script.encode("utf-16-le")).decode()],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return "balloon"


def take(cfg, now: float | None = None) -> list[dict]:
    """For the tray helper: the notes waiting, oldest first, each marked as shown (and old markers cleared away)."""
    now = time.time() if now is None else now
    folder = cfg.state_dir / FOLDER
    if not folder.is_dir():
        return []
    notes = []
    for path in sorted(folder.iterdir(), key=lambda p: p.stat().st_mtime if p.exists() else 0):
        try:
            if path.suffix == ".shown":
                if now - path.stat().st_mtime > KEEP:
                    path.unlink(missing_ok=True)
                continue
            if path.suffix != ".json" or path.is_symlink():
                continue                                  # (a note still being written, or anything else)
            value = json.loads(path.read_text("utf-8"))
            path.with_suffix(".shown").write_text("", "utf-8")
            path.unlink(missing_ok=True)
        except (OSError, ValueError):
            continue
        if isinstance(value, dict) and value.get("status") in COPY and now - float(value.get("at") or 0) < 600:
            chat = str(value.get("chat") or "")
            notes.append({"status": value["status"], "chat": chat if CHAT.fullmatch(chat) else ""})
    return notes


def chat_name(cfg, chat: str) -> str:
    """The chat's name for the notification, only when its owner has asked for it (Settings, Customize): its current
    title, on one line, at most NAME characters, cut between words. "" when not asked for, or when the chat is private,
    deleted or not there: the fixed words are said instead. (A notification can be seen on the lock screen, by anyone
    looking at the screen, and stays in Windows' list of notifications.)"""
    try:
        from jcc.learning import settings
        if not chat or not CHAT.fullmatch(chat) or settings(cfg).get("notice_titles") is not True:
            return ""
        from jcc.chats import Chats
        chats = Chats(cfg)
        if chats.is_deleted(chat):
            return ""
        title = str(chats.get(chat).get("title") or "")
    except Exception:  # noqa: BLE001 - private, gone, or unreadable: the fixed words
        return ""
    title = " ".join("".join(ch if ch.isprintable() else " " for ch in title).split())
    if title.lower() in ("", "new chat"):
        return ""
    if len(title) > NAME:
        cut = title[:NAME]
        title = (cut[:cut.rfind(" ")] if cut.rfind(" ") > NAME // 2 else cut).rstrip(" ,.;:-–") + "…"
    return title


def words(cfg, waiting: list[dict]) -> tuple[str, str, str]:
    """What the tray shows for the notes waiting (oldest first): (title, text, the chat a click opens). The most urgent
    is the one said (the latest of those), so a question for the owner is never hidden behind a finished task."""
    note = sorted(reversed(waiting), key=lambda n: RANK.get(n["status"], 9))[0]
    title, text = COPY[note["status"]]
    name, others = chat_name(cfg, note["chat"]), len(waiting) - 1
    if name:
        text = f"“{name}”" + (f" and {others} more. Open JARVIS to see them." if others else "")
    elif others:
        text = f"{text} ({len(waiting)} tasks ended. Open JARVIS to see them.)"
    return title, text, note["chat"]
