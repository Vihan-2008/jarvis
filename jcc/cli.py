"""Command line: `python -m jcc <command>` (or jcc.cmd).

  ask "<request>"     route and run one request, print the answer, write a receipt
  watch               process Inbox.md continuously (and retry queued requests)
  inbox               process Inbox.md once
  setup-vault         create folders and starter notes (never overwrites existing notes)
  keys set <name>     store a key in Windows Credential Manager (gemini | groq | bot | elevenlabs)
  keys status         show which keys are set (never prints them)
  test-providers      one tiny call to each configured free model
  usage               today's free-tier usage
"""

from __future__ import annotations

import argparse
import getpass
import sys

from jcc import config, secrets
from jcc.engine import Engine
from jcc.redact import redact


def _engine() -> Engine:
    return Engine(config.load())


def cmd_ask(text: str) -> int:
    e = _engine()
    try:
        r = e.process(text)
        print(f"[tier {r.tier} · {r.router_method} · {r.status} · {r.model}]")
        print(r.answer or r.error)
        print(f"\nReceipt: Requests/{r.id[0:4]}/{r.id[4:6]}/{r.id}.md")
        return 0 if r.status != "failed" else 1
    finally:
        e.close()


def cmd_watch(interval: float) -> int:
    import threading

    from jcc import watcher

    stop = threading.Event()
    try:
        ok = watcher.run(stop, interval, log=lambda m: print(m, flush=True))
        return 0 if ok else 1
    except KeyboardInterrupt:
        stop.set()
        return 0


def cmd_keys(action: str, name: str | None) -> int:
    if action == "status":
        for k, v in secrets.status().items():
            print(f"{k:7} {v}")
        return 0
    if name not in secrets.ENV_NAMES:
        print("name must be one of: " + ", ".join(secrets.ENV_NAMES), file=sys.stderr)
        return 2
    value = getpass.getpass(f"Paste the {name} key (hidden): ").strip()
    if not value:
        print("Nothing entered; unchanged.")
        return 1
    try:
        secrets.store(name, value)
    except (RuntimeError, ValueError) as problem:
        print(str(problem), file=sys.stderr)
        return 1
    if secrets.store_name() == "Credential Manager":
        print(f"Saved '{name}' in Windows Credential Manager (jarvis-command/{name}).")
    else:
        print(f"Saved '{name}' in {secrets.store_name()}.")
    return 0


def cmd_test_providers() -> int:
    e = _engine()
    ok = True
    try:
        for slot in ("gemini_lite", "gemini_flash", "groq"):
            if not e.models.available(slot):
                print(f"{slot:13} SKIP (no key or cap reached)")
                continue
            try:
                r = e.models.chat(slot, "Reply with one word.", "Say: ready", max_tokens=200)
                print(f"{slot:13} OK  model={r.model} tokens={r.tokens} {r.duration_ms}ms "
                      f"reply={r.text.strip()[:30]!r}")
            except Exception as ex:  # noqa: BLE001
                ok = False
                print(f"{slot:13} FAIL {redact(str(ex))[:150]}")
    finally:
        e.close()
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="jcc", description="JARVIS command center")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ask")
    a.add_argument("text", nargs="+")
    w = sub.add_parser("watch")
    w.add_argument("--interval", type=float, default=5)
    sub.add_parser("inbox")
    sub.add_parser("setup-vault")
    k = sub.add_parser("keys")
    k.add_argument("action", choices=["set", "status"])
    k.add_argument("name", nargs="?")
    sub.add_parser("test-providers")
    sub.add_parser("voice-check", help="check the ElevenLabs voice with the saved key (says one short phrase, uses a few credits)")
    sub.add_parser("usage")
    g = sub.add_parser("gui", help="open the JARVIS control screen (also runs the Inbox watcher)")
    g.add_argument("--port", type=int, default=8765)
    g.add_argument("--no-browser", action="store_true")
    g.add_argument("--no-watch", action="store_true", help="don't run the Inbox watcher here")
    args = p.parse_args(argv)

    if args.cmd == "gui":
        from jcc import gui

        return gui.serve(args.port, not args.no_browser, not args.no_watch)
    if args.cmd == "ask":
        return cmd_ask(" ".join(args.text))
    if args.cmd == "watch":
        return cmd_watch(args.interval)
    if args.cmd == "inbox":
        e = _engine()
        try:
            for r in e.process_inbox(min_age_s=0):
                print(f"{r.id} tier {r.tier} {r.status}")
        finally:
            e.close()
        return 0
    if args.cmd == "setup-vault":
        from jcc.setup_vault import setup

        for line in setup(config.load()):
            print(line)
        return 0
    if args.cmd == "voice-check":
        from jcc import speech
        try:
            result = speech.self_test(config.load())
        except ValueError as problem:
            print("Voice check failed: " + redact(str(problem)))
            return 1
        print(f"Voice check passed. Voice: {result['voice']}. First audio after {result['first_audio_seconds']}s, "
              f"{result['audio_seconds']}s of speech received.")
        return 0
    if args.cmd == "keys":
        return cmd_keys(args.action, args.name)
    if args.cmd == "test-providers":
        return cmd_test_providers()
    if args.cmd == "usage":
        e = _engine()
        try:
            for prov, u in e.usage.summary().items():
                print(f"{prov:13} {u['requests']}/{u['requests_cap']} requests  "
                      f"{u['tokens']:,}/{u['tokens_cap']:,} tokens")
        finally:
            e.close()
        return 0
    return 2
