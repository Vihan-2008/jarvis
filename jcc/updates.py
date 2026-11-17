"""Updates: JARVIS finds out about a newer version, fetches it, makes sure it is genuine, and installs it.

1. Once a day (or when asked) it asks GitHub, where its releases are published, which version is the newest. Nothing
   about the owner is sent: it is one plain request for a public page.
2. A newer release carries two small files beside its packages: a list of the packages with their fingerprints
   ("jarvis-update.json") and a signature of that list ("jarvis-update.sig"), made with a private key that only JARVIS's
   maker holds (scripts/sign_release.py). The list counts only when the signature checks out with the public key built in
   below (jcc/ed25519.py). A release without a valid signature is shown but never installed by JARVIS.
3. The package for this system is fetched in the background and counts as ready only when its size and fingerprint are
   exactly those in the signed list.
4. Installing is done by jcc/update_helper.py, a program of its own: it stops JARVIS, keeps a copy of the app as it was,
   runs the same installer people use (quietly, as an upgrade: settings, notes and keys are kept), starts JARVIS again,
   and puts the old version back if the new one does not answer. With updates set to "Automatically", a ready update
   is installed when JARVIS next starts, before anything else runs; "Install and restart" in Settings does it at once.

A copy of JARVIS that its developer deploys with scripts/deploy.py, or a copy of the source code, is never touched:
those are updated the way they were made.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from jcc import ed25519, system
from jcc.config import ROOT
from jcc.vault import atomic_write, read_json

# The public half of the key JARVIS's releases are signed with. (The private half never leaves its maker's computer.)
PUBLIC_KEY = bytes.fromhex("73baf598220bd21828554600ce51239274b541c12ee843649a4d72af2f4c8d37")
API = "https://api.github.com"
DEFAULTS = {"mode": "auto", "repo": "https://github.com/Vihan-2008/jarvis", "check_hours": 24}
MODES = ("auto", "ask", "off")
MANIFEST, SIGNATURE = "jarvis-update.json", "jarvis-update.sig"
LIMIT = 300 * 1024 * 1024                 # no package of JARVIS comes near this
AGENT = "JARVIS-updater"
VERSION_SHAPE = re.compile(r"^v?(\d{1,4})\.(\d{1,4})\.(\d{1,6})$")


class UpdateError(ValueError):
    """Something about an update, in a sentence for the owner."""


# ---------------------------------------------------------------------------------------------------- what we are
def version_tuple(text) -> tuple[int, int, int] | None:
    found = VERSION_SHAPE.match(str(text or "").strip())
    return tuple(int(part) for part in found.groups()) if found else None


def current_version(root: Path | None = None) -> str:
    root = root or ROOT
    try:
        text = (root / "VERSION").read_text("utf-8").strip()
        if version_tuple(text):
            return text
    except OSError:
        pass
    from jcc import __version__
    return __version__


def package_name() -> str | None:
    """The release package this system installs from: the same ones people download."""
    return {"windows": "JARVIS-windows.zip", "mac": "JARVIS-mac.zip"}.get(system.kind())


def managed(root: Path | None = None) -> str:
    """Why this copy is not updated here ("" when it is)."""
    root = root or ROOT
    if (root / ".deployed.json").exists():
        return "updated by its developer's deploy tool"
    if (root / ".git").exists():
        return "a copy of the source code: update it with git"
    if not package_name():
        return "on Linux, where there is no ready-made package: update it from the source code"
    if not (root / ".jarvis-files").exists():
        return "not installed by the JARVIS installer, so it cannot be upgraded by it"
    return ""


# -------------------------------------------------------------------------------------------------------- settings
def settings(cfg) -> dict:
    out = dict(DEFAULTS)
    configured = cfg.raw.get("updates") if isinstance(cfg.raw.get("updates"), dict) else {}
    for key in DEFAULTS:
        if key in configured:
            out[key] = configured[key]
    chosen = read_json(cfg.state_dir / "update-settings.json", {})
    if isinstance(chosen, dict) and chosen.get("mode") in MODES:
        out["mode"] = chosen["mode"]
    if out["mode"] not in MODES:
        out["mode"] = "auto"
    out["repo"] = repo_name(out["repo"]) or repo_name(DEFAULTS["repo"])
    try:
        out["check_hours"] = max(1, min(24 * 30, int(out["check_hours"])))
    except (TypeError, ValueError):
        out["check_hours"] = DEFAULTS["check_hours"]
    return out


def repo_name(text) -> str:
    """"owner/name" from a repository's GitHub address (or from "owner/name" itself); "" when it is neither."""
    text = str(text or "").strip().removesuffix("/").removesuffix(".git")
    text = text.removeprefix("https://github.com/")
    return text if re.fullmatch(r"[A-Za-z0-9_.-]{1,40}/[A-Za-z0-9_.-]{1,100}", text) else ""


def set_mode(cfg, mode) -> dict:
    if mode not in MODES:
        raise UpdateError("Choose automatically, ask me first, or never.")
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(cfg.state_dir / "update-settings.json", json.dumps({"mode": mode}))
    return status(cfg)


# ---------------------------------------------------------------------------------------------------------- status
def _status_path(cfg) -> Path:
    return cfg.state_dir / "update-status.json"


def read_status(cfg) -> dict:
    found = read_json(_status_path(cfg), {})
    return found if isinstance(found, dict) else {}


def _save(cfg, data: dict) -> dict:
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(_status_path(cfg), json.dumps(data))
    return data


def failed_versions(cfg) -> set[str]:
    found = read_json(cfg.state_dir / "update-failed.json", [])
    return {str(v) for v in found} if isinstance(found, list) else set()


def last_result(cfg) -> dict:
    """What the last install did: {"version", "ok", "rolled_back", "problem", "at", "from"}, or {}."""
    found = read_json(cfg.state_dir / "update-result.json", {})
    return found if isinstance(found, dict) else {}


def status(cfg) -> dict:
    """Everything the window shows about updates. Never includes a path the window has no use for."""
    data = read_status(cfg)
    staged = ready(cfg)
    return {"current": current_version(), "mode": settings(cfg)["mode"], "managed": managed(), "latest": data.get("latest", ""),
            "available": bool(data.get("available")), "signed": bool(data.get("signed")), "ready": bool(staged),
            "problem": data.get("problem", ""), "notes": data.get("notes", ""), "page": data.get("page", ""),
            "checked_at": data.get("checked_at", 0), "result": last_result(cfg), "installing": data.get("installing") or None,
            "downloading": bool(data.get("downloading"))}


# ------------------------------------------------------------------------------------------------- talking to GitHub
def _open(url: str, accept: str = "*/*", timeout: float = 30.0):
    if not url.startswith("https://"):
        raise UpdateError("Updates are only fetched over a secure connection.")
    request = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": accept})
    return urllib.request.urlopen(request, timeout=timeout)


def fetch(url: str, limit: int, accept: str = "*/*") -> bytes:
    """A small file, at most `limit` bytes."""
    try:
        with _open(url, accept) as answer:
            data = answer.read(limit + 1)
    except urllib.error.HTTPError as problem:
        if problem.code in (403, 429):
            raise UpdateError("GitHub is limiting how often this network may ask (it answered " + str(problem.code) + "). JARVIS asks again later.") from None
        raise UpdateError(f"GitHub answered {problem.code}.") from None
    except (OSError, ValueError) as problem:
        from jcc import net
        raise UpdateError("GitHub could not be reached: " + net.reason(problem) + ".") from None
    if len(data) > limit:
        raise UpdateError("An update file was larger than it may be.")
    return data


def fetch_to(url: str, target: Path, size: int, digest: str) -> None:
    """A package, written to `target` only when it is exactly `size` bytes with this SHA-256."""
    partial = target.with_name(target.name + ".part")
    hasher, got = hashlib.sha256(), 0
    try:
        with _open(url, timeout=60.0) as answer, partial.open("wb") as out:
            while True:
                piece = answer.read(1 << 20)
                if not piece:
                    break
                got += len(piece)
                if got > size:
                    raise UpdateError("The download was larger than the signed list says.")
                hasher.update(piece)
                out.write(piece)
    except urllib.error.HTTPError as problem:
        partial.unlink(missing_ok=True)
        raise UpdateError(f"GitHub answered {problem.code}.") from None
    except (OSError, ValueError) as problem:
        partial.unlink(missing_ok=True)
        if isinstance(problem, UpdateError):
            raise
        from jcc import net
        raise UpdateError("The download stopped (" + net.reason(problem) + "). It is tried again later.") from None
    if got != size or hasher.hexdigest() != digest:
        partial.unlink(missing_ok=True)
        raise UpdateError("The download does not match its signed fingerprint, so it was thrown away.")
    os.replace(partial, target)


def _file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for piece in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(piece)
    return hasher.hexdigest()


def verified_manifest(body: bytes, signature_text: bytes, version: str, key: bytes | None = None) -> dict | None:
    """The signed list of a release, when its signature checks out and it is the list of this version; else None."""
    try:
        signature = bytes.fromhex(signature_text.decode("ascii").strip())
    except (UnicodeDecodeError, ValueError):
        return None
    if not ed25519.verify(PUBLIC_KEY if key is None else key, body, signature):
        return None
    try:
        manifest = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(manifest, dict) or manifest.get("app") != "JARVIS" or manifest.get("version") != version:
        return None
    files = manifest.get("files")
    if not isinstance(files, dict):
        return None
    for name, entry in files.items():
        if not (isinstance(name, str) and isinstance(entry, dict) and isinstance(entry.get("sha256"), str)
                and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) and isinstance(entry.get("size"), int)
                and not isinstance(entry.get("size"), bool) and 0 < entry["size"] <= LIMIT):
            return None
    return manifest


def check(cfg, get=None, now=None) -> dict:
    """Ask which version is the newest, and whether this copy may and should install it."""
    get = get or fetch
    now = time.time() if now is None else now
    data = read_status(cfg)
    reason = managed()
    if reason:
        return _save(cfg, {"checked_at": now, "managed": reason})
    options = settings(cfg)
    current = current_version()
    out = {"checked_at": now, "current": current, "latest": data.get("latest", ""), "available": False, "signed": False,
           "problem": "", "notes": "", "page": "", "ready": data.get("ready")}
    try:
        release = json.loads(get(f"{API}/repos/{options['repo']}/releases/latest", 2_000_000, "application/vnd.github+json"))
        tag = str(release.get("tag_name", ""))
        latest = tag[1:] if tag.startswith("v") else tag
        if not version_tuple(latest):
            raise UpdateError("The newest release has no version number JARVIS understands.")
        page = str(release.get("html_url") or "")
        out.update(latest=latest, notes=str(release.get("body") or "")[:4000],
                   page=page if page.startswith(f"https://github.com/{options['repo']}/releases/") else "")
        out["available"] = version_tuple(latest) > version_tuple(current)
        if out["available"]:
            assets = {a.get("name"): a for a in release.get("assets") or [] if isinstance(a, dict)}
            if MANIFEST not in assets or SIGNATURE not in assets:
                out["problem"] = "This version is not signed by JARVIS's maker, so JARVIS does not install it. It can be downloaded by hand from its page."
            else:
                body = get(assets[MANIFEST]["browser_download_url"], 200_000)
                signature = get(assets[SIGNATURE]["browser_download_url"], 1_000)
                manifest = verified_manifest(body, signature, latest)
                name = package_name()
                if manifest is None:
                    out["problem"] = "This version's signature does not check out, so JARVIS does not install it."
                elif name not in manifest["files"] or name not in assets:
                    out["problem"] = "This version has no package for this computer."
                else:
                    entry = manifest["files"][name]
                    out["signed"] = True
                    out["package"] = {"name": name, "url": assets[name]["browser_download_url"], "sha256": entry["sha256"], "size": entry["size"]}
    except UpdateError as problem:
        out["problem"] = str(problem)
    except (ValueError, KeyError, TypeError, AttributeError):
        out["problem"] = "GitHub's answer could not be read."
    if out.get("ready", {}) and (out["ready"] or {}).get("version") != out["latest"]:
        out["ready"] = None                                    # (a version downloaded earlier that is no longer the newest)
    return _save(cfg, out)


def due(cfg, now=None) -> bool:
    options = settings(cfg)
    if options["mode"] == "off" or managed():
        return False
    now = time.time() if now is None else now
    return now - float(read_status(cfg).get("checked_at") or 0) >= options["check_hours"] * 3600


def download(cfg) -> dict:
    """Fetch the package of the newest version, if it is signed and not fetched already."""
    data = read_status(cfg)
    package = data.get("package")
    if not (data.get("available") and data.get("signed") and isinstance(package, dict)):
        raise UpdateError("There is no signed update to fetch.")
    version = data["latest"]
    folder = cfg.state_dir / "updates" / version
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / package["name"]
    if not (target.is_file() and target.stat().st_size == package["size"] and _file_digest(target) == package["sha256"]):
        _save(cfg, {**data, "downloading": True})
        try:
            fetch_to(package["url"], target, package["size"], package["sha256"])
        finally:
            data = read_status(cfg)
            data.pop("downloading", None)
            _save(cfg, data)
    for other in (cfg.state_dir / "updates").iterdir():
        if other.is_dir() and other.name != version:
            shutil.rmtree(other, ignore_errors=True)               # (versions fetched earlier and never installed)
    data["ready"] = {"version": version, "path": str(target), "sha256": package["sha256"]}
    return _save(cfg, data)


def ready(cfg) -> dict | None:
    """The downloaded update that may be installed now: newer than this copy, not one that failed before, still there."""
    staged = read_status(cfg).get("ready")
    if not isinstance(staged, dict) or managed():
        return None
    version, path = str(staged.get("version", "")), Path(str(staged.get("path", "")))
    if not version_tuple(version) or version_tuple(version) <= version_tuple(current_version()) or version in failed_versions(cfg):
        return None
    if not path.is_file() or path.parent.parent != cfg.state_dir / "updates":
        return None
    return staged


def install_at_start(cfg) -> bool:
    return settings(cfg)["mode"] == "auto" and ready(cfg) is not None


def start_install(cfg, start: str = "background", popen=None) -> dict:
    """Hand the ready update to the install helper (jcc/update_helper.py), which runs as a program of its own: it stops
    JARVIS, so it must not be one of JARVIS's own processes. `start`: how JARVIS is started afterwards (window,
    background, listen or none)."""
    staged = ready(cfg)
    if not staged:
        raise UpdateError("There is no downloaded update to install.")
    if start not in ("window", "background", "listen", "none"):
        start = "background"
    helper = Path(staged["path"]).parent / "update_helper.py"
    shutil.copyfile(Path(__file__).with_name("update_helper.py"), helper)       # (run from a copy: the app's own files are replaced)
    python = Path(system.background_python())
    argv = [str(python), "-I", str(helper), "--package", staged["path"], "--sha256", staged["sha256"], "--version", staged["version"],
            "--app-dir", str(ROOT), "--state", str(cfg.state_dir), "--start", start]
    data = read_status(cfg)
    data["installing"] = {"version": staged["version"], "at": time.time()}
    _save(cfg, data)
    options = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "cwd": str(helper.parent), "close_fds": True}
    if system.kind() == "windows":
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        options["start_new_session"] = True
    (popen or subprocess.Popen)(argv, **options)
    return status(cfg)


def background(cfg, stop=None, pause: float = 1800.0, first: float = 180.0) -> None:
    """The service's own loop: check when due; with updates set to automatic, fetch a signed update straight away."""
    wait = (stop.wait if stop is not None else time.sleep)
    if wait(first):
        return
    while True:
        try:
            if due(cfg):
                found = check(cfg)
                if found.get("available") and found.get("signed") and settings(cfg)["mode"] == "auto" and not ready(cfg):
                    download(cfg)
        except Exception:  # noqa: BLE001 - it is tried again at the next round; the problem is in update-status.json
            pass
        if wait(pause):
            return
