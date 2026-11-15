"""Other AI services JARVIS can use, each connected with its own key.

Nearly all of them speak the same language (OpenAI's "chat completions"), so one small client covers them all: ChatGPT's
API, Gemini, Grok, Perplexity, DeepSeek, Mistral, Groq, OpenRouter, Together, Cerebras, Fireworks, Kimi, Cohere, and
models that run on this PC (Ollama, LM Studio). Any other service that speaks it can be added by its address.

What they are used for:
- a stand-in for the fast assistant when Claude's allowance is used up, or its brain when the owner picks one;
- research, with a service that searches the web itself;
- a second opinion, from a model of the owner's choice.

A key lives in Windows Credential Manager and nowhere else. It is sent only to the service it belongs to, over HTTPS (a
plain address is accepted only for a model running on this PC). Model names are never guessed: they are read from the
service itself, so the list is always the one the key really has.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from urllib.parse import urlparse

from jcc import secrets
from jcc.redact import redact
from jcc.vault import atomic_write, read_json

AGENT = "jarvis-command/1.0 (+personal assistant)"
# id -> what is known about the service. "prefer": patterns for the model to use by default, best first.
CATALOG: dict[str, dict] = {
    "openai": {"name": "ChatGPT (OpenAI)", "base": "https://api.openai.com/v1", "get": "https://platform.openai.com/api-keys",
               "about": "OpenAI's models through an API key (separate from a ChatGPT subscription).", "prefer": [r"^gpt-[\d.]+-mini$", r"^gpt-[\d.]+$", r"^gpt-"], "vision": True},
    "gemini": {"name": "Gemini (Google)", "base": "https://generativelanguage.googleapis.com/v1beta/openai", "get": "https://aistudio.google.com/apikey",
               "about": "Google's models. A free key is enough for everyday use.", "prefer": [r"gemini-flash-latest$", r"gemini-[\d.]+-flash$", r"gemini-.*flash", r"gemini-.*pro"],
               "vision": True, "free": True},
    "xai": {"name": "Grok (xAI)", "base": "https://api.x.ai/v1", "get": "https://console.x.ai",
            "about": "xAI's Grok models.", "prefer": [r"grok-[\d.]+-fast", r"grok-[\d.]+$", r"^grok-"], "vision": True},
    # Perplexity is asked through its Agent API (POST /v1/agent). What it calls "effort levels" are ready-made depths of
    # research, each with its own model, searches and instructions; they stand in the place of model names here.
    "perplexity": {"name": "Perplexity", "base": "https://api.perplexity.ai", "get": "https://www.perplexity.ai/account/api/keys",
                   "about": "Answers that are searched for on the web first, with their sources. Best for research. Its choices are depths of research, from fast to ultra.",
                   "prefer": [r"^low$", r"^fast$"], "models": ["fast", "low", "medium", "high", "xhigh", "ultra"], "tools": False, "search": True, "agent": True},
    "groq": {"name": "Groq", "base": "https://api.groq.com/openai/v1", "get": "https://console.groq.com/keys",
             "about": "Open models, answered very fast. A free key is enough (the same key that powers Whisper listening).",
             "prefer": [r"gpt-oss-120b$", r"llama-[\d.]+-70b", r"kimi", r"gpt-oss-20b$"], "free": True, "lean": True},
    "deepseek": {"name": "DeepSeek", "base": "https://api.deepseek.com/v1", "get": "https://platform.deepseek.com/api_keys",
                 "about": "DeepSeek's models.", "prefer": [r"^deepseek-chat$", r"^deepseek-"]},
    "mistral": {"name": "Mistral", "base": "https://api.mistral.ai/v1", "get": "https://console.mistral.ai/api-keys",
                "about": "Mistral's models.", "prefer": [r"^mistral-medium-latest$", r"^mistral-large-latest$", r"^mistral-small-latest$"]},
    "openrouter": {"name": "OpenRouter", "base": "https://openrouter.ai/api/v1", "get": "https://openrouter.ai/keys",
                   "about": "One key for hundreds of models from every maker.", "prefer": [r"^openrouter/auto$"]},
    "together": {"name": "Together AI", "base": "https://api.together.xyz/v1", "get": "https://api.together.ai/settings/api-keys",
                 "about": "Open models hosted by Together.", "prefer": [r"Llama-[\d.]+-70B.*Turbo", r"llama"]},
    "cerebras": {"name": "Cerebras", "base": "https://api.cerebras.ai/v1", "get": "https://cloud.cerebras.ai",
                 "about": "Open models, answered extremely fast.", "prefer": [r"gpt-oss-120b", r"llama.*70b", r"llama"], "lean": True},
    "fireworks": {"name": "Fireworks AI", "base": "https://api.fireworks.ai/inference/v1", "get": "https://fireworks.ai/account/api-keys",
                  "about": "Open models hosted by Fireworks.", "prefer": [r"llama.*70b", r"llama"]},
    "moonshot": {"name": "Kimi (Moonshot)", "base": "https://api.moonshot.ai/v1", "get": "https://platform.moonshot.ai/console/api-keys",
                 "about": "Moonshot's Kimi models.", "prefer": [r"^kimi-", r"moonshot"]},
    "cohere": {"name": "Cohere", "base": "https://api.cohere.ai/compatibility/v1", "get": "https://dashboard.cohere.com/api-keys",
               "about": "Cohere's Command models.", "prefer": [r"^command-a", r"^command-r-plus", r"^command"]},
    "ollama": {"name": "Ollama", "base": "http://127.0.0.1:11434/v1", "local": True, "get": "https://ollama.com/download",
               "about": "Models that run on this PC with Ollama. Nothing leaves the computer and nothing is paid for.", "prefer": [r"."], "lean": True},
    "lmstudio": {"name": "LM Studio", "base": "http://127.0.0.1:1234/v1", "local": True, "get": "https://lmstudio.ai",
                 "about": "Models that run on this PC with LM Studio.", "prefer": [r"."], "lean": True},
    "custom": {"name": "Another service", "base": "", "get": "",
               "about": "Any other service that speaks the OpenAI chat format: give its address and a key.", "prefer": [r"."]},
}
# Names in a model list that are not chat models.
NOT_CHAT = re.compile(r"embed|whisper|tts|speech|audio|image|imagen|veo|lyria|dall|sora|guard|moderat|rerank|transcri|realtime|"
                      r"-live|robotics|\baqa\b|orpheus|computer-use|banana|search-preview|deep-research|antigravity|clip|omni-flash|translate", re.I)
_lock = threading.Lock()
_models: dict[str, tuple[float, list[str]]] = {}
_failed: dict[str, tuple[float, Exception]] = {}


class ProviderError(ValueError):
    """Something the owner can be told in plain words. `limit`: the service's allowance is used up or it asked to slow down."""

    def __init__(self, message: str, limit: bool = False, retry_at: float | None = None, status: int = 0, model_problem: bool = False):
        super().__init__(message)
        self.limit, self.retry_at, self.status, self.model_problem = limit, retry_at, status, model_problem


# ---------------------------------------------------------------------- settings and keys
def _file(cfg):
    return cfg.state_dir / "providers.json"


def settings(cfg) -> dict:
    saved = read_json(_file(cfg), {})
    return saved if isinstance(saved, dict) else {}


def _save(cfg, saved: dict) -> None:
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(_file(cfg), json.dumps(saved))


def key_name(ident: str) -> str:
    """The name its key is kept under in Windows Credential Manager."""
    return ident if ident in ("openai", "gemini", "groq") else "ai-" + ident


def _key(ident: str) -> str | None:
    return None if CATALOG[ident].get("local") else secrets.get(key_name(ident))


def check_address(address: str) -> str:
    """The address of a service the owner adds themselves. HTTPS, or a model server running on this very PC."""
    address = str(address or "").strip().rstrip("/")
    parts = urlparse(address)
    host = (parts.hostname or "").lower()
    here = host in ("127.0.0.1", "localhost", "::1")
    if parts.scheme not in ("https", "http") or not host or parts.username or parts.password or len(address) > 200:
        raise ProviderError("Give the service's address, starting with https://")
    if parts.scheme == "http" and not here:
        raise ProviderError("Only an https:// address is accepted, so that the key cannot be read on the way. (A plain address works for a model on this PC.)")
    return address


def base(cfg, ident: str) -> str:
    if ident == "custom":
        return str((settings(cfg).get("custom") or {}).get("base") or "")
    return CATALOG[ident]["base"]


# Where each model app is found when it is installed (Windows, a Mac, Linux), besides its command on the PATH.
INSTALLED = {"ollama": {"commands": ("ollama",),
                        "places": ("%LOCALAPPDATA%/Programs/Ollama/ollama.exe", "%ProgramFiles%/Ollama/ollama.exe", "/Applications/Ollama.app",
                                   "~/Applications/Ollama.app", "/usr/local/bin/ollama", "/opt/homebrew/bin/ollama", "/usr/bin/ollama")},
             "lmstudio": {"commands": ("lms",),
                          "places": ("%LOCALAPPDATA%/Programs/LM Studio/LM Studio.exe", "%LOCALAPPDATA%/Programs/lm-studio/LM Studio.exe",
                                     "%ProgramFiles%/LM Studio/LM Studio.exe", "~/.lmstudio/bin/lms", "~/.lmstudio/bin/lms.exe",
                                     "/Applications/LM Studio.app", "~/Applications/LM Studio.app")}}


def installed(ident: str, which=None, exists=None) -> bool:
    """Is this model app on this PC? (Its program in its usual place, or its command on the PATH.) Only the model apps
    that run on the PC are asked; every other service is not "on this PC"."""
    import os
    import shutil
    from pathlib import Path
    which, exists = which or shutil.which, exists or (lambda p: Path(p).exists())
    known = INSTALLED.get(ident)
    if not known:
        return False
    if any(which(command) for command in known["commands"]):
        return True
    for place in known["places"]:
        path = os.path.expanduser(os.path.expandvars(place))
        if "%" not in path and exists(path):
            return True
    return False


def connected(cfg, ident: str) -> bool:
    """Is this service ready to be used? (A key is saved; for a model on this PC, its server answered a moment ago.)"""
    if ident not in CATALOG or (settings(cfg).get(ident) or {}).get("off") is True:
        return False
    if CATALOG[ident].get("local"):
        with _lock:
            known = _models.get(ident)
        return bool(known and known[1] and time.time() - known[0] < 900)
    return bool(base(cfg, ident) and _key(ident))


def connect(cfg, ident: str, key: str = "", address: str = "", name: str = "") -> dict:
    """Save a key (and, for a service the owner adds, its address). The key is checked by asking the service for its models."""
    if ident not in CATALOG:
        raise ProviderError("That service is not known.")
    saved = settings(cfg)
    if ident == "custom":
        saved["custom"] = {**(saved.get("custom") or {}), "base": check_address(address), "name": redact(" ".join(str(name).split()))[:40] or "Another service"}
    key = str(key or "").strip()
    if not CATALOG[ident].get("local"):
        if not (8 <= len(key) <= 400) or re.search(r"\s", key):
            raise ProviderError("That does not look like a key. Copy it again from the service's website.")
        old = secrets.get(key_name(ident))
        secrets.store(key_name(ident), key)
        _save(cfg, saved)
        try:
            models(cfg, ident, refresh=True)
        except ProviderError as problem:
            if problem.status in (401, 403):               # the service itself says the key is wrong: it is not kept
                if old:
                    secrets.store(key_name(ident), old)
                else:
                    secrets.delete(key_name(ident))
                raise
    else:
        models(cfg, ident, refresh=True)
    saved.setdefault(ident, {}).pop("off", None)
    _save(cfg, saved)
    return describe(cfg, ident)


def disconnect(cfg, ident: str) -> dict:
    if ident not in CATALOG:
        raise ProviderError("That service is not known.")
    if not CATALOG[ident].get("local") and ident not in ("groq", "gemini", "openai"):
        secrets.delete(key_name(ident))                     # (the Groq, Gemini and OpenAI keys also serve listening and free answers: switched off, not thrown away)
    saved = settings(cfg)
    saved[ident] = {**(saved.get(ident) or {}), "off": True}
    _save(cfg, saved)
    with _lock:
        _models.pop(ident, None)
    return describe(cfg, ident)


def choose_model(cfg, ident: str, model: str) -> dict:
    model = str(model or "").strip()
    if ident not in CATALOG or not re.fullmatch(r"[\w./:@\- ]{1,120}", model):
        raise ProviderError("That model name is not valid.")
    saved = settings(cfg)
    saved[ident] = {**(saved.get(ident) or {}), "model": model}
    _save(cfg, saved)
    return describe(cfg, ident)


# ---------------------------------------------------------------------- talking to a service
def _open(cfg, ident: str, path: str, body: dict | None = None, timeout: float = 30.0):
    address = base(cfg, ident)
    if not address:
        raise ProviderError("That service has no address yet.")
    headers = {"User-Agent": AGENT, "Accept": "text/event-stream" if body and body.get("stream") else "application/json"}
    secret = _key(ident)
    if secret:
        headers["Authorization"] = "Bearer " + secret
    elif not CATALOG[ident].get("local"):
        raise ProviderError(f"No key is saved for {label(cfg, ident)}.")
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(address + path, data=json.dumps(body).encode("utf-8") if body is not None else None, headers=headers,
                                     method="POST" if body is not None else "GET")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if CATALOG[ident].get("local") else urllib.request.build_opener()
    try:
        return opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        raise _problem(cfg, ident, error.code, error.read(3000), error.headers) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        if CATALOG[ident].get("local"):
            raise ProviderError(f"{label(cfg, ident)} is not running on this PC.") from None
        raise ProviderError(f"{label(cfg, ident)} could not be reached. Check the internet connection.") from None


def _problem(cfg, ident: str, status: int, raw: bytes, headers=None) -> ProviderError:
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
        if isinstance(data, list) and data:
            data = data[0]
        detail = data.get("error") if isinstance(data, dict) else ""
        detail = detail.get("message") if isinstance(detail, dict) else detail
    except ValueError:
        detail = raw.decode("utf-8", "replace")
    detail = redact(" ".join(str(detail or "").split()))[:200]
    who = label(cfg, ident)
    if status in (401, 403):
        return ProviderError(f"{who} did not accept the key. Check it under Connections.", status=status)
    if status in (402, 429) or re.search(r"quota|rate.?limit|credit|billing|insufficient", detail, re.I):
        wait = None
        try:
            wait = float((headers or {}).get("retry-after") or 0) or None
        except (TypeError, ValueError):
            wait = None
        said = re.search(r"try again in\s+(?:(\d+)m)?\s*([\d.]+)\s*(ms|s)\b", detail, re.I)      # "Please try again in 6.52s"
        if said and not wait:
            wait = int(said.group(1) or 0) * 60 + float(said.group(2)) / (1000 if said.group(3).lower() == "ms" else 1)
        spent = status == 402 or bool(re.search(r"quota|credit|billing|insufficient|per day|daily", detail, re.I))
        return ProviderError(f"{who} has reached its limit" + (": " + detail if detail else "."), limit=True, status=status,
                             retry_at=time.time() + (wait if wait else 3600 if spent else 60), model_problem=bool(re.search(r"\bfor model\b", detail, re.I)))
    if status == 404 or re.search(r"model.{0,40}(not found|does not exist|not supported|decommission)", detail, re.I):
        return ProviderError(f"{who} does not have that model" + (": " + detail if detail else "."), status=status, model_problem=True)
    if status >= 500:
        return ProviderError(f"{who} is having trouble right now. Try again in a moment.", limit=True, status=status, retry_at=time.time() + 120)
    return ProviderError(f"{who} refused the request" + (": " + detail if detail else "."), status=status)


def label(cfg, ident: str) -> str:
    if ident == "custom":
        return str((settings(cfg).get("custom") or {}).get("name") or "the other service")
    return CATALOG[ident]["name"]


_said: dict[str, dict[str, str]] = {}


def about(ident: str, model: str) -> str:
    """One line on what this service's model is good for (jcc/model_notes.py)."""
    from jcc import model_notes
    with _lock:
        given = (_said.get(ident) or {}).get(model, "")
    return model_notes.about(model, ident, given=given, local=bool(CATALOG.get(ident, {}).get("local")))


def models_about(cfg, ident: str, refresh: bool = False) -> dict:
    """The models this key can use, each with what it is good for."""
    names = models(cfg, ident, refresh=refresh)
    return {"models": names, "about": {name: about(ident, name) for name in names}}


def models(cfg, ident: str, refresh: bool = False) -> list[str]:
    """The chat models this key can use, read from the service itself (kept for six hours)."""
    if ident not in CATALOG:
        raise ProviderError("That service is not known.")
    with _lock:
        known, failed = _models.get(ident), _failed.get(ident)
    if known and not refresh and time.time() - known[0] < 21600:
        return known[1]
    if failed and not refresh and time.time() - failed[0] < 300:
        raise failed[1]                                     # it could not be read a moment ago: not asked again straight away
    fixed = CATALOG[ident].get("models")
    if CATALOG[ident].get("agent"):
        # Its choices are fixed. When the key has just been given, it is checked without anything being asked (and so
        # without anything being charged): an empty request is turned away as "not a request" only if the key is good.
        if refresh:
            try:
                _open(cfg, ident, "/v1/agent", {}, timeout=20).close()
            except ProviderError as problem:
                if problem.status in (401, 403):
                    with _lock:
                        _failed[ident] = (time.time(), problem)
                    raise
        with _lock:
            _models[ident] = (time.time(), list(fixed))
            _failed.pop(ident, None)
        return list(fixed)
    try:
        with _open(cfg, ident, "/models", timeout=8 if CATALOG[ident].get("local") else 20) as response:
            data = json.loads(response.read(4_000_000).decode("utf-8", "replace"))
        rows = data.get("data") if isinstance(data, dict) else data
        found = sorted({str(row.get("id") or "").removeprefix("models/") for row in rows or [] if isinstance(row, dict)} - {""})
        said = {str(row.get("id") or "").removeprefix("models/"): str(row.get("description") or "")[:400]
                for row in rows or [] if isinstance(row, dict) and isinstance(row.get("description"), str)}
        with _lock:
            _said[ident] = said                             # (what the service says about each one, for model_notes)
        found = [name for name in found if not NOT_CHAT.search(name)] or found
    except ProviderError as problem:
        if not fixed or problem.status in (401, 403):
            with _lock:
                _failed[ident] = (time.time(), problem)
            raise
        found = list(fixed)                                 # this service has no list to read: the names it documents
    except (ValueError, OSError):
        if not fixed:
            raise ProviderError(f"{label(cfg, ident)} did not send a list of models.") from None
        found = list(fixed)
    with _lock:
        _models[ident] = (time.time(), found)
        _failed.pop(ident, None)
    return found


def default_model(cfg, ident: str, ask: bool = True) -> str:
    """The model to use when the owner has not picked one: the one they chose, else the best match in the service's list.
    ask=False: only what is already known is used; the service is not asked for its list now."""
    chosen = str((settings(cfg).get(ident) or {}).get("model") or "")
    try:
        if ask:
            offered = models(cfg, ident)
        else:
            with _lock:
                offered = (_models.get(ident) or (0, []))[1]
    except ProviderError:
        offered = []
    if chosen and (chosen in offered or not offered):
        return chosen
    for pattern in CATALOG[ident].get("prefer", []):
        for name in offered:
            if re.search(pattern, name, re.I):
                return name
    return offered[0] if offered else chosen


def choices(cfg, ident: str, most: int = 2) -> list[str]:
    """The models of a service worth trying, best first: the usual one, then the next best. (A second model has its own
    allowance on most services, so it can carry on when the first one's is used up.)"""
    first = default_model(cfg, ident)
    with _lock:
        offered = list((_models.get(ident) or (0, []))[1])
    out = [first] if first else []
    for pattern in CATALOG[ident].get("prefer", []):
        for name in offered:
            if name not in out and re.search(pattern, name, re.I) and len(out) < most:
                out.append(name)
    return out[:most]


def describe(cfg, ident: str) -> dict:
    """One service, for the Connections list. Never includes a key."""
    entry = CATALOG[ident]
    on = connected(cfg, ident)
    return {"id": ident, "name": label(cfg, ident), "about": entry["about"], "get": entry.get("get", ""), "local": bool(entry.get("local")),
            "connected": on, "has_key": bool(_key(ident)), "model": default_model(cfg, ident, ask=False) if on else "", "search": bool(entry.get("search")),
            "model_about": about(ident, default_model(cfg, ident, ask=False)) if on and default_model(cfg, ident, ask=False) else "",
            "tools": entry.get("tools", True), "free": bool(entry.get("free")), "address": base(cfg, ident) if ident == "custom" else "",
            # "On this PC" only for a model app that is on this PC: installed, or its server answering.
            "on_pc": bool(entry.get("local")) and (on or installed(ident))}


def listing(cfg, look: bool = False) -> list[dict]:
    """Every known service. look: also ask the model servers that may be running on this PC (quick, and only on this PC)."""
    def read(ident: str, again: bool) -> None:
        try:
            models(cfg, ident, refresh=again)
        except ProviderError:
            if CATALOG[ident].get("local"):
                with _lock:
                    _models.pop(ident, None)
    wanted = [(ident, True) for ident, entry in CATALOG.items() if look and entry.get("local") and (settings(cfg).get(ident) or {}).get("off") is not True]
    with _lock:
        known = set(_models)
    wanted += [(ident, False) for ident in CATALOG if not CATALOG[ident].get("local") and ident not in known and connected(cfg, ident)]
    workers = [threading.Thread(target=read, args=item, daemon=True, name="ai-models") for item in wanted]
    for worker in workers:                                  # all at once, and never more than a few seconds of waiting
        worker.start()
    deadline = time.time() + 6
    for worker in workers:
        worker.join(max(0.0, deadline - time.time()))
    return [describe(cfg, ident) for ident in CATALOG]


def ready(cfg, need_tools: bool = False) -> list[str]:
    """The connected services, in the order they are worth trying as a stand-in: quick and free first."""
    order = ["groq", "cerebras", "gemini", "xai", "openai", "deepseek", "mistral", "openrouter", "together", "fireworks", "moonshot", "cohere", "custom",
             "ollama", "lmstudio", "perplexity"]
    return [ident for ident in order if connected(cfg, ident) and (not need_tools or CATALOG[ident].get("tools", True))]


# ---------------------------------------------------------------------- one answer, piece by piece
EFFORTS = {"fast": 90, "low": 180, "medium": 420, "high": 900, "xhigh": 1500, "ultra": 2400}    # Perplexity's depths of research, and how long each may stay silent (seconds)


def _sources(found: list) -> list[dict]:
    """The pages an answer was drawn from, as {"title", "url"}: web addresses only, each once, no more than fifteen."""
    out, seen = [], set()
    for row in found:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        if not re.fullmatch(r"https?://[^\s<>\"'()]{4,600}", url) or url in seen:
            continue
        seen.add(url)
        title = re.sub(r"[\[\]\r\n]+", " ", redact(str(row.get("title") or ""))).strip()[:120]
        out.append({"title": title or urlparse(url).hostname or url, "url": url})
        if len(out) >= 15:
            break
    return out


def _agent_stream(cfg, ident: str, model: str, messages: list[dict], max_tokens: int, timeout: float, stop: threading.Event | None) -> Iterator[dict]:
    """The same pieces as stream(), from a service that is asked through an agent API in the "responses" shape
    (Perplexity). It searches the web itself, so there is also {"sources": [{"title", "url"}]} before the end."""
    talk = [{"role": message["role"], "content": redact(str(message.get("content") or ""))} for message in messages
            if message.get("role") in ("user", "assistant") and message.get("content")]
    if not talk:
        raise ProviderError("There is nothing to ask.")
    body: dict = {"input": talk[0]["content"] if len(talk) == 1 else talk, "stream": True}
    if model in EFFORTS:
        body["effort"] = model                              # a ready-made setup: it brings its own model, searches and instructions
        timeout = max(timeout, EFFORTS[model])
    else:
        system = " ".join(str(message.get("content") or "") for message in messages if message.get("role") == "system").strip()
        body.update(model=model, tools=[{"type": "web_search"}], max_output_tokens=max_tokens)
        if system:
            body["instructions"] = redact(system)[:4000]
    response = _open(cfg, ident, "/v1/agent", body, timeout)
    final, said = {}, False
    try:
        if "json" in (response.headers.get("Content-Type") or "") and "event-stream" not in (response.headers.get("Content-Type") or ""):
            final = json.loads(response.read(8_000_000).decode("utf-8", "replace"))        # it answered all at once
        else:
            for raw in response:
                if stop is not None and stop.is_set():
                    return
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    data = json.loads(payload)
                except ValueError:
                    continue
                if not isinstance(data, dict):
                    continue
                kind = str(data.get("type") or "")
                if kind == "response.output_text.delta" and data.get("delta"):
                    said = True
                    yield {"text": str(data["delta"])}
                elif kind == "response.completed" and isinstance(data.get("response"), dict):
                    final = data["response"]
                elif kind in ("response.failed", "error") or isinstance(data.get("error"), (dict, str)):
                    problem = data.get("error") or (data.get("response") or {}).get("error") or "it could not finish"
                    raise _problem(cfg, ident, 429 if re.search(r"limit|quota|credit", str(problem), re.I) else 500, json.dumps({"error": problem}).encode())
    except (OSError, ValueError) as problem:
        if isinstance(problem, ProviderError):
            raise
        raise ProviderError(f"{label(cfg, ident)} stopped answering part of the way through.", limit=True, retry_at=time.time() + 60) from None
    finally:
        try:
            response.close()
        except OSError:
            pass
    if isinstance(final.get("error"), (dict, str)) and final["error"]:
        raise _problem(cfg, ident, 500, json.dumps({"error": final["error"]}).encode())
    found, whole = [], ""
    for item in final.get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "search_results":
            found += [row for row in item.get("results") or [] if isinstance(row, dict)]
        elif item.get("type") == "message":
            whole += "".join(str(part.get("text") or "") for part in item.get("content") or [] if isinstance(part, dict) and part.get("type") == "output_text")
    if not said and (whole or final.get("output_text")):
        yield {"text": whole or str(final["output_text"])}
    sources = _sources(found)
    if sources:
        yield {"sources": sources}
    usage = final.get("usage") if isinstance(final.get("usage"), dict) else {}
    cost = usage.get("cost") if isinstance(usage.get("cost"), dict) else {}
    try:
        spent = max(0.0, float(cost.get("total_cost") or 0))
    except (TypeError, ValueError):
        spent = 0.0
    yield {"done": "stop", "usage": {"input": int(usage.get("input_tokens") or 0), "output": int(usage.get("output_tokens") or 0), "cached": 0, "cost": spent}}


def stream(cfg, ident: str, model: str, messages: list[dict], tools: list[dict] | None = None, max_tokens: int = 1500,
           temperature: float = 0.3, timeout: float = 60.0, stop: threading.Event | None = None) -> Iterator[dict]:
    """Ask a model and yield its answer as it is written:
      {"text": "..."}                         words of the answer
      {"call": {"id", "name", "arguments"}}   a tool it wants used (arguments is a dict), once it is complete
      {"sources": [{"title", "url"}]}         the pages it drew on (services that search the web themselves)
      {"done": reason, "usage": {...}}        the end ("stop", "tool_calls", "length"...), with the tokens used when the service says
                                              (and "cost" in US dollars, where the service reports what the answer cost)
    Secrets are taken out of everything that is sent. Raises ProviderError."""
    if CATALOG.get(ident, {}).get("agent"):
        yield from _agent_stream(cfg, ident, model, messages, max_tokens, timeout, stop)
        return
    body = {"model": model, "messages": [_clean(message) for message in messages], "stream": True, "max_tokens": max_tokens, "temperature": temperature}
    if tools:
        body["tools"] = tools
    body["stream_options"] = {"include_usage": True}
    try:
        response = _open(cfg, ident, "/chat/completions", body, timeout)
    except ProviderError as problem:
        if problem.status != 400 or "stream_options" not in body:
            raise
        body.pop("stream_options")                          # an older server that does not know the option
        response = _open(cfg, ident, "/chat/completions", body, timeout)
    calls: dict[int, dict] = {}
    usage, reason = {}, ""
    try:
        for raw in response:
            if stop is not None and stop.is_set():
                return
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                data = json.loads(payload)
            except ValueError:
                continue
            if isinstance(data.get("error"), (dict, str)):
                raise _problem(cfg, ident, 429 if re.search(r"limit|quota", str(data["error"]), re.I) else 500, json.dumps(data).encode())
            if isinstance(data.get("usage"), dict):
                usage = data["usage"]
            for choice in data.get("choices") or []:
                delta = choice.get("delta") or {}
                if delta.get("content"):
                    yield {"text": str(delta["content"])}
                for call in delta.get("tool_calls") or []:
                    slot = calls.setdefault(int(call.get("index") or 0), {"id": "", "name": "", "arguments": ""})
                    slot["id"] = call.get("id") or slot["id"]
                    function = call.get("function") or {}
                    slot["name"] += function.get("name") or ""
                    slot["arguments"] += function.get("arguments") or ""
                if choice.get("finish_reason"):
                    reason = str(choice["finish_reason"])
    except (OSError, ValueError) as problem:
        if isinstance(problem, ProviderError):
            raise
        raise ProviderError(f"{label(cfg, ident)} stopped answering part of the way through.", limit=True, retry_at=time.time() + 60) from None
    finally:
        try:
            response.close()
        except OSError:
            pass
    for index in sorted(calls):
        slot = calls[index]
        try:
            arguments = json.loads(slot["arguments"] or "{}")
        except ValueError:
            arguments = {}
        yield {"call": {"id": slot["id"] or f"call_{index}", "name": slot["name"], "arguments": arguments if isinstance(arguments, dict) else {}}}
    yield {"done": reason or ("tool_calls" if calls else "stop"),
           "usage": {"input": int(usage.get("prompt_tokens") or 0), "output": int(usage.get("completion_tokens") or 0),
                     "cached": int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)}}


def _clean(message: dict) -> dict:
    out = dict(message)
    if isinstance(out.get("content"), str):
        out["content"] = redact(out["content"])
    return out


def ask(cfg, ident: str, model: str, system: str, user: str, max_tokens: int = 1200, timeout: float = 90.0) -> dict:
    """One question, one answer (no tools). Returns {"text", "usage", "sources"}."""
    text, usage, sources = "", {}, []
    for piece in stream(cfg, ident, model, [{"role": "system", "content": system}, {"role": "user", "content": user}], max_tokens=max_tokens, timeout=timeout):
        if "text" in piece:
            text += piece["text"]
        elif "sources" in piece:
            sources = piece["sources"]
        elif "done" in piece:
            usage = piece.get("usage") or {}
    return {"text": redact(text).strip(), "usage": usage, "sources": sources}
