"""Read subscription usage through the signed-in CLIs, without running a model prompt."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from datetime import datetime

from jcc.agents import resolve_command
from jcc.config import Config
from jcc.vault import atomic_write, read_json


def _exchange(argv, initialize, request, match):
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    lines = queue.Queue()
    def read():
        for line in proc.stdout:
            try:
                lines.put(json.loads(line))
            except ValueError:
                pass
        lines.put(None)
    threading.Thread(target=read, daemon=True).start()
    def send(value):
        proc.stdin.write(json.dumps(value) + "\n")
        proc.stdin.flush()
    try:
        send(initialize)
        deadline = time.monotonic() + 30
        sent = False
        initial = {}
        while time.monotonic() < deadline:
            try:
                line = lines.get(timeout=min(1, max(0.1, deadline-time.monotonic())))
            except queue.Empty:
                continue
            if line is None:
                break
            if not sent and match(line, "init"):
                initial = line
                if "method" in initialize:
                    send({"method": "initialized"})
                send(request)
                sent = True
            elif sent and match(line, "usage"):
                return {**line, "_initialize": initial}
        raise RuntimeError("Usage service did not return a reading.")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        for stream in (proc.stdin, proc.stdout):
            stream.close()


def read_codex() -> dict:
    exe = resolve_command("codex")
    if not exe:
        raise RuntimeError("Codex is not installed.")
    data = _exchange([exe, "app-server", "--listen", "stdio://"],
        {"id": "init", "method": "initialize", "params": {"clientInfo": {"name": "jarvis_usage", "version": "1.0.0"}}},
        {"id": "usage", "method": "account/rateLimits/read"}, lambda line, key: line.get("id") == key)
    if data.get("error"):
        raise RuntimeError("Codex could not read account limits. Check its saved login.")
    result = data.get("result", {})
    buckets = result.get("rateLimitsByLimitId") or {"codex": result.get("rateLimits", {})}
    windows = []
    for name, limits in buckets.items():
        for kind in ("primary", "secondary"):
            window = limits.get(kind)
            if window and window.get("usedPercent") is not None:
                windows.append({"name": (limits.get("limitName") or name) + " · " + kind,
                    "used_percent": window["usedPercent"], "remaining_percent": max(0, 100-window["usedPercent"]),
                    "reset_at": window.get("resetsAt"), "minutes": window.get("windowDurationMins")})
    return {"provider": "codex", "at": time.time(), "windows": windows,
            "scope": "Codex allowance on your ChatGPT account; not all ChatGPT chat-model limits."}


def read_claude() -> dict:
    exe = resolve_command("claude")
    if not exe:
        raise RuntimeError("Claude Code is not installed.")
    data = _exchange([exe, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                      "--disable-slash-commands", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                      "--setting-sources", ""],
        {"type": "control_request", "request_id": "init", "request": {"subtype": "initialize"}},
        {"type": "control_request", "request_id": "usage", "request": {"subtype": "get_usage"}},
        lambda line, key: line.get("type") == "control_response" and line.get("response", {}).get("request_id") == key)
    response = data.get("response", {})
    if response.get("subtype") == "error":
        raise RuntimeError("This Claude Code version does not expose a usage reading.")
    result = response.get("response", {})
    rate = result.get("rate_limits") or {}
    windows = []
    for name, window in rate.items():
        if not isinstance(window, dict):
            continue
        used = window.get("utilization", window.get("used_percentage"))
        if not isinstance(used, (int, float)):
            continue
        reset = window.get("resets_at")
        if isinstance(reset, str):
            try:
                reset = datetime.fromisoformat(reset.replace("Z", "+00:00")).timestamp()
            except ValueError:
                reset = None
        windows.append({"name": name.replace("_", " "), "used_percent": used,
                        "remaining_percent": max(0, 100-used), "reset_at": reset})
    if not windows:
        raise RuntimeError("Claude has not supplied quota percentages. Use its Usage page for the authoritative reading.")
    raw_models = data.get("_initialize", {}).get("response", {}).get("response", {}).get("models", [])
    models = [{k: m[k] for k in ("value", "displayName") if k in m} for m in raw_models if isinstance(m, dict)]
    return {"provider": "claude", "at": time.time(), "windows": windows, "scope": "Claude subscription usage.", "models": models}


def refresh(cfg: Config, only: str | None = None) -> dict:
    """Read the allowances again (both accounts, or only the one named)."""
    results = {}
    for name, reader in (("codex", read_codex), ("claude", read_claude)):
        if only and name != only:
            continue
        path = cfg.state_dir / f"quota-{name}.json"
        old = read_json(path, {})
        try:
            value = reader()
        except (OSError, RuntimeError, ValueError) as e:
            value = {**old, "provider": name, "checked_at": time.time(), "error": str(e)[:180]}
        atomic_write(path, json.dumps(value))
        results[name] = value
    return results


def snapshot(cfg: Config) -> dict:
    return {name: read_json(cfg.state_dir / f"quota-{name}.json", {}) or {"windows": [], "error": "Waiting for first reading."}
            for name in ("codex", "claude")}


def blocked(cfg: Config, provider: str, model: str = "") -> str | None:
    path = cfg.state_dir / f"quota-{provider}.json"
    if not path.exists():
        return None
    reading = read_json(path, {})
    if time.time() - reading.get("at", 0) > 600:
        return None
    reserve = float(cfg.raw.get("tier3", {}).get("reserve_percent", 5))
    for window in reading.get("windows", []):
        name = window["name"].lower()
        if any(s in name for s in ("opus", "sonnet", "haiku")) and not any(s in model.lower() and s in name for s in ("opus", "sonnet", "haiku")):
            continue
        if window.get("reset_at") and window["reset_at"] < time.time():
            continue
        if window["remaining_percent"] <= reserve:
            return f"{window['remaining_percent']:g}% allowance left; preserving {reserve:g}% reserve"
    return None
