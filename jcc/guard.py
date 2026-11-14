"""Safety guard. Pure functions, no I/O.

- personal_reason(): personal/financial requests stay in tier 1 (no AI, nothing leaves the laptop).
- tier3_block_reason(): tier 3 must never deploy, touch servers, keys, pushes, deletes, money,
  or risk limits. Project coding is allowed in branch copies.
"""

from __future__ import annotations

from jcc import own_terms
import re

_PERSONAL = [
    (r"\b(password|passcode|pin code|otp|2fa code)s?\b", "credentials"),
    (r"\b(aadhaar|aadhar|pan card|passport|ssn|social security)\b", "identity documents"),
    (r"\b(bank|bank account|ifsc|upi|credit card|debit card|card number|cvv)\b", "banking"),
    (r"\b(salary|income|pocket money|allowance|tax return|loan|debt)\b", "personal finance"),
    (r"\bmy (money|savings|balance|finances|portfolio|profit|loss|investments?|expenses?)\b",
     "personal finance"),
    (r"\b(trading bot|paper bot|my bot|bot status|jarvis[- ]trading)\b", "trading bot data"),
    (r"\b(diagnos\w*|medical|medicine|symptoms?|therapy|prescription|doctor)\b", "health"),
    (r"\bmy (address|phone number|location|diary|journal)\b", "personal details"),
]

_TIER3_FORBIDDEN = [
    (r"\b(re)?deploy\w*\b|\bdocker compose up\b", "deploying"),
    (r"\b(ssh|scp|vps|oracle cloud|droplet|sslip" + own_terms.alternation("server_terms") + r")\b|\b(on|to|into) the server\b|"
     r"\b(remote|live|production|cloud) server\b|\brestart (the )?(server|bot)\b", "servers"),
    (r"\bgit\s+push\b|\bpush\s+(it\s+)?(to|the)\b|\bforce[- ]push\b", "pushing code"),
    (r"\b(publish|release to|upload to (github|pypi|npm))\b", "publishing"),
    (r"\b(delet\w*|remov\w*|eras\w*|wip(e|es|ed|ing)|purg\w*)\b.{0,40}\b(data|files?|folders?|"
     r"director\w*|database|db|tables?|records|backups?|logs?|history|everything|disk|drive)\b|"
     r"\brm\s+-|\bdrop\s+table\b|\bformat\w*\s+(the\s+)?(drive|disk)\b", "deleting data"),
    (r"\b(api[ _-]?keys?|secrets?|credentials?|passwords?|\.env\b|private keys?|"
     r"(access|auth|bearer|github) tokens?)\b", "keys/secrets"),
    (r"risk[_ ]limits?|risk_limits\.yaml|max[_ ]drawdown[_ ]pct|kill[- ]switch (limit|threshold)",
     "the risk limits (AI may never change them)"),
    (r"\b(purchase|checkout|subscribe|billing|invoice|payment method|credit card|pay for)\b|"
     r"\bbuy\s+(a|an|me|some|the)\s+(?!order|signal|side)", "money"),
    (r"\b(send (an )?(email|message|dm)|post (to|on) (x|twitter|reddit|instagram))\b",
     "sending messages"),
]


def personal_reason(text: str) -> str | None:
    t = text.lower()
    for pat, why in _PERSONAL:
        if re.search(pat, t):
            return why
    return None


# Match only a complete, affirmative permission reminder with a closed list
# of actions. Scan the rest of the prompt, including other sentences, normally.
# The reminder may start a message, a sentence, a line or a list item (pasted
# handoffs often put it on its own line or as a bullet) and must end the
# sentence or line, so "Ask me before deploying, then deploy now." still blocks.
_APPROVAL_ACTION = (
    r"(?:deploying|publishing|pushing to (?:git|github)|spending money|"
    r"accessing my screen|handling (?:secrets|api keys))"
)
_APPROVAL_REMINDER = re.compile(
    r"(?:^|(?<=[.!?]))[ \t]*(?:(?:[-*+•]|\d+[.)])[ \t]+)?(?:please[ \t]+)?"
    r"ask me before\s+" + _APPROVAL_ACTION
    + r"(?:\s*(?:,\s*(?:(?:or|and)\s+)?|\s+(?:or|and)\s+)" + _APPROVAL_ACTION
    + r")*[ \t]*(?=[.!](?:\s|$)|$)",
    re.MULTILINE,
)


def tier3_block_reason(text: str, protected_paths: list[str] | None = None) -> str | None:
    t = text.lower()
    action_text = _APPROVAL_REMINDER.sub(" ", t)
    for pat, why in _TIER3_FORBIDDEN:
        if re.search(pat, action_text):
            return why
    for p in protected_paths or []:
        norm = p.lower().replace("\\", "/").rstrip("/")
        if norm and norm in t.replace("\\", "/"):
            return f"protected folder {p}"
    return None


def rules_text() -> str:
    lines = ["Personal/financial patterns (forced to tier 1, no AI):"]
    lines += [f"- `{p}` → {w}" for p, w in _PERSONAL]
    lines += ["", "Tier 3 never does (needs approval note instead):"]
    lines += [f"- `{p}` → {w}" for p, w in _TIER3_FORBIDDEN]
    return "\n".join(lines)
