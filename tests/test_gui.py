import http.client
import json
import threading
import time
import unittest
from http.server import ThreadingHTTPServer

from jcc import config
from jcc.gui import GuiState, make_handler
from jcc.lock import watcher_lock
from tests.helpers import FAKE_GEMINI, FAKE_GROQ, EngineTestCase


class GuiTestCase(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.state = GuiState(config.load(), {
            "transport": self.transport,
            "spawner": lambda argv, cwd, env: self.spawned.append((argv, cwd, env)) or 1})
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.state, 0))
        self.port = self.httpd.server_address[1]
        # rebuild the handler now that the real port is known (Host checks use it)
        self.httpd.RequestHandlerClass = make_handler(self.state, self.port)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        super().tearDown()

    def req(self, method, path, body=None, token=True, host=None, ctype="application/json",
            origin=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": host or f"127.0.0.1:{self.port}"}
        if token:
            headers["X-JCC-Token"] = self.state.token if token is True else token
        if body is not None:
            headers["Content-Type"] = ctype
        if origin:
            headers["Origin"] = origin
        c.request(method, path, body=json.dumps(body) if body is not None else None,
                  headers=headers)
        r = c.getresponse()
        data = r.read()
        c.close()
        try:
            return r.status, json.loads(data)
        except ValueError:
            return r.status, data.decode()


class TestGuiSecurity(GuiTestCase):
    def test_page_served_with_token_and_csp(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", "/", headers={"Host": f"127.0.0.1:{self.port}"})
        r = c.getresponse()
        html = r.read().decode()
        self.assertEqual(r.status, 200)
        self.assertIn(self.state.token, html)
        self.assertIn("connect-src 'self'", r.getheader("Content-Security-Policy"))
        c.close()

    def test_api_requires_token(self):
        self.assertEqual(self.req("GET", "/api/state", token=False)[0], 401)
        self.assertEqual(self.req("GET", "/api/state", token="wrong")[0], 401)
        self.assertEqual(self.req("POST", "/api/ask", {"text": "help"}, token=False)[0], 401)
        self.assertEqual(self.spawned, [])

    def test_foreign_host_and_origin_rejected(self):
        self.assertEqual(self.req("GET", "/", host="evil.example:80")[0], 403)
        self.assertEqual(self.req("GET", "/api/state", host="evil.example")[0], 403)
        status, _ = self.req("POST", "/api/ask", {"text": "/job build an app"},
                             origin="https://evil.example")
        self.assertEqual(status, 403)
        self.assertEqual(self.spawned, [])

    def test_cross_site_preflight_refused(self):
        self.assertEqual(self.req("OPTIONS", "/api/ask", token=False)[0], 403)

    def test_non_json_and_oversized_rejected(self):
        self.assertEqual(self.req("POST", "/api/ask", {"text": "help"}, ctype="text/plain")[0],
                         415)
        self.assertEqual(self.req("POST", "/api/ask", {"text": "x" * 400_001})[0], 413)

    def test_bad_receipt_id_rejected(self):
        self.assertEqual(self.req("GET", "/api/receipt?id=../../secrets")[0], 400)


class TestGuiApi(GuiTestCase):
    def test_ask_goes_through_engine_and_writes_receipt(self):
        status, r = self.req("POST", "/api/ask", {"text": "what is gravity"})
        self.assertEqual(status, 200)
        self.assertEqual((r["tier"], r["status"]), (2, "done"))
        self.assertTrue((self.vault / r["receipt"]).exists())
        self.assertTrue(r["obsidian"].startswith("obsidian://open?vault="))
        status, again = self.req("GET", f"/api/receipt?id={r['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(again["id"], r["id"])
        self.assertIn("Fake answer", again["answer"])

    def test_state_shape_and_no_keys(self):
        self.req("POST", "/api/ask", {"text": "help"})
        status, s = self.req("GET", "/api/state")
        self.assertEqual(status, 200)
        for k in ("core", "vault", "watcher", "keys", "agents", "projects", "usage", "recent", "jobs",
                  "approvals", "log"):
            self.assertIn(k, s)
        self.assertEqual(s["keys"]["gemini"], True)
        blob = json.dumps(s)
        self.assertNotIn(FAKE_GEMINI, blob)
        self.assertNotIn(FAKE_GROQ, blob)

    def test_tool_switch_and_guard_still_apply(self):
        _, r = self.req("POST", "/api/ask", {"text": "/job deploy the app to my server",
                                             "tool": "codex"})
        self.assertEqual(r["status"], "needs_approval")
        self.assertEqual(self.spawned, [])
        _, s = self.req("GET", "/api/state")
        self.assertEqual(len(s["approvals"]), 1)


class TestChatPermissionReminder(GuiTestCase):
    """The user's standard permission reminder must not block a read-only handoff
    sent through the chat, while a real deployment request still needs approval."""

    REMINDER = ("Ask me before deploying, publishing, pushing to Git, spending money, "
                "accessing my screen, or handling secrets.")

    def send(self, text):
        _, chat = self.req("POST", "/api/chats", {"title": "handoff"})
        status, out = self.req("POST", "/api/chat/send",
                               {"id": chat["id"], "text": text, "mode": "auto"})
        self.assertEqual(status, 200)
        return out["messages"][-1]

    def test_handoff_with_reminder_sentence_runs(self):
        last = self.send("Give me a read-only handoff of this project. " + self.REMINDER)
        self.assertNotEqual(last.get("status"), "needs_approval")
        self.assertNotIn("Blocked", str(last.get("content")))

    def test_handoff_with_reminder_on_its_own_line_runs(self):
        last = self.send("Give me a read-only handoff of this project\n\n- " + self.REMINDER)
        self.assertNotEqual(last.get("status"), "needs_approval")
        self.assertNotIn("Blocked", str(last.get("content")))

    def test_deploy_request_with_reminder_needs_approval(self):
        last = self.send("Deploy the latest build to the server.\n" + self.REMINDER)
        self.assertEqual(last.get("status"), "needs_approval")
        self.assertEqual(self.spawned, [])


class TestWatcherLock(EngineTestCase):
    def test_only_one_watcher(self):
        a = watcher_lock(self.state)
        b = watcher_lock(self.state)
        self.assertTrue(a.acquire())
        self.assertFalse(b.acquire())
        a.release()
        self.assertTrue(b.acquire())
        b.release()

    def test_watcher_thread_processes_inbox_and_stops(self):
        from jcc import watcher

        self.note("Inbox.md", "- [ ] help\n")
        old = time.time() - 10
        import os
        os.utime(self.vault / "Inbox.md", (old, old))
        stop = threading.Event()
        lines = []
        t = threading.Thread(target=watcher.run, args=(stop, 0.2, lines.append), daemon=True)
        t.start()
        for _ in range(50):
            if "- [x] help" in (self.vault / "Inbox.md").read_text("utf-8"):
                break
            time.sleep(0.1)
        stop.set()
        t.join(5)
        self.assertIn("- [x] help", (self.vault / "Inbox.md").read_text("utf-8"))
        self.assertFalse(t.is_alive())


if __name__ == "__main__":
    unittest.main()
