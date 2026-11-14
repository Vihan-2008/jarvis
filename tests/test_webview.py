"""The built-in browser. The live tests use a local page and a fake credential store."""
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from jcc import webview

LOGIN = b"""<!doctype html><title>Members</title><body><h1>Hello page</h1><p>Visible words here.</p>
<form onsubmit="event.preventDefault()"><input name="email" type="email"><input name="pw" type="password">
<button id="go">Enter</button></form></body>"""
PRIVATE = b"<!doctype html><title>Sign in to your bank</title><body>Balance: 100</body>"


class Pages(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return

    def do_GET(self):
        body = PRIVATE if self.path.startswith("/private") else LOGIN
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class MemoryStore:
    def __init__(self):
        self.items = {}

    def get(self, name):
        return self.items.get(name)

    def set(self, name, value):
        self.items[name] = value

    def delete(self, name):
        self.items.pop(name, None)


class TestAddresses(unittest.TestCase):
    def test_addresses_and_searches(self):
        self.assertEqual(webview.target_url("example.com/a"), "https://example.com/a")
        self.assertEqual(webview.target_url("localhost:3000"), "http://localhost:3000")
        self.assertEqual(webview.target_url("https://a.b/c?d=1"), "https://a.b/c?d=1")
        self.assertTrue(webview.target_url("how to bake bread").startswith("https://www.google.com/search?q=how"))
        self.assertTrue(webview.target_url("javascript:alert(1)").startswith("https://www.google.com/search?q="))
        for bad in ("", " ", "https://user:secret@site.com", "x" * 2001):
            with self.assertRaises(ValueError, msg=bad):
                webview.target_url(bad)

    def test_site_names(self):
        self.assertEqual(webview.site_of("https://Mail.Example.com/inbox?x=1"), "mail.example.com")
        self.assertEqual(webview.site_of("http://localhost:8080/"), "localhost:8080")
        self.assertEqual(webview.site_of("about:blank"), "")

    def test_saved_sign_ins_belong_to_protected_pages_only(self):
        self.assertEqual(webview.sign_in_site("https://Mail.Example.com/inbox"), "mail.example.com")
        self.assertEqual(webview.sign_in_site("http://mail.example.com/inbox"), "", "an unprotected copy of a site is never offered your password")
        self.assertEqual(webview.sign_in_site("http://localhost:3000/login"), "localhost:3000", "pages on this PC itself are fine")
        self.assertEqual(webview.sign_in_site("http://127.0.0.1:8000/"), "127.0.0.1:8000")
        for other in ("ftp://example.com/", "about:blank", "file:///C:/x.html", "http://192.168.1.10/"):
            self.assertEqual(webview.sign_in_site(other), "", other)


@unittest.skipUnless(os.name == "nt" and webview.find_browser(), "the built-in browser drives Edge or Chrome over a private Windows pipe")
class TestLiveBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="jcc-webtest-"))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Pages)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.store = MemoryStore()
        cls.view = webview.WebView(SimpleNamespace(state_dir=cls.tmp), cls.store)

    @classmethod
    def tearDownClass(cls):
        cls.view.stop()
        cls.server.shutdown()
        time.sleep(0.5)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def settle(self, check, seconds=15):
        deadline, seq = time.time() + seconds, -1
        while time.time() < deadline:
            snap = self.view.snapshot(seq, 0.5)
            seq = snap["seq"]
            if check(snap):
                return snap
        self.fail("the page did not reach the expected state")

    def run_js(self, expression):
        return self.view.call("Runtime.evaluate", {"expression": expression, "returnByValue": True})["result"].get("value")

    def test_1_page_loads_and_can_be_read(self):
        self.view.open(self.base + "/members")
        snap = self.settle(lambda s: s["image"] and not s["loading"] and s["url"].endswith("/members"))
        self.assertTrue(snap["running"])
        self.assertGreater(len(snap["image"]), 500)
        page = self.view.page_text(True)
        self.assertEqual(page["title"], "Members")
        self.assertIn("Visible words here.", page["text"])

    def test_2_sign_in_is_offered_saved_and_filled_never_shared(self):
        self.view.open(self.base + "/members")
        self.settle(lambda s: not s["loading"] and s["url"].endswith("/members"))
        self.run_js("document.querySelector('[name=email]').value='me@example.com';document.querySelector('[name=pw]').value='correct horse';document.getElementById('go').click();1")
        snap = self.settle(lambda s: s["login_offer"])
        self.assertEqual(snap["login_offer"]["user"], "me@example.com")
        self.assertNotIn("correct horse", json.dumps(snap), "the password itself never goes to the panel")
        self.assertNotIn("correct horse", self.view.page_text(True)["text"], "typed values are never part of shared page text")
        self.assertEqual(self.store.items, {}, "nothing is stored before the owner agrees")
        self.view.login("save")
        site = webview.site_of(self.base)
        self.assertEqual(json.loads(self.store.items["web/" + site]), {"u": "me@example.com", "p": "correct horse"})
        self.view.reload()
        snap = self.settle(lambda s: not s["loading"] and s["can_fill"] and not s["login_offer"])
        time.sleep(0.4)
        self.assertEqual(self.run_js("document.querySelector('[name=pw]').value"), "")
        self.view.login("fill")
        self.assertEqual(self.run_js("document.querySelector('[name=email]').value+'|'+document.querySelector('[name=pw]').value"),
                         "me@example.com|correct horse")
        self.view.login("forget")
        self.assertNotIn("web/" + site, self.store.items, "forgetting really deletes the saved sign-in")
        self.assertFalse(self.view.snapshot(-1)["can_fill"])
        with self.assertRaises(ValueError):
            self.view.login("fill")

    def test_2b_the_hidden_browser_opens_no_network_port(self):
        import subprocess
        self.view.open(self.base + "/members")
        self.settle(lambda s: not s["loading"] and s["url"].endswith("/members"))
        count = subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                                f"(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object OwningProcess -eq {self.view.proc.pid} | Measure-Object).Count"],
                               capture_output=True, text=True, timeout=60).stdout.strip()
        self.assertEqual(count, "0", "it is driven over a private pipe, so no other program or Windows account can reach its controls")
        self.assertFalse((self.tmp / "webview-profile" / "DevToolsActivePort").exists())

    def test_3_private_pages_are_not_shared_automatically(self):
        self.view.open(self.base + "/private")
        self.settle(lambda s: not s["loading"] and s["url"].endswith("/private"))
        time.sleep(0.3)
        self.assertTrue(self.view.page_text(True).get("skipped"))
        self.assertIn("Balance", self.view.page_text(False)["text"], "the owner can still ask for it explicitly")

    def test_4_input_is_validated(self):
        self.view.inputs([{"t": "mouseMoved", "x": 5, "y": 5}, {"t": "keyDown", "key": "a", "text": "a", "vk": 65}, "junk", {"t": "other"}])
        with self.assertRaises(ValueError):
            self.view.inputs("click")
        with self.assertRaises(ValueError):
            self.view.resize("wide", 2)
        with self.assertRaises(ValueError):
            self.view.login("steal")


if __name__ == "__main__":
    unittest.main()
