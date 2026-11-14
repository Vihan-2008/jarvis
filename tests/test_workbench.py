import os
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from jcc import config, models, agents
from jcc.workbench import Workbench
from tests.helpers import EngineTestCase
from tests.test_gui import GuiTestCase
from tests.test_projects import make_repo, overrides


class WorkbenchTests(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.repo = make_repo(self.tmp)
        self.cfg = config.load(overrides(self.repo))
        self.bench = Workbench(self.cfg)

    def test_project_files_are_scoped_and_secrets_excluded(self):
        self.assertIn("VALUE = 1", self.bench.files("trading", "src/pkg/__init__.py")["text"])
        self.assertTrue(self.bench.files("trading")["entries"])
        for path in ("../outside", ".git/config", ".env", "deploy/server.json"):
            with self.assertRaises(ValueError):
                self.bench.files("trading", path)

    def test_shared_page_is_explicit_context_and_saved_in_vault(self):
        self.bench.share_page({"url": "https://example.com/article", "title": "Page", "text": "reference text"})
        self.assertEqual(self.bench.attachment_context([], False, []), "")
        self.assertIn("reference text", self.bench.attachment_context([], True, []))
        self.assertEqual(len(list((self.vault / "Research/Browser").glob("*.md"))), 1)
        with self.assertRaises(ValueError):
            self.bench.share_page({"url": "file:///secret", "text": "no"})

    def test_manual_model_and_effort_reach_argv(self):
        a = config.AgentCfg("codex", True, ["codex"], {"small": "gpt-6.1-sol"})
        argv = agents.build_argv(a, "small", "do a task", self.tmp, effort="xhigh")
        self.assertIn("gpt-6.1-sol", argv)
        self.assertIn("model_reasoning_effort=xhigh", argv)
        c = config.AgentCfg("claude", True, ["claude"], {"large": "opus"})
        argv = agents.build_argv(c, "large", "do a task", self.tmp, effort="max")
        self.assertEqual(argv[argv.index("--effort") + 1], "max")
        self.assertNotIn("--tools", argv, "unless told, a job keeps every built-in tool")

    def test_a_job_is_given_only_the_tools_it_can_use(self):
        self.assertEqual(agents.claude_tools("job", "small", shell=True), "Read,Edit,Write,Glob,Grep,Bash,WebSearch,WebFetch")
        self.assertEqual(agents.claude_tools("chat", "medium", shell=False), "Read,Edit,Write,Glob,Grep,WebSearch,WebFetch", "a job with no shell is not sent the shell's long description")
        self.assertEqual(agents.claude_tools("job", "large", shell=True, notebooks=True), "Read,Edit,Write,Glob,Grep,Bash,WebSearch,WebFetch,NotebookEdit,Task")
        self.assertEqual((agents.claude_tools("rewrite", "small", False), agents.claude_tools("review", "large", False)), ("Write", ""))
        c = config.AgentCfg("claude", True, ["claude"], {"small": "haiku"})
        argv = agents.build_argv(c, "small", "do a task", self.tmp, tools="Read,Write")
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Write")
        review = agents.build_argv(c, "small", "review this", self.tmp, tools="")
        self.assertEqual(review[review.index("--tools") + 1], "", "no tools at all is a choice too")
        codex = agents.build_argv(config.AgentCfg("codex", True, ["codex"], {"small": "m"}), "small", "do a task", self.tmp, tools="Read")
        self.assertNotIn("--tools", codex, "only Claude Code takes this")

    @unittest.skipIf(os.name == "nt", "the user's own shell on a Mac or Linux")
    def test_the_shell_terminal_executes_and_preserves_directory(self):
        terminal = self.bench.create_terminal("trading")
        session = self.bench.terminal(terminal["id"])
        try:
            session.run("echo JCC_TERMINAL_OK; cd src")
            for _ in range(80):
                snap = session.snapshot()
                if "JCC_TERMINAL_OK" in snap["output"] and snap["cwd"].endswith("src"):
                    break
                time.sleep(.1)
            self.assertIn("JCC_TERMINAL_OK", snap["output"])
            self.assertEqual(Path(snap["cwd"]).resolve(), (self.repo / "src").resolve())
        finally:
            session.stop()

    @unittest.skipUnless(os.name == "nt", "Windows PowerShell terminal")
    def test_terminal_executes_and_preserves_directory(self):
        terminal = self.bench.create_terminal("trading")
        session = self.bench.terminal(terminal["id"])
        try:
            session.run("Write-Output 'JCC_TERMINAL_OK'; Set-Location src")
            for _ in range(80):
                snap = session.snapshot()
                if "JCC_TERMINAL_OK" in snap["output"] and snap["cwd"].endswith("src"):
                    break
                time.sleep(.1)
            self.assertIn("JCC_TERMINAL_OK", snap["output"])
            self.assertEqual(Path(snap["cwd"]), self.repo / "src")
        finally:
            session.stop()


class ManualModelApiTests(GuiTestCase):
    def test_manual_model_and_effort_persist_in_job(self):
        catalog = [{"id": "codex:gpt-6.1-sol", "provider": "codex", "model": "gpt-6.1-sol",
                    "label": "GPT-6.1 Sol", "efforts": ["low", "high"]}]
        with patch.object(models, "catalog", return_value=catalog):
            _, chat = self.req("POST", "/api/chats", {})
            status, chat = self.req("POST", "/api/chat/send", {"id": chat["id"], "text": "hello",
                "mode": "chat", "model": "codex:gpt-6.1-sol", "effort": "high"})
            self.assertEqual(status, 200)
            import json
            spec = json.loads((Path(self.spawned[0][1]) / "job.json").read_text("utf-8"))
            self.assertEqual(spec["manual_model"], "codex:gpt-6.1-sol")
            self.assertEqual(spec["effort"], "high")
            self.assertEqual(spec["kind"], "chat")
            status, _ = self.req("POST", "/api/chat/send", {"id": chat["id"], "text": "hello", "model": "codex:gpt-6.1-sol", "effort": "medium"})
            self.assertEqual(status, 400, "a level this model does not have")
            status, _ = self.req("POST", "/api/chat/send", {"id": chat["id"], "text": "hello", "model": "codex:gpt-6.1-sol", "effort": "everything"})
            self.assertEqual(status, 400)
            status, _ = self.req("POST", "/api/chat/send", {"id": chat["id"], "text": "hello", "mode": "chat", "model": "codex:gpt-6.1-sol", "effort": "ultra"})
            self.assertEqual(status, 200, "ultra goes with any model: as hard as that one can think")

    def test_terminal_and_browser_endpoints_require_auth(self):
        self.assertEqual(self.req("POST", "/api/terminal", {"action": "start"}, token=False)[0], 401)
        self.assertEqual(self.req("GET", "/api/browser", token=False)[0], 401)
        self.assertEqual(self.req("GET", "/api/files?project=trading&path=../../", token=False)[0], 401)


class TestFileSaving(unittest.TestCase):
    """Owner-requested create and edit of project text files stays inside the project."""

    def setUp(self):
        import tempfile
        from types import SimpleNamespace
        from jcc.workbench import Workbench
        self.root = Path(tempfile.mkdtemp(prefix="jcc-save-"))
        (self.root / "app.py").write_text("print('hi')\n", "utf-8")
        cfg = SimpleNamespace(projects={"demo": SimpleNamespace(path=self.root)}, state_dir=self.root / "state")
        self.bench = Workbench(cfg)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    def test_create_then_edit(self):
        made = self.bench.save_file("demo", "pages/about.html", "<h1>About</h1>", create=True)
        self.assertEqual(made["path"], "pages/about.html")
        self.assertEqual((self.root / "pages" / "about.html").read_text("utf-8"), "<h1>About</h1>")
        self.bench.save_file("demo", "app.py", "print('bye')\n")
        self.assertEqual(self.bench.files("demo", "app.py")["text"], "print('bye')\n")

    def test_refuses_unsafe_targets(self):
        cases = [("../outside.txt", True), (".env", True), (".git/config", True), ("secrets/key.txt", True),
                 ("id_rsa", True), ("missing.txt", False), ("app.py", True), ("bad:name.txt", True), ("", True)]
        for rel, create in cases:
            with self.assertRaises(ValueError, msg=rel):
                self.bench.save_file("demo", rel, "x", create=create)
        with self.assertRaises(ValueError):
            self.bench.save_file("other", "a.txt", "x", create=True)
        with self.assertRaises(ValueError):
            self.bench.save_file("demo", "big.txt", "x" * 600000, create=True)
        self.assertFalse((self.root.parent / "outside.txt").exists())

    def test_never_overwrites_a_file_shown_redacted(self):
        secret = "token = 'gsk_abcdefghij1234567890abcd'\n"
        (self.root / "settings.py").write_text(secret, "utf-8")
        with self.assertRaises(ValueError):
            self.bench.save_file("demo", "settings.py", "token = '[REDACTED]'\n")
        self.assertEqual((self.root / "settings.py").read_text("utf-8"), secret)
