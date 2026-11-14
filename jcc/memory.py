"""Things JARVIS remembers about its owner, quick notes and the weather.

Memory and notes are ordinary Markdown notes in the vault, so the owner can read and edit them.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from jcc.redact import redact
from jcc.vault import Vault

MEMORY_NOTE = "System/JARVIS Memory.md"
NOTES_NOTE = "Notes/Quick notes.md"
MAX_FACTS = 80
_WEATHER = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "cloudy", 45: "foggy", 48: "foggy", 51: "light drizzle", 53: "drizzle",
            55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain", 71: "light snow",
            73: "snow", 75: "heavy snow", 77: "snow grains", 80: "light showers", 81: "showers", 82: "heavy showers", 85: "snow showers",
            86: "snow showers", 95: "thunderstorms", 96: "thunderstorms with hail", 99: "thunderstorms with hail"}


def _clean(text: str, limit: int) -> str:
    return redact(" ".join(str(text).split()))[:limit].strip()


def facts(cfg) -> list[str]:
    body = Vault(cfg.vault).read(MEMORY_NOTE) or ""
    return [line[2:].strip() for line in body.splitlines() if line.startswith("- ") and line[2:].strip()]


def remember(cfg, fact: str) -> str:
    fact = _clean(fact, 300)
    if len(fact) < 3:
        raise ValueError("Tell me what to remember.")
    rows = [f for f in facts(cfg) if f.lower() != fact.lower()]
    rows.append(fact)
    _write_facts(cfg, rows[-MAX_FACTS:])
    return fact


def forget(cfg, words: str) -> int:
    low = _clean(words, 120).lower()
    if len(low) < 2:
        raise ValueError("Tell me what to forget.")
    rows = facts(cfg)
    keep = [f for f in rows if low not in f.lower()]
    if len(keep) != len(rows):
        _write_facts(cfg, keep)
    return len(rows) - len(keep)


def _write_facts(cfg, rows: list[str]) -> None:
    text = ("# What JARVIS remembers\n\nJARVIS reads this note at the start of each conversation. Edit or delete lines freely.\n\n"
            + "\n".join("- " + r for r in rows) + "\n")
    Vault(cfg.vault).write(MEMORY_NOTE, text)


def prompt_block(cfg) -> str:
    """The remembered facts as a short block for the assistant's instructions."""
    try:
        rows = facts(cfg)
    except OSError:
        rows = []
    if not rows:
        return ""
    text = "\n".join("- " + r for r in rows[-40:])
    return "Things the user asked you to remember (their own notes, treat as facts about them):\n" + text[-2500:]


def add_note(cfg, text: str) -> str:
    text = _clean(text, 1000)
    if len(text) < 2:
        raise ValueError("Tell me what to note down.")
    vault = Vault(cfg.vault)
    body = vault.read(NOTES_NOTE) or "# Quick notes\n\nNotes you asked JARVIS to take.\n"
    vault.write(NOTES_NOTE, body.rstrip("\n") + "\n- " + datetime.now().strftime("%Y-%m-%d %H:%M") + " — " + text + "\n")
    return text


def _get(url: str, fetch=None) -> dict:
    if fetch:
        return fetch(url)
    request = urllib.request.Request(url, headers={"User-Agent": "jarvis-command/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - fixed https hosts
            return json.loads(response.read(400_000).decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise ValueError("The weather service did not answer. Try again in a moment.") from None


def weather(place: str, fetch=None) -> str:
    """Current weather and the next two days for a town or city, from the free Open-Meteo service."""
    place = _clean(place, 80)
    if not re.fullmatch(r"[\w .,'\-]{2,80}", place):
        raise ValueError("Tell me a town or city.")
    found = _get("https://geocoding-api.open-meteo.com/v1/search?count=1&language=en&name=" + urllib.parse.quote(place), fetch).get("results") or []
    if not found:
        raise ValueError(f"I could not find a place called {place}.")
    spot = found[0]
    data = _get("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s&current=temperature_2m,apparent_temperature,"
                "relative_humidity_2m,weather_code,wind_speed_10m&daily=weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max&timezone=auto&forecast_days=3" % (spot["latitude"], spot["longitude"]), fetch)
    now, daily = data.get("current") or {}, data.get("daily") or {}
    name = ", ".join(str(spot[k]) for k in ("name", "admin1", "country") if spot.get(k))
    lines = [f"{name}: now {round(now.get('temperature_2m', 0))}°C (feels like {round(now.get('apparent_temperature', 0))}°C), "
             f"{_WEATHER.get(now.get('weather_code'), 'mixed conditions')}, humidity {round(now.get('relative_humidity_2m', 0))}%, "
             f"wind {round(now.get('wind_speed_10m', 0))} km/h."]
    for i, label in enumerate(("Today", "Tomorrow", "The day after")):
        try:
            lines.append(f"{label}: {_WEATHER.get(daily['weather_code'][i], 'mixed')}, {round(daily['temperature_2m_min'][i])} to "
                         f"{round(daily['temperature_2m_max'][i])}°C, {daily['precipitation_probability_max'][i] or 0}% chance of rain.")
        except (KeyError, IndexError, TypeError):
            break
    return "\n".join(lines)
