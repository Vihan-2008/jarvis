"""One unreadable file must never take the window's connection down.

Seen live: another program's file (Codex's model list) was empty for a while, the status request crashed reading it and
the window showed "disconnected"."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from jcc import config, models, quota
from jcc.vault import read_json
from tests.helpers import EngineTestCase
from tests.test_gui import GuiTestCase

BROKEN = ("", "{", "[1, 2", "null", "�\x00garbage", '"just a string"', "[]")


class TestReadingSavedFiles(unittest.TestCase):
    def test_a_missing_empty_or_damaged_file_gives_the_default(self):
        folder = Path(tempfile.mkdtemp(prefix="jcc-sturdy-"))
        try:
            path = folder / "state.json"
            self.assertEqual(read_json(path, {"a": 1}), {"a": 1}, "missing")
            for text in BROKEN:
                path.write_text(text, "utf-8")
                self.assertEqual(read_json(path, {"a": 1}), {"a": 1}, repr(text))
            path.write_bytes(b"\xff\xfe\x00not utf-8")
            self.assertEqual(read_json(path, []), [])
            path.write_text('{"kept": true}', "utf-8")
            self.assertEqual(read_json(path, {}), {"kept": True})
            self.assertEqual(read_json(path, []), [], "the wrong kind of thing is not passed on")
            self.assertEqual(read_json(path, None), {"kept": True}, "no default: whatever is there")
        finally:
            for item in folder.iterdir():
                item.unlink()
            folder.rmdir()

    def test_saving_waits_out_a_file_that_is_being_read_at_that_moment(self):
        # Seen live: Windows refused to replace the chat list's cache ("Access is denied") because something was
        # reading it at that very moment, and the part of JARVIS that was saving it stopped.
        from unittest import mock
        from jcc import vault
        folder = Path(tempfile.mkdtemp(prefix="jcc-sturdy-"))
        real, refused = os.replace, []

        def busy(source, target):
            if len(refused) < 3:
                refused.append(target)
                raise PermissionError(5, "Access is denied")
            return real(source, target)
        try:
            path = folder / "state.json"
            path.write_text("old", "utf-8")
            with mock.patch.object(vault.os, "replace", busy), mock.patch.object(vault.time, "sleep", lambda seconds: None):
                vault.atomic_write(path, "new")
            self.assertEqual((path.read_text("utf-8"), len(refused)), ("new", 3))
            with mock.patch.object(vault.os, "replace", side_effect=PermissionError(5, "Access is denied")), mock.patch.object(vault.time, "sleep", lambda seconds: None):
                with self.assertRaises(PermissionError):
                    vault.atomic_write(path, "never")
            self.assertEqual(path.read_text("utf-8"), "new", "what was there stays whole")
            self.assertEqual([item.name for item in folder.iterdir()], ["state.json"], "nothing half-written is left behind")
        finally:
            for item in folder.iterdir():
                item.unlink()
            folder.rmdir()


class TestModelListSurvivesOtherProgramsFiles(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.load()
        self.codex = Path(tempfile.mkdtemp(prefix="jcc-codex-"))
        self._home = os.environ.get("CODEX_HOME")
        os.environ["CODEX_HOME"] = str(self.codex)

    def tearDown(self):
        if self._home is None:
            os.environ.pop("CODEX_HOME", None)
        else:
            os.environ["CODEX_HOME"] = self._home
        for item in self.codex.iterdir():
            item.unlink()
        self.codex.rmdir()
        super().tearDown()

    def test_an_empty_or_odd_model_list_is_simply_not_used(self):
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        usual = models.catalog(self.cfg)
        self.assertEqual([m["id"] for m in usual][:3], ["claude:haiku", "claude:sonnet", "claude:opus"])
        for text in BROKEN + ('{"models": "nonsense"}', '{"models": [1, null, {"visibility": "list"}, {"visibility": "list", "slug": 7}]}'):
            (self.codex / "models_cache.json").write_text(text, "utf-8")
            (self.cfg.state_dir / "quota-claude.json").write_text(text, "utf-8")
            self.assertEqual(models.catalog(self.cfg), usual, repr(text))
        (self.codex / "models_cache.json").write_text(json.dumps({"models": [
            {"slug": "gpt-test", "visibility": "list", "display_name": "GPT Test", "supported_reasoning_levels": [{"effort": "low"}, "odd", {"effort": 3}]},
            {"slug": "hidden", "visibility": "hide"}]}), "utf-8")
        (self.cfg.state_dir / "quota-claude.json").write_text(json.dumps({"models": [{"value": "claude-test-1", "displayName": "Claude Test", "efforts": "odd"},
                                                                                     {"value": "default"}, {"value": "bad name!"}, "odd"]}), "utf-8")
        found = {m["id"]: m for m in models.catalog(self.cfg)}
        self.assertEqual(found["codex:gpt-test"]["efforts"], ["low"])
        self.assertNotIn("codex:hidden", found)
        self.assertEqual((found["claude:claude-test-1"]["label"], found["claude:claude-test-1"]["efforts"]), ("Claude Test", ["low", "medium", "high"]))
        self.assertNotIn("claude:bad name!", found)
        self.assertEqual(quota.snapshot(self.cfg)["codex"]["error"], "Waiting for first reading.")


class TestTheStatusAlwaysAnswers(GuiTestCase):
    FILES = ("quota-claude.json", "quota-codex.json", "resources.json", "efficiency.json", "assistant-settings.json", "routing-learning.json",
             "job-feedback.json", "projects.json", "conversation-index.json", "import-status.json", "speech.json", "tray-status.json")

    def test_damaged_files_do_not_disconnect_the_window(self):
        status, good = self.req("GET", "/api/state")
        self.assertEqual(status, 200)
        folder = Path(tempfile.mkdtemp(prefix="jcc-codex-"))
        home = os.environ.get("CODEX_HOME")
        os.environ["CODEX_HOME"] = str(folder)
        try:
            for text in ("", "{", '"a string"', "[]"):
                (folder / "models_cache.json").write_text(text, "utf-8")
                for name in self.FILES:
                    (self.state.cfg.state_dir / name).write_text(text, "utf-8")
                status, data = self.req("GET", "/api/state")
                self.assertEqual(status, 200, repr(text))
                self.assertEqual(sorted(data), sorted(good), "every section is still there")
                self.assertEqual([m["id"] for m in data["models"]][:3], ["claude:haiku", "claude:sonnet", "claude:opus"])
                self.assertEqual(data["resources"]["settings"]["retention_days"], 30, "settings fall back to their defaults")
                self.assertEqual(data["efficiency"]["settings"]["max_attempts"], 4)
                self.assertTrue(data["learning"]["settings"]["adaptive_routing"])
                self.assertEqual(self.req("GET", "/api/speech")[0], 200)
        finally:
            if home is None:
                os.environ.pop("CODEX_HOME", None)
            else:
                os.environ["CODEX_HOME"] = home
            for item in folder.iterdir():
                item.unlink()
            folder.rmdir()

    def test_a_section_that_fails_shows_its_last_good_value(self):
        from jcc import gui
        status, good = self.req("GET", "/api/state")
        original = gui.models.catalog

        def broken(cfg):
            raise RuntimeError("something nobody thought of")
        gui.models.catalog = broken
        try:
            for _ in range(3):
                status, data = self.req("GET", "/api/state")
                self.assertEqual(status, 200)
                self.assertEqual(data["models"], good["models"], "the list from before is shown again")
            said = [line for line in data["log"] if "the model list" in line]
            self.assertEqual(len(said), 1, "noted once, not on every request")
        finally:
            gui.models.catalog = original
        status, data = self.req("GET", "/api/state")
        self.assertEqual((status, data["models"]), (200, good["models"]))

    def test_an_unexpected_failure_is_answered_not_dropped(self):
        from jcc import gui
        original = gui.Chats.get

        def broken(self, cid):
            raise RuntimeError("something nobody thought of")
        gui.Chats.get = broken
        try:
            status, data = self.req("GET", "/api/chat?id=20260101-000000-abcd")
            self.assertEqual(status, 500)
            self.assertIn("could not answer", data["error"])
            self.assertNotIn("nobody thought of", json.dumps(data), "the details stay in the log")
        finally:
            gui.Chats.get = original
        self.assertEqual(self.req("GET", "/api/state")[0], 200, "and the app carries on")

    def test_jarvis_starts_with_a_damaged_project_or_routing_list(self):
        for text in ("", "{", "[]", '{"small": "odd", "medium": 3}'):
            (self.state.cfg.state_dir / "projects.json").write_text(text, "utf-8")
            (self.state.cfg.state_dir / "routing.json").write_text(text, "utf-8")
            loaded = config.load()
            self.assertEqual(loaded.vault, self.state.cfg.vault, repr(text))


if __name__ == "__main__":
    unittest.main()
