"""Sound on a Mac: the microphone, a short tone, and how loud the Mac's own sound is.

The microphone is recorded through macOS's own Audio Queue (AudioToolbox, called through ctypes): 16 kHz, 16-bit, one
channel, handed on in pieces as it arrives, exactly as jcc/sound.py does on Windows. It is the microphone chosen in
System Settings, Sound, Input. macOS asks once whether JARVIS (or Terminal, if it was started from there) may use the
microphone.

How loud the Mac's own sound is cannot be asked of macOS in one call as it can of Windows. A small helper program
(installer/mac/sound_level.swift, built when JARVIS is installed) listens to what the Mac plays through ScreenCaptureKit
and prints only its loudness, fifty numbers a second. Nothing it hears is kept or sent anywhere. It needs macOS 13 and
the Screen Recording permission; without either, sound is simply treated as coming from the room, as it is on a PC with
no speakers.

Nothing is loaded until it is used, so this file can be imported on any system.
"""
from __future__ import annotations

import ctypes
import math
import os
import queue
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path

RATE = 16000
HELPER = "jarvis-sound-level"
NO_MICROPHONE = ("The microphone could not be opened. Check that one is connected and that JARVIS may use it "
                 "(System Settings, Privacy & Security, Microphone).")


class _Format(ctypes.Structure):          # AudioStreamBasicDescription
    _fields_ = [("rate", ctypes.c_double), ("format", ctypes.c_uint32), ("flags", ctypes.c_uint32), ("packet_bytes", ctypes.c_uint32),
                ("packet_frames", ctypes.c_uint32), ("frame_bytes", ctypes.c_uint32), ("channels", ctypes.c_uint32), ("bits", ctypes.c_uint32),
                ("reserved", ctypes.c_uint32)]


class _Buffer(ctypes.Structure):          # AudioQueueBuffer
    _fields_ = [("capacity", ctypes.c_uint32), ("data", ctypes.c_void_p), ("size", ctypes.c_uint32), ("user", ctypes.c_void_p),
                ("description_capacity", ctypes.c_uint32), ("descriptions", ctypes.c_void_p), ("description_count", ctypes.c_uint32)]


_CALLBACK = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(_Buffer), ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p)
_toolbox = None


def _audio():
    """macOS's AudioToolbox, with the few functions used here declared."""
    global _toolbox
    if _toolbox is None:
        box = ctypes.CDLL("/System/Library/Frameworks/AudioToolbox.framework/AudioToolbox")
        v, u32, status = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int32
        box.AudioQueueNewInput.restype, box.AudioQueueNewInput.argtypes = status, [ctypes.POINTER(_Format), _CALLBACK, v, v, v, u32, ctypes.POINTER(v)]
        box.AudioQueueAllocateBuffer.restype, box.AudioQueueAllocateBuffer.argtypes = status, [v, u32, ctypes.POINTER(ctypes.POINTER(_Buffer))]
        box.AudioQueueEnqueueBuffer.restype, box.AudioQueueEnqueueBuffer.argtypes = status, [v, ctypes.POINTER(_Buffer), u32, v]
        box.AudioQueueStart.restype, box.AudioQueueStart.argtypes = status, [v, v]
        box.AudioQueueStop.restype, box.AudioQueueStop.argtypes = status, [v, ctypes.c_ubyte]
        box.AudioQueueDispose.restype, box.AudioQueueDispose.argtypes = status, [v, ctypes.c_ubyte]
        _toolbox = box
    return _toolbox


class Microphone:
    """The Mac's microphone, recorded as 16 kHz 16-bit mono sound and handed on in pieces as it arrives: the same calls
    as Microphone in jcc/sound.py. `device` is not used: it is the microphone chosen in System Settings."""

    def __init__(self, device: int | None = None, piece: int = 3200, audio=None):
        self.device, self.piece, self._audio = None, int(piece), audio
        self.running, self.thread, self.used_default = False, None, True

    def start(self, each, limit: float | None = None) -> None:
        try:
            box = self._audio or _audio()
        except OSError:
            raise ValueError("The microphone can be recorded on Windows and on a Mac only.") from None
        pieces: queue.Queue = queue.Queue()
        line = ctypes.c_void_p()

        def arrived(_user, source, buffer, _when, _count, _descriptions):
            # (Called by macOS on a thread of its own: only take the sound and hand the buffer back.)
            try:
                if buffer.contents.size:
                    pieces.put(ctypes.string_at(buffer.contents.data, buffer.contents.size))
                if self.running:
                    box.AudioQueueEnqueueBuffer(source, buffer, 0, None)
            except Exception:  # noqa: BLE001 - nothing may escape into macOS's own thread
                pass
        callback = _CALLBACK(arrived)
        wanted = _Format(float(RATE), 0x6C70636D, 0x4 | 0x8, 2, 1, 2, 1, 16, 0)       # 'lpcm', signed whole numbers, packed
        if box.AudioQueueNewInput(ctypes.byref(wanted), callback, None, None, None, 0, ctypes.byref(line)) or not line:
            raise ValueError(NO_MICROPHONE)
        self.running = True
        for _ in range(6):
            buffer = ctypes.POINTER(_Buffer)()
            if box.AudioQueueAllocateBuffer(line, self.piece, ctypes.byref(buffer)) or box.AudioQueueEnqueueBuffer(line, buffer, 0, None):
                self.running = False
                box.AudioQueueDispose(line, 1)
                raise ValueError(NO_MICROPHONE)
        if box.AudioQueueStart(line, None):
            self.running = False
            box.AudioQueueDispose(line, 1)
            raise ValueError(NO_MICROPHONE)

        def collect():
            started = time.time()
            try:
                while self.running:
                    try:
                        each(pieces.get(timeout=0.05))
                    except queue.Empty:
                        pass
                    if limit and time.time() - started > limit:
                        break
            except Exception:  # noqa: BLE001 - whoever is listening has gone away
                pass
            self.running = False
            box.AudioQueueStop(line, 1)
            while True:                                   # what had already arrived is not lost
                try:
                    each(pieces.get_nowait())
                except queue.Empty:
                    break
                except Exception:  # noqa: BLE001
                    break
            box.AudioQueueDispose(line, 1)
            self._keep = callback                         # (alive until macOS has let go of it)
        self._keep = callback
        self.thread = threading.Thread(target=collect, daemon=True, name="microphone")
        self.thread.start()

    def alive(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def stop(self) -> None:
        self.running = False
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=3)


def tone(pitch: int, milliseconds: int = 70, volume: float = 0.25, run=None) -> bool:
    """A short soft tone on the Mac's speakers (its own afplay plays a small file made here). False if it could not be played."""
    rate, count = 22050, int(22050 * milliseconds / 1000)
    fade = max(1, rate // 200)
    samples = [int(32767 * volume * math.sin(2 * math.pi * pitch * i / rate) * min(1.0, i / fade, (count - i) / fade)) for i in range(count)]
    folder = Path(tempfile.mkdtemp(prefix="jarvis-tone-"))
    try:
        path = folder / "tone.wav"
        with wave.open(str(path), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(rate)
            out.writeframes(struct.pack(f"<{count}h", *samples))
        done = (run or subprocess.run)(["afplay", str(path)], capture_output=True, timeout=5, stdin=subprocess.DEVNULL)
        return done.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def helper() -> str | None:
    """The program that measures the Mac's own sound, where it is installed; None when it is not."""
    from jcc.config import ROOT
    named = os.environ.get("JCC_SOUND_LEVEL_HELPER")
    for place in ([Path(named)] if named else []) + [ROOT / "bin" / HELPER]:
        if place.is_file() and os.access(place, os.X_OK):
            return str(place)
    return None


class OutputMeter:
    """How loud the Mac's own sound is right now, 0 to 1: the same calls as OutputMeter in jcc/winctl.py. The helper
    program does the listening; this reads the numbers it prints."""

    reopen = False                       # (jcc/pcsound.py need not open it again every few seconds: it follows the Mac's speakers itself)

    def __init__(self, program: str | None = None, start=None):
        self.program, self.start = program, start or subprocess.Popen
        self.proc, self.loudest, self.ready, self.lock = None, 0.0, threading.Event(), threading.Lock()

    def open(self) -> None:
        program = self.program or helper()
        if not program:
            raise OSError("The helper that measures the Mac's own sound is not installed.")
        self.ready.clear()
        self.proc = self.start([program], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        threading.Thread(target=self._read, args=(self.proc,), daemon=True, name="mac-sound-level").start()
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline and not self.ready.is_set() and self.proc.poll() is None:
            time.sleep(0.02)
        if not self.ready.is_set():
            self.close()
            raise OSError("The Mac's own sound could not be measured (macOS 13 and the Screen Recording permission are needed).")

    def _read(self, proc) -> None:
        try:
            for line in proc.stdout:
                line = line.strip()
                if line == "ready":
                    self.ready.set()
                    continue
                try:
                    level = float(line)
                except ValueError:
                    continue
                with self.lock:
                    self.loudest = max(self.loudest, level)
        except (OSError, ValueError):
            pass
        finally:
            try:
                proc.stdout.close()
            except (OSError, ValueError):
                pass

    def peak(self) -> float:
        """The loudest moment since this was last asked."""
        if not self.proc or self.proc.poll() is not None:
            raise OSError("The helper that measures the Mac's own sound has stopped.")
        with self.lock:
            level, self.loudest = self.loudest, 0.0
        return max(0.0, min(1.0, level))

    def close(self) -> None:
        proc, self.proc = self.proc, None
        if not proc:
            return
        try:
            if proc.stdin:
                proc.stdin.close()                       # the helper stops by itself when nobody is listening to it any more
            proc.terminate()
        except OSError:
            pass
