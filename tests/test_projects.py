"""End-to-end coding jobs on a temporary git project with a fake agent (no real AI usage)."""

import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

from jcc import agents, config, projects
from jcc.jobrunner import record, run_job
from jcc.usage import Usage
from tests.helpers import EngineTestCase

FAKE = str(Path(__file__).with_name("fake_agent.py"))


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout


def make_repo(root: Path) -> Path:
    repo = root / "proj"
    (repo / "src" / "pkg").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "src" / "pkg" / "__init__.py").write_text("VALUE = 1\n")
    (repo / "tests" / "__init__.py").write_text("")
    (repo / "tests" / "test_value.py").write_text(
        "import unittest\nimport pkg\n\nclass T(unittest.TestCase):\n"
        "    def test_value(self):\n        self.assertEqual(pkg.VALUE, 1)\n")
    git("init", "-q", "-b", "master", cwd=repo)
    git("-c", "user.name=t", "-c", "user.email=t@t", "add", "-A", cwd=repo)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init", cwd=repo)
    return repo


def overrides(repo: Path, levels=("codex", "claude"), auto_merge=True):
    agent = lambda n: {"enabled": True, "command": [sys.executable, FAKE, "--as", n],  # noqa: E731
                       "models": {"small": "", "medium": "", "large": ""}}
    return {
        "agents": {"claude": agent("claude"), "codex": agent("codex"),
                   "gemini": {"enabled": False, "command": "gemini", "models": {}}},
        "tier3": {"levels": {"small": list(levels), "medium": list(levels),
                             "large": list(levels)}},
        "projects": {"trading": {
            "name": "TestProject", "path": str(repo), "base_branch": "master",
            "python": sys.executable, "pythonpath": ["src", "."],
            "checks": [["-m", "unittest", "discover", "-s", "tests", "-t", "."]],
            "keywords": ["trading"], "auto_merge": auto_merge,
            "no_auto_merge": ["config/risk_limits.yaml", "deploy/"]}},
    }


class ProjectJobTest(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.repo = make_repo(self.tmp)
        self.modes = {}

    def tearDown(self):
        for k in list(os.environ):
            if k.startswith("FAKEAGENT_MODE_"):
                del os.environ[k]
        super().tearDown()

    def run_project_job(self, task="fix the stop-loss in the trading bot", modes=None,
                        auto_merge=True, levels=("codex", "claude")):
        for name, mode in (modes or {"codex": "edit"}).items():
            os.environ[f"FAKEAGENT_MODE_{name.upper()}"] = mode
        cfg = config.load(overrides(self.repo, levels, auto_merge))
        rid = time.strftime("%Y%m%d-%H%M%S-") + os.urandom(2).hex()
        workdir = cfg.jobs_root / rid
        workdir.mkdir(parents=True)
        spec = {"id": rid, "kind": "job", "task": task, "project": "trading", "prefer": None,
                "level": "medium", "vault": str(self.vault), "timeout_minutes": 2}
        res = run_job(cfg, spec, workdir)
        record(cfg, spec, workdir, res, 1.0)
        return cfg, rid, res

    def master_file(self):
        return git("show", "master:src/pkg/__init__.py", cwd=self.repo)

    def test_passing_change_is_merged_and_cleaned_up(self):
        cfg, rid, res = self.run_project_job()
        self.assertEqual(res.status, "done", res.merge_note)
        self.assertEqual(res.agent, "codex")
        self.assertIn("added_by_agent", self.master_file())
        self.assertTrue(res.merged)
        self.assertNotIn(projects.branch_name(rid), git("branch", cwd=self.repo))
        self.assertEqual(len(git("worktree", "list", cwd=self.repo).strip().splitlines()), 1)
        self.assertIn("Merge jcc/", git("log", "-1", "--pretty=%s", cwd=self.repo))
        note = (self.vault / f"Jobs/{rid}.md").read_text("utf-8")
        self.assertIn("merged into master", note)

    def test_failing_checks_are_never_merged(self):
        _, rid, res = self.run_project_job(modes={"codex": "fail_tests"})
        self.assertEqual(res.status, "failed")
        self.assertEqual(self.master_file(), "VALUE = 1\n")
        self.assertIn(projects.branch_name(rid), git("branch", cwd=self.repo))  # kept to inspect

    def test_risk_limit_changes_wait_for_approval(self):
        _, rid, res = self.run_project_job(modes={"codex": "risk"})
        self.assertEqual(res.status, "needs_approval")
        self.assertIn("config/risk_limits.yaml", res.blocked)
        self.assertNotIn("risk_limits", git("ls-tree", "-r", "--name-only", "master",
                                            cwd=self.repo))

    def test_usage_limit_switches_agent_and_sets_cooldown(self):
        cfg, rid, res = self.run_project_job(modes={"codex": "limit", "claude": "edit"})
        self.assertEqual(res.status, "done", res.merge_note)
        self.assertEqual([a["agent"] for a in res.attempts], ["codex", "claude"])
        self.assertTrue(res.attempts[0]["limit"])
        u = Usage(cfg.state_dir, cfg.caps)
        try:
            self.assertGreater(u.cooldowns()["codex"], time.time() + 3600)
            p = agents.plan(cfg, "fix a bug", u.cooldowns())
        finally:
            u.close()
        self.assertNotIn("codex", p.agents)
        self.assertIn("usage limit", p.skipped["codex"])

    def test_crashing_agent_falls_through_to_next(self):
        _, _, res = self.run_project_job(modes={"codex": "crash", "claude": "edit"})
        self.assertEqual((res.status, res.agent), ("done", "claude"))

    def test_all_agents_limited_means_queued_and_clean(self):
        _, rid, res = self.run_project_job(modes={"codex": "limit", "claude": "limit"})
        self.assertEqual(res.status, "queued")
        self.assertEqual(self.master_file(), "VALUE = 1\n")
        self.assertNotIn(projects.branch_name(rid), git("branch", cwd=self.repo))

    def test_dirty_checkout_is_not_merged_into(self):
        (self.repo / "src" / "pkg" / "__init__.py").write_text("VALUE = 1\n# my own edit\n")
        _, rid, res = self.run_project_job()
        self.assertEqual(res.status, "needs_approval")
        self.assertIn("uncommitted", res.merge_note)
        self.assertIn("# my own edit", (self.repo / "src/pkg/__init__.py").read_text())

    def test_agent_asking_for_approval(self):
        _, rid, res = self.run_project_job(modes={"codex": "approval"})
        self.assertEqual(res.status, "needs_approval")
        self.assertNotIn("NEEDS_APPROVAL.md", res.files)
        self.assertEqual(self.master_file(), "VALUE = 1\n")

    def test_auto_merge_off_waits(self):
        _, _, res = self.run_project_job(auto_merge=False)
        self.assertEqual(res.status, "needs_approval")
        self.assertEqual(self.master_file(), "VALUE = 1\n")

    def test_no_push_possible(self):
        with self.assertRaises(projects.GitError):
            projects.git(["push", "origin", "master"], self.repo)
        self.assertEqual(git("remote", cwd=self.repo).strip(), "")

    def test_agent_works_in_copy_not_real_checkout(self):
        cfg = config.load(overrides(self.repo))
        perms = agents.claude_permissions(cfg.jobs_root / "x" / "repo", cfg.all_protected(),
                                          cfg.projects["trading"].python,
                                          cfg.projects["trading"].checks)
        real = Path(os.path.abspath(self.repo)).as_posix()
        self.assertIn(f"Edit({real}/**)", perms["deny"])
        self.assertIn(f"Read({real}/**)", perms["deny"])
        self.assertTrue(any(a.startswith("Bash(") and "unittest" in a for a in perms["allow"]))
        self.assertIn("Bash(git push:*)", perms["deny"])
        self.assertNotIn("Bash", perms["deny"])  # project jobs may run their checks


class TestLauncherWithProjects(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.repo = make_repo(self.tmp)

    def test_trading_request_runs_as_project_job(self):
        e = self.make_engine(overrides(self.repo))
        r = e.process("fix the stop-loss in the trading bot")
        self.assertEqual((r.tier, r.status), (3, "running"))
        spec = json.loads((Path(self.spawned[-1][1]) / "job.json").read_text("utf-8"))
        self.assertEqual(spec["project"], "trading")
        self.assertEqual(r.model, "codex")

    def test_project_none_and_agent_preference(self):
        e = self.make_engine(overrides(self.repo))
        e.process("build a flashcard app", project="none", agent="claude")
        spec = json.loads((Path(self.spawned[-1][1]) / "job.json").read_text("utf-8"))
        self.assertIsNone(spec["project"])
        self.assertEqual(spec["prefer"], "claude")

    def test_queued_coding_job_retries_after_cooldown(self):
        e = self.make_engine(overrides(self.repo))
        for name in ("codex", "claude"):
            e.usage.set_cooldown(name, time.time() + 3600)
        r = e.process("fix the stop-loss in the trading bot")
        self.assertEqual(r.status, "queued")
        e.retry_queued()
        self.assertEqual(self.spawned, [])
        for name in ("codex", "claude"):
            e.usage.set_cooldown(name, 0)
        e.retry_queued()
        self.assertEqual(len(self.spawned), 1)
        spec = json.loads((Path(self.spawned[0][1]) / "job.json").read_text("utf-8"))
        self.assertEqual(spec["id"], r.id)
        self.assertEqual(spec["project"], "trading")
        e.retry_queued()
        self.assertEqual(len(self.spawned), 1)

    def test_forbidden_requests_still_blocked(self):
        e = self.make_engine(overrides(self.repo))
        for q in ["/job deploy the trading bot to the server", "/job git push the trading fix",
                  "/job change the risk limits in the trading bot",
                  "/job read the api keys for the trading bot",
                  "/job delete the trading database files"]:
            self.assertEqual(e.process(q).status, "needs_approval", q)
        self.assertEqual(self.spawned, [])


class TestAgentSelection(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(agents.classify_level("fix a typo in the readme"), "small")
        self.assertEqual(agents.classify_level("add a test for the parser"), "medium")
        self.assertEqual(agents.classify_level("redesign the risk engine architecture"), "large")

    def test_limit_detection(self):
        for msg in ["Claude AI usage limit reached|1794300000", "You've hit your usage limit.",
                    "Error 429: Too Many Requests", "Quota exceeded for quota metric"]:
            self.assertTrue(agents.is_limit_message(msg), msg)
        self.assertFalse(agents.is_limit_message("All 48 tests passed."))

    def test_argv_never_has_bypass_flags(self):
        for name in ("claude", "codex", "gemini"):
            a = config.AgentCfg(name, True, [name], {"small": "m", "medium": "", "large": ""})
            argv = agents.build_argv(a, "small", "do x", Path("C:/tmp/job"))
            for flag in agents.FORBIDDEN_FLAGS:
                self.assertNotIn(flag, " ".join(argv))
        bad = config.AgentCfg("codex", True, ["codex", "--yolo"], {})
        with self.assertRaises(ValueError):
            agents.build_argv(bad, "small", "x", Path("C:/tmp"))


if __name__ == "__main__":
    unittest.main()
