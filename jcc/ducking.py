"""Other sounds made quieter while you talk to JARVIS, and put back as soon as it thinks, works or speaks.

Windows gives every program its own volume, so there only the other programs are made quieter: JARVIS's own window
(and its voice) and the JARVIS service are left as they are. A Mac has no volume per program, so there the computer's
output is made quieter, and only while JARVIS is listening: it is silent then itself.

What was changed is written down first (state/ducked.json), so a volume is always put back: when listening ends,
when nothing has said it is still listening for a while (a window that closed), and at the next start after a crash.
A volume its owner changed meanwhile is left as they set it.
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

LEVEL = 0.2              # other sounds at a fifth of their volume while JARVIS listens
STALE = 20.0             # seconds: listening that nobody has confirmed for this long is over
_IID_SESSIONS = "{77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F}"     # IAudioSessionManager2
_IID_CONTROL2 = "{BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D}"     # IAudioSessionControl2
_IID_SIMPLE = "{87CE5498-68D6-44E5-9215-6DA47EF883D8}"       # ISimpleAudioVolume


class Ducker:
    """`update(listening)` is called whenever a window says what its voice chat is doing."""

    def __init__(self, state_dir: Path, backend=None, level: float = LEVEL, stale: float = STALE, own=None):
        self.file = Path(state_dir) / "ducked.json"
        self.backend = backend or default_backend(own)
        self.level, self.stale = level, stale
        self.lock = threading.Lock()
        self.down = False
        self.seen = 0.0
        self.saved: dict = {}
        self.watch = None

    # The owner's choice (Settings, Voice) is checked by the caller; this only lowers and restores.
    def update(self, listening: bool) -> None:
        with self.lock:
            if listening:
                self.seen = time.time()
                if self.down or not self.backend:
                    return
                self.down = True
            elif not self.down:
                return
            else:
                self.down = False
        threading.Thread(target=self._apply, args=(listening,), name="ducking", daemon=True).start()
        if listening:
            self._watch()

    def _apply(self, listening: bool) -> None:
        with self.lock:                         # (one change at a time, in the order they were asked for)
            try:
                if listening:
                    self.saved = self.backend.lower(self.level) or {}
                    self._write()
                else:
                    self._restore_saved()
            except Exception:  # noqa: BLE001 - sound that cannot be changed is not a reason to stop listening
                pass

    def _restore_saved(self) -> None:
        if self.saved:
            try:
                self.backend.restore(self.saved, self.level)
            finally:
                self.saved = {}
                self._write()

    def _watch(self) -> None:
        if self.watch and self.watch.is_alive():
            return

        def run():
            while True:
                time.sleep(min(5.0, self.stale / 2))
                with self.lock:
                    if not self.down:
                        return
                    stale = time.time() - self.seen > self.stale
                if stale:                         # a window that closed while listening: the sound comes back
                    self.update(False)
                    return
        self.watch = threading.Thread(target=run, name="ducking-watch", daemon=True)
        self.watch.start()

    def _write(self) -> None:
        try:
            if self.saved:
                self.file.parent.mkdir(parents=True, exist_ok=True)
                self.file.write_text(json.dumps({"level": self.level, "saved": self.saved, "at": time.time()}), "utf-8")
            else:
                self.file.unlink(missing_ok=True)
        except OSError:
            pass

    def recover(self) -> None:
        """At start: a volume that a crash left lowered is put back."""
        try:
            data = json.loads(self.file.read_text("utf-8"))
        except (OSError, ValueError):
            return
        with self.lock:
            self.saved = data.get("saved") or {}
            try:
                if self.backend:
                    self._restore_saved()
            except Exception:  # noqa: BLE001
                pass


def default_backend(own=None):
    if os.environ.get("JCC_NO_DUCKING"):          # (the tests never change the PC's real sound)
        return None
    if os.name == "nt":
        return WindowsSessions(own)
    if sys.platform == "darwin":
        return MacOutput()
    return None


class MacOutput:
    """The Mac's output volume (0-100). JARVIS is silent while it listens, so lowering the output lowers only the rest."""

    @staticmethod
    def _run(script: str) -> str:
        done = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5)
        return done.stdout.strip()

    def lower(self, level: float) -> dict:
        now = int(self._run("output volume of (get volume settings)") or 0)
        if now <= 0:
            return {}
        self._run(f"set volume output volume {max(1, round(now * level))}")
        return {"output": now}

    def restore(self, saved: dict, level: float) -> None:
        was = int(saved.get("output") or 0)
        if not was:
            return
        now = int(self._run("output volume of (get volume settings)") or 0)
        if abs(now - max(1, round(was * level))) <= 2:      # (unless its owner changed it meanwhile)
            self._run(f"set volume output volume {was}")


class WindowsSessions:
    """Every program playing sound on the default output has a volume of its own (an audio session). The other programs'
    are lowered; JARVIS's own (its window, the service) are left alone."""

    def __init__(self, own=None):
        self.own = own or jarvis_processes

    def lower(self, level: float) -> dict:
        mine, saved = self.own(), {}

        def visit(ident, pid, volume, now):
            if pid in mine or pid == 0 or now <= 0:
                return
            self._set(volume, now * level)
            saved[ident] = now
        self._walk(visit)
        return saved

    def restore(self, saved: dict, level: float) -> None:
        def visit(ident, pid, volume, now):
            was = saved.get(ident)
            if was is not None and abs(now - was * level) < 0.02:      # (unless its owner changed it meanwhile)
                self._set(volume, was)
        self._walk(visit)

    @staticmethod
    def _set(volume, value: float) -> None:
        from jcc.winctl import _method
        _method(volume, 3, ctypes.c_float, ctypes.c_void_p)(volume, ctypes.c_float(max(0.0, min(1.0, value))), None)

    @staticmethod
    def _walk(visit) -> None:
        """visit(its identity, its program's id, its volume control, its volume now) for each sound session on the
        default output. Every control is released when the walk is over."""
        from jcc.winctl import _ENUMERATOR, _IID_ENUMERATOR, _guid, _method
        ole32 = ctypes.windll.ole32
        ole32.CoInitializeEx(None, 0)
        ole32.CoCreateInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        ole32.CoCreateInstance.restype = ctypes.c_long
        held = []
        try:
            enumerator = ctypes.c_void_p()
            if ole32.CoCreateInstance(ctypes.byref(_guid(_ENUMERATOR)), None, 23, ctypes.byref(_guid(_IID_ENUMERATOR)), ctypes.byref(enumerator)) or not enumerator:
                return
            held.append(enumerator)
            device = ctypes.c_void_p()
            if _method(enumerator, 4, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(enumerator, 0, 0, ctypes.byref(device)) or not device:
                return
            held.append(device)
            manager = ctypes.c_void_p()
            if _method(device, 3, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(
                    device, ctypes.byref(_guid(_IID_SESSIONS)), 23, None, ctypes.byref(manager)) or not manager:
                return
            held.append(manager)
            sessions = ctypes.c_void_p()
            if _method(manager, 5, ctypes.POINTER(ctypes.c_void_p))(manager, ctypes.byref(sessions)) or not sessions:
                return
            held.append(sessions)
            count = ctypes.c_int()
            _method(sessions, 3, ctypes.POINTER(ctypes.c_int))(sessions, ctypes.byref(count))
            for index in range(min(count.value, 64)):
                control = ctypes.c_void_p()
                if _method(sessions, 4, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(sessions, index, ctypes.byref(control)) or not control:
                    continue
                held.append(control)
                second, volume = ctypes.c_void_p(), ctypes.c_void_p()
                if _method(control, 0, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(control, ctypes.byref(_guid(_IID_CONTROL2)), ctypes.byref(second)) or not second:
                    continue
                held.append(second)
                if _method(control, 0, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(control, ctypes.byref(_guid(_IID_SIMPLE)), ctypes.byref(volume)) or not volume:
                    continue
                held.append(volume)
                pid, name, now = ctypes.c_ulong(), ctypes.c_void_p(), ctypes.c_float()
                _method(second, 14, ctypes.POINTER(ctypes.c_ulong))(second, ctypes.byref(pid))
                _method(volume, 4, ctypes.POINTER(ctypes.c_float))(volume, ctypes.byref(now))
                ident = ""
                if not _method(second, 13, ctypes.POINTER(ctypes.c_void_p))(second, ctypes.byref(name)) and name.value:
                    ident = ctypes.wstring_at(name.value)
                    ole32.CoTaskMemFree(name)
                visit(ident or f"pid:{pid.value}:{index}", pid.value, volume, now.value)
        finally:
            for pointer in reversed(held):
                try:
                    _method(pointer, 2)(pointer)
                except OSError:
                    pass


def jarvis_processes() -> set[int]:
    """The ids of JARVIS's own processes: this service, and every process of JARVIS's own browser windows (they run
    with a browser profile of JARVIS's own, so their command lines name it), with all their children."""
    mine = {os.getpid()}
    if os.name != "nt":
        return mine
    script = ("Get-CimInstance Win32_Process -Filter \"Name='msedge.exe' or Name='chrome.exe' or Name='python.exe' or Name='pythonw.exe'\" | "
              "ForEach-Object { '{0}|{1}|{2}' -f $_.ProcessId, $_.ParentProcessId, $_.CommandLine }")
    try:
        from jcc import system
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True,
                             timeout=10, creationflags=system.no_window()).stdout
    except (OSError, subprocess.SubprocessError):
        return mine
    rows = []
    for line in out.splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3 and parts[0].isdigit():
            rows.append((int(parts[0]), int(parts[1] or 0), parts[2].lower()))
    roots = {pid for pid, _, command in rows if "window-profile" in command or "jcc" in command and ("python" in command)}
    mine |= roots
    changed = True
    while changed:                               # and their children, and theirs
        changed = False
        for pid, parent, _ in rows:
            if parent in mine and pid not in mine:
                mine.add(pid)
                changed = True
    return mine
