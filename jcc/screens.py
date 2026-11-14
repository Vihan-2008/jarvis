"""The screens connected to this PC, in their true pixels.

JARVIS used to know only the main screen: it took its picture, and counted every position from its corner. With a
second screen, a window on it could not be seen at all. And Windows gives a program that has not said it understands
display scaling made-up numbers for every screen whose scaling differs from the main one's: a 2560 by 1600 laptop screen
at 200% beside a 1920 by 1080 monitor at 100% is reported as 1280 by 800, and a picture of it comes out at half its
sharpness.

Everything here is asked for as a thread that does understand it ("per-monitor aware"), so positions are real pixels of
the whole desktop: the main screen's corner is (0, 0), and a screen to its left or above has negative positions.

Screens are numbered for people: 1 is the main screen, the others follow from left to right, then top to bottom.
"""
from __future__ import annotations

import contextlib
import ctypes
import os
import struct

PER_MONITOR = -4          # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2


@contextlib.contextmanager
def physical():
    """While inside: this thread sees, and gives, positions in true pixels on every screen."""
    before = None
    if os.name == "nt":
        try:
            user32 = ctypes.windll.user32
            user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
            before = user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(PER_MONITOR))
        except (AttributeError, OSError):      # an older Windows: as it was
            before = None
    try:
        yield
    finally:
        if before:
            try:
                ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(before))
            except (AttributeError, OSError):
                pass


def aware() -> bool:
    """Make this whole process see every screen in its true pixels. Only possible before it has asked Windows anything
    about windows or screens (a helper does this as it starts); elsewhere physical() is used around each call."""
    if os.name != "nt":
        return False
    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        return bool(user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(PER_MONITOR)))
    except (AttributeError, OSError):
        return False


def _builtin() -> set[str]:
    """The names Windows gives the screens that are part of the PC itself (a laptop's own panel), e.g. {"\\\\.\\DISPLAY1"}.
    Empty when that cannot be told."""
    from ctypes import wintypes

    class Luid(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.LONG)]

    class Source(ctypes.Structure):
        _fields_ = [("adapter", Luid), ("id", ctypes.c_uint32), ("mode", ctypes.c_uint32), ("status", ctypes.c_uint32)]

    class Target(ctypes.Structure):
        _fields_ = [("adapter", Luid), ("id", ctypes.c_uint32), ("mode", ctypes.c_uint32), ("technology", ctypes.c_uint32), ("rotation", ctypes.c_uint32),
                    ("scaling", ctypes.c_uint32), ("rate_top", ctypes.c_uint32), ("rate_bottom", ctypes.c_uint32), ("ordering", ctypes.c_uint32),
                    ("available", wintypes.BOOL), ("status", ctypes.c_uint32)]

    class Path(ctypes.Structure):
        _fields_ = [("source", Source), ("target", Target), ("flags", ctypes.c_uint32)]

    class Mode(ctypes.Structure):
        _fields_ = [("kind", ctypes.c_uint32), ("id", ctypes.c_uint32), ("adapter", Luid), ("rest", ctypes.c_byte * 48)]

    class Name(ctypes.Structure):
        _fields_ = [("kind", ctypes.c_uint32), ("size", ctypes.c_uint32), ("adapter", Luid), ("id", ctypes.c_uint32), ("gdi", wintypes.WCHAR * 32)]

    user32 = ctypes.windll.user32
    paths, modes = ctypes.c_uint32(), ctypes.c_uint32()
    if user32.GetDisplayConfigBufferSizes(2, ctypes.byref(paths), ctypes.byref(modes)) or not paths.value:      # 2: only the screens in use
        return set()
    path_list, mode_list = (Path * paths.value)(), (Mode * max(1, modes.value))()
    if user32.QueryDisplayConfig(2, ctypes.byref(paths), path_list, ctypes.byref(modes), mode_list, None):
        return set()
    own = set()
    for path in path_list[:paths.value]:
        # built into the PC: "internal", or one of the kinds only used inside a laptop (LVDS, embedded DisplayPort, embedded UDI)
        if path.target.technology not in (0x80000000, 6, 11, 13):
            continue
        name = Name()
        name.kind, name.size, name.adapter, name.id = 1, ctypes.sizeof(Name), path.source.adapter, path.source.id
        if user32.DisplayConfigGetDeviceInfo(ctypes.byref(name)) == 0 and name.gdi:
            own.add(str(name.gdi))
    return own


def _raw() -> list[dict]:
    """Every screen as Windows lists it: its place, its usable part (without the taskbar), its scaling."""
    from ctypes import wintypes
    user32 = ctypes.windll.user32

    class Info(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("whole", wintypes.RECT), ("work", wintypes.RECT), ("flags", wintypes.DWORD), ("device", wintypes.WCHAR * 32)]

    each_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(Info)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), each_type, wintypes.LPARAM]
    user32.EnumDisplayMonitors.restype = wintypes.BOOL
    found: list[dict] = []

    def each(monitor, _dc, _rect, _extra):
        info = Info()
        info.size = ctypes.sizeof(Info)
        if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            across, down = ctypes.c_uint(96), ctypes.c_uint(96)
            try:
                ctypes.windll.shcore.GetDpiForMonitor(ctypes.c_void_p(monitor), 0, ctypes.byref(across), ctypes.byref(down))
            except (AttributeError, OSError):
                pass
            whole, work = info.whole, info.work
            found.append({"handle": int(monitor), "left": whole.left, "top": whole.top, "width": whole.right - whole.left, "height": whole.bottom - whole.top,
                          "work": (work.left, work.top, work.right, work.bottom), "scale": round((across.value or 96) / 96, 2), "main": bool(info.flags & 1),
                          "name": str(info.device)})
        return True

    user32.EnumDisplayMonitors(None, None, each_type(each), 0)
    try:
        own = _builtin()
    except Exception:  # noqa: BLE001 - only a nicety: without it no screen is called the laptop's own
        own = set()
    for screen in found:
        screen["builtin"] = screen["name"] in own
    return found


def number(found: list[dict]) -> list[dict]:
    """The screens in the order people count them: the main one first, the rest from left to right, then top to bottom."""
    usable = [s for s in found if s["width"] >= 200 and s["height"] >= 200]
    usable.sort(key=lambda s: (not s["main"], s["left"], s["top"]))
    return [{**s, "number": i + 1} for i, s in enumerate(usable)]


def screens(lister=None) -> list[dict]:
    """Every connected screen (see number()). Empty when Windows will not say."""
    if os.name != "nt" and lister is None:
        return []
    try:
        with physical():
            return number((lister or _raw)())
    except Exception:  # noqa: BLE001 - whatever Windows did, the caller carries on with what it knew before
        return []


def holding_point(found: list[dict], x: int, y: int) -> dict | None:
    """The screen a point is on; if it is on none (between two, or beyond the edge), the nearest one."""
    if not found:
        return None
    for s in found:
        if s["left"] <= x < s["left"] + s["width"] and s["top"] <= y < s["top"] + s["height"]:
            return s

    def away(s):
        dx = max(s["left"] - x, 0, x - (s["left"] + s["width"] - 1))
        dy = max(s["top"] - y, 0, y - (s["top"] + s["height"] - 1))
        return dx * dx + dy * dy
    return min(found, key=away)


def holding_box(found: list[dict], box: tuple[int, int, int, int]) -> dict | None:
    """The screen that shows most of a window (left, top, right, bottom); the nearest one if it is on none."""
    if not found:
        return None

    def shown(s):
        across = min(box[2], s["left"] + s["width"]) - max(box[0], s["left"])
        down = min(box[3], s["top"] + s["height"]) - max(box[1], s["top"])
        return max(0, across) * max(0, down)
    best = max(found, key=shown)
    return best if shown(best) > 0 else holding_point(found, (box[0] + box[2]) // 2, (box[1] + box[3]) // 2)


def window_box(handle: int) -> tuple[int, int, int, int] | None:
    """Where a window is, in true pixels (as it is drawn, without the invisible edge Windows adds for resizing)."""
    if os.name != "nt" or not handle:
        return None
    from ctypes import wintypes
    box = wintypes.RECT()
    with physical():
        user32 = ctypes.windll.user32
        got = False
        try:      # 9 = DWMWA_EXTENDED_FRAME_BOUNDS
            got = ctypes.windll.dwmapi.DwmGetWindowAttribute(ctypes.c_void_p(handle), 9, ctypes.byref(box), ctypes.sizeof(box)) == 0
        except (AttributeError, OSError):
            got = False
        if not got and not user32.GetWindowRect(ctypes.c_void_p(handle), ctypes.byref(box)):
            return None
    return (box.left, box.top, box.right, box.bottom) if box.right > box.left and box.bottom > box.top else None


def of_window(handle: int, found: list[dict] | None = None) -> dict | None:
    """The screen a window is on (most of it)."""
    found = screens() if found is None else found
    box = window_box(handle)
    return holding_box(found, box) if box else next((s for s in found if s["main"]), found[0] if found else None)


def where(screen: dict, found: list[dict]) -> str:
    """In words, where a screen is seen from the main one: "to the right", "above"..."""
    main = next((s for s in found if s["main"]), None)
    if not main or screen is main or screen.get("main"):
        return ""
    dx = (screen["left"] + screen["width"] / 2) - (main["left"] + main["width"] / 2)
    dy = (screen["top"] + screen["height"] / 2) - (main["top"] + main["height"] / 2)
    if abs(dx) >= abs(dy):
        return "to the right" if dx > 0 else "to the left"
    return "below" if dy > 0 else "above"


def describe(found: list[dict]) -> str:
    """One line saying which screens there are, for a person or an AI."""
    if not found:
        return ""
    if len(found) == 1:
        s = found[0]
        return f"One screen, {s['width']} by {s['height']}" + (f" at {round(s['scale'] * 100)}%" if s["scale"] != 1 else "") + "."
    parts = []
    for s in found:
        place = "the main screen" if s["main"] else where(s, found) + " of the main screen"
        parts.append(f"screen {s['number']} ({place}, {s['width']} by {s['height']}" + (f" at {round(s['scale'] * 100)}%" if s["scale"] != 1 else "") +
                     (", the laptop's own screen" if s.get("builtin") else "") + ")")
    return f"{len(found)} screens: " + "; ".join(parts) + "."


def grab(left: int, top: int, width: int, height: int, max_width: int = 1920) -> tuple[int, int, bytes]:
    """A picture of a rectangle of the desktop given in true pixels (any screen, negative positions included), made no
    wider than max_width. Returns (width, height, PNG)."""
    from jcc.computer import png
    if width < 1 or height < 1 or width > 20000 or height > 20000:
        raise ValueError("That part of the screen cannot be captured.")
    with physical():
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        for fn in (user32.GetDC, gdi32.CreateCompatibleDC, gdi32.CreateCompatibleBitmap, gdi32.SelectObject):
            fn.restype = ctypes.c_void_p
        scale = max(1.0, width / max_width)
        out_w, out_h = max(1, int(width / scale)), max(1, int(height / scale))
        desk = user32.GetDC(None)
        memory = gdi32.CreateCompatibleDC(ctypes.c_void_p(desk))
        bitmap = gdi32.CreateCompatibleBitmap(ctypes.c_void_p(desk), out_w, out_h)
        old = gdi32.SelectObject(ctypes.c_void_p(memory), ctypes.c_void_p(bitmap))
        try:
            gdi32.SetStretchBltMode(ctypes.c_void_p(memory), 4)      # HALFTONE keeps small text readable
            gdi32.StretchBlt(ctypes.c_void_p(memory), 0, 0, out_w, out_h, ctypes.c_void_p(desk), int(left), int(top), int(width), int(height), 0x00CC0020)
            header = struct.pack("<IiiHHIIiiII", 40, out_w, -out_h, 1, 32, 0, 0, 0, 0, 0, 0)
            pixels, info = ctypes.create_string_buffer(out_w * out_h * 4), ctypes.create_string_buffer(header, 64)
            gdi32.GetDIBits(ctypes.c_void_p(memory), ctypes.c_void_p(bitmap), 0, out_h, pixels, info, 0)
        finally:
            gdi32.SelectObject(ctypes.c_void_p(memory), ctypes.c_void_p(old))
            gdi32.DeleteObject(ctypes.c_void_p(bitmap))
            gdi32.DeleteDC(ctypes.c_void_p(memory))
            user32.ReleaseDC(None, ctypes.c_void_p(desk))
    raw = pixels.raw
    rgb = bytearray(out_w * out_h * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = raw[2::4], raw[1::4], raw[0::4]
    return out_w, out_h, png(out_w, out_h, bytes(rgb))


def fit(box: tuple[int, int, int, int], here: dict, there: dict) -> tuple[int, int, int, int]:
    """Where a window that sits at `box` on one screen belongs on another: the same share of the usable part, in the same
    place within it, and wholly on that screen. Returns (left, top, width, height)."""
    hl, ht, hr, hb = here["work"]
    tl, tt, tr, tb = there["work"]
    across, down = max(1, hr - hl), max(1, hb - ht)
    room_w, room_h = max(1, tr - tl), max(1, tb - tt)
    width = min(room_w, max(200, round((box[2] - box[0]) / across * room_w)))
    height = min(room_h, max(150, round((box[3] - box[1]) / down * room_h)))
    left = tl + round((box[0] - hl) / across * room_w)
    top = tt + round((box[1] - ht) / down * room_h)
    return min(max(left, tl), tr - width), min(max(top, tt), tb - height), width, height


def move_window(handle: int, target: dict, found: list[dict] | None = None) -> bool:
    """Put a window on another screen, keeping how it sits (maximised stays maximised; otherwise the same share of the screen)."""
    if os.name != "nt" or not handle or not target:
        return False
    found = screens() if found is None else found
    here = of_window(handle, found)
    if not here or here["handle"] == target["handle"]:
        return bool(here)
    with physical():
        user32 = ctypes.windll.user32
        pointer = ctypes.c_void_p(handle)
        full = bool(user32.IsZoomed(pointer))
        if full or user32.IsIconic(pointer):
            user32.ShowWindow(pointer, 9)                        # back to its own size first: a maximised window cannot be moved
        box = window_box(handle)
        if not box:
            return False
        left, top, width, height = fit(box, here, target)
        moved = bool(user32.SetWindowPos(pointer, None, int(left), int(top), int(width), int(height), 0x0004 | 0x0010))   # no reordering, not activated
        if full:
            user32.ShowWindow(pointer, 3)
    return moved


_COUNT = {"first": 1, "one": 1, "1st": 1, "second": 2, "two": 2, "2nd": 2, "third": 3, "three": 3, "3rd": 3, "fourth": 4, "four": 4, "4th": 4}
_WAYS = {"left": (-1, 0), "right": (1, 0), "above": (0, -1), "up": (0, -1), "top": (0, -1), "upper": (0, -1), "below": (0, 1), "down": (0, 1), "bottom": (0, 1), "lower": (0, 1)}


def choose(found: list[dict], here: dict | None, which) -> dict | None:
    """The screen meant by a number or a word, seen from the screen `here`: 2, "second", "other", "next", "main", "left",
    "right", "above", "below", "biggest", "smallest". None if there is no such screen."""
    if not found:
        return None
    words = [w for w in "".join(c if c.isalnum() else " " for c in str(which).lower()).split() if w not in ("screen", "monitor", "display", "the", "my", "one", "to", "on")]
    said = str(which).lower().split()
    text = " ".join(words) or ("one" if "one" in said else "external" if "monitor" in said else "")      # ("the monitor": the one that is not the laptop's)
    here = here or next((s for s in found if s["main"]), found[0])
    if text.isdigit() or text in _COUNT:
        wanted = int(text) if text.isdigit() else _COUNT[text]
        return next((s for s in found if s["number"] == wanted), None)
    if text in ("main", "primary"):
        return next((s for s in found if s["main"]), None)
    if text in ("other", "next", "another"):
        if len(found) < 2:
            return None
        return found[(found.index(here) + 1) % len(found)] if here in found else found[0]
    if text in ("previous", "last"):
        return found[(found.index(here) - 1) % len(found)] if here in found and len(found) > 1 else None
    if text in ("laptop", "laptops", "laptop own", "built in", "builtin", "internal"):
        return next((s for s in found if s.get("builtin")), None)
    if text in ("external", "outside", "tv", "television", "projector"):          # the one that is not part of the PC, if there is just one
        outside = [s for s in found if not s.get("builtin")]
        return outside[0] if len(outside) == 1 and len(found) > 1 else None
    if text in ("biggest", "largest", "big", "large", "bigger", "larger"):
        return max(found, key=lambda s: s["width"] * s["height"])
    if text in ("smallest", "small", "smaller"):
        return min(found, key=lambda s: s["width"] * s["height"])
    way = next((_WAYS[w] for w in words if w in _WAYS), None)
    if way:
        cx, cy = here["left"] + here["width"] / 2, here["top"] + here["height"] / 2
        best, least = None, None
        for s in found:
            if s is here or s["number"] == here["number"]:
                continue
            dx, dy = s["left"] + s["width"] / 2 - cx, s["top"] + s["height"] / 2 - cy
            along = dx * way[0] + dy * way[1]
            if along <= 0 or abs(dx * way[1] + dy * way[0]) > along * 2:      # not on that side (or far more to another side)
                continue
            if least is None or along < least:
                best, least = s, along
        return best
    return None
