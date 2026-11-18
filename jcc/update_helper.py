"""Installs an update of JARVIS that has already been downloaded and checked, and starts JARVIS again.

JARVIS starts this as a program of its own (jcc/updates.py), from a copy outside the app's folder: it stops JARVIS and
replaces the app's files, so it may use nothing of JARVIS's own, only Python's standard library.

    python -I update_helper.py --package FILE --sha256 HEX --version X.Y.Z --app-dir DIR --state DIR --start MODE

In order:
1. The package must still have the fingerprint from the signed list (it is checked again here).
2. JARVIS is stopped: its service, its helpers and its small Mac programs.
3. A copy of the app's folder is kept (the last three are kept; the Python environment and caches are left out).
4. The package is unpacked, and its own installer is run quietly, as an upgrade, the way a person would run it: the
   owner's settings, notes, keys and choices (start at sign-in, "Hey JARVIS") are kept.
5. JARVIS is started again (window, background, listen, or not at all) and must answer within two minutes.
6. If the installer failed, the version is not the one expected, or JARVIS does not answer, the copy is put back and the
   old version started again. Either way the outcome is written to update-result.json, and step by step to update.log.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

PORT = 8765
WINDOWS = os.name == "nt"
MAC = sys.platform == "darwin"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
KEEP_BACKUPS = 3
LEFT_OUT = (".venv", "__pycache__", "runtime")      # (JARVIS's own Python is not copied: an update keeps it unless it is a new one)


class Failed(Exception):
    pass


def log(state: Path, text: str) -> None:
    try:
        with (state / "update.log").open("a", encoding="utf-8") as out:
            out.write(time.strftime("%Y-%m-%d %H:%M:%S  ") + text + "\n")
    except OSError:
        pass


def write_json(path: Path, data) -> None:
    partial = path.with_name(path.name + ".tmp")
    partial.write_text(json.dumps(data), "utf-8")
    os.replace(partial, path)


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for piece in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(piece)
    return hasher.hexdigest()


def answering(port: int = PORT) -> bool:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/", timeout=2) as response:
            return b"<title>JARVIS" in response.read(8192)
    except OSError:
        return False


# ------------------------------------------------------------------------------------------------- stopping JARVIS
def jarvis_processes(app_dir: Path, run=subprocess.run) -> list[int]:
    """JARVIS's own processes: the service, its helpers, and its small Mac programs. Never this helper itself."""
    mine = os.getpid()
    found: list[int] = []
    if WINDOWS:
        script = ("$ids = @(); try { $ids += (Get-NetTCPConnection -LocalPort %d -State Listen -ErrorAction Stop).OwningProcess } catch {}; "
                  "$ids += (Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' OR Name='python.exe'\" | "
                  "Where-Object { $_.CommandLine -match '-m jcc' }).ProcessId; $ids | Where-Object { $_ } | Select-Object -Unique" % PORT)
        done = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True, timeout=60,
                   creationflags=NO_WINDOW)
        found = [int(line) for line in done.stdout.split() if line.strip().isdigit()]
    else:
        done = run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, timeout=30)
        for line in done.stdout.splitlines():
            pid, _, command = line.strip().partition(" ")
            if not pid.isdigit() or not any(mark in command for mark in (" -m jcc", "jarvis-menu", "jarvis-sound-level")):
                continue
            if str(app_dir) in command or _cwd(int(pid), run) == str(app_dir):
                found.append(int(pid))
    return [pid for pid in found if pid != mine]


def _cwd(pid: int, run=subprocess.run) -> str:
    if os.path.isdir(f"/proc/{pid}"):
        try:
            return os.readlink(f"/proc/{pid}/cwd")
        except OSError:
            return ""
    try:
        done = run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return ""
    return next((line[1:] for line in done.stdout.splitlines() if line.startswith("n")), "")


def stop(app_dir: Path, state: Path, run=subprocess.run, alive=answering, pause=time.sleep) -> None:
    pids = jarvis_processes(app_dir, run)
    log(state, f"stopping JARVIS: {len(pids)} process(es)")
    for pid in pids:
        try:
            if WINDOWS:
                # One process at a time, never "the whole tree": this helper was started by JARVIS's service, so it is in
                # that tree. (No job is running: JARVIS installs an update only when none is.)
                run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=30, creationflags=NO_WINDOW)
            else:
                os.kill(pid, signal.SIGTERM)
        except (OSError, subprocess.SubprocessError):
            pass
    for _ in range(80):
        if not alive():
            break
        pause(0.25)
    else:
        raise Failed("JARVIS did not stop, so nothing was changed.")
    if not WINDOWS:
        pause(1.0)
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


# ------------------------------------------------------------------------------------------------- the safety copy
def backup(app_dir: Path, state: Path, version: str) -> Path:
    folder = state / "update-backups"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{version}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as out:
        for path in sorted(app_dir.rglob("*")):
            relative = path.relative_to(app_dir)
            if any(part in LEFT_OUT for part in relative.parts) or path.suffix == ".pyc" or path.is_symlink():
                continue
            if path.is_file():
                info = zipfile.ZipInfo.from_file(path, relative.as_posix())
                with path.open("rb") as source, out.open(info, "w") as sink:
                    shutil.copyfileobj(source, sink)
    for old in sorted(folder.glob("*.zip"))[:-KEEP_BACKUPS]:
        old.unlink(missing_ok=True)
    return target


def restore(app_dir: Path, saved: Path, state: Path) -> None:
    """Put the app's folder back as it was: files the new version added are removed (only files of the app: never the
    owner's own), and every file of the copy is written back with its permissions."""
    with zipfile.ZipFile(saved) as copy:
        kept = {info.filename for info in copy.infolist() if not info.is_dir()}
        listed = app_dir / ".jarvis-files"
        added = []
        if listed.exists():
            for line in listed.read_text("utf-8", errors="replace").splitlines():
                name = line.strip().replace("\\", "/")
                if name and name not in kept and ".." not in name.split("/") and not os.path.isabs(name):
                    added.append(name)
        for name in added:
            (app_dir / name).unlink(missing_ok=True)
        for info in copy.infolist():
            if info.is_dir():
                continue
            target = (app_dir / info.filename).resolve()
            if app_dir.resolve() not in target.parents:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with copy.open(info) as source, target.open("wb") as sink:
                shutil.copyfileobj(source, sink)
            mode = (info.external_attr >> 16) & 0o777
            if mode and not WINDOWS:
                os.chmod(target, mode)
    log(state, f"put the copy {saved.name} back")


# --------------------------------------------------------------------------------------------------- installing
def unpack(package: Path, into: Path) -> Path:
    """Unpack the release package and return its installer (install.ps1 on Windows, install.sh on a Mac)."""
    with zipfile.ZipFile(package) as archive:
        root = into.resolve()
        for info in archive.infolist():
            target = (into / info.filename).resolve()
            if root not in target.parents and target != root:
                raise Failed("The package holds a file that would land outside its folder, so it was not used.")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as sink:
                shutil.copyfileobj(source, sink)
            mode = (info.external_attr >> 16) & 0o777
            if mode and not WINDOWS:
                os.chmod(target, mode)
    wanted = "install.ps1" if WINDOWS else "install.sh"
    found = sorted((p for p in into.rglob(wanted) if (p.parent / "jcc" / "__init__.py").exists()), key=lambda p: len(p.parts))
    if not found:
        raise Failed("The package has no installer for this computer.")
    return found[0]


def installer_argv(installer: Path, app_dir: Path) -> list[str]:
    """The installer, quiet, as an upgrade of this folder, keeping the owner's earlier choices."""
    if WINDOWS:
        argv = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(installer), "-Quiet", "-InstallDir", str(app_dir),
                "-NoObsidian", "-NoShortcuts"]
        listed = app_dir / ".shortcuts"
        lines = listed.read_text("utf-8", errors="replace").splitlines() if listed.exists() else []
        if any(line.strip().endswith("JARVIS (background).lnk") and Path(line.strip()).is_file() for line in lines):
            argv.append("-Autostart")    # (it starts at sign-in now: it still will. A shortcut the owner removed stays removed.)
        return argv
    agent = Path.home() / "Library" / "LaunchAgents" / "local.jarvis.background.plist"
    return ["/bin/bash", str(installer), "--quiet", "--install-dir", str(app_dir), "--no-obsidian",
            "--login" if agent.exists() else "--no-login"]


def install(installer: Path, app_dir: Path, state: Path, run=subprocess.run) -> None:
    argv = installer_argv(installer, app_dir)
    log(state, "running the installer: " + " ".join(argv))
    done = run(argv, cwd=str(installer.parent), capture_output=True, text=True, timeout=1800,
               creationflags=NO_WINDOW if WINDOWS else 0)
    for line in (done.stdout + done.stderr).splitlines()[-40:]:
        log(state, "   " + line)
    if done.returncode != 0:
        raise Failed(f"The installer stopped with an error ({done.returncode}).")


def installed_version(app_dir: Path) -> str:
    try:
        return (app_dir / "VERSION").read_text("utf-8").strip()
    except OSError:
        return ""


# ---------------------------------------------------------------------------------------------- starting JARVIS
def start(app_dir: Path, mode: str, popen=subprocess.Popen) -> None:
    if mode == "none":
        return
    extra = {"background": ["--background"], "listen": ["--listen"]}.get(mode, [])
    if MAC:
        bundle = ""
        try:
            bundle = (app_dir / ".app-bundle").read_text("utf-8").strip()
        except OSError:
            pass
        if bundle and Path(bundle, "Contents", "MacOS", "JARVIS").exists():
            # Through JARVIS.app, so macOS counts it as JARVIS (what it is allowed stays the same).
            popen(["/usr/bin/open", *(["-g", "-j"] if mode == "background" else []), "-a", bundle, *(["--args", *extra] if extra else [])],
                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
    python = ""
    try:
        python = (app_dir / ".python").read_text("utf-8").splitlines()[0].strip()
    except (OSError, IndexError):
        pass
    python = python if python and Path(python).exists() else sys.executable
    options = {"cwd": str(app_dir), "env": {**os.environ, "PYTHONPATH": str(app_dir)}, "stdin": subprocess.DEVNULL,
               "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if WINDOWS:
        options["creationflags"] = NO_WINDOW | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        options["start_new_session"] = True
    popen([python, "-m", "jcc.desktop", *extra], **options)


def wait_answering(seconds: float, alive=answering, pause=time.sleep) -> bool:
    until = time.time() + seconds
    while time.time() < until:
        if alive():
            return True
        pause(1.0)
    return alive()


# ------------------------------------------------------------------------------------------------------- the run
def run_update(package: Path, sha256: str, version: str, app_dir: Path, state: Path, start_mode: str,
               run=subprocess.run, popen=subprocess.Popen, alive=answering, pause=time.sleep, wait_seconds: float = 120.0) -> dict:
    old = installed_version(app_dir)
    result = {"version": version, "from": old, "ok": False, "rolled_back": False, "problem": "", "at": time.time()}
    log(state, f"updating JARVIS {old} -> {version} in {app_dir}")
    saved = None
    try:
        if digest(package) != sha256:
            raise Failed("The downloaded update no longer matches its signed fingerprint, so it was not installed.")
        stop(app_dir, state, run, alive, pause)
        saved = backup(app_dir, state, old or "unknown")
        log(state, f"kept a copy: {saved.name}")
        with tempfile.TemporaryDirectory(prefix="jarvis-update-") as work:
            installer = unpack(package, Path(work))
            install(installer, app_dir, state, run)
        if installed_version(app_dir) != version:
            raise Failed(f"After the installer the app says it is {installed_version(app_dir) or 'no version'}, not {version}.")
        start(app_dir, start_mode, popen)
        if start_mode != "none" and not wait_answering(wait_seconds, alive, pause):
            raise Failed(f"JARVIS {version} did not answer after it was started.")
        result["ok"] = True
        log(state, f"JARVIS {version} is installed" + ("" if start_mode == "none" else " and answering"))
    except Exception as problem:  # noqa: BLE001 - whatever went wrong, the old version must come back
        result["problem"] = str(problem)[:300] if isinstance(problem, Failed) else f"The update stopped: {type(problem).__name__}: {str(problem)[:200]}"
        log(state, "problem: " + result["problem"])
        if saved is not None:
            try:
                stop(app_dir, state, run, alive, pause)
            except Failed:
                pass
            try:
                restore(app_dir, saved, state)
                result["rolled_back"] = True
            except Exception as again:  # noqa: BLE001
                log(state, f"the copy could not be put back: {again}")
        start(app_dir, start_mode, popen)                       # (the old version, or the untouched one)
        try:
            failed = json.loads((state / "update-failed.json").read_text("utf-8"))
        except (OSError, ValueError):
            failed = []
        if version not in failed:
            write_json(state / "update-failed.json", (failed if isinstance(failed, list) else []) + [version])
    write_json(state / "update-result.json", result)
    try:                                                         # (the update is no longer waiting to be installed)
        status = json.loads((state / "update-status.json").read_text("utf-8"))
        status.pop("installing", None)
        if result["ok"]:
            status.pop("ready", None)
            status["available"] = False
            status["current"] = version
        write_json(state / "update-status.json", status)
    except (OSError, ValueError):
        pass
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install a downloaded, checked update of JARVIS.")
    parser.add_argument("--package", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--app-dir", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--start", default="background", choices=("window", "background", "listen", "none"))
    args = parser.parse_args(argv)
    result = run_update(Path(args.package), args.sha256, args.version, Path(args.app_dir).resolve(), Path(args.state), args.start)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
