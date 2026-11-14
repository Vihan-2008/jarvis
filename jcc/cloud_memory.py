"""Resumable private note embeddings through the owner's Supabase Edge Function."""
import hashlib
import json
import re
import time
import urllib.request
import urllib.error
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor

from jcc import secrets
from jcc.lock import InstanceLock
from jcc.redact import redact
from jcc.vault import atomic_write, parse_frontmatter


def configure(cfg, endpoint, key):
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not re.fullmatch(r"[a-z0-9]+\.supabase\.co", parsed.hostname or "") or parsed.path != "/functions/v1/jarvis-brain":
        raise ValueError("Use your project's HTTPS jarvis-brain Edge Function endpoint.")
    if len(key) < 32:
        raise ValueError("A strong sync credential is required.")
    secrets.store("supabase-sync", key)
    atomic_write(cfg.state_dir / "cloud-memory.json", json.dumps({"endpoint": endpoint, "enabled": True}))


def pairing():
    import secrets as random
    values = {}
    for name in ("sync", "query"):
        key = secrets.get("supabase-" + name)
        if not key:
            key = random.token_urlsafe(40)
            secrets.store("supabase-" + name, key)
        values[name] = key
    return {"env": f"JARVIS_SYNC_SECRET={values['sync']}\nJARVIS_QUERY_SECRET={values['query']}", "query_key": values['query']}


def note_text(path, root):
    rel = path.relative_to(root).as_posix()
    if path.is_symlink() or any(p.startswith(".") or p.lower() == "private" for p in path.relative_to(root).parts):
        return None
    if rel.startswith(("Conversations/Imported/", "Conversations/Local/")):
        return None  # canonical mirrored conversations already contain the messages
    from jcc.privacy import note
    value=note(path,root,cloud=True,explicit=True)
    if value is None:return None
    fm,body=value
    body = re.split(r"(?m)^## Original export record\s*$", body)[0]
    return redact(body).strip()


def chunks(text):
    # Conservative character bound for gte-small's 512-token context.
    # PostgreSQL text rejects NUL. Keep character positions stable so completed
    # prefix hashes remain reusable; the original vault transcript is untouched.
    text = text.replace('\x00', '\ufffd')
    return [text[i:i + 1100] for i in range(0, len(text), 1000) if text[i:i + 1100].strip()]


def _post(endpoint, key, body):
    request = urllib.request.Request(endpoint, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "x-jarvis-key": key})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.load(response)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 546, 503) or attempt == 2:
                raise
            time.sleep(1 + attempt)


def sync(cfg, post=None, budget=20):
    from jcc.governor import reason
    deferred=reason(cfg,network=True)
    if deferred:
        status_path=cfg.state_dir/'cloud-memory-status.json'
        previous=json.loads(status_path.read_text('utf-8')) if status_path.exists() else {}
        value={**previous,'status':'deferred','reason':deferred,'deferred_at':time.time()}
        atomic_write(status_path,json.dumps(value));return value
    config_path = cfg.state_dir / "cloud-memory.json"
    if not config_path.exists():
        return
    settings = json.loads(config_path.read_text("utf-8"))
    if not settings.get("enabled"):
        return
    key = secrets.get("supabase-sync")
    if not key:
        return
    lock = InstanceLock(cfg.state_dir / "cloud-memory.lock")
    if not lock.acquire():
        return
    ledger_path = cfg.state_dir / "cloud-memory-ledger.json"
    ledger = json.loads(ledger_path.read_text("utf-8")) if ledger_path.exists() else {}
    post = post or _post
    started = time.monotonic()
    uploaded = 0
    pending = 0
    seen = set()
    try:
        # Index small notes first so project decisions and guides become useful
        # immediately while long historical transcripts continue in batches.
        for path in sorted(cfg.vault.rglob("*.md"), key=lambda p: (p.stat().st_size, str(p))):
            rel = path.relative_to(cfg.vault).as_posix()
            text = note_text(path, cfg.vault)
            if text is None:
                continue
            seen.add(rel)
            digest = hashlib.sha256(text.encode()).hexdigest()
            state = ledger.get(rel, {})
            if state.get("digest") == digest and state.get("done"):
                continue
            pending += 1
            if time.monotonic() - started >= budget:
                continue
            parts = chunks(text)
            hashes = [hashlib.sha256(part.encode()).hexdigest() for part in parts]
            offset = state.get("offset", 0) if state.get("digest") == digest else 0
            if state.get("digest") != digest and state.get("hashes"):
                old = state["hashes"]
                while offset < min(len(old), len(hashes)) and old[offset] == hashes[offset]:
                    offset += 1
            # Even an unchanged prefix needs a final acknowledgement to prune
            # stale trailing chunks when a note was shortened.
            if offset == len(parts) and parts:
                offset -= 1
            while offset < len(parts) or not parts:
                # Each HTTP request runs one inference within the free CPU
                # allowance. Four independent requests reduce initial backfill
                # time without placing a multi-inference load on one request.
                batch = [{"ordinal": i, "content": parts[i], "digest": digest} for i in range(offset, min(offset + 4, len(parts)))]
                final = offset + len(batch) >= len(parts)
                payloads = [{"action": "ingest", "path": rel, "chunks": [part]} for part in batch]
                if not payloads:
                    payloads = [{"action": "ingest", "path": rel, "chunks": []}]
                if final:
                    payloads[-1]["total"] = len(parts)
                with ThreadPoolExecutor(max_workers=4) as pool:
                    responses = list(pool.map(lambda payload: post(settings["endpoint"], key, payload), payloads))
                if not all(response.get("ok") for response in responses):
                    raise ValueError("Cloud did not acknowledge the memory batch.")
                offset += len(batch)
                ledger[rel] = {"digest": digest, "offset": offset, "done": final, "hashes": hashes[:offset]}
                atomic_write(ledger_path, json.dumps(ledger))
                if final:
                    uploaded += 1
                    pending -= 1
                    break
                if time.monotonic() - started >= budget:
                    break
        # Deleted/private notes must also disappear from cloud search.
        for rel in list(ledger):
            if rel not in seen and time.monotonic() - started < budget:
                response = post(settings["endpoint"], key, {"action": "forget", "path": rel})
                if not response.get("ok"):
                    raise ValueError("Cloud did not acknowledge removal.")
                del ledger[rel]
                atomic_write(ledger_path, json.dumps(ledger))
        status = {"at": time.time(), "status": "indexing" if pending else "synced", "updated_notes": uploaded,
                  "indexed_notes": sum(bool(v.get("done")) for v in ledger.values()), "pending_notes": pending,
                  "indexed_chunks": sum(v.get("offset", 0) for v in ledger.values())}
    except Exception as e:
        status = {"at": time.time(), "status": "error", "error": redact(str(e))[:200],
                  "indexed_notes":sum(bool(v.get('done')) for v in ledger.values()),
                  "indexed_chunks":sum(v.get('offset',0) for v in ledger.values()), "pending_notes":pending}
    finally:
        lock.release()
    atomic_write(cfg.state_dir / "cloud-memory-status.json", json.dumps(status))
    return status


def main():
    from jcc.config import load
    cfg = load()
    lock = InstanceLock(cfg.state_dir / "cloud-worker.lock")
    if not lock.acquire():
        return
    try:
        while True:
            try:
                status = sync(cfg, budget=45)
            except Exception as e:
                status = {"at": time.time(), "status": "error", "error": redact(str(e))[:200]}
                atomic_write(cfg.state_dir / "cloud-memory-status.json", json.dumps(status))
            time.sleep(5 if status and status.get("status") == "indexing" else 30)
    finally:
        lock.release()


if __name__ == "__main__":
    main()
