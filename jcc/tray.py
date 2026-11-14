"""Tray icon and keyboard shortcuts for JARVIS. Runs as a small background helper.

Windows:
- Tray icon: left-click opens JARVIS; right-click shows a short menu.
- Ctrl+Alt+J from anywhere opens JARVIS.
- Ctrl+Alt+Space from anywhere starts talking to JARVIS (the window does not need to be in front).
- Ctrl+Alt+D from anywhere dictates: speak, and the words are typed where your cursor is.
- Ctrl+Alt+Backspace is the emergency stop for computer control.

A Mac: the same menu on an icon in the menu bar, and the same shortcuts with Control+Option (J, T, D, Delete). A small
program shows the icon and hears the shortcuts (installer/mac/menu_bar.swift); this helper does what they ask for.
On both, the helper also listens for "Hey JARVIS".
Standard library only. Start with:  pythonw -m jcc.tray   (python3 -m jcc.tray on a Mac)
"""
from __future__ import annotations

import ctypes
import os
import struct
import subprocess
import sys
import threading
from ctypes import wintypes
from pathlib import Path

from jcc.config import ROOT, load
from jcc.lock import InstanceLock

WM_DESTROY, WM_COMMAND, WM_HOTKEY, WM_APP_TRAY = 0x0002, 0x0111, 0x0312, 0x8001
WM_LBUTTONUP, WM_RBUTTONUP = 0x0202, 0x0205
OPEN, STOP_COMPUTER, QUIT, TALK, DICTATE = 1, 2, 3, 4, 5
HOTKEY_OPEN, HOTKEY_STOP, HOTKEY_TALK, HOTKEY_DICTATE = 1, 2, 3, 4
PORT = 8765
# Each shortcut with its choices, best first. Another program may already own one; then the next is tried.
CHOICES = {HOTKEY_OPEN: [("Ctrl+Alt+J", ord("J"))], HOTKEY_STOP: [("Ctrl+Alt+Backspace", 0x08)],
           HOTKEY_TALK: [("Ctrl+Alt+Space", 0x20), ("Ctrl+Alt+T", ord("T")), ("Ctrl+Alt+K", ord("K"))],
           HOTKEY_DICTATE: [("Ctrl+Alt+D", ord("D")), ("Ctrl+Alt+Y", ord("Y")), ("Ctrl+Alt+U", ord("U"))]}
NAMES = {HOTKEY_OPEN: "open", HOTKEY_STOP: "stop", HOTKEY_TALK: "talk", HOTKEY_DICTATE: "dictate"}


def claim(register) -> dict:
    """Register each shortcut with the first of its choices that is free. Returns {id: label} for those that worked."""
    active = {}
    for ident, choices in CHOICES.items():
        for label, key in choices:
            if register(ident, key):
                active[ident] = label
                break
    return active
TITLE = "JARVIS · Workspace"


def icon_bytes(size: int = 32) -> bytes:
    """A small round icon in JARVIS colours, built in memory (no image files needed). See jcc/icon.py."""
    from jcc import icon
    return icon.ico(size)


def hotkeys(cfg) -> dict:
    desktop = cfg.raw.get("desktop", {}) if isinstance(cfg.raw.get("desktop"), dict) else {}
    return {"tray": desktop.get("tray", True) is not False, "hotkey": desktop.get("hotkey", True) is not False}


def ask_service(cfg, action: str, text: str = "") -> dict | None:
    """Tell the running JARVIS service something from the tray. None if it is not running."""
    import json
    import urllib.request
    try:
        key = (cfg.state_dir / "tray-key").read_text("utf-8").strip()
        request = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/tray", data=json.dumps({"action": action, "text": text}).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "X-JCC-Tray": key, "Host": f"127.0.0.1:{PORT}"})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=4) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except (OSError, ValueError):
        return None


def talk(cfg) -> None:
    """Start a voice chat. Uses the open window if there is one; otherwise opens JARVIS already listening."""
    answer = ask_service(cfg, "listen")
    if not (answer and answer.get("window")):
        start_window()


def start_window(listen: bool = True) -> None:
    from jcc import system
    subprocess.Popen([system.background_python(), "-m", "jcc.desktop", *(["--listen"] if listen else [])], cwd=ROOT,
                     env={**os.environ, "PYTHONPATH": str(ROOT)}, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=system.no_window(), **system.own_group())


def nudge(cfg) -> None:
    """"Hey JARVIS" and then nothing: JARVIS asks what is wanted and listens, opening its window if it is closed."""
    answer = ask_service(cfg, "nudge")
    if not (answer and answer.get("window")):
        start_window()


def attend(cfg) -> None:
    """"Hey JARVIS" on its own: have the window show that it is listening, opening it if it is closed."""
    answer = ask_service(cfg, "attend")
    if not (answer and answer.get("window")):
        start_window()


def say(cfg, text: str) -> None:
    """Hand JARVIS something that was said after the wake word. Opens the window if there is none; the request waits for it."""
    import time
    answer = ask_service(cfg, "say", text)
    if answer is None:                       # the service itself is not running yet
        start_window()
        for _ in range(40):
            time.sleep(0.5)
            answer = ask_service(cfg, "say", text)
            if answer is not None:
                return
    elif answer.get("window") is False:
        start_window()
        threading.Thread(target=_make_sure, args=(cfg,), daemon=True, name="wake-follow-through").start()


def _make_sure(cfg, notify=None, seconds: float = 20.0) -> bool:
    """A window was opened for something that was said. If it has not picked it up after a while, say so, so that nobody
    is left waiting in silence. Returns whether it was picked up."""
    import time
    deadline = time.time() + seconds
    while time.time() < deadline:
        time.sleep(1.0)
        answer = ask_service(cfg, "status")
        if answer is not None and not answer.get("waiting"):
            return True
    (notify or _say_so)("JARVIS heard you, but its window did not pick that up. Please say it again.")
    return False


def _say_so(text: str) -> None:
    try:
        from jcc.assistant import notify_native
        notify_native(text)
    except Exception:  # noqa: BLE001 - a missing notice must not break the tray helper
        pass


def open_jarvis() -> None:
    if os.name != "nt":
        # A Mac: bring JARVIS's own window to the front if it is open and macOS lets it be; otherwise open one.
        try:
            from jcc import winctl
            from jcc.policy import MAIN_WINDOW
            row = next((r for r in winctl.windows() if MAIN_WINDOW.search(r["title"])), None)
            if row and winctl.focus(row["handle"]):
                return
        except Exception:  # noqa: BLE001 - whatever macOS would not say, opening a window still works
            pass
        start_window(listen=False)
        return
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(handle, _):
        buffer = ctypes.create_unicode_buffer(200)
        user32.GetWindowTextW(handle, buffer, 200)
        if buffer.value.startswith("JARVIS") and "Workspace" in buffer.value and user32.IsWindowVisible(handle):
            found.append(handle)
        return True

    user32.EnumWindows(visit, 0)
    if found:
        user32.ShowWindow(found[0], 9)  # restore if minimised
        user32.SetForegroundWindow(found[0])
        return
    python = Path(sys.executable).with_name("pythonw.exe")
    subprocess.Popen([str(python if python.exists() else sys.executable), "-m", "jcc.desktop"], cwd=ROOT,
                     env={**os.environ, "PYTHONPATH": str(ROOT)}, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)


class MacMenu:
    """The icon in the Mac's menu bar and the shortcuts that work from any app. A small program shows them
    (installer/mac/menu_bar.swift, built when JARVIS is installed) and says on a line which one was used; this starts
    it, reads those lines and does the thing. Without that program there is simply no icon and no shortcut."""

    NAME = "jarvis-menu"

    def __init__(self, actions: dict, icon: bool = True, keys: bool = True, program: str | None = None, start=None):
        self.actions, self.want_icon, self.want_keys = actions, icon, keys
        self.program, self.start = program, start or subprocess.Popen
        self.proc, self.icon, self.keys, self.ready = None, False, {}, threading.Event()

    @classmethod
    def where(cls) -> str | None:
        named = os.environ.get("JCC_MENU_HELPER")
        for place in ([Path(named)] if named else []) + [ROOT / "bin" / cls.NAME]:
            if place.is_file() and os.access(place, os.X_OK):
                return str(place)
        return None

    def open(self) -> bool:
        """Show the icon and claim the shortcuts. True once the program has said what it could set up."""
        program = self.program or self.where()
        if not program or not (self.want_icon or self.want_keys):
            return False
        argv = [program] + ([] if self.want_icon else ["--no-icon"]) + ([] if self.want_keys else ["--no-keys"])
        try:
            self.proc = self.start(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        except OSError:
            return False
        threading.Thread(target=self._read, args=(self.proc,), daemon=True, name="mac-menu").start()
        self.ready.wait(8.0)
        return self.ready.is_set()

    def _read(self, proc) -> None:
        import json
        try:
            for line in proc.stdout:
                line = line.strip()
                if line.startswith("{"):
                    try:
                        told = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(told, dict):
                        self.icon = told.get("icon") is True
                        self.keys = {str(name): str(label)[:40] for name, label in (told.get("keys") or {}).items() if str(name) in NAMES.values()}
                        self.ready.set()
                    continue
                action = self.actions.get(line)
                if action:                               # (each on a thread of its own: a slow one must not hold up the next)
                    threading.Thread(target=self._do, args=(action,), daemon=True, name="mac-menu-" + line).start()
        except (OSError, ValueError):
            pass
        finally:
            try:
                proc.stdout.close()
            except (OSError, ValueError):
                pass

    @staticmethod
    def _do(action) -> None:
        try:
            action()
        except Exception:  # noqa: BLE001 - one thing that failed must not end the menu
            pass

    def running(self) -> bool:
        return bool(self.proc) and self.proc.poll() is None

    def dictating(self, on: bool) -> None:
        """Tell the menu whether dictation is listening, so it offers "Finish dictating"."""
        try:
            if self.running():
                self.proc.stdin.write("dictating 1\n" if on else "dictating 0\n")
                self.proc.stdin.flush()
        except (OSError, ValueError):
            pass

    def close(self) -> None:
        proc, self.proc = self.proc, None
        if not proc:
            return
        try:
            if proc.stdin:
                proc.stdin.close()                       # the program stops by itself when nobody is listening to it any more
            proc.terminate()
        except OSError:
            pass


def listen_only(cfg, once: bool = False, pause: float = 4.0, make_ears=None, make_menu=None, make_dictation=None) -> int:
    """The helper on a Mac: the icon in the menu bar, the shortcuts that work from any app, dictation, and listening for
    "Hey JARVIS" (on the Mac itself, with the on-device model), handing what was said after the name to JARVIS.
    once: start, write down what it is doing, and stop (for checking). make_ears, make_menu, make_dictation: tests give
    stand-ins for the listener, the menu and dictation."""
    import json
    import signal
    import time
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    lock = InstanceLock(cfg.state_dir / "tray.lock")
    if not lock.acquire():
        return 0
    from jcc import pcsound, sound
    from jcc.wake import Ears, restore_volume
    told: set[str] = set()

    def notice(text: str) -> None:
        if text and text not in told:                  # each thing is said once, not again every time it is tried anew
            told.add(text)
            _say_so(text)

    def beep(pitch: int) -> None:
        sound.beep(cfg, pitch)

    ears = (make_ears or Ears)(cfg, lambda text: say(cfg, text), notice, beep=beep,
                               busy=lambda: (ask_service(cfg, "status") or {}).get("voice") is True, control=lambda word: ask_service(cfg, "control", word),
                               attend=lambda: attend(cfg), listen=lambda: nudge(cfg), sound=pcsound.shared,
                               name_said=lambda at: ask_service(cfg, "name", str(at)))
    if make_ears is None:
        restore_volume(cfg)
    if make_dictation is None:
        from jcc.dictate import Dictation
        make_dictation = Dictation
    dictation = make_dictation(cfg, _say_so, beep=beep)
    stop = threading.Event()
    options = hotkeys(cfg)
    menu = (make_menu or MacMenu)({"open": open_jarvis, "talk": lambda: talk(cfg), "dictate": dictation.toggle,
                                   "stop": lambda: (cfg.state_dir / "computer-stop").write_text("stop", "utf-8"), "quit": stop.set},
                                  icon=options["tray"], keys=options["hotkey"])
    menu.open()
    state: dict = {"wake": None, "seen": None, "dictating": False}
    try:
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
    except (ValueError, OSError):                      # (not the main thread: whoever started it stops it another way)
        pass
    checked = 0.0
    try:
        while not stop.is_set():
            if time.monotonic() - checked >= pause or not checked:
                checked = time.monotonic()
                try:
                    listening = ears.sync()
                except Exception:  # noqa: BLE001 - the wake word is optional; the helper must keep running
                    listening = False
                seen = (ears.problem or ears.note, ears.engine, menu.icon, tuple(sorted(menu.keys.items())))
                if listening != state["wake"] or seen != state["seen"]:
                    state["wake"], state["seen"] = listening, seen
                    (cfg.state_dir / "tray-status.json").write_text(json.dumps({
                        "tray": bool(menu.icon), **{name + "_hotkey": name in menu.keys for name in NAMES.values()}, "keys": dict(menu.keys),
                        "wake": bool(listening), "wake_problem": ears.problem or ears.note, "wake_mic": "", "wake_engine": ears.engine,
                        "at": time.time()}), "utf-8")
            if dictation.listening != state["dictating"]:
                state["dictating"] = dictation.listening
                menu.dictating(state["dictating"])
            if once:
                break
            stop.wait(0.4)
    finally:
        menu.close()
        ears.stop()
        lock.release()
    return 0


def main() -> int:
    if os.name != "nt":
        from jcc import system
        return listen_only(load(), once="--check" in sys.argv) if system.kind() == "mac" else 0
    cfg = load()
    options = hotkeys(cfg)
    if not options["tray"] and not options["hotkey"]:
        return 0
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    lock = InstanceLock(cfg.state_dir / "tray.lock")
    if not lock.acquire():
        return 0
    user32, shell32, kernel32 = ctypes.windll.user32, ctypes.windll.shell32, ctypes.windll.kernel32
    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = ctypes.c_ssize_t
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.CreatePopupMenu.restype = wintypes.HMENU
    user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
    user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.LPVOID]
    user32.DestroyMenu.argtypes = [wintypes.HMENU]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HANDLE), ("hCursor", wintypes.HANDLE),
                    ("hbrBackground", wintypes.HANDLE), ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
                    ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HANDLE), ("szTip", wintypes.WCHAR * 128),
                    ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
                    ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
                    ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", wintypes.HANDLE)]

    shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
    active: dict[int, str] = {}
    data = NOTIFYICONDATAW()
    tray_added = False

    def stop_computer() -> None:
        (cfg.state_dir / "computer-stop").write_text("stop", "utf-8")

    def balloon(text: str) -> None:
        """A short Windows notification from the tray icon."""
        if not tray_added:
            return
        data.uFlags = 0x1 | 0x2 | 0x4 | 0x10
        data.szInfoTitle, data.szInfo, data.dwInfoFlags = "JARVIS", text[:250], 0x1
        shell32.Shell_NotifyIconW(1, ctypes.byref(data))
        data.uFlags = 0x1 | 0x2 | 0x4

    from jcc.dictate import Dictation
    from jcc.wake import Ears
    from jcc import pcsound, sound

    def beep(pitch: int) -> None:       # on the speakers chosen in Voice and assistant, or the Windows default
        sound.beep(cfg, pitch)
    dictation = Dictation(cfg, balloon, beep=beep)
    # "Hey JARVIS", all the time: spotted on this PC, then handed to JARVIS. Quiet while a spoken conversation is already going on.
    ears = Ears(cfg, lambda text: say(cfg, text), balloon, beep=beep, busy=lambda: (ask_service(cfg, "status") or {}).get("voice") is True,
                control=lambda word: ask_service(cfg, "control", word), attend=lambda: attend(cfg), listen=lambda: nudge(cfg), sound=pcsound.shared,
                name_said=lambda at: ask_service(cfg, "name", str(at)))
    from jcc.wake import restore_volume
    restore_volume(cfg)                   # (if JARVIS was closed in the few seconds it had turned the sound down to listen)
    state = {"wake": None}

    def write_status() -> None:
        import json
        (cfg.state_dir / "tray-status.json").write_text(json.dumps({
            "tray": tray_added, **{NAMES[ident] + "_hotkey": ident in active for ident in NAMES},
            "keys": {NAMES[ident]: label for ident, label in active.items()}, "wake": bool(state["wake"]),
            "wake_problem": ears.problem or ears.note, "wake_mic": ears.microphone(), "wake_engine": ears.engine}), "utf-8")

    def keep_ears() -> None:
        try:
            listening = ears.sync()
        except Exception:  # noqa: BLE001 - the wake word is optional; the tray must keep running
            listening = False
        seen = (ears.problem or ears.note, ears.microphone(), ears.engine)
        if listening != state["wake"] or seen != state.get("seen"):
            state["wake"], state["seen"] = listening, seen
            write_status()

    def menu(window) -> None:
        handle = user32.CreatePopupMenu()
        def shown(text, ident):
            return text + ("\t" + active[ident] if ident in active else "")
        user32.AppendMenuW(handle, 0, OPEN, shown("Open JARVIS", HOTKEY_OPEN))
        user32.AppendMenuW(handle, 0, TALK, shown("Talk to JARVIS", HOTKEY_TALK))
        user32.AppendMenuW(handle, 0, DICTATE, shown("Finish dictating" if dictation.listening else "Dictate into any app", HOTKEY_DICTATE))
        user32.AppendMenuW(handle, 0, STOP_COMPUTER, shown("Stop everything JARVIS is doing", HOTKEY_STOP))
        user32.AppendMenuW(handle, 0x800, 0, None)
        user32.AppendMenuW(handle, 0, QUIT, "Hide this icon until next sign-in")
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        user32.SetForegroundWindow(window)
        choice = user32.TrackPopupMenu(handle, 0x0100 | 0x0002, point.x, point.y, 0, window, None)
        user32.DestroyMenu(handle)
        act(window, choice)

    def act(window, choice) -> None:
        if choice == OPEN:
            open_jarvis()
        elif choice == STOP_COMPUTER:
            stop_computer()
        elif choice == TALK:
            talk(cfg)
        elif choice == DICTATE:
            dictation.toggle()
        elif choice == QUIT:
            user32.DestroyWindow(window)

    def procedure(window, message, wparam, lparam):
        if message == WM_APP_TRAY:
            if lparam == WM_LBUTTONUP:
                open_jarvis()
            elif lparam == WM_RBUTTONUP:
                menu(window)
            return 0
        if message == 0x0113:   # the timer: keep the wake-word listener in step with the settings
            keep_ears()
            return 0
        if message == WM_HOTKEY:
            if wparam == HOTKEY_OPEN:
                open_jarvis()
            elif wparam == HOTKEY_TALK:
                talk(cfg)
            elif wparam == HOTKEY_DICTATE:
                dictation.toggle()
            else:
                stop_computer()
            return 0
        if message == WM_DESTROY:
            if tray_added:
                shell32.Shell_NotifyIconW(2, ctypes.byref(data))
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(window, message, wparam, lparam)

    callback = WNDPROC(procedure)
    instance = kernel32.GetModuleHandleW(None)
    cls = WNDCLASSW()
    cls.lpfnWndProc, cls.hInstance, cls.lpszClassName = callback, instance, "JarvisTrayHelper"
    user32.RegisterClassW(ctypes.byref(cls))
    window = user32.CreateWindowExW(0, cls.lpszClassName, "JARVIS helper", 0, 0, 0, 0, 0, None, None, instance, None)
    if not window:
        lock.release()
        return 1
    if options["tray"]:
        icon_path = cfg.state_dir / "jarvis.ico"
        try:
            icon_path.write_bytes(icon_bytes())
            icon = user32.LoadImageW(None, str(icon_path), 1, 32, 32, 0x0010)
        except OSError:
            icon = None
        data.cbSize, data.hWnd, data.uID = ctypes.sizeof(NOTIFYICONDATAW), window, 1
        data.uFlags, data.uCallbackMessage = 0x1 | 0x2 | 0x4, WM_APP_TRAY
        data.hIcon = icon or user32.LoadIconW(None, ctypes.c_void_p(32512))
        data.szTip = "JARVIS — click to open (Ctrl+Alt+J)"
        tray_added = bool(shell32.Shell_NotifyIconW(0, ctypes.byref(data)))
    if options["hotkey"]:
        active.update(claim(lambda ident, key: bool(user32.RegisterHotKey(window, ident, 0x0001 | 0x0002 | 0x4000, key))))
    registered = list(active)
    keep_ears()
    write_status()
    user32.SetTimer(window, 1, 4000, None)
    if "--check" in sys.argv:
        user32.DestroyWindow(window)
    message = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(message))
        user32.DispatchMessageW(ctypes.byref(message))
    ears.stop()
    for ident in registered:
        user32.UnregisterHotKey(window, ident)
    lock.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
