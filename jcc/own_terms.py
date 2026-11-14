"""Words that are private on this PC and nowhere else: a server's address, the name of a product of the owner's.

The rules about private windows, off-limits servers and screens that are never read have fixed lists of words that
hold for everyone (banks, password managers, brokers). What is private to one person is not in the code: it is read
from the settings ([safety] private_terms, usually in config/local.toml) and added to those lists.
"""
from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def terms(kind: str = "private_terms") -> list[str]:
    """The owner's own words of one kind: "private_terms" (windows and screens that are private) or "server_terms"
    (servers a coding job must never be sent to)."""
    found: list[str] = []
    names = ["default.toml"] + ([] if os.environ.get("JCC_NO_LOCAL_CONFIG") else ["local.toml"])
    for name in names:
        try:
            listed = tomllib.loads((ROOT / "config" / name).read_text("utf-8")).get("safety", {}).get(kind, [])
        except (OSError, ValueError):
            continue
        found += [str(item).strip() for item in listed if isinstance(item, str) and 2 <= len(str(item).strip()) <= 80]
    return list(dict.fromkeys(found))[:50]


def alternation(kind: str = "private_terms") -> str:
    """The owner's own words as one more piece of a pattern ("|word|word"), or "" when there are none."""
    return "".join("|" + re.escape(word) for word in terms(kind))
