"""Local GUI: a small web server on 127.0.0.1 that serves the JARVIS control screen.

Security:
- Binds to 127.0.0.1 only, and takes the port for itself alone (on Windows another program could otherwise open the
  same port beside it); requests with any other Host header are refused (DNS rebinding).
- Every API call needs a random per-launch token (sent in a header, which other websites
  cannot add without a CORS preflight this server never approves).
- POST bodies must be JSON; text is length-limited; receipt ids are validated.
- Everything goes through the same Engine: router, caps, guard, receipts, redaction.
"""

from __future__ import annotations

import collections
import errno
import hmac
import functools
import json
import os
import re
import secrets as _rand
import socket
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from jcc import agents, config, receipts, secrets, watcher, workspace
from jcc.chats import Chats
from jcc.lock import InstanceLock
from jcc.engine import Engine
from jcc.lock import watcher_lock
from jcc.redact import redact
from jcc.usage import Usage
from jcc.vault import parse_frontmatter
from jcc.vault import atomic_write
from jcc import history, quota, models, routing, prompt_master, cloud_memory, efficiency, job_control, diagnostics, learning, activity, review, onboarding, maintenance, context_inspector, memory_conflicts, insights, delivery, task_queue, work_history, routing_guard
from jcc.workbench import Workbench
from jcc import project_policy, planning, evaluations, handoffs, operations, governor, budgets, restorepoints, library, provenance, prompt_preferences, documents, retrieval

STATIC = Path(__file__).with_name("static") / "desktop.html"
MAX_TEXT = 400_000              # (what is typed has no practical limit: a long paste, a whole spec)
SCRIPTS = ("/workbench.js", "/assistant.js", "/horizon.js", "/horizon.css", "/delivery.js", "/reliability.js", "/operations.js", "/operations.css",
           "/everyday.js", "/everyday.css", "/nova.css", "/nova.js", "/nova-core.js", "/nova-rich.js", "/nova-panels.js", "/nova-voice.js",
           "/nova-audio.js", "/nova-mic.js", "/nova-work.js", "/nova-security.js", "/nova-permissions.js", "/nova-routines.js", "/nova-kinds.js", "/nova-gallery.js", "/nova-start.js", "/nova-sites.js", "/nova-connectors.js", "/vendor/xterm.js", "/vendor/xterm.css", "/vendor/addon-fit.js")
# Tools the JARVIS app itself carries out for the assistant, each only with a one-time permit from the gate.
APP_TOOLS = frozenset({"open_app", "list_projects", "create_project", "build_with_coding_agents", "make_image", "set_timer", "set_reminder",
                       "list_reminders", "cancel_reminder", "remember", "forget", "add_note", "send_email", "use_accounts",
                       "list_sites", "site_read", "site_change", "site_publish"})
# A page JARVIS shows (something a reply made, a file of a project, a pinned panel) runs in a sealed frame at an address of
# its own: it cannot reach JARVIS, the conversation or the files on this PC. Sealed, it cannot reach the internet either: no
# pictures or data from anywhere, code and styles only from the well-known libraries, no form sent off, no window opened.
# A page may have been written from what was read on a web page or in an email, and it opens by itself: this way nothing
# in it can be sent anywhere. Its owner can allow the internet for one page, with a click.
# Two things no such rule reaches are closed by a guard that is put first in the page (jcc/static/preview-guard.js):
# WebRTC, and frames inside the page. The page cannot start itself afresh without that guard: it is always shown in a
# frame, and the page that holds the frame lets it go nowhere but this server (frame-src 'self'), which also refuses an
# address that is itself a script (javascript:, data:, blob:).
LIBRARIES = "https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com"
PREVIEW_POLICY = ("sandbox allow-scripts allow-forms allow-modals; default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' " + LIBRARIES + " https://cdn.tailwindcss.com; "
                  "style-src 'unsafe-inline' " + LIBRARIES + " https://fonts.googleapis.com; img-src data: blob:; font-src data: " + LIBRARIES + " https://fonts.gstatic.com; "
                  "media-src data: blob:; connect-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'")
PREVIEW_ONLINE = ("sandbox allow-scripts allow-forms allow-modals allow-popups; default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' https:; "
                  "style-src 'unsafe-inline' https:; img-src data: blob: https:; font-src data: https:; media-src data: blob: https:; "
                  "connect-src https:; frame-ancestors 'self'")


@functools.lru_cache(maxsize=1)
def _guard() -> str:
    return (STATIC.parent / "preview-guard.js").read_text("utf-8")


def sealed_page(page: str) -> str:
    """A page as it is sent sealed: the guard put first, and the one piece of markup that makes a tree the guard could
    not look into (a closed shadow tree) made into an ordinary attribute."""
    page = re.sub(r"(?i)shadowrootmode", "data-shadowrootmode", page)
    start = re.match(r"\s*<!doctype[^>]*>", page, re.I)          # (the first line has to stay first, or the page is laid out the old way)
    at = start.end() if start else 0
    return page[:at] + "<script>" + _guard() + "</script>" + page[at:]


# Opened as a window of its own, a page is shown inside a frame there too: on its own it could take itself to any address.
PREVIEW_WINDOW = ('<!doctype html><meta charset="utf-8"><title>JARVIS \u00b7 Preview</title><style>html,body{margin:0;height:100%;background:#fff}'
                  'iframe{display:block;border:0;width:100%;height:100%}</style><iframe sandbox="SANDBOX" referrerpolicy="no-referrer" src="/preview/IDENT"></iframe>')
WINDOW_POLICY = "default-src 'none'; style-src 'unsafe-inline'; frame-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")


class GuiState:
    def __init__(self, cfg: config.Config, engine_kw: dict[str, Any] | None = None) -> None:
        self.cfg = cfg
        self.engine_kw = engine_kw or {}
        self.token = _rand.token_urlsafe(24)
        pairing = cfg.state_dir / "browser-sync-key"
        if not pairing.exists():
            atomic_write(pairing, _rand.token_urlsafe(32))
        self.sync_token = pairing.read_text("utf-8").strip()
        self.busy = 0
        self.last_error_at = 0.0
        self.watcher = "off"            # running | external | off
        self.log: collections.deque[str] = collections.deque(maxlen=40)
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.quota_lock = threading.Lock()
        self.permits: dict[str, tuple] = {}
        self.tray_key = _rand.token_urlsafe(24)      # lets the tray helper (same Windows account) ask for a voice chat
        try:
            cfg.state_dir.mkdir(parents=True, exist_ok=True)
            atomic_write(cfg.state_dir / "tray-key", self.tray_key)
        except OSError:
            pass
        self.previews: collections.OrderedDict[str, tuple[str, bool]] = collections.OrderedDict()      # id -> (the page, may it load from the internet)
        self.bench = Workbench(cfg)
        from jcc.pty_terminal import PtyManager
        self.ptys = PtyManager(cfg)
        from jcc.webview import WebView
        self.web = WebView(cfg)
        from jcc.assistant import Assistant
        self.assistant = Assistant(cfg)
        from jcc.computer import Computer
        self.computer = Computer(cfg, self.engine_kw.get('transport'))

    def refresh_quota(self) -> None:
        if not self.quota_lock.acquire(blocking=False):
            return
        def run():
            try:
                quota.refresh(self.cfg)
            finally:
                self.quota_lock.release()
        threading.Thread(target=run, daemon=True, name="account-allowances").start()

    def add_log(self, line: str) -> None:
        self.log.append(f"{time.strftime('%H:%M:%S')}  {redact(line)}")

    # ------------------------------------------------------------------ actions
    def ask(self, text: str, agent: str | None = None, project: str | None = None) -> dict[str, Any]:
        agent = agent if agent in ("auto", *self.cfg.agents) else "auto"
        project = project if project in ("auto", "none", *self.cfg.projects) else "auto"
        with self.lock:
            self.busy += 1
        e = Engine(self.cfg, **self.engine_kw)
        try:
            r = e.process(text, project=project, agent=agent)
        finally:
            e.close()
            with self.lock:
                self.busy -= 1
        if r.status == "failed":
            self.last_error_at = time.time()
        self.add_log(f"{r.id} tier {r.tier} {r.status}: {r.request[:60]}")
        return {"id": r.id, "tier": r.tier, "router_method": r.router_method,
                "confidence": r.confidence, "status": r.status, "model": r.model,
                "tokens": r.tokens, "duration_ms": r.duration_ms, "answer": r.answer,
                "error": r.error, "reason": r.reason, "outputs": r.outputs,
                "receipt": receipts.receipt_rel(r.id), "obsidian": self.obsidian_link(
                    receipts.receipt_rel(r.id))}

    def obsidian_link(self, rel: str) -> str:
        return (f"obsidian://open?vault={quote(self.cfg.vault.name)}"
                f"&file={quote(rel.removesuffix('.md'))}")

    def send_chat(self, cid: str, text: str, agent: str = "auto", mode: str = "auto",
                  manual_model: str = "auto", effort: str = "auto", files=None, use_browser=False, uploads=None,
                  as_job: bool = False, project: str | None = None) -> dict:
        """One message in a chat. as_job: a coding job started for a request that is already in this chat (by the
        assistant, or by a planner): the job reports here, without the task being added as a second message of the owner's."""
        workspace.refresh(self.cfg)
        models.validate(self.cfg, manual_model, effort)
        chats = Chats(self.cfg)
        chat = chats.get(cid)
        lock = InstanceLock(self.cfg.state_dir / f"send-{cid}.lock")
        if not lock.acquire():
            raise ValueError("A message is being sent. Try again in a moment.")
        try:
            rid = receipts.new_id()
            context = self.bench.attachment_context(files or [], use_browser, uploads or []) + "\n\n<chat-history>\n" + chats.context(cid) + "\n</chat-history>"
            labels = [str(f.get("path", "file")) for f in (files or [])[:4]] + [str(f.get("name", "file")) for f in (uploads or [])[:3]]
            if use_browser:
                labels.append("Shared browser page")
            from jcc.image_inputs import selected as selected_images
            image_ids=selected_images(chat,text,uploads)
            from jcc.image_inputs import validate as validate_images
            validate_images(self.cfg,image_ids)
            message_text = text + ("\n\nAttached: " + ", ".join(labels) if labels else "")
            work_chat = cid
            if as_job:
                # The chat where it was asked is the Master chat; this piece of work gets a chat of its own, named after
                # what it works on, under the Master. The Master keeps a line for it (and hears how it goes).
                master_id = str(chat.get("parent") or cid)
                master = chats.get(master_id) if master_id != cid else chat
                if not str(master.get("title") or "").startswith("Master"):
                    chats.update(master_id, title="Master: " + str(master.get("title") or "New chat"))
                name = " ".join(text.split())[:70]
                if name.lower().startswith("step "):
                    name = name.split(" - ", 1)[-1][:70] if " - " in name else name
                work_chat = chats.create(name, project or chat.get("project") or None, parent=master_id)["id"]
                chats.update(work_chat, message={"role": "user", "content": text, "receipt": rid})
                chats.update(master_id, archived=False, message={"role": "assistant", "content": "Started: " + name, "receipt": rid, "status": "queued",
                                                                 "job": True, "task": text[:300], "child": work_chat})
                cid = master_id
            else:
                chats.update(cid, archived=False, message={"role": "user", "content": message_text, "receipt": rid,"image_ids":image_ids})
            if mode not in ("auto", "code", "chat"):
                raise ValueError("Choose Auto, Build or Ask mode.")
            from jcc import mods
            text = mods.expand(self.cfg, text)[0]           # one of the owner's own commands: what it stands for is what is asked (the chat keeps what was typed)
            if mode == "auto" and chat.get("project") and not re.match(
                    r"^(what|why|how|explain|describe|can you explain|tell me|summarize)\b", text, re.I):
                mode = "code"
            elif mode == "chat":
                mode = "assistant"
            elif mode == "auto" and not text.startswith("/"):
                from jcc.router import apply_rules
                ruled = apply_rules(text)
                if not ruled or ruled.tier == 2:
                    mode = "assistant"
            e = Engine(self.cfg, **self.engine_kw)
            with self.lock:
                self.busy += 1
            try:
                r = e.process(text, rid=rid, project=project or chat.get("project") or "none", agent=agent,
                              chat_id=work_chat, context=context, mode=mode, manual_model=manual_model, effort=effort,image_ids=image_ids)
            finally:
                e.close()
                with self.lock:
                    self.busy -= 1
            chats.update(work_chat, message={"role": "assistant", "content": r.answer or r.error or r.status,
                                            "receipt": rid, "status": r.status, "model": r.model, **({"job": True, "task": text[:300]} if as_job else {})})
            return chats.get(cid)
        finally:
            lock.discard()

    def voice_tool(self, body: dict) -> dict:
        """Requests from the assistant's tools. `gate` decides; `do` carries out exactly what a gate approved."""
        op, sid = body.get("op"), str(body.get("session", ""))
        if op == "gate":
            tool = str(body.get("tool", ""))
            args = body.get("args") if isinstance(body.get("args"), dict) else {}
            answer = self.assistant.gate(sid, tool, args, str(body.get("window", "")), str(body.get("control", "")))
            if answer.get("ok") and tool in APP_TOOLS:
                permit, now = _rand.token_urlsafe(18), time.time()
                with self.lock:
                    self.permits = {k: v for k, v in self.permits.items() if v[3] > now}
                    self.permits[permit] = (sid, tool, args, now + 180)
                answer["permit"] = permit
            return answer
        if op == "mail":       # how the owner's email goes out, so the tools write it where they really write their mail
            from jcc import assistant as helper, mailer
            if body.get("use") in ("gmail", "app") and helper.settings(self.cfg)["mail"] == "auto":
                helper.configure(self.cfg, {"mail": body["use"]})
            return {"connected": bool(mailer.status(self.cfg)["connected"]), "through": helper.settings(self.cfg)["mail"]}
        if op == "turn":       # which request the tools are working on, so they start each one without a window left over from the last
            turn = self.assistant.turn_for(sid)
            return {"turn": turn.id if turn else ""}
        if op == "do":
            with self.lock:
                grant = self.permits.pop(str(body.get("permit", "")), None)
            turn = self.assistant.turn_for(sid)
            if not grant or grant[0] != sid or grant[3] < time.time() or not turn or turn.stopping:
                raise ValueError("That was not approved, so it was not done.")
            return self.perform(grant[1], grant[2], turn)
        raise ValueError("Unknown request.")

    def show_main(self) -> str:
        """Bring JARVIS's app window to the front, or open it if it is closed. Returns "front" or "opened"."""
        import os
        import subprocess
        import sys
        from jcc import policy, winctl
        from jcc.config import ROOT
        for row in winctl.windows():
            if policy.MAIN_WINDOW.search(row["title"]):
                winctl.focus(row["handle"])
                return "front"
        from jcc import system
        subprocess.Popen([system.background_python(), "-m", "jcc.desktop"], cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT)},
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=system.no_window())
        return "opened"

    # ------------------------------------------------------------------ a planner and a builder (jcc/pairing.py)
    def pair_hands(self):
        """The three things a pair needs done for it: ask the planner, start the builder's job, say how that job is doing."""
        from jcc import pairing
        from jcc.vault import Vault
        state, cfg = self, self.cfg

        class Hands:
            plan = staticmethod(getattr(state, "pair_planner", None) or pairing.claude_planner(cfg))

            def build(self, pair, task, context):
                # The pair has a chat of its own in its project: the plan and every hand-over are there to be read, and the
                # builder's job is an ordinary coding job of that chat (its own copy of the project, checks, review).
                chats = Chats(cfg)
                cid = str(pair.get("chat") or "")
                try:
                    chats.get(cid) if cid else None
                except (ValueError, OSError, KeyError):
                    cid = ""
                if not cid:
                    cid = chats.create("Pair: " + str(pair["goal"])[:48], pair["project"])["id"]
                    pair["chat"] = cid
                chats.update(cid, archived=False, message={"role": "assistant", "content": "**From the planner**\n\n" + context, "status": "done",
                                                           "agent": "claude", "model": pair["planner"].get("answered_by") or pair["planner"].get("model") or ""})
                try:
                    chat = state.send_chat(cid, task, mode="code", manual_model=str(pair["builder"].get("asked") or "auto"), as_job=True, project=pair["project"])
                except ValueError as problem:
                    raise pairing.PairError(str(problem)[:300]) from None
                asked = [m for m in chat.get("messages") or [] if m.get("job") and m.get("receipt")]
                if not asked:
                    raise pairing.PairError("The builder's job could not be started.")
                return asked[-1]["receipt"]

            def told(self, rid, body):
                """A job's record, as the planner should hear it: what the job system itself established (the result,
                the checks, the files changed), then the builder's own last words. Not the agent's raw output."""
                facts = re.sub(r"\n{3,}", "\n\n", re.sub(r"^# Job[^\n]*\n", "", body.split("## Agent attempts", 1)[0])).strip()
                after = body.rsplit("```", 1)[-1].strip() if "## Agent output" in body else ""      # (what was added once it was reviewed or merged)
                try:
                    from jcc import live
                    said = str(live.read(cfg, rid).get("text") or "").strip()
                except Exception:  # noqa: BLE001 - a job whose live record cannot be read is still reported
                    said = ""
                if not said and "## Agent output" not in body:
                    said = body.strip()[-2500:]           # (no record of what it did step by step: the end of what there is)
                return "\n\n".join(part for part in (
                    facts[-3000:], after[:400],
                    "(JCC_PROGRESS.md and .jcc-acceptance-*.json are the job's own working notes. They are never merged into the project.)" if facts else "",
                    "What the builder said at the end:\n" + said[-3500:] if said else "") if part)

            def report(self, rid):
                text = Vault(cfg.vault).read(f"Jobs/{rid}.md")
                if not text:                              # no job was made of it: what the request itself came to
                    loaded = receipts.load(Vault(cfg.vault), rid)
                    fm, body = loaded if loaded else ({}, "")
                    status = str(fm.get("status") or "failed")
                    return {"status": "failed" if status in ("queued", "running") else status, "text": body[-3000:] or "No job was started for this hand-over."}
                fm, body = parse_frontmatter(text)
                status = str(fm.get("status") or "")
                if status == "needs_approval" and fm.get("blocked_by"):
                    # Not a change waiting for a review: something a coding job is never allowed to do by itself.
                    return {"status": "blocked", "text": "JARVIS does not let a coding job do this by itself, because it involves " + str(fm["blocked_by"]) +
                                                         ". The owner has to do that part, or the plan has to go another way."}
                from jcc import job_control
                asked = job_control.asked(cfg, rid) if status == "needs_approval" else None
                if asked is not None:
                    # The builder stopped and asked its owner for something. That is its owner's to answer: the pair
                    # waits, with the question in sight, and the same job carries on when it is answered.
                    return {"status": "needs_approval", "asked": True, "why": " ".join(asked["text"].split())[:300], "text": asked["text"], "ask": asked}
                if status == "cancelled" and fm.get("declined"):
                    return {"status": "cancelled", "text": "The builder stopped and asked its owner for something, and the owner said no: " + str(fm["declined"])[:600] +
                                                           "\nNothing was changed. Plan another way, or ask the owner what they would accept.\n" + self.told(rid, body)}
                if status == "paused":
                    # Paused by its owner, it is waited for. A job that stopped itself (it could not make the checks pass, or
                    # ran out of the time or tries it is allowed) will not go on by itself: the planner is told.
                    from jcc import job_control
                    if job_control.signal(cfg.jobs_root / rid) != "pause":
                        return {"status": "stalled", "text": "The job stopped itself without finishing; nothing was merged.\n" + self.told(rid, body)}
                return {"status": status, "why": str(fm.get("wait_reason") or fm.get("skipped") or ""), "text": self.told(rid, body)}
        return Hands()

    # ------------------------------------------------------------------ a security check's fix (jcc/security_check.py)
    def security_send(self, project, title, briefing, task):
        """Start the coding job that fixes the chosen findings: a chat of its own in the project, the briefing posted
        first, then the task as an ordinary coding request (its own copy of the project, checks, review)."""
        chats = Chats(self.cfg)
        cid = chats.create(title[:80], project)["id"]
        chats.update(cid, archived=False, message={"role": "assistant", "content": "**Security check**\n\n" + briefing, "status": "done"})
        from jcc import security_check
        security_check.hold(self.cfg, cid)             # (never merged unseen, even in a project that merges by itself)
        chat = self.send_chat(cid, task, mode="code")
        asked = [m for m in chat.get("messages") or [] if m.get("role") == "user" and m.get("receipt")]
        if not asked:
            raise ValueError("The fix could not be started.")
        return {"job": asked[-1]["receipt"], "chat": cid}

    # ------------------------------------------------------------------ a routine's run (jcc/routines.py)
    def routine_send(self, routine):
        """Start one run of a routine: its request sent in its own chat (made at its first run, and kept, so all its runs
        are in one place) exactly as if its owner had typed it there. The same path means the same approvals and limits."""
        chats = Chats(self.cfg)
        cid = str(routine.get("chat") or "")
        try:
            if cid:
                chats.get(cid)
        except (ValueError, OSError, KeyError):
            cid = ""                                     # (its chat was deleted or made private: a new one is made)
        if not cid:
            cid = chats.create("Routine: " + str(routine.get("name") or "")[:70], routine.get("project") or None)["id"]
        chat = self.send_chat(cid, str(routine.get("what") or ""), agent=str(routine.get("agent") or "auto"),
                              mode="code" if routine.get("mode") == "build" else "chat")
        asked = [m for m in chat.get("messages") or [] if m.get("role") == "user" and m.get("receipt")]
        if not asked:
            raise ValueError("The run could not be started.")
        return {"job": asked[-1]["receipt"], "chat": cid}

    def court_runner(self):
        return getattr(self, "court_asker", None)       # (None: the real one, Claude Code on this PC; tests put a stand-in here)

    def skill_job(self) -> dict:
        """What the last "add a pack" is doing: {} (nothing), or {"status": "working" | "done" | "failed", ...}."""
        return dict(getattr(self, "_skill_job", None) or {})

    def add_skills(self, source: str, name: str = "", deep: bool = False, again: str = "") -> dict:
        """Fetch and scan a pack in the background (a few minutes; a pack of hundreds of items takes about an hour, as it
        is scanned a part at a time). The window asks how it is going. again: scan a pack that is already kept once more."""
        from jcc import skills
        if (getattr(self, "_skill_job", None) or {}).get("status") == "working":
            raise ValueError("A pack is already being scanned. Wait for it to finish.")
        if again:
            source = skills.describe(self.cfg, again, full=False)["name"]
        if not source.strip():
            raise ValueError("Give a folder, a .zip file, or the https:// address of a repository.")
        job = self._skill_job = {"status": "working", "source": redact(source)[:200], "at": time.time(), "step": ""}

        def said(text):                               # how far the scan has come, in a few words
            job["step"] = redact(str(text))[:160]

        def work():
            try:
                pack = skills.rescan(self.cfg, again, deep, progress=said) if again else skills.add_pack(self.cfg, source, name, deep, progress=said)
                self._skill_job = {"status": "done", "pack": pack, "at": time.time()}
            except ValueError as problem:
                self._skill_job = {"status": "failed", "error": str(problem)[:300], "at": time.time()}
            except Exception as problem:  # noqa: BLE001 - whatever went wrong, the window is told and nothing was added
                self._skill_job = {"status": "failed", "error": "The pack could not be added: " + redact(str(problem))[:200], "at": time.time()}
        threading.Thread(target=work, daemon=True, name="skills-add").start()
        return self.skill_job()

    def perform(self, tool: str, args: dict, turn) -> dict:
        """Carry out one approved assistant action inside the app."""
        from jcc import mailer, memory, quick, reminders as clock
        cfg, helper = self.cfg, self.assistant
        if tool == "use_accounts":     # the owner's email, calendar and other online accounts, through a helper of their own (jcc/online.py)
            from jcc import online, usage as used
            from jcc.assistant import active_assistant
            began = time.time()
            whole = {"full": True} if args.get("full") is True and args.get("change") is not True else {}      # the whole of a message, when its owner asked to read it
            got = (getattr(self, "accounts_runner", None) or online.run)(cfg, str(args.get("request", "")), change=args.get("change") is True, name=active_assistant(cfg)["name"], **whole)
            spent = got.get("usage") or {}
            used.log_turn(cfg.state_dir, {"engine": "claude", "model": str(got.get("model") or "sonnet") + " (accounts)", "status": "done", "input": spent.get("input_tokens"),
                                          "cached": spent.get("cache_read_input_tokens"), "written": spent.get("cache_creation_input_tokens"), "output": spent.get("output_tokens"),
                                          "cost": got.get("cost"), "seconds": time.time() - began})
            return {"text": str(got.get("text") or "")}
        if tool in ("list_sites", "site_read", "site_change", "site_publish"):
            from jcc import sites
            try:
                if tool == "list_sites":
                    return {"sites": sites.listing(cfg)}
                if tool == "site_read":
                    return sites.read(cfg, str(args.get("site", "")), str(args.get("kind", "")), str(args.get("item") or ""))
                if tool == "site_change":
                    made = sites.stage(cfg, str(args.get("site", "")), str(args.get("kind", "")), str(args.get("summary", "")), str(args.get("item") or ""),
                                       args.get("title"), args.get("content"), args.get("price"), args.get("visible"))
                    helper.emit("site", change=sites.public(made))        # the window shows the preview, with Publish and Discard
                    return {"id": made["id"]}
                done = sites.publish(cfg, str(args.get("change", "")))
                helper.emit("site", change=done)
                return {"site_name": done.get("site_name"), "url": (done.get("result") or {}).get("url", "")}
            except sites.SiteError as problem:
                return {"error": str(problem)}
        if tool == "open_app":
            name = " ".join(str(args.get("name", "")).lower().split())
            if name in quick.BUILT_IN:
                helper.quick.act("run", quick.BUILT_IN[name])
                return {"opened": name}
            found = helper.apps.find(name)
            if found:
                helper.quick.act("app", found[1])
                return {"opened": found[0].title()}
            return {"opened": "", "near": quick.near(name, list(helper.apps.items))}     # nothing is called that: the names that are close
        if tool in ("list_projects", "create_project", "build_with_coding_agents"):
            workspace.refresh(cfg)
        if tool == "list_projects":
            return {"projects": [{"key": k, "name": p.name, "path": str(p.path)} for k, p in cfg.projects.items()]}
        if tool == "create_project":
            made = workspace.create(cfg, str(args.get("name", "")), str(args.get("kind") or "any"))
            workspace.refresh(cfg)
            return {"key": made["key"], "name": made.get("name", made["key"]), "path": str(cfg.projects[made["key"]].path)}
        if tool == "build_with_coding_agents":
            project, task = str(args.get("project", "")), str(args.get("task", "")).strip()
            if project not in cfg.projects:
                raise ValueError("That project does not exist. Use list_projects or create_project first.")
            if not task or len(task) > MAX_TEXT:
                raise ValueError("Describe the task.")
            # The job reports in the chat where it was asked for: one conversation for one request, however many jobs it takes.
            target = str(getattr(turn, "chat", "") or "")
            try:
                Chats(cfg).get(target) if target else None
            except (ValueError, OSError, KeyError):
                target = ""
            target = target or Chats(cfg).create(task[:70], project)["id"]
            last = self.send_chat(target, task, mode="code", effort="ultra" if args.get("ultra") is True else "auto", as_job=True, project=project)["messages"][-1]
            return {"message": f"The coding agents are working on it in the project {cfg.projects[project].name} "
                               f"({last.get('status')}). Its progress shows in this chat, and its changes go into the project by themselves once its checks pass.",
                    "chat": target}
        if tool == "make_image":
            from jcc import pictures
            ident = pictures.create(cfg, str(args.get("description", "")))
            turn.images.append(ident)
            return {"message": "The picture was made and is shown in the chat.", "id": ident}
        if tool == "set_timer":
            seconds = clock.parse_duration(str(args.get("duration", "")))
            if not seconds:
                raise ValueError("That length of time was not understood. Use something like '10 minutes'.")
            helper.reminders.add(str(args.get("label") or "Timer"), time.time() + seconds, "timer")
            return {"message": f"Timer set for {clock.spoken_span(seconds)}."}
        if tool == "set_reminder":
            when = str(args.get("when", "")).lower().strip()
            seconds = clock.parse_duration(when[3:] if when.startswith("in ") else when) if not re.search(r"\bat\b|\d\s*[ap]\.?m|\d:\d", when) else None
            due = time.time() + seconds if seconds else clock.parse_clock(when)
            if not due:
                raise ValueError("That time was not understood. Use something like 'in 2 hours' or 'tomorrow at 9 am'.")
            item = helper.reminders.add(str(args.get("text", "")), due, "reminder")
            return {"message": "Reminder set for " + time.strftime("%A %d %B at %I:%M %p", time.localtime(item["due"])) + "."}
        if tool == "list_reminders":
            rows = helper.reminders.listing()
            return {"message": "\n".join(f"{r['kind']}: {r['text']} — " + time.strftime("%a %d %b %I:%M %p", time.localtime(r["due"])) for r in rows)
                    or "There are no timers or reminders."}
        if tool == "cancel_reminder":
            count = helper.reminders.cancel(text=str(args.get("text", "")))
            return {"message": f"Cancelled {count}." if count else "Nothing matched, so nothing was cancelled."}
        if tool == "remember":
            return {"message": "Remembered: " + memory.remember(cfg, str(args.get("fact", "")))}
        if tool == "forget":
            count = memory.forget(cfg, str(args.get("words", "")))
            return {"message": f"Forgot {count} thing{'s' if count != 1 else ''}." if count else "Nothing remembered matched that."}
        if tool == "add_note":
            memory.add_note(cfg, str(args.get("text", "")))
            return {"message": "Noted in Quick notes."}
        if tool == "send_email":
            if not mailer.status(cfg)["connected"]:
                return {"sent": False}
            return {"sent": True, "message": mailer.send(cfg, str(args.get("to", "")), str(args.get("subject", "")), str(args.get("body", "")))}
        raise ValueError("Unknown request.")

    def screenshot(self, body: dict) -> dict:
        """List the open windows, or take a picture of one (or of the whole screen) and keep it as an attachment."""
        import os
        from jcc import winctl
        from jcc.image_inputs import store
        from jcc.policy import PRIVATE_WINDOW
        from jcc import system
        if system.kind() not in ("windows", "mac"):
            raise ValueError("Screenshots work on Windows and on a Mac.")
        rows = winctl.windows()
        mine = next((r["handle"] for r in rows if r["title"].startswith("JARVIS") and "Workspace" in r["title"]), 0)   # JARVIS's own window
        from jcc import screens
        found = screens.screens()
        if body.get("action") == "list":
            # With more than one screen the window offers each of them by name, instead of "the whole screen".
            names = [{"number": s["number"], "label": "The laptop screen" if s.get("builtin") else "The main screen" if s["main"] else f"Screen {s['number']}",
                      "detail": f"{s['width']} by {s['height']}"} for s in found] if len(found) > 1 else []
            return {"windows": [{"id": r["handle"], "title": r["title"][:90]} for r in rows
                                if r["handle"] != mine and not PRIVATE_WINDOW.search(r["title"])][:30], "screens": names}
        if body.get("action") != "take":
            raise ValueError("Unknown screenshot action.")
        if body.get("whole") is True:
            if PRIVATE_WINDOW.search(winctl.title_of(winctl.foreground()) if not mine or winctl.foreground() != mine else ""):
                raise ValueError("A private window (banking, payment or passwords) is in front, so no picture was taken.")
            shown = [r for r in rows if r["handle"] != mine]
            if shown and PRIVATE_WINDOW.search(shown[0]["title"]):
                raise ValueError("A private window (banking, payment or passwords) is in front, so no picture was taken.")
            number = body.get("screen") if isinstance(body.get("screen"), int) and not isinstance(body.get("screen"), bool) else 0
            chosen = next((s for s in found if s["number"] == number), None)
            if number and not chosen:
                raise ValueError("That screen is no longer connected.")
            if chosen:
                # The window on top of THAT screen must not be a private one either (it may not be the one in front).
                top = next((r for r in shown if (screens.of_window(r["handle"], found) or {}).get("number") == number), None)
                if top and PRIVATE_WINDOW.search(top["title"]):
                    raise ValueError("A private window (banking, payment or passwords) is showing on that screen, so no picture was taken.")
            width, height, picture = winctl.capture_screen(mine, number)
            label = f"screen {number}" if chosen else "screen"
        else:
            chosen = next((r for r in rows if r["handle"] == body.get("id")), None)
            if not chosen or PRIVATE_WINDOW.search(chosen["title"]):
                raise ValueError("That window is no longer open, or it is a private window.")
            width, height, picture = winctl.capture_window(chosen["handle"])
            label = re.sub(r"[^\w -]", "", chosen["title"])[:40].strip() or "window"
        return store(self.cfg, f"Screenshot of {label} {time.strftime('%H.%M.%S')}.png", picture)

    def add_preview(self, html: str, online: bool = False) -> dict:
        """Keep a page the assistant wrote so the Preview panel can show it in a sealed frame. online: its owner has
        allowed this one page to load from the internet."""
        if not isinstance(html, str) or not html.strip() or len(html) > 2_000_000:
            raise ValueError("There is nothing to preview, or it is larger than 2 MB.")
        ident = _rand.token_urlsafe(18)
        with self.lock:
            self.previews[ident] = (html, online is True)
            while len(self.previews) > 12:
                self.previews.popitem(last=False)
        return {"id": ident}

    def receipt(self, rid: str) -> dict[str, Any] | None:
        text = (self.cfg.vault / receipts.receipt_rel(rid))
        if not text.exists():
            return None
        fm, body = parse_frontmatter(text.read_text("utf-8"))
        answer = body.split("## Answer", 1)[1].split("\n## ", 1)[0].strip() \
            if "## Answer" in body else ""
        problem = body.split("## Problem", 1)[1].split("\n## ", 1)[0].strip() \
            if "## Problem" in body else ""
        return {**{k: fm.get(k) for k in receipts.FIELDS}, "reason": fm.get("reason", ""),
                "answer": answer, "error": problem,
                "obsidian": self.obsidian_link(receipts.receipt_rel(rid))}

    def update_action(self, body: dict) -> dict:
        """Check for an update, fetch it, choose how updates happen, or install now. Raises ValueError with a sentence."""
        from jcc import updates
        action = body.get("action")
        if action == "mode":
            return updates.set_mode(self.cfg, body.get("mode"))
        if action == "check":
            found = updates.check(self.cfg)
            if found.get("available") and found.get("signed") and not updates.ready(self.cfg):
                threading.Thread(target=lambda: _quietly(updates.download, self.cfg), name="update-download", daemon=True).start()
            return updates.status(self.cfg)
        if action == "install":
            running, _ = self.jobs()
            if any(job.get("status") in ("running", "queued") for job in running):
                raise ValueError("A coding job is running. Install the update when it has finished.")
            if not updates.ready(self.cfg):
                updates.download(self.cfg)                        # (a signed update that was not fetched yet)
            return updates.start_install(self.cfg, start="background")
        raise ValueError("Unknown update action.")

    def jobs(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        running, approvals = [], []
        d = self.cfg.vault / "Jobs"
        for f in sorted(d.glob("*.md"), reverse=True)[:60] if d.exists() else []:
            try:
                fm, _ = parse_frontmatter(f.read_text("utf-8"))
            except (OSError, ValueError):
                continue                      # a note that cannot be read right now is left out, not fatal
            item = {"id": fm.get("id", f.stem), "task": str(fm.get("task", ""))[:140],
                    "agent": fm.get("agent") or (fm.get("agents_planned") or [""])[0],
                    "project": fm.get("project", ""), "level": fm.get("level", ""),
                    "model": fm.get("model", ""),
                    "status": fm.get("status"), "blocked_by": fm.get("blocked_by", ""),
                    "chat": fm.get("chat_id") or "",
                    "obsidian": self.obsidian_link(f"Jobs/{f.name}")}
            if fm.get("status") in ("running", "queued", "paused", "failed"):
                running.append(item)
            elif fm.get("status") == "needs_approval":
                approvals.append(item)
        return running, approvals[:10]

    def _part(self, name: str, make, default):
        """One section of what the window shows.

        If it cannot be worked out right now (a file is half-written, damaged or locked), the last good value is shown
        again. One bad file can then never make the whole window lose its connection."""
        parts, failing = self.__dict__.setdefault("_parts", {}), self.__dict__.setdefault("_parts_failing", set())
        try:
            value = make()
        except Exception as problem:  # noqa: BLE001 - deliberately broad: see above
            if name not in failing:
                failing.add(name)
                self.add_log(f"Could not refresh {name} ({type(problem).__name__}); showing the last known value.")
            return parts.get(name, default)
        failing.discard(name)
        parts[name] = value
        return value

    def snapshot(self) -> dict[str, Any]:
        part = self._part
        part("the project list", lambda: workspace.refresh(self.cfg), None)
        running, approvals = part("jobs", self.jobs, ([], []))

        def spending():
            u = Usage(self.cfg.state_dir, self.cfg.caps)
            try:
                return u.summary(), u.cooldowns(), u.agent_runs_today()
            finally:
                u.close()
        usage, cooldowns, runs = part("usage", spending, ({}, {}, {}))
        agent_status = part("agents", lambda: {name: {**info, "runs_today": runs.get(name, 0)}
                                               for name, info in agents.agent_summary(self.cfg, cooldowns).items()}, {})
        recent = part("recent requests", lambda: [{k: r.get(k) for k in ("id", "time", "request", "tier", "status", "model", "router_method")}
                                                  for r in receipts.recent(receipts.Vault(self.cfg.vault), 12)], [])
        watcher_status = self.watcher
        if watcher_status == "off":  # is a separate `jcc watch` (or autostart) holding the lock?
            lock = watcher_lock(self.cfg.state_dir)
            if lock.acquire():
                lock.release()
            else:
                watcher_status = "external"
        if self.busy:
            core = "thinking"
        elif time.time() - self.last_error_at < 20:
            core = "error"
        elif running:
            core = "working"
        else:
            core = "idle"
        return {
            "core": core,
            "vault": {"name": self.cfg.vault.name, "ok": self.cfg.vault.exists()},
            "watcher": watcher_status,
            "keys": part("keys", lambda: {k: ("missing" not in v) for k, v in secrets.status().items()}, {}),
            "agents": agent_status,
            "chats": part("chats", lambda: Chats(self.cfg).list(), []),
            "routing": {"levels": self.cfg.levels,
                        "models": {k: a.models for k, a in self.cfg.agents.items()},
                        "choices": part("routing choices", lambda: routing.choices(self.cfg), {})},
            "models": part("the model list", lambda: models.catalog(self.cfg), []),
            "efficiency": {"settings": part("efficiency settings", lambda: efficiency.settings(self.cfg), dict(efficiency.DEFAULTS)),
                           "jobs": part("job figures", lambda: efficiency.summary(self.cfg), [])},
            "diagnostics": part("source health", lambda: diagnostics.snapshot(self.cfg), {}),
            "resources": {"power": part("power", governor.power, {"on_battery": None, "percent": None}),
                          "settings": part("resource settings", lambda: governor.settings(self.cfg), dict(governor.DEFAULTS))},
            "activity": part("activity", lambda: activity.recent(self.cfg), []),
            "alerts": part("alerts", lambda: activity.alerts(self.cfg), []),
            "learning": part("learning", lambda: learning.snapshot(self.cfg),
                             {"settings": dict(learning.DEFAULTS), "evidence": {"stats": [], "minimum_tasks": 5}, "feedback": {}}),
            "maintenance":{name:diagnostics.read(self.cfg,name) for name in ('memory-audit','restore-check')},
            "memory": {"path": str(self.cfg.vault), "imports": str(self.cfg.state_dir / "imports")},
            "history": {name: diagnostics.read(self.cfg, name)
                        for name in ("import", "capture", "github", "cloud-memory", "local-history")},
            "quotas": part("allowances", lambda: quota.snapshot(self.cfg),
                           {name: {"windows": [], "error": "Waiting for first reading."} for name in ("codex", "claude")}),
            "projects": [{"key": k, "name": p.name, "path": str(p.path),
                          "memory": self.obsidian_link(f"Projects/{k}/Memory")} for k, p in self.cfg.projects.items()],
            "usage": usage, "recent": recent, "jobs": running, "approvals": approvals,
            "log": list(self.log)[-12:],
            "inbox": self.obsidian_link("Inbox.md"),
            "dashboard": self.obsidian_link("Dashboard.md"),
        }


def make_handler(state: GuiState, port: int) -> type[BaseHTTPRequestHandler]:
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    state.assistant.port = port
    allowed_origins = {f"http://{h}" for h in allowed_hosts}

    class Handler(BaseHTTPRequestHandler):
        server_version = "jarvis-command"

        def log_message(self, fmt: str, *args: Any) -> None:  # keep the console quiet
            return

        # -------------------------------------------------------------- helpers
        def _headers(self, ctype: str, policy: str | None = None, frame: str = "DENY") -> None:
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", frame)
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("Permissions-Policy", "microphone=(self), camera=(), geolocation=(), display-capture=(), payment=(), usb=()")
            origin = self.headers.get("Origin", "")
            if urlparse(self.path).path in ("/api/capture", "/api/browser/share") and re.fullmatch(r"chrome-extension://[a-z]{32}", origin):
                self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Content-Security-Policy", policy or "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")

        def _send(self, code: int, body: bytes, ctype: str, policy: str | None = None, frame: str = "DENY") -> None:
            self.send_response(code)
            self._headers(ctype, policy, frame)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _stream(self, ctype: str, pieces) -> None:
            """Send sound as it arrives. The answer ends when the connection closes."""
            self.send_response(HTTPStatus.OK)
            self._headers(ctype)
            self.end_headers()
            self.close_connection = True
            try:
                for piece in pieces:
                    self.wfile.write(piece)
                    self.wfile.flush()
            except OSError:
                pass   # the window stopped listening (for example the user interrupted)
            finally:
                pieces.close()

        def _page(self) -> None:
            """The window itself. Scripts run only from this server's own files or with this page's one-time code."""
            from jcc import speech
            nonce = _rand.token_urlsafe(16)
            direct = self.headers.get("Sec-Fetch-Site", "none") in ("none", "same-origin")
            from jcc import placement
            kept = placement.prefs(state.cfg)
            if "nv-welcomed" not in kept and any((state.cfg.state_dir / name).exists() for name in ("assistant.json", "speech.json", "conversation-index.json")):
                kept["nv-welcomed"] = "1"           # someone who has used JARVIS before is not shown the first-run guide again
            page = STATIC.read_text("utf-8")
            if "mini" in parse_qs(urlparse(self.path).query, keep_blank_values=True):
                # The small listening window is known by its title (jcc/mini.py): it has it from the page's first bytes,
                # not only once the page's scripts have run, so it is dressed and off the taskbar at once.
                from jcc import mini
                page = page.replace("<title>JARVIS · Workspace</title>", "<title>" + mini.title_for(f"http://127.0.0.1:{self.server.server_address[1]}") + "</title>", 1)
            html = (page.replace("__JCC_TOKEN__", state.token).replace("__JCC_NONCE__", nonce)
                    .replace("__JCC_DIRECT__", "1" if direct else "0")
                    .replace("__JCC_PREFS__", json.dumps(kept).replace("<", "\\u003c").replace(">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")))
            socket_origin = speech.base().replace("https://", "wss://").replace("http://", "ws://")
            policy = ("default-src 'self'; script-src 'self' 'nonce-" + nonce + "'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
                      "media-src 'self' data: blob:; connect-src 'self' " + socket_origin + "; frame-src 'self'; worker-src 'self' blob:; "
                      "object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            self._send(HTTPStatus.OK, html.encode(), "text/html; charset=utf-8", policy)

        def _json(self, code: int, obj: Any) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json")

        def _host_ok(self) -> bool:
            if self.headers.get("Host", "") not in allowed_hosts:
                return False
            origin = self.headers.get("Origin")
            return origin is None or origin in allowed_origins

        def _token_ok(self) -> bool:
            given = self.headers.get("X-JCC-Token", "")
            return hmac.compare_digest(given.encode(), state.token.encode())

        def _guard(self) -> bool:
            if not self._host_ok():
                self._json(HTTPStatus.FORBIDDEN, {"error": "forbidden host"})
                return False
            return True

        def _same_user(self) -> bool:
            """Only programs of the Windows account that runs JARVIS may load the window (it carries the access token)."""
            from jcc import peer
            return peer.same_user(self.client_address[1], port) is not False

        # -------------------------------------------------------------- routes
        def send_response(self, code, message=None):
            self._answering = True                      # an answer has been started; nothing else may be sent after it
            super().send_response(code, message)

        def _safely(self, work) -> None:
            """Whatever goes wrong while answering, the window gets an answer it can show instead of a dropped connection."""
            self._answering = False
            try:
                work()
            except ConnectionError:
                self.close_connection = True            # the window went away mid-answer: nothing to do
            except Exception:  # noqa: BLE001 - deliberately broad: see above
                import traceback
                traceback.print_exc()                   # the details go to the service log
                state.last_error_at = time.time()
                self.close_connection = True
                if not self._answering:
                    try:
                        self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "JARVIS could not answer that just now. The details are in its log."})
                    except OSError:
                        pass

        def do_GET(self) -> None:  # noqa: N802
            self._safely(self._get)

        def do_POST(self) -> None:  # noqa: N802
            self._safely(self._post)

        def _get(self) -> None:
            if not self._guard():
                return
            url = urlparse(self.path)
            if url.path.startswith("/site-preview/"):
                # A website change, shown on this computer before anything is published (jcc/sites.py). Its link carries its key.
                from jcc import sites
                page = sites.preview_html(state.cfg, url.path.rsplit("/", 1)[-1], (parse_qs(url.query).get("k") or [""])[0])
                if page is None:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "No such preview."})
                    return
                self._send(HTTPStatus.OK, page.encode("utf-8"), "text/html; charset=utf-8", sites.PREVIEW_POLICY, frame="SAMEORIGIN")
                return
            if url.path in ("/", "/index.html"):
                if not self._same_user():
                    self._json(HTTPStatus.FORBIDDEN, {"error": "JARVIS belongs to another Windows account on this PC."})
                    return
                self._page()
                return
            if url.path.startswith("/preview/"):
                ident = url.path[9:]
                with state.lock:
                    kept = state.previews.get(ident)
                if kept is None:
                    self._send(HTTPStatus.NOT_FOUND, b"This preview has expired. Open it again from the chat.", "text/plain; charset=utf-8")
                elif self.headers.get("Sec-Fetch-Dest") == "document":      # a window of its own: the page goes in a frame there as well
                    sandbox = "allow-scripts allow-forms allow-modals" + (" allow-popups" if kept[1] else "")
                    self._send(HTTPStatus.OK, PREVIEW_WINDOW.replace("SANDBOX", sandbox).replace("IDENT", ident).encode("utf-8"), "text/html; charset=utf-8", WINDOW_POLICY)
                else:
                    page, online = kept
                    self._send(HTTPStatus.OK, (page if online else sealed_page(page)).encode("utf-8", errors="replace"), "text/html; charset=utf-8",
                               PREVIEW_ONLINE if online else PREVIEW_POLICY, "SAMEORIGIN")
                return
            if url.path in SCRIPTS:
                try:
                    content = (STATIC.parent / url.path.lstrip("/")).read_bytes()
                except OSError:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                    return
                self._send(HTTPStatus.OK, content, ("text/css" if url.path.endswith(".css") else "text/javascript") + "; charset=utf-8")
                return
            if not url.path.startswith("/api/"):
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            if not self._token_ok():
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "missing or bad token"})
                return
            if url.path == "/api/state":
                self._json(HTTPStatus.OK, state.snapshot())
            elif url.path == '/api/insights':
                self._json(HTTPStatus.OK,insights.dashboard(state.cfg))
            elif url.path == '/api/operations':
                self._json(HTTPStatus.OK,operations.health(state.cfg))
            elif url.path == '/api/timeline':
                try:self._json(HTTPStatus.OK,operations.timeline(state.cfg,(parse_qs(url.query).get('id') or [''])[0]))
                except (ValueError,OSError) as e:self._json(HTTPStatus.BAD_REQUEST,{'error':redact(str(e))[:200]})
            elif url.path == '/api/voice/events':
                args=parse_qs(url.query)
                try:self._json(HTTPStatus.OK,state.assistant.poll(int((args.get('since') or ['0'])[0]),float((args.get('wait') or ['0'])[0]),(args.get('w') or [''])[0][:40],(args.get('kind') or [''])[0][:8]))
                except ValueError as e:self._json(HTTPStatus.BAD_REQUEST,{'error':str(e)[:200]})
            elif url.path in ('/api/speech', '/api/speech/voices', '/api/mail', '/api/assistants', '/api/connections'):
                try:
                    from jcc import assistant as helper, mailer, speech
                    if url.path == '/api/connections':
                        from jcc import connections
                        found = connections.overview(state.cfg)
                        result = {'items': found, 'summary': connections.summary(found), 'groups': [list(group) for group in connections.GROUPS]}
                    elif url.path == '/api/speech':
                        from jcc import sound
                        result = {**speech.status(state.cfg, True), 'mail': mailer.status(state.cfg), 'mic_muted': sound.mic_muted(state.cfg)}
                        try:   # which of the tray helper's shortcuts are active (another app may already own one)
                            result['shortcuts'] = json.loads((state.cfg.state_dir / 'tray-status.json').read_text('utf-8'))
                        except (OSError, ValueError):
                            result['shortcuts'] = {}
                    elif url.path == '/api/speech/voices':
                        result = {'voices': speech.voices(state.cfg)}
                    elif url.path == '/api/mail':
                        result = mailer.status(state.cfg)
                    else:
                        result = helper.assistants(state.cfg)
                    self._json(HTTPStatus.OK, result)
                except (ValueError, OSError) as e:self._json(HTTPStatus.BAD_REQUEST,{'error':redact(str(e))[:300]})
            elif url.path == '/api/updates':                        # what the window shows about updates (jcc/updates.py)
                from jcc import updates
                self._json(HTTPStatus.OK, updates.status(state.cfg))
            elif url.path == '/api/voice/image':
                try:
                    from jcc import pictures
                    self._json(HTTPStatus.OK,pictures.load(state.cfg,(parse_qs(url.query).get('id') or [''])[0]))
                except (ValueError,OSError) as e:self._json(HTTPStatus.BAD_REQUEST,{'error':str(e)[:200]})
            elif url.path == '/api/computer':
                self._json(HTTPStatus.OK,state.computer.status((parse_qs(url.query).get('image') or ['1'])[0]=='1'))
            elif url.path == '/api/web/frame':
                try:
                    args=parse_qs(url.query)
                    self._json(HTTPStatus.OK,state.web.snapshot(int((args.get('since') or ['-1'])[0]),float((args.get('wait') or ['0'])[0])))
                except (ValueError,OSError) as e:self._json(HTTPStatus.BAD_REQUEST,{'error':redact(str(e))[:200]})
            elif url.path == '/api/pty':
                try:
                    args=parse_qs(url.query)
                    self._json(HTTPStatus.OK,state.ptys.get((args.get('id') or [''])[0]).read(int((args.get('since') or ['0'])[0]),float((args.get('wait') or ['0'])[0])))
                except (ValueError,OSError) as e:self._json(HTTPStatus.BAD_REQUEST,{'error':redact(str(e))[:200]})
            elif url.path == '/api/live':
                try:
                    from jcc import live
                    self._json(HTTPStatus.OK,live.read(state.cfg,(parse_qs(url.query).get('id') or [''])[0]))
                except (ValueError,OSError) as e:self._json(HTTPStatus.BAD_REQUEST,{'error':redact(str(e))[:200]})
            elif url.path == '/api/restorepoints/download':
                try:self._send(HTTPStatus.OK,restorepoints.portable(state.cfg,(parse_qs(url.query).get('id') or [''])[0]),'application/zip')
                except (ValueError,OSError) as e:self._json(HTTPStatus.BAD_REQUEST,{'error':redact(str(e))[:200]})
            elif url.path == '/api/controls':
                self._json(HTTPStatus.OK,{'resources':governor.settings(state.cfg),'budgets':budgets.settings(state.cfg),'prompt':prompt_preferences.settings(state.cfg),'restore_points':restorepoints.listing(state.cfg)})
            elif url.path == '/api/task-queue':
                self._json(HTTPStatus.OK,task_queue.snapshot(state.cfg))
            elif url.path == '/api/project/preferences':
                try:
                    workspace.refresh(state.cfg)
                    key=(parse_qs(url.query).get('project') or [''])[0]
                    self._json(HTTPStatus.OK,project_policy.snapshot(state.cfg,key))
                except (ValueError,KeyError) as e:self._json(HTTPStatus.BAD_REQUEST,{'error':str(e)[:200]})
            elif url.path == '/api/evaluations':
                self._json(HTTPStatus.OK,evaluations.status(state.cfg))
            elif url.path == '/api/handoff/download':
                try:
                    name=(parse_qs(url.query).get('name') or [''])[0]
                    self._send(HTTPStatus.OK,handoffs.download(state.cfg,name),'application/zip')
                except (ValueError,OSError) as e:self._json(HTTPStatus.BAD_REQUEST,{'error':str(e)[:200]})
            elif url.path == '/api/delivery/settings':
                self._json(HTTPStatus.OK,{'settings':delivery.settings(state.cfg),'rollbacks':routing_guard.snapshot(state.cfg)})
            elif url.path == '/api/work-history':
                try:
                    params=parse_qs(url.query)
                    self._json(HTTPStatus.OK,work_history.search(state.cfg,(params.get('q') or [''])[0],(params.get('project') or [None])[0]))
                except (ValueError,OSError) as e:self._json(HTTPStatus.BAD_REQUEST,{'error':redact(str(e))[:300]})
            elif url.path == '/api/memory/conflicts':
                self._json(HTTPStatus.OK,memory_conflicts.snapshot(state.cfg))
            elif url.path == "/api/receipt":
                rid = (parse_qs(url.query).get("id") or [""])[0]
                if not _ID.match(rid):
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "bad id"})
                    return
                data = state.receipt(rid)
                self._json(HTTPStatus.OK if data else HTTPStatus.NOT_FOUND,
                           data or {"error": "not found"})
            elif url.path == "/api/chat":
                try:
                    cid = (parse_qs(url.query).get("id") or [""])[0]
                    self._json(HTTPStatus.OK, Chats(state.cfg).get(cid))
                except ValueError as e:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
            elif url.path == "/api/sync/pairing":
                self._json(HTTPStatus.OK, {"code": state.sync_token})
            elif url.path == '/api/job/details':
                try:
                    rid=(parse_qs(url.query).get('id') or [''])[0]
                    self._json(HTTPStatus.OK,review.details(state.cfg,rid))
                except (ValueError,OSError,RuntimeError) as e:
                    self._json(HTTPStatus.BAD_REQUEST,{'error':redact(str(e))[:300]})
            elif url.path in ("/api/terminal", "/api/files", "/api/browser"):
                try:
                    args = parse_qs(url.query)
                    if url.path == "/api/terminal":
                        result = state.bench.terminal((args.get("id") or [""])[0]).snapshot()
                    elif url.path == "/api/files":
                        workspace.refresh(state.cfg)
                        result = state.bench.files((args.get("project") or [""])[0], (args.get("path") or [""])[0])
                    else:
                        result = state.bench.browser_page()
                    self._json(HTTPStatus.OK, result)
                except (ValueError, OSError) as e:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)[:200]})
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def _post(self) -> None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            route = urlparse(self.path).path
            cap = history.MAX_BYTES if route == "/api/import" else 26_000_000 if route in ("/api/web/upload", "/api/speech/transcribe") else 4_100_000 if route == "/api/speech/stt" else 2_100_000 if route == "/api/preview" else 4_100_000 if route == "/api/artifacts" else 4_000_000 if route in ("/api/capture", "/api/browser/share") else 2_000_000 if route == "/api/attachments/extract" else 2_000_000 if route == "/api/chat/send" else 700_000 if route == "/api/files/save" else 250_000 if route in ("/api/pty", "/api/web") else 2_000_000 if route == "/api/voice" else 900_000 if route == "/api/mods" else 20_000
            if length < 0 or length > cap:
                self.close_connection = True
                left = length if 0 < length <= 64_000_000 else 0   # take in a moderately oversized upload so the window gets a clear answer
                while left > 0:
                    piece = self.rfile.read(min(left, 262_144))
                    if not piece:
                        break
                    left -= len(piece)
                self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "That is too large to send."})
                return
            raw = self.rfile.read(length)  # always consume the body before answering
            if route in ("/api/capture", "/api/browser/share", "/api/sync/probe"):
                origin = self.headers.get("Origin", "")
                if (self.headers.get("Host") not in allowed_hosts or
                    (origin and not re.fullmatch(r"chrome-extension://[a-z]{32}", origin)) or
                    not hmac.compare_digest(self.headers.get("X-JCC-Sync", "").encode(), state.sync_token.encode())):
                    self._json(HTTPStatus.FORBIDDEN, {"error": "Browser connection not paired."})
                    return
                try:
                    data = json.loads(raw)
                    self._json(HTTPStatus.OK, history.capture(state.cfg, data) if route == "/api/capture" else diagnostics.probe(state.cfg, data) if route == "/api/sync/probe" else state.bench.share_page(data))
                except (ValueError, TypeError, AttributeError) as e:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)[:200]})
                return
            if route == "/api/tray":
                if (self.headers.get("Host") not in allowed_hosts or self.headers.get("Origin") or
                        not hmac.compare_digest(self.headers.get("X-JCC-Tray", "").encode(), state.tray_key.encode())):
                    self._json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
                    return
                try:
                    action = json.loads(raw or b"{}").get("action")
                except (ValueError, AttributeError):
                    action = None
                    said = ""
                else:
                    said = str(json.loads(raw).get("text", "")) if action == "say" else ""
                window = state.assistant.window_open()
                if action == "status":
                    self._json(HTTPStatus.OK, {"window": window, "voice": state.assistant.voice_busy(), "phase": state.assistant.voice_phase_now(),
                                               "waiting": state.assistant._waiting()})
                elif action == "say":
                    try:
                        self._json(HTTPStatus.OK, state.assistant.heard(said))
                    except ValueError as e:
                        self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)[:200]})
                elif action == "listen":
                    self._json(HTTPStatus.OK, {"window": state.assistant.hand()})
                elif action == "nudge":       # "Hey JARVIS" and then nothing: the session asks ("Yes?") and listens
                    self._json(HTTPStatus.OK, {"window": state.assistant.hand(nudge=True)})
                elif action == "attend":      # "Hey JARVIS" on its own: show that it is listening; the tray helper passes on what is said next
                    self._json(HTTPStatus.OK, {"window": state.assistant.hand("", attend=True)})
                elif action == "name":        # its name, heard while a spoken conversation is going on: the window holding it takes it from there
                    self._json(HTTPStatus.OK, state.assistant.name_said(json.loads(raw).get("text")))
                elif action == "control":     # "JARVIS, stop" and the like
                    try:
                        self._json(HTTPStatus.OK, state.assistant.control(str(json.loads(raw).get("text", ""))))
                    except ValueError as e:
                        self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)[:200]})
                else:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "unknown"})
                return
            if route == "/api/voice/tool":
                if (self.headers.get("Host") not in allowed_hosts or self.headers.get("Origin") or
                        not hmac.compare_digest(self.headers.get("X-JCC-Voice", "").encode(), state.assistant.key.encode())):
                    self._json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
                    return
                try:
                    self._json(HTTPStatus.OK, state.voice_tool(json.loads(raw or b"{}")))
                except (ValueError, OSError, RuntimeError, KeyError, TypeError) as e:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": redact(str(e))[:300]})
                return
            if not self._guard():
                return
            if not self._token_ok():
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "missing or bad token"})
                return
            if route == "/api/import":
                try:
                    name = (parse_qs(urlparse(self.path).query).get("name") or ["export.json"])[0]
                    self._json(HTTPStatus.OK, history.import_data(state.cfg, raw, name))
                except (ValueError, OSError) as e:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)[:300]})
                return
            if route == "/api/web/upload":
                try:
                    name = (parse_qs(urlparse(self.path).query).get("name") or ["file"])[0]
                    self._json(HTTPStatus.OK, state.web.upload(name, raw))
                except (ValueError, OSError) as e:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": redact(str(e))[:300]})
                return
            if route in ("/api/speech/stt", "/api/speech/transcribe"):
                try:
                    from jcc import speech
                    query = parse_qs(urlparse(self.path).query)
                    if route == "/api/speech/stt":
                        result = speech.hear(state.cfg, raw, (query.get("hint") or [""])[0][:200], names=not query.get("plain"))
                    else:
                        result = speech.transcribe(state.cfg, raw, (query.get("name") or ["recording.wav"])[0][:120])
                    self._json(HTTPStatus.OK, result)
                except (ValueError, OSError) as e:
                    busy = getattr(e, "busy", False)
                    self._json(HTTPStatus.TOO_MANY_REQUESTS if busy else HTTPStatus.BAD_REQUEST, {"error": redact(str(e))[:300], "busy": busy})
                return
            if route == "/api/open-imports":
                from jcc import system
                folder = state.cfg.state_dir / "imports"
                folder.mkdir(parents=True, exist_ok=True)
                system.open_path(folder)
                self._json(HTTPStatus.OK, {"opened": True})
                return
            if route == "/api/quota/refresh":
                state.refresh_quota()
                self._json(HTTPStatus.OK, {"refreshing": True})
                return
            if route == "/api/open-browser-sync":
                from jcc import system
                system.open_path(Path(__file__).resolve().parents[1] / "browser-sync")
                self._json(HTTPStatus.OK, {"opened": True})
                return
            if self.path not in ("/api/connectors", "/api/sites", "/api/uninstall", "/api/accounts", "/api/project/remove", "/api/reveal", "/api/updates", "/api/ask", "/api/mods", "/api/chats", "/api/chat/send", "/api/chat/update", "/api/projects", "/api/terminal", "/api/browser/open", "/api/routing", "/api/prompt-master", "/api/cloud", "/api/efficiency", "/api/job/control", '/api/assistant/settings','/api/feedback','/api/project/browse','/api/project/inspect','/api/project/connect','/api/job/review','/api/maintenance','/api/ui/activity','/api/context/inspect','/api/memory/resolve','/api/delivery/settings','/api/delivery/plan','/api/task-queue','/api/project/preferences','/api/dry-run','/api/evaluations','/api/handoff','/api/library','/api/provenance','/api/controls','/api/restorepoints','/api/diagnostics/export','/api/attachments/extract','/api/memory/search','/api/files/save','/api/pty','/api/web','/api/computer','/api/voice','/api/speech','/api/speech/tts','/api/mail','/api/assistants','/api/preview','/api/screenshot','/api/connections','/api/window','/api/providers','/api/usage','/api/skills','/api/pairs','/api/court','/api/agents','/api/artifacts','/api/security','/api/permissions','/api/routines'):
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "json only"})
                return
            try:
                body = json.loads(raw or b"{}")
                text = str(body.get("text", "")).strip()
                agent = body.get("agent")
                project = body.get("project")
            except (ValueError, AttributeError):
                self._json(HTTPStatus.BAD_REQUEST, {"error": "bad json"})
                return
            try:
                workspace.refresh(state.cfg)
                if self.path in ('/api/controls','/api/project/preferences','/api/delivery/settings','/api/routing','/api/efficiency','/api/assistant/settings'):
                    restorepoints.create(state.cfg,'Before '+self.path.rsplit('/',1)[-1]+' change')
                if self.path == '/api/speech/tts':
                    from jcc import speech
                    if body.get('local') is True:   # Windows' own voice, made here so the window can play it on the chosen speakers
                        made = speech.local_speech(state.cfg, str(body.get('text', '')))
                        self._stream('audio/L16;rate=' + str(speech.PCM_RATE), (piece for piece in (made,)));return
                    kind, pieces = speech.tts_stream(state.cfg, str(body.get('text', '')), str(body.get('voice') or '') or None, None, str(body.get('previous', '')))
                    self._stream('audio/mpeg' if kind == 'mp3' else 'audio/L16;rate=' + str(speech.PCM_RATE), pieces);return
                if self.path == '/api/updates':
                    self._json(HTTPStatus.OK, state.update_action(body));return
                if self.path == '/api/speech':
                    from jcc import mailer, speech
                    action = body.get('action')
                    if body.get('which') == 'composio' and action in ('key', 'forget'):      # the key for the owner's online accounts (jcc/online.py)
                        from jcc import online
                        online.connect(state.cfg, body.get('value')) if action == 'key' else online.disconnect(state.cfg)
                        result = speech.status(state.cfg)
                    elif action == 'key': result = speech.save_key(state.cfg, body.get('value'), str(body.get('which', 'elevenlabs')))
                    elif action == 'forget': result = speech.forget_key(state.cfg, str(body.get('which', 'elevenlabs')))
                    elif action == 'settings': speech.configure(state.cfg, body.get('settings')); result = speech.status(state.cfg)
                    elif action == 'token': result = {'token': speech.token(str(body.get('kind', '')))}
                    elif action == 'test': result = speech.self_test(state.cfg)
                    elif action == 'unmute':                 # its owner pressed Unmute: the microphone Windows had muted is unmuted
                        from jcc import sound
                        result = {'ok': sound.unmute_mic(state.cfg), 'mic_muted': sound.mic_muted(state.cfg)}
                    elif action == 'warm': threading.Thread(target=speech.warm, daemon=True, name='speech-warm').start(); result = {'ok': True}
                    else: raise ValueError('Unknown speech action.')
                    self._json(HTTPStatus.OK, result);return
                if self.path == '/api/window':               # the app window says where it is, so it can open there next time
                    from jcc import placement
                    if 'pref' in body:                       # ...and what its owner chose in it (theme, panel width)
                        self._json(HTTPStatus.OK, placement.set_pref(state.cfg, body.get('pref'), body.get('value')));return
                    if 'fullscreen' in body:                 # into or out of full screen, and that is how it opens next time
                        placement.set_pref(state.cfg, 'nv-open', 'fullscreen' if body.get('fullscreen') is True else 'remember')
                        self._json(HTTPStatus.OK, {'ok': True, 'done': placement.press_full_screen()});return
                    if body.get('mini') == 'drag':           # the small listening window was taken hold of: it follows the pointer until let go
                        popup = state.assistant.popup
                        self._json(HTTPStatus.OK, {'ok': True, 'moving': bool(popup and popup.drag())});return
                    if body.get('show') == 'main':           # asked from the small listening window: bring the app window forward, or open it
                        self._json(HTTPStatus.OK, {'ok': True, 'opened': state.show_main()});return
                    if 'problem' in body:                    # a script error in the window: kept in a short log, for looking into it
                        placement.note_problem(state.cfg, body.get('problem'))
                        self._json(HTTPStatus.OK, {'ok': True});return
                    if 'open' in body:                       # a link in a reply: opened in the owner's own browser, not in JARVIS's window
                        link = str(body.get('open') or '')
                        if not re.fullmatch(r"https?://[^\s<>\"']{1,2000}", link): raise ValueError('Invalid request.')
                        import webbrowser
                        webbrowser.open(link)
                        self._json(HTTPStatus.OK, {'ok': True});return
                    self._json(HTTPStatus.OK, placement.remember(state.cfg, body));return
                if self.path == '/api/connections':
                    from jcc import connections
                    if body.get('action') == 'accounts_user':      # whose accounts at Composio are used (the name they were connected under)
                        from jcc import online
                        self._json(HTTPStatus.OK, online.configure(state.cfg, body.get('user')));return
                    if body.get('action') == 'mac_settings':       # the page of System Settings where a permission is switched on
                        from jcc import macdesk, system
                        if system.kind() != 'mac': raise ValueError('That is on a Mac only.')
                        self._json(HTTPStatus.OK, {'opened': macdesk.open_settings(str(body.get('which', '')))});return
                    if body.get('action') != 'check': raise ValueError('Unknown request.')
                    self._json(HTTPStatus.OK, connections.check(state.cfg, str(body.get('id', ''))));return
                if self.path == '/api/mail':
                    from jcc import mailer
                    action = body.get('action')
                    if action == 'connect': result = mailer.connect(state.cfg, str(body.get('address', '')), str(body.get('password', '')), str(body.get('host', '')), body.get('port') or 0, str(body.get('name', '')))
                    elif action == 'disconnect': result = mailer.disconnect(state.cfg)
                    else: raise ValueError('Unknown email action.')
                    self._json(HTTPStatus.OK, result);return
                if self.path == '/api/assistants':
                    from jcc import assistant as helper
                    action = body.get('action')
                    if action == 'save': result = helper.save_assistant(state.cfg, body.get('assistant'))
                    elif action == 'remove': result = helper.remove_assistant(state.cfg, str(body.get('id', '')))
                    elif action == 'use': result = helper.choose_assistant(state.cfg, str(body.get('id', '')))
                    else: raise ValueError('Unknown assistant action.')
                    self._json(HTTPStatus.OK, result);return
                if self.path == '/api/preview':
                    self._json(HTTPStatus.OK, state.add_preview(body.get('html'), body.get('online') is True));return
                if self.path == '/api/screenshot':
                    self._json(HTTPStatus.OK, state.screenshot(body));return
                if self.path == '/api/voice':
                    from jcc import assistant
                    action=body.get('action')
                    if action=='say':
                        extra=state.bench.attachment_context(body.get('files') or [],bool(body.get('use_browser')),[u for u in (body.get('uploads') or []) if isinstance(u,dict) and not u.get('image_id')])
                        result=state.assistant.say(text,str(body.get('chat') or '') or None,body.get('spoken') is True,body.get('model'),extra,str(body.get('project') or '') or None,body.get('research') is True,body.get('heard') is True,how=str(body.get('research_model') or '')[:60],
                                                   noisy=body.get('noisy') is True,near=body.get('near') is True,interrupts=body.get('interrupts') if isinstance(body.get('interrupts'),list) else None)
                    elif action=='stop':result=state.assistant.stop(str(body.get('chat') or '') or None)
                    elif action=='hold':result=state.assistant.hold(str(body.get('chat') or '') or None,body.get('on') is True)     # its owner started to speak while it works: nothing new is begun meanwhile
                    elif action=='confirm':result=state.assistant.decide(str(body.get('id','')),body.get('approve') is True)
                    elif action=='settings':result=assistant.configure(state.cfg,body.get('settings'))
                    elif action=='presence':result=state.assistant.presence(str(body.get('phase','')),str(body.get('w','')),body.get('gone') is True,body.get('wake') is True,str(body.get('kind','')))
                    elif action=='pending':result=state.assistant.take_pending(str(body.get('kind','')))
                    elif action=='took':result=state.assistant.took(str(body.get('id','')))
                    elif action=='echo':result=state.assistant.echo(body.get('start'),body.get('levels'),body.get('before'))
                    elif action=='playing':result={'playing':state.assistant.sound.playing_now()}
                    elif action=='control':result=state.assistant.control(str(body.get('what','')),spoken=False)     # stop, sleep or end, asked from the small listening window (a button: nothing is said)
                    elif action=='unwait':result=state.assistant.unwait(str(body.get('id','')))          # do not carry on with a request that is waiting
                    elif action=='resume':result={'taken':state.assistant.resume_check(now=True)}        # try the waiting requests now
                    elif action=='compact':result=state.assistant.compact(str(body.get('chat','')))
                    else:raise ValueError('Unknown assistant action.')
                    self._json(HTTPStatus.OK,result);return
                if self.path == '/api/pairs':                 # a planner and a builder working on one goal (jcc/pairing.py)
                    from jcc import pairing
                    action, ident = body.get('action'), str(body.get('id', ''))
                    try:
                        if action == 'list':
                            from jcc.models import catalog
                            listed = catalog(state.cfg)
                            names = [{'id': m['id'], 'name': m['label'], 'provider': m['provider']} for m in listed]
                            result = {'pairs': pairing.listing(state.cfg), 'projects': [{'key': k, 'name': p.name} for k, p in state.cfg.projects.items()],
                                      'planners': [m for m in names if m['provider'] == 'claude'], 'builders': names,
                                      'usual': pairing.planner_model(state.cfg), 'rounds': pairing.ROUNDS}
                        elif action == 'get': result = pairing.get(state.cfg, ident)
                        elif action == 'open':
                            made = pairing.open_pair(state.cfg, str(body.get('project', '')), str(body.get('goal', '')), str(body.get('planner') or 'auto'),
                                                     str(body.get('builder') or 'auto'), str(body.get('effort') or 'auto'), chat=str(body.get('chat') or ''))
                            result = pairing.start(state.cfg, made['id'], state.pair_hands())
                        elif action == 'start': result = pairing.start(state.cfg, ident, state.pair_hands())
                        elif action == 'tell': result = pairing.tell(state.cfg, ident, str(body.get('text', '')))
                        elif action == 'stop': result = pairing.stop(state.cfg, ident)
                        else: raise ValueError('Unknown request.')
                    except pairing.PairError as problem:
                        raise ValueError(str(problem)) from None
                    self._json(HTTPStatus.OK, result);return
                if self.path == '/api/court':                 # the Court of JARVIS: one idea, put on trial (jcc/court.py)
                    from jcc import court
                    action, ident = body.get('action'), str(body.get('id', ''))
                    try:
                        if action == 'list':
                            result = {'sessions': court.listing(state.cfg), 'rules': court.rules(), 'models': court.models(state.cfg),
                                      'stages': [{'key': key, 'title': court.TITLES[key]} for key in court.STAGES],
                                      'analysts': [{'key': key, 'name': name} for key, name, _ in court.ANALYSTS], 'longest': court.LONGEST, 'shortest': court.SHORTEST}
                        elif action == 'get': result = court.get(state.cfg, ident)
                        elif action == 'open': result = court.open_session(state.cfg)
                        elif action == 'submit': result = court.submit(state.cfg, ident, str(body.get('idea', '')), runner=state.court_runner())
                        elif action == 'resume': result = court.resume(state.cfg, ident, runner=state.court_runner())
                        else: raise ValueError('Unknown request.')
                    except court.CourtError as problem:
                        raise ValueError(str(problem)) from None
                    self._json(HTTPStatus.OK, result);return
                if self.path == '/api/artifacts':             # everything that has been made, with its versions (jcc/artifacts.py)
                    from jcc import artifacts
                    action, ident = body.get('action'), str(body.get('id', ''))
                    try:
                        if action == 'list':
                            more = artifacts.sync(state.cfg)['more']
                            only = str(body.get('only') or '')
                            result = {'items': artifacts.listing(state.cfg, str(body.get('query') or '')[:200], str(body.get('kind') or ''), only if only in ('starred', 'yours') else ''),
                                      'more': more, 'kinds': artifacts.NAMES}
                        elif action == 'get': result = artifacts.get(state.cfg, ident)
                        elif action == 'version': result = artifacts.version(state.cfg, ident, body.get('n'))
                        elif action == 'find':
                            found = artifacts.find(state.cfg, str(body.get('chat') or ''), str(body.get('kind') or ''), str(body.get('name') or ''))
                            result = {'found': found, 'at': artifacts.locate(state.cfg, found['id'], body.get('code')) if found and isinstance(body.get('code'), str) else None}
                        elif action == 'save':
                            result = artifacts.save(state.cfg, ident, str(body.get('title') or ''), str(body.get('kind') or ''), str(body.get('lang') or ''),
                                                    body.get('code') if isinstance(body.get('code'), str) else '', str(body.get('note') or ''), body.get('amend') is True)
                        elif action == 'restore': result = artifacts.restore(state.cfg, ident, body.get('n'))
                        elif action == 'rename': result = artifacts.rename(state.cfg, ident, str(body.get('title') or ''))
                        elif action == 'star': result = artifacts.star(state.cfg, ident, body.get('on') is True)
                        elif action == 'remove': result = artifacts.remove(state.cfg, ident)
                        else: raise ValueError('Unknown request.')
                    except artifacts.ArtifactError as problem:
                        raise ValueError(str(problem)) from None
                    self._json(HTTPStatus.OK, result);return
                if self.path == '/api/security':              # find the usual holes in a project, and have them fixed in a copy (jcc/security_check.py)
                    from jcc import security_check as sec
                    action, ident = body.get('action'), str(body.get('id', ''))
                    if action == 'list':
                        result = {'projects': [{'key': k, 'name': p.name} for k, p in state.cfg.projects.items()], 'scans': sec.listing(state.cfg)}
                    elif action == 'scan': result = sec.scan(state.cfg, str(body.get('project', '')))
                    elif action == 'get': result = {**sec.get(state.cfg, ident), 'state': sec.fix_state(state.cfg, ident)}
                    elif action == 'fix': result = sec.start_fix(state.cfg, ident, body.get('findings'), state.security_send)
                    elif action == 'rescan': result = sec.rescan(state.cfg, ident, str(body.get('where', '')))
                    elif action in ('preview', 'apply', 'undo'):
                        job, now = sec.fix_job(state.cfg, ident), sec.fix_state(state.cfg, ident)['status']
                        if action == 'preview':
                            if now not in ('ready', 'applied'): raise ValueError('There are no changes to show yet.')
                            seen = review.details(state.cfg, job)
                            result = {'patch': str(seen.get('diff') or '')[:200_000], 'files': seen.get('files') or [], 'revision': str(seen.get('revision') or '')}
                        elif action == 'apply':
                            if now != 'ready': raise ValueError('There is no fix waiting to be applied.')
                            # What is applied is what was shown: the window says which state of the copy it showed, and a
                            # copy that has moved since is refused (review.approve), never applied unseen.
                            shown = str(body.get('revision') or '')
                            if not re.fullmatch(r'[0-9a-f]{7,64}', shown): raise ValueError('Look at the changes first, then apply them.')
                            result = review.approve(state.cfg, job, shown)
                        else:
                            if now != 'applied': raise ValueError('There is no applied fix to undo.')
                            result = review.undo(state.cfg, job)
                    else: raise ValueError('Unknown request.')
                    self._json(HTTPStatus.OK, result);return
                if self.path == '/api/accounts':              # signing in with your own Claude or ChatGPT account (jcc/accounts.py)
                    from jcc import accounts
                    action, ident = body.get('action'), str(body.get('id') or '')
                    if action == 'status': result = {'accounts': accounts.status(state.cfg, fresh=body.get('fresh') is True)}
                    elif action == 'sign_in': result = accounts.sign_in(state.cfg, ident)
                    elif action == 'sign_out': result = accounts.sign_out(state.cfg, ident)
                    else: raise ValueError('Unknown request.')
                    self._json(HTTPStatus.OK, result);return
                if self.path == '/api/project/remove':        # "Delete project": out of JARVIS; its folder only to the Recycle Bin, if asked
                    result = workspace.remove(state.cfg, str(body.get('project') or ''), trash=body.get('trash') is True)
                    self._json(HTTPStatus.OK, result);return
                if self.path == '/api/connectors':            # /connectors: extra tools for the assistant, added without editing a file
                    from jcc import connectors
                    action = body.get('action')
                    try:
                        if action == 'add':
                            got = {'added': connectors.add(state.cfg, str(body.get('text', '')), str(body.get('name', '')), str(body.get('token', '')))}
                        elif action == 'remove':
                            got = {'removed': connectors.remove(state.cfg, str(body.get('name', '')))}
                        elif action == 'test':
                            got = {'test': connectors.test(state.cfg, str(body.get('name', '')))}
                        elif action == 'claude':
                            got = {'claude': connectors.in_claude(state.cfg)}
                        elif action == 'import':
                            names = body.get('names') if isinstance(body.get('names'), list) else []
                            got = {'added': connectors.bring_in(state.cfg, str(body.get('source', '')), [str(n) for n in names][:50])}
                        else:
                            got = {}
                    except connectors.ConnectorError as problem:
                        raise ValueError(str(problem)) from None
                    self._json(HTTPStatus.OK, {**got, 'connectors': connectors.listing(state.cfg)});return
                if self.path == '/api/sites':                 # /sites: the owner's websites, and the changes waiting for them
                    from jcc import sites
                    action = body.get('action')
                    try:
                        if action == 'add':
                            got = {'site': sites.add(state.cfg, str(body.get('platform', '')), str(body.get('address', '')), str(body.get('key', '')),
                                                     str(body.get('user', '')), str(body.get('site_id', '')), str(body.get('name', '')))}
                        elif action == 'remove':
                            got = {'removed': sites.remove(state.cfg, str(body.get('id', '')))}
                        elif action == 'rekey':
                            got = {'site': sites.rekey(state.cfg, str(body.get('id', '')), str(body.get('key', '')))}
                        elif action == 'publish':
                            got = {'change': sites.publish(state.cfg, str(body.get('id', '')))}
                        elif action == 'discard':
                            got = {'change': sites.discard(state.cfg, str(body.get('id', '')))}
                        elif action == 'change':
                            got = {'change': sites.public(sites.change(state.cfg, str(body.get('id', ''))))}
                        else:
                            got = {}
                    except sites.SiteError as problem:
                        raise ValueError(str(problem)) from None
                    self._json(HTTPStatus.OK, {**got, 'sites': sites.listing(state.cfg), 'pending': sites.pending(state.cfg),
                                               'platforms': {k: {'label': v['label'], 'key': v['key'], 'how': v['how'], 'needs': list(v['needs']), 'kinds': list(v['kinds'])}
                                                             for k, v in sites.PLATFORMS.items()}});return
                if self.path == '/api/uninstall':             # Settings > Advanced > Uninstall JARVIS: what it would do, and doing it
                    from jcc import uninstall
                    if body.get('action') == 'start':
                        if self.headers.get('X-JCC-Sure') != 'uninstall': raise ValueError('Uninstalling needs to be confirmed in JARVIS\'s own window.')
                        self._json(HTTPStatus.OK, uninstall.start(state.cfg, bool(body.get('delete_data')), bool(body.get('delete_notes'))));return
                    self._json(HTTPStatus.OK, uninstall.plan(state.cfg));return
                if self.path == '/api/reveal':                # "Open file location": a project's folder, or a file in it, in Explorer / Finder
                    from jcc import firstrun
                    workspace.refresh(state.cfg)
                    project = state.cfg.projects.get(str(body.get('project') or ''))
                    if not project: raise ValueError('That project is not known.')
                    target = project.path
                    if body.get('file'):
                        wanted = (project.path / str(body['file'])).resolve()
                        if not wanted.is_relative_to(project.path.resolve()): raise ValueError('That file is not in the project.')
                        target = wanted if wanted.exists() else wanted.parent
                    if not target.exists(): raise ValueError('That folder is not there any more.')
                    firstrun.reveal(target)
                    self._json(HTTPStatus.OK, {'opened': True});return
                if self.path == '/api/permissions':           # how much JARVIS asks, and what waits for a yes or no (jcc/permissions.py)
                    from jcc import permissions
                    action = body.get('action')
                    if action == 'state':
                        with state.assistant.lock:
                            turns = list(state.assistant.turns.values())
                        result = permissions.state(state.cfg, state.assistant, turns)
                    elif action == 'mode': result = permissions.set_mode(state.cfg, body.get('mode'))
                    elif action == 'decide':
                        result = permissions.decide(state.cfg, state.assistant, body.get('kind'), body.get('id'), body.get('yes'), str(body.get('text') or '')[:20000],
                                                    body.get('mark'), body.get('revision'))
                        again = result.pop('rerun', None)
                        if again and again['task']:
                            # Go ahead: the same task, sent again as a job of the same chat (the guard lets it through once).
                            target = again['chat']
                            try:
                                Chats(state.cfg).get(target) if target else None
                            except (ValueError, OSError, KeyError):
                                target = ''
                            target = target or Chats(state.cfg).create(again['task'][:70], again['project'] or None)['id']
                            chat = state.send_chat(target, again['task'], mode='code', as_job=True, project=again['project'] or None)
                            result['chat'] = target
                            result['started'] = next((m['receipt'] for m in reversed(chat['messages']) if m.get('job')), '')
                    else: raise ValueError('Unknown request.')
                    self._json(HTTPStatus.OK, result);return
                if self.path == '/api/routines':              # what the owner wants done again and again (jcc/routines.py)
                    from jcc import routines
                    action, ident = body.get('action'), body.get('id')
                    said = ''
                    if action == 'list': pass
                    elif action == 'save': said = 'Saved.'; routines.save(state.cfg, body.get('routine'))
                    elif action == 'pause': said = 'Paused.'; routines.pause(state.cfg, ident)
                    elif action == 'resume': said = 'It runs again from its next time.'; routines.resume(state.cfg, ident)
                    elif action == 'remove': said = 'Removed.'; routines.remove(state.cfg, ident)
                    elif action == 'run': said = 'Started.'; routines.run_now(state.cfg, ident, state.routine_send)
                    elif action == 'retry': said = 'Started again.'; routines.retry(state.cfg, ident, state.routine_send)
                    elif action == 'cancel': said = routines.cancel(state.cfg, ident)['said']
                    else: raise ValueError('Unknown request.')
                    result = {'routines': routines.listing(state.cfg), 'said': said, 'now': time.time()}
                    if action == 'list':
                        result.update(projects=[{'key': k, 'name': p.name} for k, p in state.cfg.projects.items()],
                                      agents=[n for n, a in state.cfg.agents.items() if getattr(a, 'enabled', True)])
                    self._json(HTTPStatus.OK, result);return
                if self.path == '/api/agents':                # what every agent is doing, in one list (jcc/dashboard.py)
                    from jcc import dashboard
                    with state.assistant.lock:
                        turns = list(state.assistant.turns.values())
                    self._json(HTTPStatus.OK, dashboard.overview(state.cfg, turns, state.skill_job()));return
                if self.path == '/api/skills':                # the skills library: packs of playbooks for the coding agents (jcc/skills.py)
                    from jcc import skills
                    action, ident = body.get('action'), str(body.get('id', ''))
                    if action == 'list': result = {**skills.listing(state.cfg), 'adding': state.skill_job()}
                    elif action == 'pack': result = skills.describe(state.cfg, ident)
                    elif action == 'add': result = state.add_skills(str(body.get('source', '')), str(body.get('name', '')), body.get('deep') is True)
                    elif action == 'rescan': result = state.add_skills('', '', body.get('deep') is True, again=ident)
                    elif action == 'switch':
                        names = body.get('names')
                        result = skills.switch(state.cfg, ident, [str(n) for n in names] if isinstance(names, list) else None, body.get('on') is not False,
                                               body.get('flagged') is True, str(body.get('kind', '')))
                    elif action == 'remove': result = skills.remove(state.cfg, ident)
                    else: raise ValueError('Unknown request.')
                    self._json(HTTPStatus.OK, result);return
                if self.path == '/api/providers':             # other AI services: Grok, Gemini, Perplexity and the rest (jcc/providers.py)
                    from jcc import providers
                    action, ident = body.get('action'), str(body.get('id', ''))
                    if action == 'list': result = {'items': providers.listing(state.cfg, look=body.get('look') is True)}
                    elif action == 'connect': result = providers.connect(state.cfg, ident, str(body.get('key', '')), str(body.get('address', '')), str(body.get('name', '')))
                    elif action == 'disconnect': result = providers.disconnect(state.cfg, ident)
                    elif action == 'model': result = providers.choose_model(state.cfg, ident, str(body.get('model', '')))
                    elif action == 'models': result = {'models': providers.models(state.cfg, ident, refresh=body.get('refresh') is True)}
                    else: raise ValueError('Unknown request.')
                    self._json(HTTPStatus.OK, result);return
                if self.path == '/api/mods':                  # the owner's own commands, hooks, panels and status line (jcc/mods.py)
                    from jcc import assistant as helper, mods
                    action = body.get('action')
                    if action == 'list': result = mods.listing(state.cfg)
                    elif action == 'command': result = mods.save_command(state.cfg, body.get('name'), body.get('about'), body.get('text'))
                    elif action == 'uncommand': result = mods.delete_command(state.cfg, body.get('name'))
                    elif action == 'hook': result = mods.save_hook(state.cfg, body.get('when'), body.get('do'), body.get('text'), str(body.get('id') or ''))
                    elif action == 'hook_switch': result = mods.switch_hook(state.cfg, str(body.get('id') or ''), body.get('on') is True)
                    elif action == 'unhook': result = mods.delete_hook(state.cfg, str(body.get('id') or ''))
                    elif action == 'panel': result = mods.save_panel(state.cfg, body.get('name'), body.get('html'), body.get('online') is True)
                    elif action == 'panel_html':
                        ident = str(body.get('id') or '')
                        result = {'html': mods.panel_html(state.cfg, ident), 'name': next(p['name'] for p in mods.load(state.cfg)['panels'] if p['id'] == ident)}
                    elif action == 'unpanel': result = mods.delete_panel(state.cfg, str(body.get('id') or ''))
                    elif action == 'status': result = mods.set_status(state.cfg, body.get('on') is True, body.get('items'))
                    elif action == 'status_now':
                        chosen = helper.active_assistant(state.cfg)['model'] or helper.settings(state.cfg)['model']
                        result = mods.status_now(state.cfg, 'Auto' if chosen == 'auto' else helper.spec_name(state.cfg, state.assistant._first(chosen, '')))
                        if 'voice' in mods.load(state.cfg)['status']['items']:
                            from jcc import speech
                            try: result['voice'] = speech.usage(state.cfg)
                            except (ValueError, OSError): result['voice'] = None
                    else: raise ValueError('Unknown request.')
                    self._json(HTTPStatus.OK, result);return
                if self.path == '/api/usage':                 # what has been used: the assistant's own numbers, and each account's allowance
                    from jcc import quota, speech, usage as used
                    try: days = max(1, min(60, int(body.get('days') or 7)))
                    except (TypeError, ValueError): days = 7
                    store = used.Usage(state.cfg.state_dir, state.cfg.caps)
                    try: free = store.summary()
                    finally: store.close()
                    try: voice = speech.usage(state.cfg)
                    except (ValueError, OSError): voice = None
                    if body.get('refresh') is True: state.refresh_quota()      # read the accounts' allowances again (in the background; ask again in a moment)
                    self._json(HTTPStatus.OK, {'turns': used.turns(state.cfg.state_dir, days), 'accounts': quota.snapshot(state.cfg), 'free': free, 'voice': voice,
                                               'brain': state.assistant.brain_now(), 'reading': state.quota_lock.locked(), 'days': days});return
                if self.path == '/api/computer':
                    from jcc import computer
                    action=body.get('action')
                    if action=='settings':
                        if body.get('enabled') is False:state.computer.stop('Switched off.')
                        computer.configure(state.cfg,body.get('enabled'),str(body.get('mode','ask')));result=state.computer.status(False)
                    elif action=='start':result=state.computer.start(text)
                    elif action in ('approve','skip','stop'):result=state.computer.decide(action)
                    else:raise ValueError('Unknown computer action.')
                    self._json(HTTPStatus.OK,result);return
                if self.path == '/api/web':
                    action=body.get('action')
                    if action=='open':result=state.web.open(str(body.get('query','')))
                    elif action in ('back','forward'):result=state.web.history(-1 if action=='back' else 1)
                    elif action=='reload':result=state.web.reload()
                    elif action=='resize':result=state.web.resize(body.get('width'),body.get('height'),body.get('scale',1))
                    elif action=='input':result=state.web.inputs(body.get('events'))
                    elif action=='text':
                        # The page open in the owner's built-in browser joins their next message.
                        page=state.web.page_text(body.get('auto') is True)
                        result=page if page.get('skipped') else {**state.bench.share_page(page),'url':page['url']}
                    elif action=='login':result=state.web.login(str(body.get('decision','')))
                    elif action=='stop':state.web.stop();result={'stopped':True}
                    elif action=='tab_new':result=state.web.new_tab(str(body.get('query','')))
                    elif action=='tab_switch':result=state.web.switch_tab(str(body.get('id','')))
                    elif action=='tab_close':result=state.web.close_tab(str(body.get('id','')))
                    elif action=='upload_cancel':result=state.web.cancel_upload()
                    elif action=='fullscreen_exit':result=state.web.leave_fullscreen()
                    else:raise ValueError('Unknown browser action.')
                    self._json(HTTPStatus.OK,result);return
                if self.path == '/api/pty':
                    action=body.get('action')
                    if action=='start':result=state.ptys.start(body.get('project') or None,body.get('cols',100),body.get('rows',28))
                    elif action=='input':state.ptys.get(body.get('id','')).write(body.get('data',''));result={'ok':True}
                    elif action=='resize':state.ptys.get(body.get('id','')).resize(body.get('cols'),body.get('rows'));result={'ok':True}
                    elif action=='stop':result=state.ptys.stop(body.get('id',''))
                    else:raise ValueError('Unknown terminal action.')
                    self._json(HTTPStatus.OK,result);return
                if self.path == '/api/files/save':
                    self._json(HTTPStatus.OK,state.bench.save_file(str(body.get('project','')),str(body.get('path','')),body.get('text'),body.get('create') is True));return
                if self.path == '/api/attachments/extract':
                    self._json(HTTPStatus.OK,documents.extract(body.get('name',''),body.get('base64'),state.cfg));return
                if self.path == '/api/controls':
                    section=body.get('section')
                    function={'resources':governor.configure,'budgets':budgets.configure,'prompt':prompt_preferences.configure}.get(section)
                    if not function:raise ValueError('Unknown preference section.')
                    self._json(HTTPStatus.OK,function(state.cfg,body.get('settings')));return
                if self.path == '/api/restorepoints':
                    action=body.get('action');identity=str(body.get('id',''))
                    if action=='create':result=restorepoints.create(state.cfg,str(body.get('label','Manual restore point')))
                    elif action=='preview':result=restorepoints.preview(state.cfg,identity)
                    elif action=='restore':result=restorepoints.apply(state.cfg,identity,str(body.get('version','')))
                    else:raise ValueError('Choose create, preview or restore.')
                    self._json(HTTPStatus.OK,result);return
                if self.path == '/api/library':
                    action=body.get('action','query')
                    if action=='query':result=library.query(state.cfg,body.get('filters'))
                    elif action in ('delete','restore','deleted'):
                        from jcc.chats import Chats as ChatLibrary
                        chats = ChatLibrary(state.cfg)
                        if action == 'deleted':
                            rows = []
                            for cid in sorted(chats.deleted_ids(), reverse=True):
                                try:
                                    rows.append({'id': cid, 'title': chats.get(cid)['title']})
                                except ValueError:
                                    continue
                            result = {'chats': rows}
                        else:
                            result = chats.set_deleted(str(body.get('id', '')), action == 'delete')
                    elif action=='organize':result=library.organize(state.cfg,str(body.get('id','')),body.get('preferences'))
                    elif action=='branch':result=library.branch(state.cfg,str(body.get('id','')),body.get('index'),str(body.get('title','')))
                    elif action=='save_view':result=library.save_view(state.cfg,body.get('name',''),body.get('filters') or {})
                    else:raise ValueError('Unknown library action.')
                    self._json(HTTPStatus.OK,result);return
                if self.path == '/api/memory/search':
                    self._json(HTTPStatus.OK,retrieval.search(state.cfg,str(body.get('query','')),body.get('project'),body.get('include_cloud') is True));return
                if self.path == '/api/provenance':
                    result=provenance.versions(state.cfg,str(body.get('note',''))) if body.get('action')=='versions' else provenance.describe(state.cfg,str(body.get('note','')))
                    self._json(HTTPStatus.OK,result);return
                if self.path == '/api/diagnostics/export':
                    report=operations.health(state.cfg)
                    compact={'at':report['at'],'connections':{k:{'status':v.get('status'),'at':v.get('at')} for k,v in report['connections'].items()},'evaluation_status':report['evaluations']['status'],'resources':report['resources'],'counts':{'tasks':len(report['tasks']['tasks']),'restore_points':len(report['restore_points'])},'scope':'No transcripts, task text, credentials or raw logs.'}
                    self._json(HTTPStatus.OK,compact);return
                if self.path == '/api/project/preferences':
                    self._json(HTTPStatus.OK,project_policy.configure(state.cfg,str(body.get('project','')),body.get('preferences')));return
                if self.path == '/api/evaluations':
                    threading.Thread(target=evaluations.run,args=(state.cfg,),daemon=True,name='fixed-evaluations').start()
                    self._json(HTTPStatus.OK,{'status':'started'});return
                if self.path == '/api/handoff':
                    self._json(HTTPStatus.OK,handoffs.export(state.cfg,str(body.get('project',''))));return
                if self.path == '/api/dry-run':
                    cid=str(body.get('id',''));chat=Chats(state.cfg).get(cid) if cid else None
                    project=(chat or {}).get('project') or body.get('project') or None
                    supplied=state.bench.attachment_context(body.get('files') or [],bool(body.get('use_browser')),body.get('uploads') or [])
                    if cid:supplied+='\n\n<chat-history>\n'+Chats(state.cfg).context(cid)+'\n</chat-history>'
                    from jcc.image_inputs import selected as selected_images,validate as validate_images
                    images=selected_images(chat,text,body.get('uploads') or []);validate_images(state.cfg,images)
                    result=planning.preview(state.cfg,text,project,str(body.get('mode','auto')),str(body.get('model','auto')),str(body.get('effort','auto')),agent or 'auto',supplied)
                    result['images']={'count':len(images),'scope':'Owner-attached image context; text token estimates exclude image usage.'}
                    self._json(HTTPStatus.OK,result);return
                if self.path == '/api/delivery/settings':
                    self._json(HTTPStatus.OK,delivery.configure(state.cfg,body.get('settings')));return
                if self.path == '/api/delivery/plan':
                    if not text or len(text)>MAX_TEXT:raise ValueError('Write a draft of up to 2,000 characters.')
                    self._json(HTTPStatus.OK,{'items':delivery.criteria(text),'scope':'Checklist derived locally from your draft. Edit the draft to change the requirements. Coding jobs ask the agent for per-item evidence; uncertainty waits for review.'});return
                if self.path == '/api/task-queue':
                    self._json(HTTPStatus.OK,task_queue.update(state.cfg,str(body.get('id','')),body.get('priority'),body.get('dependencies'),body.get('deadline')));return
                if self.path == '/api/context/inspect':
                    cid=str(body.get('id',''));chat=Chats(state.cfg).get(cid) if cid else None
                    project=(chat or {}).get('project') or body.get('project') or None
                    if project and project not in state.cfg.projects:raise ValueError('Project not found.')
                    supplied=state.bench.attachment_context(body.get('files') or [],bool(body.get('use_browser')),body.get('uploads') or [])
                    if cid:supplied+='\n\n<chat-history>\n'+Chats(state.cfg).context(cid)+'\n</chat-history>'
                    if len(text)>MAX_TEXT:raise ValueError('Draft is too long.')
                    self._json(HTTPStatus.OK,context_inspector.inspect(state.cfg,project,text,supplied));return
                if self.path == '/api/memory/resolve':
                    self._json(HTTPStatus.OK,memory_conflicts.resolve(state.cfg,body.get('id'),body.get('source'),body.get('version')));return
                if self.path == '/api/ui/activity':
                    if body.get('focused') is True: atomic_write(state.cfg.state_dir/'ui-active',str(time.time()))
                    self._json(HTTPStatus.OK,{'ok':True});return
                if self.path == '/api/assistant/settings':
                    self._json(HTTPStatus.OK,{'settings':learning.configure(state.cfg,body.get('settings'))});return
                if self.path == '/api/feedback':
                    self._json(HTTPStatus.OK,learning.rate(state.cfg,str(body.get('id','')),body.get('rating')));return
                if self.path == '/api/project/browse':
                    self._json(HTTPStatus.OK, {'path': onboarding.choose_folder()})
                    return
                if self.path in ('/api/project/inspect','/api/project/connect'):
                    result=onboarding.inspect(state.cfg,str(body.get('path',''))) if self.path.endswith('inspect') else onboarding.connect(state.cfg,str(body.get('path','')),str(body.get('name','')))
                    self._json(HTTPStatus.OK,result);return
                if self.path == '/api/job/review':
                    result=review.undo(state.cfg,str(body.get('id',''))) if body.get('action')=='undo' else review.approve(state.cfg,str(body.get('id','')),str(body.get('revision',''))) if body.get('action')=='merge' else None
                    if result is None: raise ValueError('Choose merge or undo.')
                    self._json(HTTPStatus.OK,result);return
                if self.path == '/api/maintenance':
                    action=body.get('action')
                    if action not in ('audit','restore'): raise ValueError('Choose memory audit or backup recovery check.')
                    function=maintenance.memory_audit if action=='audit' else maintenance.restore_check
                    def run_maintenance():
                        try: function(state.cfg)
                        except Exception as e: atomic_write(state.cfg.state_dir/'maintenance-error.json',json.dumps({'error':redact(str(e))[:200]}))
                    threading.Thread(target=run_maintenance,daemon=True).start()
                    self._json(HTTPStatus.OK,{'status':'started'});return
                if self.path == "/api/efficiency":
                    self._json(HTTPStatus.OK, {"settings": efficiency.save(state.cfg, body.get("settings"))})
                    return
                if self.path == "/api/job/control":
                    if body.get("action") in ("answer", "decline"):       # its owner's yes or no to a job that stopped to ask
                        yes = body.get("action") == "answer"
                        if yes and not (isinstance(body.get("mark"), str) and body["mark"]):
                            raise ValueError("Read the job's question again before you answer.")      # (a yes says which question it answers)
                        self._json(HTTPStatus.OK, job_control.answer(state.cfg, str(body.get("id", "")), yes, str(body.get("text", "")),
                                                                     mark=body["mark"] if yes else None))
                        return
                    self._json(HTTPStatus.OK, job_control.apply(state.cfg, str(body.get("id", "")), body.get("action")))
                    return
                if self.path == "/api/routing":
                    self._json(HTTPStatus.OK, {"choices": routing.save(state.cfg, body.get("choices"))})
                    return
                if self.path == "/api/cloud":
                    if body.get("action") == "pairing":
                        self._json(HTTPStatus.OK, cloud_memory.pairing())
                    elif body.get("action") == "enable":
                        key = secrets.get("supabase-sync")
                        if not key:
                            raise ValueError("Copy the connection settings first.")
                        cloud_memory.configure(state.cfg, body.get("endpoint", ""), key)
                        self._json(HTTPStatus.OK, {"enabled": True})
                    else:
                        raise ValueError("Unknown cloud action.")
                    return
                if self.path == "/api/prompt-master":
                    self._json(HTTPStatus.OK, prompt_master.refine(state.cfg, text, project))
                    return
                if self.path == "/api/terminal":
                    action = body.get("action")
                    if action == "start":
                        result = state.bench.create_terminal(body.get("project"))
                    elif action == "run":
                        terminal = state.bench.terminal(str(body.get("id", "")))
                        terminal.run(str(body.get("command", "")))
                        result = terminal.snapshot()
                    elif action == "stop":
                        terminal = state.bench.terminal(str(body.get("id", "")))
                        terminal.stop()
                        result = terminal.snapshot()
                    else:
                        raise ValueError("Unknown terminal action.")
                    self._json(HTTPStatus.OK, result)
                    return
                if self.path == "/api/browser/open":
                    self._json(HTTPStatus.OK, state.bench.open_browser(str(body.get("query", ""))))
                    return
                if self.path == "/api/chats":
                    self._json(HTTPStatus.OK, Chats(state.cfg).create(str(body.get("title", "New chat")),
                               project if project and project != "none" else None))
                    return
                if self.path == "/api/chat/update":
                    self._json(HTTPStatus.OK, Chats(state.cfg).update(str(body.get("id", "")),
                               project=project, title=body.get("title"), archived=body.get("archived")))
                    return
                if self.path == "/api/projects":
                    self._json(HTTPStatus.OK, workspace.create(state.cfg, str(body.get("name", "")),
                               str(body.get("kind") or "any")))
                    return
            except (ValueError, OSError, RuntimeError) as e:
                self._json(HTTPStatus.BAD_REQUEST, {"error": redact(str(e))[:300]})
                return
            if not text or len(text) > MAX_TEXT:
                self._json(HTTPStatus.BAD_REQUEST, {"error": f"text must be 1-{MAX_TEXT} chars"})
                return
            if self.path == "/api/chat/send":
                try:
                    self._json(HTTPStatus.OK, state.send_chat(str(body.get("id", "")), text,
                               str(agent or "auto"), str(body.get("mode", "auto")),
                               str(body.get("model", "auto")), str(body.get("effort", "auto")),
                               body.get("files") or [], bool(body.get("use_browser")), body.get("uploads") or []))
                except (ValueError, OSError) as e:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": redact(str(e))[:300]})
                return
            self._json(HTTPStatus.OK, state.ask(text, agent if isinstance(agent, str) else None,
                                                project if isinstance(project, str) else None))

        def do_OPTIONS(self) -> None:  # noqa: N802 - never approve cross-site preflights
            origin = self.headers.get("Origin", "")
            if (urlparse(self.path).path in ("/api/capture", "/api/browser/share", "/api/sync/probe") and self.headers.get("Host") in allowed_hosts
                    and re.fullmatch(r"chrome-extension://[a-z]{32}", origin)):
                self.send_response(HTTPStatus.NO_CONTENT)
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Methods", "POST")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-JCC-Sync")
                self.end_headers()
                return
            self._json(HTTPStatus.FORBIDDEN, {"error": "cross-origin requests are not allowed"})

    return Handler


class Listener(ThreadingHTTPServer):
    """The app's own door, and nobody else's.

    The usual setting for a server ("reuse the address") means something else on Windows: any other program on this
    PC, of any Windows account, may open the very same address and port beside it, and is then handed some of the
    window's requests, access token included. Here the port is taken for this program alone, so a second listener
    (a second copy of JARVIS included) is refused by Windows itself."""
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def listener(port: int, handler, wait: float = 8.0, pause: float = 0.4) -> Listener:
    """The app's listener on this PC's own address. A port that is still held is tried again for a few seconds (the
    copy that is being replaced may not have let go of it yet); after that it is somebody else's, and that is said."""
    until = time.monotonic() + wait
    while True:
        try:
            return Listener(("127.0.0.1", port), handler)
        except OSError as problem:
            taken = getattr(problem, "winerror", None) in (10048, 10013) or problem.errno in (errno.EADDRINUSE, errno.EACCES)
            if not taken or time.monotonic() >= until:
                if taken:
                    raise OSError(problem.errno, f"Port {port} on this PC is held by another program, so JARVIS was not started here. "
                                                 "If JARVIS is already running, use that one.") from None
                raise
            time.sleep(pause)


def _quietly(work, *args) -> None:
    try:
        work(*args)
    except Exception:  # noqa: BLE001 - a background step; its own status file says what went wrong
        pass


def serve(port: int = 8765, open_browser: bool = True, watch: bool = True,
          cfg: config.Config | None = None) -> int:
    cfg = cfg or config.load()
    from jcc.initialize import ensure_notes
    ensure_notes(cfg)
    try:
        httpd = listener(port, None)                 # the port first: a second copy must not start anything else either
    except OSError as problem:
        print(str(problem.strerror or problem), flush=True)
        return 1
    state = GuiState(cfg)
    httpd.RequestHandlerClass = make_handler(state, port)
    desk = cfg.raw.get("desktop", {}) if isinstance(cfg.raw.get("desktop"), dict) else {}
    if os.name == "nt" and not os.environ.get("JCC_NO_SCREEN") and desk.get("listening_window", True) is not False:
        from jcc.mini import Mini
        state.assistant.popup = Mini(cfg, f"http://127.0.0.1:{port}")     # the small window that shows JARVIS is listening while another program is in use
    state.assistant.start()
    # Read the chat list once now, in the background, so the window's first request does not have to wait for it.
    threading.Thread(target=lambda: Chats(cfg).list(), daemon=True, name="chat-list-warm").start()
    for pattern in ("chat-*.lock", "send-*.lock"):   # left behind by earlier versions
        for stale in cfg.state_dir.glob(pattern):
            try:
                stale.unlink()
            except OSError:
                pass
    def usage_loop():
        while not state.stop.is_set():
            state.refresh_quota()
            state.web.idle_check()
            state.assistant.idle_check()
            try:
                from jcc import speech
                speech.local_voice.idle_check()
            except Exception:  # noqa: BLE001 - housekeeping only
                pass
            state.stop.wait(120)
    threading.Thread(target=usage_loop, name="usage-refresh", daemon=True).start()

    def routine_loop():
        # The owner's routines: each one that is due is sent as if typed (jcc/routines.py). Nothing that goes wrong with
        # one tick may end the loop, or no routine would ever run again until the app is started afresh.
        from jcc import routines
        while not state.stop.wait(20):
            try:
                routines.tick(state.cfg, state.routine_send)
            except Exception as problem:  # noqa: BLE001 - the next tick tries again
                state.add_log("Routines: " + str(problem)[:200])
    threading.Thread(target=routine_loop, name="routines", daemon=True).start()

    def update_loop():
        # Updates (jcc/updates.py): asks GitHub once a day which version is newest and, set to automatic, fetches a
        # signed one in the background. Installing happens when JARVIS next starts, or when the owner presses Install.
        from jcc import updates
        updates.background(state.cfg, state.stop)
    threading.Thread(target=update_loop, name="updates", daemon=True).start()
    threading.Thread(target=lambda: _quietly(review.tidy, state.cfg), name="tidy-reviews", daemon=True).start()
    # A sound left lowered by a crash while JARVIS was listening is put back.
    threading.Thread(target=lambda: _quietly(lambda: __import__("jcc.ducking", fromlist=["Ducker"]).Ducker(state.cfg.state_dir).recover()), name="sound-back", daemon=True).start()
    watcher_thread = None
    if watch:
        def _run() -> None:
            state.watcher = "running"
            ok = watcher.run(state.stop, 5.0, log=state.add_log, cfg=cfg)
            # False = another watcher already holds the lock; True = we were asked to stop
            state.watcher = "off" if ok else "external"

        watcher_thread = threading.Thread(target=_run, name="inbox-watcher", daemon=True)
        watcher_thread.start()
    url = f"http://127.0.0.1:{port}/"
    print(f"JARVIS control screen: {url}   (Ctrl+C to stop)", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        state.stop.set()
        state.ptys.stop_all()
        state.web.stop()
        state.computer.stop('JARVIS is closing.')
        state.assistant.close()
        httpd.server_close()
        if watcher_thread:
            watcher_thread.join(timeout=10)
    return 0
