"""Explicit, scope-bound conversation reuse; never resume an unrelated last session."""
import hashlib
import json
import re
import time
from jcc.efficiency import settings
from jcc.vault import atomic_write


def reference_hash(spec):
    references=re.sub(r"<chat-history>[\s\S]*?</chat-history>","",spec.get('context','')).strip()
    return hashlib.sha256((references+json.dumps(spec.get('image_ids') or [])+(json.dumps(spec['doc_ids']) if spec.get('doc_ids') else '')).encode()).hexdigest()


def workspace(cfg, spec, fallback):
    from jcc.chats import CHAT_ID
    cid = spec.get("chat_id", "") or ""
    if spec.get("kind") == "chat" and CHAT_ID.fullmatch(cid):
        path = cfg.jobs_root / "chat-sessions" / cid
        path.mkdir(parents=True, exist_ok=True)
        return path
    return fallback


def path_for(cfg, spec, provider, model, cwd):
    identity = [spec.get("chat_id"), spec.get("reference_project"), spec.get("kind"), provider, model, str(cwd)]
    key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    return cfg.state_dir / "sessions" / (key + ".json")


def scope_key(spec):
    from jcc.chats import CHAT_ID
    if spec.get("kind") == "chat" and CHAT_ID.fullmatch(spec.get("chat_id") or ""):
        return "chat-" + spec["chat_id"]
    if re.fullmatch(r"\d{8}-\d{6}-[a-f0-9]{4}", spec.get("id") or ""):
        return "job-" + spec["id"]
    return None


def get(cfg, spec, provider, model, cwd):
    scope = scope_key(spec)
    if not scope:
        return None
    if spec.get("kind") == "chat" and re.search(r"\b(new topic|unrelated question|start over|forget previous|new task|switch project)\b", spec["task"], re.I):
        return None
    path = path_for(cfg, spec, provider, model, cwd)
    latest = cfg.state_dir / "sessions" / (scope + ".json")
    if not latest.exists() or json.loads(latest.read_text("utf-8")).get("identity") != path.name:
        return None
    if not path.exists():
        return None
    data = json.loads(path.read_text("utf-8"))
    if data.get("reference_hash") and data["reference_hash"] != reference_hash(spec):
        return None
    if data.get("reset_reason"):
        return None
    sid = data.get("session_id", "")
    if (not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", sid) or time.time() - data.get("at", 0) > 3600 or
            data.get("turns", 0) >= settings(cfg)["session_turns"] or data.get("context_chars", 0) > settings(cfg)["context_chars"] * 4):
        return None
    return data


def remember(cfg, spec, provider, model, cwd, measured, previous=None):
    scope = scope_key(spec)
    if not scope or not measured.get("session_id"):
        return
    data = {"reference_hash":reference_hash(spec), "session_id": measured["session_id"], "at": time.time(), "turns": (previous or {}).get("turns", 0) + 1,
            "input_tokens": measured.get("input_tokens") or 0,
            "context_chars": (previous or {}).get("context_chars", 0) + len(spec["task"]) +
                len(re.sub(r"<chat-history>[\s\S]*?</chat-history>", "", spec.get("context", "")))}
    if measured.get("input_tokens") is not None and measured.get("cached_tokens") is not None:
        uncached = measured["input_tokens"] - measured["cached_tokens"]
        data["baseline_uncached"] = (previous or {}).get("baseline_uncached", uncached)
        # Reuse is conditional on measured value; a tiny live verification did
        # not save uncached input, so do not keep growing that conversation.
        if previous and uncached > max(1, data["baseline_uncached"]) * 1.05:
            data["reset_reason"] = "Resumed turn used more uncached input; next turn starts fresh."
    path = path_for(cfg, spec, provider, model, cwd)
    atomic_write(path, json.dumps(data))
    atomic_write(cfg.state_dir / "sessions" / (scope + ".json"), json.dumps({"identity": path.name}))
    return data.get("reset_reason")


def invalidate_chat(cfg, spec):
    from jcc.chats import CHAT_ID
    if CHAT_ID.fullmatch(spec.get("chat_id") or ""):
        atomic_write(cfg.state_dir / "sessions" / ("chat-" + spec["chat_id"] + ".json"), json.dumps({"identity": None}))
