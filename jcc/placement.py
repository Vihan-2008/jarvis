"""Where the app window opens: the size and place it had last time, made to fit the screen it is opening on.

The window used to open at one fixed size (1280 by 860). On a smaller screen that is taller than the screen itself, so
the message box and other controls ended up below the bottom edge. Now:

  - the first time, the window is sized to the screen, or opens maximized when the screen is small;
  - after that it opens where you left it, at the size you gave it, moved back onto a screen if that one is gone.

The window says where it is (jcc/static/nova.js, POST /api/window); the launcher asks here for Edge's arguments.
All sizes are in the units Edge uses on its command line: screen points before display scaling.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from jcc.vault import atomic_write, read_json

USUAL = (1280, 860)          # the size on a screen with room for it
SMALLEST = (480, 400)        # nothing useful fits in less
LARGEST = (10000, 10000)
EDGE = 24                    # room left around a window that is sized to a screen
Area = tuple[int, int, int, int]   # left, top, right, bottom


def _file(cfg) -> Path:
    return cfg.state_dir / "window.json"


def screens() -> list[Area]:
    """The usable part of each screen (without the taskbar), the main screen first. Empty when that cannot be told."""
    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32

        class Info(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("whole", wintypes.RECT), ("work", wintypes.RECT), ("flags", wintypes.DWORD)]

        each_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
        user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(Info)]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), each_type, wintypes.LPARAM]
        user32.EnumDisplayMonitors.restype = wintypes.BOOL
        found: list[tuple[bool, Area]] = []

        def each(monitor, _dc, _rect, _extra):
            info = Info()
            info.size = ctypes.sizeof(Info)
            if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                work = info.work
                found.append((not info.flags & 1, (work.left, work.top, work.right, work.bottom)))
            return True

        # Ask as a program that knows nothing about display scaling: Windows then answers in screen points before
        # scaling, which is what Edge's --window-size and --window-position take.
        before = None
        try:
            user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
            before = user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-1))
        except (AttributeError, OSError):
            before = None
        try:
            user32.EnumDisplayMonitors(None, None, each_type(each), 0)
        finally:
            if before:
                user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(before))
        found.sort(key=lambda row: row[0])                  # the main screen first
        return [area for _, area in found if area[2] - area[0] >= 200 and area[3] - area[1] >= 200]
    except Exception:  # noqa: BLE001 - a window must still open when Windows will not say
        return []


def _number(value, low: int, high: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or not (low <= value <= high):
        return None
    return int(round(value))


def remember(cfg, body) -> dict:
    """Keep where the app window is, as the window itself reported it."""
    if not isinstance(body, dict):
        raise ValueError("Invalid request.")
    width, height = _number(body.get("width"), 200, LARGEST[0]), _number(body.get("height"), 200, LARGEST[1])
    left, top = _number(body.get("x"), -40000, 40000), _number(body.get("y"), -40000, 40000)
    if None in (width, height, left, top):
        raise ValueError("Invalid request.")
    kept = read_json(_file(cfg), {})
    if body.get("max") is True:
        # Maximized: remember that, and keep the size it had before as the size to go back to.
        kept = {"x": kept.get("x"), "y": kept.get("y"), "width": kept.get("width"), "height": kept.get("height"), "max": True,
                "on": [left + width // 2, top + height // 2]}
    else:
        kept = {"x": left, "y": top, "width": width, "height": height, "max": False}
    kept["at"] = int(time.time())
    atomic_write(_file(cfg), json.dumps(kept))
    return {"ok": True}


def place(saved: dict | None, areas: list[Area]) -> dict:
    """The size and place to open at: {"width", "height", "x", "y", "max"} (x and y are None when the place is left to Windows)."""
    saved = saved if isinstance(saved, dict) else {}
    width, height = _number(saved.get("width"), 200, LARGEST[0]), _number(saved.get("height"), 200, LARGEST[1])
    left, top = _number(saved.get("x"), -40000, 40000), _number(saved.get("y"), -40000, 40000)
    known = None not in (width, height, left, top)
    maximized = saved.get("max") is True
    if not areas:                                           # nothing is known about the screen
        return {"width": width if known else USUAL[0], "height": height if known else USUAL[1], "x": None, "y": None, "max": maximized}
    # The screen it was on: the one that holds its middle; the main screen if that screen is gone.
    middle = saved.get("on") if maximized and isinstance(saved.get("on"), list) and len(saved["on"]) == 2 else None
    if middle is None and known:
        middle = [left + width // 2, top + height // 2]
    area = areas[0]
    if middle and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in middle):
        area = next((a for a in areas if a[0] <= middle[0] < a[2] and a[1] <= middle[1] < a[3]), areas[0])
    room_w, room_h = area[2] - area[0], area[3] - area[1]
    if not known:
        # First time (or after a maximized start with nothing else known): the usual size if the screen has room for
        # it, otherwise as large as the screen allows. On a small screen, all of it.
        small = room_w < USUAL[0] + 2 * EDGE or room_h < USUAL[1] + 2 * EDGE
        width, height = min(USUAL[0], room_w - 2 * EDGE), min(USUAL[1], room_h - 2 * EDGE)
        width, height = max(min(SMALLEST[0], room_w), width), max(min(SMALLEST[1], room_h), height)
        return {"width": width, "height": height, "x": area[0] + (room_w - width) // 2, "y": area[1] + (room_h - height) // 2,
                "max": maximized or (small and not saved)}
    width, height = min(max(width, min(SMALLEST[0], room_w)), room_w), min(max(height, min(SMALLEST[1], room_h)), room_h)
    left, top = min(max(left, area[0]), area[2] - width), min(max(top, area[1]), area[3] - height)
    return {"width": width, "height": height, "x": left, "y": top, "max": maximized}


# ---------------------------------------------------------------------- the window's own browser profile
# Two of the browser's own habits are switched off in JARVIS's profile, because no rule a page is served with reaches
# them: connecting ahead to addresses a page merely mentions, and WebRTC sending packets of its own. A page JARVIS shows
# sealed (jcc/gui.py) could otherwise let a server on the internet know a few words through them.
QUIET = {"net": {"network_prediction_options": 2}, "webrtc": {"ip_handling_policy": "disable_non_proxied_udp"}}


def _quiet(settings: Path) -> None:
    """Add those two settings to a profile that was made before they were. (Edge reads the file when it starts and keeps
    what it read, so this takes hold the next time JARVIS's windows are opened afresh, and is then left alone.)"""
    try:
        kept = json.loads(settings.read_text("utf-8"))
        if not isinstance(kept, dict) or all(isinstance(kept.get(area), dict) and kept[area].get(name) == value
                                             for area, wanted in QUIET.items() for name, value in wanted.items()):
            return
        for area, wanted in QUIET.items():
            kept[area] = {**(kept.get(area) if isinstance(kept.get(area), dict) else {}), **wanted}
        atomic_write(settings, json.dumps(kept))
    except (OSError, ValueError):
        pass                                        # the window opens all the same


def profile(cfg, address: str = "http://127.0.0.1:8765") -> list[str]:
    """Edge's arguments for JARVIS's own browser profile, where its window may speak and listen the moment it opens.

    A window that has just opened in an ordinary profile may not make sound or use the microphone until someone clicks in
    it; "Hey JARVIS" would then need a click before anything is heard or said. In its own profile the window is allowed to
    play sound at once, and the microphone is allowed for JARVIS's own address (and for nothing else) from the start.
    The profile lives in JARVIS's settings folder, which the assistant itself can never read."""
    folder = cfg.state_dir / "window-profile"
    settings = folder / "Default" / "Preferences"
    if not settings.exists():
        try:
            settings.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(settings, json.dumps({"profile": {"content_settings": {"exceptions": {
                "media_stream_mic": {address.rstrip("/") + ",*": {"setting": 1}}}}}, **QUIET}))
        except OSError:
            return []                               # the window still opens, in the everyday profile, as before
    else:
        _quiet(settings)
    # --disable-sync: nothing in JARVIS's own windows is ever copied to a Microsoft account. (Without it a new profile also
    # opens with Edge's "we've signed you in" notice, which fills the whole of the small listening window.)
    # CalculateNativeWinOcclusion off: Edge works out for itself whether a window is covered by other windows and stops
    # drawing it then. It does not notice the small listening window coming onto the screen (it is shown without being
    # activated), so that window stayed blank until the keyboard went to another program. JARVIS's windows are drawn
    # whenever they are shown; a hidden or minimised one still is not.
    return [f"--user-data-dir={folder}", "--no-first-run", "--no-default-browser-check", "--autoplay-policy=no-user-gesture-required",
            "--disable-features=Translate,CalculateNativeWinOcclusion", "--hide-crash-restore-bubble", "--disable-sync"]


# ---------------------------------------------------------------------- the window's preferences (theme, panel width...)
_PREF = __import__("re").compile(r"(?:nv|jcc)-[a-z-]{1,24}")


def prefs(cfg) -> dict:
    """What the window remembers about how its owner likes it. Kept by the app, so it does not depend on a browser profile."""
    saved = read_json(cfg.state_dir / "window-prefs.json", {})
    return {key: value for key, value in saved.items() if isinstance(key, str) and _PREF.fullmatch(key) and isinstance(value, str) and len(value) <= 300}


def set_pref(cfg, key, value) -> dict:
    if not isinstance(key, str) or not _PREF.fullmatch(key) or not isinstance(value, str) or len(value) > 300:
        raise ValueError("Invalid request.")
    saved = prefs(cfg)
    if key not in saved and len(saved) >= 40:
        raise ValueError("Invalid request.")
    saved[key] = value
    atomic_write(cfg.state_dir / "window-prefs.json", json.dumps(saved))
    return {"ok": True}


def note_problem(cfg, text) -> None:
    """Keep a line about a script error a window reported (the last few hundred are kept, on this PC only)."""
    from jcc.redact import redact
    line = time.strftime("%Y-%m-%d %H:%M:%S") + "  " + " ".join(redact(str(text)).split())[:700]
    path = cfg.state_dir / "window-problems.log"
    try:
        kept = path.read_text("utf-8").splitlines()[-300:] if path.exists() else []
        atomic_write(path, "\n".join(kept + [line]) + "\n")
    except OSError:
        pass


def opens_full(cfg) -> bool:
    """Whether the window opens in full screen: the first time yes, and after that the way its owner left it."""
    return prefs(cfg).get("nv-open", "fullscreen") == "fullscreen"


def press_full_screen(windows=None, press=None) -> bool:
    """Press F11 in JARVIS's own window (that is how a window goes into and out of full screen). Only when it is in front."""
    try:
        if windows is None:
            from jcc import winctl as windows
        from jcc.policy import MAIN_WINDOW
        front = windows.foreground()
        if not front or not MAIN_WINDOW.search(windows.title_of(front)):
            return False
        if press is None:
            from jcc import computer
            press = computer.real_desktop().perform
        press({"action": "key", "keys": "f11"})
        return True
    except Exception:  # noqa: BLE001 - the page then uses its own full screen instead
        return False


def arguments(cfg, areas: list[Area] | None = None, full: bool = True) -> list[str]:
    """What to add to Edge's command line so the app window opens in the right place (and in full screen, if that is how
    it is to open). full=False: a window that opens by itself while the owner is doing something else never takes the whole screen."""
    spot = place(read_json(_file(cfg), {}), screens() if areas is None else areas)
    out = [f"--window-size={spot['width']},{spot['height']}"]
    if spot["x"] is not None and spot["y"] is not None:
        out.append(f"--window-position={spot['x']},{spot['y']}")
    if full and opens_full(cfg):
        out.append("--start-fullscreen")
    elif spot["max"]:
        out.append("--start-maximized")
    return out
