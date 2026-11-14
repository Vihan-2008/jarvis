"""The Court of JARVIS: one idea, five stages, a verdict worked out in code, and a record that is never rewritten."""
import json
import os
import subprocess
import threading
import time
import unittest

from jcc import config, court, usage
from tests.helpers import EngineTestCase

IDEA = "A bakery that delivers bread by bicycle within an hour of baking, in one small town."
SOURCE = {"title": "Town bakery prices 2026", "url": "https://example.org/bakery-prices", "date": "March 2026", "claim": "Bread sells for 4 euros.", "stance": "mixed"}


def analyst(holds=True, decisive=False, sources=(SOURCE,), gaps=(), blocker=""):
    return {"holds": holds, "decisive": decisive, "blocker": blocker, "summary": "It holds." if holds else "It does not hold.",
            "findings": ["Demand is steady."], "sources": list(sources), "conflicts": [], "gaps": list(gaps)}


def tribunal(**findings):
    return {"criteria": {key: {"finding": findings.get(key, "met"), "reason": f"The record shows it for {key}."} for key, _ in court.CRITERIA},
            "summary": "Weighed as a whole."}


class FakeCourt:
    """Stands in for every member of the court. Each role answers from a script (a fixed answer, an error to raise, or a
    function of how many times it has been asked); every call is recorded."""

    def __init__(self, **script):
        self.calls, self.lock = [], threading.Lock()
        self.searches = script.pop("searches", {})
        self.script = {"grand_jury": {"decision": "advance", "reason": "A definite proposal that can be tested.", "coherence": "Clear.",
                                      "viability": "Plausible.", "assumptions": ["People pay more for fresh bread."]},
                       "prosecution": {"charges": [{"charge": "Thin margins", "severity": "serious", "detail": "Delivery eats the margin."}],
                                       "survives": "No charge goes to the root of the idea."},
                       "analysts:logistics": analyst(), "analysts:economics": analyst(gaps=["No local survey of willingness to pay."]),
                       "analysts:dependencies": analyst(),
                       "tribunal": tribunal(distinctiveness="unproven"),
                       "executioner": lambda n, prompt: {"pronouncement": "The verdict is PASS. It survived every stage; its demand is still unproven."}}
        self.script.update({k.replace("__", ":"): v for k, v in script.items()})

    def asked(self, role):
        return [c for c in self.calls if c["role"] == role]

    def __call__(self, role, system, prompt, model, research, timeout):
        with self.lock:
            self.calls.append({"role": role, "system": system, "prompt": prompt, "model": model, "research": research, "timeout": timeout})
            n = len(self.asked(role))
        answer = self.script[role]
        if callable(answer):
            answer = answer(n, prompt)
        if isinstance(answer, BaseException):
            raise answer
        searches = self.searches.get(role, 3 if research else 0)
        return {"text": answer if isinstance(answer, str) else json.dumps(answer), "model": model, "searches": searches,
                "usage": {"input": 100, "output": 20, "cached": 5, "cost": 0.01}}


class CourtCase(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.load()
        self.pause, court.PAUSE = court.PAUSE, 0

    def tearDown(self):
        court.PAUSE = self.pause
        super().tearDown()

    def trial(self, fake, idea=IDEA):
        session = court.open_session(self.cfg)
        court.submit(self.cfg, session["id"], idea, start=False)
        return court.run(self.cfg, session["id"], runner=fake)

    def stage(self, session, key):
        return next(s for s in session["stages"] if s["key"] == key)


class TestTheRules(CourtCase):
    def test_the_rules_are_fixed_and_say_the_essentials(self):
        said = court.rules()
        self.assertEqual(said, court.rules())
        self.assertTrue(6 <= len(said) <= 8)
        whole = " ".join(said).lower()
        for words in ("one idea", "five stages", "straight to the executioner", "no appeals", "cannot be edited", "permanent", "pass means"):
            self.assertIn(words, whole)

    def test_each_seat_has_its_model_and_the_tribunal_gets_the_strongest(self):
        seats = court.models(self.cfg)
        self.assertEqual({k: v for k, v in seats.items() if k != "tribunal"}, {"grand_jury": "sonnet", "prosecution": "opus", "analysts": "sonnet", "executioner": "haiku"})
        self.assertEqual(seats["tribunal"], "opus")
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        (self.cfg.state_dir / "quota-claude.json").write_text(json.dumps({"models": [{"value": "fable", "displayName": "Fable"}]}), "utf-8")
        self.assertEqual(court.models(self.cfg)["tribunal"], "fable")


class TestTheIdea(CourtCase):
    def test_one_idea_per_session_and_it_can_never_be_changed(self):
        session = court.open_session(self.cfg)
        self.assertEqual((session["status"], session["idea"]), ("awaiting_idea", None))
        self.assertEqual([s["status"] for s in session["stages"]], ["pending"] * 5)
        got = court.submit(self.cfg, session["id"], "   " + IDEA + "  \n", start=False)
        self.assertEqual((got["status"], got["idea"]), ("in_session", IDEA))
        with self.assertRaises(court.CourtError) as again:
            court.submit(self.cfg, session["id"], "A completely different idea about selling umbrellas.", start=False)
        self.assertIn("One idea per session", str(again.exception))
        self.assertEqual(court.get(self.cfg, session["id"])["idea"], IDEA)

    def test_ideas_too_short_or_too_long_are_refused_without_starting_anything(self):
        session = court.open_session(self.cfg)
        fake = FakeCourt()
        for idea in ("", "   ", "too short", "x" * 6001):
            with self.assertRaises(court.CourtError, msg=idea[:20]):
                court.submit(self.cfg, session["id"], idea, runner=fake)
        self.assertEqual(fake.calls, [])
        self.assertEqual(court.get(self.cfg, session["id"])["status"], "awaiting_idea")
        self.assertEqual(court.submit(self.cfg, session["id"], "y" * 6000, start=False)["status"], "in_session", "6000 is still allowed")

    def test_secrets_in_an_idea_are_hidden(self):
        session = court.open_session(self.cfg)
        got = court.submit(self.cfg, session["id"], "Use my key " + os.environ["JCC_GROQ_API_KEY"] + " to build a translation app for bakers.", start=False)
        self.assertNotIn(os.environ["JCC_GROQ_API_KEY"], got["idea"])


class TestAFullTrial(CourtCase):
    def test_a_passing_idea_goes_through_all_five_stages(self):
        fake = FakeCourt()
        done = self.trial(fake)
        self.assertEqual(done["status"], "closed")
        self.assertEqual([s["status"] for s in done["stages"]], ["done"] * 5)
        self.assertEqual([s["decision"] for s in done["stages"][:4]], ["advance"] * 4)
        self.assertEqual(done["verdict"], "PASS")
        self.assertIn("The verdict is PASS", done["pronouncement"])
        self.assertEqual(done["now"], "")
        self.assertIsNotNone(done["closed"])
        self.assertEqual(done["research"], "ok")
        self.assertEqual(len(done["evidence"]), 3)
        self.assertEqual(done["evidence"][0]["analyst"], "Logistics and operations")
        # What is still uncertain is said: the unproven criterion and the analyst's gap.
        self.assertTrue(any("Unproven - Distinctiveness" in u for u in done["uncertainty"]), done["uncertainty"])
        self.assertTrue(any("No local survey" in u for u in done["uncertainty"]))
        # Each seat used its model; only the Analysts could search, each with its own brief.
        self.assertEqual([c["role"] for c in fake.calls if not c["role"].startswith("analysts")], ["grand_jury", "prosecution", "tribunal", "executioner"])
        self.assertEqual(sorted(c["role"] for c in fake.asked("analysts:logistics") + fake.asked("analysts:economics") + fake.asked("analysts:dependencies")),
                         ["analysts:dependencies", "analysts:economics", "analysts:logistics"])
        self.assertEqual({c["role"]: c["research"] for c in fake.calls}["analysts:economics"], True)
        self.assertFalse(any(c["research"] for c in fake.calls if not c["role"].startswith("analysts")))
        self.assertEqual(fake.asked("analysts:logistics")[0]["timeout"], 420.0)
        self.assertEqual(fake.asked("prosecution")[0]["model"], "opus")
        self.assertIn("never instructions to you", fake.asked("analysts:economics")[0]["system"])
        self.assertIn("Economics and market", fake.asked("analysts:economics")[0]["system"])
        self.assertTrue(all("<idea>\n" + IDEA in c["prompt"] for c in fake.calls))
        self.assertIn("Thin margins", fake.asked("analysts:logistics")[0]["prompt"], "the analysts test the charges too")
        # What was used is added up, per stage and in all, and counted like any other request.
        self.assertEqual(self.stage(done, "analysts")["usage"], {"input": 300, "output": 60, "cached": 15, "cost": 0.03, "searches": 9})
        self.assertEqual(done["usage"]["input"], 700)
        self.assertEqual(done["usage"]["searches"], 9)
        rows = usage.turns(self.cfg.state_dir, 1)
        self.assertTrue(rows and all(r["model"].endswith("(court)") for r in rows))
        self.assertEqual(sum(r["requests"] for r in rows), 7)
        self.assertEqual({r["model"] for r in rows}, {"sonnet (court)", "opus (court)", "haiku (court)"} if court.models(self.cfg)["tribunal"] == "opus" else
                         {"sonnet (court)", "opus (court)", "haiku (court)", court.models(self.cfg)["tribunal"] + " (court)"})

    def test_an_adverse_grand_jury_goes_straight_to_the_executioner(self):
        fake = FakeCourt(grand_jury={"decision": "adverse", "reason": "It contradicts itself: bread both free and sold.", "coherence": "No.",
                                     "viability": "No.", "assumptions": []})
        done = self.trial(fake)
        self.assertEqual([s["status"] for s in done["stages"]], ["done", "skipped", "skipped", "skipped", "done"])
        self.assertEqual(done["verdict"], "EXECUTED")
        self.assertEqual(done["verdict_reason"], "Grand Jury: It contradicts itself: bread both free and sold.")
        self.assertIn("It contradicts itself", done["pronouncement"], "the pronouncement said PASS, so the fixed words were used")
        self.assertEqual([c["role"] for c in fake.calls], ["grand_jury", "executioner"])
        self.assertEqual(done["status"], "closed")

    def test_a_fatal_charge_executes_but_serious_ones_do_not(self):
        fatal = FakeCourt(prosecution={"charges": [{"charge": "Thin margins", "severity": "serious", "detail": "x"},
                                                   {"charge": "Bread is free by law here", "severity": "fatal", "detail": "y"}],
                                       "survives": "It does not survive: the law makes the sale impossible."},
                          executioner={"pronouncement": "The verdict is EXECUTED. The law forbids the sale."})
        done = self.trial(fatal)
        self.assertEqual(self.stage(done, "prosecution")["decision"], "adverse")
        self.assertEqual(done["verdict"], "EXECUTED")
        self.assertIn("Prosecution: Fatal charge: Bread is free by law here.", done["verdict_reason"])
        self.assertEqual(done["pronouncement"], "The verdict is EXECUTED. The law forbids the sale.")
        self.assertEqual([s["status"] for s in done["stages"]][2:4], ["skipped", "skipped"])
        serious = FakeCourt(prosecution={"charges": [{"charge": "Thin margins", "severity": "serious", "detail": "x"}, {"charge": "Rain", "severity": "minor", "detail": "y"}],
                                         "survives": "It survives: every charge can be answered."})
        done = self.trial(serious)
        self.assertEqual((self.stage(done, "prosecution")["decision"], self.stage(done, "prosecution")["reason"]), ("advance", "It survives: every charge can be answered."))
        self.assertEqual(done["verdict"], "PASS")


class TestTheAnalysts(CourtCase):
    def test_two_analysts_who_say_it_does_not_hold_execute_it(self):
        done = self.trial(FakeCourt(analysts__logistics=analyst(holds=False), analysts__economics=analyst(holds=False)))
        self.assertEqual(self.stage(done, "analysts")["decision"], "adverse")
        self.assertEqual(done["verdict"], "EXECUTED")
        self.assertIn("does not hold in logistics and operations or economics and market", done["verdict_reason"])
        self.assertEqual(self.stage(done, "tribunal")["status"], "skipped")
        done = self.trial(FakeCourt(analysts__logistics=analyst(holds=False)))
        self.assertEqual(self.stage(done, "analysts")["decision"], "advance", "one is not enough")

    def test_a_decisive_blocker_executes_only_when_a_source_backs_it(self):
        law = {**SOURCE, "url": "https://example.org/law", "stance": "against", "claim": "Selling bread needs a licence that is no longer issued."}
        done = self.trial(FakeCourt(analysts__dependencies=analyst(decisive=True, sources=[law], blocker="No new bakery licences are issued.")))
        self.assertEqual(self.stage(done, "analysts")["decision"], "adverse")
        self.assertIn("Dependencies, law and feasibility analyst found a decisive real-world blocker: No new bakery licences", done["verdict_reason"])
        done = self.trial(FakeCourt(analysts__dependencies=analyst(decisive=True, sources=[], blocker="I believe licences are hard to get.")))
        self.assertEqual(self.stage(done, "analysts")["decision"], "advance", "a blocker nobody can point to does not execute")
        self.assertEqual(done["verdict"], "PASS")

    def test_a_research_outage_is_recorded_and_told_to_the_tribunal(self):
        fake = FakeCourt(searches={"analysts:economics": 0})
        done = self.trial(fake)
        found = {a["key"]: a for a in self.stage(done, "analysts")["body"]["analysts"]}
        self.assertEqual((found["economics"]["research"], found["logistics"]["research"]), ("unavailable", "ok"))
        self.assertEqual(found["economics"]["sources"], [], "a source that was never looked up is not kept")
        self.assertIn("reasoning without evidence", found["economics"]["note"])
        self.assertEqual(done["research"], "partial")
        self.assertEqual(len(done["evidence"]), 2)
        told = fake.asked("tribunal")[0]["prompt"]
        self.assertIn("RESEARCH: partial", told)
        self.assertIn("unavailable to the Economics and market analyst", told)
        self.assertEqual(done["verdict"], "PASS", "an outage does not stop the trial")
        self.assertTrue(any("Web research was unavailable" in u for u in done["uncertainty"]))
        nothing = FakeCourt(searches={"analysts:economics": 0, "analysts:logistics": 0, "analysts:dependencies": 0})
        done = self.trial(nothing)
        self.assertEqual((done["research"], done["evidence"]), ("unavailable", []))
        self.assertIn("RESEARCH: unavailable", nothing.asked("tribunal")[0]["prompt"])

    def test_a_source_that_is_not_a_web_address_is_dropped(self):
        bad = [SOURCE, {**SOURCE, "url": "file:///C:/Users/secret.txt"}, {**SOURCE, "url": "javascript:alert(1)"}, {**SOURCE, "url": "example.org/no-scheme"},
               {**SOURCE, "url": "http://example.org/ok", "date": "", "stance": "strongly against"}]
        done = self.trial(FakeCourt(analysts__logistics=analyst(sources=bad)))
        urls = [e["url"] for e in done["evidence"] if e["analyst"] == "Logistics and operations"]
        self.assertEqual(urls, ["https://example.org/bakery-prices", "http://example.org/ok"])
        kept = done["evidence"][1]
        self.assertEqual((kept["date"], kept["stance"]), ("undated", "mixed"))


class TestTheTribunalAndTheVerdict(CourtCase):
    def test_any_criterion_not_met_executes_and_unproven_ones_become_uncertainty(self):
        done = self.trial(FakeCourt(tribunal=tribunal(feasibility="not_met", evidence="unproven")))
        self.assertEqual(self.stage(done, "tribunal")["decision"], "adverse")
        self.assertEqual(done["verdict"], "EXECUTED")
        self.assertIn("Tribunal: Not met: Real-world feasibility", done["verdict_reason"])
        done = self.trial(FakeCourt(tribunal=tribunal(evidence="unproven", charges="unproven")))
        self.assertEqual(done["verdict"], "PASS")
        self.assertTrue(any("Quality of the evidence" in u for u in done["uncertainty"]))
        self.assertTrue(any("Answers to the prosecution's charges" in u for u in done["uncertainty"]))
        self.assertEqual(set(self.stage(done, "tribunal")["body"]["criteria"]), {k for k, _ in court.CRITERIA})

    def test_the_verdict_is_computed_by_code_whatever_the_executioner_says(self):
        liar = self.trial(FakeCourt(tribunal=tribunal(viability="not_met"), executioner={"pronouncement": "The verdict is PASS. A fine idea."}))
        self.assertEqual(liar["verdict"], "EXECUTED")
        self.assertTrue(liar["pronouncement"].startswith("The verdict is EXECUTED. Tribunal: Not met: Viability"))
        self.assertTrue(self.stage(liar, "executioner")["body"]["fixed_words"])
        for trouble in (OSError("no helper"), subprocess.TimeoutExpired("claude", 1), court.CourtError("Claude has reached its usage limit."), "not json at all"):
            fake = FakeCourt(executioner=trouble)
            done = self.trial(fake)
            self.assertEqual((done["verdict"], done["status"]), ("PASS", "closed"), repr(trouble))
            self.assertTrue(done["pronouncement"].startswith("The verdict is PASS."))
            self.assertEqual(len(fake.asked("executioner")), 1, "no second try for the Executioner's words")


class TestTriesAndResuming(CourtCase):
    def test_technical_failures_are_tried_twice_more_then_halt_and_resume_from_that_stage_only(self):
        broken = FakeCourt(prosecution=OSError("cannot start"))
        halted = self.trial(broken)
        ident = halted["id"]
        self.assertEqual(halted["status"], "halted")
        self.assertEqual(len(broken.asked("prosecution")), 3)
        case = self.stage(halted, "prosecution")
        self.assertEqual((case["status"], case["attempts"], case["decision"]), ("failed", 3, None))
        self.assertEqual(case["error"], "The helper could not be started.")
        self.assertIn("halted at the Prosecution", halted["now"])
        self.assertEqual([s["status"] for s in halted["stages"]], ["done", "failed", "pending", "pending", "pending"])
        with self.assertRaises(court.CourtError):
            court.run(self.cfg, ident, runner=FakeCourt())
        working = FakeCourt()
        court.resume(self.cfg, ident, start=False)
        done = court.run(self.cfg, ident, runner=working)
        self.assertEqual(done["verdict"], "PASS")
        self.assertEqual(working.asked("grand_jury"), [], "a decided stage is never asked again")
        self.assertEqual(len(working.asked("prosecution")), 1)
        self.assertEqual(self.stage(done, "prosecution")["attempts"], 4)
        self.assertEqual(len(working.calls), 6)

    def test_a_usage_limit_and_an_answer_in_the_wrong_form_are_technical_too(self):
        flaky = FakeCourt(grand_jury=lambda n, p: court.CourtError("Claude has reached its usage limit for now.") if n == 1 else
                          "I think it is a lovely idea!" if n == 2 else {"decision": "advance", "reason": "Testable."},
                          prosecution={"charges": [{"charge": "Rain", "severity": "catastrophic", "detail": "x"}], "survives": "No."})
        halted = self.trial(flaky)
        self.assertEqual(len(flaky.asked("grand_jury")), 3)
        self.assertEqual(self.stage(halted, "grand_jury")["decision"], "advance")
        self.assertEqual(len(flaky.asked("prosecution")), 3, "a severity that is not one of the three is not guessed at")
        self.assertEqual(self.stage(halted, "prosecution")["error"], "The answer was not in the form the court asked for.")

    def test_an_analyst_that_fails_is_the_only_one_asked_again_on_resume(self):
        broken = FakeCourt(analysts__economics=subprocess.TimeoutExpired("claude", 420))
        halted = self.trial(broken)
        self.assertEqual(halted["status"], "halted")
        self.assertEqual(len(broken.asked("analysts:economics")), 3)
        self.assertEqual(len(broken.asked("analysts:logistics")), 1)
        self.assertEqual(sorted(a["key"] for a in self.stage(halted, "analysts")["body"]["analysts"]), ["dependencies", "logistics"])
        self.assertIn("took too long", self.stage(halted, "analysts")["error"])
        working = FakeCourt()
        court.resume(self.cfg, halted["id"], start=False)
        done = court.run(self.cfg, halted["id"], runner=working)
        self.assertEqual([c["role"] for c in working.calls], ["analysts:economics", "tribunal", "executioner"])
        self.assertEqual(len(done["evidence"]), 3)
        self.assertEqual(done["verdict"], "PASS")

    def test_an_unfavourable_but_valid_answer_is_never_asked_again(self):
        fake = FakeCourt(grand_jury={"decision": "adverse", "reason": "Too vague to test."})
        done = self.trial(fake)
        self.assertEqual(len(fake.asked("grand_jury")), 1)
        for again in (lambda: court.resume(self.cfg, done["id"], runner=fake), lambda: court.run(self.cfg, done["id"], runner=fake),
                      lambda: court.submit(self.cfg, done["id"], IDEA + " Now with cake.", runner=fake)):
            with self.assertRaises(court.CourtError) as refused:
                again()
            self.assertIn("verdict stands", str(refused.exception))
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(court.get(self.cfg, done["id"])["verdict"], "EXECUTED")

    def test_a_trial_cut_off_by_a_restart_can_be_resumed(self):
        session = court.open_session(self.cfg)
        court.submit(self.cfg, session["id"], IDEA, start=False)
        with self.assertRaises(court.CourtError):
            court.resume(self.cfg, session["id"], runner=FakeCourt())
        path = self.cfg.state_dir / "court" / (session["id"] + ".json")
        saved = json.loads(path.read_text("utf-8"))
        saved["stages"][0].update(status="done", decision="advance", reason="Testable.", body={"assumptions": []})
        saved["stages"][1].update(status="running", started=time.time())          # what the file looks like if the app closed mid-stage
        path.write_text(json.dumps(saved), "utf-8")
        seen = court.get(self.cfg, session["id"])
        self.assertEqual(seen["status"], "halted")
        self.assertEqual(self.stage(seen, "prosecution")["status"], "failed")
        self.assertIn("interrupted at the Prosecution", seen["now"])
        fake = FakeCourt()
        court.resume(self.cfg, session["id"], start=False)
        done = court.run(self.cfg, session["id"], runner=fake)
        self.assertEqual(done["verdict"], "PASS")
        self.assertEqual(fake.asked("grand_jury"), [])

    def test_a_trial_cut_off_between_two_stages_can_be_resumed_too(self):
        # JARVIS was closed in the moment after one stage ended and before the next began: nothing is marked as running.
        session = court.open_session(self.cfg)
        court.submit(self.cfg, session["id"], IDEA, start=False)
        path = self.cfg.state_dir / "court" / (session["id"] + ".json")
        saved = json.loads(path.read_text("utf-8"))
        saved["stages"][0].update(status="done", decision="advance", reason="Testable.", body={"assumptions": []})
        path.write_text(json.dumps(saved), "utf-8")
        self.assertEqual(court.get(self.cfg, session["id"])["status"], "in_session", "just saved: it may be about to carry on")
        saved["saved"] = time.time() - court.STALE - 5
        path.write_text(json.dumps(saved), "utf-8")
        seen = court.get(self.cfg, session["id"])
        self.assertEqual(seen["status"], "halted")
        self.assertIn("interrupted at the Prosecution", seen["now"])
        fake = FakeCourt()
        court.resume(self.cfg, session["id"], start=False)
        done = court.run(self.cfg, session["id"], runner=fake)
        self.assertEqual(done["verdict"], "PASS")
        self.assertEqual(fake.asked("grand_jury"), [], "the stage already decided is never asked again")

    def test_resume_is_refused_unless_the_trial_is_halted(self):
        session = court.open_session(self.cfg)
        with self.assertRaises(court.CourtError) as early:
            court.resume(self.cfg, session["id"])
        self.assertIn("Only a halted trial", str(early.exception))
        with self.assertRaises(court.CourtError):
            court.run(self.cfg, session["id"], runner=FakeCourt())


class TestTheRecord(CourtCase):
    def test_ids_are_checked_before_they_reach_a_file_name(self):
        for bad in ("../../secrets", "court-20260101-120000-zzzz", "court-20260101-120000-abcd/../x", "", None, "court-20260101-120000-abcd.json"):
            with self.assertRaises(court.CourtError, msg=repr(bad)):
                court.get(self.cfg, bad)
        with self.assertRaises(court.CourtError) as missing:
            court.get(self.cfg, "court-20260101-120000-abcd")
        self.assertIn("no such session", str(missing.exception))
        self.assertRegex(court.open_session(self.cfg)["id"], r"^court-\d{8}-\d{6}-[0-9a-f]{4}$")

    def test_the_record_survives_being_read_back_from_disk(self):
        session = court.open_session(self.cfg)
        court.submit(self.cfg, session["id"], IDEA, runner=FakeCourt())          # the trial runs in the background, as in the app
        deadline = time.time() + 10
        while court.get(self.cfg, session["id"])["status"] != "closed" and time.time() < deadline:
            time.sleep(0.02)
        path = self.cfg.state_dir / "court" / (session["id"] + ".json")
        on_disk = json.loads(path.read_text("utf-8"))
        self.assertEqual(on_disk, court.get(self.cfg, session["id"]))
        self.assertEqual((on_disk["verdict"], on_disk["idea"], len(on_disk["stages"])), ("PASS", IDEA, 5))
        other = court.open_session(self.cfg)
        listed = court.listing(self.cfg)
        self.assertEqual({s["id"] for s in listed}, {session["id"], other["id"]})
        mine = next(s for s in listed if s["id"] == session["id"])
        self.assertEqual((mine["status"], mine["verdict"], mine["idea"]), ("closed", "PASS", IDEA[:120]))
        self.assertEqual(set(mine), {"id", "created", "status", "verdict", "idea", "now"}, "what a list needs, and not the whole record")
        self.assertEqual(mine["now"], on_disk["now"][:200])


class Done:
    def __init__(self, answer, stderr=""):
        self.stdout, self.stderr = json.dumps(answer) if isinstance(answer, dict) else answer, stderr


class TestTheHelper(CourtCase):
    def test_the_command_line_keeps_the_prompt_off_it_and_has_no_tools_unless_researching(self):
        started = []
        answer = {"result": '{"decision": "advance", "reason": "Testable."}', "is_error": False, "total_cost_usd": 0.02,
                  "usage": {"input_tokens": 50, "output_tokens": 30, "cache_read_input_tokens": 900, "server_tool_use": {"web_search_requests": 4}}}
        ask = court.claude_runner(self.cfg, exe="claude", process=lambda argv, **kw: started.append((argv, kw)) or Done(answer))
        got = ask("grand_jury", court.GRAND_JURY, "<idea>\nA secret plan for bread.\n</idea>", "sonnet", False, 240)
        self.assertEqual(got, {"text": '{"decision": "advance", "reason": "Testable."}', "model": "sonnet", "searches": 4,
                               "usage": {"input": 50, "output": 30, "cached": 900, "cost": 0.02}})
        argv, kw = started[0]
        self.assertEqual(argv[:4], ["claude", "-p", "--model", "sonnet"])
        self.assertEqual(kw["input"], "<idea>\nA secret plan for bread.\n</idea>")
        self.assertNotIn("secret plan", json.dumps(argv), "the prompt never goes on the command line")
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertNotIn("--allowedTools", argv)
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "")
        self.assertEqual(argv[argv.index("--mcp-config") + 1], '{"mcpServers":{}}')
        for flag in ("--strict-mcp-config", "--no-session-persistence", "--disable-slash-commands"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--system-prompt") + 1], court.GRAND_JURY)
        self.assertEqual((kw["timeout"], kw["encoding"], kw["errors"]), (240, "utf-8", "replace"))
        self.assertEqual(kw["cwd"], str(self.cfg.state_dir / "court"))
        self.assertNotIn("JCC_GROQ_API_KEY", kw["env"], "the helper's environment is scrubbed of secrets")
        if os.name == "nt":
            self.assertEqual(kw["creationflags"], subprocess.CREATE_NO_WINDOW)
        ask("analysts:economics", "brief", "question", "sonnet", True, 420)
        argv = started[1][0]
        self.assertEqual(argv[argv.index("--tools") + 1], "WebSearch")
        self.assertEqual(argv[argv.index("--allowedTools") + 1], "WebSearch")

    def test_the_record_names_the_model_that_really_answered(self):
        # The seat asks for "sonnet"; the helper reports which model answered. The record shows that, never a guess.
        answer = {"result": '{"decision": "advance", "reason": "Testable.", "assumptions": []}', "is_error": False, "usage": {},
                  "modelUsage": {"claude-haiku-5-5": {"outputTokens": 12}, "claude-sonnet-5-5": {"outputTokens": 340}}}
        ask = court.claude_runner(self.cfg, exe="claude", process=lambda argv, **kw: Done(answer))
        self.assertEqual(ask("grand_jury", court.GRAND_JURY, "question", "sonnet", False, 240)["model"], "claude-sonnet-5-5")
        # A run that searched has a small model in it too, which digests the pages found and writes more than the one
        # that answers. A real trial (14 Nov) named it as the one that answered. The model that was asked for is named.
        searched = {"modelUsage": {"claude-haiku-5-5": {"outputTokens": 5200, "webSearchRequests": 0}, "claude-sonnet-5-5": {"outputTokens": 1400, "webSearchRequests": 3}}}
        self.assertEqual(court.answered_by(searched, "sonnet"), "claude-sonnet-5-5")
        self.assertEqual(court.answered_by(searched, "claude-sonnet-5-5"), "claude-sonnet-5-5")
        self.assertEqual(court.answered_by(searched, "opus"), "claude-haiku-5-5", "the one asked for took no part: the one that wrote the most is named")
        self.assertEqual(court.answered_by({}, "sonnet"), "sonnet")
        self.assertEqual(court.answered_by({"modelUsage": {"a": "odd", 3: {}}}, "sonnet"), "sonnet")
        fake = FakeCourt()
        told = lambda role, *rest: {**fake(role, *rest), "model": "claude-test-model"}   # noqa: E731
        session = court.open_session(self.cfg)
        court.submit(self.cfg, session["id"], IDEA, start=False)
        done = court.run(self.cfg, session["id"], runner=told)
        self.assertEqual([stage["answered_by"] for stage in done["stages"]], ["claude-test-model"] * 5)
        self.assertEqual(self.stage(done, "grand_jury")["model"], "sonnet", "what the seat asked for is kept beside it")

    def test_searches_are_counted_wherever_the_helper_says_them(self):
        """A real trial (14 Nov) found every analyst's research "unavailable" and threw their sources away, although
        each had searched: Claude Code now gives the count for each model that took part and leaves the count for the
        whole run at 0. This is the shape that run came back in."""
        real = {"result": '{"holds": true}', "is_error": False, "num_turns": 3, "total_cost_usd": 0.03,
                "usage": {"input_tokens": 9, "output_tokens": 1967, "server_tool_use": {"web_search_requests": 0, "web_fetch_requests": 0}},
                "modelUsage": {"claude-haiku-5-5": {"outputTokens": 1967, "webSearchRequests": 2}}}
        self.assertEqual(court.searches_in(real), 2)
        ask = court.claude_runner(self.cfg, exe="claude", process=lambda argv, **kw: Done(real))
        self.assertEqual(ask("analysts:economics", "system", "question", "sonnet", True, 420)["searches"], 2)
        self.assertEqual(court.searches_in({"usage": {"server_tool_use": {"web_search_requests": 4}}}), 4, "the older place still counts")
        self.assertEqual(court.searches_in({"modelUsage": {"a": {"webSearchRequests": 2}, "b": {"webSearchRequests": 3}, "c": "odd", "d": {"webSearchRequests": "many"}}}), 5,
                         "two models that both searched")
        self.assertEqual(court.searches_in({"usage": {"server_tool_use": {"web_search_requests": 4}}, "modelUsage": {"a": {"webSearchRequests": 4}}}), 4,
                         "the same searches said in both places are not counted twice")
        for nothing in ({}, {"usage": None, "modelUsage": None}, {"usage": {"server_tool_use": {"web_search_requests": -3}}}, {"modelUsage": {"a": {"webSearchRequests": True}}}):
            self.assertEqual(court.searches_in(nothing), 0, nothing)
        # With the count right, an analyst that searched keeps its sources, and the research is recorded as done.
        searched = FakeCourt(searches={"analysts:logistics": 2, "analysts:economics": 1, "analysts:dependencies": 3})
        done = self.trial(searched)
        self.assertEqual(done["research"], "ok")
        self.assertEqual(len(done["evidence"]), 3)

    def test_trouble_from_the_helper_is_said_plainly(self):
        limit = court.claude_runner(self.cfg, exe="claude", process=lambda argv, **kw: Done({"result": "You've hit your 5-hour limit · resets 3:50am", "is_error": True}))
        with self.assertRaises(court.CourtError) as stopped:
            limit("tribunal", "x", "y", "opus", False, 240)
        self.assertIn("usage limit", str(stopped.exception))
        garbled = court.claude_runner(self.cfg, exe="claude", process=lambda argv, **kw: Done("not json", stderr="boom"))
        with self.assertRaises(court.CourtError) as unread:
            garbled("tribunal", "x", "y", "opus", False, 240)
        self.assertIn("could not be read", str(unread.exception))


if __name__ == "__main__":
    unittest.main()
