"""Connectors: extra tools the owner adds (a calendar, Gmail, a database...), for the assistant to use. They are MCP
servers, kept in connectors.json in JARVIS's settings folder in the same format as Claude's MCP settings.

Adding one needs no file editing: paste its link, its command, or the setup JSON from its instructions, or bring in the
ones already set up in Claude Desktop or Claude Code. Anything secret in it (header values such as an Authorization
token, and environment values, arguments or link parameters that look like keys) goes into the system's key store; the
file keeps a placeholder, ${JCC_CONNECTOR_...}, which Claude Code fills in from the assistant's environment when it
starts the connector. JARVIS puts those values in that environment only (jcc/assistant.py), and its own tool server takes
them out again before it runs anything (jcc/voice_tools.py), so a command the assistant runs never sees them.

Test starts a connector the way the assistant would and lists its tools.
"""
from __future__ import annotations

import json
import os
import queue
import re
import shlex
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from jcc import secrets
from jcc.redact import redact, register_secret
from jcc.vault import atomic_write, read_json

NAME = re.compile(r"[\w-]{1,40}")
PLACEHOLDER = re.compile(r"\$\{(JCC_CONNECTOR_[A-Z0-9_]+)\}")
SECRET_NAME = re.compile(r"key|token|secret|password|passwd|credential|auth|bearer|cookie|session|\bpat\b|_pat\b", re.I)
KEY_SHAPE = re.compile(r"(?:sk|pk|rk|ghp|gho|ghu|ghs|github_pat|xox[abpr]|AIza|shpat|IST|ntn|secret|lin_api|sbp)[\w.\-]{10,}|"
                       r"(?=[A-Za-z0-9_\-.]*\d)(?=[A-Za-z0-9_\-.]*[A-Za-z])[A-Za-z0-9_\-.]{28,}")


class ConnectorError(ValueError):
    """Said to the owner as it is."""


def _file(cfg) -> Path:
    return cfg.state_dir / "connectors.json"


def _load(cfg) -> dict:
    data = read_json(_file(cfg), {})
    data = data if isinstance(data, dict) else {}
    servers = data.get("mcpServers") if isinstance(data.get("mcpServers"), dict) else {}
    held = data.get("secrets") if isinstance(data.get("secrets"), dict) else {}
    return {"mcpServers": {k: v for k, v in servers.items() if isinstance(v, dict)}, "secrets": held}


def _save(cfg, data: dict) -> None:
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(_file(cfg), json.dumps(data, indent=1))


def _key_name(var: str) -> str:
    return "c-" + var


# ---------------------------------------------------------------------------------------------- what is there
def _masked(text: str) -> str:
    return PLACEHOLDER.sub("•••", str(text))


def describe(name: str, entry: dict) -> dict:
    if entry.get("url"):
        kind, where = "link", _masked(entry["url"])
    else:
        kind, where = "program", _masked(" ".join([str(entry.get("command", ""))] + [str(a) for a in entry.get("args") or []]))
    return {"name": name, "kind": kind, "where": where[:240], "type": entry.get("type") or ("http" if entry.get("url") else "stdio"),
            "secrets": len(PLACEHOLDER.findall(json.dumps(entry)))}


def listing(cfg) -> list[dict]:
    return [describe(name, entry) for name, entry in sorted(_load(cfg)["mcpServers"].items())]


# ------------------------------------------------------------------------------------------------ adding one
def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").upper()[:24] or "X"


def _name_from(entry: dict) -> str:
    if entry.get("url"):
        host = urllib.parse.urlsplit(str(entry["url"])).hostname or "connector"
        parts = [p for p in host.split(".") if p not in ("www", "mcp", "api", "com", "net", "org", "io", "dev", "app", "ai")]
        return (parts[0] if parts else host.split(".")[0])[:40]
    words = [str(a) for a in [entry.get("command", "")] + list(entry.get("args") or []) if not str(a).startswith("-")]
    package = next((w for w in reversed(words) if "/" in w or "server" in w.lower()), words[-1] if words else "connector")
    tail = re.split(r"[\\/]", package)[-1]
    tail = re.sub(r"^(?:mcp-server-|server-|mcp-)|(?:-mcp-server|-mcp|-server)$|@[\d.]+$|\.(?:exe|cmd|js|py)$", "", tail, flags=re.I)
    return re.sub(r"[^\w-]+", "-", tail).strip("-")[:40] or "connector"


def parse(text: str, name: str = "", token: str = "") -> dict[str, dict]:
    """What the owner pasted, as {name: entry}: setup JSON (Claude's mcpServers, or one server), a link, or a command."""
    text = str(text or "").strip()
    name = str(name or "").strip()
    if not text:
        raise ConnectorError("Paste the connector's link, its command, or the setup from its instructions.")
    found: dict[str, dict] = {}
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except ValueError:
            raise ConnectorError("That setup is not valid JSON. Copy all of it, from the first { to the last }.") from None
        if isinstance(data.get("mcpServers"), dict):
            found = data["mcpServers"]
        elif isinstance(data.get("servers"), dict):                    # (VS Code's way of writing the same thing)
            found = data["servers"]
        elif "command" in data or "url" in data:
            found = {name or _name_from(data): data}
        elif all(isinstance(v, dict) for v in data.values()):
            found = data
    elif re.match(r"^https?://", text, re.I):
        found = {name or "": {"type": "http", "url": text}}
    else:
        try:
            parts = shlex.split(text, posix=os.name != "nt")
        except ValueError:
            raise ConnectorError("That command could not be read: check its quotes.") from None
        parts = [p[1:-1] if len(p) > 1 and p[0] == p[-1] == '"' else p for p in parts]
        if not parts:
            raise ConnectorError("Paste the connector's link, its command, or the setup from its instructions.")
        found = {name or "": {"type": "stdio", "command": parts[0], "args": parts[1:]}}
    if not found:
        raise ConnectorError("No connector was found in that. Paste a link (https://...), a command (such as npx -y ...), or the setup JSON.")
    out = {}
    for key, entry in found.items():
        entry = _clean(entry)
        label = (name if len(found) == 1 and name else key) or _name_from(entry)
        label = re.sub(r"[^\w-]+", "-", str(label)).strip("-")[:40]
        if not NAME.fullmatch(label or "") or label == "jarvis":
            raise ConnectorError(f"“{label}” cannot be a connector's name: use letters, digits and dashes (and not “jarvis”).")
        if token and entry.get("url"):
            entry.setdefault("headers", {})["Authorization"] = token if re.match(r"^(?:Bearer|Basic|Token)\s", token) else "Bearer " + token
        out[label] = entry
    return out


def _clean(entry) -> dict:
    if not isinstance(entry, dict):
        raise ConnectorError("A connector's setup must say a command to run or a link.")
    out: dict = {}
    if entry.get("url"):
        url = str(entry["url"]).strip()
        parts = urllib.parse.urlsplit(url)
        local = (parts.hostname or "") in ("127.0.0.1", "localhost", "::1")
        if parts.scheme not in ("https", "http") or (parts.scheme == "http" and not local) or not parts.hostname:
            raise ConnectorError("A connector's link must start with https:// (http:// only for this computer).")
        kind = str(entry.get("type") or "http").lower()
        out = {"type": "sse" if kind == "sse" else "http", "url": url}
        if isinstance(entry.get("headers"), dict):
            out["headers"] = {str(k)[:80]: str(v)[:4000] for k, v in entry["headers"].items()}
    elif entry.get("command"):
        out = {"type": "stdio", "command": str(entry["command"])[:500]}
        args = entry.get("args") or []
        if not isinstance(args, list):
            raise ConnectorError("A connector's args must be a list.")
        out["args"] = [str(a)[:2000] for a in args][:60]
        if isinstance(entry.get("env"), dict):
            out["env"] = {str(k)[:80]: str(v)[:4000] for k, v in entry["env"].items()}
        if entry.get("cwd"):
            out["cwd"] = str(entry["cwd"])[:500]
    else:
        raise ConnectorError("A connector's setup must say a command to run or a link.")
    return out


def _secretish(value: str) -> bool:
    return bool(value) and not PLACEHOLDER.fullmatch(value) and not value.startswith("${") and bool(KEY_SHAPE.fullmatch(value.split()[-1]))


def seal(name: str, entry: dict) -> tuple[dict, dict[str, str]]:
    """The entry with its secrets replaced by placeholders, and {placeholder variable: secret value}."""
    taken: dict[str, str] = {}
    entry = json.loads(json.dumps(entry))

    def hide(value: str, what: str) -> str:
        var = f"JCC_CONNECTOR_{_slug(name)}_{_slug(what)}"
        number, base = 2, var
        while var in taken:
            var, number = f"{base}_{number}", number + 1
        taken[var] = value
        register_secret(value)
        return "${" + var + "}"

    for header, value in list((entry.get("headers") or {}).items()):
        if value and not PLACEHOLDER.search(value):
            entry["headers"][header] = hide(value, header)
    for var, value in list((entry.get("env") or {}).items()):
        if value and not value.startswith("${") and (SECRET_NAME.search(var) or _secretish(value)):
            entry["env"][var] = hide(value, var)
    args = entry.get("args") or []
    for i, arg in enumerate(args):
        flag, eq, value = arg.partition("=")
        if eq and flag.startswith("-") and SECRET_NAME.search(flag) and value and not value.startswith("${"):
            args[i] = flag + "=" + hide(value, flag)
        elif i and str(args[i - 1]).startswith("-") and SECRET_NAME.search(str(args[i - 1])) and arg and not arg.startswith(("-", "${")):
            args[i] = hide(arg, str(args[i - 1]))
        elif _secretish(arg):
            args[i] = hide(arg, f"arg{i}")
    if entry.get("url"):
        parts = urllib.parse.urlsplit(entry["url"])
        if any(SECRET_NAME.search(k) for k, _ in urllib.parse.parse_qsl(parts.query)):
            entry["url"] = hide(entry["url"], "url")
    return entry, taken


def add(cfg, text: str, name: str = "", token: str = "") -> list[dict]:
    """Add what was pasted. Its secrets go into the key store; connectors.json keeps placeholders."""
    found = parse(text, name, token)
    data = _load(cfg)
    clash = [label for label in found if label in data["mcpServers"]]
    if clash:
        raise ConnectorError("There is a connector called " + ", ".join(clash) + " already. Give this one another name, or remove that one first.")
    for label, entry in found.items():
        sealed, taken = seal(label, entry)
        for var, value in taken.items():
            secrets.store(_key_name(var), value)
        data["mcpServers"][label] = sealed
        data["secrets"][label] = sorted(taken)
    _save(cfg, data)
    return [describe(label, data["mcpServers"][label]) for label in found]


def remove(cfg, name: str) -> bool:
    data = _load(cfg)
    if name not in data["mcpServers"]:
        return False
    for var in data["secrets"].pop(name, []) or []:
        secrets.delete(_key_name(str(var)))
    del data["mcpServers"][name]
    _save(cfg, data)
    return True


def secret_env(cfg) -> dict[str, str]:
    """{placeholder variable: value} for every connector, from the key store (for the assistant's environment only)."""
    out = {}
    for names in _load(cfg)["secrets"].values():
        for var in names if isinstance(names, list) else []:
            if re.fullmatch(r"JCC_CONNECTOR_[A-Z0-9_]+", str(var)):
                value = secrets._cred_read(_key_name(var))
                if value:
                    register_secret(value)
                    out[var] = value
    return out


def strip_env(env) -> None:
    """Take the connectors' secrets out of an environment (JARVIS's own tool server does this as it starts)."""
    for var in [k for k in env if str(k).upper().startswith("JCC_CONNECTOR_")]:
        env.pop(var, None)


# ------------------------------------------------------------------------------------- the ones in Claude already
def claude_files(home: Path | None = None) -> list[tuple[str, Path]]:
    home = home or Path.home()
    if sys.platform == "darwin":
        desktop = home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif os.name == "nt":
        desktop = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming") / "Claude" / "claude_desktop_config.json"
    else:
        desktop = home / ".config" / "Claude" / "claude_desktop_config.json"
    return [("Claude Desktop", desktop), ("Claude Code", home / ".claude.json")]


def in_claude(cfg, files: list[tuple[str, Path]] | None = None) -> list[dict]:
    """The connectors set up in Claude Desktop and Claude Code (its own, for every project), ready to bring in."""
    have = _load(cfg)["mcpServers"]
    out = []
    for source, path in files or claude_files():
        servers = read_json(path, {}).get("mcpServers") if path.is_file() else None
        for label, entry in (servers or {}).items() if isinstance(servers, dict) else []:
            if not isinstance(entry, dict) or label == "jarvis":
                continue
            try:
                shown = describe(label, _clean(entry))
            except ConnectorError:
                continue
            shown.update(source=source, there=label in have, secret=bool(seal(label, _clean(entry))[1]))
            out.append(shown)
    return out


def bring_in(cfg, source: str, names: list[str], files: list[tuple[str, Path]] | None = None) -> list[dict]:
    path = dict(files or claude_files()).get(source)
    servers = (read_json(path, {}).get("mcpServers") or {}) if path and path.is_file() else {}
    chosen = {label: servers[label] for label in names if label in servers}
    if not chosen:
        raise ConnectorError("None of those is set up in " + str(source) + ".")
    return add(cfg, json.dumps({"mcpServers": chosen}))


# ---------------------------------------------------------------------------------------------------- testing
def _expanded(value, env: dict) -> str:
    return PLACEHOLDER.sub(lambda m: env.get(m.group(1), ""), str(value))


def test(cfg, name: str, timeout: float = 60.0) -> dict:
    """Start the connector as the assistant would, and ask for its tools. {"ok", "tools", "problem"}."""
    entry = _load(cfg)["mcpServers"].get(name)
    if not entry:
        raise ConnectorError("There is no connector called " + str(name) + ".")
    values = secret_env(cfg)
    try:
        tools = _http_tools(entry, values, timeout) if entry.get("url") else _stdio_tools(entry, values, timeout)
    except ConnectorError as problem:
        return {"ok": False, "tools": [], "problem": str(problem)}
    return {"ok": True, "tools": tools[:80], "problem": ""}


HELLO = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "JARVIS", "version": "1"}}}


def _stdio_tools(entry: dict, values: dict, timeout: float) -> list[str]:
    from jcc.agents import resolve_command
    from jcc.jobs import scrub_env
    command = _expanded(entry["command"], values)
    exe = resolve_command(command) or command
    env = {**scrub_env(dict(os.environ)), **{k: _expanded(v, values) for k, v in (entry.get("env") or {}).items()}}
    try:
        proc = subprocess.Popen([exe, *[_expanded(a, values) for a in entry.get("args") or []]], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, cwd=entry.get("cwd") or None, env=env, text=True, encoding="utf-8", errors="replace",
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as problem:
        raise ConnectorError(f"{command} could not be started ({problem.strerror or problem}). Is it installed?") from None
    lines: queue.Queue = queue.Queue()
    threading.Thread(target=lambda: [lines.put(line) for line in proc.stdout], daemon=True).start()
    errors: list[str] = []
    threading.Thread(target=lambda: [errors.append(line) for line in proc.stderr], daemon=True).start()

    def ask(message: dict, want: int) -> dict:
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()
        until = time.time() + timeout
        while time.time() < until:
            try:
                line = lines.get(timeout=0.5)
            except queue.Empty:
                if proc.poll() is not None:
                    raise ConnectorError("It stopped: " + redact("".join(errors[-5:]).strip())[:300] if errors else "It stopped before it answered.") from None
                continue
            try:
                reply = json.loads(line)
            except ValueError:
                continue
            if reply.get("id") == want:
                if reply.get("error"):
                    raise ConnectorError("It said: " + redact(str(reply["error"].get("message", reply["error"])))[:200])
                return reply.get("result") or {}
        raise ConnectorError(f"It did not answer within {int(timeout)} seconds.")
    try:
        ask(HELLO, 1)
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        proc.stdin.flush()
        return [str(t.get("name")) for t in ask({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, 2).get("tools", [])]
    except (OSError, ValueError) as problem:
        if isinstance(problem, ConnectorError):
            raise
        raise ConnectorError("It could not be talked to: " + redact(str(problem))[:200]) from None
    finally:
        try:
            proc.kill()
            proc.wait(10)
        except (OSError, subprocess.TimeoutExpired):
            pass
        for pipe in (proc.stdin, proc.stdout, proc.stderr):
            try:
                pipe.close()
            except (OSError, ValueError):
                pass


def _http_tools(entry: dict, values: dict, timeout: float) -> list[str]:
    if entry.get("type") == "sse":
        raise ConnectorError("This is an older kind of connector (SSE): the assistant can use it, but JARVIS cannot test it here.")
    url = _expanded(entry["url"], values)
    headers = {k: _expanded(v, values) for k, v in (entry.get("headers") or {}).items()}
    session = {}

    def post(message: dict) -> dict:
        request = urllib.request.Request(url, data=json.dumps(message).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                                                  "User-Agent": "JARVIS", **headers, **session})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as answer:
                if answer.headers.get("Mcp-Session-Id"):
                    session["Mcp-Session-Id"] = answer.headers["Mcp-Session-Id"]
                raw = answer.read(4_000_000).decode("utf-8", "replace")
        except urllib.error.HTTPError as problem:
            if problem.code == 401:
                raise ConnectorError("It needs signing in. Give it a key or token if the service offers one; JARVIS cannot do a browser "
                                     "sign-in (OAuth) for a connector yet.") from None
            raise ConnectorError(f"It answered with an error ({problem.code}).") from None
        except (urllib.error.URLError, TimeoutError, OSError) as problem:
            raise ConnectorError("It could not be reached: " + redact(str(getattr(problem, "reason", problem)))[:160]) from None
        if not raw.strip() or "id" not in message:
            return {}
        texts = [line[5:].strip() for line in raw.splitlines() if line.startswith("data:")] or [raw]
        for text in texts:
            try:
                reply = json.loads(text)
            except ValueError:
                continue
            if reply.get("id") == message["id"]:
                if reply.get("error"):
                    raise ConnectorError("It said: " + redact(str(reply["error"].get("message", reply["error"])))[:200])
                return reply.get("result") or {}
        raise ConnectorError("It answered with something that is not a connector's answer.")
    post(HELLO)
    post({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return [str(t.get("name")) for t in post({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}).get("tools", [])]
