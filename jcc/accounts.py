"""Accounts: connecting JARVIS to the AIs by signing in with your own account (your Claude or
ChatGPT subscription), through the tools that hold those sign-ins: Claude Code (`claude auth`) and Codex (`codex login`).
API keys for other services stay where they were (Settings, AI models; jcc/providers.py).

Nothing about the sign-in passes through JARVIS: each tool runs its own sign-in (its own page in the browser, its own
window), keeps its own tokens where it always does, and JARVIS only asks it whether it is signed in. No token, no key
and no address is read, shown or stored here.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

from jcc import system

# Each account: its name, what it gives, and the tool's own commands (status, sign in, sign out).
ACCOUNTS = {
    "claude": {"name": "Claude", "about": "Your Claude subscription, through Claude Code. JARVIS's main AI.",
               "status": ["auth", "status", "--json"], "login": ["auth", "login", "--claudeai"], "logout": ["auth", "logout"],
               "install": "Install Claude Code (claude.com/claude-code), then press Sign in."},
    "codex": {"name": "ChatGPT", "about": "Your ChatGPT subscription, through Codex. A second AI for building software.",
              "status": ["login", "status"], "login": ["login"], "logout": ["logout"],
              "install": "Install the Codex CLI (developers.openai.com/codex), then press Sign in."},
}
_CACHE: dict[str, tuple[float, dict]] = {}
FRESH = 20.0


def _program(cfg, ident: str) -> str:
    from jcc import agents
    agent = cfg.agents.get(ident)
    if not agent or not agent.enabled:
        return ""
    return agents.resolve_command(agent.command[0]) or ""


def _run(argv: list[str], seconds: float = 20) -> tuple[int, str]:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=seconds,
                              stdin=subprocess.DEVNULL, creationflags=system.no_window())
        return done.returncode, (done.stdout or "") + (done.stderr or "")
    except (OSError, subprocess.SubprocessError) as problem:
        return 1, str(problem)


def read(output: str, ident: str, code: int) -> dict:
    """What a tool says about its sign-in, in a few words (never its tokens, nor the address it is signed in with)."""
    if ident == "claude":
        try:
            data = json.loads(output[output.index("{"):output.rindex("}") + 1])
        except ValueError:
            return {"signed_in": False, "how": ""}
        method = str(data.get("authMethod") or "")
        return {"signed_in": data.get("loggedIn") is True,
                "how": {"claude.ai": "with your Claude account", "console": "with an Anthropic Console account", "api_key": "with an API key"}.get(method, method)[:60]}
    text = " ".join(output.split())
    signed = code == 0 and "logged in" in text.lower() and "not logged in" not in text.lower()
    how = "with your ChatGPT account" if "chatgpt" in text.lower() else "with an API key" if "api key" in text.lower() else ""
    return {"signed_in": signed, "how": how}


def status(cfg, fresh: bool = False) -> list[dict]:
    rows = []
    for ident, spec in ACCOUNTS.items():
        program = _program(cfg, ident)
        row = {"id": ident, "name": spec["name"], "about": spec["about"], "installed": bool(program), "signed_in": False, "how": "", "install": spec["install"]}
        if program:
            known = _CACHE.get(ident)
            if known and not fresh and time.time() - known[0] < FRESH:
                row.update(known[1])
            else:
                code, out = _run([program, *spec["status"]])
                seen = read(out, ident, code)
                _CACHE[ident] = (time.time(), seen)
                row.update(seen)
        rows.append(row)
    return rows


def sign_in(cfg, ident: str) -> dict:
    """Start the tool's own sign-in: it opens its page in the browser (and a small window of its own, where it may ask to
    paste a code back). JARVIS does not see any of it; Settings shows the account once the tool says it is signed in."""
    spec = ACCOUNTS.get(ident)
    if not spec:
        raise ValueError("That is not an account JARVIS can sign in to.")
    program = _program(cfg, ident)
    if not program:
        raise ValueError(spec["install"])
    _CACHE.pop(ident, None)
    argv = [program, *spec["login"]]
    if os.name == "nt":
        subprocess.Popen(argv, creationflags=subprocess.CREATE_NEW_CONSOLE, stdin=None, stdout=None, stderr=None, close_fds=True)
    elif sys.platform == "darwin":
        script = " ".join("'" + a.replace("'", "'\\''") + "'" for a in argv)
        subprocess.Popen(["osascript", "-e", 'tell application "Terminal" to do script "' + script.replace("\\", "\\\\").replace('"', '\\"') + '"',
                          "-e", 'tell application "Terminal" to activate'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        terminal = next((t for t in ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm") if _which(t)), "")
        if not terminal:
            raise ValueError("Open a terminal and run: " + " ".join([os.path.basename(program), *spec["login"]]))
        subprocess.Popen([terminal, "-e", *argv], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"started": True, "name": spec["name"]}


def sign_out(cfg, ident: str) -> dict:
    spec = ACCOUNTS.get(ident)
    if not spec:
        raise ValueError("That is not an account JARVIS can sign out of.")
    program = _program(cfg, ident)
    if not program:
        raise ValueError(spec["name"] + " is not installed.")
    code, out = _run([program, *spec["logout"]], 30)
    _CACHE.pop(ident, None)
    if code != 0:
        raise ValueError((spec["name"] + " could not sign out: " + " ".join(out.split()))[:200])
    return {"signed_out": True}


def _which(name: str) -> str:
    import shutil
    return shutil.which(name) or ""
