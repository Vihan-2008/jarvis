"""API keys from environment variables or the system's own key store. Never from files.

Windows: Credential Manager, generic credentials named "jarvis-command/<name>".
macOS: the login Keychain, generic passwords of the service "JARVIS Command" with the name as the account.
Linux: the Secret Service (GNOME Keyring, KWallet) through secret-tool, when it is installed. When it is not, keys
come from the JCC_<NAME> environment variables only, and storing one says so.
Names: gemini, groq (a SEPARATE key from the trading bot's), bot (dashboard password).

A key is never put on a command line, where any other program of this computer could read it: the Mac and Linux
stores are given it on their standard input.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
from ctypes import wintypes

from jcc import system
from jcc.redact import register_secret

ENV_NAMES = {"gemini": "JCC_GEMINI_API_KEY", "groq": "JCC_GROQ_API_KEY", "bot": "JCC_BOT_PASSWORD",
             "supabase-sync": "JCC_SUPABASE_SYNC_KEY", "supabase-query": "JCC_SUPABASE_QUERY_KEY",
             "elevenlabs": "JCC_ELEVENLABS_API_KEY", "openai": "JCC_OPENAI_API_KEY",
             "mail": "JCC_MAIL_PASSWORD", "composio": "JCC_COMPOSIO_API_KEY"}
# Keys for other AI services the owner connects (jcc/providers.py).
ENV_NAMES.update({"ai-" + name: "JCC_AI_" + name.upper() + "_KEY" for name in (
    "xai", "perplexity", "deepseek", "mistral", "openrouter", "together", "cerebras", "fireworks", "moonshot", "cohere", "custom")})
# With JCC_NO_CREDMAN set (tests), nothing touches the real key store of any system: values live here instead.
_memory: dict[str, str] = {}
TARGET_PREFIX = "jarvis-command/"
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
KEYCHAIN_SERVICE = "JARVIS Command"
SECURITY = "/usr/bin/security"
SECRET_SERVICE = "jarvis-command"


class _CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_char)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def _advapi():  # type: ignore[no-untyped-def]
    if system.PLATFORM != "win32":
        return None
    return ctypes.WinDLL("advapi32", use_last_error=True)


def store_name() -> str:
    """Where keys are kept on this system, in the owner's words."""
    if system.PLATFORM == "win32":
        return "Credential Manager"
    if system.PLATFORM == "darwin":
        return "Keychain"
    return "the system key store"


# ---------------------------------------------------------------------------------------------- macOS: the Keychain
def _quoted(text: str) -> str:
    """One argument for `security -i`, which splits its input lines itself: in double quotes, with backslashes and
    quotes escaped. A line break would end the command early, so a value with one is refused before this."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _no_line_breaks(*parts: str) -> None:
    if any("\n" in p or "\r" in p or "\0" in p for p in parts):
        raise ValueError("A key cannot contain a line break.")


def _keychain_read(name: str, run=None) -> str | None:
    run = run or subprocess.run
    try:
        done = run([SECURITY, "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", name, "-w"],
                   capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.rstrip("\n") if done.returncode == 0 and done.stdout.strip() else None


def _keychain_store(name: str, value: str, run=None) -> None:
    run = run or subprocess.run
    _no_line_breaks(name, value)
    line = f"add-generic-password -U -s {_quoted(KEYCHAIN_SERVICE)} -a {_quoted(name)} -w {_quoted(value)}\n"
    try:
        done = run([SECURITY, "-i"], input=line, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError("The Keychain could not be reached, so the key was not saved.") from e
    # `security -i` reports a failed command on its error output but may still end with 0, so the key is read back.
    if done.returncode != 0 or _keychain_read(name, run) != value:
        raise RuntimeError("The Keychain did not accept the key, so it was not saved.")


def _keychain_delete(name: str, run=None) -> None:
    run = run or subprocess.run
    try:
        run([SECURITY, "delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", name],
            capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        pass


# ---------------------------------------------------------------------------------- Linux: the Secret Service
def _secret_tool() -> str | None:
    return shutil.which("secret-tool")


def _secret_read(name: str, run=None) -> str | None:
    run = run or subprocess.run
    tool = _secret_tool()
    if not tool:
        return None
    try:
        done = run([tool, "lookup", "service", SECRET_SERVICE, "account", name], capture_output=True, text=True,
                   timeout=15, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.rstrip("\n") if done.returncode == 0 and done.stdout.strip() else None


def _secret_store(name: str, value: str, run=None) -> None:
    run = run or subprocess.run
    tool = _secret_tool()
    if not tool:
        raise RuntimeError(f"There is no key store here (secret-tool is not installed), so the key was not saved. "
                           f"Set the {ENV_NAMES.get(name, 'JCC_' + name.upper().replace('-', '_'))} environment variable instead.")
    _no_line_breaks(name, value)
    try:
        done = run([tool, "store", f"--label={KEYCHAIN_SERVICE} {name}", "service", SECRET_SERVICE, "account", name],
                   input=value, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError("The key store could not be reached, so the key was not saved.") from e
    if done.returncode != 0:
        raise RuntimeError("The key store did not accept the key, so it was not saved.")


def _secret_delete(name: str, run=None) -> None:
    run = run or subprocess.run
    tool = _secret_tool()
    if not tool:
        return
    try:
        run([tool, "clear", "service", SECRET_SERVICE, "account", name], capture_output=True, text=True, timeout=15,
            stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        pass


# ------------------------------------------------------------------------------------------------ every system
def _cred_read(name: str) -> str | None:
    if os.environ.get("JCC_NO_CREDMAN"):  # tests: never touch the real stored keys
        return _memory.get(name)
    if system.PLATFORM == "darwin":
        return _keychain_read(name)
    if system.PLATFORM != "win32":
        return _secret_read(name)
    adv = _advapi()
    if adv is None:
        return None
    pcred = ctypes.POINTER(_CREDENTIAL)()
    if not adv.CredReadW(TARGET_PREFIX + name, CRED_TYPE_GENERIC, 0, ctypes.byref(pcred)):
        return None
    try:
        c = pcred.contents
        raw = ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize)
        return raw.decode("utf-16-le")
    finally:
        adv.CredFree(pcred)


def store(name: str, value: str) -> None:
    """Save a key into the system's key store (from `jcc keys set` or the app's own key field)."""
    if os.environ.get("JCC_NO_CREDMAN"):
        _memory[name] = value
        return
    if system.PLATFORM == "darwin":
        _keychain_store(name, value)
        return
    if system.PLATFORM != "win32":
        _secret_store(name, value)
        return
    adv = _advapi()
    if adv is None:
        raise RuntimeError("Credential Manager is only available on Windows; use env vars instead")
    blob = value.encode("utf-16-le")
    buf = ctypes.create_string_buffer(blob, len(blob))
    cred = _CREDENTIAL()
    cred.Type = CRED_TYPE_GENERIC
    cred.TargetName = TARGET_PREFIX + name
    cred.UserName = "jarvis-command"
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))
    cred.Persist = CRED_PERSIST_LOCAL_MACHINE
    if not adv.CredWriteW(ctypes.byref(cred), 0):
        raise OSError(ctypes.get_last_error(), "CredWriteW failed")


def delete(name: str) -> None:
    """Remove a saved value. Missing entries are fine."""
    if os.environ.get("JCC_NO_CREDMAN"):
        _memory.pop(name, None)
        return
    if system.PLATFORM == "darwin":
        _keychain_delete(name)
        return
    if system.PLATFORM != "win32":
        _secret_delete(name)
        return
    adv = _advapi()
    if adv is not None:
        adv.CredDeleteW(TARGET_PREFIX + name, CRED_TYPE_GENERIC, 0)


def get(name: str) -> str | None:
    """Env var first (handy for tests/CI), then the system's key store. Registers it for redaction."""
    value = os.environ.get(ENV_NAMES[name]) or _cred_read(name)
    if value:
        value = value.strip()
        register_secret(value)
    return value or None


def status() -> dict[str, str]:
    out = {}
    for name, env in ENV_NAMES.items():
        if os.environ.get(env):
            out[name] = f"set (env {env})"
        elif _cred_read(name):
            out[name] = f"set ({store_name()})"
        else:
            out[name] = "missing"
    return out
