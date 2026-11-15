"""Problems JARVIS finds in itself are fixed by itself where that is safe (jcc/selfheal.py), and nothing loops."""
import json
import os
import time

from jcc import config, selfheal
from jcc.lock import InstanceLock
from jcc.vault import Vault, render_note
from tests.helpers import EngineTestCase
from tests.test_gui import GuiTestCase


class Helpers(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.load()
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        self.started = []

    def start(self, cfg, module, log_name):
        self.started.append(module)

    def test_a_helper_that_stopped_is_started_again_and_a_running_one_is_left_alone(self):
        (self.cfg.state_dir / "local-history.lock").write_text("")      # (it ran here once, and has stopped)
        running = InstanceLock(self.cfg.state_dir / "maintenance.lock")
        self.assertTrue(running.acquire())
        try:
            fixed = selfheal.run(self.cfg, start=self.start, carry_on=lambda *a: None)
        finally:
            running.release()
        self.assertEqual(self.started, ["jcc.local_history"], "not maintenance (running), nor what never ran on this computer")
        self.assertEqual(fixed[0]["done"], "Started it again.")
        self.assertEqual(selfheal.recent(self.cfg)["fixed"][0]["what"], "Saving your coding chats had stopped")

    def test_a_helper_that_keeps_stopping_is_left_stopped_and_reported(self):
        (self.cfg.state_dir / "local-history.lock").write_text("")
        now = time.time()
        for minute in range(5):
            selfheal.run(self.cfg, now=now + minute * 60, start=self.start, carry_on=lambda *a: None)
        self.assertEqual(self.started.count("jcc.local_history"), selfheal.RESTARTS_PER_HOUR, "three times in an hour, then no more")
        self.assertIn("jcc.local_history", selfheal.recent(self.cfg)["gave_up"])
        selfheal.run(self.cfg, now=now + 3700, start=self.start, carry_on=lambda *a: None)
        self.assertEqual(self.started.count("jcc.local_history"), selfheal.RESTARTS_PER_HOUR + 1, "an hour later it is tried again")


class FailedJobs(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.load()
        self.carried = []

    def job(self, rid, log, minutes_ago=5, status="failed"):
        Vault(self.cfg.vault).write(f"Jobs/{rid}.md", render_note({"id": rid, "status": status, "kind": "job", "task": "build the dashboard"}, "# Job"))
        path = self.cfg.vault / "Jobs" / f"{rid}.md"
        then = time.time() - minutes_ago * 60
        os.utime(path, (then, then))
        (self.cfg.jobs_root / rid).mkdir(parents=True, exist_ok=True)
        (self.cfg.jobs_root / rid / "output.log").write_text(log, "utf-8")

    def carry_on(self, cfg, rid, text=""):
        self.carried.append(rid)

    def test_a_job_that_failed_for_a_passing_reason_carries_on_once(self):
        self.job("20261115-120000-aaaa", "Error: request timed out after 600s")
        self.job("20261115-120001-bbbb", "AssertionError: the checks failed: 3 tests failed")
        self.job("20261115-120002-cccc", "429 Too Many Requests", minutes_ago=0.5)
        fixed = selfheal.run(self.cfg, start=lambda *a: None, carry_on=self.carry_on)
        self.assertEqual(self.carried, ["20261115-120000-aaaa"], "not a real failure, and not one that has only just failed")
        self.assertIn("timed out", fixed[0]["what"])
        selfheal.run(self.cfg, start=lambda *a: None, carry_on=self.carry_on)
        self.assertEqual(self.carried, ["20261115-120000-aaaa"], "once: a second failure waits for its owner's Continue")


class OverTheWire(GuiTestCase):
    def test_what_was_fixed_is_shown(self):
        status, got = self.req("GET", "/api/selfheal")
        self.assertEqual((status, got["fixed"]), (200, []))
        self.assertEqual(self.req("GET", "/api/selfheal", token=False)[0], 401)
