"""The Connections list: what JARVIS can be connected to, what is connected, and a real check of each."""
import json
import os
import time
import unittest

from jcc import agents, config, connections, mailer, secrets, speech
from jcc.lock import InstanceLock
from tests.helpers import EngineTestCase
from tests.test_gui import GuiTestCase
from tests.test_speech import ELEVEN_KEY, SpeechMixin

GROQ = "gsk_test_ThisIsNotARealKey_0123456789"


class TestConnections(SpeechMixin, EngineTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.load()
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        self.start_stand_in()
        self._available, self._groq = agents.available, os.environ.pop("JCC_GROQ_API_KEY", None)
        agents.available = lambda agent: agent.name == "claude"

    def tearDown(self):
        agents.available = self._available
        os.environ.pop("JCC_GROQ_API_KEY", None)
        if self._groq is not None:
            os.environ["JCC_GROQ_API_KEY"] = self._groq
        self.stop_stand_in()
        super().tearDown()

    def by_id(self):
        return {item["id"]: item for item in connections.overview(self.cfg)}

    def test_a_new_pc_shows_what_is_needed_and_what_is_optional(self):
        found = self.by_id()
        self.assertEqual((found["claude"]["state"], found["claude"]["status"]), ("ok", "Installed"))
        self.assertEqual((found["codex"]["state"], found["codex"]["status"]), ("off", "Not installed on this PC"))
        self.assertEqual((found["groq"]["state"], found["groq"]["key"], found["groq"]["check"]), ("needed", "groq", False), "listening needs one of the two keys")
        self.assertEqual([found[name]["state"] for name in ("openai", "elevenlabs", "mail", "connectors", "chatgpt", "claude-web", "github", "cloud")], ["off"] * 8)
        self.assertEqual((found["pc"]["state"], found["sound"]["status"]), ("ok", "Windows default microphone · Windows default speakers"))
        from jcc import system
        self.assertEqual(found["helper"]["state"], "off" if system.kind() == "linux" else "problem", "the background helper is not running in this test")
        for item in found.values():
            self.assertTrue(item["name"] and item["about"] and item["status"] and item["group"] in dict(connections.GROUPS), item)
            if item["state"] in ("needed", "problem") or item.get("key"):
                self.assertTrue(item.get("how") or item.get("open") or item.get("settings"), "there is always a way forward: " + item["id"])
        total = connections.summary(list(found.values()))
        self.assertEqual((total["needed"], total["problems"], total["of"]), (["Whisper listening (Groq)"], ["\"Hey JARVIS\" and shortcuts"], len(found)))

    def test_what_is_connected_is_shown_as_connected_and_no_key_is_ever_shown(self):
        os.environ["JCC_GROQ_API_KEY"] = GROQ
        secrets.store("elevenlabs", ELEVEN_KEY)
        secrets.store("mail", "app-password-1234")
        (self.cfg.state_dir / "mail.json").write_text(json.dumps({"address": "me@example.com", "host": "smtp.example.com", "port": 587}), "utf-8")
        (self.cfg.state_dir / "connectors.json").write_text(json.dumps({"mcpServers": {"calendar": {"command": "x"}, "gmail": {"command": "y", "env": {"TOKEN": "sekret-token"}}}}), "utf-8")
        (self.cfg.state_dir / "quota-claude.json").write_text(json.dumps({"at": time.time(), "windows": [{"name": "five hour"}]}), "utf-8")
        (self.cfg.state_dir / "github-status.json").write_text(json.dumps({"at": time.time() - 200, "status": "synced", "private": True}), "utf-8")
        (self.cfg.state_dir / "cloud-memory-status.json").write_text(json.dumps({"status": "error", "error": "HTTP Error 403: Forbidden", "indexed_notes": 12}), "utf-8")
        (self.cfg.state_dir / "capture-chatgpt-status.json").write_text(json.dumps({"at": time.time() - 7300}), "utf-8")
        speech.configure(self.cfg, {"mic": "Microphone (HyperX Quadcast)", "voice_name": "George"})
        (self.cfg.state_dir / "tray-status.json").write_text(json.dumps({"wake": True, "keys": {"talk": "Ctrl+Alt+T"}, "wake_problem": ""}), "utf-8")
        helper = InstanceLock(self.cfg.state_dir / "tray.lock")
        self.assertTrue(helper.acquire())
        try:
            found = self.by_id()
        finally:
            helper.release()
        self.assertEqual((found["claude"]["status"], found["groq"]["status"], found["groq"]["check"], found["groq"]["remove"]), ("Signed in and answering", "Connected", True, True))
        self.assertEqual((found["elevenlabs"]["state"], found["elevenlabs"]["status"]), ("ok", "Connected · George"))
        self.assertEqual(found["openai"]["state"], "off", "optional once Groq is there")
        self.assertEqual((found["mail"]["state"], found["mail"]["status"]), ("ok", "Connected as me@example.com"))
        self.assertEqual((found["connectors"]["state"], found["connectors"]["status"]), ("ok", "calendar, gmail"))
        self.assertEqual((found["github"]["state"], found["github"]["status"]), ("ok", "Synced 3 minutes ago"))
        self.assertEqual((found["cloud"]["state"], found["cloud"]["status"]), ("problem", "Not working: HTTP Error 403: Forbidden"))
        self.assertEqual((found["chatgpt"]["state"], found["chatgpt"]["status"]), ("ok", "Last saved 2 hours ago"))
        self.assertEqual((found["helper"]["state"], found["helper"]["status"]), ("ok", "Running, listening for \"Hey JARVIS\""))
        self.assertIn("Microphone (HyperX Quadcast)", found["sound"]["status"])
        shown = json.dumps(list(found.values()))
        for secret in (GROQ, ELEVEN_KEY, "app-password-1234", "sekret-token"):
            self.assertNotIn(secret, shown)

    def test_damaged_files_do_not_break_the_list(self):
        for name in ("quota-claude.json", "connectors.json", "github-status.json", "cloud-memory-status.json", "tray-status.json", "mail.json", "speech.json", "assistant.json"):
            (self.cfg.state_dir / name).write_text("{", "utf-8")
        (self.cfg.state_dir / "capture-chatgpt-status.json").write_text('["odd"]', "utf-8")
        from jcc import system
        self.assertEqual(len(self.by_id()), 17 + (2 if system.kind() == "mac" else 0))

    def test_each_connection_can_really_be_checked(self):
        self.assertEqual(connections.check(self.cfg, "groq"), {"ok": False, "status": "No key is saved."})
        os.environ["JCC_GROQ_API_KEY"] = GROQ
        self.assertEqual(connections.check(self.cfg, "groq"), {"ok": True, "status": "The key works."})
        self.assertEqual(self.remote.last("/w/models")["headers"]["Authorization"], "Bearer " + GROQ)
        secrets.store("openai", "sk-wrong_key_wrong_key_wrong_key")              # a key the service does not accept
        wrong = connections.check(self.cfg, "openai")
        self.assertFalse(wrong["ok"])
        self.assertNotIn("sk-wrong", wrong["status"])
        self.assertEqual(connections.check(self.cfg, "elevenlabs")["ok"], False)
        secrets.store("elevenlabs", ELEVEN_KEY)
        self.assertEqual(connections.check(self.cfg, "elevenlabs"), {"ok": True, "status": "The key works. 5.0% of this month's allowance used."})
        self.assertEqual(connections.check(self.cfg, "mail"), {"ok": False, "status": "No email account is connected."})
        for unknown in ("helper", "pc", "nonsense", ""):
            with self.assertRaises(ValueError):
                connections.check(self.cfg, unknown)

    def test_the_email_account_is_checked_by_signing_in(self):
        secrets.store("mail", "app-password-1234")
        (self.cfg.state_dir / "mail.json").write_text(json.dumps({"address": "me@example.com", "host": "smtp.example.com", "port": 587}), "utf-8")
        seen = []

        class Server:
            def __init__(self, host, port):
                seen.append((host, port))

            def login(self, address, password):
                seen.append((address, password == "app-password-1234"))

            def quit(self):
                seen.append("quit")
        self.assertEqual(mailer.verify(self.cfg, Server), "Signed in to smtp.example.com as me@example.com.")
        self.assertEqual(seen, [("smtp.example.com", 587), ("me@example.com", True), "quit"])


class TestConnectionsApi(GuiTestCase):
    def test_the_window_can_read_the_list_and_ask_for_a_check(self):
        status, data = self.req("GET", "/api/connections")
        self.assertEqual(status, 200)
        self.assertEqual([group[0] for group in data["groups"]], ["brain", "voice", "hands", "memory"])
        from jcc import system
        count = 17 + (2 if system.kind() == "mac" else 0)          # (a Mac also shows the two things macOS must allow)
        self.assertEqual(len(data["items"]), count)
        self.assertEqual(data["summary"]["of"], count)
        self.assertEqual(self.req("GET", "/api/connections", token=False)[0], 401)
        self.assertEqual(self.req("POST", "/api/connections", {"action": "check", "id": "nonsense"})[0], 400)
        self.assertEqual(self.req("POST", "/api/connections", {"action": "delete everything"})[0], 400)
        self.assertEqual(self.req("POST", "/api/connections", {"action": "check", "id": "mail"}, token=False)[0], 401)
        status, answer = self.req("POST", "/api/connections", {"action": "check", "id": "mail"})
        self.assertEqual((status, answer), (200, {"ok": False, "status": "No email account is connected."}))


if __name__ == "__main__":
    unittest.main()
