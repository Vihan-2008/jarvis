"""Live progress for a running reply: the steps an agent takes and the answer text so far.

The agent's streamed output is reduced to small events in <job folder>/live.jsonl. For Claude,
the stream is also condensed back to the single final result line, so everything after the run
(limits, usage, sessions) sees exactly what the non-streaming mode produced.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from jcc.redact import redact

MAX_BYTES = 400_000
STREAM_FLAGS = ["--output-format", "stream-json", "--verbose", "--include-partial-messages"]
_TOOLS = {"Read": "Reading", "Write": "Writing", "Edit": "Editing", "MultiEdit": "Editing", "NotebookEdit": "Editing",
          "Bash": "Running", "Grep": "Searching for", "Glob": "Looking for files", "WebSearch": "Searching the web for",
          "WebFetch": "Reading the web page", "Task": "Starting a helper for", "TodoWrite": "Updating its to-do list"}


def _short(value, limit=110) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _name(path) -> str:
    return str(path).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def describe_tool(name: str, data: dict) -> str:
    """One plain sentence for a tool call. Never includes file contents."""
    verb = _TOOLS.get(name, "Using " + name)
    if name in ("Read", "Write", "Edit", "MultiEdit", "NotebookEdit"):
        target = data.get("file_path") or data.get("notebook_path") or ""
        return f"{verb} {_name(target)}" if target else verb + " a file"
    if name == "Bash":
        return f"{verb}: {_short(data.get('command', ''), 90)}"
    if name in ("Grep", "Glob", "WebSearch", "Task"):
        return f"{verb} {_short(data.get('pattern') or data.get('query') or data.get('description') or '', 80)}".rstrip()
    if name == "WebFetch":
        return f"{verb} {_short(data.get('url', ''), 90)}"
    return verb


def plain_command(command) -> str:
    """Drop the shell wrapper Codex puts around a command, leaving what it actually runs."""
    text = str(command)
    match = re.match(r'^"?[^"]*?(?:powershell|pwsh|cmd|bash|sh)(?:\.exe)?"?\s+(?:-\w+\s+)*(?:-Command|-c|/c|-lc)\s+(.*)$', text, re.I | re.S)
    if match:
        text = match.group(1).strip()
        if len(text) > 1 and text[0] == text[-1] and text[0] in "\"'":
            text = text[1:-1]
    return text.replace("\\\\", "\\")


def partial_string(blob: str, key: str) -> str | None:
    """Decode the (possibly unfinished) JSON string value of `key` inside partial JSON text."""
    marker = f'"{key}"'
    at = blob.find(marker)
    if at < 0:
        return None
    start = blob.find('"', blob.find(":", at + len(marker)) + 1) if ":" in blob[at:] else -1
    if start < 0:
        return None
    out, i, n = [], start + 1, len(blob)
    simple = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f"}
    while i < n:
        ch = blob[i]
        if ch == '"':
            break
        if ch == "\\":
            if i + 1 >= n:
                break
            nxt = blob[i + 1]
            if nxt == "u":
                if i + 6 > n:
                    break
                try:
                    out.append(chr(int(blob[i + 2:i + 6], 16)))
                except ValueError:
                    break
                i += 6
                continue
            out.append(simple.get(nxt, nxt))
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


class Feed:
    """Consumes an agent's stdout line by line while it runs."""

    def __init__(self, provider: str, target: Path | None):
        self.provider, self.target = provider, target
        self.result_line: str | None = None
        self.plain: list[str] = []
        self.saw_json = False
        self.written = 0
        self.blocks: dict[int, dict] = {}
        self.answer = ""
        if target:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("", "utf-8")
            except OSError:
                self.target = None

    # ------------------------------------------------------------------ output
    def emit(self, kind: str, text: str) -> None:
        if not self.target or not text or self.written > MAX_BYTES:
            return
        row = json.dumps({"at": round(time.time(), 2), "k": kind, "t": redact(text)[:4000]}) + "\n"
        try:
            with self.target.open("a", encoding="utf-8") as out:
                out.write(row)
            self.written += len(row)
        except OSError:
            self.target = None

    def line(self, raw: str) -> None:
        text = raw.strip()
        if not text:
            return
        try:
            data = json.loads(text) if text[0] == "{" else None
        except ValueError:
            data = None
        if not isinstance(data, dict):
            self.plain.append(raw)
            return
        self.saw_json = True
        if self.provider == "claude":
            self._claude(data, raw)
        elif self.provider == "codex":
            self._codex(data)

    def output(self, stdout: str) -> str:
        """What the rest of the job should treat as the agent's output."""
        if self.provider != "claude" or not self.saw_json:
            return stdout
        return "".join(self.plain) + (self.result_line or "")

    # ------------------------------------------------------------------ Claude Code
    def _claude(self, data: dict, raw: str) -> None:
        kind = data.get("type")
        if kind == "result":
            self.result_line = raw if raw.endswith("\n") else raw + "\n"
            return
        if kind != "stream_event":
            return
        event = data.get("event") or {}
        what, index = event.get("type"), event.get("index", 0)
        if what == "content_block_start":
            block = event.get("content_block") or {}
            self.blocks[index] = {"type": block.get("type"), "name": block.get("name", ""), "json": "", "sent": 0}
            if block.get("type") == "thinking":
                self.emit("step", "Thinking it through")
        elif what == "content_block_delta":
            block, delta = self.blocks.get(index), event.get("delta") or {}
            if not block:
                return
            if delta.get("type") == "text_delta":
                self.emit("say", delta.get("text", ""))
            elif delta.get("type") == "input_json_delta":
                block["json"] += delta.get("partial_json", "")
                if block["name"] == "Write" and len(block["json"]) < 600_000:
                    target = partial_string(block["json"], "file_path")
                    if target and _name(target).upper() == "RESULT.MD":
                        body = partial_string(block["json"], "content") or ""
                        if len(body) > block["sent"]:
                            self.emit("answer", body[block["sent"]:])
                            block["sent"] = len(body)
        elif what == "content_block_stop":
            block = self.blocks.pop(index, None)
            if block and block["type"] == "tool_use":
                try:
                    args = json.loads(block["json"] or "{}")
                except ValueError:
                    args = {}
                if not (block["name"] == "Write" and _name(args.get("file_path", "")).upper() == "RESULT.MD"):
                    self.emit("step", describe_tool(block["name"], args if isinstance(args, dict) else {}))
                else:
                    self.emit("step", "Writing the reply")

    # ------------------------------------------------------------------ Codex
    def _codex(self, data: dict) -> None:
        item = data.get("item") if isinstance(data.get("item"), dict) else None
        if not item:
            return
        kind, done = item.get("type") or item.get("item_type"), data.get("type") == "item.completed"
        if kind == "command_execution" and data.get("type") == "item.started":
            self.emit("step", "Running: " + _short(plain_command(item.get("command", "")), 90))
        elif kind == "file_change" and done:
            names = [_name(c.get("path", "")) for c in item.get("changes", []) if isinstance(c, dict)]
            self.emit("step", "Changed " + (", ".join(n for n in names[:4] if n) or "files"))
        elif kind == "web_search" and done:
            self.emit("step", "Searched the web for " + _short(item.get("query", ""), 80))
        elif kind == "reasoning" and done:
            self.emit("step", _short(item.get("text", "") or "Thinking it through", 140))
        elif kind == "agent_message" and done:
            self.emit("say", str(item.get("text", "")) + "\n\n")


def read(cfg, rid: str) -> dict:
    """Steps and text so far for one request. Empty when nothing has streamed."""
    from jcc.activity import job_id
    work = cfg.jobs_root / job_id(rid)
    path = work / "live.jsonl"
    steps, said, answer = [], [], []
    if path.exists() and not path.is_symlink():
        try:
            lines = path.read_text("utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        for row in lines:
            try:
                event = json.loads(row)
            except ValueError:
                continue
            if event.get("k") == "step":
                if not steps or steps[-1]["text"] != event.get("t"):
                    steps.append({"at": event.get("at"), "text": event.get("t", "")})
            elif event.get("k") == "say":
                said.append(event.get("t", ""))
            elif event.get("k") == "answer":
                answer.append(event.get("t", ""))
    # The answer file is the reply; the agent's running commentary is shown only until it exists.
    text = "".join(answer) or "".join(said)
    return {"id": rid, "steps": steps[-60:], "text": text[-20000:], "answering": bool(answer)}


def with_stream(argv: list[str]) -> list[str]:
    """Swap Claude Code's single-result output for its streaming output."""
    out = list(argv)
    for i in range(len(out) - 1):
        if out[i] == "--output-format" and out[i + 1] == "json":
            return out[:i] + STREAM_FLAGS + out[i + 2:]
    return out


def streaming_supported(cfg) -> bool:
    return (cfg.raw.get("agents", {}).get("claude", {}).get("stream", True) is not False
            and not (cfg.state_dir / "claude-stream-unsupported").exists())


def stream_rejected(output: str) -> bool:
    """True only for an immediate argument error, never for an ordinary failed run."""
    text = output.lower()
    return len(output) < 3000 and "session_id" not in text and any(
        hint in text for hint in ("unknown option", "unknown argument", "unrecognized option", "invalid option",
                                  "error: option", "include-partial-messages", "requires --verbose"))


def mark_unsupported(cfg) -> None:
    try:
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        (cfg.state_dir / "claude-stream-unsupported").write_text(str(time.time()), "utf-8")
    except OSError:
        pass
