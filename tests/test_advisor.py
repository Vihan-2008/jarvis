"""/advisor, as in Claude Code: the advisor model is a saved setting that every Claude Code job is given as its
advisorModel setting, never as the --advisor flag (which would stop a job whose own model it cannot pair with)."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from jcc import agents, assistant, mods


class Advisor(unittest.TestCase):
    def setUp(self):
        self.cfg = SimpleNamespace(state_dir=Path(tempfile.mkdtemp()))

    def test_none_until_chosen_then_saved_and_turned_off_again(self):
        self.assertEqual(assistant.settings(self.cfg)["advisor"], "")
        self.assertEqual(assistant.configure(self.cfg, {"advisor": "opus"})["advisor"], "opus")
        self.assertEqual(assistant.settings(self.cfg)["advisor"], "opus")
        self.assertEqual(assistant.configure(self.cfg, {"advisor": "claude-fable-5-2"})["advisor"], "claude-fable-5-2")
        self.assertEqual(assistant.configure(self.cfg, {"advisor": "off"})["advisor"], "")

    def test_only_claude_models_are_accepted(self):
        for wrong in ("gpt-5", "opus; rm -rf /", "--advisor", 3, None, "x" * 80):
            with self.assertRaises(ValueError, msg=repr(wrong)):
                assistant.configure(self.cfg, {"advisor": wrong})

    def claude(self):
        return SimpleNamespace(name="claude", command=["claude"], models={"medium": "sonnet"})

    def test_a_claude_code_job_is_given_the_advisor_as_a_setting(self):
        argv = agents.build_argv(self.claude(), "medium", "do it", Path("."), advisor="opus")
        at = argv.index("--settings")
        self.assertEqual(json.loads(argv[at + 1]), {"advisorModel": "opus"})
        self.assertNotIn("--advisor", argv)

    def test_no_advisor_no_setting(self):
        self.assertNotIn("--settings", agents.build_argv(self.claude(), "medium", "do it", Path(".")))

    def test_codex_has_no_advisor(self):
        codex = SimpleNamespace(name="codex", command=["codex"], models={"medium": ""})
        argv = agents.build_argv(codex, "medium", "do it", Path("."), advisor="opus")
        self.assertNotIn("advisorModel", " ".join(argv))

    def test_it_is_a_command(self):
        self.assertIn("advisor", [name for name, _ in mods.BUILTIN])
        page = (Path(agents.__file__).with_name("static") / "nova.js").read_text("utf-8")
        self.assertIn("async function advisorCommand(", page)
        self.assertIn("name === 'advisor'", page)


if __name__ == "__main__":
    unittest.main()
