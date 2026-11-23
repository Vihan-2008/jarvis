"""Remove secrets from any text before it is written to the vault, logs, or sent to a model."""

from __future__ import annotations

import os
import re

_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),            # Google / Gemini
    re.compile(r"gsk_[0-9A-Za-z]{16,}"),               # Groq
    re.compile(r"xai-[0-9A-Za-z]{16,}"),               # xAI
    re.compile(r"pplx-[0-9A-Za-z]{16,}"),              # Perplexity
    re.compile(r"csk-[0-9A-Za-z]{16,}"),               # Cerebras
    re.compile(r"sk-(?:ant-|proj-)?[0-9A-Za-z_\-]{16,}"),  # Anthropic / OpenAI style
    re.compile(r"gh[pousr]_[0-9A-Za-z]{20,}"),         # GitHub
    re.compile(r"\b(?:ak|ck|uak)_[0-9A-Za-z_\-]{20,}"),  # Composio (project, consumer and user keys)
    re.compile(r"\bsk_[0-9a-fA-F]{30,}"),               # ElevenLabs
    re.compile(r"\bsutkn_[0-9A-Za-z_\-]{8,}"),          # ElevenLabs one-time tokens
    re.compile(r"(?i)(bearer\s+)[0-9A-Za-z._\-]{16,}"),
    re.compile(r'''(?i)((?:api[_-]?key|token|secret|password|passwd)\s*[:=]\s*["']?)[^\s"'\\,}]+'''),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
]

# Env vars whose values must never appear anywhere we write.
_SECRET_ENV = ("JCC_GEMINI_API_KEY", "JCC_GROQ_API_KEY", "JCC_BOT_PASSWORD", "JCC_ELEVENLABS_API_KEY",
               "JCC_SUPABASE_SYNC_KEY", "JCC_SUPABASE_QUERY_KEY", "JCC_OPENAI_API_KEY", "JCC_MAIL_PASSWORD",
               *("JCC_AI_" + name + "_KEY" for name in ("XAI", "PERPLEXITY", "DEEPSEEK", "MISTRAL", "OPENROUTER", "TOGETHER", "CEREBRAS",
                                                        "FIREWORKS", "MOONSHOT", "COHERE", "CUSTOM")))

_extra_secrets: set[str] = set()


def register_secret(value: str | None) -> None:
    """Remember a secret loaded at runtime (e.g. from Credential Manager) so it is scrubbed."""
    if value and len(value) >= 6:
        _extra_secrets.add(value)


def redact(text: str) -> str:
    if not text:
        return text
    for v in list(_extra_secrets) + [os.environ.get(k, "") for k in _SECRET_ENV]:
        if v and len(v) >= 6:
            text = text.replace(v, "[REDACTED]")
    for pat in _PATTERNS:
        text = pat.sub(lambda m: (m.group(1) if m.groups() else "") + "[REDACTED]", text)
    return text
