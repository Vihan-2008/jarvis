"""Sound on a Mac (jcc/macsound.py) and what the wake word needs there, with macOS stood in for. These run on any system.
The real microphone and the real helper are checked on a real Mac by scripts/mac_live_check.py.
"""
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from jcc import config, connections, macsound, pcsound, sound, system, tray, wake
from jcc.lock import InstanceLock
from tests.helpers import EngineTestCase


class FakeAudio:
    """Stands in for macOS's AudioToolbox: remembers what it was asked and lets the test play sound into the microphone."""

    def __init__(self, fail_at=""):
        self.fail_at, self.calls, self.callback, self.buffers = fail_at, [], None, []

    def _answer(self, name):
        self.calls.append(name)
        return 1 if name == self.fail_at else 0

    def AudioQueueNewInput(self, wanted, callback, user, loop, mode, flags, out):
        self.wanted, self.callback = wanted._obj, callback
        out._obj.value = 4242
        return self._answer("new")

    def AudioQueueAllocateBuffer(self, line, size, out):
        self.buffers.append(macsound._Buffer(size, None, 0, None, 0, None, 0))
        out._obj.contents = self.buffers[-1]
        return self._answer("allocate")

    def AudioQueueEnqueueBuffer(self, line, buffer, count, descriptions):
        return self._answer("enqueue")

    def AudioQueueStart(self, line, when):
        return self._answer("start")

    def AudioQueueStop(self, line, now):
        return self._answer("stop")

    def AudioQueueDispose(self, line, now):
        return self._answer("dispose")

    def hear(self, sound_bytes: bytes) -> None:
        """macOS hands over a full piece of sound."""
        held = ctypes.create_string_buffer(sound_bytes, len(sound_bytes))
        buffer = macsound._Buffer(len(sound_bytes), ctypes.addressof(held), len(sound_bytes), None, 0, None, 0)
        self.callback(None, 4242, ctypes.pointer(buffer), None, 0, None)


class TestTheMicrophone(unittest.TestCase):
    def test_sound_arrives_in_pieces_at_16_khz_and_stopping_lets_go_of_it(self):
        audio, heard = FakeAudio(), []
        mic = macsound.Microphone(None, 3200, audio)
        mic.start(heard.append)
        self.assertEqual((audio.wanted.rate, audio.wanted.channels, audio.wanted.bits, audio.wanted.frame_bytes), (16000.0, 1, 16, 2))
        self.assertEqual(audio.calls, ["new"] + ["allocate", "enqueue"] * 6 + ["start"])
        self.assertEqual(audio.buffers[0].capacity, 3200)
        audio.hear(b"\x01\x02" * 1600)
        audio.hear(b"\x03\x04" * 1600)
        deadline = time.time() + 3
        while len(heard) < 2 and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(heard, [b"\x01\x02" * 1600, b"\x03\x04" * 1600])
        self.assertTrue(mic.alive())
        mic.stop()
        self.assertFalse(mic.alive())
        self.assertEqual(audio.calls[-2:], ["stop", "dispose"])
        self.assertEqual(audio.calls.count("enqueue"), 8, "each piece's buffer was handed back to macOS for the next one")

    def test_it_stops_by_itself_after_the_time_it_was_given(self):
        audio = FakeAudio()
        mic = macsound.Microphone(None, 3200, audio)
        mic.start(lambda piece: None, limit=0.1)
        mic.thread.join(timeout=3)
        self.assertFalse(mic.alive())
        self.assertIn("dispose", audio.calls)

    def test_no_microphone_or_no_permission_is_said_in_plain_words(self):
        for step in ("new", "allocate", "start"):
            with self.assertRaises(ValueError) as refused:
                macsound.Microphone(None, 3200, FakeAudio(step)).start(lambda piece: None)
            self.assertIn("System Settings, Privacy & Security, Microphone", str(refused.exception), step)

    def test_on_a_mac_the_apps_microphone_is_the_macs(self):
        with mock.patch.object(system, "PLATFORM", "darwin"):
            if os.name != "nt":                         # (on Windows itself the Windows microphone is always the one)
                self.assertIsInstance(sound.Microphone(None, 1600), macsound.Microphone)
        with mock.patch.object(system, "PLATFORM", "linux"):
            self.assertIsInstance(sound.Microphone(None, 1600), sound.Microphone)

    def test_a_tone_is_played_by_the_macs_own_player_and_the_file_is_not_kept(self):
        played = []

        def run(argv, **kw):
            played.append((argv[0], Path(argv[1]).stat().st_size))
            return subprocess.CompletedProcess(argv, 0)
        self.assertTrue(macsound.tone(880, 70, run=run))
        self.assertEqual(played[0][0], "afplay")
        self.assertGreater(played[0][1], 1000)


SPEAKER = """import sys, time
print("ready", flush=True)
for level in ("0.1000", "0.6500", "0.2000", "nonsense"):
    print(level, flush=True)
if "--die" in sys.argv:
    sys.exit(3)
sys.stdin.read()
"""


class TestHowLoudTheMacsOwnSoundIs(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix="jcc-level-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.folder, ignore_errors=True))
        self.script = self.folder / "speaker.py"
        self.script.write_text(SPEAKER, "utf-8")

    def meter(self, *more):
        return macsound.OutputMeter("the-helper", lambda argv, **kw: subprocess.Popen([sys.executable, str(self.script), *more], **kw))

    def test_the_loudest_moment_since_it_was_last_asked(self):
        meter = self.meter()
        meter.open()
        try:
            deadline, level = time.time() + 5, 0.0
            while level < 0.65 and time.time() < deadline:
                level = max(level, meter.peak())
                time.sleep(0.02)
            self.assertEqual(level, 0.65)
            self.assertEqual(meter.peak(), 0.0, "asked again straight away: nothing louder since")
            self.assertFalse(meter.reopen, "it follows the Mac's speakers itself")
        finally:
            proc = meter.proc
            meter.close()
        proc.wait(timeout=5)
        self.assertIsNotNone(proc.returncode, "closing it stops the helper")

    def test_a_helper_that_stops_or_is_not_installed(self):
        meter = self.meter("--die")
        meter.open()
        meter.proc.wait(timeout=5)
        with self.assertRaises(OSError):
            meter.peak()
        with mock.patch.dict(os.environ, {"JCC_SOUND_LEVEL_HELPER": str(self.folder / "missing")}):
            self.assertIsNone(macsound.helper() if not (config.ROOT / "bin" / macsound.HELPER).is_file() else None)
        silent = macsound.OutputMeter("the-helper", lambda argv, **kw: subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(4)"], **kw))
        with self.assertRaises(OSError) as refused:
            silent.open()
        self.assertIn("Screen Recording", str(refused.exception))

    def test_each_system_has_its_own_meter(self):
        with mock.patch.object(system, "PLATFORM", "darwin"):
            self.assertIsInstance(pcsound.system_meter(), macsound.OutputMeter)
        with mock.patch.object(system, "PLATFORM", "linux"), self.assertRaises(OSError):
            pcsound.system_meter()

    def test_the_macs_meter_is_not_opened_again_every_few_seconds(self):
        class Meter:
            opened = 0
            reopen = False

            def open(self):
                Meter.opened += 1

            def peak(self):
                return 0.3

            def close(self):
                pass
        ticks = iter(range(1000, 100000, 3))
        monitor = pcsound.Monitor(meter=Meter, clock=lambda: next(ticks))
        monitor.want(60)
        monitor.thread.join(timeout=5)
        self.assertEqual(Meter.opened, 1)
        self.assertGreater(len(monitor.samples), 5)


class TestTheWakeWordOnAMac(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.load()
        patch = mock.patch.object(system, "PLATFORM", "darwin")
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_volume_turned_down_while_listening_is_the_macs(self):
        from jcc import mac
        self.assertEqual(wake._speakers(), (mac.volume, mac.set_volume))

    @unittest.skipIf(os.name == "nt", "on Windows itself the Windows recogniser would really start")
    def test_without_its_model_the_owner_is_told_what_is_missing(self):
        with self.assertRaises(ValueError) as refused:
            wake.Listener(lambda hit: None, ["jarvis"]).start()
        self.assertIn("small model that runs on the Mac itself", str(refused.exception))

    def test_the_helper_listens_without_an_icon_and_says_what_it_is_doing(self):
        made = []

        class Ears:
            """Stands in for the listener itself: no test ever opens the real microphone."""
            problem, note, engine = "", "", "neural"

            def __init__(self, cfg, deliver, notify, **ways):
                self.ways, self.stopped = ways, False
                made.append(self)

            def sync(self):
                return True

            def stop(self):
                self.stopped = True
        self.assertEqual(tray.listen_only(self.cfg, once=True, make_ears=Ears), 0)
        status = json.loads((self.cfg.state_dir / "tray-status.json").read_text("utf-8"))
        self.assertEqual((status["tray"], status["keys"], status["wake"], status["wake_engine"], status["wake_problem"]), (False, {}, True, "neural", ""))
        self.assertTrue(made[0].stopped, "the listener is stopped when the helper stops")
        self.assertEqual(sorted(made[0].ways), ["attend", "beep", "busy", "control", "listen", "name_said", "sound"])
        again = InstanceLock(self.cfg.state_dir / "tray.lock")
        self.assertTrue(again.acquire(), "it let go of its lock when it stopped")
        try:
            (self.cfg.state_dir / "tray-status.json").unlink()
            self.assertEqual(tray.listen_only(self.cfg, once=True, make_ears=Ears), 0)
            self.assertEqual(len(made), 1, "a second helper does nothing while one is running")
        finally:
            again.release()

    def test_connections_shows_what_macos_must_allow(self):
        found = {item["id"]: item for item in connections.overview(self.cfg)}
        self.assertEqual((found["mac-accessibility"]["group"], found["mac-accessibility"]["status"]), ("hands", "Could not be checked"))
        self.assertIn("Screen & System Audio Recording", found["mac-screen"]["how"])
        self.assertIn("It starts with JARVIS", found["helper"]["how"])
        with mock.patch.object(system, "PLATFORM", "linux"):
            found = {item["id"]: item for item in connections.overview(self.cfg)}
            self.assertEqual((found["helper"]["state"], found["helper"]["status"]), ("off", "Not available on Linux yet"))
            self.assertNotIn("mac-screen", found)


if __name__ == "__main__":
    unittest.main()
