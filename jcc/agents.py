"""Coding agents (Claude Code, Codex, Gemini CLI) driven headless on your existing subscriptions.

- Level -> ordered agent list from config; missing/disabled/cooling-down agents are skipped.
- Each agent runs in its NORMAL headless mode. Bypass flags are forbidden (checked on every argv).
- A usage-limit message puts that agent on cooldown and the job moves to the next agent.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
import subprocess
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jcc.config import AgentCfg, Config

FORBIDDEN_FLAGS = ("--dangerously-skip-permissions", "--allow-dangerously-skip-permissions", "bypassPermissions",
                   "--dangerously-bypass-approvals-and-sandbox", "--yolo", "danger-full-access",
                   "approval-mode=yolo")
LIMIT_PATTERNS = re.compile(
    r"usage limit|rate[- ]limit|quota (exceeded|reached)|exceeded your (current )?quota|"
    r"limit reached|hit your (?:[\w-]+ ){0,3}limit|\b(?:5-hour|five-hour|weekly|daily|session|monthly) limit\b|"
    r"\blimit\b.{0,30}\bresets?\b|too many requests|\b429\b|resource[_ ]exhausted|"
    r"out of (credits|messages)|try again (later|in|at)", re.IGNORECASE)

_LEVEL_RULES = [
    ("large", r"\b(architect\w*|redesign|rewrite|overhaul|migrat\w*|security|vulnerab\w*|"
              r"concurren\w*|race condition|risk engine|ledger|money|fees?|strategy|"
              r"multi[- ]file|across the (code|project)|whole (project|codebase)|from scratch)\b"),
    ("small", r"\b(typo|rename|comment|docstring|format\w*|lint|explain|readme|log message|"
              r"one[- ]line|tiny|small|bump|constant|wording|spelling)\b"),
    ("medium", r"\b(add|implement|fix|bug|feature|refactor|test|endpoint|function|improve|"
               r"optimi[sz]e|update|change)\b"),
]


def classify_level(task: str) -> str:
    t = task.lower()
    if not re.search(_LEVEL_RULES[0][1], t) and len(t.split()) <= 55 and re.search(
            r"\b(simple|small|tiny|single)\s+(helper|function|method|unit test|edit|fix)\b|\b(subtract|multiply|divide|greet)\s*\(", t):
        return "small"
    for level, pat in _LEVEL_RULES:
        if re.search(pat, t):
            # long, detailed requests are rarely "small"
            if level == "small" and len(t.split()) > 40:
                return "medium"
            return level
    if len(t.split()) < 35 and re.match(r"^(hi\b|hello\b|hey\b|what\b|who\b|where\b|why\b|how\b)", t):
        return "small"
    return "large" if len(t.split()) > 80 else "medium"


def is_limit_message(text: str) -> bool:
    return bool(LIMIT_PATTERNS.search(text or ""))


def is_signed_out(text: str) -> bool:
    """Did the agent stop because its sign-in or key is no longer good? (Trying it again at once cannot help then.)"""
    return bool(re.search(r"not (logged|signed) in|please (run [`'\"]?\w+ )?(log ?in|sign ?in)|\b(re-?)?(log ?in|sign ?in) (again|required|expired)|"
                          r"invalid (api )?key|authentication (failed|required|error)|unauthori[sz]ed|token (has )?expired|"
                          r"refresh token|credentials? (are |is )?(missing|invalid|expired)", text or "", re.I))


_SANDBOX_NEAR = r"(?:sandbox|logon|setup|elevat)"


def sandbox_trouble(text: str) -> str:
    """Why Codex's safe workspace on Windows could not start, if that is why it stopped: "declined" (the Windows
    permission prompt was answered No, error 1223), "blocked" (a Windows setting forbids it, error 1385), "setup" (it is
    not set up, or setting it up went wrong), or "". These fail the same way every time, so trying again does not help.
    The whole output is read: the reason can sit far from its end."""
    text = text or ""
    for kind, number in (("declined", "1223"), ("blocked", "1385")):
        near = r"[^\n]{0,80}"                               # (on the same line)
        if re.search(_SANDBOX_NEAR + near + r"\b" + number + r"\b|\b" + number + r"\b" + near + _SANDBOX_NEAR, text, re.I):
            return kind
    if re.search(r"windows sandbox failed|setup refresh had errors|helper_unknown_error|windows setup did not complete|"
                 r"sandbox setup (?:failed|is required|required)", text, re.I):
        return "setup"
    return ""


def last_words(out: str) -> str:
    """The reason an agent gave when it stopped: its last error message (Codex prints JSON events), or its last line."""
    for line in reversed([line.strip() for line in (out or "").splitlines() if line.strip()]):
        if line.startswith("{"):
            try:
                event = json.loads(line)
            except ValueError:
                continue
            failed = event.get("error") if isinstance(event, dict) else None
            said = (failed.get("message") if isinstance(failed, dict) else failed) or (event.get("message") if event.get("type") == "error" else "")
            if said and isinstance(said, str):
                return said[:240]
            continue
        return line[:240]
    return ""


def is_model_limit(text: str) -> bool:
    return bool(re.search(r"context (window|length)|maximum context|model.{0,60}(limit|quota)|"
                          r"(limit|quota).{0,60}model|model.{0,40}(unavailable|not found|not supported)|"
                          r"does not (exist|have access)|not have access to.{0,30}model", text, re.I))


def model_options(agent: AgentCfg, level: str) -> list[str]:
    order = [level, *(["medium", "small"] if level == "large" else
                      ["large", "small"] if level == "medium" else ["medium", "large"])]
    return list(dict.fromkeys(agent.models.get(lvl, "") for lvl in order))


def available(agent: AgentCfg) -> bool:
    return agent.enabled and bool(resolve_command(agent.command[0]))


def _program(path: str) -> bool:
    """Is this something Windows starts as a program itself? A launcher script (.cmd, .bat, .ps1, or the script npm puts
    beside them) is started through cmd.exe, which reads the whole command line again by its own rules: words in a request
    (a quote, an &, a %NAME%) could then be taken for commands. Requests are given to an agent on its command line, so only
    a program itself is ever started; an agent that is installed only as a launcher counts as not installed."""
    return os.name != "nt" or Path(path).suffix.lower() in (".exe", ".com")


# Where the coding CLIs are usually installed on a Mac or on Linux. An app started from the Dock or Finder does not get
# the PATH a terminal has, so these are looked at when the PATH has nothing.
USUAL_PLACES = ("~/.local/bin", "~/.claude/local", "/opt/homebrew/bin", "/usr/local/bin", "~/.npm-global/bin", "~/.volta/bin", "~/bin")


def _usual_place(command: str, places=USUAL_PLACES) -> str | None:
    if "/" in command or "\\" in command:
        return None
    for place in places:
        candidate = Path(os.path.expanduser(place)) / command
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


@lru_cache(maxsize=16)
def resolve_command(command: str) -> str | None:
    if os.name == "nt" and not Path(command).suffix:
        windows_exe = shutil.which(command + ".exe")
        if windows_exe:
            return windows_exe
    found = shutil.which(command)
    if found and _program(found):
        return found
    if Path(command).is_file() and _program(command):
        return str(Path(command))
    if os.name == "nt" and command == "claude":
        candidate = Path.home() / ".local/bin/claude.exe"
        if candidate.exists():
            return str(candidate)
    if os.name != "nt":
        return _usual_place(command)
    if os.name == "nt" and command == "codex":
        # OpenAI's own installer (chatgpt.com/codex/install.ps1), then the program inside an npm install (whose codex.cmd
        # launcher is not started; see _program), then the Codex desktop app's copy.
        local, roaming = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local"), Path(os.environ.get("APPDATA") or Path.home() / "AppData/Roaming")
        candidate = local / "Programs/OpenAI/Codex/bin/codex.exe"
        if candidate.is_file():
            return str(candidate)
        package = roaming / "npm/node_modules/@openai/codex"
        if package.is_dir():
            found_exe = next((str(p) for p in package.rglob("codex.exe") if "vendor" in p.parts), None)
            if found_exe:
                return found_exe
        try:
            result = subprocess.run(["powershell", "-NoProfile", "-Command",
                "(Get-AppxPackage -Name OpenAI.Codex).InstallLocation"], capture_output=True,
                text=True, timeout=12, creationflags=subprocess.CREATE_NO_WINDOW)
            candidate = Path(result.stdout.strip()) / "app/resources/codex.exe"
            if candidate.is_file():
                return str(candidate)
        except (OSError, subprocess.TimeoutExpired):
            pass
    return None


@dataclass
class Plan:
    level: str
    agents: list[str]     # in the order they will be tried
    skipped: dict[str, str]


def plan(cfg: Config, task: str, cooldowns: dict[str, float], prefer: str | None = None,
         level: str | None = None) -> Plan:
    level = level or classify_level(task)
    order = list(cfg.levels.get(level, ["claude"]))
    if prefer and prefer in cfg.agents:
        order = [prefer] + [a for a in order if a != prefer]
    # every enabled agent is a last-resort fallback, so a limit on one never strands the job
    order += [a for a in cfg.agents if a not in order]
    chosen, skipped = [], {}
    now = time.time()
    for name in order:
        a = cfg.agents.get(name)
        if a is None:
            skipped[name] = "not configured"
        elif not a.enabled:
            skipped[name] = "disabled"
        elif not available(a):
            skipped[name] = "not installed"
        elif cooldowns.get(name, 0) > now:
            mins = int((cooldowns[name] - now) / 60)
            skipped[name] = f"resting after a usage limit or an error, back in ~{max(1, mins)} min"
        else:
            from jcc.quota import blocked
            reason = blocked(cfg, name)
            if reason:
                skipped[name] = reason
            else:
                chosen.append(name)
    return Plan(level, chosen, skipped)


def claude_tools(kind: str, level: str, shell: bool, notebooks: bool = False) -> str:
    """The built-in tools a Claude Code job is given: only the ones it can use.

    Every tool's description is sent again on every step of a job. The full set is 18,700 tokens; a coding job needs
    about half of that, a rewrite or a review hardly any. What a job may do is unchanged: that is decided by its
    permissions, and nothing that was allowed is left out here."""
    if kind == "rewrite":
        return "Write"                                      # it writes one file with the new wording
    if kind == "review":
        return ""                                           # it reads what it is handed and answers
    names = ["Read", "Edit", "Write", "Glob", "Grep"] + (["Bash"] if shell else []) + ["WebSearch", "WebFetch"]
    if notebooks:
        names.append("NotebookEdit")
    if level == "large":
        names.append("Task")                                # helpers for wide searches: worth their two thousand tokens on a big job only
    return ",".join(names)


def build_argv(agent: AgentCfg, level: str, prompt: str, workdir: Path,
               permissions: dict[str, list[str]] | None = None, effort: str = "auto", session_id: str | None = None,
               tools: str | None = None, advisor: str = "") -> list[str]:
    exe = resolve_command(agent.command[0]) or agent.command[0]
    base = [exe, *agent.command[1:]]
    model = agent.models.get(level, "")
    perms = permissions or {}
    if agent.name == "claude":
        argv = base + ["-p", prompt, "--output-format", "json", "--permission-mode", "default",
                       "--disable-slash-commands", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                       "--setting-sources", "",
                       # The folder, the date and the like go into the first message instead of the instructions. Every job runs
                       # in its own folder; this way they all share the cached instructions instead of each rewriting them.
                       "--exclude-dynamic-system-prompt-sections"]
        if session_id:
            argv += ["--resume", session_id]
        if tools is not None:
            argv += ["--tools", tools]
        if model:
            argv += ["--model", model]
        if effort != "auto" and model != "haiku":
            argv += ["--effort", effort if effort != "ultra" else "max"]
        if perms.get("allow"):
            argv += ["--allowedTools", *perms["allow"]]
        if perms.get("deny"):
            argv += ["--disallowedTools", *perms["deny"]]
        if advisor:
            # /advisor: as a setting, not --advisor, so a model Claude Code will not pair with the job's own is simply
            # left out (the flag would stop the job at launch). (Its own settings files are not read: --setting-sources "".)
            argv += ["--settings", json.dumps({"advisorModel": advisor})]
    elif agent.name == "codex":
        # workspace-write: commands may only write inside the job folder; network is off.
        argv = base + ["exec", "--json", "--ignore-user-config", "--sandbox", "workspace-write", "--skip-git-repo-check",
                       "-C", str(workdir)]
        argv += ["-c", "model_reasoning_effort=" + (effort if effort != "auto" else {"small": "low", "medium": "medium", "large": "high"}[level])]
        argv += ["-c", 'web_search="live"']
        if os.name == "nt":
            argv += ["-c", 'windows.sandbox="elevated"']
        if model:
            argv += ["-m", model]
        if session_id:
            argv += ["resume", session_id]
        argv.append(prompt)
    elif agent.name == "grok":
        # Grok's own agent, run once with no window. It gets its file tools and nothing else: no shell (JARVIS runs the
        # project's checks itself), and only what is allowed below is ever done. Asked for anything else, a run with no
        # window cannot ask its owner, so Grok stops there (see grok_outcome).
        argv = base + ["-p", prompt + GROK_NOTE, "--output-format", "json", "--no-auto-update", "--cwd", str(workdir),
                       "--permission-mode", "dontAsk", "--disallowed-tools", "run_terminal_cmd"]
        for rule in grok_rules(perms)["allow"]:
            argv += ["--allow", rule]
        for rule in grok_rules(perms)["deny"]:
            argv += ["--deny", rule]
        if os.name != "nt":
            argv += ["--sandbox", "workspace"]         # (kept to the job's folder by the system itself, where the system can)
        if model:
            argv += ["-m", model]
        if effort != "auto":
            argv += ["--effort", effort if effort != "ultra" else "max"]
        if session_id:
            argv += ["-r", session_id]
    elif agent.name == "gemini":
        # auto_edit approves file edits only; shell commands are not available headless.
        argv = base + ["-p", prompt, "--approval-mode", "auto_edit"]
        if model:
            argv += ["-m", model]
    else:  # generic/test agent: prompt as the last argument
        argv = base + [prompt]
    joined = " ".join(argv)
    for flag in FORBIDDEN_FLAGS:
        if flag in joined:
            raise ValueError(f"refusing bypass flag {flag}")
    return argv


GROK_NOTE = ("\n\n(You have no shell in this job: read and change files with your file tools, inside this folder only. "
             "JARVIS runs the project's checks itself when you finish.)")


def grok_rules(permissions: dict[str, list[str]] | None) -> dict[str, list[str]]:
    """What a Grok job may do, in Grok's own rule words: read, search and change files in the job's folder, and look
    things up on the web. What a Claude job is denied by path (protected folders, keys) is denied here too."""
    deny = ["Read(**/.env)", "Read(**/.env.*)", "Edit(**/.env)", "Edit(**/.env.*)", "Read(~/.ssh/**)", "Edit(~/.ssh/**)"]
    for rule in (permissions or {}).get("deny") or []:
        kind, _, rest = str(rule).partition("(")
        path = rest[:-1] if rest.endswith(")") else ""
        # (Claude's rules name a Windows folder twice, as //c/... and as C:/...: Grok reads the second form.)
        if kind in ("Read", "Edit") and path and not path.startswith("//") and not path.startswith("**") and not path.startswith("~"):
            deny.append(f"{kind}({path})")
    return {"allow": ["Read(./**)", "Edit(./**)", "WebSearch"], "deny": list(dict.fromkeys(deny))}


def grok_outcome(code: int, out: str) -> tuple[int, str, str]:
    """(exit code, what to keep as the run's output, what Grok said at the end).

    Grok answers with one piece of JSON, and it exits with 0 even when it stopped half-way: asked for something that
    is not allowed, a run with no window cannot ask its owner, so it stops and says "cancelled" (seen in real runs,
    15 Nov 2026). That is not a finished job: it is given an exit code that says so, with Grok's own reason. The
    session and what was used are written out again in the one-line form the rest of the app reads."""
    start = out.find("{")
    answer = None
    while start >= 0 and answer is None:
        try:
            answer, _ = json.JSONDecoder().raw_decode(out[start:])
        except ValueError:
            start = out.find("{", start + 1)
    if not isinstance(answer, dict) or "stopReason" not in answer:
        return code, out, ""
    said = str(answer.get("text") or "").strip()
    used = answer.get("usage") if isinstance(answer.get("usage"), dict) else {}
    kept = json.dumps({"session_id": answer.get("sessionId"), "usage": {k: used.get(k) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens")}})
    rest = out[:start].strip()
    tail = out[start:]
    after = tail[tail.rfind("}") + 1:].strip() if "}" in tail else ""
    why = " ".join((rest + " " + after).split())[-400:]
    if code == 0 and answer.get("stopReason") != "end_turn":
        code = 1
        said_why = why or "it did not say why"
        return code, f"{said}\nGrok stopped before it had finished ({answer.get('stopReason')}): {said_why}\n{kept}", said
    return code, f"{said}\n{why}\n{kept}".strip(), said


def _forms(p: Path) -> list[str]:
    """The ways Claude Code's permission rules can name a folder: "//" starts a path from the root of the disk, so
    C:/work becomes //c/work on Windows and /Users/me/work becomes //Users/me/work elsewhere; the plain form is kept too."""
    posix = Path(os.path.abspath(p)).as_posix()
    if posix.startswith("/"):
        return [f"/{posix}", posix]
    return [f"//{posix[0].lower()}{posix[2:]}", posix]


def claude_permissions(workdir: Path, protected: list[Path], python: Path | None = None,
                       checks: list[list[str]] | None = None) -> dict[str, list[str]]:
    """Allow: read/edit only the job folder, search, web, and the project's check commands.
    Deny: protected folders (incl. the project's real checkout), secrets, push/ssh/deletes."""
    allow = ["Glob", "Grep", "WebSearch", "WebFetch"]
    for f in _forms(workdir):
        allow += [f"Read({f}/**)", f"Edit({f}/**)", f"Write({f}/**)"]
    if python is not None:
        for exe in {Path(os.path.abspath(python)).as_posix(), str(Path(os.path.abspath(python)))}:
            for chk in checks or []:
                allow.append(f"Bash({exe} {' '.join(chk[:2])}:*)")
        allow += ["Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)"]
    deny: list[str] = []
    for p in protected:
        for f in _forms(p):
            deny += [f"Read({f}/**)", f"Edit({f}/**)", f"Write({f}/**)"]
    deny += ["PowerShell", "Read(**/.env)", "Read(**/.env.*)", "Read(~/.ssh/**)", "Edit(~/.ssh/**)",
             "Bash(git push:*)", "Bash(git remote:*)", "Bash(git commit:*)", "Bash(git reset:*)",
             "Bash(ssh:*)", "Bash(scp:*)", "Bash(curl:*)", "Bash(rm:*)", "Bash(del:*)",
             "Bash(docker:*)", "Bash(gh:*)", "Bash(powershell:*)", "Bash(pwsh:*)"]
    if python is None:
        deny.append("Bash")  # plain jobs (no project) get no shell at all
    return {"allow": allow, "deny": deny}


def agent_summary(cfg: Config, cooldowns: dict[str, float]) -> dict[str, Any]:
    now = time.time()
    out = {}
    for name, a in cfg.agents.items():
        state = ("disabled" if not a.enabled else "not installed" if not available(a)
                 else "cooling down" if cooldowns.get(name, 0) > now else "ready")
        from jcc.quota import blocked
        if state == "ready" and blocked(cfg, name):
            state = "allowance low"
        out[name] = {"state": state, "until": cooldowns.get(name) if state == "cooling down"
                     else None}
    return out
