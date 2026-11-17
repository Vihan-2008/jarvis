"""Accounts: connecting JARVIS to the AIs by signing in with your own account (your Claude or
ChatGPT subscription), through the tools that hold those sign-ins: Claude Code (`claude auth`) and Codex (`codex login`).
API keys for other services stay where they were (Settings, AI models; jcc/providers.py).

Nothing about the sign-in passes through JARVIS: each tool runs its own sign-in (its own page in the browser, its own
window), keeps its own tokens where it always does, and JARVIS only asks it whether it is signed in. No token, no key
and no address is read, shown or stored here.

Which plans work: ChatGPT's free plan includes Codex, so a free ChatGPT account answers as JARVIS's brain
(jcc/codex_brain.py) and builds software, with no key. Claude's free plan does not include Claude Code, and Anthropic
offers no other way for an app to use a free Claude account, so JARVIS says so plainly and answers with ChatGPT or a
free key instead.

When a tool is not installed, Install and sign in runs its maker's own installer (from chatgpt.com or claude.ai, the
commands their install pages give) in a window the owner can see, and then its sign-in.
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
    "claude": {"name": "Claude", "about": "Your Claude subscription (Pro or Max), through Claude Code. JARVIS's main AI.",
               "status": ["auth", "status", "--json"], "login": ["auth", "login", "--claudeai"], "logout": ["auth", "logout"],
               "install": "Install Claude Code (claude.com/claude-code), then press Sign in."},
    "codex": {"name": "ChatGPT", "about": "Your ChatGPT account, the free plan included, through Codex: JARVIS's mind when Claude cannot answer (or when you pick it), and a second AI for building software.",
              "status": ["login", "status"], "login": ["login"], "logout": ["logout"],
              "install": "Install the Codex CLI (developers.openai.com/codex), then press Sign in."},
}
_CACHE: dict[str, tuple[float, dict]] = {}
FRESH = 20.0
SETTLED = 300.0                   # how old a reading may be when only deciding which brain answers
FREE_CLAUDE = ("Claude's free plan does not include Claude Code, which is how JARVIS uses a Claude account. JARVIS answers with "
               "ChatGPT (a free ChatGPT account works) or a free key instead. Claude Pro or Max would make Claude JARVIS's brain.")
# Each maker's own installer, as its install page gives it, followed by the sign-in. (Windows: PowerShell; Mac: Terminal.)
INSTALLERS = {
    "claude": {"windows": "irm https://claude.ai/install.ps1 | iex; & \"$env:USERPROFILE\\.local\\bin\\claude.exe\" auth login --claudeai",
               "mac": "curl -fsSL https://claude.ai/install.sh | bash && ~/.local/bin/claude auth login --claudeai"},
    "codex": {"windows": "irm https://chatgpt.com/codex/install.ps1 | iex; & \"$env:LOCALAPPDATA\\Programs\\OpenAI\\Codex\\bin\\codex.exe\" login",
              "mac": "curl -fsSL https://chatgpt.com/codex/install.sh | sh && ~/.local/bin/codex login"},
}


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
        plan = str(data.get("subscriptionType") or data.get("planTier") or "").lower()[:20]
        out = {"signed_in": data.get("loggedIn") is True,
               "how": {"claude.ai": "with your Claude account", "console": "with an Anthropic Console account", "api_key": "with an API key"}.get(method, method)[:60]}
        if plan:
            out["plan"] = plan
        if out["signed_in"] and method == "claude.ai" and plan == "free":
            out["note"] = FREE_CLAUDE
        return out
    text = " ".join(output.split())
    signed = code == 0 and "logged in" in text.lower() and "not logged in" not in text.lower()
    how = "with your ChatGPT account" if "chatgpt" in text.lower() else "with an API key" if "api key" in text.lower() else ""
    return {"signed_in": signed, "how": how}


def _one(cfg, ident: str, fresh: bool = False, most: float = FRESH) -> dict:
    spec = ACCOUNTS[ident]
    program = _program(cfg, ident)
    row = {"id": ident, "name": spec["name"], "about": spec["about"], "installed": bool(program), "signed_in": False, "how": "", "install": spec["install"],
           "can_install": system.kind() in INSTALLERS[ident]}
    if program:
        known = _CACHE.get(ident)
        if known and not fresh and time.time() - known[0] < most:
            row.update(known[1])
        else:
            code, out = _run([program, *spec["status"]])
            seen = read(out, ident, code)
            _CACHE[ident] = (time.time(), seen)
            row.update(seen)
    return row


def status(cfg, fresh: bool = False, most: float = FRESH) -> list[dict]:
    if fresh:
        from jcc import agents
        agents.resolve_command.cache_clear()             # (it may have been installed a moment ago)
    return [_one(cfg, ident, fresh, most) for ident in ACCOUNTS]


_READING: set[str] = set()


def known(cfg, ident: str, wait: bool = True) -> dict:
    """What is known of one account when only choosing which brain answers. A reading up to a few minutes old does; an
    older one is used while it is read again in the background, so no request waits for it. With none at all it is read
    now, or (wait=False) {} is returned and it is read in the background."""
    held = _CACHE.get(ident)
    if held and time.time() - held[0] < SETTLED:
        return {"installed": True, **held[1]}
    if held or not wait:
        if ident not in _READING:
            _READING.add(ident)

            def again():
                try:
                    _one(cfg, ident, most=0)
                finally:
                    _READING.discard(ident)
            import threading
            threading.Thread(target=again, daemon=True, name="account-" + ident).start()
        return {"installed": True, **held[1]} if held else {}
    return _one(cfg, ident, most=SETTLED)


def chatgpt_ready(cfg, wait: bool = True) -> bool:
    """Can ChatGPT answer as JARVIS's brain: Codex installed and signed in (jcc/codex_brain.py)."""
    row = known(cfg, "codex", wait)
    return bool(row.get("installed") and row.get("signed_in"))


def install(cfg, ident: str) -> dict:
    """Install the tool with its maker's own installer, then start its sign-in, in a window the owner can see."""
    spec, kind = ACCOUNTS.get(ident), system.kind()
    if not spec:
        raise ValueError("That is not an account JARVIS can set up.")
    script = INSTALLERS[ident].get(kind)
    if not script:
        raise ValueError(spec["install"])
    _CACHE.pop(ident, None)
    if os.name == "nt":
        whole = ("Write-Host 'Installing " + spec["name"] + "''s app from its maker, then signing in...'; " + script +
                 "; Write-Host ''; Read-Host 'Finished. Press Enter to close this window'")
        subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", whole], creationflags=subprocess.CREATE_NEW_CONSOLE, close_fds=True)
    else:
        subprocess.Popen(["osascript", "-e", 'tell application "Terminal" to do script "' + script.replace("\\", "\\\\").replace('"', '\\"') + '"',
                          "-e", 'tell application "Terminal" to activate'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    from jcc import agents
    agents.resolve_command.cache_clear()
    return {"started": True, "name": spec["name"]}


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
