"""Tier runners. Tier 1: no AI. Tier 2: free-tier model. Tier 3: background coding/research job."""

from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from jcc import receipts, secrets
from jcc.config import Config
from jcc.llm import UNTRUSTED_NOTICE, Models
from jcc.redact import redact
from jcc.usage import Usage
from jcc.vault import PrivateNoteError, Vault


@dataclass
class TierResult:
    answer: str = ""
    status: str = "done"
    model: str = "none"
    tokens: int = 0
    outputs: list[str] = field(default_factory=list)
    error: str = ""


HELP = """**Commands** (or just type normally):
- `/priorities`, `/today`, `/status` (trading bot), `/recent`, `/usage`, `/note <name>`, `/find <words>` — tier 1, no AI
- `/ask <question>`, `/sum [[Note]]` — tier 2, free model
- `/job <task>`, `/research <topic>`, `/skill <name> <task>` — tier 3, background Claude Code job
Personal/financial requests always stay in tier 1. Notes in `Private/` are never sent to any AI."""

# --------------------------------------------------------------------------- tier 1

BotFetcher = Callable[[str, str, str], dict[str, Any]]


def fetch_bot(url: str, user: str, password: str) -> dict[str, Any]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {token}"})
    with urllib.request.urlopen(req, timeout=15) as r:  # GET only: read-only dashboard API
        return json.loads(r.read().decode("utf-8"))


class Tier1:
    def __init__(self, cfg: Config, vault: Vault, usage: Usage,
                 bot_fetcher: BotFetcher | None = None) -> None:
        self.cfg, self.vault, self.usage = cfg, vault, usage
        self.bot_fetcher = bot_fetcher or fetch_bot

    def run(self, handler: str, text: str, arg: str = "") -> TierResult:
        fn = getattr(self, f"h_{handler}", None) or self.h_find
        return fn(arg or text)

    def h_help(self, _: str) -> TierResult:
        return TierResult(HELP)

    def h_priorities(self, _: str) -> TierResult:
        n = self.vault.find_note("Priorities")
        if not n or not n.body.strip():
            return TierResult("No priorities saved yet. Add them to [[Priorities]].")
        return TierResult(n.body.strip(), outputs=[n.rel.removesuffix(".md")])

    def h_tasks(self, _: str) -> TierResult:
        today = date.today().isoformat()
        found: list[str] = []
        sources: list[str] = []
        for n in self.vault.notes():
            is_daily = n.rel.startswith("Daily/") and today in n.rel
            if n.rel in ("Tasks.md",) or is_daily:
                items = re.findall(r"^\s*- \[ \] (.+)$", n.body, re.MULTILINE)
            else:
                items = [t for t in re.findall(r"^\s*- \[ \] (.+)$", n.body, re.MULTILINE)
                         if today in t or "#today" in t]
            if items:
                sources.append(n.rel.removesuffix(".md"))
                found += [f"- [ ] {t}  ([[{n.rel.removesuffix('.md')}]])" for t in items]
        if not found:
            return TierResult("No open tasks for today. Add them to [[Tasks]] or today's daily "
                              f"note `Daily/{today}`.")
        return TierResult(f"**{len(found)} open task(s) for today**\n\n" + "\n".join(found[:40]),
                          outputs=sources[:10])

    def h_bot(self, _: str) -> TierResult:
        if not self.cfg.bot_url:
            return TierResult("", "failed", error="No dashboard is set up. Put its summary address under [bot] in config/local.toml.")
        pw = secrets.get("bot")
        if not pw:
            return TierResult("", "failed", error="Bot dashboard password not set. Run "
                              "`jcc keys set bot` (stored in Windows Credential Manager).")
        try:
            d = self.bot_fetcher(self.cfg.bot_url, self.cfg.bot_user, pw)
        except (urllib.error.URLError, OSError, ValueError) as e:
            return TierResult("", "failed", error=f"Could not reach the bot dashboard: "
                              f"{type(e).__name__}")
        m, t = d.get("money", {}), d.get("trading", {})
        agents = ", ".join(f"{a.get('label')}: {a.get('state', '?')}"
                           for a in d.get("ai", {}).get("agents", []))
        pos = ", ".join(f"{p['symbol']} {p.get('unrealized_pnl', 0):+.2f}"
                        for p in d.get("positions", [])) or "none (holding cash)"
        ans = (f"**Trading bot: {d.get('state', '?')}** — {d.get('state_message', '')}\n\n"
               f"- Account value: ${m.get('equity', 0):,.2f} (start ${m.get('starting_cash', 0):,.2f})\n"
               f"- Total P&L: {m.get('total_pnl', 0):+,.2f} ({m.get('total_pnl_pct', 0):+.2f}%), "
               f"today {m.get('today_pnl', 0):+,.2f}\n"
               f"- Trades: {t.get('trades_total', 0)} total, {t.get('trades_today', 0)} today\n"
               f"- Open positions: {pos}\n"
               f"- Agents: {agents or 'n/a'}\n\n_Paper trading only. Read-only status._")
        return TierResult(ans)

    def h_recent(self, _: str) -> TierResult:
        rows = receipts.recent(self.vault, 10)
        if not rows:
            return TierResult("No requests yet.")
        lines = [f"- {r.get('time', '')[:16]} · tier {r.get('tier')} · {r.get('status')} · "
                 f"[[{receipts.receipt_rel(r['id']).removesuffix('.md')}|{r.get('request', '')[:60]}]]"
                 for r in rows]
        return TierResult("**Recent requests**\n\n" + "\n".join(lines))

    def h_usage(self, _: str) -> TierResult:
        lines = [f"- {p}: {u['requests']}/{u['requests_cap']} requests, "
                 f"{u['tokens']:,}/{u['tokens_cap']:,} tokens"
                 for p, u in self.usage.summary().items()]
        return TierResult("**Free-tier usage today** (caps are below the real free limits)\n\n"
                          + "\n".join(lines))

    def h_note(self, text: str) -> TierResult:
        name = re.sub(r"^(/note|open|show|display|read( me)?)\s+(the |my )?(note|page)?\s*", "",
                      text.strip(), flags=re.I).strip()
        n = self.vault.find_note(name) if name else None
        if not n:
            return self.h_find(name or text)
        return TierResult(f"![[{n.rel.removesuffix('.md')}]]",
                          outputs=[n.rel.removesuffix(".md")])

    def h_find(self, text: str) -> TierResult:
        q = re.sub(r"^(/find|find|search|list)\s+(notes?|pages?)?\s*(about|on|for)?\s*", "",
                   text.strip(), flags=re.I)
        words = [w for w in re.findall(r"[a-z0-9]{3,}", q.lower())
                 if w not in {"the", "and", "for", "about", "what", "my", "with", "this"}]
        if not words:
            return TierResult("Tell me what to look for, e.g. `/find chemistry notes`.")
        scored = []
        for n in self.vault.notes():
            if n.rel.startswith(("Requests/", "System/")):
                continue
            hay = (n.rel + " " + n.body).lower()
            score = sum(hay.count(w) for w in words)
            if score:
                scored.append((score, n.rel.removesuffix(".md")))
        scored.sort(reverse=True)
        if not scored:
            return TierResult(f"No notes found for: {' '.join(words)}")
        return TierResult("**Matching notes**\n\n" + "\n".join(f"- [[{r}]]" for _, r in scored[:10]),
                          outputs=[r for _, r in scored[:5]])

    def h_private(self, text: str) -> TierResult:
        res = self.h_find(text)
        res.answer = ("This looks personal or financial, so it stays on your laptop: no AI was "
                      "used. Here is what I found in your vault:\n\n" + res.answer)
        return res


# --------------------------------------------------------------------------- tier 2

T2_SYSTEM = ("You are a concise personal assistant. Answer in under 200 words using Markdown. "
             "If you are unsure, say so. " + UNTRUSTED_NOTICE)


class Tier2:
    def __init__(self, cfg: Config, vault: Vault, models: Models) -> None:
        self.cfg, self.vault, self.models = cfg, vault, models

    def run(self, handler: str, text: str, arg: str = "", context: str = "") -> TierResult:
        request = arg or text
        names = re.findall(r"\[\[([^\]|#]+)", request)
        notes_block, used = "", []
        for name in names[:3]:
            try:
                n = self.vault.note_for_ai(name)
            except PrivateNoteError as e:
                return TierResult("", "failed", error=str(e) + ". Nothing was sent to any model.")
            if n:
                used.append(n.rel.removesuffix(".md"))
                notes_block += (f"\n<untrusted source={json.dumps(n.rel)}>\n{n.body[:12000]}\n"
                                "</untrusted>\n")
        if names and not used:
            return TierResult("", "failed", error=f"Note not found: {', '.join(names)}")
        slots = (["gemini_flash", "gemini_lite", "groq"] if handler == "summarize" and notes_block
                 else ["gemini_lite", "groq"])
        user = f"REQUEST: {request}\n{notes_block}" if notes_block else f"REQUEST: {request}"
        if context:
            user += "\n<untrusted source='chat-history'>\n" + context[:12000] + "\n</untrusted>"
        result, errors = self.models.chat_with_fallback(slots, T2_SYSTEM, user, max_tokens=700)
        if result is None:
            return TierResult("", "queued", outputs=used,
                              error="No free model available right now (" + "; ".join(errors) +
                              "). Queued: it will run when a daily cap resets.")
        return TierResult(result.text, "done", result.model, result.tokens, outputs=used)
