"""Reading and pressing the controls of a window (Windows UI Automation), without any extra process.

This is how JARVIS presses a button "by name": Windows tells it which buttons, boxes, menus and links
a window has and where they are, and can press or fill them directly. It is faster and far more
exact than looking at a picture of the screen.
"""
from __future__ import annotations

import ctypes
import os
import queue
import re
import threading
import unicodedata
from ctypes import wintypes

from jcc.winctl import _guid, _method

_CLSID, _IID = "{ff48dba4-60ef-4201-aa87-54103eef594e}", "{30cbe57d-d9d0-452a-ab13-7ac5ac4825ee}"
_PATTERNS = {"invoke": (10000, "{fb377fbe-8ea6-46d5-9c73-6499642d3059}", 3, "pressed"),
             "value": (10002, "{a94cd8b1-0844-4cd6-9d2d-640537ab39e9}", 3, "set"),
             "toggle": (10015, "{94cf8058-9b8d-4ab9-8bfd-4cd0a33c8c70}", 3, "switched"),
             "select": (10010, "{a8efa66a-0fda-421a-9194-38021f3578ea}", 3, "selected"),
             "expand": (10005, "{619be086-1f4e-4ee4-bafa-210128738730}", 3, "opened"),
             "legacy": (10018, "{828055ad-355b-4435-86d5-3b51c14a9b1b}", 4, "pressed")}
TYPES = {50000: "Button", 50001: "Calendar", 50002: "CheckBox", 50003: "ComboBox", 50004: "Edit", 50005: "Hyperlink", 50006: "Image",
         50007: "ListItem", 50008: "List", 50009: "Menu", 50010: "MenuBar", 50011: "MenuItem", 50012: "ProgressBar", 50013: "RadioButton",
         50014: "ScrollBar", 50015: "Slider", 50016: "Spinner", 50017: "StatusBar", 50018: "Tab", 50019: "TabItem", 50020: "Text",
         50021: "ToolBar", 50022: "ToolTip", 50023: "Tree", 50024: "TreeItem", 50025: "Custom", 50026: "Group", 50027: "Thumb",
         50028: "DataGrid", 50029: "DataItem", 50030: "Document", 50031: "SplitButton", 50032: "Window", 50033: "Pane", 50034: "Header",
         50035: "HeaderItem", 50036: "Table", 50037: "TitleBar", 50038: "Separator", 50039: "SemanticZoom", 50040: "AppBar"}
_PLAIN = {"Window", "Pane", "Group", "Custom", "TitleBar", "ScrollBar", "Thumb", "Separator", "Image", "ToolBar", "MenuBar", "List", "Tree",
          "Table", "Tab", "Header", "StatusBar", "DataGrid", "Text", "ToolTip", "ProgressBar", "Menu", "SemanticZoom", "AppBar"}
_FIELDS = {"Edit", "ComboBox", "CheckBox", "Document", "RadioButton", "Slider", "Spinner"}
_PICKED = {"ListItem", "TreeItem", "TabItem", "RadioButton", "DataItem"}
_PRESSABLE = {"Button", "MenuItem", "Hyperlink", "TabItem", "ListItem", "CheckBox", "RadioButton", "SplitButton", "Edit", "ComboBox"}
# Where each fact lives in the element interface: (live, remembered-from-one-big-read)
_NAME, _TYPE, _ENABLED, _PASSWORD, _OFFSCREEN, _RECT = (23, 55), (21, 53), (28, 60), (35, 67), (38, 70), (43, 75)


def _release(pointer) -> None:
    if pointer:
        _method(pointer, 2)(pointer)


def plain(name: str) -> str:
    """A name as people say it: lower case, no accents, no punctuation or invisible marks ("Brooklyn Nine-Nine" -> "brooklyn nine nine")."""
    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(c for c in text if not unicodedata.combining(c) and unicodedata.category(c) not in ("Cf", "Cc"))
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower().replace("&", " and ")).split())


def mark_pages(items: list[dict]) -> None:
    """Mark the controls that belong to a web page or a document (item["page"] = True), as opposed to the program's own bars.

    A browser lists its toolbar first and then the page, as one large "Document". What lies inside that and comes after it is the page."""
    areas = []
    for item in items:
        if item["t"] == "Document" and item.get("w", 0) >= 300 and item.get("h", 0) >= 200:
            areas.append((item["x"] - item["w"] // 2, item["y"] - item["h"] // 2, item["x"] + item["w"] // 2, item["y"] + item["h"] // 2))
            continue
        if any(left <= item["x"] <= right and top <= item["y"] <= bottom for left, top, right, bottom in areas):
            item["page"] = True


def choose(items: list[dict], name: str, fields_only: bool = False) -> int:
    """Which control a name means: the index of the best match, or -1.

    An exact name beats a name that starts with the words, which beats a name that contains them; said loosely
    ("brooklyn nine nine") counts a little less than written exactly. Among equals, something that can be pressed wins,
    and a control of the page wins over the program's own button of the same name."""
    low, loose, best, score = " ".join(str(name).lower().split()), plain(name), -1, 0
    for index, item in enumerate(items):
        if not item["on"] or (fields_only and item["t"] not in ("Edit", "ComboBox", "Document")):
            continue
        label = item["n"].lower()
        points = 16 if low and label == low else 12 if low and label.startswith(low) else 8 if low and low in label else 4 if not low and fields_only else 0
        if not points and loose:
            said = plain(item["n"])
            points = 14 if said == loose else 10 if said.startswith(loose + " ") else 6 if (" " + loose + " ") in (" " + said + " ") else 0
        if not points:
            continue
        points += (2 if item["t"] in _PRESSABLE else 0) + (1 if item.get("page") else 0)
        if points > score:
            best, score = index, points
    return best


class Uia:
    """All calls run on a worker thread, so a window that stops answering can never hang JARVIS."""

    def __init__(self):
        self.lock = threading.Lock()
        self.jobs: queue.Queue | None = None
        self.worker: threading.Thread | None = None

    def call(self, payload: dict, timeout: float = 10.0) -> dict:
        if os.name != "nt":
            raise OSError("Windows only")
        with self.lock:
            if not self.worker or not self.worker.is_alive():
                self.jobs = queue.Queue()
                self.worker = threading.Thread(target=self._work, args=(self.jobs,), daemon=True, name="window-controls")
                self.worker.start()
            box = {"done": threading.Event(), "out": {}}
            jobs = self.jobs
            jobs.put((payload, box))
        if not box["done"].wait(timeout):
            with self.lock:
                if self.jobs is jobs:        # that worker is stuck inside a window; retire it and start afresh next time
                    jobs.put(None)
                    self.worker = self.jobs = None
            raise TimeoutError("the window did not answer")
        return box["out"]

    def close(self) -> None:
        with self.lock:
            if self.jobs:
                self.jobs.put(None)
            self.worker = self.jobs = None

    # ------------------------------------------------------------------ worker
    def _work(self, jobs: queue.Queue) -> None:
        # This thread asks Windows where controls are. It is given true positions on every screen (jcc/screens.py);
        # without this, a control on a screen whose scaling differs from the main one's is reported somewhere else.
        try:
            ctypes.windll.user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            ctypes.windll.user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
            ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            pass
        ole32 = ctypes.windll.ole32
        ole32.CoInitializeEx(None, 0)
        ole32.CoCreateInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        ole32.CoCreateInstance.restype = ctypes.c_long
        root = ctypes.c_void_p()
        failed = ole32.CoCreateInstance(ctypes.byref(_guid(_CLSID)), None, 1, ctypes.byref(_guid(_IID)), ctypes.byref(root)) or not root
        session = None if failed else _Session(root)
        while True:
            job = jobs.get()
            if job is None:
                break
            payload, box = job
            try:
                box["out"] = {"error": "Windows accessibility is not available."} if failed else session.run(payload)
            except Exception as problem:  # noqa: BLE001 - whatever a window does, the caller gets an answer
                box["out"] = {"error": str(problem)[:200] or "failed"}
            box["done"].set()
        _release(root)


class _Session:
    def __init__(self, root):
        self.root = root
        self.oleaut = ctypes.windll.oleaut32
        self.oleaut.SysAllocString.restype = ctypes.c_void_p
        self.oleaut.SysAllocString.argtypes = [ctypes.c_wchar_p]
        self.oleaut.SysFreeString.argtypes = [ctypes.c_void_p]

    # ------------------------------------------------------------------ reading facts
    def _text(self, element, index: int) -> str:
        out = ctypes.c_void_p()
        if _method(element, index, ctypes.POINTER(ctypes.c_void_p))(element, ctypes.byref(out)) or not out.value:
            return ""
        try:
            return ctypes.wstring_at(out.value)
        finally:
            self.oleaut.SysFreeString(out)

    def _number(self, element, index: int) -> int:
        out = ctypes.c_int()
        return 0 if _method(element, index, ctypes.POINTER(ctypes.c_int))(element, ctypes.byref(out)) else out.value

    def _describe(self, element, which: int) -> dict | None:
        rect = wintypes.RECT()
        if _method(element, _RECT[which], ctypes.POINTER(wintypes.RECT))(element, ctypes.byref(rect)):
            return None
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width < 3 or height < 3 or self._number(element, _OFFSCREEN[which]):
            return None
        return {"t": TYPES.get(self._number(element, _TYPE[which]), "Custom"), "n": " ".join(self._text(element, _NAME[which]).split())[:80],
                "x": rect.left + width // 2, "y": rect.top + height // 2, "w": width, "h": height, "on": bool(self._number(element, _ENABLED[which])),
                "secret": bool(self._number(element, _PASSWORD[which]))}

    def _window(self, handle: int):
        element = ctypes.c_void_p()
        if _method(self.root, 6, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(self.root, ctypes.c_void_p(handle), ctypes.byref(element)) or not element:
            raise OSError("That window is gone.")
        return element

    def _controls(self, handle: int, limit: int, texts: bool = False) -> tuple[str, list[dict], list]:
        """(window title, descriptions, the matching elements). The caller releases the elements."""
        window = self._window(handle)
        request, condition, found = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        items, elements = [], []
        try:
            title = self._text(window, _NAME[0])
            if _method(self.root, 20, ctypes.POINTER(ctypes.c_void_p))(self.root, ctypes.byref(request)) or not request:
                raise OSError("no cache")
            for prop in (30005, 30003, 30001, 30010, 30022, 30019):
                _method(request, 3, ctypes.c_int)(request, prop)
            if _method(self.root, 18, ctypes.POINTER(ctypes.c_void_p))(self.root, ctypes.byref(condition)) or not condition:
                raise OSError("no condition")
            if _method(window, 8, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(
                    window, 4, condition, request, ctypes.byref(found)) or not found:
                raise OSError("The window did not list its controls.")
            count = ctypes.c_int()
            _method(found, 3, ctypes.POINTER(ctypes.c_int))(found, ctypes.byref(count))
            for index in range(min(count.value, 6000)):
                element = ctypes.c_void_p()
                if _method(found, 4, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(found, index, ctypes.byref(element)) or not element:
                    continue
                described = self._describe(element, 1) if len(items) < limit else None
                # (texts: short pieces of plain text are listed too, for finding a row of a page by its heading)
                if described and (described["n"] or described["t"] in _FIELDS) and (described["t"] not in _PLAIN or
                                                                                   (texts and described["t"] == "Text" and 2 < len(described["n"]) <= 60)):
                    items.append(described)
                    elements.append(element)
                else:
                    _release(element)
            mark_pages(items)
            return title, items, elements
        finally:
            for pointer in (found, condition, request, window):
                _release(pointer)

    # ------------------------------------------------------------------ choosing and acting
    @staticmethod
    def _choose(items: list[dict], name: str, fields_only: bool) -> int:
        return choose(items, name, fields_only)

    def _pattern(self, element, name: str):
        ident, iid, _, _ = _PATTERNS[name]
        out = ctypes.c_void_p()
        if _method(element, 14, ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(element, ident, ctypes.byref(_guid(iid)), ctypes.byref(out)):
            return None
        return out if out else None

    def _press(self, element, kind: str) -> str:
        for name in (["select"] if kind in _PICKED else []) + ["invoke", "toggle", "select", "expand", "legacy"]:
            pattern = self._pattern(element, name)
            if not pattern:
                continue
            try:
                if _method(pattern, _PATTERNS[name][2])(pattern) == 0:
                    return _PATTERNS[name][3]
            finally:
                _release(pattern)
        return "click"

    def _fill(self, element, kind: str, text: str) -> str:
        pattern = None if kind == "Document" else self._pattern(element, "value")
        if pattern:
            try:
                read_only = ctypes.c_int()
                _method(pattern, 5, ctypes.POINTER(ctypes.c_int))(pattern, ctypes.byref(read_only))
                if not read_only.value:
                    value = self.oleaut.SysAllocString(text)
                    try:
                        if _method(pattern, 3, ctypes.c_void_p)(pattern, ctypes.c_void_p(value)) == 0:
                            return "set"
                    finally:
                        self.oleaut.SysFreeString(ctypes.c_void_p(value))
            finally:
                _release(pattern)
        _method(element, 3)(element)   # put the cursor there; the caller types
        return "focus"

    def run(self, payload: dict) -> dict:
        op = payload.get("op")
        if op == "list":
            title, items, elements = self._controls(int(payload["h"]), int(payload.get("max", 140)), payload.get("texts") is True)
            for element in elements:
                _release(element)
            return {"title": title, "items": items}
        if op == "at":
            element, walker, parent = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
            point = wintypes.POINT(int(payload["x"]), int(payload["y"]))
            if _method(self.root, 7, wintypes.POINT, ctypes.POINTER(ctypes.c_void_p))(self.root, point, ctypes.byref(element)) or not element:
                return {"item": None}
            try:
                item = self._describe(element, 0)
                if item and not item["n"] and not _method(self.root, 14, ctypes.POINTER(ctypes.c_void_p))(self.root, ctypes.byref(walker)) and walker:
                    if not _method(walker, 3, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(walker, element, ctypes.byref(parent)) and parent:
                        above = self._describe(parent, 0)
                        if above and above["n"] and above["t"] in _PRESSABLE:
                            item = above
                return {"item": item}
            finally:
                for pointer in (parent, walker, element):
                    _release(pointer)
        if op in ("find", "press", "set"):
            _, items, elements = self._controls(int(payload["h"]), 800)
            try:
                index = self._choose(items, str(payload.get("name", "")), op == "set")
                if index < 0:
                    return {"item": None}
                item = items[index]
                if op == "find":
                    return {"item": item}
                if op == "press":
                    return {"item": item, "how": self._press(elements[index], item["t"])}
                if item["secret"]:
                    return {"item": item, "how": "secret"}
                return {"item": item, "how": self._fill(elements[index], item["t"], str(payload.get("text", "")))}
            finally:
                for element in elements:
                    _release(element)
        return {"ok": True}
