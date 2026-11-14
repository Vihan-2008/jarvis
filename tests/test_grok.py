"""Grok's command-line agent as a coding agent: how it is started, what it may do, and how its answer is read.

The shapes here are the real ones: two small runs of the real tool (15 Nov 2026) showed that it answers with one piece
of JSON, and that when it is refused something in a run with no window it stops, says "cancelled" and still exits 0.
"""
import json
import os
import sys
import time
from pathlib import Path

from jcc import agents, config, efficiency, live
from jcc.jobrunner import record, run_job
from jcc.vault import parse_frontmatter, Vault
from tests.helpers import EngineTestCase
from tests.test_projects import git, make_repo, overrides

FAKE = str(Path(__file__).with_name("fake_grok.py"))
ENDED = json.dumps({"text": "OK", "stopReason": "end_turn", "sessionId": "01a1d9b0-06ba-7d80-9130-690427176efe", "num_turns": 1,
                    "usage": {"input_tokens": 21830, "cache_read_input_tokens": 1664, "output_tokens": 29}, "modelUsage": {"grok-4.7-build": {"outputTokens": 29}}}, indent=2)
REFUSED = (json.dumps({"text": "I'll append the line, then create the file outside this folder.", "stopReason": "cancelled",
                       "sessionId": "01a1da6c-6557-7c02-93c5-758c94151a1c", "usage": {"input_tokens": 23715, "cache_read_input_tokens": 49152, "output_tokens": 1263}}, indent=2) +
           "\npermission required: Write `C:\\somewhere\\outside.txt` was not run, as a headless run cannot ask for approval\n")


class TestHowGrokIsStarted(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.load()
        self.grok = self.cfg.agents["grok"]
        self.work = Path("C:/work/job/repo") if os.name == "nt" else Path("/work/job/repo")
        self.perms = agents.claude_permissions(self.work, [self.work.parent / "real-project"], Path(sys.executable), [["-m", "unittest"]])

    def argv(self, **more):
        return agents.build_argv(self.grok, more.pop("level", "small"), "Do the task.", self.work, self.perms, **more)

    def test_it_is_one_of_the_agents_and_used_only_when_chosen(self):
        self.assertEqual((self.grok.enabled, self.grok.command), (False, ["grok"]), "off until its owner switches it on")
        for level, order in self.cfg.levels.items():
            self.assertNotIn("grok", order, "it is not among the first choices: its owner chooses it")
        self.assertEqual(agents.plan(self.cfg, "fix a typo", {}, prefer="grok").skipped.get("grok"), "disabled", "asked for while off, it is passed over")
        on = config.load({"agents": {"grok": {"enabled": True, "command": [sys.executable, FAKE]}}})
        self.assertEqual(agents.plan(on, "fix a typo", {}, prefer="grok").agents[0], "grok", "switched on and asked for, it goes first")
        self.assertEqual(agents.plan(on, "fix a typo", {}).agents[-1], "grok", "not asked for, it is the last resort")

    def test_it_gets_its_file_tools_in_the_jobs_folder_and_no_shell(self):
        argv = self.argv()
        self.assertEqual(argv[1], "-p")
        self.assertIn("You have no shell in this job", argv[2])
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "dontAsk", "nothing that is not allowed below is done, and nothing is asked")
        self.assertEqual(argv[argv.index("--disallowed-tools") + 1], "run_terminal_cmd")
        allowed = [argv[i + 1] for i, a in enumerate(argv) if a == "--allow"]
        self.assertEqual(allowed, ["Read(./**)", "Edit(./**)", "WebSearch"], "its own folder, and looking things up")
        self.assertEqual(argv[argv.index("--cwd") + 1], str(self.work))
        self.assertEqual(argv[argv.index("--output-format") + 1], "json")
        for never in ("--yolo", "--always-approve", "bypassPermissions", "acceptEdits"):
            self.assertNotIn(never, argv)
        self.assertFalse([a for a in allowed if a.startswith("Bash")], "no command is allowed: the project's checks are run by JARVIS itself")

    def test_what_a_claude_job_is_denied_by_path_is_denied_to_grok_too(self):
        denied = [self.argv()[i + 1] for i, a in enumerate(self.argv()) if a == "--deny"]
        for rule in ("Read(**/.env)", "Edit(**/.env)", "Read(~/.ssh/**)", "Edit(~/.ssh/**)"):
            self.assertIn(rule, denied)
        project = Path(os.path.abspath(self.work.parent / "real-project")).as_posix()
        self.assertIn(f"Read({project}/**)", denied, "the project's real folder (the job works in a copy)")
        self.assertIn(f"Edit({project}/**)", denied)
        self.assertFalse([rule for rule in denied if rule.startswith(("Read(//", "Edit(//"))], "Grok reads C:/ paths, not //c/ ones")
        self.assertEqual(agents.grok_rules(None)["allow"], ["Read(./**)", "Edit(./**)", "WebSearch"])

    def test_the_model_the_effort_and_carrying_on_a_session(self):
        self.assertNotIn("-m", self.argv(), "no model named: the tool's own default")
        named = config.load({"agents": {"grok": {"enabled": True, "command": "grok", "models": {"small": "grok-4.7"}}}}).agents["grok"]
        chosen = agents.build_argv(named, "small", "Do the task.", self.work, self.perms)
        self.assertEqual(chosen[chosen.index("-m") + 1], "grok-4.7")
        self.assertNotIn("--effort", self.argv())
        self.assertEqual(self.argv(effort="ultra")[self.argv(effort="ultra").index("--effort") + 1], "max")
        carried = self.argv(session_id="01a1d9b0-06ba-7d80-9130-690427176efe")
        self.assertEqual(carried[carried.index("-r") + 1], "01a1d9b0-06ba-7d80-9130-690427176efe")
        self.assertNotIn("-r", self.argv())


class TestItsModelsInTheList(EngineTestCase):
    def test_grok_models_are_offered_only_when_it_is_switched_on(self):
        from jcc import models
        home = self.tmp / "grok-home"
        home.mkdir()
        (home / "models_cache.json").write_text(json.dumps({"models": {"grok-4.7": {"info": {"name": "Grok 4.7"}}, "bad id!": {}, "grok-4.6": "odd"}}), "utf-8")
        os.environ["GROK_HOME"] = str(home)
        try:
            self.assertEqual([m for m in models.catalog(config.load()) if m["provider"] == "grok"], [], "off: none of its models are offered")
            on = config.load({"agents": {"grok": {"enabled": True, "command": "grok"}}})
            offered = [(m["id"], m["label"]) for m in models.catalog(on) if m["provider"] == "grok"]
            self.assertEqual(offered, [("grok:grok-4.7", "Grok 4.7"), ("grok:grok-4.6", "grok-4.6")])
            self.assertEqual(models.validate(on, "grok:grok-4.7")["model"], "grok-4.7")
            with self.assertRaises(ValueError):
                models.validate(config.load(), "grok:grok-4.7")
        finally:
            os.environ.pop("GROK_HOME", None)


class TestHowItsAnswerIsRead(EngineTestCase):
    def test_a_finished_run_gives_its_words_its_session_and_what_it_used(self):
        code, out, said = agents.grok_outcome(0, ENDED)
        self.assertEqual((code, said), (0, "OK"))
        self.assertEqual(efficiency.metadata(out, "grok"), {"session_id": "01a1d9b0-06ba-7d80-9130-690427176efe", "input_tokens": 21830, "cached_tokens": 1664, "output_tokens": 29})

    def test_a_run_that_was_refused_something_is_not_a_finished_job(self):
        """The real tool exits with 0 here. Taken at its word, a job that stopped half-way would have gone on to be checked and merged."""
        code, out, said = agents.grok_outcome(0, REFUSED)
        self.assertEqual(code, 1)
        self.assertIn("Grok stopped before it had finished (cancelled)", out)
        self.assertIn("a headless run cannot ask for approval", out, "with Grok's own reason")
        self.assertTrue(said.startswith("I'll append the line"))
        self.assertEqual(efficiency.metadata(out, "grok")["session_id"], "01a1da6c-6557-7c02-93c5-758c94151a1c")

    def test_anything_else_is_left_as_it_is(self):
        for odd in ("", "no json here", '{"not": "grok"}', "{broken", '["a list"]'):
            self.assertEqual(agents.grok_outcome(3, odd), (3, odd, ""), odd)
        self.assertEqual(agents.grok_outcome(2, ENDED)[0], 2, "a failure the tool itself reported stays one")


class TestAWholeJobWithGrok(EngineTestCase):
    """A real job in a small temporary project, with a stand-in for the Grok tool (tests/fake_grok.py)."""

    def setUp(self):
        super().setUp()
        self.repo = make_repo(self.tmp)
        settings = overrides(self.repo, levels=("grok", "codex"))
        settings["agents"]["grok"] = {"enabled": True, "command": [sys.executable, FAKE], "models": {"small": "", "medium": "", "large": ""}}
        self.cfg = config.load(settings)
        self.rid = time.strftime("%Y%m%d-%H%M%S-") + os.urandom(2).hex()
        self.work = self.cfg.jobs_root / self.rid
        self.work.mkdir(parents=True)
        self.spec = {"id": self.rid, "kind": "job", "task": "add a line to the package", "project": "trading", "prefer": "grok",
                     "level": "small", "vault": str(self.vault), "timeout_minutes": 2}

    def tearDown(self):
        for name in ("FAKE_GROK_MODE", "FAKEAGENT_MODE_CODEX", "FAKEAGENT_MODE_CLAUDE"):
            os.environ.pop(name, None)
        super().tearDown()

    def run_it(self, mode):
        os.environ["FAKE_GROK_MODE"] = mode
        res = run_job(self.cfg, self.spec, self.work)
        record(self.cfg, self.spec, self.work, res, 1.0)
        return res

    def test_its_change_is_checked_and_merged_like_any_other_agents(self):
        res = self.run_it("ok")
        self.assertEqual((res.status, res.agent), ("done", "grok"))
        self.assertIn("added_by_grok", git("show", "master:src/pkg/__init__.py", cwd=self.repo), "merged after the project's own checks passed")
        started = json.loads((self.work / "grok-argv.json").read_text("utf-8"))
        self.assertIn("run_terminal_cmd", started)
        self.assertEqual(started[started.index("--cwd") + 1], str(self.work / "repo"), "it works in the job's own copy")
        attempt = json.loads((self.work / "attempts.json").read_text("utf-8"))[-1]
        self.assertEqual((attempt["agent"], attempt["exit"], attempt["session_id"], attempt["output_tokens"]), ("grok", 0, "01a1d9b0-06ba-7d80-9130-690427176efe", 29))
        self.assertEqual(live.read(self.cfg, self.rid)["text"], "I added the line.", "what it said at the end is shown")
        note = parse_frontmatter(Vault(self.cfg.vault).read(f"Jobs/{self.rid}.md"))[0]
        self.assertEqual((note["status"], note["agent"]), ("done", "grok"))

    def test_a_run_that_was_refused_something_is_not_taken_for_finished_and_the_next_agent_is_tried(self):
        os.environ["FAKEAGENT_MODE_CODEX"] = os.environ["FAKEAGENT_MODE_CLAUDE"] = "crash"       # (the other agents cannot do it either)
        res = self.run_it("refused")
        self.assertNotEqual(res.status, "done", "nobody finished the job, so nothing is merged")
        self.assertNotIn("added_by_grok", git("show", "master:src/pkg/__init__.py", cwd=self.repo), "what Grok had half done is not in the project")
        tried = [(a["agent"], a["exit"]) for a in json.loads((self.work / "attempts.json").read_text("utf-8"))]
        self.assertEqual(tried[0], ("grok", 1), "Grok's own exit code was 0: its word 'cancelled' is what counts")
        self.assertGreater(len(tried), 1, "the next agent was tried, as after any agent that could not finish")

    def tearDown_modes(self):
        for name in ("FAKE_GROK_MODE", "FAKEAGENT_MODE_CODEX", "FAKEAGENT_MODE_CLAUDE"):
            os.environ.pop(name, None)

if __name__ == "__main__":
    import unittest
    unittest.main()
