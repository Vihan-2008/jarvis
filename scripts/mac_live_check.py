"""Checks on a real Mac what the tests can only stand in for: the windows, a window's controls, typing, clicking, keys,
pictures of the screen, the microphone, the wake word model and the measuring of the Mac's own sound.

    python3 scripts/mac_live_check.py [--sound-helper PATH] [--wake-models FOLDER]

It opens TextEdit with a small file of its own in a temporary folder, types into it, presses things in it, and closes
it again without saving. It will not start while TextEdit is already open, so it can never touch a document of yours.
The pointer moves and keys are pressed while it runs: leave the Mac alone for the half minute it takes.

Each line of the report says "ok", "FAILED" (something JARVIS relies on did not work) or "skipped" (this Mac cannot do
it right now: no permission, no microphone, no speakers). It ends with status 1 if anything failed.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jcc import mac as mac_tools, macax, macdesk, macsound  # noqa: E402

rows: list[tuple[str, str, str]] = []
MARK = "jarvis-live-check"


class Skip(Exception):
    pass


def check(name: str, work) -> object:
    try:
        said = work()
        rows.append((name, "ok", "" if said is None else str(said)))
        return said
    except Skip as why:
        rows.append((name, "skipped", str(why)))
    except Exception as problem:  # noqa: BLE001 - every check reports, none stops the others
        rows.append((name, "FAILED", f"{type(problem).__name__}: {problem}"))
    print(f"[{rows[-1][1]:7}] {rows[-1][0]}" + (f": {rows[-1][2]}" if rows[-1][2] else ""), flush=True)
    return None


def report_last() -> None:
    if rows:
        print(f"[{rows[-1][1]:7}] {rows[-1][0]}" + (f": {rows[-1][2]}" if rows[-1][2] else ""), flush=True)


def run(name: str, work):
    before = len(rows)
    result = check(name, work)
    if len(rows) > before and rows[-1][1] == "ok":
        report_last()
    return result


def wait_for(what, seconds: float = 20.0, pause: float = 0.25):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        found = what()
        if found:
            return found
        time.sleep(pause)
    return None


def option(name: str) -> str:
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv and sys.argv.index(name) + 1 < len(sys.argv) else ""


def main() -> int:
    if sys.platform != "darwin":
        print("This check is for a Mac.")
        return 2
    print(f"macOS {platform.mac_ver()[0]} on {platform.machine()}, Python {platform.python_version()}", flush=True)
    m = run("macOS's own libraries load", lambda: macax.mac() and "ApplicationServices and CoreFoundation")
    if not m:
        return 1
    m = macax.mac()
    trusted, sees = m.trusted(), m.sees_screen()
    run("what macOS has allowed", lambda: f"Accessibility: {'yes' if trusted else 'no'}; Screen Recording: {'yes' if sees else 'no'}")
    run("the screens", lambda: ", ".join(f"{s['width']}x{s['height']} at ({s['left']},{s['top']})" + (" main" if s["main"] else "") for s in m.displays())
        or (_ for _ in ()).throw(OSError("no screen was listed")))
    run("where the pointer is", lambda: "(%d, %d)" % m.pointer())
    if any(row["app"] == "TextEdit" for row in m.rows(every=True)):
        print("TextEdit is open. Close it first: this check uses a TextEdit window of its own and closes it without saving.")
        return 2

    folder = Path(tempfile.mkdtemp(prefix=MARK + "-"))
    note = folder / (MARK + ".txt")
    note.write_text("start\n", "utf-8")
    windows, controls = macdesk.Windows(m), macdesk.Controls(m)
    desk = macdesk.Desktop(m, None, windows)
    state: dict = {}
    try:
        subprocess.run(["open", "-a", "TextEdit", str(note)], capture_output=True, timeout=30)

        def textedit():
            row = wait_for(lambda: next((r for r in m.rows() if r["app"] == "TextEdit"), None), 40)
            if not row:
                raise OSError("TextEdit's window did not appear; windows seen: " + ", ".join(sorted({r["app"] for r in m.rows()})))
            state["handle"] = row["handle"]
            return f"window {row['handle']} at {row['box']}, {len(m.rows())} windows on the screen"
        run("the open windows are listed", textedit)
        handle = state.get("handle", 0)

        def titled():
            if not handle:
                raise Skip("no window")
            title = wait_for(lambda: (lambda t: t if MARK in t else "")(macdesk.Windows(m).title(handle)), 10)
            if title:
                return title
            if not trusted and not sees:
                raise Skip("neither permission is given, so macOS gives no titles: " + repr(windows.title(handle)))
            raise OSError("the title was " + repr(windows.title(handle)))
        run("a window's title is known", titled)

        def needs_trust():
            if not handle:
                raise Skip("no window")
            if not trusted:
                raise Skip("Accessibility is not allowed for this process")

        def front():
            needs_trust()
            if not windows.focus(handle):
                raise OSError(f"in front is {windows.foreground()}, wanted {handle}")
            return "TextEdit is in front"
        run("a window is brought to the front", front)

        def listed():
            needs_trust()
            got = controls.call({"op": "list", "h": handle, "max": 200}, 20.0)
            if got.get("error"):
                raise OSError(got["error"])
            state["items"] = got["items"]
            if not any(item["t"] == "Edit" for item in got["items"]):
                raise OSError("no text box among: " + "; ".join(f"{i['t']}:{i['n']}" for i in got["items"][:30]))
            return f"{len(got['items'])} controls: " + "; ".join(f"{i['t']}:{i['n'] or '-'}" for i in got["items"][:25])
        run("a window's controls are listed", listed)

        def text_now() -> str:
            walked = m.walk(handle)
            try:
                area = next((n for n in walked["nodes"] if n["role"] == "AXTextArea"), None)
                if not area:
                    raise OSError("the text area was not found")
                return str(m._plain(area["el"], "AXValue") or "")
            finally:
                m.done(walked)

        def filled():
            needs_trust()
            got = controls.call({"op": "set", "h": handle, "name": "", "text": "Filled by JARVIS"}, 20.0)
            time.sleep(0.4)
            now = text_now()
            if got.get("how") != "set" or now.strip() != "Filled by JARVIS":
                raise OSError(f"how={got.get('how')!r}, the text is {now[:60]!r}")
            return "the text box was filled directly"
        run("a box is filled by name", filled)

        def typed():
            needs_trust()
            windows.focus(handle)
            area = next((i for i in state.get("items", []) if i["t"] == "Edit"), None)
            if area:
                controls.call({"op": "set", "h": handle, "name": "", "text": ""}, 20.0)
            desk.look(handle)
            if area:
                at = desk.shown(area["x"], area["y"])
                desk.perform({"action": "click", "x": at[0], "y": at[1]})
                time.sleep(0.3)
            desk.perform({"action": "type", "text": "Typed by JARVIS 123 é ok"})
            now = wait_for(lambda: (lambda t: t if "Typed by JARVIS 123 é ok" in t else "")(text_now()), 5)
            if not now:
                raise OSError("after clicking and typing the text is " + repr(text_now()[:80]))
            return "clicked in the text and typed, accents included"
        run("a click and typing arrive in the window", typed)

        def shortcut():
            needs_trust()
            windows.focus(handle)
            desk.perform({"action": "key", "keys": "cmd+a"})
            time.sleep(0.2)
            desk.perform({"action": "type", "text": "Replaced"})
            now = wait_for(lambda: (lambda t: t if t.strip() == "Replaced" else "")(text_now()), 5)
            if not now:
                raise OSError("after Command-A and typing the text is " + repr(text_now()[:80]))
            return "Command-A selected everything, typing replaced it"
        run("a shortcut is pressed", shortcut)

        def under_pointer():
            needs_trust()
            area = next((i for i in state.get("items", []) if i["t"] == "Edit"), None)
            if not area:
                raise Skip("no text box was listed")
            got = controls.call({"op": "at", "x": area["x"], "y": area["y"]}, 10.0).get("item")
            if not got or got["t"] != "Edit":
                raise OSError(f"at the text box's middle macOS reports {got}")
            return "the control under a point is known"
        run("the control at a point", under_pointer)

        def pressed():
            needs_trust()
            box = next((i for i in state.get("items", []) if i["t"] == "CheckBox" and i["n"] and i["on"]), None)
            if not box:
                raise Skip("this window has no named tick box to try: " + "; ".join(sorted({i["t"] for i in state.get("items", [])})))

            def value():
                walked = m.walk(handle)
                try:
                    for n in walked["nodes"]:
                        item = macdesk.describe(n, walked["frame"])
                        if item and item["t"] == "CheckBox" and item["n"] == box["n"]:
                            return m._plain(n["el"], "AXValue")
                finally:
                    m.done(walked)
                return None
            before = value()
            how = controls.call({"op": "press", "h": handle, "name": box["n"]}, 10.0).get("how")
            time.sleep(0.4)
            after = value()
            if how == "click" or before == after:
                raise OSError(f"pressing {box['n']!r}: how={how!r}, its value was {before!r} and is {after!r}")
            controls.call({"op": "press", "h": handle, "name": box["n"]}, 10.0)       # (and back again)
            return f'"{box["n"]}" was {how} by name: {before!r} -> {after!r}'
        run("a control is pressed by name", pressed)

        def scrolled():
            needs_trust()
            desk.move_pointer(*windows.middle(handle))
            desk.perform({"action": "scroll", "amount": -2})
            return "the wheel was turned over the window"
        run("scrolling", scrolled)

        def pictured():
            if not sees:
                raise Skip("Screen Recording is not allowed for this process")
            wide, high, data = desk.capture(handle)
            if wide > macdesk.SHOT_WIDTH or wide < 200 or high < 100 or len(data) < 2000:
                raise OSError(f"the picture is {wide}x{high}, {len(data)} bytes")
            return f"{wide}x{high}, {len(data)} bytes, one picture pixel is {desk.scale:.3f} points"
        run("a picture of the screen", pictured)

        def window_pictured():
            if not sees or not handle:
                raise Skip("Screen Recording is not allowed for this process")
            wide, high, data = macdesk.picture_of_window(handle, m)
            return f"{wide}x{high}, {len(data)} bytes"
        run("a picture of one window", window_pictured)
    finally:
        subprocess.run(["pkill", "-x", "TextEdit"], capture_output=True)
        shutil.rmtree(folder, ignore_errors=True)

    def volume():
        try:
            return f"{mac_tools.volume()} percent"
        except ValueError as problem:
            raise Skip(str(problem) + " (a Mac with no speakers)") from None
    run("the speaker volume is read", volume)

    def brightness():
        try:
            return f"{m.brightness()} percent"
        except ValueError as problem:
            raise Skip(str(problem)) from None
    run("the screen brightness is read", brightness)

    def microphone():
        heard = []
        mic = macsound.Microphone(None, 3200)
        try:
            mic.start(heard.append, limit=1.5)
        except ValueError as problem:
            raise Skip(str(problem)) from None
        mic.thread.join(timeout=6)
        total = sum(len(piece) for piece in heard)
        if not total:
            raise Skip("the microphone opened but no sound arrived in a second and a half (no microphone, or not allowed)")
        loud = max((abs(int.from_bytes(piece[i:i + 2], "little", signed=True)) for piece in heard for i in range(0, len(piece) - 1, 64)), default=0)
        return f"{total} bytes in {len(heard)} pieces of 16 kHz sound, loudest sample {loud}"
    run("the microphone is recorded", microphone)

    def wake_word():
        folder = option("--wake-models")
        if not folder:
            raise Skip("no --wake-models folder was given")
        try:
            import numpy  # noqa: F401
            import onnxruntime  # noqa: F401
        except ImportError as problem:
            raise Skip(f"numpy and onnxruntime are needed ({problem})") from None
        from jcc import wakeword
        files = {name: Path(folder) / file for name, file in wakeword.FILES.items()}
        missing = [str(path) for path in files.values() if not path.is_file()]
        if missing:
            raise Skip("the model's files are not there: " + ", ".join(missing))
        work = Path(tempfile.mkdtemp(prefix=MARK + "-say-"))
        try:
            def best(words: str) -> float:
                spoken, plain = work / "say.aiff", work / "say.wav"
                made = subprocess.run(["say", "-o", str(spoken), words], capture_output=True, timeout=60)
                if made.returncode != 0 or not spoken.is_file():
                    raise Skip("the Mac's own voice (say) is not available here")
                subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(spoken), str(plain)], capture_output=True, timeout=60, check=True)
                import wave
                with wave.open(str(plain), "rb") as sound:
                    pcm = sound.readframes(sound.getnframes())
                spotter = wakeword.Spotter(files)
                scores = spotter.feed(b"\x00" * 32000 + pcm + b"\x00" * 32000)
                return max(scores, default=0.0)
            name, other = best("Hey Jarvis, what time is it?"), best("The weather is lovely this afternoon, is it not?")
            if name < 0.5 or other >= 0.5:
                raise OSError(f'"Hey Jarvis" scored {name:.2f} (wanted 0.5 or more) and ordinary talk scored {other:.2f} (wanted less)')
            return f'"Hey Jarvis" scored {name:.2f}; ordinary talk scored {other:.2f}'
        finally:
            shutil.rmtree(work, ignore_errors=True)
    run('the wake word model hears "Hey Jarvis" on this Mac', wake_word)

    def own_sound():
        program = option("--sound-helper")
        if not program:
            raise Skip("no --sound-helper program was given")
        if not Path(program).is_file():
            raise OSError("the helper was not built: " + program)
        meter = macsound.OutputMeter(program)
        try:
            meter.open()
        except OSError as problem:
            raise Skip(str(problem)) from None
        try:
            import threading
            threading.Thread(target=lambda: macsound.tone(440, 1500, 0.8), daemon=True).start()
            loudest, quiet_first = 0.0, meter.peak()
            until = time.monotonic() + 3.0
            while time.monotonic() < until:
                loudest = max(loudest, meter.peak())
                time.sleep(0.02)
            if loudest < 0.01:
                raise Skip(f"the helper runs and reports, but a tone played on this Mac was not heard by it (loudest {loudest:.4f}): no speakers here")
            return f"a tone played on the Mac was measured at {loudest:.2f} (before it: {quiet_first:.2f})"
        finally:
            meter.close()
    run("the Mac's own sound is measured", own_sound)

    def helper():
        home = Path(tempfile.mkdtemp(prefix=MARK + "-home-"))
        try:
            env = {**os.environ, "HOME": str(home), "PYTHONPATH": str(ROOT), "JCC_NO_LOCAL_CONFIG": "1"}
            done = subprocess.run([sys.executable, "-m", "jcc.tray", "--check"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
            status = list(home.rglob("tray-status.json"))
            if done.returncode != 0 or not status:
                raise OSError(f"exit {done.returncode}; {done.stderr.strip()[-300:]}")
            return "started, wrote what it is doing, and stopped: " + status[0].read_text("utf-8")[:160]
        finally:
            shutil.rmtree(home, ignore_errors=True)
    run("the background helper starts", helper)

    failed = [row for row in rows if row[1] == "FAILED"]
    print(f"\n{sum(1 for r in rows if r[1] == 'ok')} ok, {len(failed)} failed, {sum(1 for r in rows if r[1] == 'skipped')} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
