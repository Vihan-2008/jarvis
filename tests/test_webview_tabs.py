"""Browser tabs, uploads, downloads and full screen, against a local page. No internet."""
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
from tests.test_webview import MemoryStore

PAGE = b"""<!doctype html><title>Tab %s</title><body><h1 id=h>Page %s</h1>
<input type=file id=f onchange="document.getElementById('h').textContent='got '+this.files[0].name+' '+this.files[0].size">
<button id=full onclick="document.documentElement.requestFullscreen()">full</button></body>"""


class Pages(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return

    def do_GET(self):
        name = self.path.strip("/").encode() or b"home"
        body = PAGE % (name, name)
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@unittest.skipUnless(os.name == "nt" and webview.find_browser(), "the built-in browser drives Edge or Chrome over a private Windows pipe")
class TestTabsAndFiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="jcc-webtabs-"))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Pages)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.view = webview.WebView(SimpleNamespace(state_dir=cls.tmp), MemoryStore())

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

    def js(self, expression):
        return self.view.call("Runtime.evaluate", {"expression": expression, "returnByValue": True, "userGesture": True})["result"].get("value")

    def test_1_tabs_open_switch_and_close(self):
        self.view.open(self.base + "/one")
        self.settle(lambda s: not s["loading"] and s["url"].endswith("/one") and s["image"])
        self.view.new_tab(self.base + "/two")
        snap = self.settle(lambda s: not s["loading"] and s["url"].endswith("/two") and len(s["tabs"]) == 2 and s["image"])
        titles = {t["title"]: t for t in snap["tabs"]}
        self.assertEqual(set(titles), {"Tab one", "Tab two"})
        self.assertTrue(titles["Tab two"]["active"])
        self.view.switch_tab(titles["Tab one"]["id"])
        self.settle(lambda s: s["url"].endswith("/one") and s["image"])
        self.assertEqual(self.js("document.title"), "Tab one")
        self.view.close_tab(titles["Tab one"]["id"])
        snap = self.settle(lambda s: len(s["tabs"]) == 1 and s["url"].endswith("/two"))
        self.assertEqual(self.js("document.title"), "Tab two")
        with self.assertRaises(ValueError):
            self.view.switch_tab("missing")

    def test_2_a_page_can_be_given_a_file(self):
        self.view.open(self.base + "/upload")
        self.settle(lambda s: not s["loading"] and s["url"].endswith("/upload"))
        with self.assertRaises(ValueError):
            self.view.upload("notes.txt", b"hello")
        box = self.js("(()=>{const r=document.getElementById('f').getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]})()")
        self.view.inputs([{"t": "mousePressed", "x": box[0], "y": box[1], "b": "left", "bs": 1, "c": 1},
                          {"t": "mouseReleased", "x": box[0], "y": box[1], "b": "left", "bs": 0, "c": 1}])
        self.settle(lambda s: s["file_request"])
        with self.assertRaises(ValueError):
            self.view.upload("empty.txt", b"")
        self.assertEqual(self.view.upload("..\\evil/notes.txt", b"hello")["uploaded"], "notes.txt")
        self.settle(lambda s: not s["file_request"])
        time.sleep(0.3)
        self.assertEqual(self.js("document.getElementById('h').textContent"), "got notes.txt 5")

    def test_3_page_full_screen_is_reported_and_can_be_left(self):
        self.view.open(self.base + "/video")
        self.settle(lambda s: not s["loading"] and s["url"].endswith("/video"))
        box = self.js("(()=>{const r=document.getElementById('full').getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]})()")
        self.view.inputs([{"t": "mousePressed", "x": box[0], "y": box[1], "b": "left", "bs": 1, "c": 1},
                          {"t": "mouseReleased", "x": box[0], "y": box[1], "b": "left", "bs": 0, "c": 1}])
        self.settle(lambda s: s["fullscreen"])
        self.view.leave_fullscreen()
        time.sleep(0.4)
        self.assertFalse(self.js("!!document.fullscreenElement"))
        self.assertFalse(self.view.snapshot(-1)["fullscreen"])

    def test_4_closing_the_last_tab_stops_the_browser(self):
        self.view.open(self.base + "/last")
        snap = self.settle(lambda s: s["tabs"])
        for tab in snap["tabs"][1:]:
            self.view.close_tab(tab["id"])
        self.assertTrue(self.view.close_tab(self.view.active).get("last"))
        self.assertFalse(self.view.running())
        self.assertEqual(self.view.snapshot(-1)["tabs"], [])


if __name__ == "__main__":
    unittest.main()
