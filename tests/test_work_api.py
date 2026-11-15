"""The planner-and-builder pair, the Court and the list of what every agent is doing, as the app offers them."""
import json
import os
import threading
import time
import types
from pathlib import Path

from jcc import config, court, dashboard, pairing, review
from jcc.chats import Chats
from jcc.gui import GuiState
from jcc.jobrunner import record, run_job
from jcc.vault import render_note
from tests.helpers import EngineTestCase
from tests.test_court import FakeCourt, IDEA
from tests.test_gui import GuiTestCase
from tests.test_pairing import FIRST, GOAL, Hands, plan
from tests.test_projects import git, make_repo, overrides


class TestAPairThroughTheRealJobPipeline(EngineTestCase):
    """The builder is an ordinary coding job: its own copy of the project, the project's checks, merged only if they pass.
    Here that whole pipeline runs for real on a small temporary project, with a stand-in for the coding agent."""

    def setUp(self):
        super().setUp()
        self.repo = make_repo(self.tmp)
        os.environ["FAKEAGENT_MODE_CODEX"] = "edit"
        cfg = config.load(overrides(self.repo))

        def spawner(argv, cwd, env):                       # what the job's own process does, with this test's settings
            workdir = Path(argv[-1])

            def work():
                spec = json.loads((workdir / "job.json").read_text("utf-8"))
                record(cfg, spec, workdir, run_job(cfg, spec, workdir), 1.0)
            threading.Thread(target=work, daemon=True).start()
            return 1
        self.state = GuiState(cfg, {"transport": self.transport, "spawner": spawner})
        self._pause, pairing.PAUSE = pairing.PAUSE, 0.1
        self.approved = []

    def hands(self):
        """The app's own hands, with an owner who looks at each change that waits for a review and approves it."""
        hands = self.state.pair_hands()
        real = hands.report

        def report(rid):
            state = real(rid)
            if state["status"] == "needs_approval" and rid not in self.approved:
                self.approved.append(rid)
                review.approve(self.state.cfg, rid, review.details(self.state.cfg, rid)["revision"])
            return state
        hands.report = report
        return hands

    def tearDown(self):
        pairing.PAUSE = self._pause
        os.environ.pop("FAKEAGENT_MODE_CODEX", None)
        super().tearDown()

    def test_the_plan_is_built_by_a_real_job_and_its_report_comes_back_to_the_planner(self):
        one = plan([(1, "Add a value to the package", False), (2, "Say so in the README", False)], hand_over=[1])
        two = plan([(1, "Add a value to the package", True), (2, "Say so in the README", False)], hand_over=[2], change="Step 1 is merged.")
        three = plan([(1, "Add a value to the package", True), (2, "Say so in the README", True)], done=True)
        planner = Hands([one, two, three])
        self.state.pair_planner = planner.plan
        from jcc import assistant
        assistant.configure(self.state.cfg, {"ask": "all"})           # Manual: each change waits for its owner
        made = pairing.open_pair(self.state.cfg, "trading", GOAL, builder="auto")
        done = pairing.start(self.state.cfg, made["id"], self.hands(), wait=True)
        self.assertEqual((done["status"], len(done["handoffs"])), ("done", 2), done["now"])
        first = done["handoffs"][0]
        self.assertEqual(first["status"], "done", first["report"][:400])
        self.assertEqual(self.approved, [h["job"] for h in done["handoffs"]], "each change waited for its owner's review, and the pair carried on once it was approved; "
                         + " | ".join(f"{h['job']}: {h.get('status')}: {str(h.get('report', ''))[:300]}" for h in done["handoffs"]))
        self.assertIn("Reviewed and merged with passing checks", first["report"], "the builder's own report: what the job did, and that the checks passed")
        self.assertIn("added_by_agent", git("show", "master:src/pkg/__init__.py", cwd=self.repo), "the change really is in the project")
        # The planner was given that report, as information, and revised the plan.
        self.assertIn("The builder's report on hand-over 1 (steps 1). The job ended as: done.", planner.asked[1]["prompt"])
        self.assertIn("Reviewed and merged with passing checks", planner.asked[1]["prompt"])
        self.assertIn("unittest discover", planner.asked[1]["prompt"], "which of the project's checks ran")
        self.assertEqual(done["plans"][1]["change"], "Step 1 is merged.")
        # The pair has a chat of its own in the project, where the plan and each hand-over can be read.
        chat = Chats(self.state.cfg).get(done["chat"])
        self.assertEqual(chat.get("project"), "trading")
        said = [m["content"] for m in chat["messages"]]
        self.assertTrue(any(m.startswith("**From the planner**") and "1. Add a value to the package" in m and "Hand-over 1" in m for m in said))
        asked = [m.get("task", "") for m in chat["messages"] if m.get("job")]
        self.assertTrue(any(m.startswith("Step 1: Add a value to the package") for m in asked), "what the builder was asked: the step, and nothing else")
        self.assertFalse(any(m["role"] == "user" for m in chat["messages"]), "a job of the chat, not a second message of the owner's")
        self.assertEqual(planner.asked[0]["cwd"], str(self.repo), "the planner reads the project itself")

    def test_a_change_that_fails_the_projects_checks_is_not_merged_and_the_planner_is_told(self):
        os.environ["FAKEAGENT_MODE_CODEX"] = "fail_tests"
        os.environ["FAKEAGENT_MODE_CLAUDE"] = "fail_tests"
        one = plan([(1, "Add a value to the package", False)], hand_over=[1])
        gives_up = plan([(1, "Add a value to the package", False)], questions=["The tests fail whatever is tried. Shall I stop?"])
        planner = Hands([one, gives_up])
        self.state.pair_planner = planner.plan
        try:
            made = pairing.open_pair(self.state.cfg, "trading", GOAL)
            ended = pairing.start(self.state.cfg, made["id"], self.hands(), wait=True)
        finally:
            os.environ.pop("FAKEAGENT_MODE_CLAUDE", None)
        self.assertEqual(ended["handoffs"][0]["status"], "stalled", "the job stopped itself: that is told to the planner, not waited for")
        self.assertIn("nothing was merged", ended["handoffs"][0]["report"])
        self.assertEqual(git("show", "master:src/pkg/__init__.py", cwd=self.repo), "VALUE = 1\n", "the project is as it was")
        self.assertIn("The job ended as: stalled.", planner.asked[1]["prompt"])
        self.assertIn("Repeated check failure without a successful repair", planner.asked[1]["prompt"])
        self.assertIn("The planner needs an answer from you", ended["now"])

    def test_a_builder_that_stops_and_asks_is_waited_for_with_its_question(self):
        """As a real run went: the job ends "needs approval" with nothing changed, and what it asked is in its folder.
        That is its owner's to answer (tests/test_job_answer.py): the pair is told it is a question, and what was asked."""
        rid = "20261114-020202-abcd"
        (self.vault / "Jobs").mkdir(exist_ok=True)
        (self.vault / "Jobs" / (rid + ".md")).write_text(render_note({"id": rid, "status": "needs_approval", "asked": True, "files_changed": 0}, "# Job\n\nAgent output"), "utf-8")
        folder = self.state.cfg.jobs_root / rid
        folder.mkdir(parents=True)
        (folder / "ASKED.md").write_text("# Approval needed\n\nReading the project file was denied. Paste the existing function, or allow the edit.", "utf-8")
        got = self.state.pair_hands().report(rid)
        self.assertEqual((got["status"], got["asked"]), ("needs_approval", True))
        self.assertIn(got["status"], pairing.WAITING, "the pair waits for its owner's answer")
        self.assertIn("Reading the project file was denied", got["text"])
        self.assertTrue(got["why"].startswith("# Approval needed Reading the project file was denied."))
        # A change that waits for a review is a review, not a question.
        (self.vault / "Jobs" / (rid + ".md")).write_text(render_note({"id": rid, "status": "needs_approval", "asked": False}, "# Job"), "utf-8")
        (folder / "repo").mkdir()
        self.assertNotIn("asked", self.state.pair_hands().report(rid))
        # A no from the owner ends the job, and the planner is given the owner's words.
        (self.vault / "Jobs" / (rid + ".md")).write_text(render_note({"id": rid, "status": "cancelled", "declined": "Not that file."}, "# Job\n\nlast words"), "utf-8")
        told = self.state.pair_hands().report(rid)
        self.assertEqual(told["status"], "cancelled")
        self.assertIn("the owner said no: Not that file.", told["text"])

    def test_a_job_jarvis_is_carrying_on_by_itself_is_still_working(self):
        """Requirements left (or the project changed under it): between stopping and starting again, it is not stalled."""
        rid = "20261114-020404-abcd"
        (self.vault / "Jobs").mkdir(exist_ok=True)
        note = self.vault / "Jobs" / (rid + ".md")
        note.write_text(render_note({"id": rid, "status": "paused", "carrying_on": True, "unfinished": True}, "# Job"), "utf-8")
        got = self.state.pair_hands().report(rid)
        self.assertEqual(got["status"], "running")
        self.assertIn(got["status"], pairing.WAITING)
        note.write_text(render_note({"id": rid, "status": "paused", "carrying_on": False, "unfinished": True}, "# Job\n\nNot finished: 0 of 1"), "utf-8")
        self.assertEqual(self.state.pair_hands().report(rid)["status"], "stalled", "after its rounds it waits for its owner")

    def test_the_planner_hears_what_was_established_and_the_builders_last_words_not_raw_output(self):
        """A real run gave the planner the tail of the agent's raw output, and it drew a wrong conclusion from it."""
        from jcc import live
        rid = "20261114-020303-abcd"
        raw = '{"tool_name":"Bash","usage":{"outputTokens":128000},"credential_expires_at":"2026-12-07T22:31:55.619Z"}'
        body = ("# Job " + rid + ": done\n\n**Agent:** claude \u00b7 **level:** medium \u00b7 **32 s**\n\n**Project:** Calc \u00b7 **branch:** `jcc/" + rid + "`\n\n"
                "**Result:** Merged into main after all checks passed.\n\n## Checks\n- \u2705 unittest discover\n\n## Files changed\n- `src/app.py`\n\n"
                "## Agent attempts\n- claude (haiku): exit 0 \u00b7 30.97s\n\n## Agent output (tail)\n```\n" + raw + "\n```\n\n\nReviewed and merged with passing checks.")
        (self.vault / "Jobs").mkdir(exist_ok=True)
        (self.vault / "Jobs" / (rid + ".md")).write_text(render_note({"id": rid, "status": "done", "merged": "abc123"}, body), "utf-8")
        feed = live.Feed("claude", self.state.cfg.jobs_root / rid / "live.jsonl")
        feed.emit("step", "Editing src/app.py")
        feed.emit("say", "I added median below main. I also wrote JCC_PROGRESS.md with what is left.")
        got = self.state.pair_hands().report(rid)["text"]
        self.assertIn("**Result:** Merged into main after all checks passed.", got)
        self.assertIn("- `src/app.py`", got)
        self.assertIn("Reviewed and merged with passing checks.", got)
        self.assertIn("What the builder said at the end:\nI added median below main.", got)
        self.assertIn("are the job's own working notes. They are never merged into the project.", got)
        self.assertNotIn("credential_expires_at", got)
        self.assertNotIn("outputTokens", got)
        self.assertNotIn("# Job " + rid, got)
        # A job with no step-by-step record: the facts alone, and still none of the raw output.
        other = "20261114-020304-abcd"
        (self.vault / "Jobs" / (other + ".md")).write_text(render_note({"id": other, "status": "failed"}, body.replace(rid, other)), "utf-8")
        bare = self.state.pair_hands().report(other)["text"]
        self.assertIn("**Result:**", bare)
        self.assertNotIn("credential_expires_at", bare)
        self.assertNotIn("What the builder said", bare)

    def test_something_a_job_is_never_allowed_to_do_is_told_to_the_planner_instead_of_waited_for(self):
        hands = self.state.pair_hands()
        rid = "20261114-010101-abcd"
        (self.vault / "Jobs").mkdir(exist_ok=True)
        (self.vault / "Jobs" / (rid + ".md")).write_text(render_note({"id": rid, "status": "needs_approval", "blocked_by": "deploys"}, "# Needs approval"), "utf-8")
        state = hands.report(rid)
        self.assertEqual(state["status"], "blocked")
        self.assertIn("does not let a coding job do this by itself, because it involves deploys", state["text"])
        self.assertNotIn(state["status"], pairing.WAITING, "the pair does not wait for a review that will never come")
        (self.vault / "Jobs" / (rid + ".md")).write_text(render_note({"id": rid, "status": "needs_approval"}, "# Review"), "utf-8")
        (self.state.cfg.jobs_root / rid / "repo").mkdir(parents=True)          # (the job's own copy of the project, with the change in it)
        self.assertEqual(hands.report(rid)["status"], "needs_approval", "a change waiting for its owner's review is waited for")
        self.assertEqual(hands.report("20261114-010101-ffff")["status"], "failed", "a hand-over of which no job was made")


class TestTheAddresses(GuiTestCase):
    def call(self, path, **body):
        return self.req("POST", path, body)

    def test_pairs_what_there_is_to_choose_from_and_what_is_refused(self):
        status, got = self.call("/api/pairs", action="list")
        self.assertEqual(status, 200)
        self.assertEqual((got["pairs"], got["rounds"]), ([], pairing.ROUNDS))
        self.assertTrue(all(m["provider"] == "claude" for m in got["planners"]), "the planner is a Claude Code session")
        self.assertIn("claude:opus", [m["id"] for m in got["planners"]])
        for body in ({"action": "open", "project": "no-such", "goal": GOAL}, {"action": "open", "project": "", "goal": "short"},
                     {"action": "get", "id": "../../x"}, {"action": "stop", "id": "pair-20261114-010101-zzzz"}, {"action": "dance"}):
            status, got = self.call("/api/pairs", **body)
            self.assertEqual(status, 400, body)
            self.assertNotIn("Traceback", json.dumps(got))
        self.assertEqual(self.req("POST", "/api/pairs", {"action": "list"}, token=False)[0], 401, "only this app's own window may ask")

    def test_a_pair_is_opened_started_told_and_stopped_over_the_wire(self):
        self.state.cfg.projects["calc"] = types.SimpleNamespace(key="calc", name="Calculator", path=self.tmp / "calc")
        planner = Hands([FIRST])

        class Idle(Hands):
            def build(inner, pair, task, context):
                return "20261114-010101-abcd"

            def report(inner, rid):
                return {"status": "running"}
        hands = Idle([FIRST])
        self.state.pair_hands = lambda: hands
        old, pairing.PAUSE = pairing.PAUSE, 0.05
        try:
            status, made = self.call("/api/pairs", action="open", project="calc", goal=GOAL, planner="claude:opus", builder="auto")
            self.assertEqual((status, made["planner"]["model"]), (200, "opus"))
            for _ in range(100):
                status, seen = self.call("/api/pairs", action="get", id=made["id"])
                if seen["status"] == "building" and seen["handoffs"]:
                    break
                time.sleep(0.05)
            self.assertEqual((seen["status"], seen["handoffs"][0]["job"], seen["handoffs"][0]["steps"]), ("building", "20261114-010101-abcd", [1, 2]))
            self.assertEqual(self.call("/api/pairs", action="start", id=made["id"])[0], 400, "it is at work already")
            status, told = self.call("/api/pairs", action="tell", id=made["id"], text="Keep the README short.")
            self.assertEqual((status, told["notes"][-1]["text"]), (200, "Keep the README short."))
            status, stopped = self.call("/api/pairs", action="stop", id=made["id"])
            self.assertEqual((status, stopped["status"]), (200, "stopped"))
            for _ in range(100):
                if made["id"] not in pairing._live:
                    break
                time.sleep(0.05)
            final = self.call("/api/pairs", action="get", id=made["id"])[1]
            self.assertEqual(final["status"], "stopped", "what its owner did is not written over by the pair itself")
            self.assertEqual([n["text"] for n in final["notes"]], ["Keep the README short."])
            self.assertEqual(self.call("/api/pairs", action="list")[1]["pairs"][0]["id"], made["id"])
        finally:
            pairing.PAUSE = old
        del planner

    def test_a_trial_in_the_court_from_the_rules_to_the_verdict(self):
        status, got = self.call("/api/court", action="list")
        self.assertEqual(status, 200)
        self.assertEqual([s["title"] for s in got["stages"]], ["Grand Jury", "Prosecution", "Analysts", "Tribunal", "Executioner"])
        self.assertIn("There are no appeals and no second tries for a kinder answer.", got["rules"])
        self.assertEqual(len(got["analysts"]), 3)
        self.state.court_asker = FakeCourt()
        old, court.PAUSE = court.PAUSE, 0.0
        try:
            status, session = self.call("/api/court", action="open")
            self.assertEqual((status, session["status"]), (200, "awaiting_idea"))
            self.assertEqual(self.call("/api/court", action="submit", id=session["id"], idea="too short")[0], 400)
            status, begun = self.call("/api/court", action="submit", id=session["id"], idea=IDEA)
            self.assertEqual((status, begun["status"]), (200, "in_session"))
            status, again = self.call("/api/court", action="submit", id=session["id"], idea=IDEA + " And free coffee.")
            self.assertEqual(status, 400, "one idea per session, and it cannot be changed")
            self.assertIn("One idea per session", again["error"])
            for _ in range(200):
                status, seen = self.call("/api/court", action="get", id=session["id"])
                if seen["status"] == "closed":
                    break
                time.sleep(0.05)
            self.assertEqual((seen["status"], seen["verdict"]), ("closed", "PASS"))
            self.assertTrue(seen["uncertainty"], "what is still uncertain is said with a PASS")
            self.assertEqual(self.call("/api/court", action="resume", id=session["id"])[0], 400, "a closed trial is never reopened")
            self.assertEqual(self.call("/api/court", action="get", id="court-1")[0], 400)
            listed = self.call("/api/court", action="list")[1]["sessions"]
            self.assertEqual([(s["id"], s["verdict"]) for s in listed], [(session["id"], "PASS")])
        finally:
            court.PAUSE = old

    def test_what_every_agent_is_doing_is_one_request(self):
        status, got = self.call("/api/agents", action="now")
        self.assertEqual(status, 200)
        self.assertEqual((got["working"], got["waiting"], got["held"], got["recent"]), ([], [], [], []))


class TestWhatEveryAgentIsDoing(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.load()
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        (self.vault / "Jobs").mkdir(exist_ok=True)
        self.cfg.projects["calc"] = types.SimpleNamespace(key="calc", name="Calculator", path=self.tmp / "calc")

    def job(self, rid, **fm):
        (self.vault / "Jobs" / (rid + ".md")).write_text(render_note({"id": rid, "task": "Fix the stop-loss rounding", "project_key": "calc", **fm}, "# Job"), "utf-8")

    def test_jobs_are_sorted_into_working_waiting_held_and_just_finished(self):
        from jcc import activity, live
        self.job("20261114-010101-aaaa", status="running", agent="claude", model="sonnet", chat_id="chat-1")
        activity.emit(self.cfg, "20261114-010101-aaaa", "working", "Agent is working in the isolated workspace.", agent="claude", model="sonnet")
        feed = live.Feed("claude", self.cfg.jobs_root / "20261114-010101-aaaa" / "live.jsonl")
        feed.emit("step", "Reading risk.py")
        feed.emit("step", "Running the tests")
        self.job("20261114-010102-bbbb", status="needs_approval")
        (self.cfg.jobs_root / "20261114-010102-bbbb" / "repo").mkdir(parents=True)        # (its own copy of the project: there is a change to review)
        self.job("20261114-010103-cccc", status="needs_approval", blocked_by="deploys")
        self.job("20261114-010107-abab", status="needs_approval", asked=True)
        (self.cfg.jobs_root / "20261114-010107-abab").mkdir(parents=True)
        (self.cfg.jobs_root / "20261114-010107-abab" / "ASKED.md").write_text("May I change the deploy script?", "utf-8")
        self.job("20261114-010104-dddd", status="queued", wait_reason="Claude's allowance is used up until 3 pm.")
        self.job("20261114-010105-eeee", status="done", merged="abc123")
        self.job("20261114-010106-ffff", status="failed")
        self.job("not-a-job", status="running")
        got = dashboard.overview(self.cfg)
        working = got["working"]
        self.assertEqual([(r["kind"], r["id"], r["who"], r["project"], r["chat"], r["doing"]) for r in working],
                         [("job", "20261114-010101-aaaa", "claude · sonnet", "Calculator", "chat-1", "Running the tests")], "the step it is on this moment")
        self.assertEqual({r["id"]: r["doing"] for r in got["waiting"]},
                         {"20261114-010102-bbbb": "Waiting for your review before it is merged", "20261114-010103-cccc": "Never done automatically: deploys",
                          "20261114-010107-abab": "Asks you: May I change the deploy script?"})
        self.assertEqual(next(r for r in got["waiting"] if r["id"] == "20261114-010107-abab")["ask"], {"job": "20261114-010107-abab", "text": "May I change the deploy script?", "mark": "4cc910b57d7c4268"})
        self.assertEqual([(r["id"], r["doing"]) for r in got["held"]], [("20261114-010104-dddd", "Claude's allowance is used up until 3 pm.")])
        self.assertEqual({r["id"]: r["doing"] for r in got["recent"]}, {"20261114-010105-eeee": "Finished: merged", "20261114-010106-ffff": "Did not finish"})
        old = dashboard.overview(self.cfg, now=time.time() + 3600)
        self.assertEqual(old["recent"], [], "what finished an hour ago is no longer news")

    def test_the_assistant_a_pair_a_trial_and_a_scan_are_in_the_same_list(self):
        turn = types.SimpleNamespace(id="t1", chat="chat-9", model="claude-opus-5-5", text="open my Netflix home page", spoken=True, started=time.time() - 3, doing="Opening netflix.com")
        pair = pairing.open_pair(self.cfg, "calc", GOAL)
        path = self.cfg.state_dir / "pairs" / (pair["id"] + ".json")
        saved = json.loads(path.read_text("utf-8"))
        saved.update(status="building", now="The builder is working on steps 1, 2.", plans=[pairing.plan_of(FIRST)], saved=time.time())
        saved["planner"]["answered_by"] = "claude-fable-5-2"
        path.write_text(json.dumps(saved), "utf-8")
        session = court.open_session(self.cfg)
        court.submit(self.cfg, session["id"], IDEA, start=False)
        got = dashboard.overview(self.cfg, [turn], {"status": "working", "source": "https://github.com/x/y", "step": "Scanning skills: part 12 of 113", "at": time.time()})
        rows = {r["kind"]: r for r in got["working"]}
        self.assertEqual(set(rows), {"assistant", "pair", "court", "scan"})
        self.assertEqual((rows["assistant"]["who"], rows["assistant"]["doing"], rows["assistant"]["chat"]), ("claude-opus-5-5", "Opening netflix.com", "chat-9"))
        self.assertEqual((rows["pair"]["who"], rows["pair"]["doing"], rows["pair"]["steps"], rows["pair"]["project"]),
                         ("planner claude-fable-5-2 with a builder", "The builder is working on steps 1, 2.", [0, 3], "Calculator"))
        self.assertEqual(rows["court"]["title"], IDEA[:140])
        self.assertEqual(rows["scan"]["doing"], "Scanning skills: part 12 of 113")
        self.assertEqual(got["working"][0]["kind"], "assistant", "what is answering you this moment comes first")

    def test_a_pair_that_waits_for_its_owner_is_under_waiting_and_what_is_set_for_later_is_listed(self):
        pair = pairing.open_pair(self.cfg, "calc", GOAL)
        path = self.cfg.state_dir / "pairs" / (pair["id"] + ".json")
        saved = json.loads(path.read_text("utf-8"))
        saved.update(status="halted", now="The planner needs an answer from you: Postgres or SQLite?")
        path.write_text(json.dumps(saved), "utf-8")
        from jcc.reminders import Reminders
        Reminders(self.cfg).add("Call the dentist", time.time() + 3600)
        got = dashboard.overview(self.cfg)
        self.assertEqual([(r["kind"], r["doing"]) for r in got["waiting"]], [("pair", "The planner needs an answer from you: Postgres or SQLite?")])
        self.assertEqual([(r["kind"], r["title"]) for r in got["later"]], [("reminder", "Call the dentist")])
        self.assertEqual(got["working"], [])

    def test_a_long_line_is_cut_at_a_word_and_says_so(self):
        long = "Rename the stylesheet and update every page that links to it, then check each page in turn " * 3
        self.job("20261114-010101-aaaa", status="queued", task=long, wait_reason="x" * 400)
        row = dashboard.overview(self.cfg)["held"][0]
        self.assertLessEqual(len(row["title"]), 140)
        self.assertTrue(row["title"].endswith("\u2026"), row["title"])
        self.assertFalse(row["title"][:-1].endswith(" "))
        self.assertIn(row["title"][:-1].split()[-1], long.split(), "it ends on a whole word")
        self.assertEqual(row["doing"], "x" * 139 + "\u2026", "one unbroken word is cut where it must be")
        self.job("20261114-010102-bbbb", status="queued", task="Short enough")
        self.assertEqual(dashboard.overview(self.cfg)["held"][0]["title"], "Short enough")

    def test_secrets_never_reach_the_list(self):
        self.job("20261114-010101-aaaa", status="running", task="Use the key sk-ant-api03-" + "a" * 90 + " to deploy")
        self.assertNotIn("sk-ant-api03", json.dumps(dashboard.overview(self.cfg)))


if __name__ == "__main__":
    import unittest
    unittest.main()
