"""Dictation anywhere: press the shortcut, speak, press it again, and the words are typed where the cursor is.

The microphone is recorded here directly (no window needed), the recording is transcribed by Whisper,
and the text is typed into whatever app is in front. Nothing is recorded unless the shortcut was pressed.
"""
from __future__ import annotations

import ctypes
import os
import struct
import threading
import time

RATE, PIECE = 16000, 3200          # 16 kHz, pieces of a tenth of a second
MAX_SECONDS, QUIET_SECONDS = 90, 2.5


def loudness(piece: bytes) -> float:
    """0 to 1: how loud a piece of 16-bit sound is."""
    count = len(piece) // 2
    if not count:
        return 0.0
    samples = struct.unpack(f"<{count}h", piece[:count * 2])
    return (sum(s * s for s in samples[::4]) / max(1, len(samples[::4]))) ** 0.5 / 32768


class Recorder:
    """Records a microphone until told to stop: the one chosen in Voice and assistant, or the Windows default. Tests use a fake."""

    def __init__(self, quiet: float = QUIET_SECONDS, device: int | None = None):
        self.pieces, self.mic, self.device = [], None, device
        self.heard_speech, self.quiet_since, self.quiet = False, 0.0, quiet
        self.voiced = 0.0                              # seconds of sound loud enough to be a voice

    def start(self) -> None:
        from jcc.sound import Microphone
        self.pieces, self.heard_speech, self.quiet_since, self.voiced = [], False, 0.0, 0.0
        mic = Microphone(self.device, PIECE)
        mic.start(self._take, limit=MAX_SECONDS)
        self.mic = mic

    def _take(self, piece: bytes) -> None:
        self.pieces.append(piece)
        if loudness(piece) > 0.012:
            self.heard_speech, self.quiet_since = True, 0.0
            self.voiced += len(piece) / 32000.0        # 16,000 samples a second, two bytes each
        elif self.heard_speech and not self.quiet_since:
            self.quiet_since = time.time()

    def finished_speaking(self) -> bool:
        """True once something was said and it has been quiet for a moment (so the caller can stop by itself)."""
        return bool(self.heard_speech and self.quiet_since and time.time() - self.quiet_since > self.quiet) or \
            bool(self.mic and not self.mic.alive())

    def stop(self) -> bytes:
        if self.mic:
            self.mic.stop()
        return b"".join(self.pieces)


def keys_released(timeout: float = 2.0) -> bool:
    """Wait until Ctrl, Alt, Shift and the Windows key are up, so typed letters are not taken as shortcuts."""
    if os.name != "nt":
        return True
    user32, deadline = ctypes.windll.user32, time.time() + timeout
    while time.time() < deadline:
        if not any(user32.GetAsyncKeyState(code) & 0x8000 for code in (0x10, 0x11, 0x12, 0x5B, 0x5C)):
            return True
        time.sleep(0.03)
    return False


class Dictation:
    """One press starts listening, the next (or a pause after speaking) types what was said."""

    def __init__(self, cfg, notify=None, recorder=None, desktop=None, hear=None, beep=None):
        self.cfg, self.notify = cfg, notify or (lambda text: None)
        self.make_recorder, self.desktop, self.hear, self.beep = recorder or self._recorder, desktop, hear, beep or _beep
        self.recorder, self.lock = None, threading.Lock()

    def _recorder(self):
        from jcc import sound
        return Recorder(device=sound.chosen_input(self.cfg))

    @property
    def listening(self) -> bool:
        return self.recorder is not None

    def _record(self, state: str) -> None:
        """Leave a note of what happened last, so the app (and its owner) can see the shortcut is working."""
        try:
            (self.cfg.state_dir / "dictation-status.json").write_text('{"state": "%s", "at": %d}' % (state, int(time.time())), "utf-8")
        except OSError:
            pass

    def toggle(self) -> str:
        state = self._toggle()
        self._record(state)
        return state

    def _toggle(self) -> str:
        with self.lock:
            if self.recorder:
                recorder, self.recorder = self.recorder, None
            else:
                from jcc import speech
                if not self.hear and not speech.whisper_provider():
                    self.notify("Dictation needs Whisper. Add the free Groq key in JARVIS (Voice and assistant).")
                    return "unavailable"
                try:
                    recorder = self.make_recorder()
                    recorder.start()
                except ValueError as problem:
                    self.notify(str(problem))
                    return "unavailable"
                self.recorder = recorder
                self.beep(880)
                threading.Thread(target=self._watch, args=(recorder,), daemon=True, name="dictation-watch").start()
                return "listening"
        self.beep(660)
        threading.Thread(target=self._finish, args=(recorder,), daemon=True, name="dictation-typing").start()
        return "typing"

    def _watch(self, recorder) -> None:
        """Stop by itself once the speaker has finished, so a second press is optional."""
        while self.recorder is recorder:
            if recorder.finished_speaking():
                if self.recorder is recorder:
                    self.toggle()
                return
            time.sleep(0.1)

    def _finish(self, recorder) -> None:
        try:
            sound = recorder.stop()
            if len(sound) < RATE // 2:
                return
            if not getattr(recorder, "heard_speech", True):   # only the room was heard: never type what a speech service makes of that
                self.notify("Nothing was heard. Press the shortcut and speak again.")
                return
            if self.hear:
                text = self.hear(sound)
            else:
                from jcc import speech
                text = speech.hear(self.cfg, sound, names=False)["text"]   # your words only; no names are suggested to Whisper
            text = " ".join(str(text or "").split())
            if not text:
                self.notify("Nothing was heard. Press the shortcut and speak again.")
                return
            if not keys_released():
                self.notify("Let go of the keys, then try again.")
                return
            desktop = self.desktop
            if desktop is None:
                from jcc.computer import Desktop
                desktop = Desktop()
            desktop.perform({"action": "type", "text": text + " "})
        except ValueError as problem:
            self.notify(str(problem))
        except OSError:
            self.notify("Dictation could not reach the speech service. Check your internet connection.")


def _beep(pitch: int) -> None:
    try:
        import winsound
        winsound.Beep(pitch, 70)
    except (ImportError, RuntimeError):
        pass
