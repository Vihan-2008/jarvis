"""Checks on a real Mac what the tests can only stand in for: the windows, a window's controls, typing, clicking, keys,
pictures of the screen, the microphone, the wake word model, the measuring of the Mac's own sound, the menu-bar icon,
the shortcuts that work from any app, and dictation.

    python3 scripts/mac_live_check.py [--sound-helper PATH] [--menu-helper PATH] [--wake-models FOLDER]

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
            # TextEdit's own Settings window has tick boxes: one is ticked by its name, and unticked again.
            needs_trust()
            windows.focus(handle)
            m.key(43, 1 << 20)                                                       # Command-comma opens an app's settings
            other = wait_for(lambda: next((r["handle"] for r in m.rows() if r["app"] == "TextEdit" and r["handle"] != handle), 0), 10)
            if not other:
                raise Skip("TextEdit's Settings window did not open")
            try:
                got = controls.call({"op": "list", "h": other, "max": 200}, 20.0)
                box = next((i for i in got.get("items", []) if i["t"] == "CheckBox" and i["n"] and i["on"]), None)
                if not box:
                    raise OSError("no named tick box among: " + "; ".join(f"{i['t']}:{i['n'] or '-'}" for i in got.get("items", [])[:30]))

                def value():
                    walked = m.walk(other)
                    try:
                        for n in walked["nodes"]:
                            item = macdesk.describe(n, walked["frame"])
                            if item and item["t"] == "CheckBox" and item["n"] == box["n"]:
                                return m._plain(n["el"], "AXValue")
                    finally:
                        m.done(walked)
                    return None
                before = value()
                how = controls.call({"op": "press", "h": other, "name": box["n"]}, 10.0).get("how")
                time.sleep(0.4)
                after = value()
                controls.call({"op": "press", "h": other, "name": box["n"]}, 10.0)   # (and back again, as it was)
                time.sleep(0.3)
                back = value()
                if how == "click" or before == after or back != before:
                    raise OSError(f"pressing {box['n']!r}: how={how!r}, its value was {before!r}, then {after!r}, then {back!r}")
                return (f'"{box["n"]}" in TextEdit\'s Settings was {how} by name ({before!r} -> {after!r}) and put back; '
                        f'that window listed {len(got["items"])} controls: ' + "; ".join(f"{i['t']}:{i['n'] or '-'}" for i in got["items"][:12]))
            finally:
                windows.focus(other)
                m.key(13, 1 << 20)                                                   # Command-W closes the Settings window
                time.sleep(0.3)
        run("a control is pressed by name", pressed)

        def scrolled():
            needs_trust()
            desk.move_pointer(*windows.middle(handle))
            desk.perform({"action": "scroll", "amount": -2})
            return "the wheel was turned over the window"
        run("scrolling", scrolled)

        def dictated():
            # What dictation heard is typed where the cursor is. The recording and the speech service are stood in for
            # here (a real voice cannot be had on this machine); the waiting for the keys and the typing are real.
            needs_trust()
            from jcc import config, dictate
            said: list = []

            class Heard:
                heard_speech = True

                def start(self):
                    pass

                def finished_speaking(self):
                    return False

                def stop(self):
                    return b"\x01\x00" * 16000
            windows.focus(handle)
            controls.call({"op": "set", "h": handle, "name": "", "text": ""}, 20.0)
            one = dictate.Dictation(config.load(), said.append, recorder=Heard, hear=lambda sound: "dictated on a Mac", beep=lambda pitch: None)
            if (one.toggle(), one.toggle()) != ("listening", "typing"):
                raise OSError("dictation did not start and stop: " + "; ".join(said))
            # (TextEdit itself gives a sentence its capital letter, so the words are compared without regard to case.)
            now = wait_for(lambda: (lambda t: t if "dictated on a mac" in t.lower() else "")(text_now()), 8)
            if not now:
                raise OSError(f"the text is {text_now()[:80]!r}; JARVIS said {said}")
            return f"what dictation heard was typed where the cursor is: {now.strip()!r}"
        run("dictation types into the app in front", dictated)

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
            import wave

            def best(words: str, voice: str) -> tuple[float, int]:
                """(the model's highest score, how loud the speech was) for these words in one of the Mac's voices."""
                spoken, plain = work / "say.aiff", work / "say.wav"
                for old in (spoken, plain):
                    old.unlink(missing_ok=True)
                made = subprocess.run(["say", *(["-v", voice] if voice else []), "-o", str(spoken), words], capture_output=True, timeout=60)
                if made.returncode != 0 or not spoken.is_file():
                    return -1.0, 0
                subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(spoken), str(plain)], capture_output=True, timeout=60, check=True)
                with wave.open(str(plain), "rb") as sound:
                    pcm = sound.readframes(sound.getnframes())
                loud = max((abs(int.from_bytes(pcm[i:i + 2], "little", signed=True)) for i in range(0, len(pcm) - 1, 16)), default=0)
                spotter = wakeword.Spotter(files)
                return max(spotter.feed(b"\x00" * 32000 + pcm + b"\x00" * 32000), default=0.0), loud
            # The voices a Mac comes with differ from one macOS to the next, and some are too flat for any wake word.
            # The name must be heard in at least one natural voice, and ordinary talk in none.
            tried = []
            for voice in ("", "Samantha", "Alex", "Daniel", "Karen", "Fred"):
                name, loud = best("Hey Jarvis, what time is it?", voice)
                if name < 0:
                    continue
                other, _ = best("The weather is lovely this afternoon, is it not?", voice)
                tried.append((voice or "the usual voice", name, other, loud))
            if not tried:
                raise Skip("the Mac's own voice (say) is not available here")
            told = "; ".join(f'{voice}: "Hey Jarvis" {name:.2f}, ordinary talk {other:.2f}, loudest sample {loud}' for voice, name, other, loud in tried)
            if not any(name >= 0.5 for _, name, _, _ in tried) or any(other >= 0.5 for _, _, other, _ in tried):
                raise OSError("the name was not heard in any voice, or ordinary talk was taken for it. " + told)
            return told
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

    def dictation_records():
        from jcc import config, dictate
        said: list = []
        one = dictate.Dictation(config.load(), said.append, hear=lambda sound: "", beep=lambda pitch: None)
        first = one.toggle()
        if first != "listening":
            raise Skip("dictation could not start listening: " + "; ".join(said))
        time.sleep(1.2)
        second = one.toggle()
        wait_for(lambda: bool(said), 6)
        if second != "typing":
            raise OSError(f"the second press gave {second!r}")
        return f"it listened with the real microphone and stopped; with nothing said, JARVIS says: {said[0] if said else '(nothing)'}"
    run("dictation listens with the real microphone", dictation_records)

    def menu_bar():
        program = option("--menu-helper")
        if not program:
            raise Skip("no --menu-helper program was given")
        if not Path(program).is_file():
            raise OSError("the program was not built: " + program)
        from jcc import tray
        used: list = []
        menu = tray.MacMenu({name: (lambda name=name: used.append(name)) for name in ("open", "talk", "dictate", "stop", "quit")}, program=program)
        if not menu.open():
            raise OSError("the menu-bar program did not start, or did not say what it set up")
        state["menu"], state["used"] = menu, used
        if not menu.icon:
            raise OSError(f"no icon was added; shortcuts: {menu.keys}")
        missing = [name for name in ("open", "talk", "dictate", "stop") if name not in menu.keys]
        if missing:
            raise OSError(f"shortcuts not set up: {missing}; set up: {menu.keys}")
        return "the icon was added; shortcuts: " + ", ".join(f"{name} = {label}" for name, label in sorted(menu.keys.items()))
    run("the menu-bar icon and the shortcuts are set up", menu_bar)

    def shortcut_anywhere():
        menu, used = state.get("menu"), state.get("used")
        if not menu or not menu.running():
            raise Skip("the menu-bar program is not running")
        if not trusted:
            raise Skip("Accessibility is not allowed, so no key can be pressed to try it")
        codes = {"J": 38, "T": 17, "K": 40, "Space": 49, "D": 2, "Y": 16, "U": 32, "Delete": 51}
        for name in ("open", "talk", "dictate", "stop"):
            m.key(codes[menu.keys[name].rsplit("+", 1)[-1]], (1 << 18) | (1 << 19))          # Control and Option held
            if not wait_for(lambda: name in used, 4, 0.05):
                raise OSError(f"{menu.keys[name]} was pressed but \"{name}\" did not arrive; arrived: {used}")
        return "each was pressed while another app was in front and reached JARVIS: " + ", ".join(used)
    run("a shortcut pressed in any app reaches JARVIS", shortcut_anywhere)

    def menu_entries():
        import threading
        menu, used = state.get("menu"), state.get("used")
        if not menu or not menu.running():
            raise Skip("the menu-bar program is not running")
        if not trusted:
            raise Skip("Accessibility is not allowed, so the menu cannot be opened to try it")
        app, keep = m._app(menu.proc.pid), []
        try:
            error, bar = m._copy(app, "AXExtrasMenuBar")
            if not bar:
                raise Skip(f"macOS did not list the menu-bar icon through Accessibility (answer {error})")
            keep.append(bar)
            top = m.read(bar, keep)
            icon = next((item for item in (m.read(child, keep) for child in (top or {}).get("children", [])) if item), None)
            if not icon:
                raise OSError("the program's part of the menu bar lists no icon")
            label = icon["title"] or icon["description"] or "(no name)"
            before = len(used)
            opener = threading.Thread(target=lambda: m.press(icon["el"]), daemon=True)      # (it may only answer once the menu closes)
            opener.start()
            opener.join(3)
            time.sleep(0.6)
            entries = []
            for child in (m.read(icon["el"], keep) or {}).get("children", []):
                for entry in (m.read(child, keep) or {}).get("children", []):
                    one = m.read(entry, keep)
                    if one:
                        entries.append(one)
            names = [entry["title"] for entry in entries if entry["title"]]
            talk = next((entry for entry in entries if entry["title"].startswith("Talk to JARVIS")), None)
            if not talk:
                m.key(53)                                                            # Escape closes a menu
                raise Skip(f'the icon is listed as "{label}", but its menu could not be read through Accessibility; entries seen: {names}')
            chooser = threading.Thread(target=lambda: m.press(talk["el"]), daemon=True)
            chooser.start()
            chooser.join(3)
            if not wait_for(lambda: "talk" in used[before:], 4, 0.05):
                m.key(53)
                raise OSError(f'"Talk to JARVIS" was chosen in the menu but did not arrive; menu: {names}')
            return f'the icon is listed as "{label}"; its menu: {"; ".join(names)}; "Talk to JARVIS" was chosen and reached JARVIS'
        finally:
            m.release(keep)
            m.lib.CFRelease(app)
    run("the menu on the menu-bar icon", menu_entries)
    if state.get("menu"):
        state["menu"].close()

    failed = [row for row in rows if row[1] == "FAILED"]
    print(f"\n{sum(1 for r in rows if r[1] == 'ok')} ok, {len(failed)} failed, {sum(1 for r in rows if r[1] == 'skipped')} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
