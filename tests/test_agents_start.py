"""Only a program itself is ever started for a coding agent. A launcher script (.cmd, .bat, .ps1, or the script npm puts
beside them) is started through cmd.exe, which reads the command line again by its own rules; a request is given to an
agent on its command line, so words in it could be taken for commands."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jcc import agents


@unittest.skipUnless(os.name == "nt", "it is Windows that starts launcher scripts through cmd.exe")
class TestOnlyPrograms(unittest.TestCase):
    def setUp(self):
        agents.resolve_command.cache_clear()
        self.addCleanup(agents.resolve_command.cache_clear)

    def test_an_agent_installed_only_as_a_launcher_counts_as_not_installed(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ("gemini", "gemini.cmd", "gemini.ps1", "tool.bat"):
                (Path(folder) / name).write_text("@echo off\n", "utf-8")
            with mock.patch.dict(os.environ, {"PATH": folder}):
                self.assertIsNone(agents.resolve_command("gemini"), "found on the path, but only as a launcher")
                for named in ("tool.bat", "gemini.cmd", "gemini.ps1", "gemini"):
                    self.assertIsNone(agents.resolve_command(str(Path(folder) / named)), named)
                self.assertFalse(agents.available(agents.AgentCfg(name="gemini", enabled=True, command=["gemini"], models={})))

    def test_a_program_is_found_as_before(self):
        found = agents.resolve_command(sys.executable)
        self.assertEqual(Path(found).name.lower(), Path(sys.executable).name.lower())
        with tempfile.TemporaryDirectory() as folder:
            program = Path(folder) / "agent.exe"
            program.write_bytes(b"MZ")
            (Path(folder) / "agent.cmd").write_text("@echo off\n", "utf-8")
            with mock.patch.dict(os.environ, {"PATH": folder}):
                self.assertEqual(Path(agents.resolve_command("agent")).name.lower(), "agent.exe", "the program is chosen over a launcher of the same name")


if __name__ == "__main__":
    unittest.main()
