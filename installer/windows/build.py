"""Build the Windows packages: dist/JARVIS-windows.zip and dist/JARVIS-Setup.exe.

    python installer/windows/build.py [--out FOLDER]

The zip holds the app's files (exactly those git lists, less tests, installers, website, CI, the ledger and the
owner's deployment tool) with install.ps1 and uninstall.ps1 at the top, for people who prefer to unpack it and run
install.ps1 themselves.

JARVIS-Setup.exe is the same zip wrapped by IExpress, the packager built into Windows, with a tiny setup.cmd that
unpacks it into a temporary folder and runs install.ps1. IExpress is used because it needs nothing downloaded; the
price is a plain look and an unsigned file (see docs/INSTALL.md). IExpress only exists on Windows, so the zip can be
built anywhere and the Setup.exe only on Windows.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from payload import REPO, app_files, version  # noqa: E402
import runtime  # noqa: E402  (installer/runtime.py: the Python the package carries)

INSTALLER_FILES = ("install.ps1", "uninstall.ps1")


def crlf(path: Path) -> bytes:
    """Windows scripts with Windows line endings, whatever the checkout did to them: cmd.exe misreads labels without."""
    return path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


def build_zip(out: Path, repo: Path = REPO, with_python: bool = True) -> Path:
    """dist/JARVIS-windows.zip: the app's files plus install.ps1 and uninstall.ps1 at the top."""
    out.mkdir(parents=True, exist_ok=True)
    target = out / "JARVIS-windows.zip"
    names = app_files(repo)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for name in names:
            z.write(repo / name, name)
        for name in INSTALLER_FILES:
            z.writestr(name, crlf(HERE / name))
        if with_python:
            # JARVIS's own Python, as one inner zip that the installer unpacks in one go (see installer/runtime.py).
            import io
            inner = io.BytesIO()
            with zipfile.ZipFile(inner, "w", zipfile.ZIP_DEFLATED) as rt:
                runtime.add_to_zip(rt, runtime.fetch("windows"), "")
            z.writestr("runtime/python.zip", inner.getvalue(), compress_type=zipfile.ZIP_STORED)
            z.writestr("runtime/VERSION", runtime.VERSION + "+" + runtime.RELEASE + "\n")
    return target


# (The quiet commands are the same as AppLaunched, for Setup started with /Q. ".\\setup.cmd", not "setup.cmd": where
# NoDefaultCurrentDirectoryInExePath is set, cmd does not look in the current folder for a bare name.)
SED = """[Version]
Class=IEXPRESS
SEDVersion=3
[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=0
HideExtractAnimation=1
UseLongFileName=1
InsideCompressed=0
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=%InstallPrompt%
DisplayLicense=%DisplayLicense%
FinishMessage=%FinishMessage%
TargetName=%TargetName%
FriendlyName=%FriendlyName%
AppLaunched=%AppLaunched%
PostInstallCmd=%PostInstallCmd%
AdminQuietInstCmd=%AdminQuietInstCmd%
UserQuietInstCmd=%UserQuietInstCmd%
SourceFiles=SourceFiles
[Strings]
InstallPrompt=
DisplayLicense=
FinishMessage=
TargetName={target}
FriendlyName=JARVIS {version} Setup
AppLaunched=cmd /c .\\setup.cmd
PostInstallCmd=<None>
AdminQuietInstCmd=cmd /c .\\setup.cmd
UserQuietInstCmd=cmd /c .\\setup.cmd
FILE0="setup.cmd"
FILE1="payload.zip"
[SourceFiles]
SourceFiles0={stage}\\
[SourceFiles0]
%FILE0%=
%FILE1%=
"""


def build_setup(out: Path, zip_path: Path, repo: Path = REPO) -> Path:
    """dist/JARVIS-Setup.exe, made by IExpress from the zip and setup.cmd."""
    iexpress = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "iexpress.exe"
    if not iexpress.is_file():
        raise SystemExit("IExpress (iexpress.exe) was not found; JARVIS-Setup.exe can only be built on Windows.")
    target = (out / "JARVIS-Setup.exe").resolve()
    target.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="jarvis-iexpress-") as work:
        stage = Path(work)
        shutil.copyfile(zip_path, stage / "payload.zip")
        (stage / "setup.cmd").write_bytes(crlf(HERE / "setup.cmd"))
        sed = stage / "jarvis.sed"
        sed.write_text(SED.format(target=target, version=version(repo), stage=stage), "ascii")
        subprocess.run([str(iexpress), "/N", "/Q", str(sed)], check=True)
        # IExpress can hand back before the file is fully written; wait for it to settle (it compresses the package a
        # little, so it can end up a little smaller than the zip: what counts is that it stops growing).
        last, steady = -1, 0
        for _ in range(600):
            size = target.stat().st_size if target.is_file() else -1
            steady = steady + 1 if size == last and size > zip_path.stat().st_size * 0.8 else 0
            if steady >= 4:
                break
            last = size
            time.sleep(0.5)
    if not target.is_file():
        raise SystemExit("IExpress did not make JARVIS-Setup.exe.")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the JARVIS Windows packages.")
    parser.add_argument("--out", default=str(REPO / "dist"), help="where to put the packages (default: dist)")
    parser.add_argument("--zip-only", action="store_true", help="make only the zip (works on any system)")
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    zip_path = build_zip(out)
    print(f"Made {zip_path} (version {version()})")
    if not args.zip_only:
        print(f"Made {build_setup(out, zip_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
