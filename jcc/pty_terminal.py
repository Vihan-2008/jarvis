"""A real interactive terminal for the Terminal panel: Windows' built-in pseudo-console (ConPTY) on Windows, and the
standard pseudo-terminal (the pty module) on a Mac and on Linux.

Unlike the one-command-at-a-time terminal, programs here see a true console: colours, cursor
movement, prompts that wait for a key, and full-screen tools all work. It runs as the signed-in
user and only when that user opens the panel and types. On Windows it starts PowerShell; elsewhere the user's own
shell ($SHELL, or zsh on a Mac and bash on Linux).
"""
from __future__ import annotations

import codecs
import ctypes
import os
import shutil
import threading
import time
import uuid
from ctypes import wintypes
from pathlib import Path

AVAILABLE = False
MAX_BUFFER = 600_000

if os.name == "nt":
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    AVAILABLE = hasattr(kernel32, "CreatePseudoConsole")
else:
    try:
        import fcntl
        import pty  # noqa: F401 - only to learn that pseudo-terminals exist here
        import termios
        AVAILABLE = True
    except ImportError:
        AVAILABLE = False

if os.name == "nt" and AVAILABLE:          # (the ConPTY definitions; elsewhere AVAILABLE means the pty module)
    HPCON = ctypes.c_void_p

    class COORD(ctypes.Structure):
        _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
                    ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                    ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
                    ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD), ("lpReserved2", ctypes.c_void_p),
                    ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]

    class STARTUPINFOEXW(ctypes.Structure):
        _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                    ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]

    kernel32.CreatePipe.argtypes = [ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(wintypes.HANDLE), ctypes.c_void_p, wintypes.DWORD]
    kernel32.CreatePipe.restype = wintypes.BOOL
    kernel32.CreatePseudoConsole.argtypes = [COORD, wintypes.HANDLE, wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(HPCON)]
    kernel32.CreatePseudoConsole.restype = ctypes.c_long
    kernel32.ResizePseudoConsole.argtypes = [HPCON, COORD]
    kernel32.ResizePseudoConsole.restype = ctypes.c_long
    kernel32.ClosePseudoConsole.argtypes = [HPCON]
    kernel32.ClosePseudoConsole.restype = None
    kernel32.InitializeProcThreadAttributeList.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t)]
    kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
    kernel32.UpdateProcThreadAttribute.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t, ctypes.c_void_p,
                                                   ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]
    kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL
    kernel32.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
    kernel32.DeleteProcThreadAttributeList.restype = None
    kernel32.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL,
                                        wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_void_p,
                                        ctypes.POINTER(PROCESS_INFORMATION)]
    kernel32.CreateProcessW.restype = wintypes.BOOL
    kernel32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel32.ReadFile.restype = wintypes.BOOL
    kernel32.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel32.WriteFile.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL

    PSEUDOCONSOLE_ATTRIBUTE = 0x00020016
    EXTENDED_STARTUPINFO_PRESENT = 0x00080000
    STILL_ACTIVE = 259


def _size(cols, rows) -> tuple[int, int]:
    try:
        cols, rows = int(cols), int(rows)
    except (TypeError, ValueError):
        raise ValueError("Invalid terminal size.") from None
    return max(20, min(400, cols)), max(5, min(200, rows))


class _Output:
    """What a terminal has written, kept up to MAX_BUFFER characters, for the panel to read from a position."""

    def _keep(self, text: str) -> None:
        with self.changed:
            self.buffer += text
            if len(self.buffer) > MAX_BUFFER:
                drop = len(self.buffer) - MAX_BUFFER // 2
                self.buffer, self.base = self.buffer[drop:], self.base + drop
            self.changed.notify_all()

    def _ended(self) -> None:
        with self.changed:
            self.closed = True
            self.changed.notify_all()

    def read(self, since: int, wait: float = 0.0) -> dict:
        """Output written after position `since`. Waits up to `wait` seconds for something new."""
        deadline = time.monotonic() + max(0.0, min(wait, 25.0))
        with self.changed:
            while since >= self.base + len(self.buffer) and not self.closed:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self.changed.wait(remaining):
                    break
            start = max(0, since - self.base)
            data = self.buffer[start:]
            position = self.base + len(self.buffer)
            reset = since < self.base
        return {"id": self.id, "data": data, "next": position, "reset": reset, "alive": self.alive(), "cwd": self.cwd}


class _ConPtyTerminal:
    """Windows: a pseudo-console with PowerShell in it."""

    def __init__(self, cwd: Path, cols=100, rows=28, command: str | None = None):
        if not AVAILABLE:
            raise ValueError("The interactive terminal needs Windows 10 version 1809 or newer.")
        exe = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
        if not command and not exe:
            raise ValueError("PowerShell is not available.")
        self.id = uuid.uuid4().hex
        self.cwd = str(cwd)
        self.cols, self.rows = _size(cols, rows)
        self.base, self.buffer = 0, ""
        self.changed = threading.Condition()
        self.closed = False
        self.started = time.time()
        in_read, self.in_write = wintypes.HANDLE(), wintypes.HANDLE()
        self.out_read, out_write = wintypes.HANDLE(), wintypes.HANDLE()
        if not kernel32.CreatePipe(ctypes.byref(in_read), ctypes.byref(self.in_write), None, 0) or \
                not kernel32.CreatePipe(ctypes.byref(self.out_read), ctypes.byref(out_write), None, 0):
            raise ValueError("Could not start the terminal.")
        self.console = HPCON()
        result = kernel32.CreatePseudoConsole(COORD(self.cols, self.rows), in_read, out_write, 0, ctypes.byref(self.console))
        kernel32.CloseHandle(in_read)
        kernel32.CloseHandle(out_write)
        if result != 0:
            kernel32.CloseHandle(self.in_write)
            kernel32.CloseHandle(self.out_read)
            raise ValueError("Could not start the terminal.")
        size = ctypes.c_size_t()
        kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        self._attributes = ctypes.create_string_buffer(size.value)
        startup = STARTUPINFOEXW()
        startup.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
        # Without this, a child started from a service with redirected output would write to the
        # service's own log instead of the pseudo-console. Empty handles make it use the console.
        startup.StartupInfo.dwFlags = 0x00000100  # STARTF_USESTDHANDLES
        startup.lpAttributeList = ctypes.cast(self._attributes, ctypes.c_void_p)
        self.process = PROCESS_INFORMATION()
        ok = kernel32.InitializeProcThreadAttributeList(self._attributes, 1, 0, ctypes.byref(size)) and \
            kernel32.UpdateProcThreadAttribute(self._attributes, 0, PSEUDOCONSOLE_ATTRIBUTE, self.console,
                                               ctypes.sizeof(HPCON), None, None)
        line = ctypes.create_unicode_buffer(command or f'"{exe}" -NoLogo')
        ok = ok and kernel32.CreateProcessW(None, line, None, None, False, EXTENDED_STARTUPINFO_PRESENT, None,
                                            self.cwd, ctypes.byref(startup), ctypes.byref(self.process))
        if not ok:
            self._release()
            raise ValueError("Could not start the terminal.")
        self.reader = threading.Thread(target=self._read, daemon=True, name="pty-reader")
        self.reader.start()

    # ------------------------------------------------------------------ output
    def _read(self) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        chunk, got = ctypes.create_string_buffer(8192), wintypes.DWORD()
        while True:
            if not kernel32.ReadFile(self.out_read, chunk, 8192, ctypes.byref(got), None) or not got.value:
                break
            text = decoder.decode(chunk.raw[:got.value])
            with self.changed:
                self.buffer += text
                if len(self.buffer) > MAX_BUFFER:
                    drop = len(self.buffer) - MAX_BUFFER // 2
                    self.buffer, self.base = self.buffer[drop:], self.base + drop
                self.changed.notify_all()
        with self.changed:
            self.closed = True
            self.changed.notify_all()

    def alive(self) -> bool:
        if self.closed:
            return False
        code = wintypes.DWORD()
        return bool(kernel32.GetExitCodeProcess(self.process.hProcess, ctypes.byref(code))) and code.value == STILL_ACTIVE

    def read(self, since: int, wait: float = 0.0) -> dict:
        """Output written after position `since`. Waits up to `wait` seconds for something new."""
        deadline = time.monotonic() + max(0.0, min(wait, 25.0))
        with self.changed:
            while since >= self.base + len(self.buffer) and not self.closed:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self.changed.wait(remaining):
                    break
            start = max(0, since - self.base)
            data = self.buffer[start:]
            position = self.base + len(self.buffer)
            reset = since < self.base
        return {"id": self.id, "data": data, "next": position, "reset": reset, "alive": self.alive(), "cwd": self.cwd}

    # ------------------------------------------------------------------ input
    def write(self, data: str) -> None:
        if not isinstance(data, str) or len(data) > 100_000:
            raise ValueError("Too much input at once.")
        if not self.alive():
            raise ValueError("This terminal has ended. Start a new one.")
        raw, sent = data.encode("utf-8"), wintypes.DWORD()
        if raw and not kernel32.WriteFile(self.in_write, raw, len(raw), ctypes.byref(sent), None):
            raise ValueError("This terminal has ended. Start a new one.")

    def resize(self, cols, rows) -> None:
        self.cols, self.rows = _size(cols, rows)
        if not self.closed:
            kernel32.ResizePseudoConsole(self.console, COORD(self.cols, self.rows))

    def _release(self) -> None:
        if self.console:
            # Closing the console ends the programs attached to it; the reader keeps draining meanwhile.
            closer = threading.Thread(target=kernel32.ClosePseudoConsole, args=(self.console,), daemon=True)
            closer.start()
            closer.join(timeout=5)
            self.console = HPCON()
        if getattr(self, "process", None) and self.process.hProcess:
            if kernel32.WaitForSingleObject(self.process.hProcess, 800) != 0:
                kernel32.TerminateProcess(self.process.hProcess, 1)
            kernel32.CloseHandle(self.process.hThread)
            kernel32.CloseHandle(self.process.hProcess)
            self.process = PROCESS_INFORMATION()
        for name in ("in_write", "out_read"):
            handle = getattr(self, name, None)
            if handle:
                kernel32.CloseHandle(handle)
                setattr(self, name, None)
        if getattr(self, "_attributes", None) is not None:
            kernel32.DeleteProcThreadAttributeList(self._attributes)
            self._attributes = None

    def stop(self) -> None:
        if getattr(self, "_stopped", False):
            return
        self._stopped = True
        self._release()
        with self.changed:
            self.closed = True
            self.changed.notify_all()


def user_shell() -> str:
    """The shell the user would get in their own terminal: $SHELL, else zsh on a Mac and bash elsewhere."""
    import sys
    chosen = os.environ.get("SHELL", "")
    if chosen and os.path.isabs(chosen) and os.access(chosen, os.X_OK):
        return chosen
    return "/bin/zsh" if sys.platform == "darwin" and os.path.exists("/bin/zsh") else "/bin/bash"


def _window_size(fd: int, cols: int, rows: int) -> None:
    import struct
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _take_terminal() -> None:
    """In the new shell, just before it starts: make the pseudo-terminal its controlling terminal, so job control and
    Ctrl+C work as in a real terminal window. (The shell already leads a session of its own: start_new_session.)"""
    try:
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    except OSError:
        pass                                    # the shell still runs, only without job control


class _PosixPtyTerminal(_Output):
    """A Mac or Linux: a pseudo-terminal with the user's shell in it, started as a login shell in its own session."""

    def __init__(self, cwd: Path, cols=100, rows=28, command: list[str] | None = None):
        if not AVAILABLE:
            raise ValueError("The interactive terminal is not available on this system.")
        import subprocess
        self.id = uuid.uuid4().hex
        self.cwd = str(cwd)
        self.cols, self.rows = _size(cols, rows)
        self.base, self.buffer = 0, ""
        self.changed = threading.Condition()
        self.closed = False
        self.started = time.time()
        self.master, follower = os.openpty()
        try:
            _window_size(follower, self.cols, self.rows)
            argv = list(command) if command else [user_shell(), "-l"]
            env = {**os.environ, "TERM": "xterm-256color"}
            self.process = subprocess.Popen(argv, cwd=self.cwd, env=env, stdin=follower, stdout=follower, stderr=follower, close_fds=True,
                                            start_new_session=True, preexec_fn=_take_terminal)
        except (OSError, ValueError, subprocess.SubprocessError):
            os.close(self.master)
            raise ValueError("Could not start the terminal.") from None
        finally:
            os.close(follower)
        self.reader = threading.Thread(target=self._read, daemon=True, name="pty-reader")
        self.reader.start()

    def _read(self) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        while True:
            try:
                data = os.read(self.master, 8192)
            except OSError:              # (Linux reports the end of the shell as an error on the pseudo-terminal)
                data = b""
            if not data:
                break
            self._keep(decoder.decode(data))
        self._ended()

    def alive(self) -> bool:
        return not self.closed and self.process.poll() is None

    def write(self, data: str) -> None:
        if not isinstance(data, str) or len(data) > 100_000:
            raise ValueError("Too much input at once.")
        if not self.alive():
            raise ValueError("This terminal has ended. Start a new one.")
        raw = data.encode("utf-8")
        try:
            while raw:
                raw = raw[os.write(self.master, raw):]
        except OSError:
            raise ValueError("This terminal has ended. Start a new one.") from None

    def resize(self, cols, rows) -> None:
        self.cols, self.rows = _size(cols, rows)
        if not self.closed:
            try:
                _window_size(self.master, self.cols, self.rows)
            except OSError:
                pass

    def stop(self) -> None:
        if getattr(self, "_stopped", False):
            return
        self._stopped = True
        from jcc import system
        if self.process.poll() is None:
            system.kill_tree(self.process.pid)            # the shell and everything started in it
        try:
            self.process.wait(timeout=5)
        except Exception:  # noqa: BLE001 - it was told to end; the panel must not wait on it
            pass
        try:
            os.close(self.master)
        except OSError:
            pass
        self._ended()


PtyTerminal = _ConPtyTerminal if os.name == "nt" else _PosixPtyTerminal


class PtyManager:
    """At most four interactive terminals at a time, each started by the owner from the panel."""

    def __init__(self, cfg):
        self.cfg, self.sessions, self.lock = cfg, {}, threading.Lock()

    def start(self, project, cols=100, rows=28) -> dict:
        with self.lock:
            for key in [k for k, t in self.sessions.items() if not t.alive()]:
                self.sessions.pop(key).stop()
            if project and project not in self.cfg.projects:
                raise ValueError("Project not found.")
            while len(self.sessions) >= 4:
                # A closed window can leave a session behind; the oldest one makes room.
                oldest = min(self.sessions.values(), key=lambda t: t.started)
                self.sessions.pop(oldest.id).stop()
            cwd = self.cfg.projects[project].path if project else self.cfg.state_dir / "scratch"
            cwd.mkdir(parents=True, exist_ok=True)
            terminal = PtyTerminal(cwd, cols, rows)
            self.sessions[terminal.id] = terminal
            return {"id": terminal.id, "cwd": terminal.cwd, "cols": terminal.cols, "rows": terminal.rows}

    def get(self, tid: str) -> PtyTerminal:
        terminal = self.sessions.get(str(tid))
        if not terminal:
            raise ValueError("Terminal not found. Start a new one.")
        return terminal

    def stop(self, tid: str) -> dict:
        with self.lock:
            terminal = self.sessions.pop(str(tid), None)
        if terminal:
            terminal.stop()
        return {"stopped": True}

    def stop_all(self) -> None:
        with self.lock:
            sessions, self.sessions = list(self.sessions.values()), {}
        for terminal in sessions:
            terminal.stop()
