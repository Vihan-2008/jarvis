"""Sign a JARVIS release, so that copies of JARVIS will install it (jcc/updates.py).

    python scripts/sign_release.py --new-key          make the signing key (once): the private half goes into this
                                                      computer's key store, and the public half is printed, to be put
                                                      into PUBLIC_KEY in jcc/updates.py
    python scripts/sign_release.py v0.1.4             sign that release: waits until its packages are built, fetches
                                                      them, lists their fingerprints in jarvis-update.json, signs the list
                                                      (jarvis-update.sig) and adds both files to the release
    python scripts/sign_release.py --export-key       print the private key, for its owner to keep in a password
                                                      manager (without it no further release can be signed)

The private key never leaves the key store except with --export-key, and is never written to a file. Someone who took
over the GitHub account could change a release's packages, but could not sign them: every copy of JARVIS would refuse
them. Adding the files to the release needs a GitHub sign-in with permission to write to the repository; it is taken
from git's own credential helper (or GITHUB_TOKEN), and never printed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets as random
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jcc import ed25519, secrets, updates  # noqa: E402

KEY_NAME = "update-signing"
PACKAGES = ("JARVIS-Setup.exe", "JARVIS-windows.zip", "JARVIS-mac.zip", "JARVIS.dmg")


def private_key() -> bytes:
    text = os.environ.get("JCC_UPDATE_SIGNING_KEY") or secrets._cred_read(KEY_NAME) or ""
    try:
        seed = bytes.fromhex(text.strip())
    except ValueError:
        seed = b""
    if len(seed) != 32:
        raise SystemExit("There is no signing key on this computer. Make one with --new-key (once), or set JCC_UPDATE_SIGNING_KEY.")
    return seed


def manifest_for(version: str, files: dict[str, bytes]) -> bytes:
    """The list of a release's packages and their fingerprints, as the exact bytes that are signed."""
    listed = {name: {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)} for name, data in sorted(files.items())}
    body = {"app": "JARVIS", "version": version, "tag": "v" + version, "signed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "files": listed}
    return json.dumps(body, indent=1, sort_keys=True).encode("utf-8")


def sign(seed: bytes, body: bytes) -> bytes:
    """The signature file's content: the signature in hex. Checked against the key built into JARVIS before it is used."""
    signature = ed25519.sign(seed, body)
    if not ed25519.verify(updates.PUBLIC_KEY, body, signature):
        raise SystemExit("This computer's signing key is not the one built into JARVIS (PUBLIC_KEY in jcc/updates.py). Nothing was signed.")
    return signature.hex().encode("ascii")


# --------------------------------------------------------------------------------------------------------- GitHub
def token() -> str:
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"]
    done = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n", capture_output=True, text=True,
                          env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}, timeout=60)
    found = next((line[9:] for line in done.stdout.splitlines() if line.startswith("password=")), "")
    if not found:
        raise SystemExit("No GitHub sign-in was found (git credential fill, or GITHUB_TOKEN).")
    return found


def call(method: str, url: str, data: bytes | None = None, kind: str = "application/json", auth: str = "") -> tuple[int, bytes]:
    headers = {"User-Agent": "JARVIS-release-signer", "Accept": "application/vnd.github+json"}
    if auth:
        headers["Authorization"] = "Bearer " + auth
    if data is not None:
        headers["Content-Type"] = kind
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=300) as answer:
            return answer.status, answer.read()
    except urllib.error.HTTPError as problem:
        return problem.code, problem.read()


def sign_release(tag: str, repo: str, wait_minutes: float = 30.0) -> None:
    version = tag[1:] if tag.startswith("v") else tag
    if not updates.version_tuple(version):
        raise SystemExit(f"{tag} is not a version tag such as v0.1.4.")
    seed = private_key()
    auth = token()
    api = f"https://api.github.com/repos/{repo}"
    until = time.time() + wait_minutes * 60
    while True:
        status, raw = call("GET", f"{api}/releases/tags/{tag}", auth=auth)
        release = json.loads(raw) if status == 200 else {}
        assets = {a["name"]: a for a in release.get("assets", [])}
        if all(name in assets for name in PACKAGES):
            break
        if time.time() > until:
            raise SystemExit(f"The release {tag} does not have all four packages yet: {sorted(assets)}")
        print(f"waiting for the release {tag} to be built...", flush=True)
        time.sleep(30)
    files = {}
    for name in PACKAGES:
        status, data = call("GET", assets[name]["browser_download_url"])
        if status != 200 or len(data) != assets[name]["size"]:
            raise SystemExit(f"{name} could not be fetched whole ({status}).")
        files[name] = data
        print(f"{name}: {len(data)} bytes, sha256 {hashlib.sha256(data).hexdigest()[:16]}...", flush=True)
    body = manifest_for(version, files)
    signature = sign(seed, body)
    upload_base = release["upload_url"].split("{")[0]
    for name, data, kind in ((updates.MANIFEST, body, "application/json"), (updates.SIGNATURE, signature, "text/plain")):
        if name in assets:
            call("DELETE", f"{api}/releases/assets/{assets[name]['id']}", auth=auth)
        status, raw = call("POST", f"{upload_base}?name={name}", data, kind, auth)
        if status not in (200, 201):
            raise SystemExit(f"{name} could not be added to the release ({status}).")
        print(f"added {name} to {tag}", flush=True)
    print(f"{tag} is signed: copies of JARVIS will install it.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sign a JARVIS release.")
    parser.add_argument("tag", nargs="?", help="the release to sign, such as v0.1.4")
    parser.add_argument("--repo", default=updates.repo_name(updates.DEFAULTS["repo"]))
    parser.add_argument("--new-key", action="store_true", help="make the signing key (once)")
    parser.add_argument("--replace", action="store_true", help="with --new-key: replace an existing key")
    parser.add_argument("--export-key", action="store_true", help="print the private key, to keep it safe")
    args = parser.parse_args(argv)
    if args.new_key:
        if secrets._cred_read(KEY_NAME) and not args.replace:
            raise SystemExit("There is a signing key already. Copies of JARVIS trust only that one; --replace makes a new one anyway.")
        seed = random.token_bytes(32)
        secrets.store(KEY_NAME, seed.hex())
        if secrets._cred_read(KEY_NAME) != seed.hex():
            raise SystemExit("The key could not be saved in this computer's key store.")
        print("The private key is in this computer's key store. Keep a copy (--export-key) somewhere safe, such as a password manager.")
        print("Put this public key into PUBLIC_KEY in jcc/updates.py:")
        print(ed25519.public_key(seed).hex())
        return 0
    if args.export_key:
        print(private_key().hex())
        return 0
    if not args.tag:
        parser.error("give a release tag, such as v0.1.4")
    sign_release(args.tag, args.repo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
