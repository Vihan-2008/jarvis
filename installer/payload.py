"""What goes into an installer package: the app's files as git lists them, and the version.

Both the Windows and the Mac builds use this, so the two packages always hold the same app. Only files git tracks
are packed, so a person's own config/local.toml, a .env file or anything else left in a working copy can never end
up in a package by accident.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Tracked but not part of the app: its tests, the installers themselves, the website, CI, the owner's ledger and the
# owner's own deployment tool.
LEFT_OUT_FOLDERS = ("tests/", "installer/", "website/", ".github/")
LEFT_OUT_FILES = ("LEDGER.md", "scripts/deploy.py", "scripts/export_open_source.py", "scripts/publish_open_source.py")


def app_files(repo: Path = REPO) -> list[str]:
    """The repository's tracked files that make up the app, as forward-slash paths relative to the repository."""
    listed = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], check=True, capture_output=True).stdout
    names = [n.decode("utf-8") for n in listed.split(b"\0") if n]
    kept = [n for n in names if not n.startswith(LEFT_OUT_FOLDERS) and n not in LEFT_OUT_FILES]
    missing = [n for n in kept if not (repo / n).is_file()]
    if missing:
        raise SystemExit("These tracked files are missing from the working copy: " + ", ".join(missing[:10]))
    return sorted(kept)


def version(repo: Path = REPO) -> str:
    """The version in the VERSION file at the top of the repository."""
    text = (repo / "VERSION").read_text("utf-8").strip()
    if not text or any(c.isspace() for c in text):
        raise SystemExit("VERSION must hold one version, such as 0.1.0.")
    return text
