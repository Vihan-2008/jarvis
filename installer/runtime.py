"""The Python that JARVIS's packages carry, so that nobody has to install Python first.

A relocatable CPython (python-build-standalone, the "install_only_stripped" builds: the whole standard library,
Tk included, for the folder picker), pinned by name and checked against its published SHA-256 before it is used.
The Windows package carries the Windows build; the Mac package carries both Mac builds, and its installer takes the
one for the Mac it runs on, so nobody has to know which chip their Mac has.

The archives are fetched at build time into a cache folder (dist/runtime-cache by default) and reused from there.
"""
from __future__ import annotations

import hashlib
import io
import os
import tarfile
import urllib.request
import zipfile
from pathlib import Path

RELEASE = "20261026"
VERSION = "3.12.16"
BASE = f"https://github.com/astral-sh/python-build-standalone/releases/download/{RELEASE}/"
BUILDS = {   # name in the packages -> (archive, its SHA-256 as published in the release's SHA256SUMS)
    "windows": (f"cpython-{VERSION}+{RELEASE}-x86_64-pc-windows-msvc-install_only_stripped.tar.gz",
                "1f2ab53880fc67ea323398c6388e05af28addc99a8e389209f08a51fdff4b149"),
    "mac-arm64": (f"cpython-{VERSION}+{RELEASE}-aarch64-apple-darwin-install_only_stripped.tar.gz",
                  "353d5f1b4fd2715e7053f12f068435d5bbad16b91e057006b5d01e0925709a7e"),
    "mac-x86_64": (f"cpython-{VERSION}+{RELEASE}-x86_64-apple-darwin-install_only_stripped.tar.gz",
                   "37c38fda76fec1fbf310adcbafb7f0d96af13b5511bf8ea954c3aa8eec185734"),
}
CACHE = Path(__file__).resolve().parents[1] / "dist" / "runtime-cache"


def fetch(which: str, cache: Path = CACHE) -> Path:
    """The archive for one build, from the cache or downloaded, and always checked against its SHA-256."""
    name, sha = BUILDS[which]
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / name
    if target.is_file() and _sha(target) == sha:
        return target
    url = BASE + name.replace("+", "%2B")
    part = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "JARVIS-build"})
    with urllib.request.urlopen(request, timeout=300) as answer, part.open("wb") as out:
        while chunk := answer.read(1 << 20):
            out.write(chunk)
    got = _sha(part)
    if got != sha:
        part.unlink(missing_ok=True)
        raise SystemExit(f"The Python download {name} does not match its published fingerprint ({got} is not {sha}).")
    os.replace(part, target)
    return target


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def add_to_zip(z: zipfile.ZipFile, archive: Path, prefix: str) -> int:
    """Put the archive's python/ folder into the zip under `prefix` (for example "runtime/python/"), keeping each
    file's permissions (a Mac needs its programs marked runnable). Returns how many files were added."""
    count = 0
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            if not member.name.startswith("python/") or member.name.startswith("python/../"):
                continue
            rel = member.name[len("python/"):]
            if not rel or ".." in Path(rel).parts:
                continue
            if member.issym():
                # (a link inside the build, such as bin/python3 -> python3.12: kept as a link)
                info = zipfile.ZipInfo(prefix + rel)
                info.external_attr = (0o120777 << 16)
                z.writestr(info, member.linkname)
                count += 1
                continue
            if not member.isfile():
                continue
            data = tar.extractfile(member).read()
            info = zipfile.ZipInfo(prefix + rel, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = ((member.mode & 0o777) | 0o100000) << 16
            z.writestr(info, data)
            count += 1
    return count


def main() -> int:
    for which in BUILDS:
        print(which, fetch(which))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


_ = io  # (kept for callers that build archives in memory)
