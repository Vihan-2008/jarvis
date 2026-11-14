"""Where a film or series can be watched in the owner's country.

"Play Inception" used to open Netflix whatever the film was: if Netflix does not have it, a page of nothing. Now JARVIS
first looks up where the title is streaming, and plays it on a service that has it.

The lookup is JustWatch's title search, the one its own website uses. It is not a promised public service: when it does
not answer, nothing is known, JARVIS says so, and the assistant can search the web instead. Only the title and the
country go to it.
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

ADDRESS = "https://apis.justwatch.com/graphql"
QUERY = ("query Search($q: String!, $country: Country!, $language: Language!) { popularTitles(country: $country, first: 5, filter: {searchQuery: $q}) "
         "{ edges { node { objectType content(country: $country, language: $language) { title originalReleaseYear } "
         "offers(country: $country, platform: WEB) { monetizationType package { clearName } } } } } }")
# The services JARVIS can find and start a title on itself (jcc/quick.py WATCH, and YouTube), by the names the lookup uses.
KNOWN = (("netflix", re.compile(r"^netflix\b", re.I)), ("prime video", re.compile(r"^amazon prime video\b|^prime video\b", re.I)),
         ("hotstar", re.compile(r"hotstar", re.I)), ("youtube", re.compile(r"^youtube(?! tv)\b", re.I)))
KEEP = 3600.0
_lock = threading.Lock()
_kept: dict[tuple[str, str], tuple[float, dict | None]] = {}


def country() -> str:
    """The owner's country as Windows knows it ("IN", "US"...). "US" when that cannot be told."""
    if os.name == "nt":
        try:
            name = ctypes.create_unicode_buffer(16)
            if ctypes.windll.kernel32.GetUserDefaultGeoName(name, 16) and re.fullmatch(r"[A-Za-z]{2}", name.value):
                return name.value.upper()
        except (AttributeError, OSError):
            pass
    return "US"


def _plain(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", str(text).lower().replace("&", " and ")).split())


def _ask(title: str, where: str, timeout: float = 6.0) -> dict:
    body = json.dumps({"query": QUERY, "variables": {"q": title, "country": where, "language": "en"}}).encode()
    request = urllib.request.Request(ADDRESS, data=body, headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:      # noqa: S310 - a fixed https address
        return json.loads(response.read(600_000))


def lookup(title: str, where: str | None = None, ask=None) -> dict | None:
    """Where this title can be watched: {"title", "year", "kind" ("film" or "series"), "stream": [...], "rent": [...],
    "buy": [...], "country"}. None when the lookup did not answer or knows no such title. `ask` stands in for the web."""
    title = " ".join(str(title or "").split())[:120]
    where = (where or country()).upper()
    if not title:
        return None
    key = (_plain(title), where)
    with _lock:
        kept = _kept.get(key)
        if kept and time.time() - kept[0] < KEEP:
            return kept[1]
    try:
        data = (ask or _ask)(title, where)
        edges = data["data"]["popularTitles"]["edges"]
    except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError):
        return None                                         # (not kept: it may answer next time)
    found = None
    wanted = _plain(title)
    rows = [edge.get("node") or {} for edge in edges if isinstance(edge, dict)]

    def fits(node) -> int:
        """2: exactly this name; 1: most of its words (the lookup also offers things that merely sound alike); 0: something else."""
        name = _plain((node.get("content") or {}).get("title", ""))
        if not name:
            return 0
        if name == wanted:
            return 2
        small = {"the", "a", "an", "of", "and", "in", "to", "part", "movie", "film", "series", "show", "season"}
        asked, got = [w for w in wanted.split() if w not in small] or wanted.split(), set(name.split())
        hits = sum(1 for word in asked if word in got)
        return 1 if hits and hits * 2 >= len(asked) + (len(asked) > 2) else 0
    # The one with exactly this name, if there is one; otherwise the likeliest one that really is about these words.
    for node in sorted((n for n in rows if fits(n)), key=lambda n: -fits(n))[:1]:
        content = node.get("content") or {}
        found = {"title": str(content["title"])[:120], "year": content.get("originalReleaseYear"), "kind": "series" if node.get("objectType") == "SHOW" else "film",
                 "stream": [], "rent": [], "buy": [], "country": where}
        for offer in node.get("offers") or []:
            name = str(((offer or {}).get("package") or {}).get("clearName") or "").strip()[:60]
            group = {"FLATRATE": "stream", "FREE": "stream", "ADS": "stream", "FLATRATE_AND_BUY": "stream", "RENT": "rent", "BUY": "buy"}.get(str((offer or {}).get("monetizationType")))
            if name and group and name not in found[group]:
                found[group].append(name)
    with _lock:
        _kept[key] = (time.time(), found)
    return found


def services(found: dict | None) -> list[str]:
    """The services it is streaming on that JARVIS can start a title on itself, in the lookup's order ("netflix", "prime video"...)."""
    out: list[str] = []
    for name in (found or {}).get("stream") or []:
        for key, pattern in KNOWN:
            if pattern.search(name) and key not in out:
                out.append(key)
    return out


def describe(found: dict | None) -> str:
    """One sentence a person can be told."""
    if not found:
        return ""
    what = f'"{found["title"]}"' + (f" ({found['year']} {found['kind']})" if found.get("year") else "")
    stream = [re.sub(r" with ads$", "", name, flags=re.I) for name in found["stream"]]
    stream = [name for i, name in enumerate(stream) if name not in stream[:i]][:6]
    if stream:
        return f"{what} is streaming on {', '.join(stream)}."
    paid = [name for name in dict.fromkeys(found["rent"] + found["buy"])][:4]
    if paid:
        return f"{what} is not on a streaming service in {found['country']}; it can be rented or bought on {', '.join(paid)}."
    return f"{what} is not available to stream, rent or buy in {found['country']} right now."
