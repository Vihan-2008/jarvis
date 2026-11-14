"""JARVIS's hands and eyes on a Mac: the windows, the controls inside them, the screen, the pointer and the keys.

The assistant's tools (jcc/voice_tools.py) and the step-by-step panel (jcc/computer.py) were written against three
things on Windows: the open windows (jcc/winctl.py), a window's controls by name (jcc/uia.py) and a desktop that takes
pictures and presses keys (Desktop in jcc/computer.py). This file is those three for a Mac, with the same calls and the
same answers, so nothing above it has to know which system it is on.

What macOS itself is asked is in jcc/macax.py. Everything here that decides something can be tested without a Mac:
tests pass a stand-in for that file.

Positions are the Mac's own points on the whole desktop: the main screen's corner is (0, 0), as on Windows. A picture
of a screen is never wider than the step-by-step panel's pictures, and `scale` says how many points one picture pixel
stands for, exactly as on Windows.
"""
from __future__ import annotations

import shutil
import struct
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from jcc.uia import _FIELDS, _PLAIN, _PRESSABLE, choose, mark_pages

SHOT_WIDTH = 1280
# What the Mac calls each kind of control, in the words the rest of JARVIS already uses for them.
ROLES = {"AXButton": "Button", "AXMenuButton": "Button", "AXDisclosureTriangle": "Button", "AXColorWell": "Button", "AXPopUpButton": "ComboBox",
         "AXComboBox": "ComboBox", "AXCheckBox": "CheckBox", "AXRadioButton": "RadioButton", "AXTextField": "Edit", "AXTextArea": "Edit",
         "AXDateField": "Edit", "AXLink": "Hyperlink", "AXStaticText": "Text", "AXHeading": "Text", "AXImage": "Image", "AXMenuItem": "MenuItem",
         "AXMenuBarItem": "MenuItem", "AXRow": "ListItem", "AXCell": "DataItem", "AXSlider": "Slider", "AXIncrementor": "Spinner", "AXTabGroup": "Tab",
         "AXGroup": "Group", "AXScrollArea": "Pane", "AXSplitGroup": "Pane", "AXToolbar": "ToolBar", "AXList": "List", "AXOutline": "Tree",
         "AXTable": "Table", "AXWindow": "Window", "AXSheet": "Window", "AXScrollBar": "ScrollBar", "AXSplitter": "Separator", "AXWebArea": "Document",
         "AXMenu": "Menu", "AXMenuBar": "MenuBar", "AXProgressIndicator": "ProgressBar", "AXBusyIndicator": "ProgressBar"}
SUBROLES = {"AXTabButton": "TabItem", "AXSecureTextField": "Edit", "AXSearchField": "Edit", "AXSwitch": "CheckBox", "AXToggle": "CheckBox"}
HOW = {"CheckBox": "switched", "TabItem": "selected", "RadioButton": "selected", "ListItem": "selected", "DataItem": "selected", "ComboBox": "opened"}
# macOS's numbers for the keys of a keyboard (the same on every layout for the keys named here).
KEYCODES = {"enter": 36, "return": 36, "tab": 48, "space": 49, "backspace": 51, "esc": 53, "escape": 53, "delete": 117, "del": 117, "home": 115,
            "end": 119, "pageup": 116, "pagedown": 121, "left": 123, "right": 124, "down": 125, "up": 126,
            "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98, "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111,
            "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17,
            "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "9": 25, "7": 26, "8": 28, "0": 29, "o": 31, "u": 32, "i": 34, "p": 35, "l": 37,
            "j": 38, "k": 40, "n": 45, "m": 46}
# The keys held with another: (the key's own number, the mark it puts on every key pressed while it is down).
# "win" is the Command key: it sits where the Windows key does and does the same job.
MODIFIERS = {"cmd": (55, 1 << 20), "command": (55, 1 << 20), "win": (55, 1 << 20), "windows": (55, 1 << 20), "ctrl": (59, 1 << 18),
             "control": (59, 1 << 18), "alt": (58, 1 << 19), "option": (58, 1 << 19), "opt": (58, 1 << 19), "shift": (56, 1 << 17)}
COMMAND = frozenset({"cmd", "command", "win", "windows"})
# Shortcuts that are never pressed for anyone: logging out, locking the Mac, force-quitting.
NEVER_COMBOS = ({"cmd", "alt", "esc"}, {"cmd", "alt", "escape"}, {"cmd", "ctrl", "q"}, {"cmd", "shift", "q"})
# ... and those the step-by-step panel does not press either: quitting an app, and Spotlight (which starts anything by name).
BLOCKED_COMBOS = NEVER_COMBOS + ({"cmd", "q"}, {"cmd", "space"})
# Shortcuts after which another window is in front on purpose.
SWITCHING_KEYS = ({"cmd", "tab"}, {"cmd", "shift", "tab"}, {"cmd", "`"}, {"cmd", "w"}, {"cmd", "h"}, {"cmd", "m"}, {"cmd", "n"})


def plain_keys(parts) -> set:
    """A shortcut's keys with each modifier under one name ("command", "win" and "cmd" are all cmd; "option" is alt)."""
    names = {"command": "cmd", "win": "cmd", "windows": "cmd", "control": "ctrl", "option": "alt", "opt": "alt"}
    return {names.get(str(part).lower(), str(part).lower()) for part in parts}


def blocked(parts) -> bool:
    """A shortcut the step-by-step panel does not press."""
    keys = plain_keys(parts)
    return any(combo <= keys for combo in BLOCKED_COMBOS)


def never(parts) -> bool:
    """A shortcut that is pressed for nobody, whoever asks."""
    keys = plain_keys(parts)
    return any(combo <= keys for combo in NEVER_COMBOS)


def keys(text: str) -> tuple[int, int]:
    """A shortcut written as "cmd+s" as (the key's number, the modifier marks). A modifier on its own is that key itself."""
    parts = [part.strip().lower() for part in str(text).split("+") if part.strip()]
    flags, code = 0, None
    for part in parts:
        if part in MODIFIERS:
            flags |= MODIFIERS[part][1]
        elif part in KEYCODES and code is None:
            code = KEYCODES[part]
        else:
            raise ValueError(f'JARVIS does not know the key "{part[:20]}" on a Mac.')
    if code is None:
        if not parts:
            raise ValueError("No key was named.")
        return MODIFIERS[parts[-1]][0], 0
    return code, flags


def describe(node: dict, frame=None) -> dict | None:
    """A control as the assistant is told about it: its kind, its name, where its middle is and how large it is. None
    for one that is not shown (no place, too small to see, or scrolled out of the window)."""
    place, size = node.get("position"), node.get("size")
    if not place or not size:
        return None
    width, height = round(size[0]), round(size[1])
    if width < 3 or height < 3:
        return None
    x, y = round(place[0] + size[0] / 2), round(place[1] + size[1] / 2)
    if frame and not (frame[0] - 1 <= x <= frame[0] + frame[2] + 1 and frame[1] - 1 <= y <= frame[1] + frame[3] + 1):
        return None
    kind = SUBROLES.get(node.get("subrole") or "") or ROLES.get(node.get("role") or "", "Custom")
    name = node.get("title") or node.get("description") or node.get("value") or node.get("placeholder") or ""
    return {"t": kind, "n": " ".join(str(name).split())[:80], "x": x, "y": y, "w": width, "h": height, "on": bool(node.get("enabled", True)),
            "secret": node.get("subrole") == "AXSecureTextField"}


def _real_mac():
    from jcc import macax
    return macax.mac()


class Windows:
    """The windows on this Mac, front to back. A window is known by macOS's own number for it. Where the Mac cannot be
    asked at all (no Mac, or its libraries will not load), there are simply no windows."""

    def __init__(self, mac=None, clock=time.monotonic):
        self._mac, self.clock = mac, clock
        self._seen: tuple[float, list[dict]] = (-1.0, [])
        self._titles: dict[int, tuple[float, list]] = {}

    @property
    def mac(self):
        if self._mac is None:
            self._mac = _real_mac()
        return self._mac

    def _title(self, row: dict) -> str:
        """A window's title with its app's name after it ("Notes - TextEdit"), as people say which window they mean. macOS
        gives other apps' titles only with Screen Recording allowed; without it, Accessibility is asked instead."""
        name, app = row.get("name") or "", row.get("app") or ""
        if not name:
            now = self.clock()
            kept = self._titles.get(row["pid"])
            if not kept or now - kept[0] > 1.0:
                try:
                    kept = (now, self.mac.titles(row["pid"]))
                except OSError:
                    kept = (now, [])
                self._titles[row["pid"]] = kept
            left, top, right, bottom = row["box"]
            for ident, frame, title in kept[1]:
                if ident == row["handle"] or (not ident and abs(frame[0] - left) <= 2 and abs(frame[1] - top) <= 2 and abs(frame[2] - (right - left)) <= 2):
                    name = title
                    break
        if name and app and app.lower() not in name.lower():
            return f"{name} - {app}"
        return name or app

    def all(self, fresh: bool = False) -> list[dict]:
        now = self.clock()
        if not fresh and 0 <= now - self._seen[0] < 0.25:
            return self._seen[1]
        try:
            rows = [{**row, "title": self._title(row)} for row in self.mac.rows()]
        except OSError:
            rows = []
        rows = [row for row in rows if row["title"]]
        self._seen = (now, rows)
        return rows

    def _row(self, handle: int) -> dict | None:
        return next((row for row in self.all() if row["handle"] == handle), None) if handle else None

    def foreground(self) -> int:
        rows = self.all()
        if not rows:
            return 0
        try:
            pid = self.mac.front_pid()
        except OSError:
            return 0
        return next((row["handle"] for row in rows if row["pid"] == pid), 0)

    def title(self, handle: int) -> str:
        row = self._row(handle)
        if row:
            return row["title"]
        if not handle:
            return ""
        try:
            row = next((r for r in self.mac.rows(every=True) if r["handle"] == handle), None)
        except OSError:
            row = None
        return self._title(row) if row else ""

    def exists(self, handle: int) -> bool:
        if not handle:
            return False
        try:
            return any(row["handle"] == handle for row in self.mac.rows(every=True))
        except OSError:
            return False

    def focus(self, handle: int) -> bool:
        try:
            self.mac.raise_window(handle)
        except OSError:
            return False
        for _ in range(8):
            time.sleep(0.05)
            self._seen = (-1.0, [])
            if self.foreground() == handle:
                return True
        return False

    def at(self, x: int, y: int) -> int:
        for row in self.all():
            left, top, right, bottom = row["box"]
            if left <= x < right and top <= y < bottom:
                return row["handle"]
        return 0

    def process(self, handle: int) -> int:
        row = self._row(handle)
        return row["pid"] if row else 0

    def middle(self, handle: int):
        row = self._row(handle)
        return ((row["box"][0] + row["box"][2]) // 2, (row["box"][1] + row["box"][3]) // 2) if row else None

    def box(self, handle: int):
        row = self._row(handle)
        return tuple(row["box"]) if row else None

    def app(self, handle: int) -> str:
        row = self._row(handle)
        return row["app"].lower() if row else ""


class Controls:
    """A window's buttons, boxes and links by name, as the Mac's Accessibility interface lists them. It takes the same
    requests and gives the same answers as Uia in jcc/uia.py. Every request runs on a thread of its own, so a window
    that stops answering can never hang JARVIS."""

    def __init__(self, mac=None):
        self._mac = mac
        self.lock = threading.Lock()

    @property
    def mac(self):
        if self._mac is None:
            self._mac = _real_mac()
        return self._mac

    def call(self, payload: dict, timeout: float = 10.0) -> dict:
        box: dict = {}

        def work():
            try:
                with self.lock:
                    box["out"] = self.run(payload)
            except BaseException as problem:  # noqa: BLE001 - handed to the caller below
                box["problem"] = problem
        worker = threading.Thread(target=work, daemon=True, name="window-controls")
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            raise TimeoutError("the window did not answer")
        problem = box.get("problem")
        if problem is not None:
            if type(problem).__name__ == "NotAllowed":                 # macOS has not allowed it yet: say so in its own words
                return {"error": str(problem), "say": True}
            if isinstance(problem, (OSError, ValueError)):
                raise problem
            raise OSError(str(problem))
        return box["out"]

    def close(self) -> None:
        pass

    def _items(self, walked: dict, limit: int, texts: bool = False) -> tuple[list[dict], list[dict]]:
        items, nodes = [], []
        for node in walked["nodes"]:
            if len(items) >= limit:
                break
            item = describe(node, walked.get("frame"))
            # (texts: short pieces of plain text are listed too, for finding a row of a page by its heading)
            if item and (item["n"] or item["t"] in _FIELDS) and (item["t"] not in _PLAIN or (texts and item["t"] == "Text" and 2 < len(item["n"]) <= 60)):
                items.append(item)
                nodes.append(node)
        mark_pages(items)
        return items, nodes

    def run(self, payload: dict) -> dict:
        op, mac = payload.get("op"), self.mac
        if op == "list":
            walked = mac.walk(int(payload["h"]))
            try:
                items, _ = self._items(walked, int(payload.get("max", 140)), payload.get("texts") is True)
                return {"title": walked.get("title") or "", "items": items}
            finally:
                mac.done(walked)
        if op == "at":
            found = mac.at(float(payload["x"]), float(payload["y"]))
            try:
                nodes = found["nodes"]
                item = describe(nodes[0]) if nodes else None
                if item and not item["n"] and len(nodes) > 1:
                    above = describe(nodes[1])
                    if above and above["n"] and above["t"] in _PRESSABLE:
                        item = above
                return {"item": item}
            finally:
                mac.release(found.get("keep"))
        if op in ("find", "press", "set"):
            walked = mac.walk(int(payload["h"]))
            try:
                items, nodes = self._items(walked, 800)
                index = choose(items, str(payload.get("name", "")), op == "set")
                if index < 0:
                    return {"item": None}
                item, node = items[index], nodes[index]
                if op == "find":
                    return {"item": item}
                if op == "press":
                    return {"item": item, "how": HOW.get(item["t"], "pressed") if mac.press(node["el"]) else "click"}
                if item["secret"]:
                    return {"item": item, "how": "secret"}
                # A box of a web page is typed into, key by key: a page only notices text that arrives that way.
                if not item.get("page") and item["t"] != "Document" and mac.fill(node["el"], str(payload.get("text", ""))):
                    return {"item": item, "how": "set"}
                mac.focus(node["el"])
                return {"item": item, "how": "focus"}
            finally:
                mac.done(walked)
        return {"ok": True}


def raw_screens(mac=None) -> list[dict]:
    """Every screen as jcc/screens.py describes one. A Mac's menu bar is on every screen, so the usable part starts below it."""
    try:
        found = (mac or _real_mac()).displays()
    except OSError:
        return []
    bar = 25
    return [{**s, "work": (s["left"], s["top"] + bar, s["left"] + s["width"], s["top"] + s["height"]), "scale": 1.0, "name": f"display {s['handle']}"}
            for s in found]


def window_box(handle: int, mac=None) -> tuple[int, int, int, int] | None:
    """Where a window is: (left, top, right, bottom)."""
    try:
        row = next((r for r in (mac or _real_mac()).rows(every=True) if r["handle"] == handle), None)
    except OSError:
        return None
    return tuple(row["box"]) if row else None


def move_window(handle: int, target: dict, found: list[dict], mac=None) -> bool:
    """Put a window on another screen, with the same share of the screen and in the same place on it."""
    from jcc import screens
    box = window_box(handle, mac)
    here = screens.holding_box(found, box) if box else None
    if not box or not here or not target:
        return False
    if here["handle"] == target["handle"]:
        return True
    left, top, width, height = screens.fit(box, here, target)
    try:
        return bool((mac or _real_mac()).place_window(handle, int(left), int(top), int(width), int(height)))
    except OSError:
        return False


def png_size(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise OSError("The picture of the screen could not be read.")
    return struct.unpack(">II", data[16:24])


def _shoot(what: list[str], widest: int, run=None) -> tuple[int, int, bytes]:
    """A picture (PNG) taken by the Mac's own screencapture (`what` says of what) and made no wider than `widest` by its
    own sips. Nothing is kept: the file is in a folder of its own that is removed straight away."""
    run = run or subprocess.run
    folder = Path(tempfile.mkdtemp(prefix="jarvis-shot-"))
    path = folder / "shot.png"
    try:
        done = run(["screencapture", "-x", *what, "-t", "png", str(path)], capture_output=True, timeout=25, stdin=subprocess.DEVNULL)
        if done.returncode != 0 or not path.is_file() or path.stat().st_size < 50:
            raise OSError("The Mac did not give a picture of the screen.")
        if png_size(path.read_bytes())[0] > max(1, int(widest)):
            run(["sips", "--resampleWidth", str(max(1, int(widest))), str(path)], capture_output=True, timeout=25, stdin=subprocess.DEVNULL)
        data = path.read_bytes()
        wide, high = png_size(data)
        return wide, high, data
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def grab(left: int, top: int, width: int, height: int, max_width: int = SHOT_WIDTH, run=None) -> tuple[int, int, bytes]:
    """A picture of one part of the desktop (given in points; a screen to the left of the main one has negative
    positions), no wider than max_width and never wider than the part is in points."""
    return _shoot([f"-R{int(left)},{int(top)},{int(width)},{int(height)}"], min(int(max_width), int(width)), run)


def _must_see(mac) -> None:
    from jcc import macax
    if not mac.sees_screen():
        mac.ask_screen()                               # macOS shows its own question once, and lists JARVIS under Screen Recording
        raise ValueError(macax.SCREEN)


def picture_of_window(handle: int, mac=None, run=None) -> tuple[int, int, bytes]:
    """A picture of one window, even when other windows cover it."""
    mac = mac or _real_mac()
    if not any(row["handle"] == handle for row in mac.rows()):
        raise ValueError("That window is closed or minimised. Open it first, then try again.")
    _must_see(mac)
    return _shoot([f"-l{int(handle)}", "-o"], 1920, run)        # (-o: without the shadow around it)


def picture_of_screen(screen: int = 0, hide: int = 0, mac=None, run=None) -> tuple[int, int, bytes]:
    """A picture of one whole screen: the one with this number, else the one the window `hide` is on, else the main one."""
    from jcc import screens
    mac = mac or _real_mac()
    found = screens.number(raw_screens(mac))
    box = window_box(hide, mac) if hide else None
    chosen = next((s for s in found if s["number"] == screen), None) or (screens.holding_box(found, box) if box else None) or         next((s for s in found if s["main"]), found[0] if found else None)
    if not chosen:
        raise ValueError("The Mac did not say which screens it has.")
    _must_see(mac)
    return grab(chosen["left"], chosen["top"], chosen["width"], chosen["height"], 1920, run)


class Desktop:
    """The Mac's screen, pointer and keyboard, with the same calls as the Windows Desktop in jcc/computer.py."""

    def __init__(self, mac=None, run=None, windows=None, screens=None):
        self._mac, self.run, self._windows, self._screens = mac, run, windows, screens
        # The screen that pictures and positions refer to: where its corner is on the whole desktop, how many points one
        # picture pixel stands for, its number, and how many screens there are.
        self.scale, self.origin, self.screen, self.count, self.all = 1.0, (0, 0), 1, 1, []
        self.size = (SHOT_WIDTH, 800)

    @property
    def mac(self):
        if self._mac is None:
            self._mac = _real_mac()
        return self._mac

    @property
    def windows(self) -> Windows:
        if self._windows is None:
            self._windows = Windows(self.mac)
        return self._windows

    def window_title(self) -> str:
        return self.windows.title(self.windows.foreground())

    def _found(self) -> list[dict]:
        from jcc import screens
        return screens.number(self._screens() if self._screens else raw_screens(self.mac))

    def look(self, window: int = 0, screen: int = 0) -> dict | None:
        """Choose the screen that pictures and positions refer to from now on: the one with this number; else the one
        showing this window; else the one showing the window in front. Returns it (None if the Mac will not say)."""
        from jcc import screens
        found = self._found()
        if not found:
            self.origin, self.scale, self.screen, self.count, self.all = (0, 0), 1.0, 1, 1, []
            return None
        chosen = next((s for s in found if s["number"] == screen), None) if screen else None
        if chosen is None:
            box = self.windows.box(int(window or self.windows.foreground() or 0))
            chosen = (screens.holding_box(found, box) if box else None) or found[0]
        self.origin, self.scale = (chosen["left"], chosen["top"]), max(1.0, chosen["width"] / SHOT_WIDTH)
        self.screen, self.count, self.all = chosen["number"], len(found), found
        self.size = (chosen["width"], chosen["height"])
        return chosen

    def measure(self) -> float:
        self.look()
        return self.scale

    def real(self, x, y) -> tuple[int, int]:
        """A point of the picture, as a true position on the whole desktop."""
        return round(self.origin[0] + float(x) * self.scale), round(self.origin[1] + float(y) * self.scale)

    def shown(self, x, y) -> tuple[float, float]:
        """A true position on the desktop, as a point of the picture of the screen being looked at."""
        return (float(x) - self.origin[0]) / self.scale, (float(y) - self.origin[1]) / self.scale

    def capture(self, window: int = 0, screen: int = 0) -> tuple[int, int, bytes]:
        """A picture of one whole screen (see look), no wider than SHOT_WIDTH."""
        from jcc import macax
        chosen = self.look(window, screen)
        if chosen is None:
            raise OSError("The Mac did not say which screens it has.")
        if not self.mac.sees_screen():
            self.mac.ask_screen()                      # macOS shows its own question once, and lists JARVIS under Screen Recording
            raise macax.NotAllowed(macax.SCREEN)
        return grab(chosen["left"], chosen["top"], chosen["width"], chosen["height"], round(chosen["width"] / self.scale), self.run)

    def move_pointer(self, x, y) -> None:
        """Put the pointer at a true position (the wheel turns whatever is under it)."""
        self.mac.move(float(x), float(y))

    def perform(self, step: dict) -> None:
        kind, mac = step["action"], self.mac
        if kind in ("click", "double_click", "right_click"):
            x, y = self.real(step["x"], step["y"])
            mac.click(x, y, right=kind == "right_click", double=kind == "double_click")
        elif kind == "type":
            mac.type_text(step["text"])
        elif kind == "key":
            parts = [part.strip().lower() for part in str(step["keys"]).split("+") if part.strip()]
            if never(parts):
                raise ValueError("That shortcut is reserved for macOS: it logs out, locks the Mac or force-quits.")
            code, flags = keys(step["keys"])
            mac.key(code, flags)
        elif kind == "scroll":
            mac.scroll(int(step["amount"]) * 3)
        elif kind == "wait":
            time.sleep(1.5)


def permissions(mac=None) -> dict:
    """What macOS has allowed: {"accessibility": bool, "screen": bool}. None for one that cannot be asked."""
    try:
        mac = mac or _real_mac()
        return {"accessibility": bool(mac.trusted()), "screen": bool(mac.sees_screen())}
    except OSError:
        return {"accessibility": None, "screen": None}


SETTINGS_PANES = {"accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
                  "screen": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
                  "microphone": "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"}


def open_settings(which: str, run=None) -> bool:
    """Open the page of System Settings where a permission is switched on. Only the three pages named above."""
    address = SETTINGS_PANES.get(str(which))
    if not address:
        return False
    (run or subprocess.Popen)(["open", address], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True
