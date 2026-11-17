"""The NotchPixel island (jcc/notch.py): what is sent, when, and that nothing is sent unless the owner switched it on.

A small HTTP server on this computer stands in for NotchPixel."""
import os
import shutil
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from jcc import activity, notch

RID = "20261117-173000-abcd"


class Island(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.heard.append(dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query)))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


class NotchTest(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Island)
        self.server.heard = []
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.tmp = Path(tempfile.mkdtemp(prefix="jcc-test-notch-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.cfg = self.config(enabled=True)

    def config(self, **notch_settings):
        port = self.server.server_address[1]
        return SimpleNamespace(raw={"notch": {"port": port, **notch_settings}}, jobs_root=self.tmp / "jobs", state_dir=self.tmp / "state")

    def heard(self, session=RID):
        notch.flush(3)                    # (the stand-in writes a request down before it answers, so all sent is here now)
        return [row for row in self.server.heard if row.get("session") == session]

    def last(self, session=RID):
        rows = self.heard(session)
        return rows[-1] if rows else None

    def test_nothing_is_sent_unless_the_owner_switched_it_on(self):
        for cfg in (self.config(), self.config(enabled=False), self.config(enabled="yes"), SimpleNamespace(raw={}), SimpleNamespace()):
            notch.tell(cfg, RID, "working", "Running tests")
        self.assertEqual(self.heard(), [])

    def test_a_moment_reaches_the_island_with_its_name_and_session(self):
        notch.tell(self.cfg, RID, "working", "Running tests")
        self.assertEqual(self.last(), {"source": "custom", "name": "Jarvis", "event": "working", "session": RID, "detail": "Running tests"})

    def test_detail_is_redacted_put_on_one_line_and_kept_short(self):
        secret = "sk-ant-api03-" + "A" * 40
        url = notch.address(self.cfg, RID, "working", f"Using {secret}\n\n   now " + "x" * 300)
        detail = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))["detail"]
        self.assertNotIn(secret, detail)
        self.assertNotIn("\n", detail)
        self.assertLessEqual(len(detail), notch.DETAIL)

    def test_it_only_ever_calls_this_computer_and_refuses_a_bad_port(self):
        self.assertTrue(notch.address(self.cfg, RID, "done").startswith(f"http://127.0.0.1:{self.server.server_address[1]}/agent?"))
        with self.assertRaises(ValueError):
            notch.address(self.config(port=70000), RID, "done")

    def test_an_unknown_event_is_not_sent(self):
        notch.tell(self.cfg, RID, "exploded")
        self.assertEqual(self.heard(), [])

    def test_island_not_running_never_raises(self):
        with socket_closed() as port:
            notch.tell(self.config(port=port), RID, "working")
            notch.flush(2)

    def test_the_last_moment_of_a_session_is_the_one_shown(self):
        for event in ("thinking", "working", "working", "done"):
            notch.tell(self.cfg, RID, event)
        self.assertEqual(self.last()["event"], "done")

    def test_job_stages_show_as_the_owner_would_read_them(self):
        cases = {"planned": "thinking", "waiting": "thinking", "working": "working", "checking": "working",
                 "needs_approval": "waiting", "failed": "error", "done": "done", "cancelled": "end"}
        for n, (stage, event) in enumerate(cases.items()):
            rid = f"20261117-1730{n:02d}-abcd"
            activity.emit(self.cfg, rid, stage, "Agent is working in the isolated workspace.")
            self.assertEqual(self.last(rid)["event"], event, stage)
        self.assertEqual(self.last("20261117-173002-abcd")["detail"], "Agent is working in the isolated workspace.")

    def test_a_recovered_job_shows_its_final_status(self):
        with mock.patch.dict(os.environ, {"JCC_NO_CREDMAN": "1"}):
            activity.emit(self.cfg, RID, "recovered", "The worker stopped unexpectedly.")
            activity.alert(self.cfg, RID, "paused")
        self.assertEqual(self.last()["event"], "waiting")

    def test_a_request_shows_thinking_working_waiting_and_done(self):
        turns = {"chat-1": SimpleNamespace(id=RID)}
        notch.chat_event(self.cfg, "start", {"id": RID, "chat": "chat-1", "model": "haiku"}, turns)
        self.assertEqual(self.last()["event"], "thinking")
        notch.chat_event(self.cfg, "step", {"id": RID, "t": "Opening Calculator"}, turns)
        self.assertEqual((self.last()["event"], self.last()["detail"]), ("working", "Opening Calculator"))
        notch.chat_event(self.cfg, "confirm", {"id": "q1", "question": "Send the email?", "chat": "chat-1"}, turns)
        self.assertEqual((self.last()["event"], self.last()["detail"]), ("waiting", "Send the email?"))
        notch.chat_event(self.cfg, "confirmed", {"id": "q1", "approved": True}, turns)
        self.assertEqual(self.last()["event"], "working")
        notch.chat_event(self.cfg, "done", {"id": RID, "chat": "chat-1", "status": "failed"}, turns)
        self.assertEqual(self.last()["event"], "error")

    def test_compacting_a_conversation_is_left_off_the_island(self):
        notch.chat_event(self.cfg, "start", {"id": RID, "chat": "c", "model": "compact"}, {})
        notch.chat_event(self.cfg, "done", {"id": RID, "chat": "c", "status": "done", "compact": True}, {})
        self.assertEqual(self.heard(), [])

    def test_a_request_not_meant_for_jarvis_leaves_the_island(self):
        notch.chat_event(self.cfg, "done", {"id": RID, "chat": "c", "status": "ignored"}, {})
        self.assertEqual(self.last()["event"], "end")


class socket_closed:
    """A port on this computer that nothing listens on."""

    def __enter__(self):
        import socket
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            return probe.getsockname()[1]

    def __exit__(self, *exc):
        return False


if __name__ == "__main__":
    unittest.main()
