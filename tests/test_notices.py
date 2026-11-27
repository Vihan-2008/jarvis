"""The Windows notification when JARVIS finishes something (jcc/notices.py): one owner, fixed words, never while the owner
is looking at JARVIS, and never twice for the same ending. The window's own part (sound and toast) is in
tests/finish_ui.test.js."""
import http.client
import json
import os
import shutil
import subprocess
import time
import unittest
from pathlib import Path

from jcc import activity, config, learning, notices
from tests.helpers import EngineTestCase
from tests.test_gui import GuiTestCase


class NoticeTests(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.load()
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)

    def tray_up(self):
        (self.cfg.state_dir / "tray-alive").write_text("", "utf-8")

    def test_a_finished_task_is_handed_to_the_tray_with_its_chat_and_nothing_else(self):
        self.tray_up()
        self.assertEqual(notices.finished(self.cfg, "turn-1", "done", chat="chat_42", background=True), "queued")
        notes = notices.take(self.cfg)
        self.assertEqual(notes, [{"status": "done", "chat": "chat_42"}])
        note_files = list((self.cfg.state_dir / notices.FOLDER).iterdir())
        self.assertTrue(all(p.suffix == ".shown" for p in note_files), "a note is taken once")
        self.assertEqual(notices.take(self.cfg), [])
        self.assertEqual(notices.finished(self.cfg, "turn-1", "done", chat="chat_42"), "duplicate", "never shown twice")
        self.assertEqual(notices.finished(self.cfg, "turn-1", "failed", chat="chat_42"), "queued", "another ending of the same work is news")

    def test_what_is_shown_is_fixed_words_never_what_was_asked(self):
        self.tray_up()
        notices.finished(self.cfg, "job-9", "failed", chat="../../evil chat\nwith words")
        note = json.loads(next((self.cfg.state_dir / notices.FOLDER).glob("*.json")).read_text("utf-8"))
        self.assertEqual(set(note), {"status", "chat", "at"})
        self.assertEqual(note["chat"], "", "anything that is not a chat id is dropped")
        self.assertEqual(notices.COPY["failed"], ("JARVIS could not finish", "A task did not finish. Open JARVIS to see why."))

    def test_nothing_while_the_owner_is_looking_or_listening_or_has_switched_it_off(self):
        self.tray_up()
        (self.cfg.state_dir / "ui-active").write_text(str(time.time()), "utf-8")
        self.assertEqual(notices.finished(self.cfg, "a", "done"), "focused")
        os.utime(self.cfg.state_dir / "ui-active", (time.time() - 60, time.time() - 60))
        self.assertEqual(notices.finished(self.cfg, "b", "done", spoken=True), "spoken")
        self.assertEqual(notices.finished(self.cfg, "c", "done", seconds=2, background=False), "quick", "an answer that came at once")
        self.assertEqual(notices.finished(self.cfg, "d", "failed", seconds=2, background=False), "queued", "a failure always counts")
        self.assertEqual(notices.finished(self.cfg, "e", "cancelled"), "ignored", "the owner stopped it")
        learning.configure(self.cfg, {"desktop_alerts": False})
        self.assertEqual(notices.finished(self.cfg, "f", "done"), "off")

    def test_without_the_tray_helper_nothing_is_left_waiting_in_a_test(self):
        self.assertEqual(notices.finished(self.cfg, "g", "done"), "no-tray")
        self.assertFalse((self.cfg.state_dir / notices.FOLDER).exists())

    def test_old_notes_are_not_shown_late_and_old_markers_are_cleared(self):
        self.tray_up()
        notices.finished(self.cfg, "h", "done", now=time.time() - 3600)
        self.assertEqual(notices.take(self.cfg), [], "an hour-old note is no news")
        marker = next((self.cfg.state_dir / notices.FOLDER).glob("*.shown"))
        os.utime(marker, (time.time() - 2 * notices.KEEP, time.time() - 2 * notices.KEEP))
        notices.take(self.cfg)
        self.assertFalse(marker.exists())

    def test_a_background_job_goes_through_the_same_owner(self):
        self.tray_up()
        rid = "20261127-101010-abcd"
        (self.vault / "Jobs").mkdir(exist_ok=True)
        (self.vault / "Jobs" / f"{rid}.md").write_text("---\nid: " + rid + "\nchat_id: chat_7\n---\n", "utf-8")
        activity.alert(self.cfg, rid, "needs_approval")
        self.assertEqual(notices.take(self.cfg), [{"status": "needs_approval", "chat": "chat_7"}])
        activity.alert(self.cfg, rid, "needs_approval")
        self.assertEqual(notices.take(self.cfg), [], "the same status again is not news")

    def test_the_most_urgent_is_said_and_a_chat_is_named_only_when_asked(self):
        from jcc.chats import Chats
        chats = Chats(self.cfg)
        long = chats.create("Summarize the quarterly report and then draft an email to the whole team about it")["id"]
        odd = chats.create("Line one\n\twith a tab")["id"]
        waiting = [{"status": "needs_approval", "chat": "c1"}, {"status": "done", "chat": long}, {"status": "failed", "chat": "c3"}]
        self.assertEqual(notices.words(self.cfg, waiting),
                         ("JARVIS needs your OK", "JARVIS needs your OK to continue. (3 tasks ended. Open JARVIS to see them.)", "c1"),
                         "a question for the owner is never hidden behind a later ending")
        self.assertEqual(notices.words(self.cfg, [{"status": "done", "chat": long}]), ("JARVIS finished", "JARVIS finished a task.", long),
                         "no chat name unless the owner asked for it")
        learning.configure(self.cfg, {"notice_titles": True})
        self.assertEqual(notices.words(self.cfg, [{"status": "done", "chat": long}])[1],
                         "\u201cSummarize the quarterly report and then draft an email to\u2026\u201d", "at most 60 characters, cut between words")
        self.assertEqual(notices.words(self.cfg, [{"status": "done", "chat": long}, {"status": "done", "chat": odd}])[1],
                         "\u201cLine one with a tab\u201d and 1 more. Open JARVIS to see them.", "on one line; the latest of equals is said")
        chats.set_deleted(odd, True)
        self.assertEqual(notices.chat_name(self.cfg, odd), "", "a deleted chat is not named")
        self.assertEqual(notices.chat_name(self.cfg, "20990101-000000-abcd"), "", "nor one that is not there")
        self.assertEqual(notices.chat_name(self.cfg, "../../x"), "")

    def test_preferences_change_one_at_a_time(self):
        self.assertTrue(learning.settings(self.cfg)["done_sound"])
        self.assertFalse(learning.settings(self.cfg)["notice_titles"], "a chat's name in a notification only when asked for")
        saved = learning.configure(self.cfg, {"done_sound": False})
        self.assertEqual((saved["done_sound"], saved["adaptive_routing"], saved["desktop_alerts"]), (False, True, True))
        for bad in ({}, {"done_sound": "no"}, {"unknown": True}, "on"):
            with self.assertRaises(ValueError):
                learning.configure(self.cfg, bad)


class WindowRulesTests(unittest.TestCase):
    def test_the_window_rules_pass(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is not installed")
        result = subprocess.run([node, "--test", "tests/finish_ui.test.js"], cwd=Path(__file__).resolve().parents[1], capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout[-2000:] + result.stderr[-1000:])


class NoticeClickTests(GuiTestCase):
    def tray(self, body):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("POST", "/api/tray", body=json.dumps(body),
                  headers={"Host": f"127.0.0.1:{self.port}", "X-JCC-Tray": self.state.tray_key, "Content-Type": "application/json"})
        r = c.getresponse()
        out = (r.status, json.loads(r.read()))
        c.close()
        return out

    def test_a_click_on_the_notification_opens_that_chat_in_the_window(self):
        self.assertEqual(self.tray({"action": "open_chat", "text": "chat_42"})[0], 200)
        events = self.state.assistant.poll(0)["events"]
        self.assertEqual([(e["k"], e.get("chat")) for e in events if e["k"] == "open_chat"], [("open_chat", "chat_42")])
        self.tray({"action": "open_chat", "text": "<script>"})
        self.assertEqual(len([e for e in self.state.assistant.poll(0)["events"] if e["k"] == "open_chat"]), 1, "only a chat id")
