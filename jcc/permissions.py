"""Permissions: how much JARVIS asks before it acts, and what is waiting for its owner's answer, in one place.

The modes are Claude Code's (jcc/policy.py LEVELS): Auto (the usual one), Manual, Accept edits, Plan and Bypass
permissions. The chip beside the message box shows the mode in force and changes it; what is waiting is shown as a
card at the end of the chat it belongs to, with its answers on it, and the work carries on as soon as it is answered.

Four kinds of things wait:

- The assistant, in the middle of a reply, holding one action for a yes: an email to send, a command, a connector's
  tool, something to delete (jcc/assistant.py, ask_owner). The yes covers exactly that action with exactly those
  details, once (the app keeps the details the question was asked about and carries out those).
- A coding job that stopped to ask (jcc/job_control.py). It is answered once, and a yes says which question it
  answers: if the job is asking something else by then, the yes is refused. The same job then carries on.
- A finished change that waits to be kept (Manual mode, or a project that asks for a review): Keep puts exactly the
  change that was shown into the project, after its checks pass again (jcc/review.py approve); Throw away leaves the
  project as it is.
- A job that was not started because of what it mentions (deploying, servers, keys...: jcc/guard.py). Go ahead starts
  it again, with the agents still told never to do those things themselves; Cancel ends it. What may never be done
  by a job (spending money, the trading risk limits, a protected folder) can only be cancelled.

This file decides nothing by itself and widens nothing. It lists what the parts that own these questions say is
waiting, and hands each answer back to the part that owns it, which checks it again. Changing the mode changes only
how often the owner is asked: what is refused outright stays refused in every mode, Bypass permissions included.
"""
from __future__ import annotations

import hashlib
import time

from jcc import policy
from jcc.redact import redact

# The modes, in the order and the words of Claude Code's own menu (id, name, what it does).
MODES = (("sending", "Auto", "JARVIS decides. It asks only before sending, deleting or paying. Recommended."),
         ("all", "Manual", "Always ask before making changes."),
         ("edits", "Accept edits", "File edits happen by themselves; commands and other changes ask first."),
         ("plan", "Plan", "Make a plan first, and change nothing until you say go ahead."),
         ("bypass", "Bypass permissions", "Never ask. (What JARVIS never does stays off.)"))
OLDER = {"risky": ("Ask before risky things", "The setting from earlier versions.")}
MOST = 20                      # requests listed at once
KINDS = ("assistant", "job", "review", "blocked")
# What a job that was held for its words may still do once its owner says go ahead. (Never: money, the trading risk
# limits, protected folders.)
MAY_GO_AHEAD = ("deploying", "servers", "pushing code", "publishing", "deleting data", "keys/secrets", "sending messages")
GO_AHEAD_NOTE = ("\n\n(The owner said go ahead with this. Even so, do not deploy, push, publish, send messages, delete data, or read "
                 "or write keys and secrets yourself: do everything else, and end by saying what is left for the owner to do.)")
GO_AHEAD_MINUTES = 15


class PermissionError_(ValueError):
    """Something the owner is told as it is."""


def mode(cfg) -> str:
    """The mode in force (one of policy.LEVELS)."""
    from jcc.assistant import settings
    level = settings(cfg).get("ask")
    return level if level in policy.LEVELS else "sending"


def _go_ahead_file(cfg, chat: str, block: str):
    key = hashlib.sha256((str(chat) + "\0" + str(block)).encode("utf-8")).hexdigest()[:32]
    return cfg.state_dir / "go-ahead" / key


def may_go_ahead(cfg, chat: str, block: str) -> bool:
    """Whether a job held for what it mentions may start anyway: its owner said go ahead to exactly that, in that chat,
    a moment ago (used once), or the mode is Bypass permissions. Never for what a job may never do."""
    if block not in MAY_GO_AHEAD:
        return False
    marker = _go_ahead_file(cfg, chat, block)
    try:
        fresh = time.time() - marker.stat().st_mtime < GO_AHEAD_MINUTES * 60
        marker.unlink()
        if fresh:
            return True
    except OSError:
        pass
    return mode(cfg) == "bypass"


def _waiting_jobs(cfg, turns) -> list[dict]:
    """Jobs that wait for their owner, as the list of all work already knows them (jcc/dashboard.py)."""
    from jcc import dashboard
    try:
        return [row for row in dashboard.overview(cfg, turns, {}).get("waiting") or [] if row.get("kind") == "job"]
    except (OSError, ValueError):
        return []


def _blocked_by(cfg, ident: str) -> str:
    from jcc import review
    try:
        return str(review.note(cfg, ident).get("blocked_by") or "")
    except (OSError, ValueError):
        return ""


def state(cfg, assistant, turns=()) -> dict:
    """The mode in force and everything that is waiting for an answer, oldest first."""
    level = mode(cfg)
    pending = []
    with assistant.lock:
        asked = sorted(assistant.pending.values(), key=lambda entry: entry["asked"])
        from jcc import phone
        for entry in asked:
            on_phone = phone.is_phone_chat(cfg, entry.get("chat"))
            pending.append({"kind": "assistant", "id": entry["id"], "question": entry["question"], "detail": entry["detail"], "chat": entry.get("chat") or "",
                            "phone": ("" if not on_phone else "also" if entry.get("phone_ok", True) else "here"),
                            "why": {"send": "It reaches other people or cannot be undone.", "risky": "It changes something on this PC.",
                                    "careful": "This chat has read something from outside, so JARVIS is being careful.", "all": "You chose Manual: JARVIS asks before every change."}
                            .get(str(entry.get("kind")), "")})
    for row in _waiting_jobs(cfg, turns):
        common = {"id": row["id"], "title": str(row.get("title") or ""), "project": str(row.get("project") or ""), "chat": str(row.get("chat") or "")}
        if isinstance(row.get("ask"), dict):
            pending.append({"kind": "job", "question": "The coding job has a question for you", "detail": str(row["ask"].get("text") or ""),
                            "mark": str(row["ask"].get("mark") or ""), **common})
        elif row.get("review"):
            pending.append({"kind": "review", "question": "Keep these changes?", "detail": "", **common})
        else:
            block = _blocked_by(cfg, row["id"])
            if not block:
                continue
            can = block in MAY_GO_AHEAD
            pending.append({"kind": "blocked", "question": ("Go ahead with this?" if can else "A coding job may never do this"),
                            "detail": ("It mentions " + block + ". The coding agents never do that part themselves: they do the rest and tell you what is left."
                                       if can else "It involves " + block + ". Do that part yourself; JARVIS can help with the rest in a new message."),
                            "can": can, **common})
    return {"mode": level,
            "modes": [{"id": ident, "name": name, "about": about} for ident, name, about in MODES],
            "older": {ident: {"name": name, "about": about} for ident, (name, about) in OLDER.items()},
            "pending": pending[:MOST], "more": max(0, len(pending) - MOST)}


def set_mode(cfg, level) -> dict:
    """Change how much JARVIS asks. It takes effect for the next action, in every chat."""
    if level not in policy.LEVELS:
        raise PermissionError_("Choose one of the modes: Auto, Manual, Accept edits, Plan or Bypass permissions.")
    from jcc.assistant import configure
    configure(cfg, {"ask": level})
    return {"mode": level}


def decide(cfg, assistant, kind, ident, yes, text: str = "", mark=None, revision=None) -> dict:
    """The owner's answer to one thing that is waiting. Each kind is handed to the part that owns it."""
    ident, yes = str(ident or ""), yes is True
    if kind == "assistant":
        assistant.decide(ident, yes)                    # (refused there if that question is no longer waiting)
        return {"kind": kind, "id": ident, "answered": "yes" if yes else "no"}
    if kind == "job":
        from jcc import job_control
        if yes and not (isinstance(mark, str) and mark):
            raise PermissionError_("Read the job's question again before you answer.")     # (a yes says which question it answers)
        done = job_control.answer(cfg, ident, yes, redact(str(text or "")), mark=mark if yes else None)
        return {"kind": kind, "id": ident, **done}
    if kind == "review":
        from jcc import review
        if not yes:
            return {"kind": kind, "id": ident, **review.discard(cfg, ident), "answered": "no"}
        # What is kept is what was shown: the card says which state of the copy it showed, and a copy that has moved
        # since is refused (review.approve), never put in unseen.
        if not (isinstance(revision, str) and 7 <= len(revision) <= 64 and all(c in "0123456789abcdef" for c in revision)):
            raise PermissionError_("Look at the changes first: the card shows them, then Keep them.")
        return {"kind": kind, "id": ident, **review.approve(cfg, ident, revision), "answered": "yes"}
    if kind == "blocked":
        from jcc import review
        fm = review.note(cfg, ident)
        block = str(fm.get("blocked_by") or "")
        if fm.get("status") != "needs_approval" or not block:
            raise PermissionError_("That is no longer waiting.")
        if yes and block not in MAY_GO_AHEAD:
            raise PermissionError_("A coding job may never do this, so it can only be cancelled.")
        rerun = None
        if yes:
            marker = _go_ahead_file(cfg, str(fm.get("chat_id") or ""), block)
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(ident, "utf-8")
            rerun = {"chat": str(fm.get("chat_id") or ""), "task": str(fm.get("task") or ""), "project": str(fm.get("project_key") or "")}
        review.close_held(cfg, ident, "Started again, as its owner said go ahead." if yes else "Cancelled by its owner.")
        return {"kind": kind, "id": ident, "answered": "yes" if yes else "no", **({"rerun": rerun} if rerun else {})}
    raise PermissionError_("That is not something that is waiting.")
