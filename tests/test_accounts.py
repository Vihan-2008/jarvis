"""Accounts (jcc/accounts.py): signed in with your own Claude or ChatGPT account, as the tools themselves say. The real
tools are never run here: what they answer is stood in for."""
import types
import unittest
from unittest import mock

from jcc import accounts


class TestWhatTheToolsSay(unittest.TestCase):
    def test_claude_code(self):
        said = '{\n  "loggedIn": true,\n  "authMethod": "claude.ai",\n  "apiProvider": "firstParty"\n}'
        self.assertEqual(accounts.read(said, "claude", 0), {"signed_in": True, "how": "with your Claude account"})
        self.assertEqual(accounts.read('{"loggedIn": false}', "claude", 1)["signed_in"], False)
        self.assertEqual(accounts.read("not json at all", "claude", 0), {"signed_in": False, "how": ""})

    def test_codex(self):
        self.assertEqual(accounts.read("Logged in using ChatGPT\n", "codex", 0), {"signed_in": True, "how": "with your ChatGPT account"})
        self.assertEqual(accounts.read("Logged in using an API key - sk-...\n", "codex", 0)["how"], "with an API key")
        self.assertFalse(accounts.read("Not logged in\n", "codex", 1)["signed_in"])

    def test_status_asks_each_installed_tool_and_never_one_that_is_missing(self):
        cfg = types.SimpleNamespace(agents={})
        ran = []
        with mock.patch.object(accounts, "_program", lambda cfg, ident: "C:/tools/claude.exe" if ident == "claude" else ""), \
                mock.patch.object(accounts, "_run", lambda argv, seconds=20: (ran.append(argv), (0, '{"loggedIn": true, "authMethod": "claude.ai"}'))[1]):
            accounts._CACHE.clear()
            rows = {r["id"]: r for r in accounts.status(cfg, fresh=True)}
        self.assertEqual((rows["claude"]["installed"], rows["claude"]["signed_in"]), (True, True))
        self.assertEqual((rows["codex"]["installed"], rows["codex"]["signed_in"]), (False, False))
        self.assertIn("Install the Codex CLI", rows["codex"]["install"])
        self.assertEqual(ran, [["C:/tools/claude.exe", "auth", "status", "--json"]], "only the installed one, with its own status command")

    def test_signing_in_runs_the_tools_own_sign_in(self):
        cfg = types.SimpleNamespace(agents={})
        started = []
        with mock.patch.object(accounts, "_program", lambda cfg, ident: "C:/tools/codex.exe"), \
                mock.patch.object(accounts, "_which", lambda name: "/usr/bin/" + name), \
                mock.patch.object(accounts.subprocess, "Popen", lambda argv, **kw: started.append(list(argv))):
            self.assertEqual(accounts.sign_in(cfg, "codex")["name"], "ChatGPT")
        said = " ".join(started[0]) if started else ""
        # Windows runs it in a window of its own, a Mac in Terminal, Linux in the terminal it has: the tool's own sign-in each time.
        self.assertTrue("C:/tools/codex.exe" in said and "login" in said, said)
        with self.assertRaises(ValueError):
            accounts.sign_in(cfg, "something-else")
        with mock.patch.object(accounts, "_program", lambda cfg, ident: ""):
            with self.assertRaises(ValueError) as said:
                accounts.sign_in(cfg, "claude")
        self.assertIn("Install Claude Code", str(said.exception))


if __name__ == "__main__":
    unittest.main()
