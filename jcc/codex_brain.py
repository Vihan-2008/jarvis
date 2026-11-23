"""ChatGPT as JARVIS's brain, through Codex: for an owner who signs in with a ChatGPT account (the free plan included)
instead of paying for an API key.

Codex is OpenAI's own program, and it holds the ChatGPT sign-in (jcc/accounts.py starts it, JARVIS never sees a token).
For each request JARVIS runs `codex exec` once, as a talker and not as a coder:
- with JARVIS's own instructions in place of Codex's coding ones (model_instructions_file), so it behaves as the assistant
  and each request costs far fewer tokens;
- with JARVIS's tools (the same helper Claude Code and the stand-ins use, jcc/voice_tools.py), and nothing else: no shell,
  no file editing (read-only sandbox, shell tool off), no apps, plugins, browser, computer use, memories or images of its own.
  Each of JARVIS's tools checks itself at the safety gate (jcc/policy.py), exactly as with Claude;
- with web search, as Claude has;
- without the owner's own Codex settings (--ignore-user-config) and without keeping a copy of the talk (--ephemeral).
Its events are turned into the same stream Claude Code sends, so the rest of the assistant does not care which brain is at
work. Codex starts afresh for each request, so the session keeps a short record of the talk and hands it back each time.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

from jcc.config import ROOT
from jcc.redact import redact
from jcc.vault import atomic_write

KEY = "chatgpt"                   # its name among the brains: ("api", "chatgpt", <model>)
NAME = "ChatGPT"
DEFAULT = "default"               # the model the owner's ChatGPT plan gives Codex (no -m)
QUIET = 300                       # Codex silent this long (no tool of JARVIS's at work) is stuck: it is stopped
TOOL_QUIET = 900                  # ...and this long while one of JARVIS's tools is at work (it may be asking the owner)
LONGEST = 3600                    # one request, at most: a request of many steps is not cut off half-way
LOOK = 2.0                        # how often the watch looks
REMEMBERED = 6                    # exchanges of this talk handed back with each request
# Codex's own abilities that a talker does not need. (A name an older or newer Codex does not know is only ignored.)
OFF = ("shell_tool", "unified_exec", "apps", "browser_use", "browser_use_external", "computer_use", "in_app_browser", "plugins", "memories",
       "image_generation", "multi_agent", "multi_agent_v2", "hooks", "goals", "skill_search", "tool_suggest", "remote_plugin")
PASSED = ("JCC_VOICE_PORT", "JCC_VOICE_KEY", "JCC_VOICE_SESSION", "JCC_VOICE_STATE", "JCC_VOICE_PC", "PYTHONPATH", "PYTHONIOENCODING")


def _event(event: dict) -> dict:
    return {"type": "stream_event", "event": event}


def _toml(value) -> str:
    """A value for `codex -c key=value`: TOML, which for strings and lists of strings is the same as JSON."""
    return json.dumps(value)


def command(exe: str, instructions: Path, work: Path, model: str = DEFAULT, python: str | None = None) -> list[str]:
    """The `codex exec` command for one request (the request itself goes in on stdin)."""
    python = python or _python()
    argv = [exe, "exec", "--json", "--ephemeral", "--ignore-user-config", "--skip-git-repo-check", "-s", "read-only", "-C", str(work)]
    for feature in OFF:
        argv += ["-c", f"features.{feature}=false"]
    argv += ["-c", 'web_search="live"', "-c", 'approval_policy="never"',
             "-c", "include_permissions_instructions=false", "-c", "include_environment_context=false",
             "-c", "model_instructions_file=" + _toml(str(instructions)),
             "-c", "mcp_servers.jarvis.command=" + _toml(python),
             "-c", "mcp_servers.jarvis.args=" + _toml(["-m", "jcc.voice_tools"]),
             "-c", "mcp_servers.jarvis.cwd=" + _toml(str(ROOT)),
             # The tools helper's key reaches it through the environment, never on a command line other programs can read.
             "-c", "mcp_servers.jarvis.env_vars=" + _toml(list(PASSED)),
             "-c", "mcp_servers.jarvis.startup_timeout_sec=30",
             # (a tool can take as long as the service lets it, 200 s for online accounts: Codex's own limit is shorter)
             "-c", "mcp_servers.jarvis.tool_timeout_sec=210",
             "-c", 'mcp_servers.jarvis.default_tools_approval_mode="approve"']
    if model and model != DEFAULT:
        argv += ["-m", model]
    return argv + ["-"]


def _python() -> str:
    python = Path(sys.executable)
    return str(python.with_name("python.exe") if python.name.lower() == "pythonw.exe" else python)


def available(cfg) -> bool:
    """Is Codex here and signed in with a ChatGPT account? (Read from jcc/accounts.py, which asks Codex at most every few minutes.)"""
    from jcc import accounts
    return accounts.chatgpt_ready(cfg)


class CodexSession:
    """One conversation with ChatGPT through Codex. Looks like a Claude Code session to the assistant."""

    engine = "codex"

    def __init__(self, cfg, model: str, system: str, ident: str, port: int, key: str, pc_control: bool, exe: str | None = None,
                 popen=subprocess.Popen):
        from jcc.agents import resolve_command
        self.cfg, self.model, self.id, self.popen = cfg, model or DEFAULT, ident, popen
        self.exe = exe or resolve_command("codex")
        if not self.exe:
            raise ValueError("Codex is not installed, so ChatGPT cannot answer. Install it in Settings, AI models & accounts.")
        self.work = cfg.state_dir / "assistant"
        self.work.mkdir(parents=True, exist_ok=True)
        self.instructions = self.work / f"codex-{ident}.md"
        atomic_write(self.instructions, system)
        from jcc.jobs import scrub_env
        # (No keys of the owner's pass to Codex: it answers with the ChatGPT sign-in only, never an API key it finds lying about.)
        self.env = {**scrub_env(dict(os.environ)), "PYTHONPATH": str(ROOT), "JCC_VOICE_PORT": str(port), "JCC_VOICE_KEY": key, "JCC_VOICE_SESSION": ident,
                    "JCC_VOICE_STATE": str(cfg.state_dir), "JCC_VOICE_PC": "1" if pc_control else "0", "PYTHONIOENCODING": "utf-8"}
        self.talk: list[tuple[str, str]] = []
        self.proc = None
        self.closed, self.lock = False, threading.Lock()
        self.turns, self.used, self.signature, self.key = 0, time.time(), None, KEY + ":" + self.model

    def alive(self) -> bool:
        return not self.closed

    def _asked(self, prompt: str) -> str:
        """The request, after a short record of the talk so far (Codex starts afresh each time)."""
        if not self.talk:
            return prompt
        lines = []
        for asked, answered in self.talk[-REMEMBERED:]:
            lines.append("User: " + " ".join(asked.split())[:600])
            lines.append("You: " + " ".join(answered.split())[:600])
        return "Earlier in this conversation (for context; already answered):\n" + "\n".join(lines) + "\n\nNow:\n" + prompt

    def events(self, prompt: str) -> Iterator[dict]:
        self.turns, self.used = self.turns + 1, time.time()
        argv = command(self.exe, self.instructions, self.work, self.model)
        try:
            with self.lock:
                if self.closed:
                    return
                self.proc = self.popen(argv, cwd=str(self.work), env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            proc = self.proc
        except OSError as problem:
            yield {"type": "result", "is_error": True, "result": "Codex could not be started: " + redact(str(problem))[:200], "usage": {}}
            return
        # Codex is stopped only when it has gone quiet, never because a request of several steps takes a while. (A fixed five
        # minutes for the whole request cut long ones off between their steps.)
        heard, tools, finished, stalled = [time.monotonic()], [0], threading.Event(), []
        began = heard[0]

        def watch():
            while not finished.wait(LOOK):
                now = time.monotonic()
                if now - began > LONGEST or now - heard[0] > (TOOL_QUIET if tools[0] > 0 else QUIET):
                    stalled.append(now - began > LONGEST)
                    self._kill()
                    return

        threading.Thread(target=watch, daemon=True, name="codex-watch").start()
        said, problem, usage, done, index = "", "", {}, False, 0
        try:
            proc.stdin.write(self._asked(prompt))
            proc.stdin.close()
            for raw in proc.stdout:
                heard[0] = time.monotonic()
                try:
                    data = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(data, dict):
                    continue
                kind, item = data.get("type"), data.get("item") if isinstance(data.get("item"), dict) else {}
                what = item.get("type")
                if what == "mcp_tool_call":
                    tools[0] = max(0, tools[0] + (1 if kind == "item.started" else -1 if kind == "item.completed" else 0))
                if kind == "item.started" and what == "mcp_tool_call":
                    index += 1
                    args = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
                    yield _event({"type": "content_block_start", "index": index, "content_block": {"type": "tool_use", "name": "mcp__jarvis__" + str(item.get("tool") or "")}})
                    yield _event({"type": "content_block_delta", "index": index, "delta": {"type": "input_json_delta", "partial_json": json.dumps(args)}})
                    yield _event({"type": "content_block_stop", "index": index})
                elif kind == "item.completed" and what == "web_search":
                    index += 1
                    yield _event({"type": "content_block_start", "index": index, "content_block": {"type": "tool_use", "name": "WebSearch"}})
                    yield _event({"type": "content_block_delta", "index": index, "delta": {"type": "input_json_delta",
                                                                                          "partial_json": json.dumps({"query": str(item.get("query") or "")})}})
                    yield _event({"type": "content_block_stop", "index": index})
                elif kind == "item.completed" and what == "agent_message" and str(item.get("text") or "").strip():
                    piece = ("\n\n" if said else "") + str(item["text"]).strip()
                    said += piece
                    yield _event({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": piece}})
                elif kind == "item.completed" and what == "error":
                    message = str(item.get("message") or "")
                    if not message.startswith("Codex is ignoring"):     # (a setting this version of Codex does not know: harmless)
                        problem = message
                elif kind == "error":
                    problem = str(data.get("message") or problem)
                elif kind == "turn.failed":
                    failed = data.get("error")
                    problem = str((failed or {}).get("message") if isinstance(failed, dict) else failed or problem or "ChatGPT could not answer.")
                elif kind == "turn.completed":
                    numbers = data.get("usage") if isinstance(data.get("usage"), dict) else {}
                    cached = int(numbers.get("cached_input_tokens") or 0)
                    usage = {"input": int(numbers.get("input_tokens") or 0), "cached": cached, "output": int(numbers.get("output_tokens") or 0)}
                    done = True
            proc.wait(timeout=10)
        except (OSError, ValueError, subprocess.TimeoutExpired) as trouble:
            problem = problem or "Codex stopped: " + str(trouble)
        finally:
            finished.set()
        if self.closed:
            return
        if stalled and not done:
            problem = ("ChatGPT (through Codex) worked on this for an hour without finishing, so it was stopped." if stalled[0] else
                       "ChatGPT (through Codex) stopped responding, so it was stopped.") + " Ask again to carry on."
        if done and (said or not problem):                 # (a passing complaint along the way does not undo an answer)
            self.talk.append((prompt[-1200:], said))
            del self.talk[:-REMEMBERED]
            yield {"type": "result", "is_error": False, "result": said, "usage": usage}
            return
        if not problem:
            try:
                problem = " ".join((proc.stderr.read() or "").split())[-300:]
            except (OSError, ValueError):
                problem = ""
        yield {"type": "result", "is_error": True, "result": redact(_plain(problem))[:300] or "ChatGPT (through Codex) stopped without answering.", "usage": usage}

    def _kill(self) -> None:
        proc = self.proc
        if proc and proc.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                proc.kill()

    def close(self) -> None:
        with self.lock:
            self.closed = True
        self._kill()
        try:
            self.instructions.unlink(missing_ok=True)
        except OSError:
            pass


def _plain(problem: str) -> str:
    """Codex's error, in words the owner can act on."""
    low = problem.lower()
    if "not logged in" in low or "login" in low and ("required" in low or "please" in low) or "401" in low:
        return "ChatGPT is not signed in. Sign in again in Settings, AI models & accounts. (" + problem[:160] + ")"
    return problem
