"""Which microphone and which speakers JARVIS uses.

Windows' own default device is the default. A device chosen under Voice and assistant is remembered by its
name, because the window (a browser) and the tray helper (Windows itself) know the same device under
different numbers but the same name. If the chosen device is not connected, the Windows default is used.
"""
from __future__ import annotations

import ctypes
import math
import os
import re
import struct
import threading
import time
from ctypes import wintypes

RATE = 16000
DEFAULT = 0xFFFFFFFF          # Windows' own choice ("wave mapper")
NAME_LENGTH = 31              # Windows cuts device names to this many characters here


class _Format(ctypes.Structure):
    _fields_ = [("tag", wintypes.WORD), ("channels", wintypes.WORD), ("rate", wintypes.DWORD), ("bytes_per_second", wintypes.DWORD),
                ("block", wintypes.WORD), ("bits", wintypes.WORD), ("extra", wintypes.WORD)]


class _Header(ctypes.Structure):
    _fields_ = [("data", ctypes.c_void_p), ("length", wintypes.DWORD), ("recorded", wintypes.DWORD), ("user", ctypes.c_size_t),
                ("flags", wintypes.DWORD), ("loops", wintypes.DWORD), ("next", ctypes.c_void_p), ("reserved", ctypes.c_size_t)]


class _InCaps(ctypes.Structure):
    _fields_ = [("mid", wintypes.WORD), ("pid", wintypes.WORD), ("version", wintypes.UINT), ("name", wintypes.WCHAR * 32),
                ("formats", wintypes.DWORD), ("channels", wintypes.WORD), ("reserved", wintypes.WORD)]


class _OutCaps(ctypes.Structure):
    _fields_ = [("mid", wintypes.WORD), ("pid", wintypes.WORD), ("version", wintypes.UINT), ("name", wintypes.WCHAR * 32),
                ("formats", wintypes.DWORD), ("channels", wintypes.WORD), ("reserved", wintypes.WORD), ("support", wintypes.DWORD)]


def plain(label) -> str:
    """A device's name without what browsers put around it ("Default - " in front, the USB numbers behind)."""
    text = re.sub(r"[\x00-\x1f\x7f]", " ", str(label or ""))
    text = re.sub(r"^\s*(default|communications)\s*-\s*", "", text, flags=re.I)
    text = re.sub(r"\s*\([0-9a-f]{4}:[0-9a-f]{4}\)\s*$", "", text, flags=re.I)
    return " ".join(text.split())[:120]


def _names(count, caps_of, kind) -> list[str]:
    if os.name != "nt":
        return []
    winmm, found = ctypes.windll.winmm, []
    caps_of = getattr(winmm, caps_of)
    caps_of.argtypes = [ctypes.c_size_t, ctypes.c_void_p, wintypes.UINT]
    for index in range(min(64, getattr(winmm, count)())):
        caps = kind()
        found.append(str(caps.name) if not caps_of(index, ctypes.byref(caps), ctypes.sizeof(caps)) else "")
    return found


def inputs() -> list[str]:
    """Windows' names for the microphones, in Windows' own order (the position in the list is the device's number)."""
    return _names("waveInGetNumDevs", "waveInGetDevCapsW", _InCaps)


def outputs() -> list[str]:
    return _names("waveOutGetNumDevs", "waveOutGetDevCapsW", _OutCaps)


def find(label, names: list[str]) -> int | None:
    """Windows' number for the device with this name. None means: use the Windows default (nothing chosen, or not connected)."""
    wanted = plain(label).lower()
    if not wanted:
        return None
    for index, name in enumerate(names):
        short = " ".join(str(name).split()).lower()
        if short and (short == wanted or (len(short) >= NAME_LENGTH - 1 and wanted.startswith(short))):
            return index
    return None


def chosen_input(cfg) -> int | None:
    from jcc import speech
    try:
        return find(speech.settings(cfg)["mic"], inputs())
    except Exception:  # noqa: BLE001 - whatever goes wrong here, the Windows default still works
        return None


def chosen_output(cfg) -> int | None:
    from jcc import speech
    try:
        return find(speech.settings(cfg)["speaker"], outputs())
    except Exception:  # noqa: BLE001
        return None


class Microphone:
    """One microphone, recorded as 16 kHz 16-bit mono sound and handed on in pieces as it arrives.

    `device` is Windows' number for it; None is the Windows default. A chosen device that cannot be opened
    (unplugged a moment ago, or held by another program) falls back to the Windows default."""

    def __init__(self, device: int | None = None, piece: int = 3200):
        self.device, self.piece = device, piece
        self.running, self.thread, self.used_default = False, None, device is None

    def start(self, each, limit: float | None = None) -> None:
        if os.name != "nt":
            raise ValueError("The microphone can be recorded on Windows only.")
        winmm, handle = ctypes.windll.winmm, wintypes.HANDLE()
        wanted = _Format(1, 1, RATE, RATE * 2, 2, 16, 0)
        opened = self.device is not None and not winmm.waveInOpen(ctypes.byref(handle), ctypes.c_uint(self.device), ctypes.byref(wanted), 0, 0, 0)
        if not opened:
            self.used_default = True
            if winmm.waveInOpen(ctypes.byref(handle), ctypes.c_uint(DEFAULT), ctypes.byref(wanted), 0, 0, 0):
                raise ValueError("The microphone could not be opened. Check that one is connected and that apps may use it (Windows Settings, Privacy, Microphone).")
        self.running = True
        buffers = [ctypes.create_string_buffer(self.piece) for _ in range(6)]
        headers = [_Header(ctypes.addressof(buffer), self.piece, 0, 0, 0, 0, None, 0) for buffer in buffers]
        for header in headers:
            winmm.waveInPrepareHeader(handle, ctypes.byref(header), ctypes.sizeof(header))
            winmm.waveInAddBuffer(handle, ctypes.byref(header), ctypes.sizeof(header))
        winmm.waveInStart(handle)

        def collect():
            started = time.time()
            try:
                while self.running:
                    for header in headers:
                        if header.flags & 1 and self.running:           # this piece is full
                            piece = ctypes.string_at(header.data, header.recorded)
                            header.flags &= ~1
                            winmm.waveInAddBuffer(handle, ctypes.byref(header), ctypes.sizeof(header))
                            each(piece)
                    if limit and time.time() - started > limit:
                        break
                    time.sleep(0.02 if self.piece >= 3200 else 0.01)
            except Exception:  # noqa: BLE001 - whoever is listening has gone away
                pass
            self.running = False
            winmm.waveInReset(handle)
            for header in headers:
                if header.flags & 1 and header.recorded:
                    try:
                        each(ctypes.string_at(header.data, header.recorded))
                    except Exception:  # noqa: BLE001
                        pass
                winmm.waveInUnprepareHeader(handle, ctypes.byref(header), ctypes.sizeof(header))
            winmm.waveInClose(handle)
            self._keep = buffers   # keep the memory alive until the device has let go of it
        self.thread = threading.Thread(target=collect, daemon=True, name="microphone")
        self.thread.start()

    def alive(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def stop(self) -> None:
        self.running = False
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=3)


def tone(pitch: int, milliseconds: int = 70, device: int | None = None, volume: float = 0.25) -> bool:
    """A short soft tone on one particular set of speakers (or the Windows default). False if it could not be played."""
    if os.name != "nt":
        return False
    rate, count = 22050, int(22050 * milliseconds / 1000)
    fade = max(1, rate // 200)
    samples = [int(32767 * volume * math.sin(2 * math.pi * pitch * i / rate) * min(1.0, i / fade, (count - i) / fade)) for i in range(count)]
    data = struct.pack(f"<{count}h", *samples)
    winmm, handle = ctypes.windll.winmm, wintypes.HANDLE()
    wanted = _Format(1, 1, rate, rate * 2, 2, 16, 0)
    if winmm.waveOutOpen(ctypes.byref(handle), ctypes.c_uint(DEFAULT if device is None else device), ctypes.byref(wanted), 0, 0, 0):
        return False
    buffer = ctypes.create_string_buffer(data, len(data))
    header = _Header(ctypes.addressof(buffer), len(data), 0, 0, 0, 0, None, 0)
    try:
        if winmm.waveOutPrepareHeader(handle, ctypes.byref(header), ctypes.sizeof(header)) or winmm.waveOutWrite(handle, ctypes.byref(header), ctypes.sizeof(header)):
            return False
        deadline = time.time() + milliseconds / 1000 + 1.5
        while not header.flags & 1 and time.time() < deadline:      # until Windows says it has been played
            time.sleep(0.01)
        return True
    finally:
        winmm.waveOutReset(handle)
        winmm.waveOutUnprepareHeader(handle, ctypes.byref(header), ctypes.sizeof(header))
        winmm.waveOutClose(handle)


def beep(cfg, pitch: int) -> None:
    """The small sound the tray helper makes when it starts or stops listening, on the chosen speakers."""
    try:
        device = chosen_output(cfg)
        if device is not None and tone(pitch, 70, device):
            return
        import winsound
        winsound.Beep(pitch, 70)
    except Exception:  # noqa: BLE001 - a missing beep must never stop the listening
        pass
