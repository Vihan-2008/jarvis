"""Uninstall JARVIS from inside JARVIS (Settings > Advanced), so removing it needs no terminal and no hunting for files.

It runs the uninstaller the installer left in the install folder (uninstall.ps1 on Windows, uninstall.sh on a Mac) on
its own, detached from JARVIS: the uninstaller stops JARVIS (this process included) and removes the app and its
shortcuts. Settings and chats, and the notes vault, are kept unless the owner chose to delete them; whatever is deleted
goes to the Recycle Bin / Trash. A copy of JARVIS that no installer made (a developer's checkout) is never removed.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

WINDOWS = os.name == "nt"
MAC = sys.platform == "darwin"


def app_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def _uninstaller(folder: Path) -> Path | None:
    script = folder / ("uninstall.ps1" if WINDOWS else "uninstall.sh")
    installed = (folder / ".jarvis-files").is_file() and (folder / "jcc" / "__init__.py").is_file()
    return script if installed and script.is_file() and (WINDOWS or MAC) else None


def plan(cfg, folder: Path | None = None) -> dict:
    """What uninstalling would do: whether it can be done here, and what would be kept or could be deleted."""
    folder = folder or app_dir()
    vault = getattr(cfg, "vault", None)
    return {"can": _uninstaller(folder) is not None, "app": str(folder), "data": str(cfg.state_dir), "vault": str(vault) if vault else "",
            "bin": "Recycle Bin" if WINDOWS else "Trash",
            "why": "" if _uninstaller(folder) else "This copy of JARVIS was not installed by the JARVIS installer, so it is not removed from here."}


def command(script: Path, delete_data: bool, delete_notes: bool) -> list[str]:
    if WINDOWS:
        args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", str(script), "-Quiet"]
        return args + (["-DeleteData"] if delete_data else []) + (["-DeleteNotes"] if delete_notes else [])
    return ["/bin/bash", str(script), "--quiet"] + (["--delete-data"] if delete_data else []) + (["--delete-notes"] if delete_notes else [])


def start(cfg, delete_data: bool = False, delete_notes: bool = False, folder: Path | None = None, popen=subprocess.Popen) -> dict:
    """Starts the uninstaller on its own, and returns at once: it stops JARVIS a moment later."""
    folder = folder or app_dir()
    script = _uninstaller(folder)
    if not script:
        raise ValueError(plan(cfg, folder)["why"])
    log = Path(tempfile.gettempdir()) / "jarvis-uninstall.log"
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    env["JCC_STATE_DIR"] = str(cfg.state_dir)          # (the data folder it may delete is the one this JARVIS uses)
    with open(log, "ab") as out:
        if WINDOWS:
            flags = 0x00000008 | 0x00000200 | 0x08000000 | 0x01000000   # detached, own group, no window, out of JARVIS's job
            try:
                popen(command(script, delete_data, delete_notes), cwd=tempfile.gettempdir(), env=env, stdout=out, stderr=out,
                      stdin=subprocess.DEVNULL, creationflags=flags)
            except OSError:                                              # (a job that may not be left: started inside it)
                popen(command(script, delete_data, delete_notes), cwd=tempfile.gettempdir(), env=env, stdout=out, stderr=out,
                      stdin=subprocess.DEVNULL, creationflags=flags & ~0x01000000)
        else:
            popen(command(script, delete_data, delete_notes), cwd="/", env=env, stdout=out, stderr=out, stdin=subprocess.DEVNULL,
                  start_new_session=True)
    return {"started": True, "log": str(log)}
