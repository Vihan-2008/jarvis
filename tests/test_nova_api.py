"""The new interface's server side, through the same local HTTP API the app uses."""
import http.client
import json
import os
import time
import unittest

from jcc import activity, live, pty_terminal
from tests.test_gui import GuiTestCase


class TestNovaApi(GuiTestCase):
    def raw(self, path):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", path, headers={"Host": f"127.0.0.1:{self.port}"})
        r = c.getresponse()
        body = r.read().decode("utf-8", errors="replace")
        c.close()
        return r.status, r.getheader("Content-Type"), body

    def test_page_and_scripts_are_served(self):
        status, _, page = self.raw("/")
        self.assertEqual(status, 200)
        for needed in ('href="/nova.css"', 'src="/nova-core.js"', 'src="/nova-rich.js"', 'src="/nova.js"', 'src="/nova-panels.js"', 'src="/nova-work.js"', 'src="/nova-security.js"', 'src="/nova-permissions.js"', 'src="/nova-routines.js"', 'src="/nova-kinds.js"', 'src="/nova-gallery.js"'):
            self.assertIn(needed, page)
        for path, kind, marker in (("/nova.css", "text/css", "--accent"), ("/nova.js", "text/javascript", "window.Nova"),
                                   ("/nova-core.js", "text/javascript", "NovaCore"), ("/nova-rich.js", "text/javascript", "NovaRich"),
                                   ("/nova-panels.js", "text/javascript", "registerPane"), ("/nova-work.js", "text/javascript", "registerPane({ id: 'agents'"), ("/nova-security.js", "text/javascript", "registerPane({ id: 'security'"), ("/nova-permissions.js", "text/javascript", "'/api/permissions'"),
                                   ("/nova-routines.js", "text/javascript", "registerPane({ id: 'routines'"),
                                   ("/nova-kinds.js", "text/javascript", "root.NovaKinds ="), ("/nova-gallery.js", "text/javascript", "N.openGallery = openGallery"),
                                   ("/vendor/xterm.js", "text/javascript", "Terminal"),
                                   ("/vendor/xterm.css", "text/css", ".xterm"), ("/vendor/addon-fit.js", "text/javascript", "FitAddon")):
            status, ctype, body = self.raw(path)
            self.assertEqual(status, 200, path)
            self.assertTrue(ctype.startswith(kind), path)
            self.assertIn(marker, body, path)
        self.assertEqual(self.raw("/vendor/../gui.py")[0], 404)

    def test_new_routes_need_the_token(self):
        for path in ("/api/live?id=20260101-010101-abcd", "/api/pty?id=x", "/api/web/frame", "/api/computer"):
            self.assertEqual(self.req("GET", path, token=False)[0], 401, path)
        for path in ("/api/files/save", "/api/pty", "/api/web", "/api/computer", "/api/routines"):
            self.assertEqual(self.req("POST", path, {"action": "start"}, token=False)[0], 401, path)

    def test_live_progress_for_a_request(self):
        rid = "20260101-010101-abcd"
        self.assertEqual(self.req("GET", "/api/live?id=" + rid)[1], {"id": rid, "steps": [], "text": "", "answering": False})
        feed = live.Feed("codex", self.jobs_root / rid / "live.jsonl")
        feed.emit("step", "Running: git status")
        feed.emit("say", "Half an answer")
        status, data = self.req("GET", "/api/live?id=" + rid)
        self.assertEqual((status, data["steps"][0]["text"], data["text"]), (200, "Running: git status", "Half an answer"))
        self.assertEqual(self.req("GET", "/api/live?id=../../x")[0], 400)

    def test_running_jobs_say_which_chat_they_belong_to(self):
        _, chat = self.req("POST", "/api/chats", {"title": "a"})
        self.req("POST", "/api/chat/send", {"id": chat["id"], "text": "Give me a read-only handoff of this project", "mode": "auto"})
        _, state = self.req("GET", "/api/state")
        self.assertTrue(state["jobs"])
        self.assertEqual(state["jobs"][0]["chat"], chat["id"])

    def test_two_chats_run_side_by_side_and_a_third_waits(self):
        ids = []
        for n in range(3):
            _, chat = self.req("POST", "/api/chats", {"title": f"chat {n}"})
            _, out = self.req("POST", "/api/chat/send", {"id": chat["id"], "text": f"Summarise topic number {n} for me", "mode": "chat"})
            ids.append((chat["id"], out["messages"][-1]["status"]))
        self.assertEqual([status for _, status in ids], ["running", "running", "queued"])
        self.assertEqual(len(self.spawned), 2)
        _, state = self.req("GET", "/api/state")
        self.assertEqual({job["chat"] for job in state["jobs"]}, {cid for cid, _ in ids})

    def test_computer_control_is_off_until_switched_on(self):
        status, data = self.req("GET", "/api/computer")
        self.assertEqual((status, data["enabled"], data["running"], data["mode"]), (200, False, False, "ask"))
        status, data = self.req("POST", "/api/computer", {"action": "start", "text": "Open Notepad and write a list"})
        self.assertEqual(status, 400)
        self.assertIn("off", data["error"])
        self.assertEqual(self.req("POST", "/api/computer", {"action": "settings", "enabled": "yes"})[0], 400)
        status, data = self.req("POST", "/api/computer", {"action": "settings", "enabled": True, "mode": "ask"})
        self.assertEqual((status, data["enabled"]), (200, True))
        status, data = self.req("POST", "/api/computer", {"action": "start", "text": "Log in to my bank and send money"})
        self.assertEqual(status, 400)
        self.assertEqual(self.req("POST", "/api/computer", {"action": "explode"})[0], 400)

    def test_browser_requests_are_validated_without_starting_a_browser(self):
        self.assertEqual(self.req("POST", "/api/web", {"action": "open", "query": ""})[0], 400)
        self.assertEqual(self.req("POST", "/api/web", {"action": "open", "query": "https://me:pw@site.com"})[0], 400)
        self.assertEqual(self.req("POST", "/api/web", {"action": "nope"})[0], 400)
        status, snap = self.req("GET", "/api/web/frame")
        self.assertEqual((status, snap["running"], snap["image"], snap["login_offer"], snap["can_fill"]), (200, False, "", None, False))
        self.assertIsNone(self.state.web.proc)

    @unittest.skipUnless(pty_terminal.AVAILABLE, "needs a pseudo-console (ConPTY on Windows, pty elsewhere)")
    def test_terminal_over_http(self):
        status, started = self.req("POST", "/api/pty", {"action": "start", "cols": 80, "rows": 20})
        self.assertEqual(status, 200)
        line = "echo web-$(40+2)\r" if os.name == "nt" else "echo web-$((40+2))\r"       # PowerShell, or the user's own shell
        try:
            self.assertEqual(self.req("POST", "/api/pty", {"action": "input", "id": started["id"], "data": line})[0], 200)
            text, position, deadline = "", 0, time.time() + 25
            while "web-42" not in text and time.time() < deadline:
                _, chunk = self.req("GET", f"/api/pty?id={started['id']}&since={position}&wait=1")
                text, position = text + chunk["data"], chunk["next"]
            self.assertIn("web-42", text)
            self.assertEqual(self.req("POST", "/api/pty", {"action": "resize", "id": started["id"], "cols": 100, "rows": 30})[0], 200)
        finally:
            self.assertEqual(self.req("POST", "/api/pty", {"action": "stop", "id": started["id"]})[1], {"stopped": True})
        self.assertEqual(self.req("GET", f"/api/pty?id={started['id']}&since=0")[0], 400)
        self.assertEqual(self.req("POST", "/api/pty", {"action": "input", "id": "missing", "data": "x"})[0], 400)

    def test_timeline_and_live_steps_combine_for_a_running_reply(self):
        rid = "20260101-020202-beef"
        activity.emit(self.state.cfg, rid, "planned", "Chose a model.", agent="claude", model="sonnet")
        status, data = self.req("GET", "/api/timeline?id=" + rid)
        self.assertEqual((status, data["events"][0]["stage"]), (200, "planned"))


if __name__ == "__main__":
    unittest.main()
