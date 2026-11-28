"""The help tool and the map of where data goes (jcc/app_help.py)."""
import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from jcc import app_help, policy, voice_tools

JCC = Path(app_help.__file__).resolve().parent
HOST = re.compile(r"(?:https?|wss?)://([a-z0-9-]+(?:\.[a-z0-9-]+)+)", re.I)


class TestDataMap(unittest.TestCase):
    def test_every_outside_address_in_the_code_is_in_the_data_map_or_is_only_a_link(self):
        mapped = {host for entry in app_help.DATA_MAP for host in entry["hosts"]}
        found = {}
        for path in JCC.rglob("*"):
            if path.suffix not in (".py", ".js", ".ps1") or not path.is_file():
                continue
            for host in HOST.findall(path.read_text(encoding="utf-8", errors="replace")):
                host = host.lower().rstrip(".")
                if host in ("127.0.0.1", "localhost") or host == "example.com" or host.endswith((".localhost", ".test", ".example", ".invalid", ".example.com"))                         or host.startswith("your-"):        # (placeholders shown in a form)
                    continue
                found.setdefault(host, path.name)
        missing = {h: f for h, f in found.items() if h not in mapped and h not in app_help.LINKS_ONLY}
        self.assertEqual(missing, {}, "a new outside address: add it to app_help.DATA_MAP (data goes there) or LINKS_ONLY (only opened as a link)")

    def test_no_address_is_both_a_link_and_a_destination(self):
        mapped = {host for entry in app_help.DATA_MAP for host in entry["hosts"]}
        self.assertEqual(mapped & app_help.LINKS_ONLY, set())

    def test_every_entry_says_where_what_when_and_how_to_switch_it_off(self):
        keys = [entry["key"] for entry in app_help.DATA_MAP]
        self.assertEqual(len(keys), len(set(keys)))
        for entry in app_help.DATA_MAP:
            for field in ("name", "where", "what", "when", "off"):
                self.assertTrue(entry.get(field), (entry["key"], field))

    def test_the_known_gaps_are_stated_not_hidden(self):
        by_key = {entry["key"]: entry for entry in app_help.DATA_MAP}
        self.assertIn("Private/", by_key["vault_git"]["what"])
        self.assertIn("no off switch", by_key["cloud_memory"]["gap"])
        self.assertIn("cloud_sync: false", by_key["coding"]["gap"])
        self.assertIn("Nothing goes to the JARVIS project", by_key["phone"]["what"])


class TestHelp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        state = Path(self.dir.name)
        self.cfg = SimpleNamespace(state_dir=state, vault=state / "OneDrive" / "Vault")

    def test_the_guides_phone_setup_ai_keys_and_data_map_are_all_there(self):
        titles = [item["title"] for item in app_help.sections(self.cfg)]
        self.assertIn("The interface", titles)
        self.assertIn("Set up the phone app", titles)
        self.assertIn("Connect Groq", titles)
        self.assertIn("Where your data goes: Vault backup to GitHub", titles)

    def test_setup_questions_find_the_setup_and_data_questions_find_the_map(self):
        self.assertEqual(app_help.search(self.cfg, "how do I set up the phone app")[0]["title"], "Set up the phone app")
        self.assertIn("console.groq.com", app_help.answer(self.cfg, "how do I connect Groq"))
        found = app_help.answer(self.cfg, "where does my data go with cloud memory")
        self.assertIn("Cloud memory", found)
        self.assertIn("On this computer: off.", found)

    def test_the_live_setup_is_read_from_this_computer(self):
        (self.cfg.state_dir / "github.json").write_text("{}")
        (self.cfg.state_dir / "cloud-memory.json").write_text(json.dumps({"enabled": True}))
        text = {item["title"]: item["text"] for item in app_help.sections(self.cfg)}
        self.assertIn("On this computer: set up.", text["Where your data goes: Vault backup to GitHub"])
        self.assertIn("On this computer: on.", text["Where your data goes: Cloud memory"])
        self.assertIn("Microsoft holds a copy", text["Where your data goes: overview"])

    def test_an_unknown_question_says_the_guide_has_nothing(self):
        self.assertIn("nothing on that", app_help.answer(self.cfg, "zzqx"))

    def test_the_tool_is_offered_read_only_and_without_pc_control(self):
        self.assertIn("app_help", voice_tools.NAMES)
        self.assertIn("app_help", policy.WITHOUT_PC)
        self.assertIn("app_help", policy.QUIET_TOOLS)
        self.assertIn("app_help(question)", voice_tools.BRIEF["app_help"])


if __name__ == "__main__":
    unittest.main()
