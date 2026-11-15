"""The small window that shows JARVIS is listening while another program is in front.

"Hey JARVIS" works from anywhere. When JARVIS's own window is not the one in use (it is closed, minimised or behind
another program) a small panel with the orb and the words appears in a corner of the screen the owner is working on,
stays on top, and goes away again when the conversation is over. It never takes the keyboard away from the program in
front: it is shown without being activated, and when it is clicked (Edge takes the keyboard then, whatever the window
says) the keyboard goes straight back to the program that had it.

It is an ordinary JARVIS page (opened with ?mini) in a private browser profile of its own, kept ready out of sight, so it
appears at once and the microphone and the voice are already allowed. It used to share the app window's profile, and so
the app window's browser: that browser opened it the way the app window had been opened (full screen, or maximised as it
was last left), over the whole screen. In a browser of its own it opens at its own small size, and a window that comes
up maximised anyway is put back to its own size before it is shown. Edge's own title bar and border are taken off and
the window is cut down to the page, so what is seen is just the panel. It can be dragged anywhere with the mouse, and it
comes back where it was put (measured from the corner of whichever screen is in use).

If a future Edge is built differently and the page inside the window cannot be found, the window is shown as it is,
title bar and all: it still works.
"""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import threading
import time

TITLE = "JARVIS · Listening"
WIDE, HIGH, GAP = 372, 150, 18          # the size of the panel, and the room left to the screen's edge (screen points)
FAR = -32000                            # a place far off every screen
PAGE = "Chrome_RenderWidgetHostHWND"    # Edge's own name for the part of a window that shows the page
PROFILE = "listening-window-profile"   # its own browser profile, beside the app window's ("window-profile")
ROOM = 240                              # more than Edge ever keeps around the page (real pixels at the largest scaling)


def title_for(url: str) -> str:
    """The small window's title. A second JARVIS on this PC (one being tried out on another port) gets its own, so that
    neither ever takes hold of the other's window."""
    port = url.rstrip("/").rpartition(":")[2]
    return TITLE if port in ("8765", "") or not port.isdigit() else f"{TITLE} · {port}"


class _Windows:
    """What is needed of Windows here, in real pixels. Tests pass a stand-in with the same methods."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.c, self.wintypes, self.user32, self.gdi32 = ctypes, wintypes, ctypes.windll.user32, ctypes.windll.gdi32
        pointer, number = ctypes.c_void_p, ctypes.c_int
        user = self.user32
        user.GetForegroundWindow.restype = pointer
        user.MonitorFromWindow.restype = pointer
        user.MonitorFromWindow.argtypes = [pointer, wintypes.DWORD]
        user.SetWindowPos.argtypes = [pointer, pointer, number, number, number, number, wintypes.UINT]
        user.ShowWindow.argtypes = [pointer, number]
        user.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user.GetWindowLongPtrW.argtypes = [pointer, number]
        user.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        user.SetWindowLongPtrW.argtypes = [pointer, number, ctypes.c_ssize_t]
        user.SetWindowRgn.argtypes = [pointer, pointer, wintypes.BOOL]
        user.GetAsyncKeyState.restype = ctypes.c_short
        self.gdi32.CreateRectRgn.restype = pointer
        self.gdi32.CreateRectRgn.argtypes = [number] * 4
        self.gdi32.DeleteObject.argtypes = [pointer]

    @contextlib.contextmanager
    def real(self):
        """While this lasts, Windows gives and takes real pixels on this thread, whatever a screen's scaling is."""
        before = None
        try:
            self.user32.SetThreadDpiAwarenessContext.argtypes = [self.c.c_void_p]
            self.user32.SetThreadDpiAwarenessContext.restype = self.c.c_void_p
            before = self.user32.SetThreadDpiAwarenessContext(self.c.c_void_p(-4))
        except (AttributeError, OSError):
            before = None
        try:
            yield
        finally:
            if before:
                try:
                    self.user32.SetThreadDpiAwarenessContext(self.c.c_void_p(before))
                except (AttributeError, OSError):
                    pass

    def find(self, title: str) -> int:
        """The window with exactly this title, shown or hidden. 0 if there is none."""
        ctypes, found = self.c, []
        proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def each(handle, _):
            buffer = ctypes.create_unicode_buffer(120)
            self.user32.GetWindowTextW(ctypes.c_void_p(handle), buffer, 120)
            if buffer.value == title:
                found.append(int(handle))
            return True
        self.user32.EnumWindows(proto(each), 0)
        return found[0] if found else 0

    def owned(self, pid: int) -> list[int]:
        """The shown top-level browser windows of this process (the Edge started for the small window)."""
        ctypes, found = self.c, []
        proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def each(handle, _):
            owner = self.wintypes.DWORD()
            self.user32.GetWindowThreadProcessId(ctypes.c_void_p(handle), ctypes.byref(owner))
            if owner.value == pid and self.user32.IsWindowVisible(ctypes.c_void_p(handle)):
                name = ctypes.create_unicode_buffer(80)
                self.user32.GetClassNameW(ctypes.c_void_p(handle), name, 80)
                if name.value == "Chrome_WidgetWin_1":
                    found.append(int(handle))
            return True
        self.user32.EnumWindows(proto(each), 0)
        return found

    def untask(self, handle: int) -> bool:
        """Off the taskbar at once: a tool window that is never activated, and its taskbar button taken away (Windows
        keeps a button made before the window became a tool window until the window is hidden)."""
        ctypes, pointer = self.c, self.c.c_void_p(handle)
        extended = self.user32.GetWindowLongPtrW(pointer, -20)
        self.user32.SetWindowLongPtrW(pointer, -20, (extended | 0x80 | 0x08000000) & ~0x40000)
        ole, started = ctypes.windll.ole32, False
        try:
            started = ole.CoInitializeEx(None, 2) in (0, 1)              # (S_OK or S_FALSE: this thread is set up for COM)
            clsid, iid = (ctypes.c_byte * 16)(), (ctypes.c_byte * 16)()
            ole.CLSIDFromString("{56FDF344-FD6D-11d0-958A-006097C9A090}", ctypes.byref(clsid))     # TaskbarList
            ole.CLSIDFromString("{56FDF342-FD6D-11d0-958A-006097C9A090}", ctypes.byref(iid))       # ITaskbarList
            taskbar = ctypes.c_void_p()
            if ole.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(taskbar)) != 0 or not taskbar:
                return False
            table = ctypes.cast(taskbar, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            call = lambda at, *kinds: ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *kinds)(table[at])   # noqa: E731
            try:
                call(3)(taskbar)                                           # HrInit
                return call(5, ctypes.c_void_p)(taskbar, pointer) == 0      # DeleteTab
            finally:
                call(2)(taskbar)                                           # Release
        except (AttributeError, OSError, ValueError):
            return False
        finally:
            if started:
                ole.CoUninitialize()

    def exists(self, handle: int) -> bool:
        return bool(handle) and bool(self.user32.IsWindow(self.c.c_void_p(handle)))

    def foreground(self) -> int:
        return int(self.user32.GetForegroundWindow() or 0)

    def visible(self, handle: int) -> bool:
        return bool(self.user32.IsWindowVisible(self.c.c_void_p(handle)))

    def unmaximise(self, handle: int) -> bool:
        """If the window is maximised, give it back its own size, without showing or activating it. True if it was."""
        pointer = self.c.c_void_p(handle)
        if not self.user32.IsZoomed(pointer):
            return False
        wintypes = self.wintypes

        class Placement(self.c.Structure):
            _fields_ = [("length", wintypes.UINT), ("flags", wintypes.UINT), ("show", wintypes.UINT), ("low", wintypes.POINT),
                        ("high", wintypes.POINT), ("normal", wintypes.RECT)]
        place = Placement()
        place.length = self.c.sizeof(Placement)
        if not self.user32.GetWindowPlacement(pointer, self.c.byref(place)):
            return False
        place.show = 4 if self.user32.IsWindowVisible(pointer) else 0       # its own size; shown without being activated, or kept hidden
        place.flags = 0
        return bool(self.user32.SetWindowPlacement(pointer, self.c.byref(place)))

    def rect(self, handle: int) -> tuple[int, int, int, int]:
        box = self.wintypes.RECT()
        self.user32.GetWindowRect(self.c.c_void_p(handle), self.c.byref(box))
        return box.left, box.top, box.right, box.bottom

    def page(self, handle: int) -> tuple[int, int, int, int] | None:
        """Where the page itself is inside an Edge window (None if that cannot be told)."""
        ctypes, found = self.c, []
        proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def each(child, _):
            name = ctypes.create_unicode_buffer(80)
            self.user32.GetClassNameW(ctypes.c_void_p(child), name, 80)
            if name.value == PAGE:
                found.append(self.rect(child))
                return False
            return True
        self.user32.EnumChildWindows(ctypes.c_void_p(handle), proto(each), 0)
        return found[0] if found else None

    def dress(self, handle: int, bare: bool) -> None:
        """A tool window (no taskbar button, not in Alt+Tab), on top, that is never activated. `bare`: also without a title
        bar or a sizing border, and with nothing drawn around it by Windows."""
        pointer = self.c.c_void_p(handle)
        extended = self.user32.GetWindowLongPtrW(pointer, -20)
        self.user32.SetWindowLongPtrW(pointer, -20, (extended | 0x80 | 0x08000000 | 0x8) & ~0x40000)      # tool window, no activate, topmost; not an "app window"
        self.untask(handle)
        if not bare:
            return
        style = self.user32.GetWindowLongPtrW(pointer, -16)
        # No caption, sizing border, window menu, minimise or maximise: a plain pop-up.
        self.user32.SetWindowLongPtrW(pointer, -16, (style & ~(0x00C00000 | 0x00040000 | 0x00080000 | 0x00020000 | 0x00010000)) | 0x80000000)
        self.user32.SetWindowPos(pointer, None, 0, 0, 0, 0, 0x1 | 0x2 | 0x4 | 0x10 | 0x20)             # the frame has changed
        try:
            dwm = self.c.windll.dwmapi
            dwm.DwmSetWindowAttribute.argtypes = [self.c.c_void_p, self.wintypes.DWORD, self.c.c_void_p, self.wintypes.DWORD]
            # No backdrop material, no frame drawn by Windows, no border colour, square corners: otherwise a faint frame
            # stays visible around the part the window is cut down to.
            for attribute, value in ((38, 1), (17, 0), (2, 1), (34, 0xFFFFFFFE), (33, 1)):
                number = self.c.c_uint(value)
                dwm.DwmSetWindowAttribute(pointer, attribute, self.c.byref(number), 4)
        except (AttributeError, OSError):
            pass

    def area(self, handle: int) -> tuple[int, int, int, int, float]:
        """The usable part of the screen a window is on (the main screen if there is no window), and that screen's scaling."""
        wintypes = self.wintypes

        class Info(self.c.Structure):
            _fields_ = [("size", wintypes.DWORD), ("whole", wintypes.RECT), ("work", wintypes.RECT), ("flags", wintypes.DWORD)]
        info = Info()
        info.size = self.c.sizeof(Info)
        monitor = self.user32.MonitorFromWindow(self.c.c_void_p(handle or 0), 1 if not handle else 2)      # 1: the main screen, 2: the nearest one
        if not monitor or not self.user32.GetMonitorInfoW(self.c.c_void_p(monitor), self.c.byref(info)):
            return 0, 0, 1280, 720, 1.0
        scale = 1.0
        try:
            across, down = self.c.c_uint(96), self.c.c_uint(96)
            if self.c.windll.shcore.GetDpiForMonitor(self.c.c_void_p(monitor), 0, self.c.byref(across), self.c.byref(down)) == 0 and across.value:
                scale = across.value / 96
        except (AttributeError, OSError):
            scale = 1.0
        return info.work.left, info.work.top, info.work.right, info.work.bottom, scale

    def place(self, handle: int, x: int, y: int, wide: int, high: int, show: bool | None = None) -> None:
        # On top of everything, at this place and size, never activated. (0x10: no activate, 0x40: show, 0x80: hide.)
        self.user32.SetWindowPos(self.c.c_void_p(handle), self.c.c_void_p(-1), x, y, wide, high, 0x10 | (0x40 if show else 0x80 if show is False else 0))

    def move(self, handle: int, x: int, y: int) -> None:
        self.user32.SetWindowPos(self.c.c_void_p(handle), None, x, y, 0, 0, 0x1 | 0x4 | 0x10)              # the same size and order; not activated

    def cut(self, handle: int, left: int, top: int, right: int, bottom: int) -> bool:
        """Only this part of the window (measured from its own corner) is seen and can be clicked. An empty part: nothing
        of it is seen, although it is shown."""
        region = self.gdi32.CreateRectRgn(left, top, right, bottom)
        if self.user32.SetWindowRgn(self.c.c_void_p(handle), self.c.c_void_p(region), True):
            return True                                                                                    # (Windows owns the region now)
        self.gdi32.DeleteObject(self.c.c_void_p(region))
        return False

    def uncut(self, handle: int) -> None:
        self.user32.SetWindowRgn(self.c.c_void_p(handle), None, True)

    def cursor(self) -> tuple[int, int]:
        point = self.wintypes.POINT()
        self.user32.GetCursorPos(self.c.byref(point))
        return point.x, point.y

    def pressed(self) -> bool:
        """Is the mouse's main button held down?"""
        return bool(self.user32.GetAsyncKeyState(0x02 if self.user32.GetSystemMetrics(23) else 0x01) & 0x8000)

    def show(self, handle: int, on: bool) -> None:
        self.user32.ShowWindow(self.c.c_void_p(handle), 4 if on else 0)                                   # 4: shown, not activated

    def focus(self, handle: int) -> None:
        from jcc import winctl
        winctl.focus(handle)

    def close(self, handle: int) -> None:
        self.user32.PostMessageW(self.c.c_void_p(handle), 0x0010, 0, 0)                                    # ask it to close


def launch_argv(cfg, edge, url: str) -> list[str]:
    """How Edge is started for the small window: in its own profile (so in a browser of its own), at its own small size,
    far off every screen, and never full screen or maximised."""
    from jcc import placement
    return [str(edge), "--app=" + url, *placement.profile(cfg, url.split("?")[0], PROFILE), f"--window-size={WIDE},{HIGH}",
            f"--window-position={FAR},{FAR}"]


class Mini:
    def __init__(self, cfg, url: str, launch=None, windows=None, clock=time.time, pause=time.sleep):
        self.cfg, self.url, self.clock, self.pause = cfg, url.rstrip("/") + "/?mini", clock, pause
        self.title = title_for(url)
        self.make_windows, self.win, self.launch = windows, None, launch or self._launch
        self.handle, self.wanted, self.starting, self.failed_at = 0, False, False, 0.0
        self.bare, self.fitted = False, None       # without Edge's frame; what it was last cut down to (the room around the page, and the page's size)
        self.extra, self.spot = (0, 0, 0, 0), None  # the room Edge kept around the page when last seen; where the panel was last put
        self.front = 0                             # the program that had the keyboard when the panel was last looked at
        self.dragging = False
        self.pid = 0                               # the Edge started for it (see _launch)
        self.gap = self._kept()                    # how far from the right and bottom edges its owner put it (screen points)
        self.lock, self.moving = threading.Lock(), threading.RLock()

    def _windows(self):
        if self.win is None:
            self.win = self.make_windows() if self.make_windows else _Windows()
        return self.win

    # ------------------------------------------------------------------ where its owner put it
    def _file(self):
        return self.cfg.state_dir / "listening-window.json"

    def _kept(self) -> tuple[int, int]:
        try:
            saved = json.loads(self._file().read_text("utf-8"))
            right, bottom = saved["right"], saved["bottom"]
            if all(isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 8000 for v in (right, bottom)):
                return right, bottom
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return GAP, GAP

    def _keep(self) -> None:
        try:
            from jcc.vault import atomic_write
            atomic_write(self._file(), json.dumps({"right": self.gap[0], "bottom": self.gap[1]}))
        except OSError:
            pass

    # ------------------------------------------------------------------ opening it
    def _launch(self) -> bool:
        from jcc.desktop import edge_path
        edge = edge_path()
        if not edge:
            return False
        # It opens far off the screen, so nothing flashes before it has been dressed and put in its corner. (Its process is
        # kept: its window is taken off the taskbar the moment it appears, before its page has even said what it is.)
        self.pid = subprocess.Popen(launch_argv(self.cfg, edge, self.url), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL).pid
        return True

    def alive(self) -> bool:
        return bool(self.handle) and self._windows().exists(self.handle)

    def ensure(self) -> bool:
        """Make sure the small window exists (out of sight unless it is wanted). True if it does, or is on its way."""
        if os.name != "nt" and not self.make_windows:
            return False
        if self.alive():
            return True
        with self.lock:
            if self.starting:
                return True
            if self.clock() - self.failed_at < 120:
                return False                                # it could not be opened a moment ago: not tried again at once
            self.starting = True
        threading.Thread(target=self._start, daemon=True, name="listening-window").start()
        return True

    def _start(self) -> None:
        win = self._windows()
        try:
            with win.real():
                before = win.foreground()
                stale = win.find(self.title)
                if stale:
                    # One left open by an earlier run of JARVIS shows the page as it was then: a fresh one takes its place.
                    win.close(stale)
                    for _ in range(25):
                        self.pause(0.2)
                        if not win.find(self.title):
                            break
                self.pid = 0
                if not self.launch():
                    self.failed_at = self.clock()
                    return
                early, owned, untask = set(), getattr(win, "owned", None), getattr(win, "untask", None)
                for _ in range(300):                        # (up to 30 s: a first start of Edge with a new profile is slow)
                    self.pause(0.1)
                    if self.pid and owned and untask:
                        for shown in owned(self.pid):
                            if shown not in early:          # never on the taskbar, not even while its page loads
                                early.add(shown)
                                untask(shown)
                    handle = win.find(self.title)
                    if handle:
                        unmaximise = getattr(win, "unmaximise", None)
                        if unmaximise:
                            unmaximise(handle)              # never over the whole screen, whatever the browser remembered
                        self.bare = win.page(handle) is not None
                        win.dress(handle, self.bare)
                        self.handle, self.fitted = handle, None
                        if self.wanted:
                            self._put()
                        else:
                            self._ready()
                        if before and win.foreground() != before and win.exists(before):
                            win.focus(before)               # the keyboard goes straight back to the program that had it
                        return
                for shown in early:                         # a page that never loaded: its window is closed, not left about
                    if win.exists(shown):
                        win.close(shown)
                self.failed_at = self.clock()
        except Exception:  # noqa: BLE001 - without this window JARVIS still listens and answers
            self.failed_at = self.clock()
        finally:
            self.starting = False

    # ------------------------------------------------------------------ its size, its cut and its place
    def _fit(self, x: int, y: int, wide: int, high: int) -> bool:
        """Put the window so that the page inside it is exactly here and this large, and cut the rest of the window away.
        True when that is so.

        Edge lays a window out a moment after it is moved or shown, so this looks again a few times. While a window is
        hidden Edge puts the page's own inner window away altogether: then the window is shown as it was last laid out, and
        looked at again."""
        win, wanted = self._windows(), (x, y, x + wide, y + high)
        for turn in range(14):
            outer, page = win.rect(self.handle), win.page(self.handle)
            extra = (page[0] - outer[0], page[1] - outer[1], outer[2] - page[2], outer[3] - page[3]) if page else None
            if extra and all(0 <= part <= ROOM for part in extra):         # (anything else: Edge has not laid it out yet)
                if page == wanted:
                    if self.fitted != (extra, wide, high) and win.cut(self.handle, extra[0], extra[1], extra[0] + wide, extra[1] + high):
                        self.fitted = (extra, wide, high)
                    self.extra, self.spot = extra, wanted
                    return True
                win.place(self.handle, x - extra[0], y - extra[1], wide + extra[0] + extra[2], high + extra[1] + extra[3], True)
            elif turn == 0:
                extra = self.extra
                win.place(self.handle, x - extra[0], y - extra[1], wide + extra[0] + extra[2], high + extra[1] + extra[3], True)
            self.pause(0.07)
        return False

    def _ready(self) -> None:
        """Hidden until it is wanted, and with nothing of it to be seen until it has been cut down to the page."""
        win = self._windows()
        with self.moving:
            if self.bare:
                win.cut(self.handle, 0, 0, 0, 0)
            win.show(self.handle, False)

    def _spot(self, here: bool) -> tuple[int, int, int, int]:
        """Where the panel goes: x, y, width and height in real pixels, on the screen in use (`here`: the screen it is on)."""
        win = self._windows()
        front = win.foreground()
        left, top, right, bottom, scale = win.area(self.handle if here else (front if front != self.handle else 0))
        wide, high = round(WIDE * scale), round(HIGH * scale)
        x = min(max(right - round(self.gap[0] * scale) - wide, left), max(left, right - wide))
        y = min(max(bottom - round(self.gap[1] * scale) - high, top), max(top, bottom - high))
        return x, y, wide, high

    def _put(self, here: bool = False) -> None:
        """Shown in its place, on top, never activated."""
        win = self._windows()
        with self.moving, win.real():
            x, y, wide, high = self._spot(here)
            front = win.foreground()
            if front and front != self.handle:
                self.front = front
            if not self.bare:
                win.place(self.handle, x, y, wide, high, True)
                return
            if not self.fitted or self.fitted[1:] != (wide, high):
                # Not cut to this size yet (the first time, or a screen with another scaling): nothing of it is seen while
                # it is laid out. It is laid out in its place, on the screen, where Edge lays it out as it will stay.
                win.cut(self.handle, 0, 0, 0, 0)
                self.fitted = None
            if self._fit(x, y, wide, high):
                return
            outer, page = win.rect(self.handle), win.page(self.handle)
            if page:                                        # it would not settle: what there is of the page is shown
                win.cut(self.handle, page[0] - outer[0], page[1] - outer[1], page[2] - outer[0], page[3] - outer[1])
            else:                                           # the page inside cannot be found any more: an ordinary small window
                self.bare, self.fitted, self.spot = False, None, None
                win.uncut(self.handle)
                win.place(self.handle, x, y, wide, high, True)

    def _back(self) -> None:
        """A click in the panel gives it the keyboard (Edge sees to that): the keyboard goes back to the program that had it."""
        win = self._windows()
        front = win.foreground()
        if front and front != self.handle:
            self.front = front
        elif front == self.handle and self.front and win.exists(self.front):
            win.focus(self.front)

    def _check(self) -> None:
        """While it is on the screen: the keyboard stays with the program in use, and if Edge has laid the window out
        afresh (the screens changed, say) it is fitted again."""
        win = self._windows()
        if self.dragging:
            return
        self._back()
        if not self.bare or not self.spot:
            return
        with self.moving, win.real():
            page = win.page(self.handle)
            if page and page != self.spot and not self.dragging:
                self._fit(self.spot[0], self.spot[1], self.spot[2] - self.spot[0], self.spot[3] - self.spot[1])

    def show(self) -> None:
        self.wanted = True
        if self.alive():
            if self.dragging or self.starting:
                return
            if self._windows().visible(self.handle):
                self._check()
            else:
                self._put()
        else:
            self.ensure()

    def hide(self) -> None:
        self.wanted = False
        if self.handle and not self.dragging and self._windows().exists(self.handle) and self._windows().visible(self.handle):
            self._back()
            self._windows().show(self.handle, False)

    def shown(self) -> bool:
        return bool(self.handle) and self._windows().exists(self.handle) and self._windows().visible(self.handle)

    # ------------------------------------------------------------------ moving it with the mouse
    def drag(self) -> bool:
        """Its owner has taken hold of it: it follows the pointer until the mouse button is let go, and stays where it was put."""
        with self.lock:
            if self.dragging or not self.shown():
                return False
            self.dragging = True
        threading.Thread(target=self._follow, daemon=True, name="listening-window-move").start()
        return True

    def _follow(self) -> None:
        win = self._windows()
        try:
            with win.real():
                grip, start, began = win.cursor(), win.rect(self.handle), self.clock()
                while win.pressed() and self.clock() - began < 120 and win.exists(self.handle):
                    now = win.cursor()
                    win.move(self.handle, start[0] + now[0] - grip[0], start[1] + now[1] - grip[1])
                    self.pause(0.012)
                if win.exists(self.handle):
                    self._dropped()
                    self._back()
        except Exception:  # noqa: BLE001 - a window that could not be moved stays where it is
            pass
        finally:
            self.dragging = False
            if not self.wanted:
                self.hide()                                 # the conversation ended while it was being moved

    def _dropped(self) -> None:
        """It was let go: kept wholly on the screen it is on now, and remembered as so far from that screen's corner."""
        win = self._windows()
        left, top, right, bottom, scale = win.area(self.handle)
        box = (win.page(self.handle) if self.bare else None) or win.rect(self.handle)
        wide, high = box[2] - box[0], box[3] - box[1]
        x, y = min(max(box[0], left), max(left, right - wide)), min(max(box[1], top), max(top, bottom - high))
        self.gap = (max(0, round((right - x - wide) / scale)), max(0, round((bottom - y - high) / scale)))
        self._keep()
        self._put(here=True)

    def close(self) -> None:
        self.wanted = False
        try:
            win = self._windows()
            handle = self.handle if self.alive() else win.find(self.title)
            if handle:
                win.close(handle)
        except Exception:  # noqa: BLE001
            pass
        self.handle, self.fitted = 0, None
