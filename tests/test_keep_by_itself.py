"""The permission mode decides what waits for its owner. When the project changed while a job worked, JARVIS combines the
two, checks them again and keeps the change by itself; when files clash, the same job carries on to combine them; in
Auto or Bypass a finished change whose checks pass is kept without anyone pressing Keep; Manual waits."""
import json
import os
from pathlib import Path

from jcc import assistant, config, job_control, review
from jcc.vault import Vault, parse_frontmatter
from tests.helpers import EngineTestCase
from tests import test_projects
from tests.test_projects import git, make_repo, overrides


class Case(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.repo = make_repo(self.tmp)

    def tearDown(self):
        for k in list(os.environ):
            if k.startswith("FAKEAGENT_MODE_"):
                del os.environ[k]
        super().tearDown()

    run_project_job = test_projects.ProjectJobTest.run_project_job
    master_file = test_projects.ProjectJobTest.master_file

    def waiting(self):
        cfg, rid, res = self.run_project_job(auto_merge=False)          # (a finished change, waiting to be kept)
        self.assertEqual(res.status, "needs_approval", res.merge_note)
        return cfg, rid

    def other_work(self, path="NOTES.md", text="other work\n"):
        """Another job's change, merged into the project meanwhile."""
        (self.repo / path).write_text(text, "utf-8")
        git("add", "-A", cwd=self.repo)
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "other work", cwd=self.repo)

    def status(self, cfg, rid):
        return parse_frontmatter(Vault(cfg.vault).read(f"Jobs/{rid}.md"))[0]["status"]


class TheProjectMovedOn(Case):
    def test_keep_combines_with_the_newer_project_checks_again_and_merges(self):
        cfg, rid = self.waiting()
        self.other_work()
        got = review.approve(cfg, rid, review.details(cfg, rid)["revision"])
        self.assertEqual(got["status"], "done", "no 'the base branch changed' for its owner to deal with")
        self.assertIn("added_by_agent", self.master_file(), "the job's change is in")
        self.assertEqual(git("show", "master:NOTES.md", cwd=self.repo), "other work\n", "and so is the other work")

    def test_when_files_clash_the_same_job_carries_on_to_combine_them(self):
        cfg, rid = self.waiting()
        self.other_work("src/pkg/__init__.py", "VALUE = 2  # changed by other work\n")
        got = review.approve(cfg, rid, review.details(cfg, rid)["revision"])
        self.assertEqual(got, {"status": "queued", "combining": True})
        self.assertEqual(self.status(cfg, rid), "queued")
        told = json.loads((cfg.jobs_root / rid / "owner-next.json").read_text("utf-8"))
        self.assertEqual(told["by"], "jarvis")
        self.assertIn("src/pkg/__init__.py", told["text"])
        self.assertIn("keeping both sets of changes", told["text"])


class TheModeDecides(Case):
    def keep_cfg(self, mode):
        cfg = config.load(overrides(self.repo, ("codex", "claude"), True))     # (the project merges by itself)
        assistant.configure(cfg, {"ask": mode})
        return cfg

    def test_auto_and_bypass_keep_a_passing_change_by_themselves(self):
        for mode in ("sending", "bypass"):
            _, rid = self.waiting()
            cfg = self.keep_cfg(mode)
            done = review.keep_by_itself(cfg)
            self.assertEqual(done, [{"job": rid, "did": "kept"}], mode)
            self.assertEqual(self.status(cfg, rid), "done")

    def test_manual_waits_for_its_owner(self):
        _, rid = self.waiting()
        cfg = self.keep_cfg("all")
        self.assertEqual(review.keep_by_itself(cfg), [])
        self.assertEqual(self.status(cfg, rid), "needs_approval")

    def test_a_project_set_to_always_review_waits_in_every_mode(self):
        _, rid = self.waiting()
        cfg = config.load(overrides(self.repo, ("codex", "claude"), False))
        assistant.configure(cfg, {"ask": "bypass"})
        self.assertEqual(review.keep_by_itself(cfg), [])

    def test_bypass_answers_a_jobs_question_yes(self):
        cfg, rid, res = self.run_project_job(modes={"codex": "approval"})
        self.assertTrue(res.asked)
        cfg = self.keep_cfg("bypass")
        self.assertEqual(review.keep_by_itself(cfg), [{"job": rid, "did": "answered yes"}])
        self.assertEqual(self.status(cfg, rid), "queued")
        self.assertEqual(job_control.signal(cfg.jobs_root / rid), "resume")
