"""Resumable private note embeddings through the owner's Supabase Edge Function."""
import hashlib
import json
import re
import time
import urllib.request
import urllib.error
from urllib.parse import urlparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

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


def wire_json(value):
    """JSON in which every character of every string, except ASCII letters and digits, is a \\u escape.

    Supabase sits behind Cloudflare, whose firewall refuses request bodies that look like attacks: a conversation
    note that quotes a path-traversal string (..%2f..%2f...) was refused forever and stopped every later note.
    JSON parsing restores the identical text, so the function stores exactly what the note says. The worst case
    (a 1100-character chunk of emoji) stays well under the function's 25000-character request limit."""
    if isinstance(value, str):
        out = []
        for ch in value:
            if ch.isascii() and ch.isalnum():
                out.append(ch)
                continue
            code = ord(ch)
            if code > 0xFFFF:
                code -= 0x10000
                out.append("\\u%04x\\u%04x" % (0xD800 + (code >> 10), 0xDC00 + (code & 0x3FF)))
            else:
                out.append("\\u%04x" % code)
        return '"' + "".join(out) + '"'
    if isinstance(value, dict):
        return "{" + ",".join(wire_json(str(k)) + ":" + wire_json(v) for k, v in value.items()) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(wire_json(v) for v in value) + "]"
    return json.dumps(value)


def _post(endpoint, key, body):
    request = urllib.request.Request(endpoint, data=wire_json(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "x-jarvis-key": key})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.load(response)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 546, 503) or attempt == 2:
                raise
            time.sleep(1 + attempt)


# Each request carries one chunk and runs one inference within Supabase's free CPU allowance, so a request is slow
# (seconds) while the PC is idle. Up to four are kept in flight: a new one starts as soon as any finishes, instead of
# four at a time waiting for the slowest. More at once would risk the function's resource limit (HTTP 546).
IN_FLIGHT = 4
LEDGER_SAVE_EVERY = 10   # seconds: the ledger is a few MB, so it is saved now and then while a long note uploads
FORGET_TIME = 30         # seconds each pass gives to removing deleted or private notes, apart from the upload budget


def _send_note(post, endpoint, key, rel, parts, digest, offset, started, budget, record):
    """Upload one note's chunks from `offset`, IN_FLIGHT at a time, until done, a failure, or the budget is used up.
    `record(acknowledged)` is told how many chunks from `offset` on the cloud has, counting only an unbroken run (a
    later chunk that arrived early is sent again next time), now and then and when this stops. Returns whether the
    note is done; raises the first failure once the requests in flight have finished."""
    payloads = [{"action": "ingest", "path": rel, "chunks": [{"ordinal": i, "content": parts[i], "digest": digest}]}
                for i in range(offset, len(parts))] or [{"action": "ingest", "path": rel, "chunks": []}]
    # The last chunk tells the function how long the note is now; it only removes chunks past that end, so the order
    # replies arrive in does not matter.
    payloads[-1]["total"] = len(parts)
    acknowledged, run, failure, saved, nxt = set(), 0, None, time.monotonic(), 0
    with ThreadPoolExecutor(max_workers=IN_FLIGHT) as pool:
        flying = {}
        while True:
            while failure is None and nxt < len(payloads) and len(flying) < IN_FLIGHT and time.monotonic() - started < budget:
                flying[pool.submit(post, endpoint, key, payloads[nxt])] = nxt
                nxt += 1
            if not flying:
                break
            finished, _ = wait(flying, return_when=FIRST_COMPLETED)
            for future in finished:
                n = flying.pop(future)
                try:
                    ok = future.result().get("ok")
                except Exception as e:  # noqa: BLE001 - the first failure ends this pass once the rest have landed
                    failure = failure or e
                    continue
                if ok:
                    acknowledged.add(n)
                else:
                    failure = failure or ValueError("Cloud did not acknowledge the memory batch.")
            before = run
            while run in acknowledged:
                run += 1
            if run > before and time.monotonic() - saved >= LEDGER_SAVE_EVERY:
                record(run)
                saved = time.monotonic()
    if run:
        record(run)
    if failure is not None:
        raise failure
    return run == len(payloads)


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

            def record(acknowledged, rel=rel, digest=digest, hashes=hashes, start=offset, total=len(parts)):
                # (An empty note is one request with no chunks: once it is acknowledged, upto == total == 0.)
                upto = min(start + acknowledged, total)
                ledger[rel] = {"digest": digest, "offset": upto, "done": upto == total, "hashes": hashes[:upto]}
                atomic_write(ledger_path, json.dumps(ledger))

            if _send_note(post, settings["endpoint"], key, rel, parts, digest, offset, started, budget, record):
                uploaded += 1
                pending -= 1
        # Deleted/private notes must also disappear from cloud search, even while a long backlog uses up the upload
        # budget of every pass: removals get time of their own.
        forgets_started = time.monotonic()
        removed = False
        try:
            for rel in list(ledger):
                if rel in seen or time.monotonic() - forgets_started >= FORGET_TIME:
                    continue
                response = post(settings["endpoint"], key, {"action": "forget", "path": rel})
                if not response.get("ok"):
                    raise ValueError("Cloud did not acknowledge removal.")
                del ledger[rel]
                removed = True
        finally:
            if removed:
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


# Every pass reads, redacts and fingerprints the whole vault before it knows whether anything changed, which costs
# several seconds of CPU on a large vault. So the worker rests longer when there is nothing left to send, and a cloud
# that keeps refusing (a wrong key, an outage) is asked less and less often instead of every half minute forever.
INDEXING_WAIT = 5        # notes are still waiting to be sent
SYNCED_WAIT = 300        # everything is sent: new, changed or newly private notes are noticed within five minutes
IDLE_WAIT = 30           # off, not set up, or deferred: those checks are cheap and stop before the vault is read
ERROR_WAIT = 30          # the first retry after a failure ...
ERROR_WAIT_MAX = 900     # ... doubles with each failure in a row, up to fifteen minutes
UPLOAD_BUDGET = 120      # seconds a pass may upload: the vault is read again only between passes, so longer passes
                         # spend more of the time sending while a backlog waits (a pass with nothing to send is short)


def wait_after(status, failures):
    """Seconds to rest after a pass, from its status and the number of failed passes in a row."""
    state = (status or {}).get("status")
    if state == "indexing":
        return INDEXING_WAIT
    if state == "synced":
        return SYNCED_WAIT
    if state == "error":
        return min(ERROR_WAIT * 2 ** min(max(failures - 1, 0), 10), ERROR_WAIT_MAX)
    return IDLE_WAIT


def main():
    from jcc.config import load
    cfg = load()
    lock = InstanceLock(cfg.state_dir / "cloud-worker.lock")
    if not lock.acquire():
        return
    failures = 0
    try:
        while True:
            try:
                status = sync(cfg, budget=UPLOAD_BUDGET)
            except Exception as e:
                status = {"at": time.time(), "status": "error", "error": redact(str(e))[:200]}
                atomic_write(cfg.state_dir / "cloud-memory-status.json", json.dumps(status))
            failures = failures + 1 if status and status.get("status") == "error" else 0
            time.sleep(wait_after(status, failures))
    finally:
        lock.release()


if __name__ == "__main__":
    main()
