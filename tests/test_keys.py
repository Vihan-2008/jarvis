"""Keys in the system's own key store: the Keychain on a Mac, the Secret Service on Linux. Each system is stood in for
by a fake subprocess.run, so these run anywhere; the Windows Credential Manager is used only by the app itself."""
import json
import os
import sys
import subprocess
import unittest
from unittest import mock

from jcc import secrets, system

KEY = "AIzaSyFAKEkeychainKEY_1234567890abcd"


class FakeRun:
    """Stands in for subprocess.run: records every call and keeps what was stored, like the real store would."""

    def __init__(self, fail_store=False):
        self.calls, self.kept, self.fail_store = [], {}, fail_store

    def __call__(self, argv, **kw):
        self.calls.append((list(argv), kw))
        out, code = "", 0
        if argv[:2] == [secrets.SECURITY, "-i"]:
            if not self.fail_store:
                self.kept["mac"] = kw["input"]
        elif "find-generic-password" in argv:
            stored = self.kept.get("mac")
            out, code = (self.stored_value() + "\n", 0) if stored else ("", 44)
        elif argv[1:2] == ["store"]:
            self.kept["linux"] = kw["input"]
        elif argv[1:2] == ["lookup"]:
            out, code = (self.kept["linux"], 0) if "linux" in self.kept else ("", 1)
        return subprocess.CompletedProcess(argv, code, out, "")

    def stored_value(self) -> str:
        """What `security -i` would have stored from the line it was given (its quoting undone)."""
        line = self.kept["mac"]
        quoted = line.split(" -w ", 1)[1].rstrip("\n")
        return json.loads(quoted)          # the same quoting rules as a JSON string for these characters

    def every_argument(self) -> str:
        return "\n".join(" ".join(argv) for argv, _ in self.calls)


class KeyStoreCase(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop("JCC_NO_CREDMAN", None)
        os.environ.pop("JCC_GEMINI_API_KEY", None)
        self.run = FakeRun()
        self.patches = [mock.patch("subprocess.run", self.run)]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.env.stop()

    def on(self, platform):
        patch = mock.patch.object(system, "PLATFORM", platform)
        patch.start()
        self.patches.append(patch)


class TestKeychain(KeyStoreCase):
    def setUp(self):
        super().setUp()
        self.on("darwin")

    def test_a_key_is_kept_in_the_login_keychain_and_read_back(self):
        secrets.store("gemini", KEY)
        argv, kw = self.run.calls[0]
        self.assertEqual(argv, [secrets.SECURITY, "-i"])
        self.assertEqual(kw["input"], f'add-generic-password -U -s "JARVIS Command" -a "gemini" -w "{KEY}"\n')
        self.assertEqual(secrets.get("gemini"), KEY)
        self.assertIn([secrets.SECURITY, "find-generic-password", "-s", "JARVIS Command", "-a", "gemini", "-w"], [a for a, _ in self.run.calls])
        self.assertEqual(secrets.status()["gemini"], "set (Keychain)")

    def test_the_secret_is_never_on_a_command_line(self):
        secrets.store("gemini", KEY)
        secrets.get("gemini")
        secrets.delete("gemini")
        self.assertNotIn(KEY, self.run.every_argument(), "other programs can read a command line; the key goes on standard input")

    def test_quotes_and_backslashes_in_a_value_stay_inside_it(self):
        value = 'pa"ss\\word -a evil'
        secrets.store("mail", value)
        self.assertEqual(self.run.stored_value(), value)
        line = self.run.kept["mac"]
        self.assertEqual(line.count("\n"), 1, "one command, ended once")
        self.assertTrue(line.startswith('add-generic-password -U -s "JARVIS Command" -a "mail" -w "'))

    def test_a_value_with_a_line_break_is_refused(self):
        with self.assertRaises(ValueError):
            secrets.store("gemini", "abc\nadd-generic-password -s other -a x -w y")
        self.assertEqual(self.run.calls, [], "nothing reached the Keychain")

    def test_a_key_the_keychain_did_not_keep_is_reported(self):
        self.run.fail_store = True
        with self.assertRaises(RuntimeError):
            secrets.store("gemini", KEY)

    def test_deleting_asks_the_keychain_to_forget_it(self):
        secrets.delete("groq")
        self.assertEqual(self.run.calls[0][0], [secrets.SECURITY, "delete-generic-password", "-s", "JARVIS Command", "-a", "groq"])


class TestSecretService(KeyStoreCase):
    def setUp(self):
        super().setUp()
        self.on("linux")

    def test_secret_tool_keeps_the_key_from_its_standard_input(self):
        with mock.patch("shutil.which", lambda name: "/usr/bin/secret-tool" if name == "secret-tool" else None):
            secrets.store("groq", KEY)
            self.assertEqual(secrets._cred_read("groq"), KEY)
            secrets.delete("groq")
        store, lookup, clear = (argv for argv, _ in self.run.calls)
        self.assertEqual(store, ["/usr/bin/secret-tool", "store", "--label=JARVIS Command groq", "service", "jarvis-command", "account", "groq"])
        self.assertEqual(self.run.calls[0][1]["input"], KEY)
        self.assertEqual(lookup, ["/usr/bin/secret-tool", "lookup", "service", "jarvis-command", "account", "groq"])
        self.assertEqual(clear, ["/usr/bin/secret-tool", "clear", "service", "jarvis-command", "account", "groq"])
        self.assertNotIn(KEY, self.run.every_argument())

    def test_without_secret_tool_storing_says_which_variable_to_set(self):
        with mock.patch("shutil.which", lambda name: None):
            with self.assertRaises(RuntimeError) as told:
                secrets.store("gemini", KEY)
            self.assertIn("JCC_GEMINI_API_KEY", str(told.exception))
            self.assertIsNone(secrets._cred_read("gemini"))
        self.assertEqual(self.run.calls, [])


class TestEverySystem(KeyStoreCase):
    def test_the_environment_variable_works_everywhere_without_a_key_store(self):
        for platform in ("darwin", "linux") + (("win32",) if sys.platform == "win32" else ()):
            with mock.patch.object(system, "PLATFORM", platform), mock.patch.dict(os.environ, {"JCC_GEMINI_API_KEY": KEY}):
                self.assertEqual(secrets.get("gemini"), KEY)
                self.assertEqual(self.run.calls, [], "the variable is used without asking any key store")
                self.assertTrue(secrets.status()["gemini"].startswith("set (env"))
                self.run.calls.clear()

    def test_jcc_no_credman_switches_every_key_store_off(self):
        os.environ["JCC_NO_CREDMAN"] = "1"
        try:
            for platform in ("darwin", "linux"):
                with mock.patch.object(system, "PLATFORM", platform):
                    secrets.store("groq", KEY)
                    self.assertEqual(secrets._cred_read("groq"), KEY)
                    secrets.delete("groq")
                    self.assertIsNone(secrets._cred_read("groq"))
        finally:
            secrets._memory.clear()
        self.assertEqual(self.run.calls, [], "no real key store was touched")

    def test_the_store_is_named_for_the_owner(self):
        for platform, said in (("win32", "Credential Manager"), ("darwin", "Keychain"), ("linux", "the system key store")):
            with mock.patch.object(system, "PLATFORM", platform):
                self.assertEqual(secrets.store_name(), said)


if __name__ == "__main__":
    unittest.main()
