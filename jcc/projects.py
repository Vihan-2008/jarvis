"""Branch-copy workflow for coding on a real project.

The agent never touches your real checkout. It works in a git worktree on its own branch
`jcc/<job id>`. Afterwards the system (not the agent) runs the project's checks, commits on that
branch, and merges into the base branch only if every gate passes. Nothing is ever pushed.
"""

from __future__ import annotations

import fnmatch
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from jcc.config import ProjectCfg
from jcc.redact import redact

GIT_ID = ["-c", "user.name=JARVIS Command", "-c", "user.email=jarvis-command@localhost",
          "-c", "commit.gpgsign=false"]


class GitError(RuntimeError):
    pass


def git(args: list[str], cwd: Path, check: bool = True, timeout: int = 120) -> str:
    if any(a in ("push", "remote", "fetch", "pull") for a in args[:2]):
        raise GitError("network git commands are not allowed")
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, stdin=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if check and p.returncode != 0:
        raise GitError(f"git {' '.join(args[:3])} failed: {(p.stderr or p.stdout).strip()[:300]}")
    return p.stdout


def branch_name(job_id: str) -> str:
    return f"jcc/{job_id}"


def create_worktree(project: ProjectCfg, wt: Path, job_id: str) -> None:
    wt.parent.mkdir(parents=True, exist_ok=True)
    git(["worktree", "add", "-b", branch_name(job_id), str(wt), project.base_branch], project.path)


def reset_worktree(wt: Path) -> None:
    """Throw away a failed attempt's edits (only inside the job's own branch copy)."""
    git(["reset", "--hard", "HEAD"], wt)
    git(["clean", "-fd"], wt)


def changed_files(wt: Path) -> list[str]:
    out = git(["status", "--porcelain", "--untracked-files=all"], wt)
    files = []
    for line in out.splitlines():
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        files.append(path.strip('"').replace("\\", "/"))
    return files


@dataclass
class CheckResult:
    name: str
    ok: bool
    tail: str


def check_env(project: ProjectCfg, wt: Path, base_env: dict[str, str]) -> dict[str, str]:
    env = dict(base_env)
    paths = [str(wt / p) for p in project.pythonpath]
    env["PYTHONPATH"] = os.pathsep.join(paths)  # the copy's code shadows the editable install
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run_checks(project: ProjectCfg, wt: Path, env: dict[str, str],
               timeout_s: int = 1800) -> list[CheckResult]:
    results = []
    deadline = time.monotonic() + timeout_s
    for chk in project.checks:
        name = " ".join(chk[1:3]) if chk[:1] == ["-m"] else " ".join(chk[:2])
        try:
            argv = chk if project.check_mode == "command" else [str(project.python), *chk]
            if env.get("JCC_CONTROL_FILE"):
                from jcc.jobrunner import run_process
                code, out = run_process(argv, wt, check_env(project, wt, env), max(1, int(deadline-time.monotonic())))
                results.append(CheckResult(name, code == 0, redact(out)[-1500:]))
                if code in (130, 131):
                    break
                continue
            p = subprocess.run(argv, cwd=wt, env=check_env(project, wt, env),
                               capture_output=True, text=True, encoding="utf-8", errors="replace",
                                 timeout=max(1, int(deadline-time.monotonic())), stdin=subprocess.DEVNULL,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            out = (p.stdout or "") + (p.stderr or "")
            results.append(CheckResult(name, p.returncode == 0, redact(out)[-1500:]))
        except (subprocess.TimeoutExpired, OSError) as e:
            results.append(CheckResult(name, False, f"{type(e).__name__}"))
    return results


def commit_all(wt: Path, message: str) -> str:
    git(["add", "-A"], wt)
    git([*GIT_ID, "commit", "-q", "-m", message], wt)
    return git(["rev-parse", "--short", "HEAD"], wt).strip()


def blocked_paths(files: list[str], patterns: list[str]) -> list[str]:
    hits = []
    for f in files:
        for pat in patterns:
            if f == pat or f.startswith(pat.rstrip("/") + "/") or pat in f or \
                    fnmatch.fnmatch(f, pat):
                hits.append(f)
                break
    return hits


def diff_stat(project: ProjectCfg, job_id: str) -> str:
    return git(["diff", "--stat", f"{project.base_branch}...{branch_name(job_id)}"],
               project.path, check=False)[-2000:]


def merge(project: ProjectCfg, job_id: str) -> tuple[bool, str]:
    """Merge the job branch into the base branch of the REAL checkout, only if that is safe."""
    repo = project.path
    current = git(["branch", "--show-current"], repo).strip()
    if current != project.base_branch:
        return False, f"your checkout is on '{current}', not '{project.base_branch}'"
    dirty = git(["status", "--porcelain", "--untracked-files=no"], repo).strip()
    if dirty:
        return False, "your checkout has uncommitted changes; merge it yourself when ready"
    branch = branch_name(job_id)
    if git(["merge-base", project.base_branch, branch], repo).strip() != git(["rev-parse", project.base_branch], repo).strip():
        return False, "the base branch changed while this job was running; review and re-test the combined changes"
    p = subprocess.run(["git", *GIT_ID, "merge", "--no-ff", "--no-edit",
                        "-m", f"Merge {branch_name(job_id)} (JARVIS job, all checks passed)",
                        branch_name(job_id)], cwd=repo, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    if p.returncode != 0:
        git(["merge", "--abort"], repo, check=False)
        return False, "merge conflict; left the branch for you to merge"
    return True, git(["rev-parse", "--short", "HEAD"], repo).strip()


def update_from_base(project: ProjectCfg, wt: Path) -> tuple[bool, list[str]]:
    """Bring the base branch's newer work (other jobs merged meanwhile) into this job's own copy: a merge in the job's
    branch, never in the real checkout. (True, []) when it went in cleanly. (False, files) when files clash: the merge is
    left in progress in the copy, the clashes marked in those files, for the job to resolve. (False, []) otherwise."""
    p = subprocess.run(["git", *GIT_ID, "merge", "--no-edit", "-m", f"Combine with the newer {project.base_branch}", project.base_branch],
                       cwd=wt, capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    if p.returncode == 0:
        return True, []
    clashing = git(["diff", "--name-only", "--diff-filter=U"], wt, check=False).split()
    if not clashing:
        git(["merge", "--abort"], wt, check=False)
    return False, clashing


def remove_worktree(project: ProjectCfg, wt: Path, job_id: str, delete_branch: bool) -> None:
    git(["worktree", "remove", "--force", str(wt)], project.path, check=False)
    if delete_branch:
        git(["branch", "-d", branch_name(job_id)], project.path, check=False)
