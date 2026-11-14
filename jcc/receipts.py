"""Receipts: every request leaves Requests/YYYY/MM/<id>.md with standard frontmatter."""

from __future__ import annotations

import json
import secrets as _rand
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from jcc.redact import redact
from jcc.vault import Vault, parse_frontmatter, render_note

STATUSES = ("done", "failed", "queued", "running", "paused", "cancelled", "needs_approval")
FIELDS = ("id", "time", "request", "tier", "router_method", "confidence", "model", "tokens",
          "cost", "duration_ms", "status", "outputs")


def new_id(now: datetime | None = None) -> str:
    now = now or datetime.now()
    return now.strftime("%Y%m%d-%H%M%S-") + _rand.token_hex(2)


def receipt_rel(rid: str) -> str:
    return f"Requests/{rid[0:4]}/{rid[4:6]}/{rid}.md"


@dataclass
class Receipt:
    id: str
    time: str
    request: str
    tier: int
    router_method: str
    confidence: float
    model: str = "none"
    tokens: int = 0
    duration_ms: int = 0
    status: str = "done"
    outputs: list[str] = field(default_factory=list)
    reason: str = ""
    handler: str = ""
    error: str = ""
    answer: str = ""

    def frontmatter(self) -> dict[str, Any]:
        if self.status not in STATUSES:
            raise ValueError(f"bad status {self.status}")
        return {
            "id": self.id,
            "time": self.time,
            "request": redact(self.request),
            "tier": self.tier,
            "router_method": self.router_method,
            "confidence": round(float(self.confidence), 2),
            "model": self.model or "none",
            "tokens": int(self.tokens),
            "cost": 0,  # free tiers and existing plans only, always 0
            "duration_ms": int(self.duration_ms),
            "status": self.status,
            "outputs": [o if o.startswith("[[") else f"[[{o}]]" for o in self.outputs],
            "reason": self.reason,
            "tags": ["request", f"tier{self.tier}"],
        }

    def body(self) -> str:
        parts = [f"# Request {self.id}", "", f"> {redact(self.request)}", ""]
        parts.append(f"**Tier {self.tier}** via {self.router_method} "
                     f"({self.confidence:.2f}): {self.reason}")
        if self.answer:
            parts += ["", "## Answer", "", self.answer]
        if self.error:
            parts += ["", "## Problem", "", self.error]
        if self.outputs:
            parts += ["", "## Outputs", ""] + [f"- {o if o.startswith('[[') else f'[[{o}]]'}"
                                               for o in self.outputs]
        return "\n".join(parts)


def write(vault: Vault, r: Receipt) -> Path:
    return vault.write(receipt_rel(r.id), render_note(r.frontmatter(), r.body()))


def load(vault: Vault, rid: str) -> tuple[dict[str, Any], str] | None:
    text = vault.read(receipt_rel(rid))
    return parse_frontmatter(text) if text else None


def update_status(vault: Vault, rid: str, status: str, append: str = "",
                  extra: dict[str, Any] | None = None) -> None:
    loaded = load(vault, rid)
    if loaded is None:
        return
    fm, body = loaded
    fm["status"] = status
    fm.update(extra or {})
    if append:
        body = body.rstrip() + "\n\n" + append
    vault.write(receipt_rel(rid), render_note(fm, body))


def recent(vault: Vault, limit: int = 10) -> list[dict[str, Any]]:
    root = vault.root / "Requests"
    files = sorted(root.rglob("*.md"), reverse=True)[: limit * 3] if root.exists() else []
    out = []
    for f in files:
        try:
            fm, _ = parse_frontmatter(f.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        if fm.get("id"):
            out.append(fm)
    out.sort(key=lambda x: str(x.get("id", "")), reverse=True)
    return out[:limit]


def log_routing(vault: Vault, r: Receipt, errors: list[str]) -> None:
    """Append one JSON line per routing decision (System/routing-log.jsonl) to improve rules."""
    line = json.dumps({"id": r.id, "time": r.time, "request": redact(r.request)[:300],
                       "tier": r.tier, "method": r.router_method,
                       "confidence": round(r.confidence, 2), "reason": r.reason,
                       "errors": [redact(e) for e in errors]}, ensure_ascii=False)
    p = vault.path("System/routing-log.jsonl")
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8", newline="\n") as f:
        f.write(redact(line) + "\n")
