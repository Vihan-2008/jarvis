"""The neural wake word: "Hey JARVIS" heard by a small model on this PC, and what the tray helper does with it."""
import math
import struct
import time
import unittest

from jcc import config, pcsound, speech, wake, wakeword
from tests.helpers import EngineTestCase
from tests.test_wake import FakeListener, FakeRecorder


def tone(seconds: float, loud: float) -> bytes:
    count = int(16000 * seconds)
    return struct.pack(f"<{count}h", *(int(32767 * loud * math.sin(i / 3.0)) for i in range(count)))


PIECE = wakeword.STEP * 2
QUIET, LOUD = b"\x00\x00" * wakeword.STEP, tone(0.08, 0.3)


class FakeMic:
    def __init__(self, device=None):
        self.device, self.each, self.on, self.used_default = device, None, False, device is None

    def start(self, each, limit=None):
        self.each, self.on = each, True

    def alive(self):
        return self.on

    def stop(self):
        self.on = False


class ScriptedSpotter:
    """Gives the scores it was told to give, one for each piece of sound."""

    def __init__(self, scores):
        self.scores = list(scores)

    def feed(self, sound):
        return [self.scores.pop(0) if self.scores else 0.0]


class TestTheModel(unittest.TestCase):
    def test_it_knows_the_name_from_ordinary_talk(self):
        files = wakeword.parts()
        if not files:
            self.skipTest("the wake word model is not installed on this PC")
        spotter = wakeword.Spotter(files)
        results = {}
        for name, sentence in (("name", "Hey Jarvis"), ("request", "Hey Jarvis, what time is it?"), ("talk", "I think the weather was really quite good yesterday evening.")):
            sound = speech.sample_speech(sentence)
            if len(sound) < 16000:
                self.skipTest("Windows could not make a test sentence")
            spotter.reset()
            results[name] = max(spotter.feed(b"\x00\x00" * 16000 + sound + b"\x00\x00" * 16000))
        self.assertGreater(results["name"], 0.9)
        self.assertGreater(results["request"], 0.9)
        self.assertLess(results["talk"], 0.2, "ordinary talk is not the name")
        spotter.reset()
        self.assertEqual(spotter.feed(b"\x00\x00" * 100), [], "less than one step of sound: no score yet")
        self.assertEqual(len(spotter.feed(b"\x00\x00" * (wakeword.STEP * 2))), 2, "sound is taken in whole steps, however it arrives")

    def test_a_pc_without_its_parts_listens_the_old_way(self):
        import importlib.util
        real = importlib.util.find_spec
        importlib.util.find_spec = lambda name, *a: None if name == "onnxruntime" else real(name, *a)
        try:
            self.assertIsNone(wakeword.parts())
        finally:
            importlib.util.find_spec = real


class TestTheListener(unittest.TestCase):
    def make(self, scores, sound=None):
        self.hits, self.mic = [], FakeMic()
        self.clock = [1000.0]
        listener = wakeword.NeuralListener(self.hits.append, {}, microphone=lambda device: self.mic, spotter=lambda files: ScriptedSpotter(scores), sound=sound,
                                           clock=lambda: self.clock[0])
        listener.start()
        return listener

    def feed(self, piece, count=1):
        for _ in range(count):
            self.clock[0] += 0.08
            self.mic.each(piece)

    def wait(self, count=1):
        deadline = time.time() + 3
        while len(self.hits) < count and time.time() < deadline:
            time.sleep(0.01)
        time.sleep(0.05)

    def test_a_certain_match_is_passed_on_at_once_with_what_follows_already_being_recorded(self):
        listener = self.make([0.0] * 30 + [0.2, 0.95])
        self.assertTrue(listener.ready.is_set() and listener.running())
        self.assertEqual(listener.input, "default")
        release = __import__("threading").Event()
        seen = []
        listener.heard = lambda hit: (seen.append(hit), release.wait(3))
        self.feed(QUIET, 32)
        deadline = time.time() + 3
        while not seen and time.time() < deadline:
            time.sleep(0.01)
        hit = seen[0]
        self.assertEqual((hit["grammar"], hit["neural"], hit["confidence"]), ("wake", True, 0.95))
        self.assertEqual(len(hit["pcm"]), 25 * PIECE, "the two seconds that held the name come along")
        self.assertAlmostEqual(hit["began"], hit["at"] - 2.0, places=2)
        self.feed(LOUD, 5)                               # "open Spotify", straight after the name
        self.assertEqual(hit["recorder"].so_far(), LOUD * 5, "not a word is lost between the name and the request")
        self.assertTrue(hit["recorder"].heard_speech)
        release.set()
        time.sleep(0.1)
        self.feed(LOUD, 2)
        self.assertEqual(len(hit["recorder"].so_far()), 5 * PIECE, "once it has been dealt with, nothing more is collected")
        self.assertEqual(listener.followers, [])

    def test_the_same_name_is_not_heard_twice_and_a_doubtful_one_is_given_a_moment(self):
        listener = self.make([0.0] * 30 + [0.9, 0.95, 0.99, 0.97] + [0.0] * 30 + [0.4, 0.5, 0.0])
        self.feed(QUIET, 34)
        self.wait()
        self.assertEqual([hit["confidence"] for hit in self.hits], [0.9], "one hit for one 'Hey JARVIS', however long the score stays high")
        self.feed(QUIET, 33)
        self.wait(2)
        self.assertEqual([hit["confidence"] for hit in self.hits], [0.9, 0.5], "a doubtful match is passed on with its best score, to be checked")
        listener.stop()
        self.assertFalse(listener.running())

    def test_a_microphone_that_goes_silent_counts_as_stopped(self):
        listener = self.make([])
        self.feed(QUIET, 3)
        self.assertTrue(listener.running())
        self.clock[0] += 30
        self.assertFalse(listener.running(), "unplugged: the helper starts it again on whichever microphone Windows offers")

    def test_it_learns_how_loudly_the_pc_reaches_the_microphone(self):
        class Sound:
            learned, wanted = [], 0

            def want(self, seconds=30):
                Sound.wanted += 1

            def playing_now(self, seconds=1.0):
                return True

            def learn(self, start, levels):
                Sound.learned.append((round(start, 2), len(levels)))

            def echo_now(self):
                return 0.05
        listener = self.make([], Sound())
        self.feed(QUIET, 38)
        self.assertTrue(Sound.learned and Sound.wanted, "now and then, while nobody has called it")
        self.assertEqual(Sound.learned[-1][1] % 4, 0, "loudness on the same grid the PC's own sound is measured on")
        self.assertEqual(listener._echo(), 0.05)


class TestWhatFollows(unittest.TestCase):
    def test_it_knows_the_room_and_the_pcs_own_sound(self):
        plain = wakeword.Following()
        plain._take(tone(0.08, 0.02))
        self.assertTrue(plain.heard_speech, "in a quiet room an ordinary voice counts")
        noisy = wakeword.Following(floor=0.03)
        noisy._take(tone(0.08, 0.05))
        self.assertFalse(noisy.heard_speech, "a fan or a film at that level is the room, not someone speaking")
        noisy._take(tone(0.08, 0.2))
        self.assertTrue(noisy.heard_speech)
        film = wakeword.Following(floor=0.005, echo=lambda: 0.1)
        film._take(tone(0.08, 0.2))
        self.assertFalse(film.heard_speech, "the PC's own sound at the microphone is not someone speaking")
        film.echo = lambda: 0.0
        film._take(tone(0.08, 0.2))
        self.assertTrue(film.heard_speech)

    def test_it_says_how_long_it_has_been_quiet(self):
        following = wakeword.Following(quiet=0.2)
        self.assertEqual(following.quiet_for(), 0.0)
        following._take(LOUD)
        self.assertEqual(following.quiet_for(), 0.0)
        following._take(QUIET)
        time.sleep(0.25)
        self.assertGreater(following.quiet_for(), 0.2)
        self.assertTrue(following.finished_speaking())
        self.assertEqual(following.stop(), LOUD + QUIET)
        following._take(LOUD)
        self.assertEqual(following.stop(), LOUD + QUIET, "after it was stopped nothing is added")


class Talk(FakeRecorder):
    """A recorder that can say how long it has been quiet, like the one that follows the neural wake word."""
    voiced, gap = 1.0, 0.6

    def quiet_for(self):
        return self.gap if self.heard_speech else 0.0

    def so_far(self):
        return self.sound

    def finished_speaking(self):
        return False


class TestEarsWithTheNeuralWakeWord(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.load()
        self.delivered, self.told, self.beeps, self.heard_audio, self.attended, self.listened, self.controls = [], [], [], [], [], [], []
        FakeListener.made, FakeRecorder.said = [], True

    def make(self, *replies, sound=None, busy=False):
        replies = list(replies)

        def hear(audio):
            self.heard_audio.append(audio)
            return replies.pop(0) if replies else ""
        return wake.Ears(self.cfg, self.delivered.append, self.told.append, FakeListener, FakeRecorder, hear, self.beeps.append, lambda: busy,
                         control=self.controls.append, attend=lambda: self.attended.append(1), listen=lambda: self.listened.append(1), sound=sound)

    def hit(self, confidence=0.95, recorder=None):
        recorder = recorder or FakeRecorder()
        recorder.start()
        return {"text": "hey jarvis", "confidence": confidence, "grammar": "wake", "neural": True, "pcm": b"\x01\x02" * 32000, "began": time.time() - 2,
                "recorder": recorder, "at": time.time()}

    def test_a_certain_match_needs_no_checking_and_what_follows_is_the_request(self):
        ears = self.make("open Spotify.")
        ears._heard(self.hit())
        self.assertEqual(self.delivered, ["open Spotify."])
        self.assertEqual(self.heard_audio, [FakeRecorder.sound], "only what followed was transcribed; the name itself did not need it")
        self.assertEqual((self.beeps, self.attended), ([880], [1]), "the window shows at once that it is listening")

    def test_a_doubtful_match_is_checked_and_hey_travis_is_not_the_name(self):
        ears = self.make("Hey Travis, how are you?")
        ears._heard(self.hit(0.5))
        self.assertEqual((self.delivered, self.beeps, self.attended), ([], [], []), "nothing happens, not even a sound")
        ears = self.make("So anyway. Hey Jarvis.", "what time is it?")
        ears._heard(self.hit(0.5))
        self.assertEqual(self.delivered, ["what time is it?"], "the name may come after other talk in that clip")
        self.assertEqual(self.heard_audio[-2], b"\x01\x02" * 32000, "the clip that held the name was what was checked")

    def test_without_the_speech_service_a_fair_match_still_counts(self):
        def unreachable(audio):
            raise OSError("offline")
        ears = wake.Ears(self.cfg, self.delivered.append, self.told.append, FakeListener, FakeRecorder, unreachable, self.beeps.append,
                         listen=lambda: self.listened.append(1))
        ears._heard(self.hit(0.6))
        self.assertEqual(self.beeps[:1], [880])
        ears._heard(self.hit(0.35))
        self.assertEqual(self.beeps.count(880), 1, "a weak match with nothing to check it against is dropped")

    def test_nothing_after_the_name_and_jarvis_asks(self):
        FakeRecorder.said = False
        ears = self.make()
        ears._heard(self.hit())
        self.assertEqual((self.delivered, self.listened), ([], [1]))

    def test_a_film_saying_the_name_is_ignored(self):
        class Film:
            def want(self, seconds=30):
                pass

            def verdict(self, start, levels, before=None):
                return {"pc": True}
        ears = self.make("open Spotify.", sound=Film())
        ears._heard(self.hit())
        self.assertEqual((self.delivered, self.beeps), ([], []))

    def test_it_stays_out_of_a_conversation_that_is_going_on(self):
        ears = self.make("open Spotify.", busy=True)
        ears._heard(self.hit())
        self.assertEqual((self.delivered, self.heard_audio), ([], []))

    def test_stop_after_the_name_is_a_command_and_is_given_once(self):
        ears = self.make("stop")
        ears._heard(self.hit())
        ears._heard({"text": "jarvis stop", "confidence": 0.9, "grammar": "ctrl", "wav": b"RIFF"})   # Windows' recogniser heard the same words
        self.assertEqual((self.controls, self.delivered), (["rest"], []))

    def test_a_finished_sentence_is_passed_on_during_the_first_pause(self):
        ears = self.make("What time is it?")
        started = time.time()
        ears._heard(self.hit(recorder=Talk()))
        self.assertEqual(self.delivered, ["What time is it?"])
        self.assertLess(time.time() - started, 3, "it did not wait for the long silence")
        self.assertEqual(len(self.heard_audio), 1, "and it was transcribed once")

    def test_an_unfinished_sentence_is_given_longer(self):
        self.assertTrue(wake.complete("What time is it?") and wake.complete("Open Spotify."))
        for text in ("Set a timer for.", "Play something by", "Okay.", "remind me to", ""):
            self.assertFalse(wake.complete(text), text)

    def test_the_neural_wake_word_runs_beside_windows_own_and_covers_for_it(self):
        made = []

        class Neural:
            def __init__(self, heard, device):
                self.heard, self.device, self.alive = heard, device, False
                made.append(self)

            def start(self):
                self.alive = True

            def running(self):
                return self.alive

            def stop(self):
                self.alive = False
        ears = wake.Ears(self.cfg, self.delivered.append, self.told.append, FakeListener, FakeRecorder, lambda audio: "", spotter=Neural)
        self.assertTrue(ears.sync())
        self.assertEqual((len(made), len(FakeListener.made), ears.engine), (1, 1, "neural"))
        FakeListener.made[0].alive, FakeListener.made[0].problem = False, "no-recognizer"
        self.assertTrue(ears.sync(), "Windows' own recogniser is missing, and the wake word still works")
        self.assertEqual((self.told, ears.problem), ([], ""), "so the owner is not told that anything is wrong")
        made[0].alive = False
        ears.sync()
        self.assertEqual(len(made), 2, "a neural listener that stopped (the microphone was unplugged) is started again")
        speech.configure(self.cfg, {"wake": False})
        self.assertFalse(ears.sync())
        self.assertFalse(made[1].alive)
        self.assertEqual(ears.engine, "")
        plain = wake.Ears(self.cfg, self.delivered.append, self.told.append, FakeListener, FakeRecorder, lambda audio: "")
        self.assertIs(plain.make_spotter, False, "tests that bring their own listener never open the real microphone")


class TestHowLoudlyThePcReachesTheMicrophone(unittest.TestCase):
    def test_learning_from_the_last_few_seconds(self):
        now = [5000.0]
        monitor = pcsound.Monitor(meter=lambda: None, clock=lambda: now[0])
        monitor.want = lambda seconds=30.0: None
        film = [0.3 if (i // 10) % 2 else 0.0 for i in range(200)]             # the PC's sound comes and goes
        for i, level in enumerate(film):
            monitor.add(4996.0 + i * 0.02, level)
        heard = [0.004 + 0.2 * level for level in film]                           # the microphone follows it: speakers
        self.assertAlmostEqual(monitor.learn(4996.0, heard), 0.2, delta=0.05)
        monitor.add(4999.99, 0.3)
        self.assertAlmostEqual(monitor.echo_now(), 0.06, delta=0.02)
        self.assertEqual(monitor.learn(4996.0, [0.004] * 200), 0.0, "the microphone did not notice it: headphones")
        self.assertEqual(monitor.echo_now(), 0.0)
        self.assertIsNone(monitor.learn(4996.0, [0.004] * 10), "too short to tell")


if __name__ == "__main__":
    unittest.main()
