import unittest

from jcc.guard import personal_reason, tier3_block_reason
from jcc.redact import redact


class TestGuard(unittest.TestCase):
    def test_permission_reminder_does_not_authorize_actions(self):
        from jcc.guard import tier3_block_reason
        reminder = ("Ask me before deploying, publishing, pushing to Git, spending money, "
                    "accessing my screen, or handling secrets.")
        self.assertIsNone(tier3_block_reason("Give me a read-only handoff. " + reminder))
        for request in ("Deploy now. " + reminder, reminder + " Deploy now.",
                        "Don't ask me before deploying.", "Ask me before deploying, then deploy now."):
            self.assertEqual(tier3_block_reason(request), "deploying")

    def test_permission_reminder_in_common_layouts(self):
        reminder = ("Ask me before deploying, publishing, pushing to Git, spending money, "
                    "accessing my screen, or handling secrets")
        allowed = [
            f"Give me a read-only handoff of this project\n\n{reminder}.",  # own line
            f"Read-only handoff please:\n- summarise the project\n- {reminder}.",  # bullet
            f"Read-only handoff:\n1. summarise it\n2. {reminder}",  # numbered, no period
            f"Give me a read-only handoff. {reminder}!",  # exclamation
            f"Give me a read-only handoff\r\n{reminder}.\r\n",  # Windows line endings
            f"Use [[Projects/jarvis-app-dev/Memory]] for context. Please {reminder.lower()}.",
        ]
        for text in allowed:
            self.assertIsNone(tier3_block_reason(text), repr(text))
        blocked = [
            f"{reminder}\nDeploy the app now.",  # real action on the next line
            f"- {reminder}, then deploy now.",  # action appended inside the bullet
            f"Read-only handoff\n- {reminder}\n- deploy it to the server",
            f"Please deploy it. {reminder}!",
            f"I want you to deploy it and {reminder.lower()}.",  # not a standalone reminder
        ]
        for text in blocked:
            self.assertEqual(tier3_block_reason(text), "deploying", repr(text))

    def test_tier3_blocks_word_forms(self):
        for text in ["deploys the app", "redeploying it", "deleted the logs", "removes files",
                     "wiping the disk", "git push to main", "ssh into the box",
                     "read my API keys", "store passwords",
                     "change risk_limits", "buy a domain", "send an email to my teacher",
                     r"open C:\Users\kiran\Garden-Planner\src"]:
            self.assertIsNotNone(tier3_block_reason(text, [r"C:\Users\kiran\Garden-Planner"]),
                                 text)

    def test_tier3_allows_normal_work(self):
        for text in ["build a flashcard app", "write a python script that renames photos",
                     "create a website for my school club", "research solid state batteries",
                     "edit garden-planner", "remove an unused function", "fix token counting"]:
            self.assertIsNone(tier3_block_reason(text), text)

    def test_personal_detection(self):
        self.assertEqual(personal_reason("what is my bank balance"), "banking")
        self.assertEqual(personal_reason("how is the trading bot doing"), "trading bot data")
        self.assertIsNone(personal_reason("explain how banks create money in economics"[:0]))

    def test_redact_patterns(self):
        s = redact("key AIzaSyA1234567890abcdefghijklmn and gsk_abcdefghij1234567890 and "
                   "password: hunter22 and Bearer abcdefghijklmnopqrstu")
        for leaked in ("AIzaSyA", "gsk_abc", "hunter22", "abcdefghijklmnopqrstu"):
            self.assertNotIn(leaked, s)


if __name__ == "__main__":
    unittest.main()


class TestProviderErrors(unittest.TestCase):
    def test_error_detail_formats(self):
        from jcc.llm import error_detail
        self.assertIn("high demand", error_detail(
            {"error": [{"error": {"code": 503, "message": "This model is experiencing high demand"}}]}))
        self.assertEqual(error_detail({"error": {"message": "bad key gsk_abcdefghij1234567890"}}),
                         "bad key [REDACTED]")
        self.assertEqual(error_detail({}), "")

    def test_requests_send_a_user_agent(self):
        import urllib.request
        from unittest import mock
        from jcc import llm
        seen = {}

        class Resp:
            status = 200
            def read(self): return b"{}"
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_open(req, timeout):
            seen["ua"] = req.get_header("User-agent")
            return Resp()

        with mock.patch.object(urllib.request, "urlopen", fake_open):
            llm.urllib_transport("https://example.invalid", {}, {})
        self.assertTrue(seen["ua"].startswith("jarvis-command/"))
