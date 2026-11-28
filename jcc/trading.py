"""The owner's paper-trading app (a server of their own), looked at and never touched: how each market is doing, whether
its services are running, whether the kill switch or a pause is on, and what it decided lately.

Read only, by how it is built and not by a promise:
- There is one request, and it is always GET to one fixed path on the owner's server (STATUS_PATH). Nothing here takes a
  method or a path, so nothing here can place an order, change a mode or a setting, or switch on real-money trading.
- The token the owner pastes in is a read-only one the trading server makes for JARVIS alone, at the server's own command
  line (`trading-ai jarvis-token new`). The trading dashboard's own password, which can change things, is never asked
  for and never kept.
- The token is kept in the system's key store (never in a file, a note or a log) and is sent only over https (plain http
  only to this computer itself). A redirect is never followed, so the token never goes to an address the owner did not
  give.

What comes back is read strictly: numbers as numbers, and words only where they are ids, symbols or one of a few known
codes. The trading server sends no free text (no reasons written by its AI, no error messages), and anything else it
might send is left out here too, so nothing it says can steer the assistant.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from jcc import secrets
from jcc.redact import redact, register_secret
from jcc.vault import atomic_write, read_json

STATUS_PATH = "/api/jarvis/v1/status"     # the one thing JARVIS ever asks the trading server for
KEY_NAME = "trading-feed"
MARKETS = {"crypto": "Crypto", "us": "US stocks", "in": "India"}
TOKEN_SHAPE = re.compile(r"[A-Za-z0-9_\-.~]{16,200}")
SYMBOLS = {"USD": "$", "INR": "₹", "EUR": "€", "GBP": "£"}


class TradingError(ValueError):
    """Said to the owner as it is: plain words, never the token. `kind` lets the panel decide how long to wait."""

    def __init__(self, message: str, kind: str = "other"):
        super().__init__(message)
        self.kind = kind


# ------------------------------------------------------------------------------------------------- the connection
def _file(cfg) -> Path:
    return cfg.state_dir / "trading.json"


def _local(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1") or host.endswith(".localhost")


def clean_address(address: str) -> str:
    """The trading server's address as https://host[:port][/path]: plain http only for this computer itself."""
    text = str(address or "").strip()
    if not text:
        raise TradingError("Give the trading server's address.")
    if not re.match(r"^https?://", text, re.I):
        text = "https://" + text
    parts = urllib.parse.urlsplit(text)
    try:
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        raise TradingError("That does not look like a server's address.") from None
    host = (parts.hostname or "").lower()
    if not host or ("." not in host and not _local(host)) or parts.username or parts.password or parts.query or parts.fragment:
        raise TradingError("That does not look like a server's address.")
    if parts.scheme.lower() == "http" and not _local(host):
        raise TradingError("Use the server's https:// address: the token is never sent over plain http.")
    path = parts.path.rstrip("/")
    if path.endswith(STATUS_PATH):
        path = path[: -len(STATUS_PATH)]                   # (the whole link pasted in: the server is what comes before it)
    path = re.sub(r"/#.*$", "", path)
    return f"{parts.scheme.lower()}://{host}{port}{path}"


def _saved(cfg) -> dict:
    saved = read_json(_file(cfg), {})
    return saved if isinstance(saved, dict) else {}


def _keep(cfg, saved: dict) -> None:
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(_file(cfg), json.dumps(saved, indent=1))


def connected(cfg) -> dict:
    """{"address": ...} when a trading server is connected, else {} (never the token)."""
    address = _saved(cfg).get("address")
    return {"address": address} if isinstance(address, str) and address else {}


# ------------------------------------------------------------------------------------------------- the owner's goal
def goal(cfg) -> dict:
    """The monthly amount the owner wants the trading app to make, and what it is for: {"monthly", "currency", "items"},
    or {} when none is set. Kept on this PC only, in trading.json; it is shown, and never changes how the app trades."""
    raw = _saved(cfg).get("goal")
    if not isinstance(raw, dict):
        return {}
    items = [{"name": _text(i.get("name"), 60), "amount": _num(i.get("amount"))} for i in raw.get("items") or [] if isinstance(i, dict)]
    items = [i for i in items if i["name"] and i["amount"] is not None and i["amount"] >= 0][:20]
    monthly = sum(i["amount"] for i in items) if items else _num(raw.get("monthly"))
    if not monthly or monthly <= 0:
        return {}
    rise = raw.get("raise") if isinstance(raw.get("raise"), dict) else {}
    step = _num(rise.get("step"))
    return {"monthly": round(monthly, 2), "currency": _text(raw.get("currency"), 6).upper() or "USD", "items": items,
            "raise": {"on": rise.get("on") is not False, "step": min(max(step, 0.01), 0.5) if step is not None else RAISE_STEP}}


RAISE_STEP = 0.10      # the goal climbs this much after each month that meets it (never falls below the plans' total)


def set_goal(cfg, items: list | None = None, monthly=None, currency: str = "USD", raise_on: bool = True) -> dict:
    """Set the goal: a list of {"name", "amount"} (the total is their sum, and the least the goal can be), or one monthly
    amount, and whether it climbs after each month that meets it. Nothing clears it. A goal raised by earlier months keeps
    its raises; a new currency starts the record over, since the old amounts are in the old currency."""
    saved = _saved(cfg)
    before = saved.get("goal") if isinstance(saved.get("goal"), dict) else {}
    saved["goal"] = {"items": items or [], "monthly": monthly, "currency": currency, "raise": {"on": bool(raise_on), "step": RAISE_STEP}}
    if str(before.get("currency") or "USD").upper() != str(currency or "USD").upper():
        for key in ("target", "history"):
            saved.pop(key, None)
    _keep(cfg, saved)
    found = goal(cfg)
    if not found:
        raise TradingError("Give a monthly amount above zero, or the plans with their monthly prices.")
    return found


def clear_goal(cfg) -> None:
    saved = _saved(cfg)
    for key in ("goal", "month", "target", "history"):
        saved.pop(key, None)
    _keep(cfg, saved)


def _close_month(saved: dict, aim: dict, last: dict, month: str) -> None:
    """A new month began: note how the last one went against its goal, and set this month's goal from it. It climbs by
    the step when the last month met its goal (and raising is on); otherwise it stays where it was. It is never lower
    than the plans' total. The last month's figure is the last one JARVIS saw in it."""
    target = saved.get("target") if isinstance(saved.get("target"), dict) else {}
    amount = max(aim["monthly"], _num(target.get("amount")) or 0) if aim["raise"]["on"] else aim["monthly"]
    made = _num(last.get("made"))
    met = made is not None and made >= amount
    history = [h for h in saved.get("history") or [] if isinstance(h, dict)][-23:]
    history.append({"month": _text(last.get("key"), 7), "goal": round(amount, 2), "made": made, "met": met})
    saved["history"] = history
    raised = aim["raise"]["on"] and met
    saved["target"] = {"month": month, "amount": round(amount * (1 + aim["raise"]["step"]), 2) if raised else round(amount, 2),
                       "raised": raised}


def progress(cfg, state: dict, today=None) -> dict:
    """How this month is going against the goal. The server's own figure for the month is used when it gives one;
    otherwise JARVIS counts from the total P&L it first saw this month (and says from when). The goal for the month is the
    plans' total, raised after each month that met its goal; it is shown, and never changes how the app trades."""
    import datetime
    aim = goal(cfg)
    if not aim:
        return {}
    today = today or datetime.date.today()
    month = today.strftime("%Y-%m")
    same = aim["currency"] == state["currency"]
    saved = _saved(cfg)
    start = saved.get("month") if isinstance(saved.get("month"), dict) else {}
    if start.get("key") != month:
        if start.get("key"):
            _close_month(saved, aim, start, month)
        start = {"key": month, "since": today.isoformat()}
    made, since = state.get("month_pnl"), None
    if made is None and state["total"]["pnl"] is not None:
        if _num(start.get("pnl")) is None:
            start.update(pnl=state["total"]["pnl"], since=today.isoformat())
        made, since = state["total"]["pnl"] - start["pnl"], start.get("since")
    start["made"] = made if same else None
    saved["month"] = start
    target = saved.get("target") if isinstance(saved.get("target"), dict) and saved["target"].get("month") == month else None
    if target is None:
        target = saved["target"] = {"month": month, "amount": aim["monthly"], "raised": False}
    _keep(cfg, saved)
    amount = max(aim["monthly"], _num(target.get("amount")) or 0) if aim["raise"]["on"] else aim["monthly"]
    history = [h for h in saved.get("history") or [] if isinstance(h, dict)]
    return {**aim, "month": month, "target": round(amount, 2), "raised": amount > aim["monthly"],
            "last": history[-1] if history else None, "met_months": sum(1 for h in history if h.get("met")),
            "made": made if same else None, "since": since if since and since != f"{month}-01" else None,
            "share": (made / amount) if same and made is not None else None,
            "paper": state["mode"] == "paper", "partial": bool(state.get("month_partial")) and state.get("month_pnl") is not None,
            "note": "" if same else f"The goal is in {aim['currency']} and the app reports in {state['currency']}: no comparison is made."}


def _token() -> str:
    value = (secrets._cred_read(KEY_NAME) or "").strip()
    if not value:
        raise TradingError("The trading server's token is missing from this computer's key store. Type /trading and connect again.")
    register_secret(value)
    return value


def connect(cfg, address: str, token: str, check: bool = True) -> dict:
    """Keep the server's address (in trading.json) and its read-only token (in the key store), after one look to see
    that they work. Nothing is kept when they do not."""
    where = clean_address(address)
    token = str(token or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not TOKEN_SHAPE.fullmatch(token):
        raise TradingError("That does not look like the token. Make one on the server with: trading-ai jarvis-token new")
    register_secret(token)
    if check:
        _ask(where, token)                     # (raises with what is wrong; nothing has been kept yet)
    secrets.store(KEY_NAME, token)
    _CACHE.clear()
    saved = _saved(cfg)
    if saved.get("address") != where:
        saved.pop("month", None)               # (another server: its month starts afresh)
    saved["address"] = where
    _keep(cfg, saved)
    return connected(cfg)


def disconnect(cfg) -> bool:
    """Forget the server: its address, and its token from the key store."""
    was = bool(connected(cfg))
    secrets.delete(KEY_NAME)
    _CACHE.clear()
    saved = _saved(cfg)
    saved.pop("address", None)
    saved.pop("month", None)
    _keep(cfg, saved)                          # (the goal, if any, stays: it is the owner's, not the server's)
    return was


# --------------------------------------------------------------------------------------------- asking the server
class _NeverFollow(urllib.request.HTTPRedirectHandler):
    """A redirect is not followed: the token goes to the address the owner gave, and nowhere else."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NeverFollow)


def _agent() -> str:
    from jcc import __version__
    return f"JARVIS/{__version__} (trading status, read only)"


def _get(url: str, headers: dict) -> tuple[int, object]:
    """One GET. Returns (status, the decoded answer); raises TradingError when the server cannot be reached."""
    request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json", "User-Agent": _agent(), **headers})
    try:
        with _OPENER.open(request, timeout=20) as answer:
            raw = answer.read(2_000_000)
            status = answer.status
    except urllib.error.HTTPError as problem:
        return problem.code, {}
    except (urllib.error.URLError, TimeoutError, OSError) as problem:
        from jcc import net
        raise TradingError("The trading server could not be reached: " + redact(net.reason(problem))[:300]) from None
    try:
        return status, json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return status, None


FETCH = _get                    # (tests put a stand-in here; it is only ever given a GET to STATUS_PATH)


def _ask(address: str, token: str) -> dict:
    status, answer = FETCH(address + STATUS_PATH, {"Authorization": "Bearer " + token})
    if status in (401, 403):
        raise TradingError("The trading server did not accept the token. Make a new one on the server (trading-ai jarvis-token new) "
                           "and connect again.")
    if status == 404:
        raise TradingError("The trading server has no status feed for JARVIS at that address. It needs a version of the trading app "
                           "with the JARVIS feed, and the address of its dashboard.")
    if status == 429:
        raise TradingError("The trading server asked JARVIS to wait a little (too many requests). Try again in a minute.", "rate")
    if 300 <= status < 400:
        raise TradingError("The trading server sent JARVIS to another address. Give the address its dashboard is at, with https://.")
    if status != 200 or not isinstance(answer, dict):
        raise TradingError(f"The trading server did not answer as expected (status {status}).")
    return answer


CACHE_S = 20                    # the card, the panel and the voice share one answer for this long (the server allows 30 a minute)
_CACHE: dict = {}


def fetch(cfg, fresh: bool = False) -> dict:
    """The server's status, read and cleaned (see summary)."""
    import time
    where = connected(cfg).get("address")
    if not where:
        raise TradingError("No trading server is connected. Type /trading to connect one.")
    now = time.monotonic()
    if not fresh and _CACHE.get("address") == where and now - _CACHE.get("at", -1e9) < CACHE_S:
        return _CACHE["state"]
    state = summary(_ask(where, _token()))
    _CACHE.update(address=where, at=now, state=state)
    return state


# --------------------------------------------------------------------------------------------- what it said
def _num(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if number == number and abs(number) < 1e15 else None      # (not NaN, not absurd)


def _text(value, most: int = 200) -> str:
    return " ".join(str(value or "").split())[:most]


CODE = re.compile(r"[a-z0-9_:./\-]{1,40}")
LEVELS = ("critical", "error", "warning", "action", "info")


def _code(value, known: tuple = ()) -> str:
    """An id, a symbol or a status code: kept only when it looks like one (never a sentence)."""
    text = str(value or "").strip()
    if known:
        return text.lower() if text.lower() in known else ""
    return text if CODE.fullmatch(text.lower()) and len(text) <= 40 else ""


def _active(value) -> bool:
    return isinstance(value, dict) and value.get("active") is True


REASONS = ("not_enough_data", "price_moved", "rule_no_entry", "rule_skip_confirmed", "scout_pass", "strategist_pass",
           "desk_declined", "lead_unavailable", "forecast_unavailable", "news_unavailable", "budget_exhausted",
           "expired_unreviewed", "other")      # why a decision did not trade: fixed codes from the server, worded on screen
MODES = ("investing", "trading")
BOOK_MONEY = ("equity", "pnl", "cash", "net_contributed", "realized", "unrealized", "fees_paid", "daily_pnl", "positions_value")


def _id(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _decision(row: dict) -> dict:
    return {"id": _id(row.get("id")), "book": _code(row.get("book_id")), "symbol": _code(row.get("symbol")).upper(),
            "kind": _code(row.get("kind")).lower(), "action": _code(row.get("action")).lower(),
            "status": _code(row.get("status")).lower(), "reason": _code(row.get("reason_code"), REASONS),
            "when": _num(row.get("decided_at")) or _num(row.get("created_at"))}


def _book(row: dict) -> dict:
    positions = []
    for p in (row.get("positions") or [])[:25] if isinstance(row.get("positions"), list) else []:
        if isinstance(p, dict) and _code(p.get("symbol")):
            positions.append({"symbol": _code(p.get("symbol")).upper(), "side": _code(p.get("side"), ("long", "short")) or "long",
                              "qty": _num(p.get("qty")), "value": _num(p.get("value")), "unrealized": _num(p.get("unrealized")),
                              "weight": _num(p.get("weight"))})
    series = []
    for point in (row.get("series") or [])[-120:] if isinstance(row.get("series"), list) else []:
        if isinstance(point, list) and len(point) == 3 and all(_num(x) is not None for x in point):
            series.append([_num(x) for x in point])
    last = row.get("last_decision")
    total = _id(row.get("positions_total"))
    return {"id": _code(row.get("id")), "mode": _code(row.get("mode"), MODES), "market": _code(row.get("market"), tuple(MARKETS)),
            "currency": _code(row.get("currency")).upper()[:6], "halted": row.get("halted") is True,
            "status": _code(row.get("status")).lower(), **{k: _num(row.get(k)) for k in BOOK_MONEY},
            "stale_marks": _id(row.get("stale_marks")) or 0, "positions_total": total if total is not None else len(positions),
            "positions": positions, "series": series, "last_decision": _decision(last) if isinstance(last, dict) else None}


# The real-money part, as a shadow test (it records the orders it would place and places none). Read even more strictly
# than the paper figures: fixed values only, and a book past the shadow test shows only its stage (a new review is due
# before JARVIS shows anything more of real money).
STAGES = ("off", "shadow", "approve", "autonomous")
LIVE_BOOK = re.compile(r"live:(investing|trading):(crypto|us|in)")
CHECKS = ("paper_days", "round_trips", "paper_net", "profit_factor", "max_drawdown", "shadow_days", "shadow_orders")
SHADOW_STATES = ("shadow_logged", "rejected_by_gate", "skipped_too_small", "stale", "not_mirrored")
SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9._/&-]{0,23}")


def _stage(value) -> str:
    return value if value in STAGES else "unknown"


def _live(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    executor = raw.get("executor") if isinstance(raw.get("executor"), dict) else None
    books, shadow = [], set()
    for row in (raw.get("books") or [])[:5] if isinstance(raw.get("books"), list) else []:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not LIVE_BOOK.fullmatch(row["id"]):
            continue
        book = {"id": row["id"], "market": row["id"].split(":")[2], "stage": _stage(row.get("stage")),
                "enabled": row.get("enabled") is True, "halted": row.get("halted") is True}
        if book["stage"] in ("off", "shadow"):
            readiness = row.get("readiness") if isinstance(row.get("readiness"), dict) else {}
            checks = []
            for c in (readiness.get("checks") or [])[:7] if isinstance(readiness.get("checks"), list) else []:
                if isinstance(c, dict) and c.get("name") in CHECKS:
                    checks.append({"name": c["name"], "pass": c.get("pass") is True, "need": _num(c.get("need")), "have": _num(c.get("have"))})
            currency = str(row.get("currency") or "")
            book.update(currency=currency if re.fullmatch(r"[A-Z]{3}", currency) else "", checks=checks,
                        checks_pass=readiness.get("checks_pass") is True and bool(checks) and all(c["pass"] for c in checks),
                        # Setup only: whether a sell code is set, and whether selling is locked. Never the code itself.
                        sell_code_set=row.get("sell_code_set") is True, sell_locked=row.get("sell_locked") is True)
            if book["stage"] == "shadow":
                shadow.add(book["id"])
        books.append(book)
    orders = []
    for row in (raw.get("shadow_orders") or [])[:10] if isinstance(raw.get("shadow_orders"), list) else []:
        if (isinstance(row, dict) and row.get("book") in shadow and row.get("side") in ("buy", "sell") and row.get("state") in SHADOW_STATES
                and isinstance(row.get("symbol"), str) and SYMBOL.fullmatch(row["symbol"])):
            orders.append({"book": row["book"], "symbol": row["symbol"], "side": row["side"], "notional": _num(row.get("notional")),
                           "state": row["state"], "when": _num(row.get("created_at"))})
    count = _id(raw.get("shadow_orders_7d"))
    return {"max_stage": _stage(raw.get("max_supported_stage")),
            "executor": {"running": executor.get("running") is True, "seen_age_s": _num(executor.get("seen_age_s"))} if executor else None,
            "books": books, "past_shadow": any(b["stage"] not in ("off", "shadow") for b in books),
            "shadow_orders_7d": count if count is not None and count >= 0 else None,
            "shadow_orders": orders if not any(b["stage"] not in ("off", "shadow") for b in books) else []}


def summary(raw: dict) -> dict:
    """Only what JARVIS shows and says, each piece checked for its type. Anything else the server sent is left out."""
    combined = raw.get("combined") if isinstance(raw.get("combined"), dict) else {}
    by_market = combined.get("by_market") if isinstance(combined.get("by_market"), dict) else {}
    currency = _code(raw.get("reporting_currency")).upper()[:6] or "USD"
    markets = []
    for key, label in MARKETS.items():
        row = by_market.get(key)
        if isinstance(row, dict):
            markets.append({"market": key, "label": label, "equity": _num(row.get("equity")), "pnl": _num(row.get("pnl")),
                            "currency": _code(row.get("currency")).upper()[:6] or currency, "equity_local": _num(row.get("equity_local"))})
    services = []
    for name, row in sorted((raw.get("services") or {}).items()) if isinstance(raw.get("services"), dict) else []:
        if isinstance(row, dict) and _code(name):
            services.append({"name": _code(name), "status": _code(row.get("status")).lower(), "age_s": _num(row.get("age_s"))})
    flags = raw.get("flags") if isinstance(raw.get("flags"), dict) else {}
    decisions = [_decision(row) for row in (raw.get("recent_decisions") or [])[:20] if isinstance(row, dict)] \
        if isinstance(raw.get("recent_decisions"), list) else []
    books = [_book(row) for row in (raw.get("books") or [])[:20] if isinstance(row, dict) and _code(row.get("id"))] \
        if isinstance(raw.get("books"), list) else []
    skips = raw.get("skips_7d") if isinstance(raw.get("skips_7d"), dict) else {}
    attention = [{"level": _code(a.get("level"), LEVELS), "kind": _code(a.get("kind")).lower()}
                 for a in (raw.get("attention") or [])[:10] if isinstance(a, dict)] if isinstance(raw.get("attention"), list) else []
    goal_block = raw.get("goal") if isinstance(raw.get("goal"), dict) else {}
    return {
        "mode": _code(raw.get("mode"), ("paper", "live")) or "paper",
        "now": _num(raw.get("now")),
        "currency": currency,
        "total": {"equity": _num(combined.get("equity")), "pnl": _num(combined.get("pnl")), "partial": combined.get("partial") is True,
                  "cash": _num(combined.get("cash")), "today": _num(combined.get("daily_pnl")),
                  "put_in": _num(combined.get("net_contributed"))},
        "month_pnl": _num(goal_block.get("month_pnl_usd")) if currency == "USD" else None,
        "month_partial": goal_block.get("partial") is True,
        "live": _live(raw.get("live")),
        "markets": markets,
        "books": books,
        "kill_switch": {"active": _active(flags.get("kill_switch"))},
        "paused": {"active": _active(flags.get("trading_paused"))},
        "services": services,
        "attention": [a for a in attention if a["level"]],
        "decisions": decisions,
        "skips_7d": {code: n for code, n in skips.items() if code in REASONS and _id(n) is not None and 0 <= n < 10**7},
    }


def money(value: float | None, currency: str = "USD", signed: bool = False) -> str:
    if value is None:
        return "unknown"
    sign = ("+" if value > 0 else "-" if value < 0 else "") if signed else ("-" if value < 0 else "")
    return f"{sign}{SYMBOLS.get(currency, currency + ' ')}{abs(value):,.2f}"


def _said_money(value: float | None, currency: str) -> str:
    if value is None:
        return "not known yet"
    if abs(value) < 0.005:
        return "flat"
    return ("up " if value > 0 else "down ") + money(abs(value), currency)


def unhealthy(state: dict) -> list[str]:
    """Services that are not running well, by name."""
    return [s["name"] for s in state["services"] if s["status"] not in ("ok", "running", "healthy", "idle", "up")]


def spoken(state: dict) -> str:
    """A few sentences to say aloud: the money first, then anything that needs the owner."""
    parts = []
    mode = "Paper trading" if state["mode"] == "paper" else "Trading (" + state["mode"] + ")"
    if state["total"]["pnl"] is not None:
        parts.append(f"{mode} is {_said_money(state['total']['pnl'], state['currency'])} overall"
                     + (", not counting books without an exchange rate yet" if state["total"]["partial"] else "") + ".")
    else:
        parts.append(f"{mode}: the overall result is not known yet.")
    if state["markets"]:
        parts.append(" ".join(f"{m['label']} {_said_money(m['pnl'], state['currency'])}." for m in state["markets"]))
    if state["kill_switch"]["active"]:
        parts.append("The kill switch is on.")
    if state["paused"]["active"]:
        parts.append("Trading is paused.")
    halted = [b["id"] for b in state["books"] if b["halted"]]
    if halted:
        parts.append("Halted: " + ", ".join(halted) + ".")
    down = unhealthy(state)
    if down:
        parts.append("Needs a look: " + ", ".join(down) + ".")
    elif state["services"]:
        parts.append("All services are running.")
    if state["decisions"]:
        last = state["decisions"][0]
        parts.append(f"Latest decision: {last['action'] or last['status']} {last['symbol']}".rstrip() + ".")
    return " ".join(parts)


def said_goal(made: dict) -> str:
    """The goal in a sentence, or "" when there is none."""
    if not made:
        return ""
    aim = money(made.get("target", made["monthly"]), made["currency"])
    raised = f" (raised from {money(made['monthly'], made['currency'])} after months that met it)" if made.get("raised") else ""
    if made["made"] is None:
        return f"Your goal this month is {aim}{raised}. " + (made["note"] or "This month's result is not known yet.")
    share = f"{made['share'] * 100:.0f}%" if made["share"] is not None else ""
    text = f"Goal: {aim} this month{raised}. So far: {money(made['made'], made['currency'], signed=True)}" + (f", {share} of it" if share and made["made"] > 0 else "") + "."
    if made["since"]:
        text += f" (Counted from {made['since']}, when JARVIS first looked this month.)"
    if made["paper"]:
        text += " This is paper money: it does not pay for anything."
    return text


def compact(state: dict) -> dict:
    """The status without the day-by-day history and with each book's five largest positions: what the assistant needs to
    answer from, at a fraction of the length."""
    books = [{**{k: v for k, v in b.items() if k != "series"}, "positions": b["positions"][:5]} for b in state.get("books", [])]
    return {**state, "books": books}


def for_assistant(state: dict, made: dict | None = None) -> str:
    """The status for the assistant to answer from: numbers, ids and codes only (see summary)."""
    lines = ["The user's paper-trading app, read only: JARVIS cannot place orders or change anything there (the user does that "
             "in the trading app's dashboard, which /trading opens). Status: " + json.dumps(compact(state), ensure_ascii=False)]
    if state.get("live"):
        lines.append("About 'live' in the status: the real-money part runs as a shadow test. It records the orders it would place "
                     "and places none; say 'would buy' or 'would sell', never 'bought' or 'sold'. JARVIS cannot change it. "
                     "checks_pass is evidence, not a recommendation: do not advise switching to real money. If past_shadow is true, "
                     "say only that a real-money book is past the shadow test and point to the trading dashboard.")
    if made:
        lines.append("Goal: " + json.dumps(made, ensure_ascii=False))
    lines.append("Spoken summary: " + spoken(state) + (" " + said_goal(made) if made else ""))
    return "\n".join(lines)


# ------------------------------------------------------------------------------------------------- the window's card
def window(cfg, body: dict) -> dict:
    """What /trading shows, after doing what the card asked: connect, disconnect, set or clear the goal, or just look.
    Problems the owner can fix are raised as ValueError (said in the window); a server that does not answer is shown on
    the card instead, beside what JARVIS already knows."""
    action = str((body or {}).get("action") or "show")
    try:
        if action == "connect":
            connect(cfg, str(body.get("address", "")), str(body.get("token", "")))
        elif action == "disconnect":
            disconnect(cfg)
        elif action == "goal":
            items = body.get("items") if isinstance(body.get("items"), list) else []
            set_goal(cfg, items, _num(body.get("monthly")), str(body.get("currency") or "USD"), body.get("raise") is not False)
        elif action == "clear_goal":
            clear_goal(cfg)
    except TradingError as problem:
        raise ValueError(str(problem)) from None
    out = {"connected": connected(cfg), "goal": goal(cfg), "state": None, "progress": None, "said": "", "error": "", "error_kind": ""}
    if out["connected"] and action in ("show", "connect", "goal"):
        try:
            state = fetch(cfg, fresh=(body or {}).get("fresh") is True)
            out["state"], out["progress"] = state, progress(cfg, state)
            out["said"] = " ".join(part for part in (spoken(state), said_goal(out["progress"])) if part)
        except TradingError as problem:
            out["error"], out["error_kind"] = str(problem), problem.kind
    return out
