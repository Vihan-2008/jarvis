"""Inbox watcher loop, shared by `jcc watch` and the GUI (which runs it in a background thread)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from jcc import config
from jcc.engine import Engine
from jcc.lock import watcher_lock
from jcc.redact import redact

RETRY_EVERY_S = 30


def run(stop: threading.Event, interval: float = 5.0,
        log: Callable[[str], None] = print, cfg: config.Config | None = None) -> bool:
    """Watch Inbox.md until `stop` is set. Returns False if another watcher already runs."""
    cfg = cfg or config.load()
    lock = watcher_lock(cfg.state_dir)
    if not lock.acquire():
        log("Another watcher is already running; not starting a second one.")
        return False
    e = Engine(cfg)  # created in this thread: its SQLite connection stays in this thread
    try:
        e.write_rules_note()
        log(f"Watching {e.vault.root / 'Inbox.md'} every {interval:.0f}s.")
        last_retry = 0.0
        while not stop.is_set():
            try:
                for r in e.process_inbox():
                    log(f"{r.id} tier {r.tier} {r.status}: {redact(r.request)[:70]}")
                if time.time() - last_retry > RETRY_EVERY_S:
                    from jcc.history import watch_imports
                    watch_imports(cfg)
                    recover(e)
                    e.retry_queued()
                    last_retry = time.time()
            except Exception as ex:  # noqa: BLE001 - keep watching; errors also land in the vault
                log(f"error: {type(ex).__name__}: {redact(str(ex))[:200]}")
            stop.wait(interval)
        return True
    finally:
        e.close()
        lock.release()


def recover(e: Engine) -> None:
    """Use the same interruption/orphan/merged-work checks as maintenance."""
    from jcc.resilience import recover as reconcile
    reconcile(e.cfg)
