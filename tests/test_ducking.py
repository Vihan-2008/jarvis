"""Other sounds made quieter while JARVIS listens (jcc/ducking.py). The PC's real sound is never touched here: a stand-in
keeps the volumes."""
import json
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

from jcc import ducking


class Sound:
    """Three programs playing; "jarvis" is JARVIS's own window."""

    def __init__(self):
        self.volumes = {"music": 0.8, "game": 1.0, "jarvis": 0.9}
        self.changes = 0
        self.done = threading.Event()

    def lower(self, level):
        saved = {}
        for name, now in self.volumes.items():
            if name != "jarvis" and now > 0:
                self.volumes[name] = now * level
                saved[name] = now
        self.changes += 1
        self.done.set()
        return saved

    def restore(self, saved, level):
        for name, was in saved.items():
            if abs(self.volumes[name] - was * level) < 0.02:
                self.volumes[name] = was
        self.changes += 1
        self.done.set()


class TestDucking(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="jcc-duck-"))
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))
        self.sound = Sound()
        self.ducker = ducking.Ducker(self.dir, backend=self.sound, level=0.2, stale=0.6)

    def wait(self):
        self.assertTrue(self.sound.done.wait(3)); self.sound.done.clear()
        time.sleep(0.05)

    def test_quieter_while_listening_and_back_while_thinking(self):
        self.ducker.update(True); self.wait()
        self.assertEqual(self.sound.volumes, {"music": 0.16000000000000003, "game": 0.2, "jarvis": 0.9}, "JARVIS's own sound is left alone")
        self.ducker.update(True)                     # still listening: nothing more is done
        time.sleep(0.1)
        self.assertEqual(self.sound.changes, 1)
        self.assertTrue((self.dir / "ducked.json").exists(), "written down first, so it is always put back")
        self.ducker.update(False); self.wait()
        self.assertEqual(self.sound.volumes, {"music": 0.8, "game": 1.0, "jarvis": 0.9})
        self.assertFalse((self.dir / "ducked.json").exists())

    def test_a_volume_its_owner_changed_meanwhile_is_left_as_they_set_it(self):
        self.ducker.update(True); self.wait()
        self.sound.volumes["music"] = 0.5            # turned up by hand while JARVIS listened
        self.ducker.update(False); self.wait()
        self.assertEqual((self.sound.volumes["music"], self.sound.volumes["game"]), (0.5, 1.0))

    def test_listening_that_nobody_confirms_ends_by_itself(self):
        self.ducker.update(True); self.wait()
        self.wait()                                  # (a window that closed while listening: after a moment it is put back)
        self.assertEqual(self.sound.volumes["game"], 1.0)

    def test_after_a_crash_the_sound_is_put_back_at_start(self):
        self.ducker.update(True); self.wait()
        again = ducking.Ducker(self.dir, backend=self.sound, level=0.2)
        again.recover()
        self.assertEqual(self.sound.volumes["game"], 1.0)
        self.assertFalse((self.dir / "ducked.json").exists())

    def test_nothing_is_done_where_sound_cannot_be_changed(self):
        quiet = ducking.Ducker(self.dir, backend=None)
        quiet.update(True); quiet.update(False)
        self.assertFalse((self.dir / "ducked.json").exists())

    def test_the_tests_never_get_the_real_sound(self):
        self.assertIsNone(ducking.default_backend(), "JCC_NO_DUCKING is set for every test")


if __name__ == "__main__":
    unittest.main()
