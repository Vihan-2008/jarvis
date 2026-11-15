import io
import json
import os
import time
import unittest
import zipfile
from pathlib import Path

from jcc import config, history, workspace, projects, receipts, watcher
from jcc.chats import Chats
from jcc.jobrunner import run_job
from jcc.usage import Usage
from tests.helpers import EngineTestCase
from tests.test_projects import make_repo, overrides
from tests.test_gui import GuiTestCase


class WorkspaceTests(EngineTestCase):
    def cfg(self):
        return config.load({"paths": {"projects_root": str(self.tmp / "managed")}})

    def test_new_projects_persist_and_checks_pass(self):
        cfg = self.cfg()
        for kind in ("any", "python", "web", "node"):
            created = workspace.create(cfg, "New " + kind, kind)
            p = cfg.projects[created["key"]]
            self.assertEqual(projects.git(["branch", "--show-current"], p.path).strip(), "main")
            self.assertTrue(all(c.ok for c in projects.run_checks(p, p.path, dict(os.environ))))
            self.assertIn(created["key"], config.load().projects)
            self.assertTrue((self.vault / f"Projects/{created['key']}/Memory.md").exists())
        anything = cfg.projects["new-any"]
        self.assertEqual(anything.checks, [["check.py"]], "a project of any kind is checked by its own check.py")
        self.assertIn("whatever language", (anything.path / "AGENTS.md").read_text("utf-8"))
        self.assertEqual(workspace.create(cfg, "Made by default")["kind"], "any", "the usual kind: anything")
        with self.assertRaises(ValueError):
            workspace.create(cfg, "New python")
        with self.assertRaises(ValueError):
            workspace.create(cfg, "../../")

    def test_a_deleted_projects_name_can_be_used_again(self):
        cfg = self.cfg()
        first = workspace.create(cfg, "WII-Latest")
        (cfg.projects[first["key"]].path / "notes.txt").write_text("the old one", "utf-8")
        workspace.remove(cfg, first["key"])                            # (its folder is left where it was)
        again = workspace.create(cfg, "WII-Latest")
        self.assertEqual(again["key"], first["key"], "the same name")
        fresh = cfg.projects[again["key"]].path
        self.assertNotEqual(fresh, Path(first["path"]), "in a folder of its own")
        self.assertFalse((fresh / "notes.txt").exists(), "nothing of the old project is reused")
        self.assertTrue((Path(first["path"]) / "notes.txt").exists(), "and nothing of it is written over")
        with self.assertRaisesRegex(ValueError, "already exists"):
            workspace.create(cfg, "wii latest")                         # (a project that is there still keeps its name)

    def test_chat_roundtrip_and_bounded_context(self):
        cfg = self.cfg()
        c = Chats(cfg).create("New chat")
        store = Chats(cfg)
        for i in range(12):
            store.update(c["id"], message={"role": "user", "content": "turn " + str(i), "receipt": str(i)})
        restored = Chats(cfg).get(c["id"])
        self.assertEqual(len(restored["messages"]), 12)
        context = store.context(c["id"], until="5")
        self.assertIn("turn 4", context)
        self.assertNotIn("turn 5", context)
        self.assertNotIn("turn 11", context)
        store.update(c["id"], message={"role": "assistant", "content": "finished", "receipt": "x", "status": "done"})
        store.update(c["id"], message={"role": "assistant", "content": "started", "receipt": "x", "status": "running"})
        self.assertEqual(store.get(c["id"])["messages"][-1]["content"], "finished")
        with self.assertRaises(ValueError):
            store.get("../../secrets")

    def test_private_memory_is_never_released(self):
        cfg = self.cfg()
        self.note("Private/secret.md", "never send this")
        with self.assertRaises(PermissionError):
            workspace.memory(cfg, None, "read [[Private/secret]]")

    def test_redaction_does_not_corrupt_chat_json(self):
        cfg = self.cfg()
        store = Chats(cfg)
        c = store.create()
        store.update(c["id"], message={"role": "user", "content": 'password: hunter22 and token="example-secret"'})
        saved = store.get(c["id"])
        self.assertIsInstance(saved["messages"], list)
        self.assertNotIn("hunter22", saved["messages"][0]["content"])

    def test_claude_and_chatgpt_exports_import_idempotently(self):
        cfg = self.cfg()
        claude = [{"uuid": "one", "name": "My Claude chat", "chat_messages": [
            {"sender": "human", "text": "Hello"}, {"sender": "assistant", "text": "Hi"}]}]
        chatgpt = [{"id": "two", "title": "GPT chat", "mapping": {"a": {"message": {
            "author": {"role": "user"}, "content": {"parts": ["my question"]}}}}}]
        for data in (claude, chatgpt):
            self.assertEqual(history.import_data(cfg, json.dumps(data).encode(), "history.json")["conversations"], 1)
            history.import_data(cfg, json.dumps(data).encode(), "history.json")
        paths = [p for p in (self.vault / "Conversations/Imported").rglob("*.md") if p.name != "Index.md"]
        self.assertEqual(len(paths), 2)
        self.assertIn("my question", "\n".join(p.read_text("utf-8") for p in paths))

    def test_zip_slip_is_not_extracted(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("../../outside.json", json.dumps({"uuid": "safe", "chat_messages": []}))
        history.import_data(self.cfg(), buf.getvalue(), "export.zip")
        self.assertFalse((self.tmp / "outside.json").exists())

    def test_capture_keeps_complete_version_and_validates_source(self):
        cfg = self.cfg()
        data = {"source": "Claude", "url": "https://claude.ai/chat/abc", "title": "Captured",
                "messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]}
        self.assertTrue(history.capture(cfg, data)["saved"])
        data["messages"] = data["messages"][:1]
        self.assertFalse(history.capture(cfg, data)["saved"])
        data["url"] = "https://evil.example/chat/abc"
        with self.assertRaises(ValueError):
            history.capture(cfg, data)

    def test_fresh_allowance_reading_changes_automatic_agent_selection(self):
        from jcc import agents, quota
        from unittest.mock import patch
        cfg = self.cfg()
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        reading = {"at": time.time(), "windows": [{"name": "five hour", "remaining_percent": 0,
                                                  "reset_at": time.time() + 1000}]}
        (cfg.state_dir / "quota-claude.json").write_text(json.dumps(reading), "utf-8")
        with patch.object(agents, "available", return_value=True):
            plan = agents.plan(cfg, "redesign the architecture", {})
        self.assertEqual(plan.agents, ["codex"])
        self.assertIn("0%", plan.skipped["claude"])
        reading["at"] = time.time() - 1000
        (cfg.state_dir / "quota-claude.json").write_text(json.dumps(reading), "utf-8")
        self.assertIsNone(quota.blocked(cfg, "claude"))

    def test_local_transcripts_capture_dialogue_not_hidden_reasoning(self):
        from jcc.local_history import sync
        cfg = self.cfg()
        logs = self.tmp / "logs"
        logs.mkdir()
        path = logs / "example.jsonl"
        rows = [
            {"type": "response_item", "payload": {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "private system instruction"}]}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "my coding question"}]}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "channel": "analysis", "content": [{"type": "output_text", "text": "hidden reasoning"}]}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "channel": "final", "content": [{"type": "output_text", "text": "the visible answer"}]}}]
        path.write_text("\n".join(map(json.dumps, rows)), "utf-8")
        result = sync(cfg, [("Codex local", logs)])
        self.assertEqual(result["updated_conversations"], 1)
        c = Chats(cfg).list()[0]
        messages = Chats(cfg).get(c["id"])["messages"]
        self.assertEqual(len(messages), 2)
        self.assertNotIn("hidden reasoning", str(messages))
        self.assertNotIn("private system instruction", str(messages))
        self.assertEqual(sync(cfg, [("Codex local", logs)])["updated_conversations"], 0)


class ContinuationTests(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.repo = make_repo(self.tmp)

    def test_model_limit_preserves_edits_and_hands_off(self):
        raw = overrides(self.repo)
        raw["agents"]["codex"]["models"] = {"small": "fast", "medium": "normal", "large": "deep"}
        cfg = config.load(raw)
        rid = receipts.new_id()
        work = cfg.jobs_root / rid
        work.mkdir(parents=True)
        calls = []
        def runner(argv, cwd, env, seconds):
            calls.append(argv)
            file = cwd / "src/pkg/__init__.py"
            if len(calls) == 1:
                file.write_text("VALUE = 1\n# preserved partial work\n", "utf-8")
                return 1, "maximum context length exceeded for this model"
            self.assertIn("preserved partial work", file.read_text("utf-8"))
            self.assertIn("Changed files (preserved)", argv[-1])
            return 0, "finished with the existing edits"
        spec = {"id": rid, "task": "fix typo", "kind": "job", "project": "trading", "level": "small",
                "vault": str(self.vault), "timeout_minutes": 1}
        result = run_job(cfg, spec, work, runner)
        self.assertEqual(result.status, "done", result.log)
        self.assertEqual([a["model"] for a in result.attempts], ["fast", "normal"])
        self.assertTrue((work / "HANDOFF.md").exists())
        self.assertIn("preserved partial work", projects.git(["show", "master:src/pkg/__init__.py"], self.repo))

    def test_provider_quota_switches_without_trying_all_its_models(self):
        raw = overrides(self.repo)
        raw["agents"]["codex"]["models"] = {"small": "a", "medium": "b", "large": "c"}
        cfg = config.load(raw)
        rid = receipts.new_id()
        work = cfg.jobs_root / rid
        work.mkdir(parents=True)
        calls = []
        def runner(argv, cwd, env, seconds):
            calls.append(argv)
            if len(calls) == 1:
                (cwd / "src/pkg/__init__.py").write_text("VALUE = 1\n# first agent\n", "utf-8")
                return 1, "You have hit your usage limit"
            self.assertIn("first agent", (cwd / "src/pkg/__init__.py").read_text("utf-8"))
            return 0, "continued"
        spec = {"id": rid, "task": "fix", "kind": "job", "project": "trading", "level": "small", "vault": str(self.vault)}
        result = run_job(cfg, spec, work, runner)
        self.assertEqual([a["agent"] for a in result.attempts], ["codex", "claude"])
        self.assertEqual(result.status, "done")

    def test_running_project_serializes_the_next_job(self):
        e = self.make_engine(overrides(self.repo))
        one = e.process("fix the trading bot parser")
        two = e.process("fix the trading bot dashboard")
        self.assertEqual(one.status, "running")
        self.assertEqual(two.status, "queued")
        self.assertEqual(len(self.spawned), 1)

    def test_partial_work_survives_all_limits_and_a_later_retry(self):
        cfg = config.load(overrides(self.repo))
        rid = receipts.new_id()
        work = cfg.jobs_root / rid
        work.mkdir(parents=True)
        spec = {"id": rid, "task": "fix", "kind": "job", "project": "trading", "level": "small", "vault": str(self.vault)}
        def limited(argv, cwd, env, seconds):
            (cwd / "src/pkg/__init__.py").write_text("VALUE = 1\n# saved across a quota wait\n", "utf-8")
            return 1, "usage limit reached"
        result = run_job(cfg, spec, work, limited)
        self.assertEqual(result.status, "queued")
        self.assertTrue((work / "repo").exists())
        usage = Usage(cfg.state_dir, cfg.caps)
        for name in ("codex", "claude"):
            usage.set_cooldown(name, 0)
        usage.close()
        def resume(argv, cwd, env, seconds):
            self.assertIn("saved across a quota wait", (cwd / "src/pkg/__init__.py").read_text("utf-8"))
            return 0, "completed"
        result = run_job(cfg, spec, work, resume)
        self.assertEqual(result.status, "done")
        self.assertTrue(result.merged)

    def test_failed_checks_trigger_a_repair_attempt(self):
        raw = overrides(self.repo)
        raw["agents"]["codex"]["models"] = {"small": "fast", "medium": "normal", "large": "deep"}
        cfg = config.load(raw)
        rid = receipts.new_id()
        work = cfg.jobs_root / rid
        work.mkdir(parents=True)
        calls = []
        def runner(argv, cwd, env, seconds):
            calls.append(argv)
            (cwd / "src/pkg/__init__.py").write_text("VALUE = 2\n" if len(calls) == 1 else "VALUE = 1\n# repaired\n", "utf-8")
            return 0, "edited"
        spec = {"id": rid, "task": "fix", "kind": "job", "project": "trading", "level": "small", "vault": str(self.vault)}
        result = run_job(cfg, spec, work, runner)
        self.assertEqual(result.status, "done")
        self.assertEqual(len(result.attempts), 2)
        self.assertTrue(result.attempts[0]["checks_failed"])
        self.assertTrue(result.merged)


class WorkspaceApiTests(GuiTestCase):
    def test_create_chat_and_followup_use_history(self):
        status, c = self.req("POST", "/api/chats", {"title": "Remember this"})
        self.assertEqual(status, 200)
        status, c = self.req("POST", "/api/chat/send", {"id": c["id"], "text": "what is gravity", "mode": "chat"})
        self.assertEqual(status, 200)
        self.assertEqual(len(c["messages"]), 2)
        status, again = self.req("POST", "/api/chat/send", {"id": c["id"], "text": "explain more", "mode": "chat"})
        self.assertEqual(len(again["messages"]), 4)
        self.assertEqual(len(self.spawned), 2)  # several requests at once: the follow-up does not wait for the first answer
        note = (self.vault / "Jobs" / (again["messages"][-1]["receipt"] + ".md")).read_text("utf-8")
        self.assertIn("what is gravity", note)
        self.assertEqual(self.transport.calls, [])  # native Claude/GPT chat, not the old free API tier

    def test_pairing_requires_current_gui_token(self):
        self.assertEqual(self.req("GET", "/api/sync/pairing", token=False)[0], 401)
        status, d = self.req("GET", "/api/sync/pairing")
        self.assertEqual(status, 200)
        self.assertGreater(len(d["code"]), 30)
        status, d = self.req("POST", "/api/capture", {"source": "Claude"})
        self.assertEqual(status, 403)

    def test_new_chat_rejects_unknown_project(self):
        self.assertEqual(self.req("POST", "/api/chats", {"project": "missing"})[0], 400)


if __name__ == "__main__":
    unittest.main()
