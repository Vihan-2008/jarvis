"""The interactive terminal: a real pseudo-console session started on request."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from jcc import pty_terminal


class TerminalCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jcc-pty-"))
        self.manager = pty_terminal.PtyManager(SimpleNamespace(projects={}, state_dir=self.tmp))

    def tearDown(self):
        self.manager.stop_all()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def collect(self, terminal, needle, seconds=25):
        position, text, deadline = 0, "", time.time() + seconds
        while time.time() < deadline and needle not in text:
            chunk = terminal.read(position, 1.0)
            text, position = text + chunk["data"], chunk["next"]
        return text

    def check_runs_commands(self, line):
        info = self.manager.start(None, 90, 24)
        terminal = self.manager.get(info["id"])
        self.assertTrue(terminal.alive())
        terminal.write(line)
        self.assertIn("pty-check-42", self.collect(terminal, "pty-check-42"))
        terminal.resize(120, 30)
        self.assertEqual((terminal.cols, terminal.rows), (120, 30))
        self.manager.stop(info["id"])
        self.assertFalse(terminal.alive())
        with self.assertRaises(ValueError):
            self.manager.get(info["id"])

    def check_limits(self):
        with self.assertRaises(ValueError):
            self.manager.start("missing-project")
        with self.assertRaises(ValueError):
            self.manager.get("nope")
        ids = [self.manager.start(None)["id"] for _ in range(4)]
        with self.assertRaises(ValueError):
            self.manager.get(ids[1]).write("x" * 100_001)
        fifth = self.manager.start(None)["id"]
        self.assertEqual(len(self.manager.sessions), 4)
        self.assertIn(fifth, self.manager.sessions)
        self.assertNotIn(ids[0], self.manager.sessions)


@unittest.skipUnless(os.name == "nt" and pty_terminal.AVAILABLE, "the Windows pseudo-console (ConPTY) with PowerShell in it")
class TestPtyTerminal(TerminalCase):
    def test_runs_commands_like_a_real_console(self):
        self.check_runs_commands("echo pty-check-$(20+22)\r")

    def test_limits_and_bad_input(self):
        self.check_limits()


@unittest.skipIf(os.name == "nt", "a Mac's or Linux's pseudo-terminal (the pty module does not exist on Windows)")
class TestPosixTerminal(TerminalCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"SHELL": "/bin/sh"})      # a plain shell: the test does not read the user's own startup files
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_runs_commands_like_a_real_terminal(self):
        self.check_runs_commands("echo pty-check-$((20+22))\r")

    def test_limits_and_bad_input(self):
        self.check_limits()

    def test_the_users_own_shell_is_started(self):
        with mock.patch.dict(os.environ, {"SHELL": "/bin/sh"}):
            self.assertEqual(pty_terminal.user_shell(), "/bin/sh")
        with mock.patch.dict(os.environ, {"SHELL": "not a shell"}):
            self.assertIn(pty_terminal.user_shell(), ("/bin/zsh", "/bin/bash"))


class TestSizes(unittest.TestCase):
    def test_a_terminal_is_kept_to_a_sensible_size(self):
        self.assertEqual(pty_terminal._size(5, 1000), (20, 200))
        with self.assertRaises(ValueError):
            pty_terminal._size("wide", 3)

    def test_each_system_gets_its_own_kind_of_terminal(self):
        expected = "_ConPtyTerminal" if os.name == "nt" else "_PosixPtyTerminal"
        self.assertEqual(pty_terminal.PtyTerminal.__name__, expected)


if __name__ == "__main__":
    unittest.main()
