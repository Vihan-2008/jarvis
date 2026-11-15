"""The first command, given to an INSTALLED JARVIS as a new user would give it, and checked.

    python scripts/first_command_check.py --app-dir <install folder> [--say "open notepad"] [--expect Notepad]

Starts the installed copy's own service (with its own Python, on a port of its own, its data in a temporary folder so
nothing of a real install is touched), sends the words the way JARVIS's window does when they are typed, and checks
the answer: that JARVIS understood it and did it itself (no AI account needed), and that the app is now running.
Used on GitHub's machines after installing the real package; it opens a real app, so it is not for a person's own PC.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


def runtime(app: Path) -> str:
    """The installed copy's Python (python.exe beside the pythonw.exe the shortcuts use), as its installer chose it."""
    named = Path((app / ".python").read_text("utf-8").strip())
    plain = named.with_name("python.exe") if named.name.lower() == "pythonw.exe" else named
    return str(plain if plain.exists() else named)


def call(port: int, token: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method="POST" if data else "GET",
                                     headers={"X-JCC-Token": token, "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as answer:
        return json.loads(answer.read())


def running(name: str) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}.exe"], capture_output=True, text=True).stdout
        return name.lower() in out.lower()
    return subprocess.run(["pgrep", "-x", name], capture_output=True).returncode == 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-dir", required=True)
    parser.add_argument("--say", default="open notepad" if os.name == "nt" else "open calculator")
    parser.add_argument("--expect", default="notepad" if os.name == "nt" else "Calculator", help="the program that should be running afterwards")
    parser.add_argument("--port", type=int, default=8799)
    args = parser.parse_args(argv)
    app = Path(args.app_dir).resolve()
    state = Path(tempfile.mkdtemp(prefix="jarvis-first-"))
    env = {**os.environ, "JCC_STATE_DIR": str(state / "state"), "JCC_VOICE_STATE": str(state / "state"), "JCC_NO_CREDMAN": "1"}
    env.pop("PYTHONPATH", None)
    started = time.time()
    service = subprocess.Popen([runtime(app), "-m", "jcc", "gui", "--no-browser", "--no-watch", "--port", str(args.port)], cwd=app, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        page = ""
        for _ in range(240):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{args.port}/", timeout=3) as answer:
                    page = answer.read().decode("utf-8", "replace")
                    break
            except OSError:
                if service.poll() is not None:
                    print(service.stdout.read()[-3000:])
                    raise SystemExit("JARVIS stopped before it answered.")
                time.sleep(0.5)
        found = re.search(r'const TOKEN="([^"]{10,80})"', page)
        if not found:
            raise SystemExit("JARVIS did not answer with its window within two minutes.")
        print(f"JARVIS answered after {time.time() - started:.1f} s")
        token = found.group(1)
        said = call(args.port, token, "/api/voice", {"action": "say", "text": args.say, "chat": None})
        print("asked:", args.say, "->", {k: said.get(k) for k in ("instant", "model", "chat")})
        if not said.get("instant"):
            raise SystemExit("JARVIS did not do it itself: it would need an AI for this (instant answer expected).")
        chat = call(args.port, token, "/api/chat?id=" + said["chat"])
        reply = next((m["content"] for m in reversed(chat["messages"]) if m["role"] == "assistant"), "")
        print("JARVIS said:", reply)
        for _ in range(40):
            if running(args.expect):
                break
            time.sleep(0.5)
        else:
            raise SystemExit(f"{args.expect} is not running after the command.")
        print(f"{args.expect} is running: the first command worked, {time.time() - started:.1f} s after JARVIS was started.")
        return 0
    finally:
        service.terminate()
        try:
            service.wait(15)
        except subprocess.TimeoutExpired:
            service.kill()
        shutil.rmtree(state, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
