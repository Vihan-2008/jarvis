"""Tier 3 launcher: guard, project detection, then a detached job runner (jcc.jobrunner).

Safety layers:
1. guard.tier3_block_reason(): deploy/servers/keys/push/delete/money/risk-limits -> needs approval.
2. Work happens under jobs_root: a plain job folder, or a git worktree branch copy of a project.
   The project's REAL checkout and other protected folders are denied to the agent.
3. Agents run in their normal headless permission mode with explicit allow/deny lists; bypass
   flags are refused (jcc.agents.build_argv).
4. The job environment has every key/token removed, so subscriptions are used, not API billing.
5. For projects, the system runs the checks and merges only if everything passes and no
   protected file (risk limits, deploy, docker, .env) changed. Nothing is ever pushed.
"""

from __future__ import annotations

import json
import time
import os
import subprocess
import sys
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jcc import agents, guard, receipts, workspace, models, efficiency
from jcc.lock import InstanceLock
from jcc.config import ROOT, Config, ProjectCfg
from jcc.redact import redact
from jcc.usage import Usage
from jcc.vault import Vault, parse_frontmatter, render_note

FORBIDDEN_FLAGS = agents.FORBIDDEN_FLAGS
_SECRET_ENV_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "JCC_",
                       "GROQ", "GEMINI_API", "XAI", "OPENAI_API", "ANTHROPIC_API")


# Settings that say where things are kept (and two switches used by tests and previews). They name places, not secrets.
PLACES = ("JCC_VAULT", "JCC_STATE_DIR", "JCC_JOBS_ROOT", "JCC_PROJECTS_ROOT", "JCC_NO_CREDMAN", "JCC_NO_SCREEN", "JCC_NO_LOCAL_CONFIG")


def scrub_env(env: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in env.items()
            if not any(m in k.upper() for m in _SECRET_ENV_MARKERS)
            and not (k.upper().startswith(("CODEX_", "CLAUDE_CODE_")) and k.upper() != "CODEX_HOME")
            and k.upper() != "CLAUDECODE"}


def is_inside(child: Path, parent: Path) -> bool:
    try:
        Path(os.path.abspath(child)).relative_to(Path(os.path.abspath(parent)))
        return True
    except ValueError:
        return False


def detect_project(cfg: Config, text: str) -> ProjectCfg | None:
    t = text.lower()
    for p in cfg.projects.values():
        if f"@{p.key}" in t or any(k in t for k in p.keywords):
            return p
    return None


Spawner = Callable[[list[str], Path, dict[str, str]], int]


def detached_spawn(argv: list[str], cwd: Path, env: dict[str, str]) -> int:
    flags = 0
    if sys.platform == "win32":
        flags = (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
                 | subprocess.CREATE_NO_WINDOW)
    # Off Windows the job gets a session of its own, so it outlives the app that started it and can be ended with
    # everything it started (jcc/system.py kill_tree).
    p = subprocess.Popen(argv, cwd=cwd, env=env, creationflags=flags,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True, start_new_session=sys.platform != "win32")
    return p.pid


@dataclass
class JobOutcome:
    status: str          # running | needs_approval | queued | failed
    message: str
    outputs: list[str]
    agent: str = ""


class JobLauncher:
    def __init__(self, cfg: Config, vault: Vault, spawner: Spawner | None = None) -> None:
        self.cfg, self.vault = cfg, vault
        self.spawner = spawner or detached_spawn

    def running_jobs(self) -> int:
        d = self.vault.root / "Jobs"
        n = 0
        for f in d.glob("*.md") if d.exists() else []:
            fm, _ = parse_frontmatter(f.read_text("utf-8"))
            n += fm.get("status") == "running"
        return n

    def write_job_note(self, rid: str, fm: dict[str, Any], body: str) -> str:
        rel = f"Jobs/{rid}.md"
        self.vault.write(rel, render_note(fm, body))
        return rel.removesuffix(".md")

    def launch(self, rid: str, kind: str, task: str, project: str | None = None,
               agent: str | None = None, chat_id: str | None = None, context: str = "",
               manual_model: str = "auto", effort: str = "auto",image_ids=None,doc_ids=None) -> JobOutcome:
        lock = InstanceLock(self.cfg.state_dir / "launch.lock")
        for _ in range(300):                      # another job is being scheduled at this moment: wait for it (up to a minute)
            if lock.acquire():
                break
            time.sleep(0.2)
        else:
            return JobOutcome("failed", "Another job is being scheduled. Please send again.", [])
        try:
            return self._launch(rid, kind, task, project, agent, chat_id, context, manual_model, effort,image_ids,doc_ids)
        finally:
            lock.release()

    def _launch(self, rid: str, kind: str, task: str, project: str | None,
                agent: str | None, chat_id: str | None, context: str, manual_model: str, effort: str,image_ids=None,doc_ids=None) -> JobOutcome:
        cfg = self.cfg
        from jcc.image_inputs import validate
        from jcc import doc_inputs
        image_ids=image_ids or []
        validate(cfg,image_ids)
        doc_ids=doc_ids or []
        doc_inputs.validate(cfg,doc_ids)
        supplied_context = context
        workspace.refresh(cfg)
        if project and project not in ("auto", "none") and project not in cfg.projects:
            return JobOutcome("failed", "Project not found.", [])
        proj = (cfg.projects.get(project) if project and project not in ("auto", "none")
                else None if project == "none" else detect_project(cfg, task))
        limits = efficiency.settings(cfg)
        from jcc.context_inspector import compose
        context = compose(cfg,proj.key if proj else None,task,context)
        reference_project = proj.key if proj else "none"
        if kind == "chat":
            proj = None
        selected = models.validate(cfg, manual_model, effort)
        if selected:
            agent = selected["provider"]
        block = guard.tier3_block_reason(task, [str(p) for p in cfg.protected])
        if kind == "chat" and block != "keys/secrets" and not str(block).startswith("protected folder") and re.match(r"^(what|why|how|explain|describe|tell me|summarize)\b", task, re.I):
            block = None  # an explanation is not an instruction to execute the described action
        if block and kind == "job":
            from jcc import permissions
            if permissions.may_go_ahead(cfg, chat_id or "", block):
                # Its owner said go ahead (or chose Bypass permissions). The agents are still told to leave those things alone.
                task, block = task + permissions.GO_AHEAD_NOTE, None
        u = Usage(cfg.state_dir, cfg.caps)
        try:
            # Ultracode (effort "ultra") is always planned as a large job: the strongest models, helpers for wide searches and
            # a second opinion on the result.
            p = agents.plan(cfg, task, u.cooldowns(), prefer=agent if agent != "auto" else None, level="large" if effort == "ultra" else None)
        finally:
            u.close()
        if effort == "auto" and manual_model == "auto":
            effort = cfg.raw.get("routing_choices", {}).get(p.level, {}).get("effort", "auto")
        base_fm = {"id": rid, "kind": kind, "task": task, "project": proj.name if proj else "",
                   "level": p.level, "agents_planned": p.agents, "project_key": reference_project,
                   "image_ids":image_ids,"doc_ids":doc_ids,"chat_id": chat_id or "", "context": redact(supplied_context[:18000]),
                   "manual_model": manual_model, "effort": effort, "reference_project": reference_project,
                   "preferred_agent": agent or "auto",
                   "receipt": f"[[{receipts.receipt_rel(rid).removesuffix('.md')}]]"}
        if kind=='job':
            from jcc.evaluations import status as evaluation_status
            evaluation=evaluation_status(cfg)
            if evaluation['status'] in ('failed','checking') or evaluation.get('current_build') is False:
                message='Fixed update evaluations reported a regression. Inspect App settings before starting more coding work.' if evaluation['status']=='failed' else 'Waiting for fixed evaluations of this application update to finish.'
                note=self.write_job_note(rid,{**base_fm,'status':'queued','wait_reason':message},'# Update validation wait\n\n'+message)
                return JobOutcome('queued',message,[note])
        from jcc.budgets import reason as budget_reason
        exceeded=budget_reason(cfg,reference_project)
        if exceeded and not block:
            note=self.write_job_note(rid,{**base_fm,'status':'queued','wait_reason':exceeded},'# Budget wait\n\n'+exceeded)
            return JobOutcome('queued',exceeded,[note])
        if block:
            note = self.write_job_note(
                rid, {**base_fm, "status": "needs_approval", "blocked_by": block},
                f"# Waiting for your go-ahead\n\nThis was not started because it mentions **{block}**.\n\n> {task}\n\n"
                "Answer it in the chat: Go ahead starts it (the agents still never do that part themselves), Cancel ends it.")
            return JobOutcome("needs_approval", f"Blocked: involves {block}.", [note])
        from jcc.task_queue import blocked
        dependency_reason=blocked(cfg,rid)
        if dependency_reason:
            note=self.write_job_note(rid,{**base_fm,'status':'queued','wait_reason':dependency_reason},'# Waiting\n\n'+dependency_reason)
            return JobOutcome('queued',dependency_reason,[note])
        if not p.agents:
            why = "; ".join(f"{k}: {v}" for k, v in p.skipped.items())
            note = self.write_job_note(rid, {**base_fm, "status": "queued", "skipped": why},
                                       f"# Queued\n\nNo coding agent is available right now "
                                       f"({why}).")
            return JobOutcome("queued", f"No agent available ({why}).", [note])
        same_project = False
        for f in (self.vault.root / "Jobs").glob("*.md"):
            fm, _ = parse_frontmatter(f.read_text("utf-8"))
            # Jobs on the same project take turns, so that their changes cannot collide. (Jobs of the same chat on
            # different projects, or with no project, run at the same time.)
            if f.stem != rid and fm.get("status") == "running" and proj and fm.get("project_key") == proj.key:
                same_project = True
        from jcc.governor import settings as resource_settings
        max_running=resource_settings(cfg)['max_parallel_jobs'] or cfg.tier3_max_running
        if self.running_jobs() >= max_running or same_project:
            note = self.write_job_note(rid, {**base_fm, "status": "queued"},
                                       "# Queued\n\nToo many jobs running; will start later.")
            return JobOutcome("queued", "Queued: too many tier 3 jobs running.", [note])

        workdir = cfg.jobs_root / rid
        for bad in [*cfg.all_protected(), self.vault.root]:
            if is_inside(workdir, bad):
                return JobOutcome("failed", f"Refusing: job folder would be inside {bad}", [])
        workdir.mkdir(parents=True, exist_ok=True)
        spec = {"id": rid, "kind": kind, "task": redact(task),
                "project": proj.key if proj else None, "prefer": agent,
                "level": p.level, "vault": str(self.vault.root), "chat_id": chat_id,
                "image_ids":image_ids,"doc_ids":doc_ids,"context": redact(context), "reference_project": reference_project,
                "manual_model": manual_model, "effort": effort,
                "timeout_minutes": limits["timeout_minutes"], "max_attempts": limits["max_attempts"]}
        from jcc.delivery import criteria
        spec.update({'delivery_version':1,'acceptance':criteria(task),'context_source':redact(supplied_context[:18000])})
        (workdir / "job.json").write_text(json.dumps(spec, indent=2), "utf-8")
        where = f"a branch copy of **{proj.name}**" if proj else f"`{workdir}`"
        note = self.write_job_note(
            rid, {**base_fm, "status": "running", "workdir": str(workdir)},
            f"# Job {rid}\n\nRunning in {where}. Level **{p.level}**, agents in order: "
            f"{', '.join(p.agents)}.\n\n> {task}")
        runner = [sys.executable, "-m", "jcc.jobrunner", str(workdir)]
        env = scrub_env(dict(os.environ))
        env["PYTHONPATH"] = str(ROOT)
        # The job's own process reads its settings afresh, and it has to mean the same places as the app that started
        # it: where the notes, the app's own files, the jobs and the projects are kept. Those are not secrets. Without
        # them, an app set up through these variables started jobs that looked in the usual places instead: such a job
        # did not know its project and ran without one. (The coding agent the job starts gets none of them: the job
        # scrubs its own environment again before starting it.)
        for name in PLACES:
            if name in os.environ:
                env[name] = os.environ[name]
        try:
            self.spawner(runner, workdir, env)
        except OSError as e:
            self.write_job_note(rid, {**base_fm, "status": "failed"}, "Could not start the coding process.")
            return JobOutcome("failed", f"Could not start job: {type(e).__name__}", [note])
        target = f" on {proj.name} (branch copy)" if proj else ""
        return JobOutcome("running", f"Started{target}: {p.level} task, trying "
                          f"{' → '.join(p.agents)}.", [note], p.agents[0])
