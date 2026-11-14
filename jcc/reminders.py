"""Timers and reminders. Kept on disk so they survive a restart, and announced when they are due."""
from __future__ import annotations

import json
import re
import secrets
import threading
import time
from datetime import datetime, timedelta

from jcc.redact import redact
from jcc.vault import atomic_write

MAX_ITEMS = 50
_UNITS = {"second": 1, "sec": 1, "s": 1, "minute": 60, "min": 60, "m": 60, "hour": 3600, "hr": 3600, "h": 3600, "day": 86400, "d": 86400}
_NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
            "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "forty-five": 45, "fifty": 50, "sixty": 60, "ninety": 90, "half": 0.5}


def parse_duration(text: str) -> float | None:
    """Seconds for phrases like '5 minutes', 'an hour and a half', '90 seconds', '1h 30m'."""
    low = str(text).lower().replace("-and-", " and ").strip()
    total, found = 0.0, False
    if re.search(r"\b(an?|one) hour and a half\b", low):
        return 5400.0
    if re.search(r"\bhalf an hour\b", low):
        return 1800.0
    units = r"seconds?|secs?|minutes?|mins?|hours?|hrs?|days?"
    for digits, short, word, long in re.findall(rf"(\d+(?:\.\d+)?)\s*({units}|[smhd])\b|\b([a-z]+(?:-[a-z]+)?)\s+({units})\b", low):
        amount, unit = (digits, short) if digits else (word, long)
        value = float(amount) if digits else _NUMBERS.get(amount)
        if value is None:
            continue
        key = unit.rstrip("s") if len(unit) > 1 else unit
        total += value * _UNITS.get(key, _UNITS.get(unit, 0))
        found = True
    return total if found and 1 <= total <= 366 * 86400 else None


def pure_duration(text: str) -> float | None:
    """Seconds, but only when the text is nothing except a length of time ("ten minutes", not "ten minutes and then...")."""
    low = " ".join(str(text).lower().replace("-and-", " and ").split())
    seconds = parse_duration(low)
    if not seconds:
        return None
    units = r"seconds?|secs?|minutes?|mins?|hours?|hrs?|days?"
    rest = re.sub(r"\b(?:an?|one) hour and a half\b|\bhalf an hour\b", " ", low)
    rest = re.sub(rf"\d+(?:\.\d+)?\s*(?:{units}|[smhd])\b", " ", rest)
    rest = re.sub(rf"\b([a-z]+(?:-[a-z]+)?)\s+(?:{units})\b", lambda m: " " if m.group(1) in _NUMBERS else m.group(0), rest)
    return seconds if not re.sub(r"\band\b|,", " ", rest).strip() else None


def pure_clock(text: str, now: datetime | None = None) -> float | None:
    """A time of day, but only when the text is nothing else ("at 5pm", "tomorrow at 9 am")."""
    low = " ".join(str(text).lower().split())
    if not re.fullmatch(r"(?:tomorrow\s+)?(?:at\s+)?\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?(?:\s+tomorrow)?", low):
        return None
    return parse_clock(low if "at " in low else low.replace("tomorrow ", "tomorrow at ", 1) if low.startswith("tomorrow ") else "at " + low, now)


def parse_clock(text: str, now: datetime | None = None) -> float | None:
    """Epoch seconds for 'at 5pm', 'at 17:30', 'tomorrow at 9 am'. The next such time, never the past."""
    now = now or datetime.now()
    low = str(text).lower()
    match = re.search(r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?\b", low)
    if not match or (not match.group(2) and not match.group(3) and "at " not in low):
        return None
    hour, minute, half = int(match.group(1)), int(match.group(2) or 0), (match.group(3) or "").replace(".", "")
    if half == "pm" and hour < 12:
        hour += 12
    if half == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if "tomorrow" in low:
        due += timedelta(days=1)
    elif due <= now:
        due += timedelta(hours=12) if not half and hour <= 12 and due + timedelta(hours=12) > now else timedelta(days=1)
    return due.timestamp()


def spoken_span(seconds: float) -> str:
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    parts = [f"{hours} hour{'s' if hours != 1 else ''}" if hours else "", f"{minutes} minute{'s' if minutes != 1 else ''}" if minutes else "",
             f"{secs} second{'s' if secs != 1 else ''}" if secs and not hours else ""]
    parts = [p for p in parts if p]
    return " and ".join(parts) if parts else "a moment"


class Reminders:
    def __init__(self, cfg, announce=None):
        self.cfg, self.announce = cfg, announce
        self.path = cfg.state_dir / "reminders.json"
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None

    def _load(self) -> list[dict]:
        try:
            rows = json.loads(self.path.read_text("utf-8")) if self.path.exists() else []
        except (OSError, ValueError):
            rows = []
        return [r for r in rows if isinstance(r, dict) and isinstance(r.get("due"), (int, float))]

    def _save(self, rows: list[dict]) -> None:
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        atomic_write(self.path, json.dumps(rows))

    def add(self, text: str, due: float, kind: str = "reminder") -> dict:
        text = redact(" ".join(str(text).split()))[:200] or ("Timer" if kind == "timer" else "Reminder")
        if not isinstance(due, (int, float)) or due <= time.time() - 1 or due > time.time() + 366 * 86400:
            raise ValueError("Choose a time in the coming year.")
        with self.lock:
            rows = self._load()
            if len(rows) >= MAX_ITEMS:
                raise ValueError("There are already fifty timers and reminders. Cancel some first.")
            item = {"id": secrets.token_hex(4), "text": text, "due": float(due), "kind": "timer" if kind == "timer" else "reminder",
                    "made": time.time()}
            self._save(sorted([*rows, item], key=lambda r: r["due"]))
        return item

    def listing(self) -> list[dict]:
        with self.lock:
            return self._load()

    def cancel(self, ident: str = "", text: str = "") -> int:
        with self.lock:
            rows = self._load()
            low = text.lower().strip()
            keep = [r for r in rows if not (r["id"] == ident or (low and low in r["text"].lower()) or (not ident and not low))]
            self._save(keep)
            return len(rows) - len(keep)

    def due_now(self) -> list[dict]:
        """Items whose time has come. Each is returned once and then removed."""
        with self.lock:
            rows = self._load()
            now = time.time()
            ready = [r for r in rows if r["due"] <= now]
            if ready:
                self._save([r for r in rows if r["due"] > now])
        return ready

    def start(self) -> None:
        if self.thread:
            return

        def loop():
            while not self.stop.wait(1.0):
                for item in self.due_now():
                    late = time.time() - item["due"] > 120
                    message = ("Your timer is done." if item["kind"] == "timer" and item["text"] == "Timer" else
                               ("Timer done: " if item["kind"] == "timer" else "Reminder: ") + item["text"]) + (" (this was due earlier)" if late else "")
                    if self.announce:
                        try:
                            self.announce(item, message)
                        except Exception:  # noqa: BLE001 - one failed announcement must not stop the clock
                            pass
        self.thread = threading.Thread(target=loop, daemon=True, name="reminders")
        self.thread.start()

    def close(self) -> None:
        self.stop.set()
