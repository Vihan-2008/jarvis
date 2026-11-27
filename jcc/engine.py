"""Request flow: route -> run tier -> receipt -> logs/usage notes."""

from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from jcc import agents, receipts, workspace, guard
from jcc.config import Config
from jcc.jobs import JobLauncher, Spawner
from jcc.llm import Models, Transport
from jcc.redact import redact
from jcc.router import Decision, GeminiLiteClassifier, NoClassifier, Router, rules_markdown
from jcc.tiers import BotFetcher, Tier1, Tier2, TierResult
from jcc.usage import Usage
from jcc.vault import Vault, parse_frontmatter, render_note

INBOX = "Inbox.md"
_TODO = re.compile(r"^(\s*)- \[ \] (.+?)\s*$")


class Engine:
    def __init__(self, cfg: Config, transport: Transport | None = None,
                 spawner: Spawner | None = None, bot_fetcher: BotFetcher | None = None) -> None:
        self.cfg = cfg
        self.vault = Vault(cfg.vault)
        self.usage = Usage(cfg.state_dir, cfg.caps)
        self.models = Models(cfg, self.usage, transport)
        classifier = (GeminiLiteClassifier(self.models) if cfg.classifier == "gemini_lite"
                      else NoClassifier())
        self.router = Router(classifier, cfg.rule_confidence, cfg.model_confidence,
                             cfg.tier3_min_confidence)
        self.tier1 = Tier1(cfg, self.vault, self.usage, bot_fetcher)
        self.tier2 = Tier2(cfg, self.vault, self.models)
        self.jobs = JobLauncher(cfg, self.vault, spawner)

    def close(self) -> None:
        self.usage.close()

    # ------------------------------------------------------------------ main flow
    def process(self, text: str, rid: str | None = None, retry_tier2: bool = False,
                project: str | None = None, agent: str | None = None,
                chat_id: str | None = None, context: str = "", mode: str = "auto",
                manual_model: str = "auto", effort: str = "auto", image_ids=None, doc_ids=None) -> receipts.Receipt:
        """project: project key, "auto" (detect from text) or "none"; agent: name or "auto"."""
        text = redact(text.strip())
        rid = rid or receipts.new_id()
        t0 = time.monotonic()
        if mode in ("code", "assistant") and guard.personal_reason(text) not in (None, "trading bot data"):
            d = Decision(1, "privacy", 1.0, "personal data stays local", "private", text)
        elif mode == "assistant":
            d = Decision(3, "chat", 1.0, "conversation with a coding subscription", "chat", text)
        elif mode == "code" and not retry_tier2:
            d = Decision(3, "chat", 1.0, "coding chat", "job", text)
        elif mode == "chat" and not guard.personal_reason(text):
            d = Decision(2, "chat", 1.0, "discussion in a chat", "answer", text)
        elif retry_tier2:
            # a queued tier 2 request is retried AS tier 2; it is never re-routed (a retry must
            # not be able to escalate into a tier 3 job)
            d = Decision(2, "retry", 1.0, "retry of a queued tier 2 request", "answer")
        else:
            d = self.router.route(text)
        try:
            if d.tier == 1:
                res = self.tier1.run(d.handler, text, d.arg)
            elif d.tier == 2:
                res = self.tier2.run(d.handler, text, d.arg, context=context)
            else:
                out = self.jobs.launch(rid, d.handler or "job", d.arg or text, project, agent,
                                       chat_id=chat_id, context=context, manual_model=manual_model, effort=effort,image_ids=image_ids,doc_ids=doc_ids)
                res = TierResult(out.message, out.status, out.agent or "none",
                                 0, out.outputs, "" if out.status != "failed" else out.message)
        except Exception as e:  # noqa: BLE001 - every request must still leave a receipt
            res = TierResult("", "failed", error=f"{type(e).__name__}: {redact(str(e))[:300]}")
        model = res.model if res.model != "none" else (d.model or "none")
        r = receipts.Receipt(
            id=rid, time=datetime.now().isoformat(timespec="seconds"), request=text,
            tier=d.tier, router_method=d.method, confidence=d.confidence, model=model,
            tokens=res.tokens + d.tokens, duration_ms=int((time.monotonic() - t0) * 1000),
            status=res.status, outputs=res.outputs, reason=d.reason, handler=d.handler,
            error=res.error, answer=res.answer)
        receipts.write(self.vault, r)
        receipts.log_routing(self.vault, r, d.classifier_errors)
        if r.status == "failed" or d.classifier_errors:
            self.append_error(r, d.classifier_errors)
        self.write_usage_note()
        return r

    # ------------------------------------------------------------------ inbox
    def process_inbox(self, min_age_s: float = 3.0) -> list[receipts.Receipt]:
        p = self.vault.path(INBOX)
        if not p.exists() or time.time() - p.stat().st_mtime < min_age_s:
            return []
        lines = p.read_text("utf-8").splitlines()
        done: list[receipts.Receipt] = []
        changed = False
        for i, line in enumerate(lines):
            m = _TODO.match(line)
            if not m or "[[Requests/" in line:
                continue
            r = self.process(m.group(2))
            link = receipts.receipt_rel(r.id).removesuffix(".md")
            lines[i] = (f"{m.group(1)}- [x] {redact(m.group(2))} → [[{link}|receipt]] "
                        f"(tier {r.tier}, {r.status})")
            done.append(r)
            changed = True
        if changed:
            self.vault.write(INBOX, "\n".join(lines) + "\n")
        return done

    def retry_queued(self) -> list[receipts.Receipt]:
        """Re-run requests queued because a daily cap was reached (once caps have room again)."""
        workspace.refresh(self.cfg)
        out = []
        root = self.vault.root / "Requests"
        for f in sorted(root.rglob("*.md")) if root.exists() else []:
            fm, body = parse_frontmatter(f.read_text("utf-8"))
            if fm.get("status") != "queued" or int(fm.get("tier", 0)) != 2:
                continue
            if not any(self.models.available(s) for s in ("gemini_lite", "groq")):
                break
            r = self.process(str(fm.get("request", "")), rid=str(fm["id"]), retry_tier2=True)
            out.append(r)
        from jcc import task_queue
        queue_rows=task_queue.ordered(self.cfg)
        for fm in queue_rows:
            if fm.get("status") != "queued" or task_queue.blocked(self.cfg,str(fm["id"]),queue_rows):
                continue
            task = str(fm.get("task", ""))
            prefer = str(fm.get("preferred_agent", "auto"))
            plan = agents.plan(self.cfg, task, self.usage.cooldowns(), prefer=prefer)
            from jcc.governor import settings as resource_settings
            if not plan.agents or self.jobs.running_jobs() >= (resource_settings(self.cfg)['max_parallel_jobs'] or self.cfg.tier3_max_running):
                continue
            rid = str(fm["id"])
            context = str(fm.get("context", ""))
            if fm.get("chat_id") and not context:
                from jcc.chats import Chats
                context = "<chat-history>\n" + Chats(self.cfg).context(fm["chat_id"], until=rid) + "\n</chat-history>"
            outcome = self.jobs.launch(rid, str(fm.get("kind", "job")), task,
                                       project=str(fm.get("project_key", "auto")), agent=prefer,
                                       chat_id=fm.get("chat_id") or None, context=context,
                                       manual_model=str(fm.get("manual_model", "auto")), effort=str(fm.get("effort", "auto")),image_ids=fm.get("image_ids") or [],doc_ids=fm.get("doc_ids") or [])
            receipts.update_status(self.vault, rid, outcome.status, append=outcome.message)
            if fm.get("chat_id"):
                from jcc.chats import Chats
                Chats(self.cfg).update(fm["chat_id"], message={"role": "assistant", "content": outcome.message,
                                                           "receipt": rid, "status": outcome.status})
        return out

    # ------------------------------------------------------------------ system notes
    def write_usage_note(self) -> None:
        s = self.usage.summary()
        fm: dict[str, Any] = {"date": self.usage.today(), "updated":
                              datetime.now().isoformat(timespec="seconds")}
        for p, u in s.items():
            fm[f"{p}_requests"] = u["requests"]
            fm[f"{p}_requests_cap"] = u["requests_cap"]
            fm[f"{p}_tokens"] = u["tokens"]
            fm[f"{p}_tokens_cap"] = u["tokens_cap"]
        rows = "\n".join(f"| {p} | {u['requests']} / {u['requests_cap']} | "
                         f"{u['tokens']:,} / {u['tokens_cap']:,} |" for p, u in s.items())
        body = ("# Free-tier usage today\n\nCaps are set below the real free limits. Cost is "
                "always 0.\n\n| Provider | Requests | Tokens |\n|---|---|---|\n" + rows)
        self.vault.write("System/Usage.md", render_note(fm, body))

    def append_error(self, r: receipts.Receipt, extra: list[str]) -> None:
        p = self.vault.path("System/Errors.md")
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_text("# Errors and fallbacks\n\n", "utf-8")
        msg = r.error or "; ".join(extra)
        link = receipts.receipt_rel(r.id).removesuffix(".md")
        with open(p, "a", encoding="utf-8", newline="\n") as f:
            f.write(redact(f"- {r.time} [[{link}|{r.id}]] tier {r.tier} {r.status}: {msg}"[:500])
                    + "\n")

    def write_rules_note(self) -> Path:
        return self.vault.write("System/Router Rules.md", rules_markdown())
