"""NotchPixel: what JARVIS is doing, shown on the island at the top of the screen.

NotchPixel is a separate app on this computer that listens at 127.0.0.1. At each moment of a request or a coding job,
JARVIS tells it whether it is thinking, working, waiting for its owner, done or in trouble, with a few words on what
it is doing. It is off unless config/local.toml says

    [notch]
    enabled = true

Nothing is sent anywhere but this computer, and the words go through redact() first. Sending happens on a thread of
its own, so a missing or slow island never holds up an answer or a job.
"""
import atexit
import threading
import time
import urllib.parse
import urllib.request

from jcc.redact import redact

EVENTS = ("start", "thinking", "working", "waiting", "done", "error", "end")
NAME = "Jarvis"
PORT = 47823
DETAIL = 120                          # characters of detail: the island has room for a line, not a paragraph

# Straight to this computer: a proxy set for the web must never see what JARVIS is doing.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_cond = threading.Condition()
_queue: dict[str, str] = {}           # session -> the newest address to call for it (an older moment is not worth showing)
_state = {"worker": None, "sending": False}
_asked: dict[str, str] = {}           # a question put to the owner -> the request it belongs to
# How a finished request shows. "paused" waits for an AI's allowance to come back, not for the owner, so it leaves the island.
CHAT_END = {"done": "done", "failed": "error", "cancelled": "end", "ignored": "end", "paused": "end"}


def enabled(cfg) -> bool:
    return (getattr(cfg, "raw", None) or {}).get("notch", {}).get("enabled") is True


def address(cfg, session: str, event: str, detail: str = "") -> str:
    """The address that puts one moment on the island."""
    port = int((cfg.raw.get("notch") or {}).get("port", PORT))
    if not 0 < port < 65536:
        raise ValueError("The NotchPixel port must be between 1 and 65535.")
    params = {"source": "custom", "name": NAME, "event": event, "session": str(session)[:80]}
    words = " ".join(redact(str(detail or "")).split())[:DETAIL]
    if words:
        params["detail"] = words
    return f"http://127.0.0.1:{port}/agent?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)


def tell(cfg, session: str, event: str, detail: str = "") -> None:
    """Puts one moment on the island. Returns at once and never fails: NotchPixel may well not be running."""
    try:
        if event not in EVENTS or not session or not enabled(cfg):
            return
        url = address(cfg, session, event, detail)
    except (AttributeError, TypeError, ValueError):
        return
    with _cond:
        _queue.pop(str(session), None)            # (moved to the back, so every session gets its turn)
        _queue[str(session)] = url
        if _state["worker"] is None:
            _state["worker"] = threading.Thread(target=_send_all, name="notchpixel", daemon=True)
            _state["worker"].start()
            atexit.register(flush)
        _cond.notify_all()


def chat_event(cfg, kind: str, fields: dict, turns: dict) -> None:
    """Shows one of the assistant's events for the window (Assistant.emit in jcc/assistant.py) on the island. Each request
    being answered is a session of its own. Shortening a conversation (compacting) is housekeeping and is left off."""
    if not enabled(cfg) or fields.get("compact") or fields.get("model") == "compact":
        return
    rid = str(fields.get("id") or "")
    if kind == "start":
        tell(cfg, rid, "thinking")
    elif kind == "step":
        tell(cfg, rid, "working", fields.get("t", ""))
    elif kind == "confirm":
        turn = turns.get(fields.get("chat"))
        if turn is not None:
            _asked[rid] = turn.id
            tell(cfg, turn.id, "waiting", fields.get("question", ""))
    elif kind == "confirmed":
        tell(cfg, _asked.pop(rid, ""), "working" if fields.get("approved") else "thinking")
    elif kind == "done":
        tell(cfg, rid, CHAT_END.get(fields.get("status"), "done"))


def _send_all() -> None:
    while True:
        with _cond:
            while not _queue:
                _cond.wait()
            url = _queue.pop(next(iter(_queue)))
            _state["sending"] = True
        try:
            _opener.open(url, timeout=1).close()
        except Exception:  # noqa: BLE001 - not running, busy or gone: the island simply misses this moment
            pass
        with _cond:
            _state["sending"] = False
            _cond.notify_all()


def flush(wait: float = 1.5) -> None:
    """Gives what is still to be sent a moment to go, so a job that ends straight after finishing still shows "done"."""
    end = time.monotonic() + wait
    with _cond:
        while (_queue or _state["sending"]) and _state["worker"] is not None and time.monotonic() < end:
            _cond.wait(end - time.monotonic())
