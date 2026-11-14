"""Ultracode: work that has to be right. The strongest AI, thinking as hard as it can, planned as a large job, and
looked at again by a second AI whatever the review setting says."""
import json
from dataclasses import replace

from jcc import config, delivery, learning, models, voice_tools
from jcc.jobrunner import record, run_job
from jcc.jobs import JobLauncher
from jcc.vault import Vault, atomic_write
from tests.helpers import EngineTestCase
from tests.test_gui import GuiTestCase
from tests.test_projects import make_repo, overrides

FULL = ["low", "medium", "high", "xhigh", "max"]


def after(argv, flag):
    return argv[argv.index(flag) + 1]


class UltracodeTests(EngineTestCase):
    def run_job(self, effort="ultra", other=True, named=False):
        """One coding job by Claude, with reviews switched off in the settings. Returns (result, every command line started)."""
        repo = make_repo(self.tmp)
        cfg = config.load(overrides(repo, levels=("claude", "codex")))
        if named:
            cfg.agents["claude"] = replace(cfg.agents["claude"], models={"small": "haiku", "medium": "sonnet", "large": "opus"})
        if not other:
            cfg.agents["codex"] = replace(cfg.agents["codex"], enabled=False)
        delivery.configure(cfg, {**delivery.DEFAULTS, "review_enabled": False})
        rid = "20261112-010000-abcd"
        work = cfg.jobs_root / rid
        work.mkdir(parents=True)
        task = "Add a helper. Preserve existing behavior."
        items = delivery.criteria(task)
        spec = {"id": rid, "task": task, "kind": "job", "level": "large", "vault": str(self.vault), "project": "trading", "delivery_version": 1,
                "acceptance": items, "max_attempts": 4, "effort": effort, "manual_model": "auto"}
        calls = []

        def runner(argv, cwd, env, seconds):
            calls.append(argv)
            if any(str(a).startswith("Review only the supplied") for a in argv):
                return 0, json.dumps({"status": "clear", "findings": []})
            (cwd / "src/pkg/__init__.py").write_text("VALUE = 1\n# helper\n")
            (cwd / delivery.report_name(rid)).write_text(json.dumps({"items": [
                {"id": i["id"], "status": "met", "evidence": "src/pkg/__init__.py and tests/test_value.py"} for i in items]}))
            return 0, "Implementation complete"
        result = run_job(cfg, spec, work, runner)
        record(cfg, spec, work, result, 1)
        return result, calls

    def test_the_strongest_model_thinks_as_hard_as_it_can_and_another_ai_checks_the_result(self):
        result, calls = self.run_job()
        self.assertEqual(result.status, "done", result.merge_note)
        self.assertEqual(len(calls), 2, "the work, then the second opinion, though reviews are switched off in the settings")
        self.assertEqual((after(calls[0], "--model"), after(calls[0], "--effort")), ("opus", "max"))
        self.assertIn("Task", after(calls[0], "--tools"), "a large job: it may send helpers to search widely")
        review = result.attempts[-1]
        self.assertEqual((review["kind"], review["agent"]), ("review", "codex"))
        self.assertNotIn("ultra", calls[0], "no agent is ever handed a level it does not know")

    def test_an_ordinary_job_is_left_as_it_was(self):
        result, calls = self.run_job(effort="auto")
        self.assertEqual((result.status, len(calls)), ("done", 1))
        self.assertNotIn("opus", calls[0])

    def test_with_no_other_ai_free_the_one_that_did_the_work_looks_again_with_another_model(self):
        result, calls = self.run_job(other=False, named=True)
        self.assertEqual(result.status, "done", result.merge_note)
        self.assertEqual(len(calls), 2)
        self.assertEqual(after(calls[0], "--model"), "opus")
        review = result.attempts[-1]
        self.assertEqual((review["kind"], review["agent"]), ("review", "claude"))
        self.assertEqual(after(calls[1], "--model"), "sonnet", "not the model that wrote it")
        self.assertIn("--disallowedTools", calls[1])

    def test_ultra_means_the_hardest_level_each_model_has(self):
        cfg = config.load()
        spec = {"effort": "ultra", "level": "large", "task": "Add a helper", "kind": "job"}
        self.assertEqual(learning.effort_for(cfg, spec, "claude", "opus", [], FULL)[0], "max")
        self.assertEqual(learning.effort_for(cfg, spec, "codex", "gpt", [], ["low", "medium", "high"])[0], "high")
        self.assertEqual(learning.effort_for(cfg, spec, "claude", "haiku", [], [])[0], "auto", "a model with no levels just runs")

    def test_ultra_goes_with_any_model_and_the_strongest_one_is_known(self):
        cfg = config.load()
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        self.assertEqual(models.validate(cfg, "claude:haiku", "ultra")["model"], "haiku")
        self.assertIsNone(models.validate(cfg, "auto", "ultra"))
        with self.assertRaises(ValueError):
            models.validate(cfg, "claude:haiku", "max")
        with self.assertRaises(ValueError):
            models.validate(cfg, "auto", "everything")
        self.assertEqual(models.strongest(cfg), "opus")
        atomic_write(cfg.state_dir / "quota-claude.json", json.dumps({"models": [
            {"value": "default", "displayName": "Default"}, {"value": "opus", "displayName": "Opus"}, {"value": "fable", "displayName": "Fable 5.2"},
            {"value": "claude-fable-5-1", "displayName": "Fable 5.1"}]}))
        self.assertEqual(models.strongest(cfg), "fable")
        listed = {m["model"]: m for m in models.catalog(cfg)}
        self.assertEqual(listed["fable"]["efforts"], FULL, "the newest strongest model takes every level")
        self.assertEqual(listed["claude-fable-5-1"]["efforts"], ["low", "medium", "high"], "an older one is not assumed to")

    def test_an_ultracode_job_is_planned_as_a_large_one_however_small_it_sounds(self):
        cfg = config.load(overrides(make_repo(self.tmp)))
        started = []
        launcher = JobLauncher(cfg, Vault(cfg.vault), spawner=lambda *a: started.append(a))
        for rid, effort, level in (("20261112-020000-abcd", "auto", "small"), ("20261112-020001-abcd", "ultra", "large")):
            outcome = launcher.launch(rid, "chat", "Write a small helper function that greets", "none", effort=effort)
            self.assertEqual(outcome.status, "running", outcome.message)
            spec = json.loads((cfg.jobs_root / rid / "job.json").read_text("utf-8"))
            self.assertEqual((spec["level"], spec["effort"]), (level, effort))


class TestByVoice(GuiTestCase):
    def test_asking_for_ultracode_by_voice_starts_the_job_that_way(self):
        made = self.state.perform("create_project", {"name": "Bakery site", "kind": "web"}, None)
        sent = []

        def send_chat(cid, text, **kw):
            sent.append(kw)
            return {"messages": [{"status": "running"}]}
        self.state.send_chat = send_chat
        self.state.perform("build_with_coding_agents", {"project": made["key"], "task": "Add an opening hours page"}, None)
        self.state.perform("build_with_coding_agents", {"project": made["key"], "task": "Add an opening hours page", "ultra": True}, None)
        self.state.perform("build_with_coding_agents", {"project": made["key"], "task": "Add an opening hours page", "ultra": "yes"}, None)
        self.assertEqual([kw["effort"] for kw in sent], ["auto", "ultra", "auto"], "only a plain true switches it on")

    def test_the_tool_passes_the_wish_on_only_when_it_was_made(self):
        asked = []

        def service(op, payload):
            asked.append((op, payload))
            return {"ok": True, "permit": "p1"} if op == "gate" else {"message": "Started."}
        box = voice_tools.Toolbox(service=service)
        box.build_with_coding_agents("bakery", "Add a page")
        box.build_with_coding_agents("bakery", "Add a page", ultra=True)
        self.assertEqual([payload["args"] for op, payload in asked if op == "gate"],
                         [{"project": "bakery", "task": "Add a page"}, {"project": "bakery", "task": "Add a page", "ultra": True}])
