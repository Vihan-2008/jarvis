"""What differs between Windows, macOS and Linux, in one place.

JARVIS was written on Windows. The rest of the app asks here instead of deciding for itself, so each difference is
written once and tested once: how to start a program without a console window, which Python runs in the background,
which browser can show the app window, how a file or a web page is opened, which shell runs a line the assistant was
asked to run, and how a program is ended together with everything it started.

Every function reads the system from PLATFORM when it is called, so a test can stand in for another system by changing
that one attribute. Nothing here reaches a Windows-only name unless the system really is Windows.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

PLATFORM = sys.platform
WINDOWS = PLATFORM == "win32"
MAC = PLATFORM == "darwin"
LINUX = PLATFORM.startswith("linux")


def kind() -> str:
    """The kind of system: windows, mac or linux (anything that is neither Windows nor a Mac is treated as Linux)."""
    if PLATFORM == "win32":
        return "windows"
    if PLATFORM == "darwin":
        return "mac"
    return "linux"


def name() -> str:
    """This system in plain words, for sentences the owner reads."""
    return {"windows": "Windows", "mac": "macOS", "linux": "Linux"}[kind()]


def no_window() -> int:
    """The creationflags that start a program without a console window. Only Windows opens one, so elsewhere it is 0."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if kind() == "windows" else 0


def background_python() -> str:
    """The Python that runs JARVIS's helpers in the background: pythonw.exe beside this Python on Windows (it opens no
    console window), and this Python everywhere else."""
    here = Path(sys.executable)
    if kind() == "windows":
        quiet = here.with_name("pythonw.exe")
        if quiet.exists():
            return str(quiet)
    return str(here)


def _windows_browsers() -> list[str]:
    roots = [os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), os.environ.get("ProgramFiles", r"C:\Program Files"),
             os.environ.get("LOCALAPPDATA", "")]
    tails = (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe",
             r"BraveSoftware\Brave-Browser\Application\brave.exe")
    found = [str(Path(root) / tail) for tail in tails for root in roots if root and (Path(root) / tail).exists()]
    found += [p for p in (shutil.which(n) for n in ("msedge", "chrome", "chromium")) if p]
    return found


MAC_BROWSERS = ("Google Chrome.app/Contents/MacOS/Google Chrome", "Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                "Brave Browser.app/Contents/MacOS/Brave Browser", "Chromium.app/Contents/MacOS/Chromium")
MAC_APP_ROOTS = ("/Applications", "~/Applications")
LINUX_BROWSERS = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "microsoft-edge-stable", "brave-browser")


def browsers() -> list[str]:
    """The Chromium-family browsers on this system, best first, as full paths. Only these can open the app in a window
    of its own (--app=...), so Safari and Firefox are not counted."""
    here = kind()
    if here == "windows":
        found = _windows_browsers()
    elif here == "mac":
        roots = [Path(os.path.expanduser(root)) for root in MAC_APP_ROOTS]
        found = [str(root / tail) for tail in MAC_BROWSERS for root in roots if (root / tail).exists()]
    else:
        found = [p for p in (shutil.which(n) for n in LINUX_BROWSERS) if p]
    return list(dict.fromkeys(found))


def _opener() -> str:
    return "open" if kind() == "mac" else "xdg-open"


def open_path(path, run=None) -> None:
    """Open a file or a folder with the program the system uses for it, as if the owner had double-clicked it. The path
    is made absolute, so it can never be read as an option of the opener, and it is passed as one argument, never
    through a shell."""
    target = str(Path(path).resolve())
    if kind() == "windows" and run is None:
        os.startfile(target)  # noqa: S606 - the caller has checked the path
        return
    (run or subprocess.Popen)([_opener(), target], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_url(url: str, run=None) -> None:
    """Open a web address (or a mailto: link) in the owner's own browser or mail app. Only these kinds of address are
    opened: anything else could start a program."""
    url = str(url)
    if url.split(":", 1)[0].lower() not in ("http", "https", "mailto"):
        raise ValueError("Only web addresses and mail links can be opened.")
    if kind() == "windows" and run is None:
        os.startfile(url)  # noqa: S606 - a web address or a mail link, checked above
        return
    (run or subprocess.Popen)([_opener(), url], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def shell_command(text: str) -> list[str]:
    """The argv that runs one line of shell for the assistant's run_command: PowerShell on Windows, the owner's usual
    zsh on a Mac (bash when zsh is missing), and bash on Linux. The line is one argument; nothing is joined into it."""
    here = kind()
    if here == "windows":
        return ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", text]
    if here == "mac" and os.path.exists("/bin/zsh"):
        return ["/bin/zsh", "-lc", text]
    return ["/bin/bash", "-lc", text]


def shell_name() -> str:
    """The shell shell_command uses, in plain words, for the assistant's tool description."""
    return {"windows": "PowerShell", "mac": "zsh", "linux": "bash"}[kind()]


def own_group() -> dict:
    """Popen arguments that put a program in its own process group off Windows, so kill_tree can end it together with
    everything it started. Windows needs nothing: taskkill follows the tree itself."""
    return {} if kind() == "windows" else {"start_new_session": True}


def kill_tree(pid: int, run=None) -> None:
    """End a program and every program it started. A program that has already ended is fine."""
    run = run or subprocess.run
    if not isinstance(pid, int) or pid <= 0:
        return
    if kind() == "windows":
        run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=no_window())
        return
    try:
        group = os.getpgid(pid)
    except (OSError, AttributeError):
        return
    try:
        if group != os.getpgrp():           # its own group (started with own_group): end the whole group
            os.killpg(group, signal.SIGKILL)
        else:                               # it shares JARVIS's own group: end only that program, never JARVIS itself
            os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
