"""Build the Windows installer and use it for real, inside one temporary folder, then remove that folder.

    python installer/windows/test_install.py

Exits non-zero on the first failure, so CI can run it. What it does:

1. Builds JARVIS-Setup.exe and JARVIS-windows.zip into the temporary folder.
2. Unpacks the Setup.exe with its own "extract only" switch (/C), which installs nothing, and unpacks the zip inside.
3. Runs that install.ps1 with -Quiet, an install folder, a vault and a shortcut folder all in the temporary folder.
4. Checks the files, ".python", the shortcut, config/local.toml, the vault's notes, and that the installed copy runs
   (`python -m jcc --help` and `python -m jcc usage`, which start nothing) with every app folder in the temporary
   folder too.
5. Installs again as an upgrade, and checks that local.toml and a file of the person's own survived while a file the
   old version shipped and the new one does not was removed.
6. Runs the uninstaller and checks that the app and the shortcut are gone and the vault is still there.

It never touches the real Desktop, Start menu, app data or vault: every place the installer or the app would write
to is pointed into the temporary folder.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build  # noqa: E402

POWERSHELL = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass"]


class Failed(Exception):
    pass


def check(condition: bool, what: str) -> None:
    if not condition:
        raise Failed(what)
    print(f"  ok  {what}")


def run(argv: list[str], env: dict, cwd: Path | None = None, timeout: int = 300) -> str:
    done = subprocess.run(argv, env=env, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace")
    output = (done.stdout or "") + (done.stderr or "")
    if done.returncode != 0:
        raise Failed(f"{' '.join(map(str, argv))} exited with {done.returncode}:\n{output}")
    return output


def shortcut(link: Path, env: dict) -> tuple[str, str, str]:
    """A shortcut's target, arguments and start-in folder, read through the same Windows object that made it."""
    script = ("$l = (New-Object -ComObject WScript.Shell).CreateShortcut($env:JARVIS_LINK); "
              "Write-Output $l.TargetPath; Write-Output $l.Arguments; Write-Output $l.WorkingDirectory")
    lines = run(POWERSHELL + ["-Command", script], {**env, "JARVIS_LINK": str(link)}).splitlines()
    return lines[0].strip(), lines[1].strip(), lines[2].strip()


def main() -> int:
    if os.name != "nt":
        print("This test is for Windows.")
        return 1
    tmp = Path(tempfile.mkdtemp(prefix="jarvis-install-test-"))
    try:
        test(tmp)
    except Failed as problem:
        print(f"FAILED: {problem}")
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("The Windows installer test passed.")
    return 0


def test(tmp: Path) -> None:
    dist, unpacked, payload = tmp / "dist", tmp / "unpacked", tmp / "payload"
    app, vault, links, state = tmp / "app", tmp / "vault", tmp / "links", tmp / "state"
    env = {**os.environ, "JCC_STATE_DIR": str(state), "JCC_VAULT": str(vault), "JCC_JOBS_ROOT": str(tmp / "jobs"),
           "JCC_PROJECTS_ROOT": str(tmp / "projects"), "JCC_VOICE_STATE": str(state),
           "JCC_NO_CREDMAN": "1", "JCC_NO_SCREEN": "1"}
    env.pop("PYTHONPATH", None)

    print("Building the packages")
    zip_path = build.build_zip(dist)
    setup = build.build_setup(dist, zip_path)
    check(setup.is_file() and setup.stat().st_size > zip_path.stat().st_size, "JARVIS-Setup.exe was made")
    names = zipfile.ZipFile(zip_path).namelist()
    check("install.ps1" in names and "uninstall.ps1" in names and "jcc/firstrun.py" in names, "the zip has install.ps1 and the app")
    check(not any(n.startswith(("tests/", "installer/", ".github/", "website/")) or n in ("LEDGER.md", "scripts/deploy.py", "config/local.toml")
                  for n in names), "the zip leaves out tests, installers, CI, the ledger, deploy.py and local.toml")
    check(b"asInvoker" in setup.read_bytes(), "JARVIS-Setup.exe asks for no administrator rights")

    print("Unpacking JARVIS-Setup.exe (extract only, nothing runs)")
    unpacked.mkdir()
    subprocess.run([str(setup), "/Q", "/C", f"/T:{unpacked}"], check=True, timeout=120)
    check((unpacked / "setup.cmd").is_file() and (unpacked / "payload.zip").is_file(), "the Setup.exe holds setup.cmd and payload.zip")
    with zipfile.ZipFile(unpacked / "payload.zip") as z:
        z.extractall(payload)

    install = POWERSHELL + ["-File", str(payload / "install.ps1"), "-Quiet", "-InstallDir", str(app), "-Vault", str(vault),
                            "-ShortcutDir", str(links), "-NoObsidian", "-Python", sys.executable]
    print("Installing")
    print(run(install, env))
    check((app / "jcc" / "__init__.py").is_file() and (app / "config" / "default.toml").is_file(), "the app's files were copied")
    check(not (app / "tests").exists() and not (app / "scripts" / "deploy.py").exists() and not (app / "LEDGER.md").exists(),
          "nothing left out of the package was installed")
    pythonw = (app / ".python").read_text("utf-8").strip()
    check(Path(pythonw).is_file() and Path(pythonw).name.lower() in ("pythonw.exe", "python.exe"), f".python names {pythonw}")
    check((app / "uninstall.ps1").is_file(), "uninstall.ps1 is in the install folder")
    check((app / "jarvis.ico").is_file(), "the icon was written")
    target, arguments, start_in = shortcut(links / "JARVIS.lnk", env)
    check(Path(target) == Path(pythonw), "the shortcut starts pythonw.exe")
    check(arguments == "-m jcc.desktop", "the shortcut's arguments are -m jcc.desktop")
    check(Path(start_in) == app, "the shortcut starts in the install folder")
    local = tomllib.loads((app / "config" / "local.toml").read_text("utf-8"))
    check(local["paths"]["vault"] == str(vault), "config/local.toml names the vault")
    for note in ("Start here.md", "Inbox.md", "Dashboard.md", "System/JARVIS Guide.md", ".obsidian/app.json"):
        check((vault / note).is_file(), f"the vault has {note}")
    check((state / "settings-schema.json").is_file(), "the app's data went to the temporary data folder")

    print("Running the installed copy")
    python = str(Path(pythonw).with_name("python.exe")) if Path(pythonw).with_name("python.exe").is_file() else pythonw
    help_text = run([python, "-m", "jcc", "--help"], env, cwd=app)
    check("setup-vault" in help_text, "python -m jcc --help works from the installed copy")
    where = run([python, "-c", "import jcc; print(jcc.__file__)"], env, cwd=app).strip()
    check(Path(where).parent == app / "jcc", "the installed copy is the one that runs")
    run([python, "-m", "jcc", "usage"], env, cwd=app)
    check(True, "python -m jcc usage works from the installed copy")

    print("Upgrading over the existing install")
    settings = app / "config" / "local.toml"
    settings.write_text(settings.read_text("utf-8") + "\n[safety]\nprivate_terms = [\"kept-term\"]\n", "utf-8")
    (app / "my own notes.txt").write_text("mine", "utf-8")
    (app / "jcc" / "retired_module.py").write_text("# shipped by an older version", "utf-8")
    with open(app / ".jarvis-files", "a", encoding="utf-8") as f:
        f.write("jcc\\retired_module.py\r\n")
    print(run(install, env))
    local = tomllib.loads(settings.read_text("utf-8"))
    check(local["safety"]["private_terms"] == ["kept-term"] and local["paths"]["vault"] == str(vault), "config/local.toml survived the upgrade")
    check((app / "my own notes.txt").read_text("utf-8") == "mine", "a file of the person's own survived the upgrade")
    check(not (app / "jcc" / "retired_module.py").exists(), "a file only the older version shipped was removed")
    check((links / "JARVIS.lnk").is_file(), "the shortcut is still there")

    print("Uninstalling")
    print(run(POWERSHELL + ["-File", str(app / "uninstall.ps1"), "-Quiet"], env))
    check(not app.exists(), "the install folder is gone")
    check(not (links / "JARVIS.lnk").exists(), "the shortcut is gone")
    check((vault / "Start here.md").is_file() and (vault / "Inbox.md").is_file(), "the vault and its notes are still there")
    check((state / "settings-schema.json").is_file(), "the app's data folder is still there")


if __name__ == "__main__":
    sys.exit(main())
