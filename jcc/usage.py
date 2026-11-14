"""Per-provider daily request/token caps, stored outside the vault (not synced)."""

from __future__ import annotations

import sqlite3
import time
from datetime import date
from pathlib import Path

from jcc.config import Cap


class CapReached(RuntimeError):
    pass


# One row for each request the fast assistant answered: which brain, how many tokens, how long it took.
TURNS = ("create table if not exists turns (ts real, day text, engine text, model text, spoken int, status text, input int, cached int,"
         " written int, output int, cost real, seconds real, first real, tools int)")


def log_turn(state_dir: Path, row: dict) -> None:
    """Keep the numbers of one answered request (on this PC only). Never raises: a full disk must not break an answer."""
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(state_dir / "usage.sqlite3", timeout=10)
        try:
            db.execute(TURNS)
            db.execute("insert into turns values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (time.time(), date.today().isoformat(), str(row.get("engine", ""))[:40], str(row.get("model", ""))[:80], int(bool(row.get("spoken"))),
                        str(row.get("status", ""))[:20], int(row.get("input") or 0), int(row.get("cached") or 0), int(row.get("written") or 0),
                        int(row.get("output") or 0), float(row.get("cost") or 0.0), float(row.get("seconds") or 0.0), float(row.get("first") or 0.0),
                        int(row.get("tools") or 0)))
            db.commit()
        finally:
            db.close()
    except (sqlite3.Error, OSError, ValueError, TypeError):
        pass


def turns(state_dir: Path, days: int = 7) -> list[dict]:
    """The assistant's requests of the last days, added up by day and by model."""
    try:
        db = sqlite3.connect(state_dir / "usage.sqlite3", timeout=10)
        try:
            db.execute(TURNS)
            rows = db.execute("select day, engine, model, count(*), sum(input), sum(cached), sum(written), sum(output), sum(cost), avg(seconds), avg(first), "
                              "sum(case when status = 'done' then 1 else 0 end) from turns where ts > ? group by day, engine, model order by day desc, count(*) desc",
                              (time.time() - days * 86400,)).fetchall()
        finally:
            db.close()
    except (sqlite3.Error, OSError):
        return []
    names = ("day", "engine", "model", "requests", "input", "cached", "written", "output", "cost", "seconds", "first", "done")
    return [{name: (round(value, 4) if isinstance(value, float) else value) for name, value in zip(names, row)} for row in rows]


class Usage:
    def __init__(self, state_dir: Path, caps: dict[str, Cap]) -> None:
        state_dir.mkdir(parents=True, exist_ok=True)
        self.caps = caps
        self.db = sqlite3.connect(state_dir / "usage.sqlite3", timeout=30)
        self.db.execute(
            "create table if not exists usage (day text, provider text, requests int, tokens int,"
            " primary key (day, provider))"
        )
        self.db.execute(
            "create table if not exists events (ts real, day text, provider text, ok int,"
            " tokens int, note text)"
        )
        self.db.execute("create table if not exists cooldowns (agent text primary key, until real)")
        self.db.execute(
            "create table if not exists agent_runs (ts real, day text, agent text, level text,"
            " outcome text, seconds real)"
        )
        self.db.execute(TURNS)
        self.db.commit()

    # ------------------------------------------------------------ coding agents
    def set_cooldown(self, agent: str, until: float) -> None:
        self.db.execute("insert into cooldowns values (?,?) on conflict(agent) do update set"
                        " until = excluded.until", (agent, until))
        self.db.commit()

    def cooldowns(self) -> dict[str, float]:
        return {a: u for a, u in self.db.execute("select agent, until from cooldowns")}

    def record_agent_run(self, agent: str, level: str, outcome: str, seconds: float) -> None:
        self.db.execute("insert into agent_runs values (?,?,?,?,?,?)",
                        (time.time(), self.today(), agent, level, outcome, seconds))
        self.db.commit()

    def agent_runs_today(self) -> dict[str, int]:
        return {a: n for a, n in self.db.execute(
            "select agent, count(*) from agent_runs where day=? group by agent", (self.today(),))}

    @staticmethod
    def today() -> str:
        return date.today().isoformat()

    def get(self, provider: str, day: str | None = None) -> tuple[int, int]:
        row = self.db.execute(
            "select requests, tokens from usage where day=? and provider=?",
            (day or self.today(), provider),
        ).fetchone()
        return (row[0], row[1]) if row else (0, 0)

    def remaining(self, provider: str) -> tuple[int, int]:
        cap = self.caps.get(provider)
        if cap is None:
            return (0, 0)
        r, t = self.get(provider)
        return (max(0, cap.requests - r), max(0, cap.tokens - t))

    def can_use(self, provider: str, est_tokens: int = 0) -> bool:
        req_left, tok_left = self.remaining(provider)
        return req_left > 0 and tok_left > est_tokens

    def reserve(self, provider: str, est_tokens: int = 0) -> None:
        """Count a request BEFORE it is sent, so concurrent callers can't overshoot the cap."""
        if not self.can_use(provider, est_tokens):
            raise CapReached(f"daily cap reached for {provider}")
        self.db.execute(
            "insert into usage values (?,?,1,0) on conflict(day,provider) do update set"
            " requests = requests + 1",
            (self.today(), provider),
        )
        self.db.commit()

    def record(self, provider: str, tokens: int, ok: bool, note: str = "") -> None:
        self.db.execute(
            "insert into usage values (?,?,0,?) on conflict(day,provider) do update set"
            " tokens = tokens + excluded.tokens",
            (self.today(), provider, int(tokens)),
        )
        self.db.execute(
            "insert into events values (?,?,?,?,?,?)",
            (time.time(), self.today(), provider, int(ok), int(tokens), note[:200]),
        )
        self.db.commit()

    def summary(self) -> dict[str, dict[str, int]]:
        out = {}
        for p, cap in self.caps.items():
            r, t = self.get(p)
            out[p] = {"requests": r, "requests_cap": cap.requests, "tokens": t,
                      "tokens_cap": cap.tokens}
        return out

    def close(self) -> None:
        self.db.close()
