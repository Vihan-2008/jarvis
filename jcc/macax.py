"""macOS itself, reached directly: the windows on the screen, the buttons and boxes inside a window (the Accessibility
interface), the pointer, the keys and the screens.

This is the Mac's counterpart of what jcc/winctl.py and jcc/uia.py reach on Windows. It uses only what macOS ships:
ApplicationServices (Accessibility and Quartz events) and CoreFoundation, called through ctypes. Nothing is loaded until
it is first used, so this file can be imported on any system; jcc/macdesk.py holds everything that can be decided
without a Mac, and tests give it a stand-in for this file.

macOS gives two permissions to the app JARVIS was started from (JARVIS.app, or Terminal), under System Settings,
Privacy & Security:
- Accessibility: reading a window's controls, pressing them, typing and clicking.
- Screen Recording: pictures of the screen, and the titles of other apps' windows.
"""
from __future__ import annotations

import ctypes
import threading
import time

UTF8 = 0x08000100
# What is asked of every control in one go. (Its value is not: a text box's value is the whole document.)
ATTRIBUTES = ("AXRole", "AXSubrole", "AXTitle", "AXDescription", "AXPosition", "AXSize", "AXEnabled", "AXChildren", "AXPlaceholderValue")
ROLE, SUBROLE, TITLE, DESCRIPTION, POSITION, SIZE, ENABLED, CHILDREN, PLACEHOLDER = range(9)
# Controls whose insides only repeat their name (the picture and the words on a button).
LEAVES = frozenset({"AXButton", "AXLink", "AXCheckBox", "AXRadioButton", "AXPopUpButton", "AXMenuButton", "AXStaticText", "AXImage", "AXTextField",
                    "AXSlider", "AXIncrementor", "AXDisclosureTriangle", "AXComboBox", "AXScrollBar", "AXValueIndicator"})
# The modifier keys: (the mark each puts on what is pressed while it is down, the key's own number). Command, Shift, Option, Control.
MODIFIER_KEYS = ((1 << 20, 55), (1 << 17, 56), (1 << 19, 58), (1 << 18, 59))
NOT_ALLOWED = -25211             # kAXErrorAPIDisabled: Accessibility has not been allowed
ACCESSIBILITY = ("macOS has not yet allowed JARVIS to control other apps. Open System Settings, Privacy & Security, Accessibility, "
                 "and switch on JARVIS (or Terminal, if you started it from there). Then try again.")
SCREEN = ("macOS has not yet allowed JARVIS to see the screen. Open System Settings, Privacy & Security, Screen & System Audio Recording, "
          "and switch on JARVIS (or Terminal, if you started it from there). Then try again.")


NO_BRIGHTNESS = "This screen's brightness cannot be changed from here. It works on a Mac's own screen; use the monitor's buttons otherwise."


class NotAllowed(OSError):
    """macOS has not given JARVIS the permission this needs. The message says which, and where to switch it on."""


class CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class CGRect(ctypes.Structure):
    _fields_ = [("origin", CGPoint), ("size", CGSize)]


class _Libraries:
    """The two system libraries, with every function's arguments declared (on Apple's own chips a wrong guess is a crash)."""

    def __init__(self):
        v, i32, u32, f32, u8 = ctypes.c_void_p, ctypes.c_int32, ctypes.c_uint32, ctypes.c_float, ctypes.c_ubyte
        long, out = ctypes.c_long, ctypes.POINTER(ctypes.c_void_p)
        cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        app = ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        self.cf, self.app = cf, app

        def declare(library, name, result, *arguments, needed=True):
            try:
                function = getattr(library, name)
            except AttributeError:
                if needed:
                    raise
                return None
            function.restype, function.argtypes = result, list(arguments)
            setattr(self, name.lstrip("_"), function)
            return function

        for name in ("CFStringGetTypeID", "CFArrayGetTypeID", "CFBooleanGetTypeID", "CFNumberGetTypeID"):
            declare(cf, name, ctypes.c_ulong)
        declare(cf, "CFRelease", None, v)
        declare(cf, "CFRetain", v, v)
        declare(cf, "CFGetTypeID", ctypes.c_ulong, v)
        declare(cf, "CFStringCreateWithBytes", v, v, ctypes.c_char_p, long, u32, u8)
        declare(cf, "CFStringGetLength", long, v)
        declare(cf, "CFStringGetMaximumSizeForEncoding", long, long, u32)
        declare(cf, "CFStringGetCString", u8, v, ctypes.c_char_p, long, u32)
        declare(cf, "CFArrayGetCount", long, v)
        declare(cf, "CFArrayGetValueAtIndex", v, v, long)
        declare(cf, "CFArrayCreate", v, v, out, long, v)
        declare(cf, "CFBooleanGetValue", u8, v)
        declare(cf, "CFNumberGetValue", u8, v, long, v)
        declare(cf, "CFDictionaryGetValue", v, v, v)
        declare(cf, "CFDictionaryCreate", v, v, out, out, long, v, v)
        self.true = v.in_dll(cf, "kCFBooleanTrue")
        self.false = v.in_dll(cf, "kCFBooleanFalse")
        self.array_callbacks = ctypes.addressof(ctypes.c_char.in_dll(cf, "kCFTypeArrayCallBacks"))
        self.key_callbacks = ctypes.addressof(ctypes.c_char.in_dll(cf, "kCFTypeDictionaryKeyCallBacks"))
        self.value_callbacks = ctypes.addressof(ctypes.c_char.in_dll(cf, "kCFTypeDictionaryValueCallBacks"))

        declare(app, "AXIsProcessTrusted", u8)
        declare(app, "AXIsProcessTrustedWithOptions", u8, v)
        declare(app, "AXUIElementGetTypeID", ctypes.c_ulong)
        declare(app, "AXValueGetTypeID", ctypes.c_ulong)
        declare(app, "AXUIElementCreateApplication", v, i32)
        declare(app, "AXUIElementCreateSystemWide", v)
        declare(app, "AXUIElementCopyAttributeValue", i32, v, v, out)
        declare(app, "AXUIElementCopyMultipleAttributeValues", i32, v, v, u32, out)
        declare(app, "AXUIElementPerformAction", i32, v, v)
        declare(app, "AXUIElementSetAttributeValue", i32, v, v, v)
        declare(app, "AXUIElementIsAttributeSettable", i32, v, v, ctypes.POINTER(u8))
        declare(app, "AXUIElementCopyElementAtPosition", i32, v, f32, f32, out)
        declare(app, "AXUIElementGetPid", i32, v, ctypes.POINTER(i32))
        declare(app, "AXUIElementSetMessagingTimeout", i32, v, f32)
        declare(app, "AXValueGetType", i32, v)
        declare(app, "AXValueGetValue", u8, v, i32, v)
        declare(app, "AXValueCreate", v, i32, v)
        # (Which window an Accessibility element is: not a published function, but one every window tool on a Mac relies
        # on. Where it is missing, a window is matched by its place and size instead.)
        declare(app, "_AXUIElementGetWindow", i32, v, ctypes.POINTER(u32), needed=False)
        self.trusted_prompt = v.in_dll(app, "kAXTrustedCheckOptionPrompt")

        declare(app, "CGWindowListCopyWindowInfo", v, u32, u32)
        declare(app, "CGRectMakeWithDictionaryRepresentation", u8, v, ctypes.POINTER(CGRect))
        declare(app, "CGMainDisplayID", u32)
        declare(app, "CGGetActiveDisplayList", i32, u32, ctypes.POINTER(u32), ctypes.POINTER(u32))
        declare(app, "CGDisplayBounds", CGRect, u32)
        declare(app, "CGDisplayPixelsWide", ctypes.c_size_t, u32)
        declare(app, "CGDisplayIsBuiltin", u32, u32)
        declare(app, "CGEventCreate", v, v)
        declare(app, "CGEventGetLocation", CGPoint, v)
        declare(app, "CGEventCreateMouseEvent", v, v, u32, CGPoint, u32)
        declare(app, "CGEventCreateKeyboardEvent", v, v, ctypes.c_uint16, u8)
        declare(app, "CGEventCreateScrollWheelEvent2", v, v, u32, u32, i32, i32, i32)
        declare(app, "CGEventSetIntegerValueField", None, v, u32, ctypes.c_int64)
        declare(app, "CGEventSetFlags", None, v, ctypes.c_uint64)
        declare(app, "CGEventKeyboardSetUnicodeString", None, v, ctypes.c_ulong, ctypes.POINTER(ctypes.c_uint16))
        declare(app, "CGEventPost", None, u32, v)
        declare(app, "CGEventSourceKeyState", u8, i32, ctypes.c_uint16)
        for name in ("CGPreflightScreenCaptureAccess", "CGRequestScreenCaptureAccess", "CGPreflightPostEventAccess", "CGRequestPostEventAccess"):
            declare(app, name, u8, needed=False)
        self.kinds = {"string": self.CFStringGetTypeID(), "array": self.CFArrayGetTypeID(), "boolean": self.CFBooleanGetTypeID(),
                      "number": self.CFNumberGetTypeID(), "element": self.AXUIElementGetTypeID(), "value": self.AXValueGetTypeID()}


_loaded: _Libraries | None = None
_loading = threading.Lock()


def _lib() -> _Libraries:
    global _loaded
    if _loaded is None:
        with _loading:
            if _loaded is None:
                _loaded = _Libraries()
    return _loaded


class Mac:
    """Everything jcc/macdesk.py asks of the Mac. One per process is enough; every call may come from any thread."""

    def __init__(self):
        self.lib = _lib()
        self._names: dict[str, int] = {}
        self._lock = threading.Lock()
        self._system = None
        self._attributes = None
        self._eased: set[int] = set()

    # ------------------------------------------------------------------ CoreFoundation values
    def _string(self, text: str) -> int:
        """A new CFString (the caller releases it)."""
        data = str(text).encode("utf-8", "replace")
        return self.lib.CFStringCreateWithBytes(None, data, len(data), UTF8, 0)

    def _name(self, text: str) -> int:
        """The CFString for an attribute's or an action's name. Made once and kept."""
        with self._lock:
            if text not in self._names:
                self._names[text] = self._string(text)
            return self._names[text]

    def _text(self, ref) -> str:
        lib = self.lib
        if not ref:
            return ""
        size = lib.CFStringGetMaximumSizeForEncoding(lib.CFStringGetLength(ref), UTF8) + 1
        if size <= 1 or size > 4_000_000:
            return ""
        buffer = ctypes.create_string_buffer(size)
        return buffer.value.decode("utf-8", "replace") if lib.CFStringGetCString(ref, buffer, size, UTF8) else ""

    def _value(self, ref):
        """A CoreFoundation value as Python: text, a number, yes or no, a point or a size, a list of what it holds (still
        the system's own references, alive only as long as the list they came in), or an element's reference."""
        lib = self.lib
        if not ref:
            return None
        kind = lib.CFGetTypeID(ref)
        if kind == lib.kinds["string"]:
            return self._text(ref)
        if kind == lib.kinds["boolean"]:
            return bool(lib.CFBooleanGetValue(ref))
        if kind == lib.kinds["number"]:
            number = ctypes.c_double()
            return number.value if lib.CFNumberGetValue(ref, 13, ctypes.byref(number)) else None
        if kind == lib.kinds["value"]:
            which = lib.AXValueGetType(ref)
            if which == 1:
                point = CGPoint()
                return (point.x, point.y) if lib.AXValueGetValue(ref, 1, ctypes.byref(point)) else None
            if which == 2:
                size = CGSize()
                return (size.width, size.height) if lib.AXValueGetValue(ref, 2, ctypes.byref(size)) else None
            return None                                # (the marker for "this control has no such attribute")
        if kind == lib.kinds["array"]:
            return [lib.CFArrayGetValueAtIndex(ref, index) for index in range(lib.CFArrayGetCount(ref))]
        if kind == lib.kinds["element"]:
            return int(ref)
        return None

    def _copy(self, element, name: str):
        """(error, reference) for one attribute of an element. The caller releases the reference."""
        found = ctypes.c_void_p()
        error = self.lib.AXUIElementCopyAttributeValue(element, self._name(name), ctypes.byref(found))
        return error, (found.value if not error else None)

    def _plain(self, element, name: str):
        """One attribute as a plain Python value (text, number, yes or no, point, size); None when there is none."""
        error, ref = self._copy(element, name)
        if not ref:
            return None
        try:
            value = self._value(ref)
            return None if isinstance(value, list) else value
        finally:
            self.lib.CFRelease(ref)

    def release(self, references) -> None:
        for ref in references or ():
            if ref:
                self.lib.CFRelease(ref)

    # ------------------------------------------------------------------ permissions
    def trusted(self) -> bool:
        """Has Accessibility been allowed?"""
        return bool(self.lib.AXIsProcessTrusted())

    def ask_trust(self) -> bool:
        """Have macOS show its own "JARVIS would like to control this computer" window (it does so once), and return
        whether it is already allowed."""
        lib = self.lib
        keys, values = (ctypes.c_void_p * 1)(lib.trusted_prompt), (ctypes.c_void_p * 1)(lib.true)
        options = lib.CFDictionaryCreate(None, keys, values, 1, lib.key_callbacks, lib.value_callbacks)
        try:
            return bool(lib.AXIsProcessTrustedWithOptions(options))
        finally:
            lib.CFRelease(options)

    def sees_screen(self) -> bool:
        """Has Screen Recording been allowed? (True where macOS is too old to ask.)"""
        check = getattr(self.lib, "CGPreflightScreenCaptureAccess", None)
        return bool(check()) if check else True

    def ask_screen(self) -> bool:
        ask = getattr(self.lib, "CGRequestScreenCaptureAccess", None)
        return bool(ask()) if ask else True

    def need_trust(self) -> None:
        if not self.trusted():
            self.ask_trust()
            raise NotAllowed(ACCESSIBILITY)

    def brightness(self, percent=None) -> int:
        """The Mac's own screen's brightness, 0 to 100: read it, or set it and read it back. macOS publishes no way to do
        this, so the one its own settings use (DisplayServices) is asked. ValueError where the screen does not take it
        (most separate monitors do not)."""
        try:
            services = ctypes.CDLL("/System/Library/PrivateFrameworks/DisplayServices.framework/DisplayServices")
            read, write = services.DisplayServicesGetBrightness, services.DisplayServicesSetBrightness
        except (OSError, AttributeError):
            raise ValueError(NO_BRIGHTNESS) from None
        read.restype, read.argtypes = ctypes.c_int32, [ctypes.c_uint32, ctypes.POINTER(ctypes.c_float)]
        write.restype, write.argtypes = ctypes.c_int32, [ctypes.c_uint32, ctypes.c_float]
        screen = self.lib.CGMainDisplayID()
        if percent is not None:
            try:
                value = max(0, min(100, int(float(percent))))
            except (TypeError, ValueError):
                raise ValueError("Give a brightness from 0 to 100.") from None
            if write(screen, value / 100):
                raise ValueError(NO_BRIGHTNESS)
        level = ctypes.c_float()
        if read(screen, ctypes.byref(level)):
            raise ValueError(NO_BRIGHTNESS)
        return round(level.value * 100)

    # ------------------------------------------------------------------ screens and windows
    def displays(self) -> list[dict]:
        """Every screen: where it is on the whole desktop (in points, the main screen's corner at 0, 0) and how many
        real pixels it is wide."""
        lib = self.lib
        listed, count = (ctypes.c_uint32 * 16)(), ctypes.c_uint32()
        if lib.CGGetActiveDisplayList(16, listed, ctypes.byref(count)):
            return []
        main, found = lib.CGMainDisplayID(), []
        for ident in listed[:count.value]:
            box = lib.CGDisplayBounds(ident)
            found.append({"handle": int(ident), "left": round(box.origin.x), "top": round(box.origin.y), "width": round(box.size.width),
                          "height": round(box.size.height), "main": ident == main, "pixels": int(lib.CGDisplayPixelsWide(ident)),
                          "builtin": bool(lib.CGDisplayIsBuiltin(ident))})
        return found

    def rows(self, every: bool = False) -> list[dict]:
        """The ordinary windows, front to back: {"handle", "pid", "app", "name", "box": (left, top, right, bottom)}.
        every: also the ones not on the screen now (minimised, on another desktop). "name" is empty where macOS will
        not give other apps' window titles (Screen Recording not allowed)."""
        lib = self.lib
        listed = lib.CGWindowListCopyWindowInfo(0 if every else 1 | 16, 0)
        if not listed:
            return []
        found = []
        try:
            for index in range(lib.CFArrayGetCount(listed)):
                row = lib.CFArrayGetValueAtIndex(listed, index)
                get = lambda key: self._value(lib.CFDictionaryGetValue(row, self._name(key)))    # noqa: E731
                if get("kCGWindowLayer") != 0:
                    continue                           # the menu bar, the Dock, notices: not windows to work in
                box = CGRect()
                bounds = lib.CFDictionaryGetValue(row, self._name("kCGWindowBounds"))
                if not bounds or not lib.CGRectMakeWithDictionaryRepresentation(bounds, ctypes.byref(box)):
                    continue
                if box.size.width < 40 or box.size.height < 40 or (get("kCGWindowAlpha") or 1) <= 0:
                    continue
                found.append({"handle": int(get("kCGWindowNumber") or 0), "pid": int(get("kCGWindowOwnerPID") or 0),
                              "app": str(get("kCGWindowOwnerName") or ""), "name": str(get("kCGWindowName") or ""),
                              "box": (round(box.origin.x), round(box.origin.y), round(box.origin.x + box.size.width), round(box.origin.y + box.size.height))})
        finally:
            lib.CFRelease(listed)
        return [row for row in found if row["handle"] and row["pid"]]

    def front_pid(self) -> int:
        """The process whose window has the keyboard. Asked of Accessibility; without it, the owner of the window on top."""
        lib = self.lib
        if self._system is None:
            self._system = lib.AXUIElementCreateSystemWide()
        error, app = self._copy(self._system, "AXFocusedApplication")
        if app:
            try:
                pid = ctypes.c_int32()
                if not lib.AXUIElementGetPid(app, ctypes.byref(pid)) and pid.value > 0:
                    return pid.value
            finally:
                lib.CFRelease(app)
        rows = self.rows()
        return rows[0]["pid"] if rows else 0

    def _app(self, pid: int) -> int:
        """The Accessibility element of an app (the caller releases it). Apps drawn by a browser engine (Chrome, Edge,
        and apps built on Electron) only list what is on their pages once they are asked to; they are asked here."""
        lib = self.lib
        app = lib.AXUIElementCreateApplication(int(pid))
        if not app:
            raise OSError("That app is gone.")
        lib.AXUIElementSetMessagingTimeout(app, 2.0)
        if pid not in self._eased:
            self._eased.add(pid)
            lib.AXUIElementSetAttributeValue(app, self._name("AXManualAccessibility"), lib.true)
        return app

    def _windows_of(self, app) -> list[int]:
        """The app's windows as Accessibility elements, each kept alive for the caller to release."""
        lib = self.lib
        error, listed = self._copy(app, "AXWindows")
        if error == NOT_ALLOWED:
            self.ask_trust()
            raise NotAllowed(ACCESSIBILITY)
        if not listed:
            return []
        try:
            windows = [w for w in self._value(listed) or [] if w]
            for window in windows:
                lib.CFRetain(window)
            return windows
        finally:
            lib.CFRelease(listed)

    def _ident(self, window) -> int:
        """Which window (macOS's number for it) an Accessibility window element is; 0 when macOS will not say."""
        ask = getattr(self.lib, "AXUIElementGetWindow", None)
        if not ask:
            return 0
        number = ctypes.c_uint32()
        return int(number.value) if not ask(window, ctypes.byref(number)) else 0

    def _frame(self, element) -> tuple[float, float, float, float] | None:
        place, size = self._plain(element, "AXPosition"), self._plain(element, "AXSize")
        return (place[0], place[1], size[0], size[1]) if isinstance(place, tuple) and isinstance(size, tuple) else None

    def window(self, handle: int) -> tuple[int, dict]:
        """(the window's Accessibility element, its row). The caller releases the element. OSError when it is gone."""
        row = next((r for r in self.rows(every=True) if r["handle"] == int(handle)), None)
        if not row:
            raise OSError("That window is gone.")
        if not self.trusted():
            self.ask_trust()
            raise NotAllowed(ACCESSIBILITY)
        app = self._app(row["pid"])
        try:
            windows, chosen = self._windows_of(app), 0
            for window in windows:
                if self._ident(window) == row["handle"]:
                    chosen = window
                    break
            if not chosen:                             # by its place and size
                left, top, right, bottom = row["box"]
                for window in windows:
                    frame = self._frame(window)
                    if frame and abs(frame[0] - left) <= 2 and abs(frame[1] - top) <= 2 and abs(frame[2] - (right - left)) <= 2 and abs(frame[3] - (bottom - top)) <= 2:
                        chosen = window
                        break
            self.release(w for w in windows if w != chosen)
            if not chosen:
                raise OSError("That window does not answer.")
            return chosen, row
        finally:
            self.lib.CFRelease(app)

    def titles(self, pid: int) -> list[tuple[int, tuple, str]]:
        """(macOS's number, (left, top, width, height), title) for each of an app's windows, as Accessibility tells it.
        Empty when it is not allowed or the app does not answer."""
        if not self.trusted():
            return []
        try:
            app = self._app(pid)
        except OSError:
            return []
        try:
            windows = self._windows_of(app)
        except OSError:
            windows = []
        finally:
            self.lib.CFRelease(app)
        try:
            return [(self._ident(w), self._frame(w) or (0, 0, 0, 0), str(self._plain(w, "AXTitle") or "")) for w in windows]
        finally:
            self.release(windows)

    def raise_window(self, handle: int) -> None:
        """Bring a window, and its app, to the front (and out of the Dock if it was put there)."""
        lib = self.lib
        window, row = self.window(handle)
        try:
            lib.AXUIElementSetAttributeValue(window, self._name("AXMinimized"), lib.false)
            app = self._app(row["pid"])
            try:
                lib.AXUIElementSetAttributeValue(app, self._name("AXFrontmost"), lib.true)
            finally:
                lib.CFRelease(app)
            lib.AXUIElementPerformAction(window, self._name("AXRaise"))
            lib.AXUIElementSetAttributeValue(window, self._name("AXMain"), lib.true)
        finally:
            lib.CFRelease(window)

    def place_window(self, handle: int, left: int, top: int, width: int, height: int) -> bool:
        """Move a window and give it a size. True when macOS took both."""
        lib = self.lib
        window, _ = self.window(handle)
        try:
            point, size = CGPoint(float(left), float(top)), CGSize(float(width), float(height))
            done = True
            for name, kind, value in (("AXPosition", 1, point), ("AXSize", 2, size), ("AXPosition", 1, point)):
                boxed = lib.AXValueCreate(kind, ctypes.byref(value))
                try:
                    done = lib.AXUIElementSetAttributeValue(window, self._name(name), boxed) == 0 and done
                finally:
                    lib.CFRelease(boxed)
            return done
        finally:
            lib.CFRelease(window)

    # ------------------------------------------------------------------ a window's controls
    def _attribute_list(self) -> int:
        with self._lock:
            if self._attributes is None:
                names = (ctypes.c_void_p * len(ATTRIBUTES))()
                for index, name in enumerate(ATTRIBUTES):
                    names[index] = self._string(name)
                self._attributes = self.lib.CFArrayCreate(None, names, len(ATTRIBUTES), self.lib.array_callbacks)
            return self._attributes

    def read(self, element, keep: list) -> dict | None:
        """One control as it describes itself: {"el", "role", "subrole", "title", "description", "placeholder", "value",
        "position", "size", "enabled", "children"}. Its children are added to `keep`, which the caller releases."""
        lib = self.lib
        values = ctypes.c_void_p()
        if lib.AXUIElementCopyMultipleAttributeValues(element, self._attribute_list(), 0, ctypes.byref(values)) or not values:
            return None
        try:
            got = [self._value(lib.CFArrayGetValueAtIndex(values, index)) for index in range(len(ATTRIBUTES))]
            children = [c for c in got[CHILDREN] if c] if isinstance(got[CHILDREN], list) else []
            for child in children:
                lib.CFRetain(child)
            keep.extend(children)
        finally:
            lib.CFRelease(values)
        text = lambda value: value if isinstance(value, str) else ""               # noqa: E731
        node = {"el": element, "role": text(got[ROLE]), "subrole": text(got[SUBROLE]), "title": text(got[TITLE]), "description": text(got[DESCRIPTION]),
                "placeholder": text(got[PLACEHOLDER]), "value": "", "position": got[POSITION] if isinstance(got[POSITION], tuple) else None,
                "size": got[SIZE] if isinstance(got[SIZE], tuple) else None, "enabled": got[ENABLED] is not False, "children": children}
        if node["role"] in ("AXStaticText", "AXHeading") and not node["title"] and not node["description"]:
            value = self._plain(element, "AXValue")
            node["value"] = value[:200] if isinstance(value, str) else ""
        return node

    def walk(self, handle: int, limit: int = 6000, seconds: float = 6.0) -> dict:
        """Every control of a window, in the order it lists them: {"title", "frame": (left, top, width, height),
        "nodes": [...], "keep": [...]}. Give the result to done() afterwards."""
        window, row = self.window(handle)
        keep, nodes, until = [window], [], time.monotonic() + seconds
        try:
            top = self.read(window, keep)
            if top is None:
                raise OSError("The window did not list its controls.")
            left, upper, right, lower = row["box"]
            frame = (top["position"] + top["size"]) if top["position"] and top["size"] else (left, upper, right - left, lower - upper)
            waiting = list(reversed(top["children"]))
            while waiting and len(nodes) < limit and time.monotonic() < until:
                node = self.read(waiting.pop(), keep)
                if node is None:
                    continue
                nodes.append(node)
                if node["role"] not in LEAVES:
                    waiting.extend(reversed(node["children"]))
            return {"title": top["title"], "frame": frame, "nodes": nodes, "keep": keep}
        except BaseException:
            self.release(keep)
            raise

    def done(self, walked: dict | None) -> None:
        if walked:
            self.release(walked.get("keep"))
            walked["keep"] = []

    def at(self, x: float, y: float) -> dict:
        """The control showing at a point of the screen, and the one it sits in: {"nodes": [it, its parent], "keep"}."""
        lib = self.lib
        if self._system is None:
            self._system = lib.AXUIElementCreateSystemWide()
        found = ctypes.c_void_p()
        if lib.AXUIElementCopyElementAtPosition(self._system, float(x), float(y), ctypes.byref(found)) or not found:
            return {"nodes": [], "keep": []}
        keep, nodes = [found.value], []
        node = self.read(found.value, keep)
        if node:
            nodes.append(node)
            error, parent = self._copy(found.value, "AXParent")
            if parent:
                keep.append(parent)
                above = self.read(parent, keep)
                if above:
                    nodes.append(above)
        return {"nodes": nodes, "keep": keep}

    def press(self, element) -> bool:
        """Press a control the way the keyboard would (no pointer involved). False when it has no such action."""
        return self.lib.AXUIElementPerformAction(element, self._name("AXPress")) == 0

    def fill(self, element, text: str) -> bool:
        """Put text into a box directly. False when the box does not take it that way (then it is typed)."""
        lib = self.lib
        can = ctypes.c_ubyte(0)
        if lib.AXUIElementIsAttributeSettable(element, self._name("AXValue"), ctypes.byref(can)) or not can.value:
            return False
        value = self._string(text)
        try:
            return lib.AXUIElementSetAttributeValue(element, self._name("AXValue"), value) == 0
        finally:
            lib.CFRelease(value)

    def focus(self, element) -> bool:
        """Put the cursor in a control."""
        return self.lib.AXUIElementSetAttributeValue(element, self._name("AXFocused"), self.lib.true) == 0

    # ------------------------------------------------------------------ pointer and keys
    def pointer(self) -> tuple[float, float]:
        lib = self.lib
        event = lib.CGEventCreate(None)
        try:
            place = lib.CGEventGetLocation(event)
            return place.x, place.y
        finally:
            lib.CFRelease(event)

    def modifiers_held(self) -> bool:
        """Is Control, Option, Shift or Command (either one of each) down right now? The keys themselves are asked, not
        the marks that events carry: a mark can outlast the key that set it."""
        return any(self.lib.CGEventSourceKeyState(1, key) for key in (55, 54, 56, 60, 58, 61, 59, 62))

    def _send(self, event) -> None:
        if not event:
            raise OSError("macOS did not make the event.")
        try:
            self.lib.CGEventPost(0, event)
        finally:
            self.lib.CFRelease(event)

    def _mouse(self, kind: int, x: float, y: float, button: int = 0, count: int = 1) -> None:
        event = self.lib.CGEventCreateMouseEvent(None, kind, CGPoint(float(x), float(y)), button)
        if event and count > 1:
            self.lib.CGEventSetIntegerValueField(event, 1, count)      # the second press of a double click says so
        self._send(event)

    def move(self, x: float, y: float) -> None:
        self.need_trust()
        self._mouse(5, x, y)

    def click(self, x: float, y: float, right: bool = False, double: bool = False) -> None:
        self.need_trust()
        self._mouse(5, x, y)
        time.sleep(0.08)
        down, up, button = (3, 4, 1) if right else (1, 2, 0)
        for count in range(1, 3 if double else 2):
            self._mouse(down, x, y, button, count)
            self._mouse(up, x, y, button, count)
            time.sleep(0.06)

    def scroll(self, lines: int) -> None:
        """Turn the wheel over whatever is under the pointer: positive is up, as on Windows."""
        self.need_trust()
        self._send(self.lib.CGEventCreateScrollWheelEvent2(None, 1, 1, int(lines), 0, 0))

    def _key_event(self, code: int, down: bool, flags: int) -> None:
        event = self.lib.CGEventCreateKeyboardEvent(None, int(code), 1 if down else 0)
        if event:
            self.lib.CGEventSetFlags(event, int(flags))
        self._send(event)
        time.sleep(0.01)

    def key(self, code: int, flags: int = 0) -> None:
        """Press and let go of one key (macOS's number for it), with the modifier keys in `flags` held: as a keyboard
        does it. The modifier keys go down one by one, then the key goes down and up, then the modifier keys come up
        again. (Sent as the key alone with only a mark saying "Command is held", macOS went on counting Command as
        held afterwards.)"""
        self.need_trust()
        flags = int(flags)
        modifiers = [(mark, own) for mark, own in MODIFIER_KEYS if flags & mark]
        held = 0
        for mark, own in modifiers:
            held |= mark
            self._key_event(own, True, held)
        self._key_event(code, True, flags)
        self._key_event(code, False, flags)
        for mark, own in reversed(modifiers):
            held &= ~mark
            self._key_event(own, False, held)

    def type_character(self, character: str) -> None:
        """Type one character exactly as given, whatever the keyboard layout."""
        units = character.encode("utf-16-le")
        count = len(units) // 2
        buffer = (ctypes.c_uint16 * count).from_buffer_copy(units)
        for down in (1, 0):
            event = self.lib.CGEventCreateKeyboardEvent(None, 0, down)
            if event:
                self.lib.CGEventSetFlags(event, 0)
                self.lib.CGEventKeyboardSetUnicodeString(event, count, buffer)
            self._send(event)

    def type_text(self, text: str) -> None:
        self.need_trust()
        for character in str(text):
            if character == "\n":
                self.key(36)
            elif character == "\t":
                self.key(48)
            elif character >= " ":
                self.type_character(character)
            time.sleep(0.004)


_mac: Mac | None = None


def mac() -> Mac:
    """The one Mac for this process."""
    global _mac
    if _mac is None:
        _mac = Mac()
    return _mac
