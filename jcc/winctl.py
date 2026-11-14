"""Small Windows helpers for the assistant: windows, sound volume, screen brightness, finding files."""
from __future__ import annotations

import ctypes
import os
import re
import subprocess
import time
import uuid

_ENUMERATOR = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
_IID_ENUMERATOR = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
_IID_VOLUME = "{5CDF2C82-841E-4546-9722-0CF74078229A}"
_IID_METER = "{C02216F6-8C67-4B5B-9D00-D008E73E0064}"
_NOISE = re.compile(r"\\(__pycache__|node_modules|\.git|\$recycle\.bin|appdata\\local\\temp|\.venv|site-packages)\\", re.I)
_SKIP_TITLES = {"Program Manager", "Windows Input Experience", "Microsoft Text Input Application", "Settings ", "Default IME", "MSCTFIME UI"}


def _powershell(script: str, timeout: int = 25) -> str:
    done = subprocess.run(["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL,
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    return (done.stdout or "").strip()


# ---------------------------------------------------------------------- windows
def foreground() -> int:
    if os.name != "nt":
        return 0
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    return int(user32.GetForegroundWindow() or 0)


def title_of(handle: int) -> str:
    buffer = ctypes.create_unicode_buffer(300)
    ctypes.windll.user32.GetWindowTextW(ctypes.c_void_p(handle), buffer, 300)
    return buffer.value


def windows() -> list[dict]:
    """The windows the user could switch to, front to back."""
    if os.name != "nt":
        return []
    user32, rows = ctypes.windll.user32, []
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def each(handle, _):
        pointer = ctypes.c_void_p(handle)
        if user32.IsWindowVisible(pointer) and not user32.GetWindowLongW(pointer, -20) & 0x80:  # not a tool window
            cloaked = ctypes.c_int(0)
            try:
                ctypes.windll.dwmapi.DwmGetWindowAttribute(pointer, 14, ctypes.byref(cloaked), 4)
            except (AttributeError, OSError):
                pass
            title = title_of(handle)
            if title and not cloaked.value and title not in _SKIP_TITLES:
                rows.append({"handle": int(handle), "title": title})
        return True

    callback = proto(each)
    user32.EnumWindows(callback, 0)
    return rows


def exists(handle: int) -> bool:
    return bool(handle) and os.name == "nt" and bool(ctypes.windll.user32.IsWindow(ctypes.c_void_p(handle)))


def process_of(handle: int) -> int:
    """The number of the program a window belongs to."""
    if os.name != "nt" or not handle:
        return 0
    found = ctypes.c_ulong(0)
    ctypes.windll.user32.GetWindowThreadProcessId(ctypes.c_void_p(handle), ctypes.byref(found))
    return int(found.value)


def app_of(handle: int) -> str:
    """The program a window belongs to, by its file name without ".exe" ("comet", "Spotify"). "" when that cannot be told."""
    pid = process_of(handle)
    if not pid:
        return ""
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel32.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    process = kernel32.OpenProcess(0x1000, 0, pid)            # may only ask what it is: nothing else
    if not process:
        return ""
    try:
        size, buffer = ctypes.c_ulong(520), ctypes.create_unicode_buffer(520)
        if not kernel32.QueryFullProcessImageNameW(ctypes.c_void_p(process), 0, buffer, ctypes.byref(size)):
            return ""
        name = os.path.basename(buffer.value)
        name = name[:-4] if name.lower().endswith(".exe") else name
        return "" if name.lower() in ("applicationframehost", "explorer") else name      # (those only hold other programs' windows)
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(process))


def default_browser() -> str:
    """The name of the browser that opens web links on this PC ("Comet", "Google Chrome"). "" when that cannot be told."""
    if os.name != "nt":
        return ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice") as key:
            ident = str(winreg.QueryValueEx(key, "ProgId")[0])
        for root, sub in ((winreg.HKEY_CLASSES_ROOT, ident + r"\Application"), (winreg.HKEY_CLASSES_ROOT, ident)):
            try:
                with winreg.OpenKey(root, sub) as key:
                    for value in ("ApplicationName", "FriendlyTypeName", ""):
                        try:
                            name = str(winreg.QueryValueEx(key, value)[0]).strip()
                        except OSError:
                            continue
                        if name and not name.startswith("@") and len(name) <= 40:
                            return re.sub(r"\s+(HTML Document|HTML|URL|Document)$", "", name).strip()
            except OSError:
                continue
        return re.sub(r"(HTML|URL|HTM)$", "", ident.split(".")[0]).strip()[:40]
    except (OSError, ImportError, ValueError):
        return ""


def window_at(x: int, y: int) -> int:
    """The top-level window showing at this point of the screen (in real screen dots)."""
    if os.name != "nt":
        return 0
    from ctypes import wintypes
    from jcc import screens
    user32 = ctypes.windll.user32
    user32.WindowFromPoint.restype, user32.WindowFromPoint.argtypes = ctypes.c_void_p, [wintypes.POINT]
    user32.GetAncestor.restype, user32.GetAncestor.argtypes = ctypes.c_void_p, [ctypes.c_void_p, ctypes.c_uint]
    with screens.physical():                           # (true positions, on whichever screen)
        found = user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
    return int(user32.GetAncestor(ctypes.c_void_p(found), 2) or 0) if found else 0


def middle(handle: int) -> tuple[int, int] | None:
    """The middle of a window, in real screen dots."""
    if os.name != "nt" or not handle:
        return None
    from jcc import screens
    box = screens.window_box(handle)
    return ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2) if box else None


def find_window(words: str, rows: list[dict] | None = None) -> dict | None:
    low = " ".join(str(words).lower().split())
    if not low:
        return None
    rows = windows() if rows is None else rows
    titles = [(r, r["title"].lower()) for r in rows]
    for test in (lambda t: t == low, lambda t: t.endswith(low), lambda t: low in t, lambda t: all(w in t for w in low.split())):
        for row, title in titles:
            if test(title):
                return row
    return None


def focus(handle: int) -> bool:
    """Bring a window to the front. Windows resists this from background programs, so three ways are tried."""
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    pointer = ctypes.c_void_p(handle)
    if user32.IsIconic(pointer):
        user32.ShowWindow(pointer, 9)
    for attempt in range(3):
        if foreground() == handle:
            return True
        if attempt == 0:
            user32.keybd_event(0xE8, 0, 0, 0)   # a key no program uses; it lifts the focus lock
            user32.keybd_event(0xE8, 0, 2, 0)
            user32.SetForegroundWindow(pointer)
            user32.BringWindowToTop(pointer)
        elif attempt == 1:
            mine = kernel32.GetCurrentThreadId()
            other = user32.GetWindowThreadProcessId(ctypes.c_void_p(foreground()), None)
            user32.AttachThreadInput(mine, other, True)
            user32.BringWindowToTop(pointer)
            user32.SetForegroundWindow(pointer)
            user32.AttachThreadInput(mine, other, False)
        else:
            for _ in range(2):                  # Alt twice: the second press closes any menu the first one opened
                user32.keybd_event(0x12, 0, 0, 0)
                user32.keybd_event(0x12, 0, 2, 0)
            user32.SetForegroundWindow(pointer)
        time.sleep(0.15)
    return foreground() == handle


# ---------------------------------------------------------------------- sound volume
class _Guid(ctypes.Structure):
    _fields_ = [("data", ctypes.c_ubyte * 16)]


def _guid(text: str) -> _Guid:
    return _Guid.from_buffer_copy(uuid.UUID(text).bytes_le)


def _method(pointer, index: int, *argtypes):
    table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(table[index])


class _Speakers:
    """The volume control of the default speakers (Windows Core Audio)."""

    def __enter__(self):
        if os.name != "nt":
            raise OSError("Windows only")
        ole32, self.held = ctypes.windll.ole32, []
        ole32.CoInitializeEx(None, 0)
        ole32.CoCreateInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        ole32.CoCreateInstance.restype = ctypes.c_long
        enumerator, device, volume = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        if ole32.CoCreateInstance(ctypes.byref(_guid(_ENUMERATOR)), None, 23, ctypes.byref(_guid(_IID_ENUMERATOR)), ctypes.byref(enumerator)) or not enumerator:
            raise OSError("no audio service")
        self.held.append(enumerator)
        if _method(enumerator, 4, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(enumerator, 0, 1, ctypes.byref(device)) or not device:
            raise OSError("no speakers")
        self.held.append(device)
        if _method(device, 3, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(
                device, ctypes.byref(_guid(_IID_VOLUME)), 23, None, ctypes.byref(volume)) or not volume:
            raise OSError("no volume control")
        self.held.append(volume)
        return volume

    def __exit__(self, *_):
        for item in reversed(self.held):
            _method(item, 2)(item)
        return False


class OutputMeter:
    """How loud everything this PC is playing through its default speakers is right now, 0 to 1 (Windows Core Audio).

    Used on one thread: the one that opens it."""

    def __init__(self):
        self.held, self.meter = [], None

    def open(self) -> None:
        if os.name != "nt":
            raise OSError("Windows only")
        ole32 = ctypes.windll.ole32
        ole32.CoInitializeEx(None, 0)
        ole32.CoCreateInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        ole32.CoCreateInstance.restype = ctypes.c_long
        enumerator, device, meter = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        if ole32.CoCreateInstance(ctypes.byref(_guid(_ENUMERATOR)), None, 23, ctypes.byref(_guid(_IID_ENUMERATOR)), ctypes.byref(enumerator)) or not enumerator:
            raise OSError("no audio service")
        self.held.append(enumerator)
        if _method(enumerator, 4, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(enumerator, 0, 1, ctypes.byref(device)) or not device:
            self.close()
            raise OSError("no speakers")
        self.held.append(device)
        if _method(device, 3, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(
                device, ctypes.byref(_guid(_IID_METER)), 23, None, ctypes.byref(meter)) or not meter:
            self.close()
            raise OSError("no sound meter")
        self.held.append(meter)
        self.meter = meter

    def peak(self) -> float:
        level = ctypes.c_float()
        if not self.meter or _method(self.meter, 3, ctypes.POINTER(ctypes.c_float))(self.meter, ctypes.byref(level)):
            raise OSError("the sound meter did not answer")
        return float(level.value)

    def close(self) -> None:
        held, self.held, self.meter = self.held, [], None
        for item in reversed(held):
            _method(item, 2)(item)


def volume() -> int:
    """Speaker volume, 0 to 100."""
    try:
        with _Speakers() as speakers:
            level = ctypes.c_float()
            if _method(speakers, 9, ctypes.POINTER(ctypes.c_float))(speakers, ctypes.byref(level)):
                raise OSError("read failed")
            return int(round(level.value * 100))
    except OSError:
        raise ValueError("The speaker volume could not be read.") from None


def set_volume(percent) -> int:
    try:
        value = max(0, min(100, int(float(percent))))
    except (TypeError, ValueError):
        raise ValueError("Give a volume from 0 to 100.") from None
    try:
        with _Speakers() as speakers:
            if _method(speakers, 7, ctypes.c_float, ctypes.c_void_p)(speakers, ctypes.c_float(value / 100), None):
                raise OSError("write failed")
            _method(speakers, 14, ctypes.c_int, ctypes.c_void_p)(speakers, 0 if value else 1, None)   # un-mute, or mute at zero
    except OSError:
        raise ValueError("The speaker volume could not be changed.") from None
    return value


# ---------------------------------------------------------------------- screen brightness
def brightness(percent=None, run=_powershell) -> int:
    if percent is None:
        out = run("(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness -ErrorAction Stop | Select-Object -First 1).CurrentBrightness")
    else:
        try:
            value = max(0, min(100, int(float(percent))))
        except (TypeError, ValueError):
            raise ValueError("Give a brightness from 0 to 100.") from None
        out = run("$m = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods -ErrorAction Stop | Select-Object -First 1; "
                  f"Invoke-CimMethod -InputObject $m -MethodName WmiSetBrightness -Arguments @{{Timeout=[uint32]1;Brightness=[byte]{value}}} | Out-Null; {value}")
    if not out.strip().isdigit():
        raise ValueError("This screen's brightness cannot be changed from Windows. It works on laptop screens; use the monitor's own buttons otherwise.")
    return int(out.strip())


# ---------------------------------------------------------------------- finding files
def find_files(words: str, limit: int = 15, run=_powershell) -> list[str]:
    """Files whose name contains all the given words, newest first (uses the Windows search index)."""
    parts = [part for part in re.findall(r"[\w.\-]+", str(words)) if re.search(r"[^\W_]", part)][:5]
    if not parts or sum(len(p) for p in parts) < 2:
        raise ValueError("Say part of the file's name.")
    limit = max(1, min(40, int(limit)))
    fetch = limit * 3
    where = " AND ".join(f"System.FileName LIKE '%{p}%'" for p in parts)
    script = ("$ErrorActionPreference='Stop';try{$c=New-Object -ComObject ADODB.Connection;$r=New-Object -ComObject ADODB.Recordset;"
              "$c.Open(\"Provider=Search.CollatorDSO;Extended Properties='Application=Windows';\");"
              f"$r.Open(\"SELECT TOP {fetch} System.ItemPathDisplay FROM SYSTEMINDEX WHERE {where} ORDER BY System.DateModified DESC\",$c);"
              "while(-not $r.EOF){$r.Fields.Item(0).Value;$r.MoveNext()}}catch{}")
    rows = [line.strip() for line in run(script).splitlines() if line.strip() and not _NOISE.search(line)]
    if not rows:  # the index is off or has not seen it: look in the usual folders by name
        pattern = "*" + parts[0] + "*"
        script = ("Get-ChildItem -Path \"$HOME\\Desktop\",\"$HOME\\Documents\",\"$HOME\\Downloads\",\"$HOME\\Pictures\" -Recurse -Depth 4 -File "
                  f"-Filter '{pattern}' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First {limit} -ExpandProperty FullName")
        rows = [line.strip() for line in run(script).splitlines() if line.strip()]
        rows = [r for r in rows if all(p.lower() in r.rsplit("\\", 1)[-1].lower() for p in parts)]
    return rows[:limit]


# ---------------------------------------------------------------------- pictures of a window or the screen
def _grab(source, left: int, top: int, width: int, height: int, window: int = 0, max_width: int = 1920) -> tuple[int, int, bytes]:
    """Copy a rectangle of the screen (or one window's own picture) and return (width, height, PNG bytes)."""
    import struct
    from jcc.computer import png
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    for fn in (user32.GetDC, gdi32.CreateCompatibleDC, gdi32.CreateCompatibleBitmap, gdi32.SelectObject):
        fn.restype = ctypes.c_void_p
    scale = max(1.0, width / max_width)
    out_w, out_h = max(1, int(width / scale)), max(1, int(height / scale))
    screen = user32.GetDC(None)
    full, small = gdi32.CreateCompatibleDC(ctypes.c_void_p(screen)), gdi32.CreateCompatibleDC(ctypes.c_void_p(screen))
    full_map = gdi32.CreateCompatibleBitmap(ctypes.c_void_p(screen), width, height)
    small_map = gdi32.CreateCompatibleBitmap(ctypes.c_void_p(screen), out_w, out_h)
    old_full, old_small = gdi32.SelectObject(ctypes.c_void_p(full), ctypes.c_void_p(full_map)), gdi32.SelectObject(ctypes.c_void_p(small), ctypes.c_void_p(small_map))
    try:
        if window:
            if not user32.PrintWindow(ctypes.c_void_p(window), ctypes.c_void_p(full), 2):   # 2 = include content drawn by the graphics card
                raise ValueError("That window could not be captured. Bring it to the front and capture the whole screen instead.")
        else:
            gdi32.BitBlt(ctypes.c_void_p(full), 0, 0, width, height, ctypes.c_void_p(screen), left, top, 0x00CC0020)
        gdi32.SetStretchBltMode(ctypes.c_void_p(small), 4)
        gdi32.StretchBlt(ctypes.c_void_p(small), 0, 0, out_w, out_h, ctypes.c_void_p(full), 0, 0, width, height, 0x00CC0020)
        header = struct.pack("<IiiHHIIiiII", 40, out_w, -out_h, 1, 32, 0, 0, 0, 0, 0, 0)
        pixels, info = ctypes.create_string_buffer(out_w * out_h * 4), ctypes.create_string_buffer(header, 64)
        gdi32.GetDIBits(ctypes.c_void_p(small), ctypes.c_void_p(small_map), 0, out_h, pixels, info, 0)
    finally:
        gdi32.SelectObject(ctypes.c_void_p(full), ctypes.c_void_p(old_full))
        gdi32.SelectObject(ctypes.c_void_p(small), ctypes.c_void_p(old_small))
        for item in (full_map, small_map):
            gdi32.DeleteObject(ctypes.c_void_p(item))
        gdi32.DeleteDC(ctypes.c_void_p(full))
        gdi32.DeleteDC(ctypes.c_void_p(small))
        user32.ReleaseDC(None, ctypes.c_void_p(screen))
    raw = pixels.raw
    rgb = bytearray(out_w * out_h * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = raw[2::4], raw[1::4], raw[0::4]
    return out_w, out_h, png(out_w, out_h, bytes(rgb))


def capture_window(handle: int) -> tuple[int, int, bytes]:
    """A picture of one window, even when other windows cover it."""
    from ctypes import wintypes
    from jcc import screens
    user32 = ctypes.windll.user32
    pointer = ctypes.c_void_p(handle)
    if not user32.IsWindow(pointer) or user32.IsIconic(pointer):
        raise ValueError("That window is closed or minimised. Open it first, then try again.")
    with screens.physical():                           # its true size, on whichever screen it is and whatever that screen's scaling
        rect = wintypes.RECT()
        user32.GetWindowRect(pointer, ctypes.byref(rect))
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width < 40 or height < 40 or width > 12000 or height > 12000:
            raise ValueError("That window is too small or too large to capture.")
        return _grab(None, 0, 0, width, height, handle)


def capture_screen(hide: int = 0, screen: int = 0) -> tuple[int, int, bytes]:
    """A picture of one whole screen: the one with this number, or the one `hide` is on (the main one if neither is
    known). `hide` is a window to move out of the way first (JARVIS itself)."""
    from jcc import screens
    user32 = ctypes.windll.user32
    found = screens.screens()
    chosen = next((s for s in found if s["number"] == screen), None) or (screens.of_window(hide, found) if hide and found else None) or \
        next((s for s in found if s["main"]), None)
    hidden = bool(hide) and not user32.IsIconic(ctypes.c_void_p(hide))
    if hidden:
        user32.ShowWindow(ctypes.c_void_p(hide), 6)   # minimise
        time.sleep(0.45)
    try:
        if chosen:
            return screens.grab(chosen["left"], chosen["top"], chosen["width"], chosen["height"])
        with screens.physical():
            return screens.grab(0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
    finally:
        if hidden:
            user32.ShowWindow(ctypes.c_void_p(hide), 9)
            focus(hide)
