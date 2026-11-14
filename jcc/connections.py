"""Everything JARVIS can be connected to, in one list: what it is for, whether it is connected, and how to connect it.

This is what a new user needs to get going, and what an old one looks at when something has stopped working.
`overview` only reads what is already known (fast, no network). `check` really tries one connection.
No key or password ever leaves through here: only "connected" or "not".
"""
from __future__ import annotations

import os
import time

from jcc import secrets
from jcc.vault import read_json

GROUPS = (("brain", "Thinking"), ("voice", "Hearing and speaking"), ("hands", "Doing things"), ("memory", "Remembering"))


def _item(ident: str, group: str, name: str, about: str, state: str, status: str, **more) -> dict:
    """state: "ok" (working), "off" (not connected, and optional), "needed" (not connected, and JARVIS is poorer without it), "problem"."""
    return {"id": ident, "group": group, "name": name, "about": about, "state": state, "status": status, **more}


def _ago(when) -> str:
    try:
        seconds = max(0, time.time() - float(when))
    except (TypeError, ValueError):
        return ""
    for size, word in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= size:
            count = int(seconds // size)
            return f"{count} {word}{'s' if count != 1 else ''} ago"
    return "just now"


def _agent(cfg, name: str, label: str, about: str, needed: bool, how: str) -> dict:
    from jcc import agents
    agent = cfg.agents.get(name)
    reading = read_json(cfg.state_dir / f"quota-{name}.json", {})
    if not agent or not agent.enabled:
        return _item(name, "brain", label, about, "off", "Switched off in JARVIS's settings", how=how)
    if not agents.available(agent):
        return _item(name, "brain", label, about, "needed" if needed else "off", "Not installed on this PC", how=how)
    fresh = time.time() - float(reading.get("at") or 0) < 3600
    if reading.get("windows") and fresh and not reading.get("error"):
        return _item(name, "brain", label, about, "ok", "Signed in and answering", detail="Allowance last read " + _ago(reading.get("at")) + ".", check=True)
    if reading.get("error"):
        return _item(name, "brain", label, about, "problem", "Installed, but it did not answer", detail=str(reading["error"])[:160], how=how, check=True)
    return _item(name, "brain", label, about, "ok", "Installed", detail="Press Check to make sure it is signed in.", how=how, check=True)


def overview(cfg) -> list[dict]:
    from jcc import assistant, mailer, speech
    items = [
        _agent(cfg, "claude", "Claude", "JARVIS's mind. Uses your Claude subscription through Claude Code; no API key is needed.", True,
               "Install Claude Code, then open a terminal, type claude and sign in with your Claude account."),
        _agent(cfg, "codex", "GPT (Codex)", "A second AI for building software. Optional.", False,
               "Install the Codex CLI and sign in with your ChatGPT account. JARVIS works without it."),
    ]
    from jcc import providers
    others = [providers.label(cfg, ident).split(" (")[0] for ident in providers.CATALOG if providers.connected(cfg, ident)]
    items.append(_item("ai", "brain", "Other AI services", "Grok, Gemini, ChatGPT's API, Perplexity, DeepSeek, Mistral, models on this PC and more. They stand in when "
                       "Claude has reached its limit, do research, or answer when you pick one.", "ok" if others else "off",
                       (f"{len(others)} connected: " + ", ".join(others))[:140] if others else "None connected", open="models",
                       how="Each one needs its own key, from that service's website. Open AI models to add them."))
    try:
        from jcc import skills
        packs = skills.listing(cfg)["packs"]
    except Exception:  # noqa: BLE001 - a damaged library file must not break the list
        packs = []
    switched = sum(pack["on"] for pack in packs)
    items.append(_item("skills", "brain", "Skills library", "Packs of playbooks, reviewers and rules for the coding agents. Each pack is scanned with SkillSpector "
                       "before it is kept, and nothing in one is ever run.", "ok" if switched else "off",
                       (f"{switched} switched on, from {len(packs)} pack{'s' if len(packs) != 1 else ''}") if packs else "No packs added", open="skills",
                       how="Open Skills and add a pack by its folder, .zip file or repository address."))
    keys = {name: bool(secrets.get(name)) for name in ("groq", "openai", "elevenlabs")}
    listening, speaking = speech.engines(cfg)
    items.append(_item("groq", "voice", "Whisper listening (Groq)", "Understands what you say, in about a fifth of a second. Free.",
                       "ok" if keys["groq"] else "off" if keys["openai"] else "needed", "Connected" if keys["groq"] else "Not connected",
                       key="groq", check=keys["groq"], remove=keys["groq"],
                       how="Create a free key at console.groq.com (API Keys) and paste it here."))
    items.append(_item("openai", "voice", "OpenAI transcription", "An alternative to Groq for understanding speech. Optional, paid by use.",
                       "ok" if keys["openai"] else "off", "Connected" if keys["openai"] else "Not connected", key="openai", check=keys["openai"], remove=keys["openai"],
                       how="Create a key at platform.openai.com (API keys) and paste it here."))
    chosen = speech.settings(cfg)
    items.append(_item("elevenlabs", "voice", "ElevenLabs voice", "A natural, human-sounding voice for JARVIS. Paid plan.",
                       "ok" if keys["elevenlabs"] else "off", ("Connected" + (" · " + chosen["voice_name"] if chosen.get("voice_name") else "")) if keys["elevenlabs"] else "Not connected",
                       detail="" if keys["elevenlabs"] else "Without it JARVIS speaks with the voice built into Windows.", key="elevenlabs",
                       check=keys["elevenlabs"], remove=keys["elevenlabs"],
                       how="Choose a plan at elevenlabs.io, create a key under Developers, API Keys, and paste it here."))
    items.append(_item("sound", "voice", "Microphone and speakers", "Which devices JARVIS listens and speaks through.", "ok",
                       (chosen["mic"] or "Windows default microphone") + " · " + (chosen["speaker"] or "Windows default speakers"),
                       detail=f"Listening with {'Whisper' if listening == 'whisper' else 'ElevenLabs' if listening == 'eleven' else 'the built-in recogniser'}, "
                              f"speaking with {'ElevenLabs' if speaking == 'eleven' else 'the built-in voice'}.", open="voice"))
    tray = read_json(cfg.state_dir / "tray-status.json", {})
    helper_running = _held(cfg.state_dir / "tray.lock")
    from jcc import system
    if not helper_running and system.kind() == "linux":
        items.append(_item("helper", "voice", "\"Hey JARVIS\" and shortcuts", "Listens for its name and for the keyboard shortcuts, with or without a window open.",
                           "off", "Not available on Linux yet"))
    elif not helper_running:
        items.append(_item("helper", "voice", "\"Hey JARVIS\" and shortcuts", "Listens for its name and for the keyboard shortcuts, with or without a window open.",
                           "problem", "The background helper is not running",
                           how="It starts with JARVIS. Open JARVIS to start it now." if system.kind() == "mac" else
                           "It starts when you sign in to Windows. Open JARVIS from the Start menu to start it now."))
    else:
        wake = "listening for \"Hey JARVIS\"" if tray.get("wake") else ("\"Hey JARVIS\" is off" if not chosen.get("wake") else "\"Hey JARVIS\" is not listening")
        items.append(_item("helper", "voice", "\"Hey JARVIS\" and shortcuts", "Listens for its name and for the keyboard shortcuts, with or without a window open.",
                           "problem" if tray.get("wake_problem") else "ok", "Running, " + wake,
                           detail=str(tray.get("wake_problem") or ", ".join(f"{what} {keys_}" for what, keys_ in (tray.get("keys") or {}).items()))[:200], open="voice"))
    options = assistant.settings(cfg)
    items.append(_item("pc", "hands", "Control of this PC", "Opening apps, clicking, typing and running commands for you.",
                       "ok" if options["pc_control"] else "off", "Allowed" if options["pc_control"] else "Switched off",
                       detail={"sending": "JARVIS asks first only before sending, deleting or paying.", "risky": "JARVIS asks first before anything risky.",
                               "all": "JARVIS asks first before every action."}[options["ask"]], open="assistant"))
    if system.kind() == "mac":
        # What macOS itself must allow before JARVIS can work in other apps or see the screen. It is switched on by the
        # owner in System Settings and nowhere else.
        from jcc import macdesk
        allowed = macdesk.permissions()
        for ident, which, title, about, where in (
                ("mac-accessibility", "accessibility", "Accessibility (macOS)", "Lets JARVIS press buttons, type and click in other apps.", "Accessibility"),
                ("mac-screen", "screen", "Screen Recording (macOS)", "Lets JARVIS see the screen, and tell the Mac's own sound from your voice.",
                 "Screen & System Audio Recording")):
            yes = allowed[which]
            items.append(_item(ident, "hands", title, about, "ok" if yes else "needed" if yes is False else "off",
                               "Allowed" if yes else "Not allowed yet" if yes is False else "Could not be checked",
                               how=f"Open System Settings, Privacy & Security, {where}, and switch on JARVIS (or Terminal, if you started it from there)."))
    mail = mailer.status(cfg)
    items.append(_item("mail", "hands", "Email", "Sending email for you, after you have said yes to each one.",
                       "ok" if mail["connected"] else "off", ("Connected as " + mail["address"]) if mail["connected"] else "Not connected",
                       detail="" if mail["connected"] else {"gmail": "Without an account JARVIS writes the email in Gmail in your browser, shows it to you, and sends it after your yes.",
                                                            "app": "Without an account JARVIS writes the email in the mail app on this PC, shows it to you, and sends it after your yes."}.get(
                           options["mail"], "Without an account JARVIS writes the email where you write your mail (Gmail in your browser, or your mail app), shows it to you, and sends it after your yes."),
                       open="email", check=mail["connected"]))
    from jcc import online
    linked = online.connected(cfg)
    items.append(_item("accounts", "hands", "Email, calendar and other online accounts", "Lets JARVIS look things up in Gmail, Outlook, Google Calendar and hundreds of "
                       "other services, through Composio. Looking things up is done by a helper that can only read; JARVIS asks you before anything is created, "
                       "changed or deleted.", "ok" if linked else "off", "Connected" if linked else "Not connected", key="composio", check=linked, remove=linked,
                       detail=("Say “connect my Gmail” (or your calendar) and JARVIS gives you the link to sign in. Accounts connected at Composio under the name “"
                               + online.settings(cfg)["user"] + "” are used.") if linked else "", user=online.settings(cfg)["user"] if linked else "",
                       how="Make a free account at composio.dev, open Settings, Project Settings, API Keys, copy the project key (it starts with ak_) and paste it here."))
    added = read_json(cfg.state_dir / "connectors.json", {}).get("mcpServers", {})
    names = sorted(str(name) for name in added) if isinstance(added, dict) else []
    items.append(_item("connectors", "hands", "Connectors", "Extra tools you have added yourself (a calendar, Gmail, a database).",
                       "ok" if names else "off", (", ".join(names)[:120]) if names else "None added",
                       how="Put them in connectors.json in JARVIS's settings folder, in the same format as Claude's MCP settings. JARVIS asks before using them in a chat that has read outside content."))
    for label, ident, file, about in (("ChatGPT website", "chatgpt", "capture-chatgpt-status.json", "Saves your ChatGPT conversations into your notes."),
                                      ("Claude website", "claude-web", "capture-claude-status.json", "Saves your Claude conversations into your notes.")):
        seen = read_json(cfg.state_dir / file, {})
        items.append(_item(ident, "memory", label, about + " Needs the JARVIS browser extension.", "ok" if seen.get("at") else "off",
                           ("Last saved " + _ago(seen["at"])) if seen.get("at") else "Nothing saved yet", settings=True,
                           how="Open Settings, Memory and add the browser extension."))
    github = read_json(cfg.state_dir / "github-status.json", {})
    state = "ok" if github.get("status") == "synced" else "problem" if github.get("status") in ("error", "failed") else "off"
    items.append(_item("github", "memory", "GitHub backup", "Keeps a private copy of your notes on GitHub.", state,
                       ("Synced " + _ago(github.get("at"))) if state == "ok" else str(github.get("error") or github.get("status") or "Not connected")[:120],
                       detail="Private repository." if github.get("private") and state == "ok" else "", settings=True, how="Open Settings, Memory to connect a repository."))
    cloud = read_json(cfg.state_dir / "cloud-memory-status.json", {})
    state = "problem" if cloud.get("status") == "error" else "ok" if cloud.get("status") else "off"
    items.append(_item("cloud", "memory", "Cloud search (Supabase)", "Searches your notes by meaning. Optional.", state,
                       ("Not working: " + str(cloud.get("error", ""))[:100]) if state == "problem" else (str(cloud.get("status")).capitalize() if state == "ok" else "Not connected"),
                       detail=(f"{cloud.get('indexed_notes', 0)} notes indexed." if cloud.get("indexed_notes") else ""), settings=True,
                       how="Open Settings, Memory to connect or repair it."))
    return items


def summary(items: list[dict]) -> dict:
    return {"connected": sum(1 for item in items if item["state"] == "ok"), "of": len(items),
            "needed": [item["name"] for item in items if item["state"] == "needed"], "problems": [item["name"] for item in items if item["state"] == "problem"]}


def _held(lock_path) -> bool:
    """Is another program (the tray helper) holding this lock right now?"""
    if os.name != "nt":
        try:
            import fcntl
            with open(lock_path, "r+b") as handle:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    return True
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                return False
        except (OSError, ImportError):
            return False
    try:
        import msvcrt
        with open(lock_path, "r+b") as handle:       # looked at, never written: the helper's own note in it stays as it is
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                return True
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            return False
    except OSError:
        return False


def check(cfg, ident: str) -> dict:
    """Really try one connection now. Returns {"ok", "status"}; never a key."""
    from jcc import mailer, quota, speech
    if ident in ("groq", "openai"):
        secret = secrets.get(ident)
        if not secret:
            return {"ok": False, "status": "No key is saved."}
        try:
            speech._json(speech.whisper_base(ident), "GET", "/models", {"Authorization": "Bearer " + secret}, who=ident.title())
        except (ValueError, OSError) as problem:
            return {"ok": False, "status": str(problem)[:200]}
        return {"ok": True, "status": "The key works."}
    if ident == "accounts":
        from jcc import online
        try:
            return {"ok": True, "status": online.verify(cfg)}
        except (ValueError, OSError) as problem:
            return {"ok": False, "status": str(problem)[:200]}
    if ident == "elevenlabs":
        if not secrets.get("elevenlabs"):
            return {"ok": False, "status": "No key is saved."}
        try:
            speech._cache.pop("usage", None)
            used = speech.usage(cfg)
            speech.voices(cfg)
        except (ValueError, OSError) as problem:
            return {"ok": False, "status": str(problem)[:200]}
        return {"ok": True, "status": "The key works." + (f" {used['percent']}% of this month's allowance used." if used else "")}
    if ident in ("claude", "codex"):
        reading = quota.refresh(cfg, only=ident).get(ident, {})
        if reading.get("error"):
            return {"ok": False, "status": str(reading["error"])[:200]}
        return {"ok": bool(reading.get("windows")), "status": "Signed in and answering." if reading.get("windows") else "It answered, but gave no account details."}
    if ident == "mail":
        try:
            return {"ok": True, "status": mailer.verify(cfg)}
        except (ValueError, OSError) as problem:
            return {"ok": False, "status": str(problem)[:200]}
    raise ValueError("That cannot be checked from here.")
