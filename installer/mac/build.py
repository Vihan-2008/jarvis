"""Build the Mac package: dist/JARVIS-mac.zip. Runs on any system.

    python installer/mac/build.py [--out FOLDER]
    python installer/mac/build.py --stage FOLDER      (the same content as a folder; build_dmg.sh uses this)

The package is one folder, "JARVIS Installer", holding the app's files (exactly those git lists, less tests,
installers, website, CI, the ledger and the owner's deployment tool), install.sh, uninstall.sh and
"Install JARVIS.command", which a person double-clicks in Finder.

A zip made on Windows has no Unix permissions unless they are written into it, and without the executable bit Finder
will not run the .command file. So each entry's mode is set by hand (ZipInfo.external_attr), and the zip is read back
afterwards to check that the scripts are executable. Shell scripts are also given Unix line endings, whatever the
checkout did to them: bash refuses a script whose lines end in a carriage return.
"""
from __future__ import annotations

import argparse
import stat
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from payload import REPO, app_files, version  # noqa: E402

TOP = "JARVIS Installer"
INSTALLER_FILES = ("install.sh", "uninstall.sh", "Install JARVIS.command", "sound_level.swift", "menu_bar.swift")
# JARVIS's two small Mac programs (the one that measures the Mac's own sound, and the menu-bar icon with its shortcuts),
# when they were built just before on a Mac (build_helper.sh, in the release workflow). install.sh builds them on the
# person's own Mac when it can, and uses these otherwise.
HELPERS = (("dist/jarvis-sound-level", "bin/jarvis-sound-level"), ("dist/jarvis-menu", "bin/jarvis-menu"))
EXECUTABLE = 0o755
PLAIN = 0o644


def is_script(name: str) -> bool:
    return name.endswith((".sh", ".command"))


def contents(repo: Path = REPO) -> list[tuple[str, bytes, int]]:
    """Every file in the package as (path inside the package, bytes, Unix mode)."""
    items = []
    for name in app_files(repo):
        data = (repo / name).read_bytes()
        items.append((name, data.replace(b"\r\n", b"\n") if is_script(name) else data, EXECUTABLE if is_script(name) else PLAIN))
    for name in INSTALLER_FILES:
        items.append((name, (HERE / name).read_bytes().replace(b"\r\n", b"\n"), EXECUTABLE if is_script(name) else PLAIN))
    for built, placed in HELPERS:
        if (repo / built).is_file():
            items.append((placed, (repo / built).read_bytes(), EXECUTABLE))
    return items


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
        for name in INSTALLER_FILES:
            info = names.get(f"{TOP}/{name}")
            if info is None:
                raise SystemExit(f"{name} is missing from {target}")
            if is_script(name) and (info.create_system != 3 or not (info.external_attr >> 16) & stat.S_IXUSR):
                raise SystemExit(f"{name} is not executable in {target}")
            if b"\r" in z.read(info):
                raise SystemExit(f"{name} has Windows line endings in {target}")


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
