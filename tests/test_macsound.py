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


class NoMenu:
    """Stands in for the menu-bar program where a test does not need one: no icon, no shortcuts."""
    icon, keys = False, {}

    def __init__(self, actions, icon=True, keys=True):
        self.actions, self.told = actions, []

    def open(self):
        return False

    def dictating(self, on):
        self.told.append(on)

    def close(self):
        self.closed = True


class NoDictation:
    """Stands in for dictation: no test ever opens the real microphone."""
    listening = False

    def __init__(self, cfg, notify, beep=None):
        self.presses = 0

    def toggle(self):
        self.presses += 1
        self.listening = not self.listening
        return "listening" if self.listening else "typing"


MENU = """import json, sys
print(json.dumps({"icon": "--no-icon" not in sys.argv, "keys": {} if "--no-keys" in sys.argv else
                  {"open": "Control+Option+J", "talk": "Control+Option+T", "made up": "x"}}), flush=True)
print("talk", flush=True)
print("nonsense", flush=True)
print("open", flush=True)
for line in sys.stdin:
    if line.strip() == "dictating 1":
        print("dictate", flush=True)
"""


class TestTheMenuBarAndTheShortcuts(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.load()
        self.script = self.tmp / "menu.py"
        self.script.write_text(MENU, "utf-8")
        patch = mock.patch.object(system, "PLATFORM", "darwin")
        patch.start()
        self.addCleanup(patch.stop)

    def menu(self, actions, **ways):
        started = []

        def start(argv, **kw):
            started.append(argv)
            return subprocess.Popen([sys.executable, str(self.script), *argv[1:]], **kw)
        made = tray.MacMenu(actions, program="jarvis-menu", start=start, **ways)
        self.addCleanup(made.close)
        return made, started

    def wait(self, check, seconds=5.0):
        until = time.time() + seconds
        while time.time() < until and not check():
            time.sleep(0.02)
        return check()

    def test_what_the_menu_or_a_shortcut_asks_for_is_done(self):
        done = []

        def broken():
            raise RuntimeError("this one fails")
        menu, started = self.menu({"talk": broken, "open": lambda: done.append("open"), "dictate": lambda: done.append("dictate")})
        self.assertTrue(menu.open())
        self.assertEqual((menu.icon, menu.keys), (True, {"open": "Control+Option+J", "talk": "Control+Option+T"}), "only shortcuts JARVIS knows are taken")
        self.assertEqual(started, [["jarvis-menu"]])
        self.assertTrue(self.wait(lambda: done == ["open"]), "the one that failed did not stop the next; a word it does not know is ignored")
        menu.dictating(True)
        self.assertTrue(self.wait(lambda: done == ["open", "dictate"]), "the menu is told when dictation is listening")
        proc = menu.proc
        self.assertTrue(menu.running())
        menu.close()
        proc.wait(timeout=5)
        self.assertFalse(menu.running())

    def test_the_icon_or_the_shortcuts_can_be_left_out_and_without_the_program_there_are_none(self):
        menu, started = self.menu({}, icon=False)
        self.assertTrue(menu.open())
        self.assertEqual((menu.icon, started), (False, [["jarvis-menu", "--no-icon"]]))
        neither, started = self.menu({}, icon=False, keys=False)
        self.assertEqual((neither.open(), started), (False, []), "nothing to show and nothing to hear: it is not started")
        with mock.patch.dict(os.environ, {"JCC_MENU_HELPER": str(self.tmp / "missing")}):
            if not (config.ROOT / "bin" / tray.MacMenu.NAME).is_file():
                self.assertFalse(tray.MacMenu({}).open(), "the program is not installed")

    def test_the_helper_does_what_the_menu_asks_and_says_which_shortcuts_work(self):
        made = {}

        class Menu(NoMenu):
            icon, keys = True, {"open": "Control+Option+J", "dictate": "Control+Option+D"}

            def __init__(self, actions, icon=True, keys=True):
                super().__init__(actions)
                made["menu"], made["wanted"] = self, (icon, keys)

        class Dictation(NoDictation):
            def __init__(self, cfg, notify, beep=None):
                super().__init__(cfg, notify, beep)
                made["dictation"] = self

        class Ears:
            problem, note, engine = "", "", ""

            def __init__(self, *a, **k):
                pass

            def sync(self):
                return False

            def stop(self):
                made["ears stopped"] = True
        opened, talked = [], []
        with mock.patch.object(tray, "open_jarvis", lambda: opened.append(1)), mock.patch.object(tray, "talk", lambda cfg: talked.append(1)):
            import threading
            helper = threading.Thread(target=lambda: made.setdefault("exit", tray.listen_only(self.cfg, pause=0.1, make_ears=Ears, make_menu=Menu, make_dictation=Dictation)), daemon=True)
            helper.start()
            self.assertTrue(self.wait(lambda: (self.cfg.state_dir / "tray-status.json").exists() and "menu" in made))
            status = json.loads((self.cfg.state_dir / "tray-status.json").read_text("utf-8"))
            self.assertEqual((status["tray"], status["keys"]), (True, {"open": "Control+Option+J", "dictate": "Control+Option+D"}))
            self.assertEqual((status["open_hotkey"], status["dictate_hotkey"], status["talk_hotkey"], status["stop_hotkey"]), (True, True, False, False))
            actions = made["menu"].actions
            self.assertEqual(sorted(actions), ["dictate", "open", "quit", "stop", "talk"])
            actions["open"]()
            actions["talk"]()
            actions["stop"]()
            self.assertEqual((opened, talked, (self.cfg.state_dir / "computer-stop").read_text("utf-8")), ([1], [1], "stop"), "the emergency stop is the same file as on Windows")
            actions["dictate"]()
            self.assertTrue(self.wait(lambda: made["menu"].told == [True]), 'the menu then offers "Finish dictating"')
            actions["dictate"]()
            self.assertTrue(self.wait(lambda: made["menu"].told == [True, False]))
            actions["quit"]()
            helper.join(timeout=5)
        self.assertFalse(helper.is_alive(), '"Hide this icon" ends the helper')
        self.assertEqual((made["exit"], made.get("ears stopped"), getattr(made["menu"], "closed", False), made["wanted"]), (0, True, True, (True, True)))

    def test_typing_waits_until_the_shortcuts_keys_are_let_go(self):
        from jcc import dictate, macax
        held = iter([True, True, False])
        with mock.patch.object(macax, "mac", lambda: type("Mac", (), {"modifiers_held": staticmethod(lambda: next(held))})()):
            if os.name != "nt":                         # (on Windows itself, Windows' own keys are asked)
                self.assertTrue(dictate.keys_released(2.0))
        with mock.patch.object(macax, "mac", lambda: type("Mac", (), {"modifiers_held": staticmethod(lambda: True)})()):
            if os.name != "nt":
                self.assertFalse(dictate.keys_released(0.15), "still held: nothing is typed")

    def test_dictation_types_with_the_macs_keys_and_says_so_when_macos_has_not_allowed_it(self):
        from jcc import dictate

        class NotAllowed(OSError):
            pass

        class Recorder:
            heard_speech = True

            def start(self):
                pass

            def finished_speaking(self):
                return False

            def stop(self):
                return b"\x01\x00" * 16000
        typed, said = [], []

        class Desk:
            def perform(self, step):
                typed.append(step)
        with mock.patch.object(dictate, "keys_released", lambda timeout=2.0: True):
            one = dictate.Dictation(self.cfg, said.append, recorder=Recorder, desktop=Desk(), hear=lambda sound: "hello  there", beep=lambda pitch: None)
            self.assertEqual((one.toggle(), one.toggle()), ("listening", "typing"))
            self.assertTrue(self.wait(lambda: typed == [{"action": "type", "text": "hello there "}]))

            class Refusing:
                def perform(self, step):
                    raise NotAllowed("macOS has not yet allowed JARVIS to control other apps. Open System Settings, Privacy & Security, Accessibility.")
            two = dictate.Dictation(self.cfg, said.append, recorder=Recorder, desktop=Refusing(), hear=lambda sound: "hello", beep=lambda pitch: None)
            two.toggle()
            two.toggle()
            self.assertTrue(self.wait(lambda: bool(said)))
            self.assertIn("Privacy & Security, Accessibility", said[0], "the owner is told what to switch on, not that the internet is down")

    @unittest.skipIf(os.name == "nt", "on Windows itself the Windows way of finding the window is used")
    def test_open_brings_jarviss_window_forward_or_opens_one(self):
        from jcc import winctl
        started, focused = [], []
        rows = [{"handle": 5, "title": "Notes - TextEdit"}, {"handle": 7, "title": "JARVIS · Workspace - Google Chrome"}]
        with mock.patch.object(tray, "start_window", lambda listen=True: started.append(listen)), mock.patch.object(winctl, "windows", lambda: rows), \
                mock.patch.object(winctl, "focus", lambda handle: focused.append(handle) or True):
            tray.open_jarvis()
            self.assertEqual((focused, started), ([7], []), "its own window, brought to the front")
            rows.pop()
            tray.open_jarvis()
            self.assertEqual(started, [False], "no window is open: one is opened (not listening)")


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
        self.assertEqual(tray.listen_only(self.cfg, once=True, make_ears=Ears, make_menu=NoMenu, make_dictation=NoDictation), 0)
        status = json.loads((self.cfg.state_dir / "tray-status.json").read_text("utf-8"))
        self.assertEqual((status["tray"], status["keys"], status["wake"], status["wake_engine"], status["wake_problem"]), (False, {}, True, "neural", ""))
        self.assertTrue(made[0].stopped, "the listener is stopped when the helper stops")
        self.assertEqual(sorted(made[0].ways), ["attend", "beep", "busy", "control", "listen", "name_said", "sound"])
        again = InstanceLock(self.cfg.state_dir / "tray.lock")
        self.assertTrue(again.acquire(), "it let go of its lock when it stopped")
        try:
            (self.cfg.state_dir / "tray-status.json").unlink()
            self.assertEqual(tray.listen_only(self.cfg, once=True, make_ears=Ears, make_menu=NoMenu, make_dictation=NoDictation), 0)
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
