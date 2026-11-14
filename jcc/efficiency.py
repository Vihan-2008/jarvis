"""Measured task usage and bounded execution preferences."""
import json
import re
from jcc.vault import atomic_write

DEFAULTS = {"max_attempts": 4, "timeout_minutes": 20, "context_chars": 6000, "session_turns": 8}
BOUNDS = {"max_attempts": (1, 12), "timeout_minutes": (1, 120), "context_chars": (2000, 18000), "session_turns": (1, 20)}


def settings(cfg):
    path = cfg.state_dir / "efficiency.json"
    from jcc.vault import read_json
    saved = read_json(path, {})

    def whole(value, usual):
        try:
            return int(value)
        except (TypeError, ValueError):
            return usual
    return {k: max(BOUNDS[k][0], min(BOUNDS[k][1], whole(saved.get(k, v), v))) for k, v in DEFAULTS.items()}


def save(cfg, values):
    if not isinstance(values, dict) or set(values) != set(DEFAULTS):
        raise ValueError("Supply all efficiency preferences.")
    cleaned = {}
    for k, v in values.items():
        if isinstance(v, bool) or not isinstance(v, int) or not BOUNDS[k][0] <= v <= BOUNDS[k][1]:
            raise ValueError(f"{k} must be between {BOUNDS[k][0]} and {BOUNDS[k][1]}.")
        cleaned[k] = v
    atomic_write(cfg.state_dir / "efficiency.json", json.dumps(cleaned))
    return cleaned


def metadata(output, provider):
    result = {"session_id": None, "input_tokens": None, "cached_tokens": None, "output_tokens": None}
    for line in output.splitlines():
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        sid = data.get("thread_id") if provider == "codex" else data.get("session_id")
        if sid and re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", str(sid)):
            result["session_id"] = sid
        usage = data.get("usage")
        if isinstance(usage, dict):
            for dest, key in (("input_tokens", "input_tokens"), ("output_tokens", "output_tokens"),
                              ("cached_tokens", "cached_input_tokens" if provider == "codex" else "cache_read_input_tokens")):
                value = usage.get(key)
                if isinstance(value, int) and value >= 0:
                    result[dest] = value
            if provider == "claude" and result["input_tokens"] is not None:
                # Claude reports cached and cache-creation input separately.
                result["input_tokens"] += int(usage.get("cache_read_input_tokens", 0)) + int(usage.get("cache_creation_input_tokens", 0))
    if result["output_tokens"] is None:
        match = re.search(r"tokens used\s*\n([\d,]+)", output)
        if match:
            result["reported_total_tokens"] = int(match[1].replace(",", ""))
    return result


def summary(cfg):
    # Per-job files keep diagnostics outside the vault and avoid schema upgrades.
    rows = []
    for path in cfg.jobs_root.glob("*/metrics.json"):
        try:
            rows.append(json.loads(path.read_text("utf-8")))
        except (OSError, ValueError):
            continue
    rows.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
    return rows[:30]
