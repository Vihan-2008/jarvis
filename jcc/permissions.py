"""Permissions: how much JARVIS asks before it acts, and what is waiting for its owner's yes or no, in one place.

The control beside the message box shows the mode in force and whatever is waiting. Three kinds of things wait:

- The assistant, in the middle of a reply, holding one action for a yes: an email to send, a command, a connector's
  tool, something to delete (jcc/assistant.py, ask_owner). The yes covers exactly that action with exactly those
  details, once (the app keeps the details the question was asked about and carries out those).
- A coding job that stopped to ask (jcc/job_control.py). It is answered once, and a yes says which question it
  answers: if the job is asking something else by then, the yes is refused. The same job then carries on.
- A change that passed its checks and waits to be looked at. That one is not decided here: it has to be looked at
  first, so the control only leads to where it can be seen.

This file decides nothing by itself and widens nothing. It lists what the parts that own these questions say is
waiting, and hands each answer back to the part that owns it, which checks it again. Changing the mode changes only
how often the owner is asked: what is refused outright stays refused in every mode, and sending, deleting and paying
are asked about in every mode.
"""
from __future__ import annotations

from jcc import policy
from jcc.redact import redact

# The modes, in the words the owner sees. (The same three as Settings, Assistant: jcc/policy.py LEVELS.)
MODES = (("sending", "Ask before sending, deleting or paying", "JARVIS does everything else by itself. Recommended."),
         ("risky", "Also ask before risky things", "Installing, running commands and changing files wait for your yes too."),
         ("all", "Ask before everything", "Every action on this PC waits for your yes."))
MOST = 20                      # requests listed at once
KINDS = ("assistant", "job", "review")


class PermissionError_(ValueError):
    """Something the owner is told as it is."""


def _waiting_jobs(cfg, turns) -> list[dict]:
    """Jobs that wait for their owner, as the list of all work already knows them (jcc/dashboard.py)."""
    from jcc import dashboard
    try:
        return [row for row in dashboard.overview(cfg, turns, {}).get("waiting") or [] if row.get("kind") == "job"]
    except (OSError, ValueError):
        return []


def state(cfg, assistant, turns=()) -> dict:
    """The mode in force and everything that is waiting for a yes or no, oldest first."""
    from jcc.assistant import settings
    level = settings(cfg).get("ask")
    pending = []
    with assistant.lock:
        asked = sorted(assistant.pending.values(), key=lambda entry: entry["asked"])
        for entry in asked:
            pending.append({"kind": "assistant", "id": entry["id"], "question": entry["question"], "detail": entry["detail"], "chat": entry.get("chat") or "",
                            "why": {"send": "It reaches other people or cannot be undone.", "risky": "It changes something on this PC.",
                                    "careful": "This chat has read something from outside, so JARVIS is being careful.", "all": "You asked to be asked about everything."}
                            .get(str(entry.get("kind")), "")})
    for row in _waiting_jobs(cfg, turns):
        if isinstance(row.get("ask"), dict):
            pending.append({"kind": "job", "id": row["id"], "question": "A coding job stopped and asks you", "detail": str(row["ask"].get("text") or ""),
                            "mark": str(row["ask"].get("mark") or ""), "title": str(row.get("title") or ""), "project": str(row.get("project") or ""),
                            "chat": str(row.get("chat") or "")})
        elif row.get("review"):
            pending.append({"kind": "review", "id": row["id"], "question": "A change is waiting for you to look at it", "detail": "",
                            "title": str(row.get("title") or ""), "project": str(row.get("project") or ""), "chat": str(row.get("chat") or "")})
    return {"mode": level if level in policy.LEVELS else "sending",
            "modes": [{"id": ident, "name": name, "about": about} for ident, name, about in MODES],
            "pending": pending[:MOST], "more": max(0, len(pending) - MOST)}


def set_mode(cfg, level) -> dict:
    """Change how much JARVIS asks. It takes effect for the next action, in every chat."""
    if level not in policy.LEVELS:
        raise PermissionError_("Choose one of the three ways of asking.")
    from jcc.assistant import configure
    configure(cfg, {"ask": level})
    return {"mode": level}


def decide(cfg, assistant, kind, ident, yes, text: str = "", mark=None) -> dict:
    """The owner's yes or no to one thing that is waiting. Each kind is handed to the part that owns it."""
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
        raise PermissionError_("Look at the change first: open it, then approve it there.")
    raise PermissionError_("That is not something that is waiting.")
