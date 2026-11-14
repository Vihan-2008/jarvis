"""A planner and a builder: the plan goes across a few steps at a time, the builder's report comes back, the plan is revised."""
import json
import subprocess
import time
import types
import unittest

from jcc import config, pairing, usage
from tests.helpers import EngineTestCase

GOAL = "Add a subtract function to the calculator, with a test for it."


def plan(steps, hand_over=(), done=False, **more):
    """A planner's answer: steps as (number, title, done)."""
    return {"summary": "Small steps, each with its own test.", "steps": [{"n": n, "title": title, "detail": f"Do {title.lower()} in calc.py.", "check": "python -m unittest", "done": was}
                                                                         for n, title, was in steps],
            "hand_over": list(hand_over), "note_to_builder": "Tests live in test_calc.py.", "change": "", "done": done, "questions": [], **more}


FIRST = plan([(1, "Write subtract", False), (2, "Test subtract", False), (3, "Mention it in the README", False)], hand_over=[1, 2])
SECOND = plan([(1, "Write subtract", True), (2, "Test subtract", True), (3, "Mention it in the README", False)], hand_over=[3], change="Nothing changed; two steps are done.")
LAST = plan([(1, "Write subtract", True), (2, "Test subtract", True), (3, "Mention it in the README", True)], done=True)


class Hands:
    """Stands in for the planner (a Claude Code session) and the builder (a coding job)."""

    def __init__(self, answers, jobs=None):
        self.answers, self.jobs, self.asked, self.built = list(answers), dict(jobs or {}), [], []

    def plan(self, prompt, model, effort, session, cwd):
        self.asked.append({"prompt": prompt, "model": model, "effort": effort, "session": session, "cwd": cwd})
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return {"text": answer if isinstance(answer, str) else json.dumps(answer), "session": "0a1b2c3d-1111", "model": "claude-test-planner",
                "usage": {"input": 1000, "output": 200, "cached": 500, "cost": 0.05}}

    def build(self, pair, task, context):
        rid = f"job-{len(self.built) + 1}"
        self.built.append({"job": rid, "task": task, "context": context})
        return rid

    def report(self, rid):
        states = self.jobs.get(rid) or [{"status": "done", "text": f"Result: merged. Checks: all passed. ({rid})"}]
        return states.pop(0) if len(states) > 1 else states[0]


class PairCase(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.load()
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        self.cfg.projects["calc"] = types.SimpleNamespace(key="calc", name="Calculator", path=self.tmp / "calc")
        self._pause, pairing.PAUSE = pairing.PAUSE, 0.0

    def tearDown(self):
        pairing.PAUSE = self._pause
        super().tearDown()

    def open(self, **how):
        return pairing.open_pair(self.cfg, "calc", GOAL, **how)

    def run_pair(self, hands, pair=None):
        pair = pair or self.open()
        return pairing.start(self.cfg, pair["id"], hands, wait=True)


class TestARoundTrip(PairCase):
    def test_the_plan_goes_across_the_report_comes_back_and_the_plan_is_revised(self):
        hands = Hands([FIRST, SECOND, LAST])
        done = self.run_pair(hands)
        self.assertEqual((done["status"], len(done["plans"]), len(done["handoffs"])), ("done", 3, 2))
        self.assertEqual([h["steps"] for h in done["handoffs"]], [[1, 2], [3]])
        self.assertEqual([h["job"] for h in done["handoffs"]], ["job-1", "job-2"])
        # What the builder is asked: exactly the steps handed over, one line each, and nothing else. (A coding job turns
        # every line of what it is asked into a point it must account for: a step is one such point.)
        self.assertEqual(hands.built[0]["task"], "Step 1: Write subtract - Do write subtract in calc.py (done when: python -m unittest)\n"
                                                 "Step 2: Test subtract - Do test subtract in calc.py (done when: python -m unittest)")
        # What goes along beside it: the goal, the whole plan, the planner's note, and what to report.
        along = hands.built[0]["context"]
        self.assertIn("Hand-over 1 of a planner-and-builder pair. The goal of the whole work: " + GOAL, along)
        self.assertIn("3. Mention it in the README", along, "the whole plan, to find its way by")
        self.assertIn("The planner's note to the builder: Tests live in test_calc.py.", along)
        self.assertIn("do exactly steps 1, 2 as asked in the next message, and nothing beyond that", along)
        self.assertIn("anything about the project that the plan got wrong", along)
        # What the planner was asked the second time: the builder's report, as information.
        self.assertIn("<goal>\n" + GOAL, hands.asked[0]["prompt"])
        self.assertIn("The builder's report on hand-over 1 (steps 1, 2). The job ended as: done.", hands.asked[1]["prompt"])
        self.assertIn("<report>\nResult: merged. Checks: all passed. (job-1)", hands.asked[1]["prompt"])
        self.assertEqual(done["plans"][1]["change"], "Nothing changed; two steps are done.")
        self.assertEqual([s["done"] for s in done["plans"][2]["steps"]], [True, True, True])
        self.assertIn("goal is reached", done["now"])

    def test_the_planner_is_one_session_carried_on_and_the_record_says_which_model_really_answered(self):
        hands = Hands([FIRST, SECOND, LAST])
        done = self.run_pair(hands, self.open(planner="opus", effort="high"))
        self.assertEqual([a["session"] for a in hands.asked], ["", "0a1b2c3d-1111", "0a1b2c3d-1111"], "started once, then carried on from where it stopped")
        self.assertEqual({(a["model"], a["effort"], a["cwd"]) for a in hands.asked}, {("opus", "high", str(self.tmp / "calc"))})
        self.assertEqual((done["planner"]["model"], done["planner"]["answered_by"], done["planner"]["turns"]), ("opus", "claude-test-planner", 3))
        self.assertEqual(done["usage"], {"input": 3000, "output": 600, "cached": 1500, "cost": 0.15, "turns": 3})
        rows = usage.turns(self.cfg.state_dir, 5)
        self.assertEqual({row["model"] for row in rows}, {"claude-test-planner (planner)"})

    def test_a_failed_hand_over_goes_back_to_the_planner_which_changes_the_plan(self):
        other_way = plan([(1, "Write subtract", False), (2, "Test subtract", False), (4, "Fix the import the tests need", False)], hand_over=[4],
                         change="The tests could not import calc: step 4 comes first.")
        hands = Hands([FIRST, other_way, plan([(1, "Write subtract", True), (2, "Test subtract", True), (4, "Fix the import the tests need", True)], done=True)],
                      jobs={"job-1": [{"status": "failed", "text": "Checks failed (unittest); branch kept, nothing merged.\nImportError: No module named calc"}]})
        done = self.run_pair(hands)
        self.assertIn("The job ended as: failed.", hands.asked[1]["prompt"])
        self.assertIn("ImportError: No module named calc", hands.asked[1]["prompt"])
        self.assertEqual(done["handoffs"][1]["steps"], [4])
        self.assertEqual(done["plans"][1]["change"], "The tests could not import calc: step 4 comes first.")
        self.assertEqual(done["status"], "done")

    def test_a_change_that_needs_its_owners_review_is_waited_for(self):
        hands = Hands([FIRST, LAST], jobs={"job-1": [{"status": "running"}, {"status": "needs_approval"}, {"status": "needs_approval"}, {"status": "done", "text": "Approved and merged."}]})
        seen = []
        real = pairing._save

        def watch(cfg, pair):
            seen.append((pair["status"], pair["now"]))
            real(cfg, pair)
        pairing._save = watch
        try:
            done = self.run_pair(hands)
        finally:
            pairing._save = real
        self.assertIn(("waiting", "The builder's change is waiting for your review. Approve it in the chat and the pair carries on by itself."), seen)
        self.assertEqual((done["status"], done["handoffs"][0]["status"], done["handoffs"][0]["report"]), ("done", "done", "Approved and merged."))
        self.assertEqual(len(hands.built), 1, "the job was started once, however long it took")


class TestWhatGoesAcrossIsDecidedHere(unittest.TestCase):
    def test_only_steps_that_exist_and_are_not_done_and_only_a_few_at_a_time(self):
        made = pairing.plan_of(plan([(1, "A", True), (2, "B", False), (3, "C", False), (4, "D", False), (5, "E", False)], hand_over=[1, 9, 2, 2, 3, 4, 5, "x"]))
        self.assertEqual(made["hand_over"], [2, 3, 4], "not the one that is done, not one that does not exist, not twice, and three at most")
        self.assertEqual(made["version"], 1)
        self.assertEqual(pairing.plan_of(plan([(1, "A", False)], hand_over=[1]), made)["version"], 2)

    def test_the_goal_counts_as_reached_only_when_nothing_is_handed_over(self):
        self.assertFalse(pairing.plan_of(plan([(1, "A", False)], hand_over=[1], done=True))["done"], "done, and more to build: not done")
        self.assertTrue(pairing.plan_of(plan([(1, "A", True)], done=True))["done"])

    def test_an_answer_in_another_form_is_not_a_plan(self):
        for bad in (None, {}, {"steps": []}, {"steps": "all of it"}, {"steps": [{"n": 1}]}, {"steps": [{"n": 0, "title": "x"}]},
                    {"steps": [{"n": 1, "title": "x"}, {"n": 1, "title": "y"}]}, {"steps": ["write it"]}):
            with self.assertRaises((ValueError, TypeError, KeyError), msg=str(bad)):
                pairing.plan_of(bad)

    def test_secrets_in_a_plan_are_hidden_and_long_things_are_cut(self):
        made = pairing.plan_of({"summary": "Use the key sk-ant-api03-" + "a" * 90 + " to deploy.", "steps": [{"n": 1, "title": "t" * 500, "detail": "d" * 5000}]})
        self.assertNotIn("sk-ant-api03", made["summary"])
        self.assertEqual((len(made["steps"][0]["title"]), len(made["steps"][0]["detail"])), (160, 1200))


class TestTroubleAndStopping(PairCase):
    def test_trouble_with_the_planner_is_tried_once_more_then_the_pair_halts_and_can_carry_on(self):
        hands = Hands([subprocess.TimeoutExpired("claude", 600), "I think we should start with the README."])
        halted = self.run_pair(hands)
        self.assertEqual((halted["status"], len(hands.asked), len(hands.built)), ("halted", 2, 0))
        self.assertIn("not in the form asked for", halted["now"])
        again = Hands([FIRST, SECOND, LAST])
        done = pairing.start(self.cfg, halted["id"], again, wait=True)
        self.assertEqual((done["status"], len(done["handoffs"])), ("done", 2))

    def test_an_answer_in_the_wrong_form_is_asked_for_again_and_said_so(self):
        hands = Hands(["Here is my plan: first the function, then the test.", FIRST, LAST])
        done = self.run_pair(hands)
        self.assertEqual(done["status"], "done")
        self.assertIn("Your last answer was not one JSON object", hands.asked[1]["prompt"])

    def test_it_stops_after_a_fixed_number_of_hand_overs_and_carries_on_only_when_told_to(self):
        endless = [plan([(n, f"Step {n}", False) for n in range(1, 30)], hand_over=[k]) for k in range(1, 30)]
        hands = Hands(endless)
        halted = self.run_pair(hands)
        self.assertEqual((halted["status"], len(halted["handoffs"])), ("halted", pairing.ROUNDS))
        self.assertIn("hand-overs have been made", halted["now"])
        more = pairing.start(self.cfg, halted["id"], hands, wait=True)
        self.assertEqual(len(more["handoffs"]), 2 * pairing.ROUNDS, "its owner said carry on: as many again, and then it stops once more")

    def test_a_question_only_the_owner_can_answer_stops_it_until_they_do(self):
        asks = plan([(1, "Choose the database", False)], questions=["Postgres or SQLite?"])
        hands = Hands([asks, FIRST, SECOND, LAST])
        waiting = self.run_pair(hands)
        self.assertEqual((waiting["status"], len(hands.built)), ("halted", 0))
        self.assertIn("The planner needs an answer from you: Postgres or SQLite?", waiting["now"])
        pairing.tell(self.cfg, waiting["id"], "SQLite. Keep it simple.")
        done = pairing.start(self.cfg, waiting["id"], hands, wait=True)
        self.assertIn("From the owner of the project:\n- SQLite. Keep it simple.", hands.asked[1]["prompt"])
        self.assertEqual(done["status"], "done")
        self.assertTrue(all(note["read"] for note in done["notes"]))

    def test_stopped_means_nothing_more_is_started(self):
        pair = self.open()

        class Stops(Hands):
            def report(inner, rid):
                pairing.stop(self.cfg, pair["id"])
                return {"status": "running"}
        hands = Stops([FIRST, SECOND])
        stopped = self.run_pair(hands, pair)
        self.assertEqual((stopped["status"], len(hands.asked), len(hands.built)), ("stopped", 1, 1))
        self.assertIn("carries on as an ordinary job", stopped["now"])
        with self.assertRaises(pairing.PairError):
            pairing.start(self.cfg, pair["id"], hands, wait=True)
        with self.assertRaises(pairing.PairError):
            pairing.tell(self.cfg, pair["id"], "one more thing")

    def test_a_builder_that_cannot_be_started_halts_the_pair(self):
        class NoBuilder(Hands):
            def build(self, pair, task, context):
                raise pairing.PairError("No coding agent is available right now.")
        halted = self.run_pair(NoBuilder([FIRST]))
        self.assertEqual(halted["status"], "halted")
        self.assertIn("The builder could not be started: No coding agent is available right now.", halted["now"])
        self.assertEqual(halted["handoffs"], [], "no hand-over is on record that never went out")


class TestTheRecord(PairCase):
    def test_a_pair_cut_off_by_closing_the_app_is_shown_as_halted_and_carries_on_without_starting_the_job_again(self):
        pair = self.open()
        path = self.cfg.state_dir / "pairs" / (pair["id"] + ".json")
        saved = json.loads(path.read_text("utf-8"))
        saved.update(status="building", plans=[pairing.plan_of(FIRST)], saved=time.time() - pairing.STALE - 5,
                     handoffs=[{"number": 1, "plan": 1, "steps": [1, 2], "job": "job-9", "started": time.time(), "finished": None, "status": "", "report": ""}])
        path.write_text(json.dumps(saved), "utf-8")
        seen = pairing.get(self.cfg, pair["id"])
        self.assertEqual(seen["status"], "halted")
        self.assertIn("JARVIS was closed while this pair was at work", seen["now"])
        hands = Hands([SECOND, LAST], jobs={"job-9": [{"status": "done", "text": "Merged while JARVIS was closed."}]})
        done = pairing.start(self.cfg, pair["id"], hands, wait=True)
        self.assertEqual([b["job"] for b in hands.built], ["job-1"], "the job that was out is waited for, not started again; then the next one")
        self.assertEqual(done["handoffs"][0]["report"], "Merged while JARVIS was closed.")
        self.assertEqual(done["status"], "done")

    def test_what_a_pair_needs_to_begin(self):
        for goal, project in (("too short", "calc"), ("x" * 400_001, "calc"), (GOAL, "no-such-project")):
            with self.assertRaises(pairing.PairError):
                pairing.open_pair(self.cfg, project, goal)
        with self.assertRaises(pairing.PairError):
            pairing.open_pair(self.cfg, "calc", GOAL, builder="--dangerously-skip-permissions; rm -rf")
        for ident in ("../../secrets", "pair-1", "", None, "pair-20261114-010101-zzzz"):
            with self.assertRaises(pairing.PairError):
                pairing.get(self.cfg, ident)
        self.assertEqual(pairing.listing(self.cfg), [])
        made = self.open()
        self.assertEqual(made["status"], "new")
        listed = pairing.listing(self.cfg)
        self.assertEqual([(p["id"], p["status"], p["project"]) for p in listed], [(made["id"], "new", "calc")])

    def test_the_list_says_how_far_each_pair_is(self):
        done = self.run_pair(Hands([FIRST, SECOND, LAST]))
        row = pairing.listing(self.cfg)[0]
        self.assertEqual((row["id"], row["status"], row["version"], row["steps"], row["done"], row["handoffs"], row["answered_by"]),
                         (done["id"], "done", 3, 3, 3, 2, "claude-test-planner"))


class Done:
    def __init__(self, answer, stderr=""):
        self.stdout, self.stderr = json.dumps(answer) if isinstance(answer, dict) else answer, stderr


class TestThePlannerItself(PairCase):
    def test_it_can_read_and_search_files_and_nothing_else_and_what_it_is_asked_is_never_on_the_command_line(self):
        started = []
        answer = {"result": json.dumps(FIRST), "is_error": False, "session_id": "0a1b2c3d-4e5f-6071-8293-a4b5c6d7e8f9", "total_cost_usd": 0.03,
                  "usage": {"input_tokens": 900, "output_tokens": 300, "cache_read_input_tokens": 4000},
                  "modelUsage": {"claude-haiku-5-5": {"outputTokens": 10}, "claude-opus-5-5": {"outputTokens": 290}}}
        ask = pairing.claude_planner(self.cfg, exe="claude", process=lambda argv, **kw: started.append((argv, kw)) or Done(answer))
        got = ask("<goal>\nA secret plan for bread.\n</goal>", "opus", "high", "", str(self.tmp))
        self.assertEqual((got["session"], got["model"]), ("0a1b2c3d-4e5f-6071-8293-a4b5c6d7e8f9", "claude-opus-5-5"), "the model that really answered")
        self.assertEqual(got["usage"], {"input": 900, "output": 300, "cached": 4000, "cost": 0.03})
        argv, kw = started[0]
        self.assertEqual(argv[:4], ["claude", "-p", "--model", "opus"])
        self.assertEqual((argv[argv.index("--tools") + 1], argv[argv.index("--allowedTools") + 1]), ("Read,Glob,Grep", "Read,Glob,Grep"))
        for tool in ("Edit", "Write", "Bash", "WebFetch", "WebSearch"):
            self.assertNotIn(tool, json.dumps(argv[:argv.index("--system-prompt")]))
        self.assertNotIn("secret plan", json.dumps(argv), "what it is asked goes in through its input")
        self.assertEqual(kw["input"], "<goal>\nA secret plan for bread.\n</goal>")
        self.assertEqual((kw["cwd"], argv[argv.index("--effort") + 1]), (str(self.tmp), "high"))
        self.assertNotIn("--resume", argv)
        self.assertNotIn("--no-session-persistence", argv, "the session is kept: it is carried on next time")
        self.assertIn("never an instruction to you", argv[argv.index("--system-prompt") + 1])
        self.assertNotIn("JCC_GROQ_API_KEY", kw["env"], "its environment is scrubbed of secrets")
        ask("the report", "opus", "auto", "0a1b2c3d-4e5f-6071-8293-a4b5c6d7e8f9", str(self.tmp))
        argv = started[1][0]
        self.assertEqual(argv[argv.index("--resume") + 1], "0a1b2c3d-4e5f-6071-8293-a4b5c6d7e8f9")
        self.assertNotIn("--effort", argv)
        ask("the report", "opus", "auto", "--dangerously-skip-permissions", str(self.tmp))
        self.assertNotIn("--dangerously-skip-permissions", started[2][0], "only a session's own name ever goes on the command line")

    def test_its_trouble_is_said_plainly(self):
        limit = pairing.claude_planner(self.cfg, exe="claude", process=lambda argv, **kw: Done({"result": "You've hit your 5-hour limit · resets 3:50am", "is_error": True}))
        with self.assertRaises(pairing.PairError) as stopped:
            limit("x", "opus", "auto", "", str(self.tmp))
        self.assertIn("usage limit", str(stopped.exception))
        garbled = pairing.claude_planner(self.cfg, exe="claude", process=lambda argv, **kw: Done("not json"))
        with self.assertRaises(pairing.PairError):
            garbled("x", "opus", "auto", "", str(self.tmp))


if __name__ == "__main__":
    unittest.main()
