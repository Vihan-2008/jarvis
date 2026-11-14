"""The assistant's hands on a Mac, where the Mac has a plain way to do the thing.

Each function runs one of the Mac's own command-line programs with its arguments as a list, never through a shell:
`open` for apps, files and web pages, `pbpaste` and `pbcopy` for the clipboard, `osascript` for the volume, `pmset` to
lock the screen and `mdfind` (Spotlight) to find files. Nothing the model writes is ever put into AppleScript source:
the only AppleScript here is fixed text with a whole number in it.

Controlling other apps' windows (pressing their buttons, typing into them, looking at the screen) needs permissions
and interfaces this file does not use; on a Mac those tools are not offered at all (see WINDOWS_ONLY_TOOLS in
jcc/voice_tools.py).

Every function takes `run`, the program runner, so tests can stand in for the Mac.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

APP_FOLDERS = ("/Applications", "/Applications/Utilities", "/System/Applications", "/System/Applications/Utilities", "~/Applications")
# Folders that are never worth showing as a found file: build output, caches, other programs' insides.
NOISE = re.compile(r"[\\/](__pycache__|node_modules|\.git|\.venv|site-packages|\.Trash|Library[\\/]Caches|Library[\\/]Containers)[\\/]", re.I)


def _run(run):
    return run or subprocess.run


def installed_apps(folders=APP_FOLDERS) -> dict[str, str]:
    """{name in lower case: the app's folder} for every app in the usual places, the user's own folder last."""
    found: dict[str, str] = {}
    for folder in folders:
        root = Path(os.path.expanduser(folder))
        try:
            entries = sorted(root.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.suffix == ".app" and entry.is_dir():
                found.setdefault(entry.stem.lower(), str(entry))
    return found


def open_app(app: str, run=None) -> None:
    """Open an app by its folder (from installed_apps) or by its name, with `open -a`. The name is one argument of
    `open` and nothing else, so no word in it can become another argument or a command."""
    app = str(app).strip()
    if not app or app.startswith("-") or "\n" in app or len(app) > 300:
        raise ValueError("Give just the app's name.")
    done = _run(run)(["open", "-a", app], capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL)
    if done.returncode != 0:
        raise ValueError(f"No app called {Path(app).stem} could be opened.")


def read_clipboard(run=None) -> str:
    done = _run(run)(["pbpaste"], capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL)
    return done.stdout or ""


def write_clipboard(text: str, run=None) -> None:
    """Put text on the clipboard. It goes to pbcopy on its standard input, never on a command line."""
    _run(run)(["pbcopy"], input=str(text), text=True, capture_output=True, timeout=10)


def _osascript(line: str, run=None) -> str:
    done = _run(run)(["osascript", "-e", line], capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL)
    if done.returncode != 0:
        raise ValueError("The Mac did not answer.")
    return (done.stdout or "").strip()


def volume(run=None) -> int:
    """The speaker volume, 0 to 100."""
    try:
        return int(_osascript("output volume of (get volume settings)", run))
    except ValueError:
        raise ValueError("The speaker volume could not be read.") from None


def set_volume(percent, run=None) -> int:
    try:
        value = max(0, min(100, int(float(percent))))
    except (TypeError, ValueError):
        raise ValueError("Give a volume from 0 to 100.") from None
    try:
        _osascript(f"set volume output volume {value}", run)        # (a whole number: nothing else is ever written into the script)
    except ValueError:
        raise ValueError("The speaker volume could not be changed.") from None
    return value


def change_volume(steps: int, run=None) -> int:
    """Louder or quieter by a few steps, as the volume keys would (each step is about 6 percent)."""
    return set_volume(volume(run) + 6 * int(steps), run)


def toggle_mute(run=None) -> None:
    _osascript("set volume output muted not (output muted of (get volume settings))", run)


def lock(run=None) -> None:
    """Put the screen to sleep, which locks the Mac when it asks for the password on waking (its usual setting)."""
    _run(run)(["pmset", "displaysleepnow"], capture_output=True, timeout=10, stdin=subprocess.DEVNULL)


def _words(words: str) -> list[str]:
    parts = [part for part in re.findall(r"[\w.\-]+", str(words)) if re.search(r"[^\W_]", part)][:5]
    if not parts or sum(len(p) for p in parts) < 2:
        raise ValueError("Say part of the file's name.")
    return parts


def find_files(words: str, limit: int = 15, run=None, home: Path | None = None, seconds: float = 8.0) -> list[str]:
    """Files in the home folder whose name contains all the given words, newest first. Spotlight answers first; when it
    is off or finds nothing, the usual folders are walked by name, for a few seconds at most."""
    parts = _words(words)
    limit = max(1, min(40, int(limit)))
    home = Path(home or Path.home())
    rows: list[str] = []
    try:
        done = _run(run)(["mdfind", "-onlyin", str(home), "-name", parts[0]], capture_output=True, text=True, timeout=seconds,
                         stdin=subprocess.DEVNULL)
        rows = [line.strip() for line in (done.stdout or "").splitlines() if line.strip()]
    except (OSError, subprocess.TimeoutExpired):
        rows = []
    rows = [r for r in rows if not NOISE.search(r) and all(p.lower() in Path(r).name.lower() for p in parts)]
    if not rows:
        rows = walk(home, parts, limit, seconds)
    try:
        rows.sort(key=lambda r: os.path.getmtime(r), reverse=True)
    except OSError:
        pass
    return rows[:limit]


def walk(home: Path, parts: list[str], limit: int, seconds: float) -> list[str]:
    """Look by name in the folders people keep their files in, four levels deep, for a few seconds at most."""
    until = time.monotonic() + seconds
    found: list[str] = []
    for top in ("Desktop", "Documents", "Downloads", "Pictures", "Movies", "Music"):
        start = home / top
        if not start.is_dir():
            continue
        for folder, subfolders, files in os.walk(start):
            depth = len(Path(folder).relative_to(start).parts)
            subfolders[:] = [s for s in subfolders if not s.startswith(".") and s not in ("node_modules", "__pycache__") and depth < 4]
            for name in files:
                if all(p.lower() in name.lower() for p in parts):
                    found.append(str(Path(folder) / name))
            if len(found) >= limit * 3 or time.monotonic() > until:
                return found
    return found
