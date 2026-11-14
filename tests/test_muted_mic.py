"""A microphone that Windows has muted (its mute key, or Settings): then nothing at all reaches JARVIS. Found on the
owner's PC, where both microphones were muted and JARVIS seemed simply not to hear. It is now said where the owner looks,
and an Unmute button unmutes it when the owner presses it. The real microphone is never read or changed here."""
import json
import unittest
from unittest import mock

from jcc import config, connections, sound, wake
from tests.helpers import EngineTestCase
from tests.test_gui import GuiTestCase
from tests.test_wake import FakeListener, FakeRecorder


class TestItIsSaid(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.load()
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)

    def test_connections_says_the_microphone_is_muted_and_what_to_do(self):
        with mock.patch.object(sound, "mic_muted", lambda cfg: True):
            item = next(i for i in connections.overview(self.cfg) if i["id"] == "sound")
        self.assertEqual(item["state"], "problem")
        self.assertTrue(item["status"].startswith("Muted in Windows · "))
        self.assertIn("Unmute", item["how"])
        for unknown in (False, None):
            with mock.patch.object(sound, "mic_muted", lambda cfg, unknown=unknown: unknown):
                item = next(i for i in connections.overview(self.cfg) if i["id"] == "sound")
            self.assertEqual((item["state"], "Muted" in item["status"]), ("ok", False), "not muted, or not known: nothing is said")

    def test_the_wake_word_says_it_cannot_be_heard(self):
        muted = [True]
        ears = wake.Ears(self.cfg, lambda text: None, lambda text: None, FakeListener, FakeRecorder, lambda s: "", lambda p: None, lambda: False,
                         muted=lambda: muted[0])
        self.assertEqual(ears.note, "", "nothing is listening yet: nothing to say")
        ears.listener = FakeListener(lambda hit: None, ["jarvis"])
        self.assertIn('"Hey JARVIS" cannot be heard', ears.note)
        self.assertIn("Unmute", ears.note)
        muted[0] = False
        ears.mute_at = 0
        self.assertEqual(ears.note, "", "unmuted: it is no longer said")

    def test_a_wake_word_in_a_test_never_asks_about_the_real_microphone(self):
        ears = wake.Ears(self.cfg, lambda text: None, lambda text: None, FakeListener, FakeRecorder, lambda s: "", lambda p: None, lambda: False)
        self.assertIsNone(ears.muted)

    def test_the_question_itself_never_fails(self):
        real = sound.real_mic_muted                     # (the one tests/__init__.py set aside)
        with mock.patch.object(sound, "input_mute", side_effect=RuntimeError("audio service gone")):
            self.assertIsNone(real(self.cfg))
        if sound.os.name != "nt":
            self.assertIsNone(sound.input_mute("Microphone"), "off Windows it is simply not known")


class TestTheWindowAsksAndUnmutes(GuiTestCase):
    def test_the_voice_status_says_so_and_unmute_unmutes_only_when_asked(self):
        asked = []
        with mock.patch.object(sound, "mic_muted", lambda cfg: True):
            status, data = self.req("GET", "/api/speech")
        self.assertEqual((status, data["mic_muted"]), (200, True))
        with mock.patch.object(sound, "unmute_mic", lambda cfg: asked.append("unmute") or True), mock.patch.object(sound, "mic_muted", lambda cfg: False):
            status, data = self.req("POST", "/api/speech", {"action": "unmute"})
        self.assertEqual((status, data, asked), (200, {"ok": True, "mic_muted": False}, ["unmute"]))
        self.assertNotIn("unmute", json.dumps(self.req("GET", "/api/speech")[1].get("settings", {})), "it is not a setting that is kept")


if __name__ == "__main__":
    unittest.main()
