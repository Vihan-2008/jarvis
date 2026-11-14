"""Telling the PC's own sound (a video, a film, music) from the person in the room, by loudness alone."""
import math
import random
import unittest

from jcc import pcsound

STEP = pcsound.STEP


def speech(seed: int, seconds: float, loud: float = 0.2) -> list[float]:
    """A made-up loudness line that rises and falls the way talking does: syllables, words and pauses."""
    rng, out, at = random.Random(seed), [], 0
    total = int(seconds / STEP)
    while at < total:
        if rng.random() < 0.22:                                   # a pause between words
            gap = rng.randint(4, 18)
            out += [0.0] * gap
            at += gap
            continue
        length, peak = rng.randint(6, 16), loud * rng.uniform(0.4, 1.0)
        out += [peak * math.sin(math.pi * (i + 0.5) / length) for i in range(length)]
        at += length
    return out[:total]


def room(seed: int, seconds: float, loud: float = 0.004) -> list[float]:
    rng = random.Random(seed)
    return [loud * rng.uniform(0.5, 1.5) for _ in range(int(seconds / STEP))]


class TestPcSound(unittest.TestCase):
    def monitor(self, playing: list[float], start: float = 1000.0) -> pcsound.Monitor:
        """A monitor that has been measuring: one second of silence, then `playing`, then silence."""
        self.now = start + len(playing) * STEP + 2.0
        found = pcsound.Monitor(meter=lambda: None, clock=lambda: self.now)
        found.want = lambda seconds=30.0: None                    # no real sound device in tests
        line = [0.0] * 50 + playing + [0.0] * 100
        for index, level in enumerate(line):
            found.add(start - 1.0 + index * STEP + 0.007, level)  # Windows' readings do not fall exactly on the microphone's grid
        return found

    def heard_by_microphone(self, played: list[float], late: int = 6, share: float = 0.3, seed: int = 9) -> list[float]:
        """What a microphone near the speakers picks up: the same sound a little later and quieter, plus the room."""
        noise = room(seed, len(played) * STEP)
        return [share * (played[i - late] if i >= late else 0.0) + noise[i] for i in range(len(played))]

    def test_a_video_playing_through_the_speakers_is_the_pcs_own_sound(self):
        film = speech(1, 6)
        monitor = self.monitor(film)
        for late in (2, 6, 14):                                   # near and far speakers, quick and slow sound cards
            mic = self.heard_by_microphone(film, late)
            found = monitor.verdict(1000.0 + 1.0, mic[50:200])    # three seconds from the middle of it
            self.assertTrue(found["pc"], (late, found))
            self.assertTrue(found["playing"] and found["heard"])

    def test_a_person_is_heard_when_nothing_is_playing(self):
        monitor = self.monitor([0.0] * 300)
        found = monitor.verdict(1000.0 + 1.0, speech(2, 3))
        self.assertEqual((found["pc"], found["playing"]), (False, False))

    def test_a_person_talking_while_something_plays_in_headphones_is_heard(self):
        film = speech(1, 8)
        monitor = self.monitor(film)
        me, quiet_before = speech(3, 2.5), room(4, 3)
        found = monitor.verdict(1000.0 + 4.0, me, quiet_before)   # the microphone heard only the room before I spoke
        self.assertEqual((found["pc"], found["playing"], found["heard"]), (False, True, False), found)

    def test_a_person_talking_over_a_film_on_speakers_is_not_taken_for_the_film(self):
        film = speech(1, 8)
        monitor = self.monitor(film)
        from_speakers = self.heard_by_microphone(film, 6, 0.25)
        me = speech(5, 2.5, loud=0.35)
        mixed = [me[i] + from_speakers[200 + i] for i in range(len(me))]
        found = monitor.verdict(1000.0 + 4.0, mixed, from_speakers[50:200])
        self.assertFalse(found["pc"], found)                      # mostly me: not thrown away as the PC's sound...
        self.assertEqual((found["playing"], found["heard"]), (True, True), found)   # ...but the speakers are audible, so care is needed

    def test_other_people_talking_are_not_mistaken_for_the_pc(self):
        film = speech(1, 8)
        monitor = self.monitor(film)
        wrong = sum(monitor.verdict(1000.0 + 2.0, speech(seed, 2.5))["pc"] for seed in range(20, 60))
        self.assertLessEqual(wrong, 1, "an unrelated voice almost never looks like the PC's sound")

    def test_without_measurements_everything_counts_as_the_room(self):
        monitor = pcsound.Monitor(meter=lambda: None, clock=lambda: 5000.0)
        monitor.want = lambda seconds=30.0: None
        found = monitor.verdict(4990.0, speech(2, 3), room(1, 3))
        self.assertEqual((found["pc"], found["playing"], found["heard"]), (False, False, None))
        self.assertEqual(monitor.verdict(4990.0, [0.1] * 5)["pc"], False, "too short to judge")

    def test_is_something_playing_right_now(self):
        music = speech(7, 4, loud=0.1)
        monitor = self.monitor(music)
        self.now = 1000.0 + 2.0
        monitor.samples = type(monitor.samples)([row for row in monitor.samples if row[0] <= self.now], maxlen=4000)
        self.assertTrue(monitor.playing_now())
        self.now = 1000.0 + len(music) * STEP + 1.9
        monitor.samples = type(monitor.samples)(list(self.monitor(music).samples), maxlen=4000)
        self.assertFalse(monitor.playing_now())

    def test_loudness_of_a_recording_piece_by_piece(self):
        import struct
        loud, soft = struct.pack("<320h", *([8000, -8000] * 160)), struct.pack("<320h", *([40, -40] * 160))
        found = pcsound.levels_of(loud * 3 + soft * 2)
        self.assertEqual(len(found), 5)
        self.assertTrue(all(v > 0.2 for v in found[:3]) and all(v < 0.01 for v in found[3:]))

    def test_the_monitor_measures_only_while_asked_and_survives_a_missing_device(self):
        class Meter:
            opened = closed = 0

            def open(self):
                Meter.opened += 1

            def peak(self):
                return 0.25

            def close(self):
                Meter.closed += 1

        monitor = pcsound.Monitor(meter=Meter)
        monitor.want(0.25)
        import time
        time.sleep(0.6)
        self.assertGreaterEqual(len(monitor.samples), 5)
        self.assertFalse(monitor.thread.is_alive(), "stopped by itself when no longer asked")
        self.assertEqual((Meter.opened, Meter.closed), (1, 1))

        def broken():
            raise OSError("no speakers")
        gone = pcsound.Monitor(meter=broken)
        gone.want(0.2)
        time.sleep(0.2)
        self.assertEqual(len(gone.samples), 0)
        self.assertEqual(gone.verdict(time.time() - 1, [0.1] * 50)["pc"], False)


if __name__ == "__main__":
    unittest.main()
