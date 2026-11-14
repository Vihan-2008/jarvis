"""Telling the PC's own sound from the person in the room.

A microphone next to speakers hears a video, a film or music just as it hears its owner, and a voice assistant that
takes a film's dialogue for instructions is worse than useless. Windows knows how loud everything it is playing is at
each moment. If what the microphone heard rises and falls in step with that, it was the PC's own sound and not a
person, and it is ignored. Someone talking over a film does not follow the film's rise and fall, so they are still
heard. Nothing is recorded here: only loudness, a few dozen numbers a second, kept for a minute.
"""
from __future__ import annotations

import collections
import os
import threading
import time

STEP = 0.02                    # the microphone's loudness arrives in pieces of this length (seconds)
QUIET = 0.004                  # below this the PC is as good as silent
PC_SOUND = 0.5                 # how closely the microphone must follow the PC's sound to be called the PC's sound
HEARD = 0.35                   # ... and to say "the microphone can hear the speakers" at all


def follows(mic: list[float], out: list[float]) -> float:
    """How closely one loudness line follows another, -1 to 1 (0 when either is flat or too short)."""
    count = min(len(mic), len(out))
    if count < 12:
        return 0.0
    a, b = mic[:count], out[:count]
    mean_a, mean_b = sum(a) / count, sum(b) / count
    top = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    spread = (sum((x - mean_a) ** 2 for x in a) * sum((y - mean_b) ** 2 for y in b)) ** 0.5
    return top / spread if spread > 1e-12 else 0.0


def smooth(values: list[float]) -> list[float]:
    """Each value averaged with its neighbours: speech's rise and fall, without the jitter."""
    if len(values) < 3:
        return list(values)
    return [(values[max(0, i - 1)] + values[i] + values[min(len(values) - 1, i + 1)]) / 3 for i in range(len(values))]


class Monitor:
    """Keeps the last minute of how loud the PC's own sound was. Runs only while someone asks (a voice chat is awake)."""

    def __init__(self, meter=None, clock=time.time):
        self.make_meter, self.clock = meter, clock
        self.samples: collections.deque = collections.deque(maxlen=4000)     # (when, loudness 0..1)
        self.lock, self.thread, self.wanted_until, self.failed_at = threading.Lock(), None, 0.0, 0.0

    # ------------------------------------------------------------------ measuring
    def want(self, seconds: float = 30.0) -> None:
        """Keep measuring for a while longer (called whenever a voice chat is listening)."""
        self.wanted_until = max(self.wanted_until, self.clock() + seconds)
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            if self.clock() - self.failed_at < 60:          # no sound device, or Windows will not say: do not hammer it
                return
            self.thread = threading.Thread(target=self._run, daemon=True, name="pc-sound")
            self.thread.start()

    def _run(self) -> None:
        try:
            if self.make_meter:
                meter = self.make_meter()
            else:
                from jcc.winctl import OutputMeter
                meter = OutputMeter()
            meter.open()
        except Exception:  # noqa: BLE001 - without a meter everything is simply treated as coming from the room
            self.failed_at = self.clock()
            return
        opened = self.clock()
        try:
            while self.clock() < self.wanted_until:
                try:
                    self.add(self.clock(), meter.peak())
                except Exception:  # noqa: BLE001 - the speakers were unplugged or changed: start again with the new ones
                    break
                if self.clock() - opened > 8:               # follow a change of Windows' default speakers
                    meter.close()
                    meter.open()
                    opened = self.clock()
                time.sleep(STEP)
        finally:
            try:
                meter.close()
            except Exception:  # noqa: BLE001
                pass

    def add(self, when: float, loudness: float) -> None:
        self.samples.append((float(when), max(0.0, min(1.0, float(loudness)))))

    def line(self, start: float, count: int) -> list[float] | None:
        """The PC's loudness on the microphone's grid: `count` pieces of STEP seconds from `start`. None if it was not being measured then."""
        rows = [row for row in self.samples if start - 1.0 <= row[0] <= start + count * STEP + 1.0]
        if len(rows) < 5 or rows[0][0] > start + 0.25 or rows[-1][0] < start + count * STEP - 0.25:
            return None
        out, at = [], 0
        for index in range(count):
            moment = start + index * STEP
            while at + 1 < len(rows) and rows[at + 1][0] <= moment:
                at += 1
            out.append(max(rows[at][1], rows[min(at + 1, len(rows) - 1)][1]))     # the louder of the two nearest readings
        return out

    # ------------------------------------------------------------------ judging
    def compare(self, start: float, levels: list[float]) -> tuple[bool, float, list[float]]:
        """(was the PC playing during this stretch, how closely the microphone followed it, the PC's loudness lined up with it)."""
        levels = [max(0.0, float(v)) for v in levels][:3000]
        if len(levels) < 12:
            return False, 0.0, []
        best, playing, lined = 0.0, False, []
        mic = smooth(levels)
        for lag in range(-4, 22, 2):                        # the microphone hears it up to 0.4 s after Windows plays it
            out = self.line(start - lag * STEP, len(levels))
            if out is None:
                continue
            if sum(1 for v in out if v > QUIET) >= 0.3 * len(out):
                playing = True
                score = follows(mic, smooth(out))
                if score > best or not lined:
                    best, lined = max(best, score), out
        return playing, best, lined

    def _louder_with_pc(self, start: float, mic: list[float]) -> float | None:
        """How much louder the microphone's sound is while the PC plays than in the PC's own pauses (1 = no louder).
        None when the PC's sound had no pauses to compare with (music, for instance)."""
        out = self.line(start, len(mic))
        if out is None:
            return None
        during, between = [], []
        for index, level in enumerate(mic):
            lately = out[max(0, index - 8):index + 3]               # what the PC played around this moment (sound arrives a little late)
            if max(lately) < QUIET:
                between.append(level)
            elif max(out[max(0, index - 8):index + 1]) > 4 * QUIET:
                during.append(level)
        if len(during) < 10 or len(between) < 8:
            return None
        return (sum(during) / len(during)) / max(1e-6, sum(between) / len(between))

    def verdict(self, start: float, levels: list[float], before: list[float] | None = None) -> dict:
        """What to make of something the microphone picked up.

        pc: it was the PC's own sound (ignore it).  playing: the PC was playing something at the time.
        heard: whether the microphone can hear the speakers at all (False with headphones; None when that cannot be told).

        `before` is the microphone's loudness just before this sound began, when nobody was talking. If the PC was playing
        then, it shows how loudly (if at all) the speakers reach the microphone. A sound is the PC's own when that
        accounts for nearly all of it; a person adds sound of their own on top, or speaks while the PC is quiet."""
        self.want()
        now = self.clock()
        levels = [max(0.0, float(v)) for v in levels][:3000]
        playing, score, out = self.compare(start, levels)
        # reach: how loud the speakers are at the microphone, per unit the PC plays
        reach = self._reach(start - len(before) * STEP, before) if before and len(before) >= 50 else None
        if reach is not None:
            self.reach, self.reach_at = reach, now
        elif getattr(self, "reach", None) is not None and now - self.reach_at < 120:
            reach = self.reach                              # learned a moment ago
        heard = None if reach is None else reach > 0
        if not playing or len(levels) < 12:
            pc = False
        elif reach is None:                                 # nothing to go on but the rise and fall: only an unmistakable match counts
            pc = score >= 0.75 and len(levels) >= 75
            heard = True if pc else heard
        elif reach <= 0:
            pc = False
        else:
            mic = smooth(levels)
            floor = sorted(mic)[len(mic) // 10]             # the room's own hum
            explained = sum(min(m, 1.6 * reach * o + floor) for m, o in zip(mic, smooth(out))) / max(1e-9, sum(mic))
            pc = explained >= 0.9 and score >= 0.3
        return {"pc": bool(pc), "playing": bool(playing), "heard": heard, "score": round(score, 2)}

    def _reach(self, start: float, quiet: list[float]) -> float | None:
        """How loudly the PC's own sound reaches the microphone, from a stretch in which nobody was talking.
        0: not at all (headphones). None: it cannot be told from this stretch."""
        was_playing, background, back_out = self.compare(start, quiet)
        if not was_playing:
            return None
        quiet_mic = [max(0.0, float(v)) for v in quiet]
        louder = self._louder_with_pc(start, quiet_mic)
        if background >= HEARD and (louder is None or louder >= 1.3):
            ratios = sorted(m / o for m, o in zip(smooth(quiet_mic), back_out) if o > 4 * QUIET)
            return ratios[len(ratios) // 2] if len(ratios) >= 10 else None
        if background <= 0.2 or (louder is not None and louder <= 1.2):
            return 0.0                                      # the PC was playing and the microphone did not notice: headphones
        return None

    def learn(self, start: float, levels: list[float]) -> float | None:
        """Take note of how loudly the PC reaches the microphone, from the microphone's loudness over the last few seconds.
        (The always-on wake word does this now and then, so that it is already known when someone speaks.)"""
        if len(levels) < 50:
            return None
        reach = self._reach(start, [max(0.0, float(v)) for v in levels][:3000])
        if reach is not None:
            self.reach, self.reach_at = reach, self.clock()
        return reach

    def echo_now(self) -> float:
        """How loud the PC's own sound is at the microphone at this moment: 0 when it is silent, cannot be heard there, or that is not known."""
        reach = getattr(self, "reach", None)
        if not reach or self.clock() - self.reach_at > 120:
            return 0.0
        now = self.clock()
        recent = [level for when, level in self.samples if now - when <= 0.35]
        return reach * max(recent) if recent else 0.0

    def lately(self, seconds: float = 10.0) -> bool | None:
        """Has the PC played anything in the last few seconds? None when that has not been measured (nobody was listening)."""
        self.want()
        now = self.clock()
        recent = [level for when, level in self.samples if now - when <= seconds]
        if len(recent) < seconds * 2:                      # (measured about ten times a second while a voice chat is awake)
            return None
        return sum(1 for level in recent if level > QUIET) >= 5

    def playing_now(self, seconds: float = 1.0) -> bool:
        """Is the PC playing something right now?"""
        self.want()
        now = self.clock()
        recent = [level for when, level in self.samples if now - when <= seconds]
        return len(recent) >= 5 and sum(1 for level in recent if level > QUIET) >= 0.5 * len(recent)


def levels_of(sound: bytes, piece: int = 640) -> list[float]:
    """How loud a recording is, piece by piece (raw 16-bit, 16 kHz mono sound; 640 bytes are STEP seconds)."""
    from jcc.dictate import loudness
    return [loudness(sound[at:at + piece]) for at in range(0, len(sound) - piece + 1, piece)]


shared = Monitor() if os.name == "nt" else Monitor(meter=lambda: (_ for _ in ()).throw(OSError("Windows only")))
