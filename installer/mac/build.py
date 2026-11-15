"""Build the Mac package: dist/JARVIS-mac.zip. Runs on any system.

    python installer/mac/build.py [--out FOLDER]
    python installer/mac/build.py --stage FOLDER      (the same content as a folder; build_dmg.sh uses this)

The package is one folder, "JARVIS Installer". Opened, it shows two things: "Install JARVIS", which a person
double-clicks in Finder, and "Read me first.txt". What is installed (the app's files: exactly those git lists, less tests,
installers, website, CI, the ledger and the owner's deployment tool; install.sh, uninstall.sh, the sources, the
ready-built copies of JARVIS's small Mac programs, and JARVIS's own Python for both kinds of Mac) is the "payload".

Built on a Mac (the release workflow, after build_helper.sh made dist/Install JARVIS.app), "Install JARVIS" is that app,
with the payload INSIDE it (Contents/Resources/jarvis-app) and signed again over it. It has to be inside: macOS runs an
app opened from a download where it lies from a hidden read-only copy of the app alone ("app translocation"), and files
beside it would not be found. Built anywhere else, "Install JARVIS" is the Terminal script "Install JARVIS.command" and
the payload is a hidden folder beside it, ".jarvis-app".

A zip made on Windows has no Unix permissions unless they are written into it, and without the executable bit Finder
will not run the .command file. So each entry's mode is set by hand (ZipInfo.external_attr), and the zip is read back
afterwards to check that the scripts are executable. Shell scripts are also given Unix line endings, whatever the
checkout did to them: bash refuses a script whose lines end in a carriage return.
"""
from __future__ import annotations

import argparse
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from payload import REPO, app_files, version  # noqa: E402
import runtime  # noqa: E402  (installer/runtime.py: the Python the package carries)

TOP = "JARVIS Installer"
PAYLOAD = ".jarvis-app"                 # (hidden in Finder: a person sees only the installer and the note)
INSTALLER_FILES = ("install.sh", "uninstall.sh", "sound_level.swift", "menu_bar.swift", "launcher.swift")      # (in PAYLOAD)
SHOWN_FILES = ("Install JARVIS.command", "Read me first.txt")                                # (at the top)
# JARVIS's two small Mac programs (the one that measures the Mac's own sound, and the menu-bar icon with its shortcuts),
# when they were built just before on a Mac (build_helper.sh, in the release workflow). install.sh builds them on the
# person's own Mac when it can, and uses these otherwise.
HELPERS = (("dist/jarvis-sound-level", "bin/jarvis-sound-level"), ("dist/jarvis-menu", "bin/jarvis-menu"),
           ("dist/jarvis-launcher", "bin/jarvis-launcher"))
EXECUTABLE = 0o755
PLAIN = 0o644


def is_script(name: str) -> bool:
    return name.endswith((".sh", ".command"))


def payload(repo: Path = REPO, with_python: bool = True) -> list[tuple[str, bytes, int]]:
    """What is installed, as (path inside the payload folder, bytes, Unix mode)."""
    items = []
    for name in app_files(repo):
        data = (repo / name).read_bytes()
        items.append((name, data.replace(b"\r\n", b"\n") if is_script(name) else data, EXECUTABLE if is_script(name) else PLAIN))
    for name in INSTALLER_FILES:
        items.append((name, (HERE / name).read_bytes().replace(b"\r\n", b"\n"), EXECUTABLE if is_script(name) else PLAIN))
    for built, placed in HELPERS:
        if (repo / built).is_file():
            items.append((placed, (repo / built).read_bytes(), EXECUTABLE))
    if with_python:
        # JARVIS's own Python for both kinds of Mac, as published (checked against its fingerprint); the installer
        # unpacks the one for the Mac it runs on.
        for which, chip in (("mac-arm64", "arm64"), ("mac-x86_64", "x86_64")):
            items.append((f"runtime/python-{chip}.tar.gz", runtime.fetch(which).read_bytes(), PLAIN))
        items.append(("runtime/VERSION", (runtime.VERSION + "+" + runtime.RELEASE + "\n").encode(), PLAIN))
    return items


def contents(repo: Path = REPO, with_python: bool = True) -> list[tuple[str, bytes, int]]:
    """Every file in the package as (path inside the package, bytes, Unix mode)."""
    items = payload(repo, with_python)
    note = (NOTE, (HERE / NOTE).read_bytes().replace(b"\r\n", b"\n"), PLAIN)
    app = installer_app(repo)
    if app:
        return [*app_with_payload(app, items), note]
    command = (COMMAND, (HERE / COMMAND).read_bytes().replace(b"\r\n", b"\n"), EXECUTABLE)
    return [*((f"{PAYLOAD}/{name}", data, mode) for name, data, mode in items), command, note]


APP_NAME = "Install JARVIS.app"
INSIDE_APP = "Contents/Resources/jarvis-app"      # (where the payload is, inside the app)
COMMAND, NOTE = SHOWN_FILES


def installer_app(repo: Path = REPO):
    """dist/Install JARVIS.app, made on a Mac by build_helper.sh (osacompile); None where it was not made, or where it
    could not be signed again once the payload is in it (anywhere but a Mac)."""
    app = repo / "dist" / APP_NAME
    if not (app / "Contents" / "Info.plist").is_file() or sys.platform != "darwin" or not shutil.which("codesign"):
        return None
    return app


def app_with_payload(app: Path, items: list[tuple[str, bytes, int]]) -> list[tuple[str, bytes, int]]:
    """Install JARVIS.app with the payload inside it, signed again (by nobody in particular, like the programs): what is
    inside a signed app is part of its signature, and an app whose signature does not match is "damaged" to macOS."""
    work = Path(tempfile.mkdtemp(prefix="jarvis-app-"))
    try:
        copy = work / APP_NAME
        shutil.copytree(app, copy, symlinks=True)
        for name, data, mode in items:
            path = copy / INSIDE_APP / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            path.chmod(mode)
        subprocess.run(["codesign", "--force", "--deep", "-s", "-", str(copy)], check=True)
        subprocess.run(["codesign", "--verify", "--deep", "--strict", str(copy)], check=True)
        found = []
        for path in sorted(copy.rglob("*")):
            if path.is_symlink() or not path.is_file():
                if path.is_symlink():
                    raise SystemExit(f"{path} is a link; the package can carry files only")
                continue
            found.append((f"{APP_NAME}/{path.relative_to(copy).as_posix()}", path.read_bytes(),
                          EXECUTABLE if path.stat().st_mode & 0o111 else PLAIN))
        return found
    finally:
        shutil.rmtree(work, ignore_errors=True)


def build_zip(out: Path, repo: Path = REPO) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    target = out / "JARVIS-mac.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data, mode in contents(repo):
            info = zipfile.ZipInfo(f"{TOP}/{name}", date_time=(2020, 1, 1, 0, 0, 0))
            info.create_system = 3                              # Unix, so Archive Utility honours the mode below
            info.external_attr = (stat.S_IFREG | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    check_zip(target)
    return target


def check_zip(target: Path) -> None:
    """Read the zip back and fail if a script is not executable or has Windows line endings."""
    with zipfile.ZipFile(target) as z:
        names = {i.filename: i for i in z.infolist()}
        inside = f"{APP_NAME}/{INSIDE_APP}" if installer_app() else PAYLOAD
        listed = [f"{inside}/{n}" for n in INSTALLER_FILES] + ([NOTE] if installer_app() else list(SHOWN_FILES))
        for name in listed:
            info = names.get(f"{TOP}/{name}")
            if info is None:
                raise SystemExit(f"{name} is missing from {target}")
            if is_script(name) and (info.create_system != 3 or not (info.external_attr >> 16) & stat.S_IXUSR):
                raise SystemExit(f"{name} is not executable in {target}")
            if b"\r" in z.read(info):
                raise SystemExit(f"{name} has Windows line endings in {target}")
        shown = sorted({n[len(TOP) + 1:].split("/")[0] for n in names if n.startswith(TOP + "/")})
        expected = sorted([APP_NAME, NOTE]) if installer_app() else sorted([PAYLOAD, *SHOWN_FILES])
        if shown != expected:
            raise SystemExit(f"the package's folder should show only the installer and the note, not {shown}")


def stage(folder: Path, repo: Path = REPO) -> Path:
    """The same content written to a folder, with the same modes, for build_dmg.sh."""
    for name, data, mode in contents(repo):
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(mode)
    return folder


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the JARVIS Mac package.")
    parser.add_argument("--out", default=str(REPO / "dist"), help="where to put JARVIS-mac.zip (default: dist)")
    parser.add_argument("--stage", help="write the package's content into this folder instead of a zip")
    args = parser.parse_args(argv)
    if args.stage:
        print(f"Staged the Mac package in {stage(Path(args.stage).resolve())}")
        return 0
    target = build_zip(Path(args.out).resolve())
    print(f"Made {target} (version {version()}); its scripts are executable inside the zip.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
