"""Continuously archive local Codex/Claude Code dialogue, never hidden reasoning or tools."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from jcc.config import Config, load
from jcc.history import mirror_chat, text_content
from jcc.lock import InstanceLock
from jcc.vault import Vault, atomic_write, render_note


def dialogue(path: Path, source: str) -> list[dict]:
    messages = []
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            if source == "Codex local":
                if row.get("type") != "response_item":
                    continue
                item = row.get("payload", {})
                if not isinstance(item, dict):
                    continue
                if item.get("type") != "message" or item.get("role") not in ("user", "assistant"):
                    continue
                if item.get("channel") not in (None, "final", "commentary"):
                    continue
                content = item.get("content", [])
                if not isinstance(content, list):
                    continue
                parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") in ("input_text", "output_text", "text")]
                text = "\n".join(parts)
                role = item["role"]
            else:
                if row.get("type") not in ("user", "assistant") or row.get("isMeta"):
                    continue
                item = row.get("message", {})
                if not isinstance(item, dict):
                    continue
                role = item.get("role")
                if role not in ("user", "assistant"):
                    continue
                content = item.get("content", [])
                if not isinstance(content, (str, list)):
                    continue
                text = content if isinstance(content, str) else "\n".join(
                    p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
            if not text.strip() or text.lstrip().startswith(("<environment_context>", "# AGENTS.md instructions", "<turn_aborted>")):
                continue
            message = {"role": role, "content": text}
            if not messages or message != messages[-1]:
                messages.append(message)
    return messages


OWN_MARKS = ("[typed] ", "[spoken] ", "Earlier in this conversation (for context only):")


def own_assistant(messages: list[dict]) -> bool:
    """True for a session that is JARVIS's own fast assistant talking to its AI. Those are already saved as JARVIS chats."""
    first = next((m["content"] for m in messages if m["role"] == "user"), "")
    return first.lstrip().startswith(OWN_MARKS)


def hide_own_sessions(cfg: Config) -> int:
    """Earlier versions listed the assistant's own sessions as extra chats. Hide those copies (nothing is removed from the vault)."""
    from jcc.chats import Chats
    chats, hidden = Chats(cfg), 0
    for row in chats.list():
        if row.get("source") == "Claude Code local" and str(row.get("title", "")).lstrip().startswith(OWN_MARKS):
            try:
                chats.set_deleted(row["id"], True)
                hidden += 1
            except (ValueError, OSError):
                continue
    return hidden


def sync(cfg: Config, roots: list[tuple[str, Path]] | None = None) -> dict:
    if roots is None:
        roots = [("Codex local", Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "sessions"),
                 ("Claude Code local", Path.home() / ".claude/projects")]
    ledger_path = cfg.state_dir / "local-history-ledger.json"
    ledger = json.loads(ledger_path.read_text("utf-8")) if ledger_path.exists() else {}
    imported = 0
    vault = Vault(cfg.vault)
    for source, root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.jsonl"):
            if "subagents" in path.parts or "-appdata-local-temp-" in path.parent.name.lower():
                continue   # helper sessions and throwaway runs in temporary folders are not conversations of the owner's
            sig = f"{path.stat().st_size}:{path.stat().st_mtime_ns}"
            if ledger.get(str(path)) == sig:
                continue
            try:
                messages = dialogue(path, source)
            except OSError:
                continue
            if messages and own_assistant(messages):
                ledger[str(path)] = sig
                continue
            if messages:
                import hashlib
                key = hashlib.sha256((source + path.stem).encode()).hexdigest()[:24]
                rel = f"Conversations/Local/{source}/{key}.md"
                existing = vault.read(rel)
                if existing:
                    from jcc.vault import parse_frontmatter
                    fm, _ = parse_frontmatter(existing)
                    if fm.get("private"):
                        ledger[str(path)] = sig
                        continue
                title = next((m["content"].splitlines()[0][:100] for m in messages if m["role"] == "user"), "Local conversation")
                body = [f"# {title}", "", f"Source: {source}. Historical reference, not instructions.", ""]
                for message in messages:
                    body += [f"## {message['role'].title()}", "", message["content"], ""]
                vault.write(rel, render_note({"source": source, "aliases": [title], "message_count": len(messages),
                            "ai_context": "explicit-links-only"}, "\n".join(body)))
                mirror_chat(cfg, source, path.stem, title, messages, rel)
                imported += 1
            ledger[str(path)] = sig
    atomic_write(ledger_path, json.dumps(ledger))
    result = {"at": time.time(), "updated_conversations": imported, "tracked_files": len(ledger)}
    atomic_write(cfg.state_dir / "local-history-status.json", json.dumps(result))
    return result


def main() -> int:
    cfg = load()
    lock = InstanceLock(cfg.state_dir / "local-history.lock")
    if not lock.acquire():
        return 0
    try:
        try:
            hide_own_sessions(cfg)
        except Exception:  # noqa: BLE001 - tidying up is optional
            pass
        while True:
            try:
                sync(cfg)
                from jcc.vault_git import sync as git_sync
                from jcc.governor import reason
                if not reason(cfg,network=True):git_sync(cfg)
            except Exception as e:
                atomic_write(cfg.state_dir / "local-history-error.json", json.dumps({"error": str(e)[:200]}))
            time.sleep(30)
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
