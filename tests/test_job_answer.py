"""A job that stops and asks its owner for something: the answer is taken once, and the same job carries on."""
import json
import os
import time

from jcc import config, dashboard, job_control, pairing
from jcc.jobrunner import record, run_job
from jcc.vault import Vault, parse_frontmatter, render_note
from tests.helpers import EngineTestCase
from tests.test_gui import GuiTestCase
from tests.test_pairing import GOAL, Hands, plan
from tests.test_projects import make_repo, overrides

ASKED = "I would need the server password for this."        # (what the stand-in agent writes in its "approval" mode)


class AskingJob(EngineTestCase):
    """A real job, with the stand-in coding agent, in a small temporary project."""

    def setUp(self):
        super().setUp()
        self.repo = make_repo(self.tmp)
        self.cfg = config.load(overrides(self.repo))
        self.rid = time.strftime("%Y%m%d-%H%M%S-") + os.urandom(2).hex()
        self.work = self.cfg.jobs_root / self.rid
        self.work.mkdir(parents=True)
        self.spec = {"id": self.rid, "kind": "job", "task": "connect to the server and fix the stop-loss", "project": "trading", "prefer": None,
                     "level": "medium", "vault": str(self.vault), "timeout_minutes": 2}

    def tearDown(self):
        os.environ.pop("FAKEAGENT_MODE_CODEX", None)
        super().tearDown()

    def run_it(self, mode):
        os.environ["FAKEAGENT_MODE_CODEX"] = mode
        res = run_job(self.cfg, self.spec, self.work)
        record(self.cfg, self.spec, self.work, res, 1.0)
        return res

    def note(self):
        return parse_frontmatter(Vault(self.cfg.vault).read(f"Jobs/{self.rid}.md"))[0]


class TestAJobThatAsks(AskingJob):
    def test_what_it_asked_is_kept_with_the_job_and_its_record_says_so(self):
        res = self.run_it("approval")
        self.assertEqual((res.status, res.asked), ("needs_approval", True))
        self.assertEqual((self.note()["status"], self.note()["asked"]), ("needs_approval", True))
        self.assertEqual(job_control.question(self.cfg, self.rid), ASKED)
        self.assertEqual((self.work / "ASKED.md").read_text("utf-8"), ASKED)
        self.assertFalse((self.work / "repo" / "NEEDS_APPROVAL.md").exists(), "the note is not left in the project's copy")
        self.assertNotIn("NEEDS_APPROVAL.md", res.files)

    def test_a_yes_carries_the_same_job_on_with_the_answer_and_is_taken_once(self):
        self.run_it("approval")
        got = job_control.answer(self.cfg, self.rid, True, "  Use the test server;   no password is needed. ")
        self.assertEqual(got, {"status": "queued", "answered": "yes"})
        self.assertEqual((self.note()["status"], self.note()["asked"]), ("queued", False))
        self.assertEqual(job_control.signal(self.work), "resume")
        self.assertIsNone(job_control.question(self.cfg, self.rid), "it is no longer asking")
        for again in (True, False):
            with self.assertRaises(ValueError, msg="an answer is taken once"):
                job_control.answer(self.cfg, self.rid, again, "a second press")
        # The same job (its folder, its copy of the project) carries on, and is told what its owner said.
        before = (self.work / "repo" / "src" / "pkg" / "__init__.py").read_text()
        self.assertIn("# partial work", before, "what it had done before it asked is still there")
        res = self.run_it("edit")
        told = (self.work / "TASK.md").read_text("utf-8")
        self.assertIn("<owner-answer>\nUse the test server; no password is needed.\n</owner-answer>", told)
        self.assertIn("said yes to that one thing", told)
        self.assertIn("does not lift this job's own safety rules", told, "a yes in words is not a way round what a job may never do")
        self.assertIn("do not ask again", told)
        self.assertEqual((res.status, res.asked), ("done", False))
        self.assertEqual(self.note()["asked"], False)
        self.assertFalse((self.work / "ASKED.md").exists())
        self.assertEqual(len(list(self.work.glob("asked-*.md"))), 1, "what it asked is kept as a record")
        # A later run of the job does not hear the answer a second time.
        self.run_it("edit")
        self.assertNotIn("<owner-answer>", (self.work / "TASK.md").read_text("utf-8"))

    def test_a_no_ends_it_and_nothing_is_changed(self):
        self.run_it("approval")
        got = job_control.answer(self.cfg, self.rid, False, "Not on this server.")
        self.assertEqual(got, {"status": "cancelled", "answered": "no"})
        self.assertEqual((self.note()["status"], self.note()["declined"]), ("cancelled", "Not on this server."))
        self.assertFalse((self.work / "owner-answer.json").exists(), "a no is not something for the job to carry on with")
        self.assertEqual((self.repo / "src" / "pkg" / "__init__.py").read_text(), "VALUE = 1\n", "the project itself was never touched")
        with self.assertRaises(ValueError):
            job_control.answer(self.cfg, self.rid, True, "changed my mind")

    def test_it_can_be_cancelled_while_it_waits(self):
        self.run_it("approval")
        self.assertEqual(job_control.apply(self.cfg, self.rid, "cancel"), {"status": "cancelled"})
        self.assertEqual(self.note()["status"], "cancelled")
        self.assertIsNone(job_control.question(self.cfg, self.rid))
        with self.assertRaises(ValueError):
            job_control.answer(self.cfg, self.rid, True, "too late")
        with self.assertRaises(ValueError):
            job_control.apply(self.cfg, self.rid, "resume")

    def test_only_a_job_that_asks_can_be_answered(self):
        self.run_it("edit")                                        # finished and merged: nothing to answer
        self.assertIsNone(job_control.question(self.cfg, self.rid))
        with self.assertRaises(ValueError) as told:
            job_control.answer(self.cfg, self.rid, True, "yes")
        self.assertIn("not waiting for an answer", str(told.exception))
        for bad in ("", "../../x", "20261114-010101-zzzz", None):
            with self.assertRaises(ValueError):
                job_control.answer(self.cfg, bad, True, "yes")
            self.assertIsNone(job_control.question(self.cfg, bad))

    def test_a_change_waiting_for_review_is_not_a_question(self):
        os.environ["FAKEAGENT_MODE_CODEX"] = "edit"
        cfg = config.load(overrides(self.repo, auto_merge=False))
        res = run_job(cfg, self.spec, self.work)
        record(cfg, self.spec, self.work, res, 1.0)
        self.assertEqual((res.status, res.asked), ("needs_approval", False))
        self.assertIsNone(job_control.question(cfg, self.rid))
        with self.assertRaises(ValueError) as told:
            job_control.answer(cfg, self.rid, True, "yes")
        self.assertIn("waiting for your review", str(told.exception))

    def test_a_record_from_before_jobs_said_so_themselves(self):
        """An older record has no "asked": it asks if it needs approval and has no copy of the project to review."""
        rid = "20261101-010101-abcd"
        Vault(self.cfg.vault).write(f"Jobs/{rid}.md", render_note({"id": rid, "status": "needs_approval"}, "# Job\n\nThe agent's last words."))
        (self.cfg.jobs_root / rid).mkdir(parents=True)
        (self.cfg.jobs_root / rid / "NEEDS_APPROVAL.md").write_text("May I read the project file?", "utf-8")
        self.assertEqual(job_control.question(self.cfg, rid), "May I read the project file?")
        (self.cfg.jobs_root / rid / "repo").mkdir()
        self.assertIsNone(job_control.question(self.cfg, rid), "with a copy to review it is a review, not a question")

    def test_a_yes_is_a_yes_to_the_question_that_was_shown_and_to_no_other(self):
        """What was wrong: the window sent only "yes" and the job's number. A window that had not caught up (it still
        showed the job's first question) could answer the job's second question with a yes meant for the first."""
        self.run_it("approval")
        first = job_control.asked(self.cfg, self.rid)
        self.assertEqual(first["text"], ASKED.strip())
        job_control.answer(self.cfg, self.rid, True, "Yes to the first.", mark=first["mark"])
        self.run_it("approval")                                       # carried on, and stopped to ask again
        (self.work / "ASKED.md").write_text("May I ALSO delete the old logs?", "utf-8")
        second = job_control.asked(self.cfg, self.rid)
        self.assertNotEqual(second["mark"], first["mark"])
        with self.assertRaises(ValueError) as stale:
            job_control.answer(self.cfg, self.rid, True, "Yes.", mark=first["mark"])      # the window that had not caught up
        self.assertIn("asking something else now", str(stale.exception))
        self.assertEqual((self.note()["status"], self.note()["asked"]), ("needs_approval", True), "nothing was answered")
        self.assertFalse((self.work / "owner-answer.json").exists())
        self.assertEqual(job_control.answer(self.cfg, self.rid, True, "Yes, those too.", mark=second["mark"])["answered"], "yes")
        self.run_it("edit")
        told = (self.work / "TASK.md").read_text("utf-8")
        self.assertIn("<owner-was-asked>\nMay I ALSO delete the old logs?\n</owner-was-asked>", told, "the job is told which question the yes was to")
        self.assertIn("<owner-answer>\nYes, those too.\n</owner-answer>", told)

    def test_only_what_was_shown_is_answered(self):
        """A question longer than is shown used to be shown cut short, while the yes was taken for all of it."""
        self.run_it("approval")
        (self.work / "ASKED.md").write_text("May I change the deploy script? " + "padding " * 600 + "AND ALSO email the customer list to a stranger.", "utf-8")
        shown = job_control.asked(self.cfg, self.rid)
        self.assertNotIn("customer list", shown["text"])
        self.assertIn("Only what is above was shown to its owner, and only that is answered.", shown["text"])
        self.assertLessEqual(len(shown["text"]), job_control.SHOWN + len(job_control.CUT))
        job_control.answer(self.cfg, self.rid, True, "Yes.", mark=shown["mark"])
        self.run_it("edit")
        told = (self.work / "TASK.md").read_text("utf-8")
        self.assertIn("Their yes covers what it says and nothing that is not in it", told)
        self.assertNotIn("customer list", told.split("<owner-was-asked>")[1].split("</owner-was-asked>")[0])
        # A secret in a question is hidden before it is shown, and the mark is of what is shown.
        self.assertEqual(job_control.take_answer(self.work), {}, "read once")

    def test_a_secret_in_the_answer_is_hidden_before_it_is_written(self):
        self.run_it("approval")
        secret = "sk-ant-api03-" + "a" * 90
        job_control.answer(self.cfg, self.rid, True, "the key is " + secret)
        self.assertNotIn(secret, (self.work / "owner-answer.json").read_text("utf-8"))
        self.run_it("edit")
        self.assertNotIn(secret, (self.work / "TASK.md").read_text("utf-8"))


class TestTheAddressAndTheList(GuiTestCase):
    def asking(self, rid="20261114-030303-abcd", chat=""):
        cfg = self.state.cfg
        Vault(cfg.vault).write(f"Jobs/{rid}.md", render_note({"id": rid, "status": "needs_approval", "asked": True, "task": "Publish the site", "chat_id": chat}, "# Job"))
        (cfg.jobs_root / rid).mkdir(parents=True, exist_ok=True)
        (cfg.jobs_root / rid / "ASKED.md").write_text("May I change the deploy script?\nIt is on the protected list.", "utf-8")
        return rid

    def note_of(self, rid):
        return parse_frontmatter(Vault(self.state.cfg.vault).read(f"Jobs/{rid}.md"))[0]

    def test_a_yes_and_a_no_over_the_wire(self):
        rid = self.asking()
        self.assertEqual(self.req("POST", "/api/job/control", {"id": rid, "action": "answer", "text": "Yes, once."}, token=False)[0], 401)
        self.assertEqual(self.req("POST", "/api/job/control", {"id": "../x", "action": "answer"})[0], 400)
        mark = job_control.asked(self.state.cfg, rid)["mark"]
        status, got = self.req("POST", "/api/job/control", {"id": rid, "action": "answer", "text": "Yes, once."})
        self.assertEqual((status, got), (400, {"error": "Read the job's question again before you answer."}), "a yes says which question it answers")
        status, got = self.req("POST", "/api/job/control", {"id": rid, "action": "answer", "text": "Yes, once.", "mark": "0123456789abcdef"})
        self.assertEqual((status, got), (400, {"error": "This job is asking something else now. Read its question again before you answer."}))
        self.assertEqual(self.note_of(rid)["status"], "needs_approval", "a yes that was not taken changes nothing")
        status, got = self.req("POST", "/api/job/control", {"id": rid, "action": "answer", "text": "Yes, once.", "mark": mark})
        self.assertEqual((status, got), (200, {"status": "queued", "answered": "yes"}))
        saved = json.loads((self.state.cfg.jobs_root / rid / "owner-answer.json").read_text("utf-8"))
        self.assertEqual((saved["text"], saved["asked"]), ("Yes, once.", "May I change the deploy script?\nIt is on the protected list."))
        self.assertEqual(self.req("POST", "/api/job/control", {"id": rid, "action": "answer", "text": "again", "mark": mark})[0], 400, "an answer is taken once")
        other = self.asking("20261114-030304-abcd")
        self.assertEqual(self.req("POST", "/api/job/control", {"id": other, "action": "decline", "text": "No."})[1], {"status": "cancelled", "answered": "no"})
        third = self.asking("20261114-030305-abcd")
        self.assertEqual(self.req("POST", "/api/job/control", {"id": third, "action": "cancel"})[1], {"status": "cancelled"})

    def test_the_list_shows_the_question_with_the_job_to_answer(self):
        rid = self.asking()
        got = dashboard.overview(self.state.cfg)
        row = next(r for r in got["waiting"] if r["id"] == rid)
        self.assertEqual(row["doing"], "Asks you: May I change the deploy script? It is on the protected list.")
        self.assertEqual(row["ask"], {"job": rid, "text": "May I change the deploy script?\nIt is on the protected list.", "mark": job_control.asked(self.state.cfg, rid)["mark"]})
        self.assertRegex(row["ask"]["mark"], r"^[0-9a-f]{16}$")
        job_control.answer(self.state.cfg, rid, True, "Yes.", mark=row["ask"]["mark"])
        self.assertEqual([r for r in dashboard.overview(self.state.cfg)["waiting"] if r["id"] == rid], [], "answered: it is no longer waiting for its owner")


class TestAPairWhoseBuilderAsks(EngineTestCase):
    def setUp(self):
        super().setUp()
        import types
        self.cfg = config.load()
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        self.cfg.projects["calc"] = types.SimpleNamespace(key="calc", name="Calculator", path=self.tmp / "calc")
        self._pause, pairing.PAUSE = pairing.PAUSE, 0.0

    def tearDown(self):
        pairing.PAUSE = self._pause
        super().tearDown()

    def test_the_pair_waits_for_its_owner_with_the_question_in_sight_and_then_carries_on(self):
        cfg, seen = self.cfg, []
        made = pairing.open_pair(cfg, "calc", GOAL)

        class Watching(Hands):
            def report(self, rid):
                state = super().report(rid)
                now = pairing.get(cfg, made["id"])
                seen.append((state["status"], bool(state.get("asked")), now["status"], (now.get("ask") or {}).get("text")))
                return state
        hands = Watching([plan([(1, "Add a value", False)], hand_over=[1]), plan([(1, "Add a value", True)], done=True)],
                         jobs={"job-1": [{"status": "needs_approval", "asked": True, "text": "May I edit the .env file?"}, {"status": "needs_approval", "asked": True, "text": "May I edit the .env file?"},
                                         {"status": "running"}, {"status": "done", "text": "Result: merged."}]})
        done = pairing.start(cfg, made["id"], hands, wait=True)
        self.assertEqual((done["status"], done["handoffs"][0]["status"], done.get("ask")), ("done", "done", None))
        self.assertEqual(seen[1][2:], ("waiting", "May I edit the .env file?"), "while it asks, the pair waits and shows the question")
        self.assertEqual(seen[3][3], None, "once it is answered and working again the question is gone")
        self.assertEqual(len(hands.built), 1, "the same job carried on: no second one was started")
        self.assertEqual(len(hands.asked), 2, "the planner was not asked to deal with the builder's question")

    def test_a_no_from_the_owner_is_told_to_the_planner(self):
        hands = Hands([plan([(1, "Add a value", False)], hand_over=[1]), plan([(1, "Add a value", False)], questions=["What would you accept instead?"])],
                      jobs={"job-1": [{"status": "cancelled", "text": "The builder stopped and asked its owner for something, and the owner said no: Not that file.\nNothing was changed."}]})
        made = pairing.open_pair(self.cfg, "calc", GOAL)
        ended = pairing.start(self.cfg, made["id"], hands, wait=True)
        self.assertEqual((ended["status"], ended["handoffs"][0]["status"]), ("halted", "cancelled"))
        self.assertIn("The job ended as: cancelled.", hands.asked[1]["prompt"])
        self.assertIn("the owner said no: Not that file.", hands.asked[1]["prompt"])


if __name__ == "__main__":
    import unittest
    unittest.main()
