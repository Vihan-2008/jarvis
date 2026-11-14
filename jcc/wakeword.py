"""Hearing "Hey JARVIS" with a small neural network that runs on this PC.

Windows' own speech recogniser (jcc/wake.py) understands a wake word that is said clearly and close by. This one is far
better at it: across a room, over music or a film, in any accent. It is openWakeWord's "hey jarvis" model (three small
files), run here with onnxruntime and numpy. Both are optional: where they are not installed, JARVIS listens the old way.

Nothing leaves the PC and nothing is kept: the last few seconds of sound live in memory only, so that what is said
straight after the name is not lost.
"""
from __future__ import annotations

import collections
import importlib.util
import threading
import time
from pathlib import Path

from jcc.dictate import Recorder, loudness

RATE = 16000
STEP = 1280                    # the model looks at the sound in steps of this many samples (80 ms)
SURE, MAYBE = 0.75, 0.3        # a score this high is the name for certain; from MAYBE up it is checked before anything happens
FILES = {"mel": "melspectrogram.onnx", "embed": "embedding_model.onnx", "wake": "hey_jarvis_v0.1.onnx"}


def parts(cfg=None) -> dict | None:
    """Where the model's three files are, or None if this PC cannot run it (then Windows' own recogniser is used)."""
    try:
        if not importlib.util.find_spec("numpy") or not importlib.util.find_spec("onnxruntime"):
            return None
    except (ImportError, ValueError):
        return None
    places = []
    if cfg is not None:
        places.append(Path(cfg.state_dir) / "wake-models")
    try:
        spec = importlib.util.find_spec("openwakeword")          # found, not imported: its own imports are heavy and not needed
        if spec and spec.origin:
            places.append(Path(spec.origin).parent / "resources" / "models")
    except (ImportError, ValueError):
        pass
    for place in places:
        found = {name: place / file for name, file in FILES.items()}
        if all(path.is_file() for path in found.values()):
            return found
    return None


class Spotter:
    """Scores sound for the wake word, step by step. 0 is "not it", 1 is "certainly it"."""

    def __init__(self, files: dict):
        import numpy
        import onnxruntime
        self.np = numpy
        options = onnxruntime.SessionOptions()
        options.inter_op_num_threads = options.intra_op_num_threads = 1      # it needs a few thousandths of a second per step: never more than one core
        options.log_severity_level = 3

        def load(name):
            return onnxruntime.InferenceSession(str(files[name]), sess_options=options, providers=["CPUExecutionProvider"])
        self.mel, self.embed, self.wake = load("mel"), load("embed"), load("wake")
        self.wake_input = self.wake.get_inputs()[0].name
        self.reset()

    def reset(self) -> None:
        np = self.np
        self.left = b""
        self.raw = np.zeros(0, dtype=np.int16)
        self.spectrum = np.ones((76, 32), dtype=np.float32)
        # The model wants a second and a half of history. It starts with the features of soft noise, as openWakeWord does.
        noise = np.random.default_rng(7).integers(-1000, 1000, RATE * 4).astype(np.int16)
        spectrum = self._spectrum(noise)
        windows = [spectrum[at:at + 76] for at in range(0, spectrum.shape[0], 8) if spectrum[at:at + 76].shape[0] == 76]
        self.features = self.embed.run(None, {"input_1": np.expand_dims(np.array(windows), -1).astype(np.float32)})[0].reshape(len(windows), -1)

    def _spectrum(self, samples):
        np = self.np
        return np.squeeze(self.mel.run(None, {"input": samples[None].astype(np.float32)})[0]) / 10 + 2

    def feed(self, sound: bytes) -> list[float]:
        """Take more sound (raw 16-bit, 16 kHz, one channel). Returns one score for each whole step it completed."""
        np = self.np
        data = self.left + sound
        whole = len(data) // (STEP * 2) * STEP * 2
        self.left = data[whole:]
        scores = []
        for at in range(0, whole, STEP * 2):
            step = np.frombuffer(data, dtype=np.int16, count=STEP, offset=at)
            self.raw = np.concatenate((self.raw, step))[-RATE * 3:]
            self.spectrum = np.vstack((self.spectrum, self._spectrum(self.raw[-STEP - 480:])))[-970:]
            feature = self.embed.run(None, {"input_1": self.spectrum[-76:].astype(np.float32)[None, :, :, None]})[0].reshape(1, -1)
            self.features = np.vstack((self.features, feature))[-120:]
            scores.append(float(self.wake.run(None, {self.wake_input: self.features[-16:][None].astype(np.float32)})[0][0][0]))
        return scores


class Following(Recorder):
    """What is said after the name, taken from the very stream that heard the name, so not a word is lost in between.

    It knows how loud the room was just before (a fan, a film), and how loud the PC's own sound reaches the microphone,
    so that it can tell when the person has finished speaking even while something else is making noise.

    A room with other sound in it (a film on another device, people talking) never goes quiet, so waiting for quiet
    would mean waiting for the film to pause. There the question is who is speaking. The name itself was said by the
    person: that is how loud their voice is (`voice`). The room just before it shows how loud its own louder moments
    are (`high`). What is still as loud as the person's voice is the person; what has fallen back to the room is the
    room. `stands_out()` says whether the two can be told apart that way at all."""

    def __init__(self, quiet: float = 0.8, floor: float = 0.0, echo=None, high: float = 0.0, voice: float = 0.0):
        super().__init__(quiet=quiet)
        self.floor, self.echo, self.closed = floor, echo, False
        self.high, self.voice = high, voice
        self.busy = high > 0.012                       # the room's louder moments would themselves pass for a voice
        self.last: collections.deque = collections.deque(maxlen=3)

    def start(self) -> None:                              # it is already being fed
        pass

    def limit(self) -> float:
        """How loud a piece must be to count as someone speaking, right now."""
        echo = 0.0
        if self.echo:
            try:
                echo = float(self.echo() or 0.0)
            except Exception:  # noqa: BLE001 - not knowing is the same as silence
                echo = 0.0
        quiet = max(0.012, self.floor * 2.2, self.floor + echo * 1.8)
        if self.busy and self.voice:
            return max(quiet, min(self.high * 1.15, self.voice * 0.6), self.voice * 0.4)
        return quiet

    def stands_out(self) -> bool:
        """Can the person be told from the room by how loud they are? (Not when the room is as loud as their voice.)"""
        return not self.busy or self.voice > self.high * 1.5

    def _take(self, piece: bytes) -> None:
        if self.closed:
            return
        self.pieces.append(piece)
        loud = loudness(piece) > self.limit()
        self.last.append(loud)
        # In a room with other sound, one loud moment of the film is not the person speaking again: two of the last three
        # pieces have to be.
        speaking = sum(self.last) >= 2 if self.busy else loud
        if speaking:
            self.heard_speech, self.quiet_since = True, 0.0
            if loud:
                self.voiced += len(piece) / (RATE * 2.0)
        elif self.heard_speech and not self.quiet_since:
            self.quiet_since = time.time()

    def quiet_for(self) -> float:
        """How long it has been quiet since the last thing said (0 while someone is speaking, or before anyone has)."""
        return time.time() - self.quiet_since if self.heard_speech and self.quiet_since else 0.0

    def so_far(self) -> bytes:
        return b"".join(self.pieces)

    def stop(self) -> bytes:
        self.closed = True
        return b"".join(self.pieces)


class NeuralListener:
    """Listens to the microphone all the time and calls `heard(hit)` when the wake word is said.

    hit: {"text", "confidence" (the model's score), "grammar": "wake", "neural": True, "pcm" (the two seconds that held the
    name), "began" (when that sound started), "recorder" (a Following, already recording what comes next), "at"}."""

    def __init__(self, heard, files: dict, device: int | None = None, microphone=None, spotter=None, sound=None, clock=time.time):
        self.heard, self.files, self.device, self.clock = heard, files, device, clock
        self.make_microphone, self.make_spotter, self.sound = microphone, spotter, sound
        self.mic, self.spotter, self.ready, self.problem, self.input = None, None, threading.Event(), "", ""
        self.recent: collections.deque = collections.deque(maxlen=38)            # the last three seconds, piece by piece: (when it ended, the sound, how loud)
        self.followers: list[Following] = []
        self.rising, self.best, self.quiet_until, self.learned_at, self.last_piece = 0, 0.0, 0.0, 0.0, 0.0
        self.lock = threading.Lock()

    def start(self) -> None:
        try:
            self.spotter = self.make_spotter(self.files) if self.make_spotter else Spotter(self.files)
        except Exception as problem:  # noqa: BLE001 - a broken install must fall back to Windows' own recogniser, not stop the helper
            self.problem = str(problem)[:200]
            self.ready.set()
            raise ValueError("The wake word model could not be loaded.") from None
        if self.make_microphone:
            mic = self.make_microphone(self.device)
        else:
            from jcc.sound import Microphone
            mic = Microphone(self.device, STEP * 2)
        mic.start(self._piece)                           # raises ValueError if no microphone can be opened
        self.mic = mic
        self.input = "default" if getattr(mic, "used_default", self.device is None) else "chosen"
        self.last_piece = self.clock()
        self.ready.set()

    def running(self) -> bool:
        mic = self.mic
        if not mic or not mic.alive():
            return False
        return self.clock() - self.last_piece < 20       # a microphone that has gone silent (unplugged) counts as stopped

    def stop(self) -> None:
        mic, self.mic = self.mic, None
        if mic:
            threading.Thread(target=mic.stop, daemon=True, name="wake-microphone-stop").start()

    # ------------------------------------------------------------------ each piece of sound
    def _piece(self, piece: bytes) -> None:
        now = self.clock()
        self.last_piece = now
        level = loudness(piece)
        self.recent.append((now, piece, level))
        with self.lock:
            followers = list(self.followers)
        for follower in followers:
            follower._take(piece)
            if follower.closed:
                with self.lock:
                    if follower in self.followers:
                        self.followers.remove(follower)
        self._learn(now)
        try:
            scores = self.spotter.feed(piece)
        except Exception as problem:  # noqa: BLE001
            self.problem = str(problem)[:200]
            raise                                       # ends the recording; Ears notices and falls back
        for score in scores:
            self._score(score, now)

    def _learn(self, now: float) -> None:
        """Every couple of seconds: note how loudly (if at all) the PC's own sound reaches this microphone."""
        if not self.sound or now - self.learned_at < 2.0 or len(self.recent) < 30 or self.followers:
            return
        self.learned_at = now
        try:
            self.sound.want(30)
            if self.sound.playing_now(1.0):
                levels = self._levels([sound for _, sound, _ in self.recent])
                self.sound.learn(self.recent[0][0] - len(self.recent[0][1]) / (RATE * 2.0), levels)
        except Exception:  # noqa: BLE001 - this is a refinement, never a reason to stop listening
            pass

    @staticmethod
    def _levels(pieces: list[bytes]) -> list[float]:
        from jcc.pcsound import levels_of
        return levels_of(b"".join(pieces))

    def _score(self, score: float, now: float) -> None:
        if now < self.quiet_until:
            return
        if score >= MAYBE:
            self.rising += 1
            self.best = max(self.best, score)
            # A certain match is acted on at once; a doubtful one is given a quarter of a second to become certain.
            if self.best >= SURE or self.rising >= 4:
                self._fire(now)
        elif self.rising:
            self._fire(now)

    def _fire(self, now: float) -> None:
        score, self.rising, self.best = self.best, 0, 0.0
        self.quiet_until = now + 1.5                     # the same "Hey JARVIS" must not be heard twice
        held = list(self.recent)
        name = held[-25:]                                # the two seconds that held the name
        before = sorted(level for _, _, level in held[:-19])   # the room before the name was said
        floor = before[len(before) // 2] if len(before) >= 6 else 0.0
        high = before[int(len(before) * 0.9)] if len(before) >= 6 else 0.0          # how loud its louder moments were
        said = sorted(level for _, _, level in held[-15:])                          # the name itself: this is the person's voice
        voice = said[int(len(said) * 0.8)] if len(said) >= 6 else 0.0
        follower = Following(floor=min(floor, 0.08), echo=self._echo, high=min(high, 0.25), voice=voice)
        with self.lock:
            self.followers.append(follower)
        hit = {"text": "hey jarvis", "confidence": round(score, 3), "grammar": "wake", "neural": True, "pcm": b"".join(sound for _, sound, _ in name),
               "began": name[0][0] - len(name[0][1]) / (RATE * 2.0), "recorder": follower, "at": now}

        def tell():
            try:
                self.heard(hit)
            except Exception:  # noqa: BLE001 - one bad moment must not stop the listening
                pass
            finally:
                follower.closed = True                   # whoever handled it has what they need; stop collecting
        threading.Thread(target=tell, daemon=True, name="wake-heard").start()

    def _echo(self) -> float:
        """How loud the PC's own sound is at the microphone at this moment (0 when it is not, or when that is not known)."""
        return self.sound.echo_now() if self.sound else 0.0
