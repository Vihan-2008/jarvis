"""Choosing the microphone and the speakers. Windows' default stays the default; a chosen device is known by its name."""
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from jcc import config, dictate, sound, speech, wake
from tests.helpers import EngineTestCase
from tests.test_gui import GuiTestCase

MICS = ["Microphone (HyperX Quadcast)", "Microphone Array (Realtek(R) Au"]            # as Windows lists them: cut to 31 characters
SPEAKERS = ["Speakers (Realtek(R) Audio)", "LS24AG32x (NVIDIA High Definiti", "Speakers (HyperX Quadcast)"]


class TestDeviceNames(unittest.TestCase):
    def test_a_browsers_name_for_a_device_is_reduced_to_the_name_windows_shows(self):
        for label, name in (("Default - Microphone (HyperX Quadcast) (0951:16df)", "Microphone (HyperX Quadcast)"),
                            ("Communications - Speakers (HyperX Quadcast) (0951:16DF)", "Speakers (HyperX Quadcast)"),
                            ("Microphone Array (Realtek(R) Audio)", "Microphone Array (Realtek(R) Audio)"),
                            ("  Speakers   (Realtek(R) Audio) ", "Speakers (Realtek(R) Audio)"), ("Odd\x00name\n", "Odd name"), ("", ""), (None, "")):
            self.assertEqual(sound.plain(label), name, label)
        self.assertLessEqual(len(sound.plain("x" * 500)), 120)

    def test_the_chosen_name_finds_the_device_even_though_windows_shortens_names(self):
        self.assertEqual(sound.find("Microphone (HyperX Quadcast) (0951:16df)", MICS), 0)
        self.assertEqual(sound.find("Microphone Array (Realtek(R) Audio)", MICS), 1, "Windows cut this name off; the start is enough")
        self.assertEqual(sound.find("LS24AG32x (NVIDIA High Definition Audio)", SPEAKERS), 1)
        self.assertEqual(sound.find("Default - Speakers (Realtek(R) Audio)", SPEAKERS), 0)

    def test_nothing_chosen_or_not_connected_means_the_windows_default(self):
        self.assertIsNone(sound.find("", MICS))
        self.assertIsNone(sound.find("Headset (Unplugged Thing)", MICS))
        self.assertIsNone(sound.find("Microphone", MICS), "a shorter name is another device, not a match")
        self.assertIsNone(sound.find("Microphone (HyperX Quadcast)", []))

    def test_a_tone_never_raises(self):
        self.assertIn(sound.tone(880, 30, None, volume=0.0), (True, False))          # silent: only checks that the speakers can be opened
        self.assertIn(sound.tone(880, 30, 63, volume=0.0), (True, False), "a device that does not exist is simply not played on")


class TestChoiceIsSaved(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.load()
        self._inputs, self._outputs = sound.inputs, sound.outputs
        sound.inputs, sound.outputs = (lambda: list(MICS)), (lambda: list(SPEAKERS))

    def tearDown(self):
        sound.inputs, sound.outputs = self._inputs, self._outputs
        super().tearDown()

    def test_windows_default_is_the_default(self):
        current = speech.settings(self.cfg)
        self.assertEqual((current["mic"], current["speaker"]), ("", ""))
        self.assertEqual((sound.chosen_input(self.cfg), sound.chosen_output(self.cfg)), (None, None))

    def test_a_choice_is_kept_by_name_and_found_again(self):
        saved = speech.configure(self.cfg, {"mic": "Default - Microphone Array (Realtek(R) Audio)", "speaker": "Speakers (HyperX Quadcast) (0951:16df)"})
        self.assertEqual((saved["mic"], saved["speaker"]), ("Microphone Array (Realtek(R) Audio)", "Speakers (HyperX Quadcast)"))
        self.assertEqual((sound.chosen_input(self.cfg), sound.chosen_output(self.cfg)), (1, 2))
        sound.inputs = lambda: [MICS[0]]                                             # the chosen microphone is unplugged
        self.assertIsNone(sound.chosen_input(self.cfg), "the Windows default carries on")
        self.assertEqual(speech.settings(self.cfg)["mic"], "Microphone Array (Realtek(R) Audio)", "and the choice is remembered for when it is back")
        speech.configure(self.cfg, {"mic": "", "speaker": ""})
        self.assertEqual((sound.chosen_input(self.cfg), sound.chosen_output(self.cfg)), (None, None))
        for bad in ({"mic": 3}, {"speaker": None}, {"mic": ["x"]}):
            with self.assertRaises(speech.SpeechError):
                speech.configure(self.cfg, bad)

    def test_dictation_records_the_chosen_microphone(self):
        speech.configure(self.cfg, {"mic": "Microphone Array (Realtek(R) Audio)"})
        session = dictate.Dictation(self.cfg, lambda text: None, None, SimpleNamespace(perform=lambda step: None), lambda sound_: "", lambda pitch: None)
        self.assertEqual(session.make_recorder().device, 1)
        speech.configure(self.cfg, {"mic": ""})
        self.assertIsNone(session.make_recorder().device)

    def test_the_recorder_keeps_what_the_microphone_hears(self):
        made = []

        class FakeMicrophone:
            def __init__(self, device, piece):
                self.device, self.piece, self.on = device, piece, False
                made.append(self)

            def start(self, each, limit=None):
                self.on, self.each, self.limit = True, each, limit

            def alive(self):
                return self.on

            def stop(self):
                self.on = False

        original, sound.Microphone = sound.Microphone, FakeMicrophone
        try:
            recorder = dictate.Recorder(quiet=0.05, device=1)
            recorder.start()
            self.assertEqual((made[0].device, made[0].limit), (1, dictate.MAX_SECONDS))
            made[0].each(b"\x00\x00" * 1600)
            self.assertFalse(recorder.heard_speech)
            made[0].each(b"\x00\x40" * 1600)
            self.assertTrue(recorder.heard_speech)
            self.assertFalse(recorder.finished_speaking())
            made[0].each(b"\x00\x00" * 1600)
            time.sleep(0.1)
            self.assertTrue(recorder.finished_speaking(), "quiet after speech: the caller may stop by itself")
            self.assertEqual(len(recorder.stop()), 3 * 3200)
            self.assertFalse(made[0].on)
        finally:
            sound.Microphone = original


class FakeListener:
    made = []

    def __init__(self, heard, names, device=None):
        self.heard, self.names, self.device, self.alive = heard, names, device, False
        FakeListener.made.append(self)

    def start(self):
        self.alive = True

    def running(self):
        return self.alive

    def stop(self):
        self.alive = False


class TestWakeWordFollowsTheChoice(EngineTestCase):
    def test_the_listener_moves_to_the_chosen_microphone_and_back(self):
        cfg = config.load()
        FakeListener.made, chosen = [], [None]
        ears = wake.Ears(cfg, lambda text: None, lambda text: None, FakeListener, None, lambda sound_: "", lambda pitch: None, device=lambda: chosen[0])
        self.assertTrue(ears.sync())
        self.assertIsNone(FakeListener.made[0].device, "nothing chosen: the recogniser opens the Windows default itself")
        self.assertTrue(ears.sync())
        self.assertEqual(len(FakeListener.made), 1, "nothing changed, nothing restarted")
        chosen[0] = 1                                                               # another microphone was chosen in the settings
        self.assertTrue(ears.sync())
        self.assertEqual((len(FakeListener.made), FakeListener.made[0].alive, FakeListener.made[1].device), (2, False, 1))
        chosen[0] = None                                                            # it was unplugged, or the default was chosen again
        self.assertTrue(ears.sync())
        self.assertEqual((len(FakeListener.made), FakeListener.made[1].alive, FakeListener.made[2].device), (3, False, None))
        ears.stop()


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestRealListenerOnAChosenMicrophone(unittest.TestCase):
    def test_sound_handed_over_from_a_chosen_microphone_is_understood(self):
        """The recogniser normally opens Windows' default microphone itself. For a chosen one, JARVIS records it and
        hands the sound over through a private pipe. Here the "microphone" plays a made-up sentence at the speed of speech."""
        said = speech.sample_speech("Hey Jarvis, what time is it?")
        if len(said) < 16000:
            self.skipTest("Windows could not make a test sentence")
        track = b"\x00\x00" * 16000 + said + b"\x00\x00" * 48000

        class PlaysATrack:
            def __init__(self, device):
                self.device, self.on = device, False

            def start(self, each):
                self.on = True

                def run():
                    at, began = 0, time.time()
                    try:
                        while self.on:
                            each(track[at:at + 3200] if at < len(track) else b"\x00\x00" * 1600)
                            at += 3200
                            wait = began + at / 32000 - time.time()
                            if wait > 0:
                                time.sleep(wait)
                    except OSError:
                        pass
                    self.on = False
                threading.Thread(target=run, daemon=True).start()

            def stop(self):
                self.on = False

        hits = []
        listener = wake.Listener(hits.append, ["jarvis"], device=0, microphone=PlaysATrack)
        listener.start()
        try:
            self.assertTrue(listener.ready.wait(40))
            if listener.problem:
                self.skipTest("no offline recogniser on this PC: " + listener.problem)
            if listener.input != "chosen":
                self.skipTest("this PC does not allow the sound to be handed over; the Windows default is used instead")
            deadline = time.time() + 40
            while not hits and time.time() < deadline:
                time.sleep(0.2)
            self.assertEqual(len(hits), 1)
            self.assertEqual(wake.split(hits[0]["text"], ["jarvis"]), "what time is it")
            self.assertEqual(hits[0]["wav"][:4], b"RIFF")
            self.assertTrue(listener.running())
        finally:
            listener.stop()
        self.assertFalse(listener.running())


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestWindowsOwnVoice(EngineTestCase):
    def test_a_sentence_is_made_on_the_pc_and_the_helper_is_let_go_when_unused(self):
        voice = speech.LocalVoice()
        try:
            try:
                first = voice.say("Hello. The timer is done.")
            except speech.SpeechError as problem:
                self.skipTest(str(problem))
            self.assertGreater(len(first), 24000, "at least half a second of sound")
            self.assertEqual(len(first) % 2, 0)
            began = time.time()
            self.assertGreater(len(voice.say("A second sentence, without the start-up wait.", 2)), 24000)
            self.assertLess(time.time() - began, 5)
            self.assertEqual(voice.say("   "), b"")
            voice.idle_check(0)
            self.assertIsNone(voice.proc, "closed when unused, to give its memory back")
            self.assertGreater(len(voice.say("Back again.")), 10000, "and started again when needed")
        finally:
            voice.close_now()


class TestSpeakingOnChosenSpeakers(GuiTestCase):
    def raw(self, path, body, token=True):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        headers = {"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json"}
        if token:
            headers["X-JCC-Token"] = self.state.token
        c.request("POST", path, body=body, headers=headers)
        r = c.getresponse()
        out = (r.status, r.getheader("Content-Type") or "", r.read())
        c.close()
        return out

    def test_the_window_can_ask_for_windows_own_voice(self):
        asked, original = [], speech.local_voice.say
        speech.local_voice.say = lambda text, rate=0, language="": asked.append((text, rate, language)) or b"\x01\x02" * 2400
        try:
            speech.configure(self.state.cfg, {"speed": 1.2, "language": "hi"})
            status, kind, body = self.raw("/api/speech/tts", b'{"text": "Namaste.", "local": true}')
            self.assertEqual((status, body), (200, b"\x01\x02" * 2400))
            self.assertIn("audio/L16", kind)
            self.assertEqual(asked, [("Namaste.", 2, "hi")])
            self.assertEqual(self.raw("/api/speech/tts", b'{"text": "Hello.", "local": true}', token=False)[0], 401)
            status, data = self.req("POST", "/api/speech", {"action": "settings", "settings": {"mic": "Default - Microphone (HyperX Quadcast) (0951:16df)", "speaker": "Speakers (Realtek(R) Audio)"}})
            self.assertEqual((status, data["settings"]["mic"], data["settings"]["speaker"]), (200, "Microphone (HyperX Quadcast)", "Speakers (Realtek(R) Audio)"))
        finally:
            speech.local_voice.say = original


if __name__ == "__main__":
    unittest.main()
