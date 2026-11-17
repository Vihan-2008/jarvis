"""The always-on wake word: spotted on this PC, then handed to JARVIS. Fake microphone and fake recogniser, plus one real offline check."""
import http.client
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

from jcc import assistant, config, speech, wake
from tests.helpers import EngineTestCase
from tests.test_gui import GuiTestCase


class FakeListener:
    made = []

    def __init__(self, heard, names):
        self.heard, self.names, self.alive = heard, names, False
        FakeListener.made.append(self)

    def start(self):
        self.alive = True

    def running(self):
        return self.alive

    def stop(self):
        self.alive = False


class FakeRecorder:
    said, sound = True, b"\x01\x02" * 16000

    def __init__(self):
        self.heard_speech = False

    def start(self):
        self.heard_speech = self.said

    def finished_speaking(self):
        return True

    def stop(self):
        return self.sound


def hit(text="hey jarvis", confidence=0.9, grammar="wake+", wav=b"RIFFfake"):
    return {"text": text, "confidence": confidence, "grammar": grammar, "wav": wav}


class TestWakeWord(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.load()
        self.delivered, self.told, self.beeps, self.heard_audio, self.replies, self.busy = [], [], [], [], [], False
        FakeListener.made, FakeRecorder.said = [], True

    def make(self, *replies):
        self.replies = list(replies)

        def hear(sound):
            self.heard_audio.append(sound)
            return self.replies.pop(0) if self.replies else ""
        return wake.Ears(self.cfg, self.delivered.append, self.told.append, FakeListener, FakeRecorder, hear, self.beeps.append, lambda: self.busy)

    def test_only_sentences_that_start_with_the_wake_word_count(self):
        names = ["jarvis", "coach"]
        for text, asked in (("Hey Jarvis, what time is it?", "what time is it?"), ("Jarvis open Notepad", "open Notepad"), ("OK, JARVIS.", ""),
                            ("hey coach how did I do", "how did I do"), ("Hello Jarvis!", ""), ("Hey Jarvice, play music", "play music")):
            self.assertEqual(wake.split(text, names), asked, text)
        for text in ("What time is it?", "I told Jarvis yesterday", "the service is harvesting", "", "hey there"):
            self.assertIsNone(wake.split(text, names), text)

    def test_a_request_said_in_one_breath_is_passed_on_whole(self):
        FakeRecorder.said = False                      # nothing more was said after that sentence
        ears = self.make("Hey Jarvis, remind me to call Asha at 5 pm tomorrow.")
        ears._heard(hit("ok jarvis remind me to call a shot at five PM tomorrow"))
        self.assertEqual(self.delivered, ["remind me to call Asha at 5 pm tomorrow."], "Whisper's careful transcript is used, not the rough local one")
        self.assertEqual((self.beeps, self.heard_audio), ([880], [b"RIFFfake"]), "and it is passed on at once: nothing more is waited for")

    def test_a_sentence_that_went_on_after_the_first_part_is_joined_up(self):
        # Windows hands over "Hey Jarvis, play No Role Modelz" at the speaker's pause; "by J. Cole on Spotify" is still being said.
        ears = self.make("Hey Jarvis, play No Role Modelz", "by J. Cole on Spotify.")
        ears._heard(hit("hey jarvis play no role models"))
        self.assertEqual(self.delivered, ["play No Role Modelz by J. Cole on Spotify."])
        self.assertEqual(self.heard_audio, [b"RIFFfake", FakeRecorder.sound], "the recording began the moment the name was heard")

    def test_words_whisper_adds_to_a_clip_that_held_only_the_name_are_not_a_request(self):
        # The real case: "Hey Jarvis" alone came back from Whisper as "Hey Jarvis. Ouvindo a palco." and JARVIS answered that.
        FakeRecorder.said = False
        ears = self.make("Hey Jarvis. Ouvindo a palco.")
        ears._heard(hit("hey jarvis", grammar="wake"))
        self.assertEqual(self.delivered, [], "nothing was asked, so nothing is answered")
        FakeRecorder.said = True
        ears = self.make("Hey Jarvis. Ouvindo a palco.", "open Spotify")
        ears._heard(hit("hey jarvis", grammar="wake"))
        self.assertEqual(self.delivered, ["open Spotify"], "what is said next is the request")

    def test_a_click_or_a_breath_after_the_name_is_not_words(self):
        class Breath(FakeRecorder):
            voiced = 0.1
        ears = wake.Ears(self.cfg, self.delivered.append, self.told.append, FakeListener, Breath, lambda sound: "Hey Jarvis.", self.beeps.append)
        ears._heard(hit("hey jarvis", grammar="wake"))
        self.assertEqual((self.delivered, self.beeps), ([], [880, 440]))

    def test_the_wake_word_alone_then_listens_for_what_comes_next(self):
        ears = self.make("Hey Jarvis.", "  open   the calculator ")
        ears._heard(hit("hey jarvis", grammar="wake"))
        self.assertEqual(self.delivered, ["open the calculator"])
        self.assertEqual(self.heard_audio[1], FakeRecorder.sound, "what was said next was recorded and transcribed")
        FakeRecorder.said = False
        ears = self.make("Hey Jarvis.")
        ears._heard(hit("hey jarvis", grammar="wake"))
        self.assertEqual((len(self.delivered), self.beeps[-2:]), (1, [880, 440]), "nothing followed, so nothing is done")

    def test_false_alarms_and_quiet_matches_are_dropped(self):
        ears = self.make("The service is harvesting the garden.")
        ears._heard(hit("jarvis is harvesting the garden", confidence=0.6))
        ears._heard(hit("hey jarvis", confidence=0.2))
        self.assertEqual((self.delivered, self.beeps, len(self.heard_audio)), ([], [], 1), "a faint match is not even sent to be transcribed")

    def test_it_stays_out_of_a_conversation_that_is_already_going_on(self):
        self.busy = True
        ears = self.make("Hey Jarvis, what time is it?")
        ears._heard(hit())
        self.assertEqual((self.delivered, self.heard_audio), ([], []), "JARVIS never answers its own voice or cuts into a chat")

    def test_it_still_works_when_the_speech_service_is_unreachable(self):
        def unreachable(sound):
            raise OSError("offline")
        ears = wake.Ears(self.cfg, self.delivered.append, self.told.append, FakeListener, FakeRecorder, unreachable, self.beeps.append)
        ears._heard(hit("hey jarvis what time is it"))
        self.assertEqual(self.delivered, ["what time is it"], "the local transcript is good enough to carry on")

    def test_the_listener_follows_the_settings_and_the_assistant_name(self):
        ears = self.make()
        self.assertTrue(speech.settings(self.cfg)["wake"], "on unless switched off")
        self.assertTrue(ears.sync())
        self.assertEqual((len(FakeListener.made), FakeListener.made[0].names), (1, ["jarvis"]))
        self.assertTrue(ears.sync())
        self.assertEqual(len(FakeListener.made), 1, "nothing is restarted when nothing changed")
        assistant.save_assistant(self.cfg, {"name": "Coach", "use": True})
        ears.sync()
        self.assertEqual((FakeListener.made[0].alive, FakeListener.made[1].names), (False, ["jarvis", "coach"]), "the assistant in use can be called by its name")
        speech.configure(self.cfg, {"wake": False})
        self.assertFalse(ears.sync())
        self.assertFalse(FakeListener.made[1].alive)
        speech.configure(self.cfg, {"wake": True})
        FakeListener.made[1].alive = False
        self.assertTrue(ears.sync())
        self.assertEqual(len(FakeListener.made), 3, "a listener that stopped is started again")
        ears.stop()

    def test_a_pc_where_it_cannot_run_is_told_once_and_not_hammered(self):
        ears = self.make()
        self.assertTrue(ears.sync())
        FakeListener.made[0].alive, FakeListener.made[0].problem = False, "no-recognizer"
        self.assertFalse(ears.sync())
        self.assertIn("not installed", ears.problem)
        self.assertEqual(len(self.told), 1)
        for _ in range(5):
            self.assertFalse(ears.sync())
        self.assertEqual((len(FakeListener.made), len(self.told)), (1, 1), "no restart loop and no repeated messages")
        ears.retry_at = 0
        self.assertTrue(ears.sync())
        self.assertEqual(len(FakeListener.made), 2, "tried again after the wait")


class TestOnlyWhileJarvisIsOpen(EngineTestCase):
    """"Hey JARVIS" listens only while a JARVIS window is open: nothing at sign-in, and the microphone is let go when the
    last window closes, crashes or stops asking for news. Fake listeners only: no test opens the real microphone."""

    def setUp(self):
        super().setUp()
        self.cfg = config.load()
        self.window_is_open, self.neural = False, []
        FakeListener.made = []

    def ears(self, **extra):
        test = self

        class Neural:
            def __init__(self, heard, device):
                self.alive = False
                test.neural.append(self)

            def start(self):
                self.alive = True

            def running(self):
                return self.alive

            def stop(self):
                self.alive = False
        return wake.Ears(self.cfg, lambda text: None, lambda text: None, FakeListener, FakeRecorder, lambda sound: "", spotter=Neural,
                         window=extra.pop("window", lambda: self.window_is_open), **extra)

    def wait(self, check, seconds=5.0):
        until = time.time() + seconds
        while time.time() < until and not check():
            time.sleep(0.02)
        return check()

    def test_no_window_means_no_listener_and_it_follows_the_window(self):
        ears = self.ears()
        for _ in range(3):
            self.assertFalse(ears.sync(), "signed in, no window: nothing listens")
        self.assertEqual((FakeListener.made, self.neural, ears.waiting, ears.engine), ([], [], True, ""), "neither wake word touched the microphone")
        self.window_is_open = True
        self.assertTrue(ears.sync(), "the window opens: it listens")
        self.assertEqual((len(FakeListener.made), len(self.neural), FakeListener.made[0].alive, self.neural[0].alive, ears.waiting), (1, 1, True, True, False))
        self.assertTrue(ears.sync())
        self.assertEqual((len(FakeListener.made), len(self.neural)), (1, 1), "while it stays open (minimised too), nothing is restarted")
        self.window_is_open = False
        self.assertFalse(ears.sync(), "the last window closed")
        self.assertEqual((FakeListener.made[0].alive, self.neural[0].alive, ears.engine, ears.waiting), (False, False, "", True),
                         "both wake words let go of the microphone")
        self.assertFalse(ears.sync())
        self.assertEqual((len(FakeListener.made), len(self.neural)), (1, 1), "and nothing starts them again while it is closed")
        self.window_is_open = True
        self.assertTrue(ears.sync())
        self.assertEqual((len(FakeListener.made), len(self.neural)), (2, 2), "opened again: listening again")
        ears.stop()

    def test_switched_off_it_neither_listens_nor_looks_for_a_window(self):
        speech.configure(self.cfg, {"wake": False})
        asked = []

        def window():
            asked.append(1)
            return True
        ears = self.ears(window=window)
        self.assertFalse(ears.sync())
        self.assertEqual((FakeListener.made, ears.waiting, asked), ([], False, []))

    def test_when_it_cannot_be_told_whether_a_window_is_open_nothing_listens(self):
        def broken():
            raise OSError("no answer")
        ears = self.ears(window=broken)
        self.assertFalse(ears.sync())
        self.assertEqual((FakeListener.made, self.neural), ([], []))

    def test_the_helpers_own_listener_always_waits_for_a_window(self):
        self.assertIsNotNone(wake.Ears(self.cfg, lambda text: None).window, "without stand-ins (the tray helper itself) the window is always asked about")
        self.assertIsNone(wake.Ears(self.cfg, lambda text: None, listener=FakeListener).window)

    def test_windows_is_asked_first_and_the_services_heartbeat_where_it_cannot_be(self):
        def never():
            raise AssertionError("not asked")
        self.assertTrue(wake.window_open(self.cfg, find=lambda: True, ask=never))
        self.assertFalse(wake.window_open(self.cfg, find=lambda: False, ask=never), "Windows says it has gone (closed, crashed, ended): that settles it")
        for answer, expected in (({"window": True, "app": True}, True), ({"window": True, "app": False}, False), ({"window": True}, True),
                                 ({"window": False, "app": False}, False), (None, False)):
            self.assertIs(wake.window_open(self.cfg, find=lambda: None, ask=lambda: answer), expected, answer)

    def test_the_app_window_is_known_by_its_title_and_the_small_one_does_not_count(self):
        from jcc import desktop
        self.assertTrue(desktop.app_window_open(lambda: ["Notepad", "JARVIS · Workspace"]))
        self.assertFalse(desktop.app_window_open(lambda: ["JARVIS · Listening", "JARVIS · Workspace - Microsoft Edge", "", None]),
                         "the small listening window kept out of sight, or JARVIS's page in an ordinary browser tab, is not the app")

        def broken():
            raise OSError("the windows could not be listed")
        self.assertIsNone(desktop.app_window_open(broken), "cannot be told: the service is asked instead")
        self.assertIsNone(desktop.app_window_open(), "the tests never look at this PC's real windows")

    def test_the_tray_helper_listens_only_while_a_window_is_open(self):
        from jcc import tray
        menus = []

        def make_ears(cfg, deliver, notify, **ways):
            return wake.Ears(cfg, deliver, notify, FakeListener, FakeRecorder, lambda sound: "", window=lambda: self.window_is_open)

        class Menu:
            icon, keys = False, {}

            def __init__(self, actions, icon=True, keys=True):
                self.actions = actions
                menus.append(self)

            def open(self):
                return False

            def dictating(self, on):
                pass

            def close(self):
                pass

        class Dictation:
            listening = False

            def __init__(self, cfg, notify, beep=None):
                pass

            def toggle(self):
                pass
        status = self.cfg.state_dir / "tray-status.json"

        def seen():
            try:
                return json.loads(status.read_text("utf-8"))
            except (OSError, ValueError):
                return {}
        helper = threading.Thread(target=lambda: tray.listen_only(self.cfg, pause=0.05, make_ears=make_ears, make_menu=Menu, make_dictation=Dictation), daemon=True)
        helper.start()
        try:
            self.assertTrue(self.wait(lambda: seen().get("wake_waits") is True))
            self.assertEqual((seen()["wake"], FakeListener.made), (False, []), "after sign-in the helper runs and the microphone is not used")
            self.window_is_open = True
            self.assertTrue(self.wait(lambda: seen().get("wake") is True), "JARVIS opened: it listens within a moment")
            self.assertEqual((FakeListener.made[-1].alive, seen()["wake_waits"]), (True, False))
            self.window_is_open = False
            self.assertTrue(self.wait(lambda: seen().get("wake") is False), "the last window closed")
            self.assertEqual((FakeListener.made[-1].alive, seen()["wake_waits"]), (False, True), "the microphone is let go")
        finally:
            if menus:
                menus[0].actions["quit"]()
            helper.join(timeout=5)
        self.assertFalse(helper.is_alive())


@unittest.skipUnless(os.name == "nt", "Windows only")
class TestRealOfflineRecogniser(unittest.TestCase):
    def test_windows_spots_the_wake_word_in_a_recording_without_the_internet(self):
        folder = Path(tempfile.mkdtemp(prefix="jcc-wake-"))
        try:
            results = {}
            for name, sentence in (("wake", "Hey Jarvis, what time is it?"), ("other", "This is just people talking in the room about the weather.")):
                sound = speech.sample_speech(sentence)
                if len(sound) < 16000:
                    self.skipTest("Windows could not make a test sentence")
                path = folder / f"{name}.wav"
                path.write_bytes(speech.wav(b"\x00\x00" * 8000 + sound + b"\x00\x00" * 24000))
                hits = []
                listener = wake.Listener(hits.append, ["jarvis"], str(path))
                listener.start()
                listener.proc.wait(timeout=90)
                time.sleep(0.5)
                if listener.problem:
                    self.skipTest("no offline recogniser on this PC: " + listener.problem)
                results[name] = hits
            self.assertEqual(results["other"], [], "ordinary talk never leaves the recogniser")
            self.assertEqual(len(results["wake"]), 1)
            found = results["wake"][0]
            self.assertEqual(wake.split(found["text"], ["jarvis"]), "what time is it")
            self.assertGreater(found["confidence"], 0.5)
            self.assertEqual(found["wav"][:4], b"RIFF", "the sentence itself comes along, ready to be transcribed properly")
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class TestWakeApi(GuiTestCase):
    def tray(self, body):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("POST", "/api/tray", body=json.dumps(body),
                  headers={"Host": f"127.0.0.1:{self.port}", "X-JCC-Tray": self.state.tray_key, "Content-Type": "application/json"})
        r = c.getresponse()
        out = (r.status, json.loads(r.read()))
        c.close()
        return out

    def test_what_was_said_reaches_the_window_or_waits_for_it(self):
        self.state.assistant.hand_wait = 0.3
        self.assertEqual(self.tray({"action": "status"}), (200, {"window": False, "app": False, "voice": False, "phase": "idle", "waiting": False}))
        self.assertEqual(self.tray({"action": "say", "text": "  what   time is it "}), (200, {"window": False}), "no window yet: the tray opens one")
        self.assertTrue(self.req("GET", "/api/voice/events?since=0")[1]["waiting"], "any window that turns up is told something is waiting")
        self.assertEqual(self.req("POST", "/api/voice", {"action": "pending"})[1], {"text": "what time is it", "listen": False, "attend": False, "nudge": False}, "the new window picks the request up")
        self.assertEqual(self.req("POST", "/api/voice", {"action": "pending"})[1], {"text": "", "listen": False, "attend": False, "nudge": False}, "once")
        self.assertFalse(self.req("GET", "/api/voice/events?since=0")[1]["waiting"])
        self.assertEqual(self.tray({"action": "say", "text": ""})[0], 400)

    def test_an_open_window_has_to_take_the_request_itself(self):
        """A window that was closed a moment ago still looks open for a while. Nothing may be lost to it."""
        agent = self.state.assistant
        agent.hand_wait = 0.3
        self.req("GET", "/api/voice/events?since=0")          # a window was here a moment ago...
        self.assertEqual(self.tray({"action": "say", "text": "open the calculator"}), (200, {"window": False}), "...but it is gone, so the tray opens a new one")
        self.assertEqual(self.req("POST", "/api/voice", {"action": "pending"})[1]["text"], "open the calculator", "and the request is still there for it")
        # A window that really is open is woken at once and takes the request; the tray is told so without delay.
        upto, took = self.req("GET", "/api/voice/events?since=0")[1]["next"], []

        def window():
            data = self.req("GET", f"/api/voice/events?since={upto}&wait=8")[1]
            took.append(([e["k"] for e in data["events"]], data["waiting"], self.req("POST", "/api/voice", {"action": "pending"})[1]))

        thread = threading.Thread(target=window)
        thread.start()
        time.sleep(0.3)
        agent.hand_wait = 8
        started = time.time()
        self.assertEqual(self.tray({"action": "say", "text": "what time is it"}), (200, {"window": True}))
        self.assertLess(time.time() - started, 4, "answered as soon as the window has it, not after the whole wait")
        thread.join(8)
        self.assertEqual(took, [(["wake"], True, {"text": "what time is it", "listen": False, "attend": False, "nudge": False})])
        self.assertEqual(self.req("POST", "/api/voice", {"action": "pending"})[1], {"text": "", "listen": False, "attend": False, "nudge": False}, "exactly one window gets it")

    def test_the_wake_word_does_not_cut_into_a_spoken_conversation(self):
        self.req("GET", "/api/voice/events?since=0")
        self.req("POST", "/api/voice", {"action": "presence", "phase": "speaking"})
        self.assertEqual(self.tray({"action": "status"})[1], {"window": True, "app": True, "voice": True, "phase": "speaking", "waiting": False})
        self.assertEqual(self.tray({"action": "say", "text": "jarvis here how can I help"}), (200, {"busy": True}), "JARVIS's own voice is not taken as a request")
        self.req("POST", "/api/voice", {"action": "presence", "phase": "idle"})
        self.state.assistant.hand_wait = 0.3
        self.assertEqual(self.tray({"action": "say", "text": "what time is it"})[1], {"window": False}, "accepted once it is quiet again (no window takes it in this test, so it waits)")
        self.assertEqual(self.req("POST", "/api/voice", {"action": "pending"})[1]["text"], "what time is it")
        self.req("POST", "/api/voice", {"action": "presence", "phase": "nonsense"})
        self.assertFalse(self.tray({"action": "status"})[1]["voice"])


if __name__ == "__main__":
    unittest.main()

    def test_the_tray_is_told_whether_the_app_window_is_open(self):
        """The heartbeat the tray helper goes by where it cannot ask the PC itself (jcc/wake.py window_open)."""
        agent = self.state.assistant
        self.assertFalse(self.tray({"action": "status"})[1]["app"], "signed in, no window")
        self.req("GET", "/api/voice/events?since=0&w=small&kind=mini")
        status = self.tray({"action": "status"})[1]
        self.assertEqual((status["window"], status["app"]), (True, False), "the small listening window, kept ready out of sight, is not JARVIS being open")
        self.req("GET", "/api/voice/events?since=0&w=app1&kind=main")
        self.assertTrue(self.tray({"action": "status"})[1]["app"])
        self.req("POST", "/api/voice", {"action": "presence", "phase": "idle", "w": "app1", "gone": True})
        self.assertFalse(self.tray({"action": "status"})[1]["app"], "closed: the window said so")
        self.req("GET", "/api/voice/events?since=0&w=app2&kind=main")
        self.assertTrue(self.tray({"action": "status"})[1]["app"])
        with agent.lock:
            agent.windows["app2"] -= 46
        self.assertFalse(self.tray({"action": "status"})[1]["app"], "crashed or ended: no goodbye, but it stopped asking for news")

    def test_a_window_waits_for_the_helper_only_while_the_helper_runs(self):
        """The helper says it is about to listen (a window has just opened): the window then does not listen itself. Said by
        a helper that is no longer running, it is not believed, or nothing would ever listen."""
        from jcc.lock import InstanceLock
        (self.state.cfg.state_dir / "tray-status.json").write_text(json.dumps({"wake": False, "wake_waits": True}), "utf-8")
        self.assertIs(self.req("GET", "/api/speech")[1]["shortcuts"]["wake_waits"], False, "no helper running")
        helper = InstanceLock(self.state.cfg.state_dir / "tray.lock")
        self.assertTrue(helper.acquire())
        try:
            self.assertIs(self.req("GET", "/api/speech")[1]["shortcuts"]["wake_waits"], True, "the helper is running")
        finally:
            helper.release()
