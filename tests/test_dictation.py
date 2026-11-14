"""Dictation anywhere and the tray's "talk to JARVIS" shortcut, with a fake microphone and a fake keyboard."""
import http.client
import json
import struct
import time
import unittest
from types import SimpleNamespace

from jcc import config, dictate
from tests.helpers import EngineTestCase
from tests.test_gui import GuiTestCase


class FakeRecorder:
    sound, done, broken = b"\x01\x02" * 16000, False, False

    def start(self):
        if self.broken:
            raise ValueError("The microphone could not be opened.")

    def finished_speaking(self):
        return self.done

    def stop(self):
        return self.sound


class TestDictation(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.load()
        self.typed, self.told, self.beeps, self.heard = [], [], [], []
        self._released = dictate.keys_released
        dictate.keys_released = lambda timeout=2.0: True
        FakeRecorder.sound, FakeRecorder.done, FakeRecorder.broken = b"\x01\x02" * 16000, False, False

    def tearDown(self):
        dictate.keys_released = self._released
        super().tearDown()

    def make(self, says="  Hello   world. "):
        def hear(sound):
            self.heard.append(len(sound))
            return says
        return dictate.Dictation(self.cfg, self.told.append, FakeRecorder, SimpleNamespace(perform=self.typed.append), hear, self.beeps.append)

    def wait(self, check, seconds=3):
        deadline = time.time() + seconds
        while time.time() < deadline and not check():
            time.sleep(0.02)
        return check()

    def test_press_speak_press_and_the_words_are_typed(self):
        session = self.make()
        self.assertEqual(session.toggle(), "listening")
        self.assertTrue(session.listening)
        self.assertEqual(self.typed, [], "nothing is typed while you are still speaking")
        self.assertEqual(session.toggle(), "typing")
        self.assertTrue(self.wait(lambda: self.typed))
        self.assertEqual(self.typed, [{"action": "type", "text": "Hello world. "}])
        self.assertEqual((self.beeps, self.heard, session.listening), ([880, 660], [32000], False))

    def test_it_finishes_by_itself_when_you_stop_talking(self):
        session = self.make("Send the report on Friday.")
        session.toggle()
        FakeRecorder.done = True
        self.assertTrue(self.wait(lambda: self.typed), "a pause after speaking ends the dictation without a second press")
        self.assertEqual(self.typed[0]["text"], "Send the report on Friday. ")

    def test_a_noise_in_the_room_is_never_typed(self):
        """A speech service asked to make words out of a noise will make some. So a recording with no speech in it is not sent."""
        FakeRecorder.heard_speech = False
        try:
            session = self.make("JARVIS.")
            session.toggle()
            session.toggle()
            self.assertTrue(self.wait(lambda: self.told))
            self.assertEqual((self.typed, self.heard, self.told), ([], [], ["Nothing was heard. Press the shortcut and speak again."]))
        finally:
            del FakeRecorder.heard_speech

    def test_nothing_is_typed_when_nothing_was_said(self):
        session = self.make("")
        session.toggle()
        session.toggle()
        self.assertTrue(self.wait(lambda: self.told))
        self.assertEqual((self.typed, self.told), ([], ["Nothing was heard. Press the shortcut and speak again."]))
        FakeRecorder.sound = b"\x00" * 100
        session.toggle()
        session.toggle()
        time.sleep(0.3)
        self.assertEqual((self.typed, len(self.heard)), ([], 1), "a recording shorter than half a second is not even sent")

    def test_keys_still_held_down_do_not_turn_words_into_shortcuts(self):
        dictate.keys_released = lambda timeout=2.0: False
        session = self.make()
        session.toggle()
        session.toggle()
        self.assertTrue(self.wait(lambda: self.told))
        self.assertEqual((self.typed, self.told), ([], ["Let go of the keys, then try again."]))

    def test_problems_are_explained(self):
        FakeRecorder.broken = True
        session = self.make()
        self.assertEqual(session.toggle(), "unavailable")
        self.assertEqual(self.told, ["The microphone could not be opened."])
        self.assertFalse(session.listening)

    def test_loudness_of_sound(self):
        self.assertEqual(dictate.loudness(b""), 0.0)
        self.assertEqual(dictate.loudness(b"\x00\x00" * 400), 0.0)
        self.assertAlmostEqual(dictate.loudness(struct.pack("<400h", *([16384, -16384] * 200))), 0.5, places=2)


class TestWithoutWhisper(EngineTestCase):
    keys = False

    def test_dictation_says_what_is_missing(self):
        told = []
        session = dictate.Dictation(config.load(), told.append, FakeRecorder, SimpleNamespace(perform=lambda step: None))
        self.assertEqual(session.toggle(), "unavailable")
        self.assertIn("needs Whisper", told[0])


class TestTrayApi(GuiTestCase):
    def tray(self, body, key=None, origin=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": f"127.0.0.1:{self.port}", "X-JCC-Tray": key or self.state.tray_key, "Content-Type": "application/json"}
        if origin:
            headers["Origin"] = origin
        c.request("POST", "/api/tray", body=json.dumps(body), headers=headers)
        r = c.getresponse()
        out = (r.status, json.loads(r.read()))
        c.close()
        return out

    def test_the_tray_can_start_a_voice_chat_but_nothing_else_can(self):
        self.assertEqual((self.state.cfg.state_dir / "tray-key").read_text("utf-8"), self.state.tray_key)
        self.assertEqual(self.tray({"action": "listen"}, key="wrong")[0], 403)
        self.assertEqual(self.tray({"action": "listen"}, origin=f"http://127.0.0.1:{self.port}")[0], 403, "never from a web page")
        self.assertEqual(self.req("POST", "/api/tray", {"action": "listen"})[0], 403, "the page token is not the tray key")
        self.assertEqual(self.tray({"action": "shutdown"})[0], 400)
        self.state.assistant.hand_wait = 0.3
        self.assertEqual(self.tray({"action": "listen"}), (200, {"window": False}), "no window is open, so the tray opens one itself")
        self.assertEqual(self.req("POST", "/api/voice", {"action": "pending"})[1], {"text": "", "listen": True, "attend": False, "nudge": False}, "and that window starts listening")
        upto, got = self.req("GET", "/api/voice/events?since=0")[1]["next"], []

        def window():   # an open window is woken at once and comes to take the request
            data = self.req("GET", f"/api/voice/events?since={upto}&wait=8")[1]
            got.append(([e["k"] for e in data["events"]], data["waiting"], self.req("POST", "/api/voice", {"action": "pending"})[1]))

        import threading
        thread = threading.Thread(target=window)
        thread.start()
        time.sleep(0.3)
        self.state.assistant.hand_wait = 8
        self.assertEqual(self.tray({"action": "listen"}), (200, {"window": True}))
        thread.join(8)
        self.assertEqual(got, [(["wake"], True, {"text": "", "listen": True, "attend": False, "nudge": False})], "the open window is told to start listening")


if __name__ == "__main__":
    unittest.main()
