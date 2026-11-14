"""Pictures made for the chat. Uses the free Pollinations image service; no account or key."""
from __future__ import annotations

import base64
import re
import secrets
import urllib.request
from urllib.parse import quote

from jcc.redact import redact

ENDPOINT = "https://image.pollinations.ai/prompt/"
ID = re.compile(r"^[0-9a-f]{16}$")


def create(cfg, description: str, fetch=None) -> str:
    description = redact(" ".join(str(description).split()))[:600]
    if len(description) < 3:
        raise ValueError("Describe the picture in a few words.")
    url = ENDPOINT + quote(description) + "?width=1024&height=1024&nologo=true"
    if fetch is None:
        def fetch(address):
            request = urllib.request.Request(address, headers={"User-Agent": "jarvis-command/0.1"})
            with urllib.request.urlopen(request, timeout=90) as response:
                return response.read(8_000_000)
    try:
        data = fetch(url)
    except OSError:
        raise ValueError("The picture service did not answer. Try again in a moment.") from None
    if not (data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n"):
        raise ValueError("The picture service did not return a picture.")
    folder = cfg.state_dir / "pictures"
    folder.mkdir(parents=True, exist_ok=True)
    ident = secrets.token_hex(8)
    (folder / (ident + (".png" if data[:1] == b"\x89" else ".jpg"))).write_bytes(data)
    return ident


def load(cfg, ident: str) -> dict:
    if not ID.fullmatch(str(ident)):
        raise ValueError("Unknown picture.")
    for suffix, mime in ((".jpg", "image/jpeg"), (".png", "image/png")):
        path = cfg.state_dir / "pictures" / (ident + suffix)
        if path.is_file():
            return {"id": ident, "mime": mime, "data": base64.b64encode(path.read_bytes()).decode(), "path": str(path)}
    raise ValueError("Unknown picture.")
