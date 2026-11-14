"""Mods: the owner's own changes to how JARVIS looks and behaves.

- commands  /name stands for a longer request. "$ARGUMENTS" in its text is where whatever follows the name goes.
- hooks     when something happens (JARVIS opens, an answer is finished, a coding job is finished, a reminder is due)
            a note is shown, something is said, or a command is run.
- panels    a small page of the owner's own (pinned from something JARVIS made) that stays beside the chat.
- status    a line under the message box with what the owner wants in view: which AI answers, what is left of the
            allowances, the time.

Everything is kept in <state>/mods.json (and a panel's page in <state>/mods/) on this PC. Nothing here runs a program:
a hook can only show, say or ask, and a panel is shown sealed off like every page JARVIS makes.
"""
from __future__ import annotations

import json
import re
import secrets as _rand
import time

from jcc.redact import redact
from jcc.vault import atomic_write, read_json

NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,30}")
# What typing "/" offers before anything of the owner's own. These are done by the window itself (see nova.js).
BUILTIN = (("work", "What is running, waiting for you and finished, here in the chat"),
           ("mode", "Auto, Manual, Accept edits, Plan or Bypass permissions"),
           ("new", "Start a fresh conversation"),
           ("research", "Research what follows on the web, with sources"),
           ("projects", "Your projects: pick one, open its folder or delete it"),
           ("folder", "Open file location: the project's folder"),
           ("undo", "Undo the last change made in this chat"),
           ("stop", "Stop what is running in this chat"),
           ("status", "The mode, the AI and what is left of each allowance"),
           ("usage", "Show what has been used"),
           ("compact", "Shorten this conversation to a summary and carry on from it"),
           ("chat", "Switch to Chat"),
           ("code", "Switch to Code"),
           ("ultracode", "Code with the strongest AI, thinking as hard as it can (on or off)"),
           ("dryrun", "Show what JARVIS would do with what follows, without doing it"),
           ("checklist", "Show what will count as done for what follows"),
           ("files", "The project's files"),
           ("terminal", "A terminal"),
           ("browser", "A web browser beside the chat"),
           ("artifacts", "What JARVIS has made"),
           ("agents", "Every agent at work"),
           ("pair", "A planner and a builder on one goal"),
           ("court", "The Court of JARVIS: put an idea on trial"),
           ("security", "Check a project for the usual holes"),
           ("routines", "Things done again and again"),
           ("activity", "Every job's steps and changes, one by one"),
           ("efficiency", "How much each AI was used and how well it did"),
           ("tasks", "The order of waiting work"),
           ("recall", "Search past decisions and work"),
           ("shared", "Web pages shared with JARVIS"),
           ("control", "Step-by-step control of this computer"),
           ("settings", "Open Settings"),
           ("voice", "Voice settings"),
           ("connections", "What JARVIS is connected to"),
           ("models", "The AIs JARVIS can use"),
           ("updates", "Updates"),
           ("mods", "Change these commands, hooks, panels and the status line"),
           ("help", "List every command"))
WHEN = {"open": "JARVIS is opened", "answer": "an answer is finished", "job": "a coding job is finished", "reminder": "a timer or reminder is due"}
DO = {"toast": "show a note", "say": "say it aloud", "command": "run a command"}
STATUS = {"brain": "Which AI answers", "claude": "Claude allowance left", "codex": "Codex allowance left", "voice": "Voice characters left", "clock": "The time"}
MOST = {"commands": 60, "hooks": 20, "panels": 8}
PANEL_BYTES = 600_000


class ModError(ValueError):
    pass


def _file(cfg):
    return cfg.state_dir / "mods.json"


def _text(value, most: int) -> str:
    return redact(str(value or "").replace("\r\n", "\n").strip())[:most]


def load(cfg) -> dict:
    """Everything the owner has set up, with anything that is not as it should be left out."""
    saved = read_json(_file(cfg), {})
    saved = saved if isinstance(saved, dict) else {}
    commands = [{"name": c["name"], "about": _text(c.get("about"), 160), "text": _text(c.get("text"), 6000)} for c in saved.get("commands") or []
                if isinstance(c, dict) and isinstance(c.get("name"), str) and NAME.fullmatch(c["name"]) and str(c.get("text") or "").strip()]
    hooks = [{"id": str(h["id"]), "when": h["when"], "do": h["do"], "text": _text(h.get("text"), 300), "on": h.get("on", True) is not False} for h in saved.get("hooks") or []
             if isinstance(h, dict) and re.fullmatch(r"[0-9a-f]{8}", str(h.get("id") or "")) and h.get("when") in WHEN and h.get("do") in DO and str(h.get("text") or "").strip()]
    panels = [{"id": str(p["id"]), "name": _text(p.get("name"), 40) or "Panel", "online": p.get("online") is True} for p in saved.get("panels") or []
              if isinstance(p, dict) and re.fullmatch(r"[0-9a-f]{8}", str(p.get("id") or ""))]
    status = saved.get("status") if isinstance(saved.get("status"), dict) else {}
    return {"commands": commands[:MOST["commands"]], "hooks": hooks[:MOST["hooks"]], "panels": panels[:MOST["panels"]],
            "status": {"on": status.get("on") is True, "items": [item for item in status.get("items") or [] if item in STATUS] or ["brain", "claude"]}}


def _save(cfg, mods: dict) -> None:
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(_file(cfg), json.dumps(mods))


def listing(cfg) -> dict:
    """Everything the window needs: the owner's mods, the built-in commands, and the commands of switched-on skill packs."""
    mods = load(cfg)
    try:
        from jcc import skills
        packs = [{"name": c["name"], "about": str(c.get("description") or "")[:160], "pack": c["pack"]} for c in skills.commands(cfg)]
    except Exception:  # noqa: BLE001 - the skills library is optional
        packs = []
    own = {c["name"] for c in mods["commands"]} | {name for name, _ in BUILTIN}
    return {**mods, "builtin": [{"name": name, "about": about} for name, about in BUILTIN], "packs": [c for c in packs if c["name"] not in own][:200],
            "when": WHEN, "do": DO, "status_items": STATUS}


# ---------------------------------------------------------------------- commands
def save_command(cfg, name, about, text) -> dict:
    name = str(name or "").strip().lstrip("/").lower()
    if not NAME.fullmatch(name):
        raise ModError("A command's name is one word: letters, numbers and dashes (for example: standup).")
    if name in {builtin for builtin, _ in BUILTIN}:
        raise ModError(f"/{name} is one of JARVIS's own commands. Choose another name.")
    text = _text(text, 6000)
    if not text:
        raise ModError("Write what the command should ask JARVIS to do.")
    mods = load(cfg)
    rest = [c for c in mods["commands"] if c["name"] != name]
    if len(rest) >= MOST["commands"]:
        raise ModError("That is as many commands as JARVIS keeps. Remove one first.")
    mods["commands"] = sorted(rest + [{"name": name, "about": _text(about, 160), "text": text}], key=lambda c: c["name"])
    _save(cfg, mods)
    return listing(cfg)


def delete_command(cfg, name) -> dict:
    mods = load(cfg)
    mods["commands"] = [c for c in mods["commands"] if c["name"] != str(name or "").strip().lstrip("/").lower()]
    _save(cfg, mods)
    return listing(cfg)


def expand(cfg, text: str) -> tuple[str, str]:
    """What a message that starts with one of the owner's commands really asks: (the request in full, the command's name).
    Anything else comes back as it is, with "" for the name."""
    found = re.match(r"^/([a-z0-9][a-z0-9-]{0,30})(?:[ \t]+(.*))?$", str(text or "").strip(), re.S | re.I)
    if not found:
        return text, ""
    name, rest = found.group(1).lower(), (found.group(2) or "").strip()
    body = next((c["text"] for c in load(cfg)["commands"] if c["name"] == name), "")
    if not body:
        try:
            from jcc import skills
            body = skills.command_text(cfg, name)
        except Exception:  # noqa: BLE001
            body = ""
    if not body:
        return text, ""
    if "$ARGUMENTS" in body:
        return body.replace("$ARGUMENTS", rest), name
    return (body + ("\n\n" + rest if rest else "")), name


# ---------------------------------------------------------------------- hooks
def save_hook(cfg, when, do, text, ident: str = "") -> dict:
    if when not in WHEN or do not in DO:
        raise ModError("Choose what should happen, and when.")
    text = _text(text, 300)
    if not text:
        raise ModError("Write what should be shown, said or run." )
    if do == "command":
        if not re.match(r"^/[a-z0-9][a-z0-9-]{0,30}(\s|$)", text, re.I):
            raise ModError("To run a command, write it as you would type it: /name and anything that follows.")
        if when == "answer":
            raise ModError("A command cannot be run after every answer: its own answer would run it again, without end.")
    mods = load(cfg)
    rest = [h for h in mods["hooks"] if h["id"] != ident]
    if len(rest) >= MOST["hooks"]:
        raise ModError("That is as many of these as JARVIS keeps. Remove one first.")
    known = next((h for h in mods["hooks"] if h["id"] == ident), None)
    mods["hooks"] = rest + [{"id": known["id"] if known else _rand.token_hex(4), "when": when, "do": do, "text": text, "on": known["on"] if known else True}]
    _save(cfg, mods)
    return listing(cfg)


def switch_hook(cfg, ident, on) -> dict:
    mods = load(cfg)
    for hook in mods["hooks"]:
        if hook["id"] == ident:
            hook["on"] = bool(on)
    _save(cfg, mods)
    return listing(cfg)


def delete_hook(cfg, ident) -> dict:
    mods = load(cfg)
    mods["hooks"] = [h for h in mods["hooks"] if h["id"] != ident]
    _save(cfg, mods)
    return listing(cfg)


# ---------------------------------------------------------------------- panels
def _panel_file(cfg, ident: str):
    return cfg.state_dir / "mods" / f"panel-{ident}.html"


def save_panel(cfg, name, html, online: bool = False) -> dict:
    """online: its owner allowed this page to load from the internet when pinning it (otherwise it is sealed from it)."""
    name, html = _text(name, 40), str(html or "")
    if not name:
        raise ModError("Give the panel a name.")
    if not html.strip() or len(html.encode("utf-8")) > PANEL_BYTES:
        raise ModError("That page is empty or too large to keep as a panel.")
    mods = load(cfg)
    if len(mods["panels"]) >= MOST["panels"]:
        raise ModError("That is as many panels as JARVIS keeps. Remove one first.")
    ident = _rand.token_hex(4)
    path = _panel_file(cfg, ident)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, html)
    mods["panels"].append({"id": ident, "name": name, "online": online is True})
    _save(cfg, mods)
    return {**listing(cfg), "made": ident}


def panel_html(cfg, ident) -> str:
    if not re.fullmatch(r"[0-9a-f]{8}", str(ident or "")) or not any(p["id"] == ident for p in load(cfg)["panels"]):
        raise ModError("That panel is not there any more.")
    try:
        return _panel_file(cfg, ident).read_text("utf-8")
    except OSError:
        raise ModError("That panel is not there any more.") from None


def delete_panel(cfg, ident) -> dict:
    mods = load(cfg)
    if re.fullmatch(r"[0-9a-f]{8}", str(ident or "")):
        mods["panels"] = [p for p in mods["panels"] if p["id"] != ident]
        _panel_file(cfg, ident).unlink(missing_ok=True)
        _save(cfg, mods)
    return listing(cfg)


# ---------------------------------------------------------------------- the status line
def set_status(cfg, on, items) -> dict:
    mods = load(cfg)
    chosen = [item for item in items if item in STATUS] if isinstance(items, list) else mods["status"]["items"]
    mods["status"] = {"on": bool(on), "items": list(dict.fromkeys(chosen)) or ["brain"]}
    _save(cfg, mods)
    return listing(cfg)


def status_now(cfg, brain: str = "") -> dict:
    """What the status line shows at this moment (only what is already known on this PC: nothing is fetched)."""
    from jcc import quota
    out: dict = {"brain": brain, "clock": time.strftime("%H:%M")}
    accounts = quota.snapshot(cfg)
    for name in ("claude", "codex"):
        windows = [w for w in (accounts.get(name) or {}).get("windows") or [] if isinstance(w, dict) and isinstance(w.get("remaining_percent"), (int, float))]
        if windows:
            out[name] = [{"name": str(w.get("name") or ""), "left": round(float(w["remaining_percent"])), "minutes": w.get("minutes"), "reset_at": w.get("reset_at")} for w in windows[:3]]
    return out
