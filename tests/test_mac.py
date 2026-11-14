"""The assistant's tools on a Mac (and what Linux has), with the Mac stood in for: a fake subprocess.run and Popen record
what would have been run, and jcc.system.PLATFORM says which system it is. These run on any system."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jcc import desktop, mac, quick, reminders, system, voice_tools
from tests.helpers import EngineTestCase


class Recorder:
    """Stands in for subprocess.run and subprocess.Popen. `answers` maps the program's name to what it prints."""

    def __init__(self, answers=None, codes=None):
        self.calls, self.answers, self.codes = [], answers or {}, codes or {}

    def __call__(self, argv, **kw):
        self.calls.append((list(argv), kw))
        name = Path(str(argv[0])).name
        return subprocess.CompletedProcess(argv, self.codes.get(name, 0), self.answers.get(name, ""), "")

    @property
    def argvs(self):
        return [argv for argv, _ in self.calls]


class OnAMac(unittest.TestCase):
    platform = "darwin"

    def setUp(self):
        self.run = Recorder({"osascript": "35\n", "pbpaste": "copied words"})
        self.patches = [mock.patch.object(system, "PLATFORM", self.platform), mock.patch("subprocess.run", self.run),
                        mock.patch("subprocess.Popen", self.run)]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()

    def toolbox(self, opened=""):
        self.asked = []

        def service(op, payload):
            self.asked.append((op, payload))
            if op == "do":
                return {"opened": opened}
            return {"ok": True, "permit": "p"} if op == "gate" else {}
        controls = type("NoControls", (), {"call": lambda self, payload, timeout=10: {}, "close": lambda self: None})()
        box = voice_tools.Toolbox(None, service, None, controls)
        box.state_dir = Path(tempfile.mkdtemp(prefix="jcc-mac-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(box.state_dir, ignore_errors=True))
        return box


class TestTheToolsOffered(OnAMac):
    def test_tools_that_need_windows_are_not_offered_on_a_mac(self):
        names = {tool["name"] for tool in voice_tools.offered(full=True)}
        self.assertFalse(names & voice_tools.WINDOW_TOOLS, "no tool that works inside other apps' windows")
        self.assertNotIn("play_show", names)
        self.assertNotIn("set_brightness", names)
        for kept in ("open_app", "open_website", "open_file", "find_files", "run_command", "read_clipboard", "write_clipboard", "set_volume", "lock_pc", "media"):
            self.assertIn(kept, names)
        command = next(tool for tool in voice_tools.offered(full=True) if tool["name"] == "run_command")
        self.assertIn("zsh", command["description"])
        everyday = voice_tools.offered()
        more = next(tool for tool in everyday if tool["name"] == "more")
        self.assertNotIn("PowerShell", more["description"])
        self.assertFalse({tool["name"] for tool in everyday} & voice_tools.WINDOW_TOOLS)

    def test_a_windows_only_tool_called_anyway_answers_with_one_sentence(self):
        box = self.toolbox()
        for name, args in (("click", {"x": 1, "y": 2}), ("type_text", {"text": "hi"}), ("list_controls", {})):
            reply = voice_tools.handle(box, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})
            self.assertTrue(reply["result"]["isError"])
            self.assertEqual(reply["result"]["content"][0]["text"], "Controlling other apps' windows is only available on Windows for now.")
        self.assertEqual(self.asked, [], "nothing was asked for or done")

    def test_on_windows_every_tool_is_still_offered(self):
        with mock.patch.object(system, "PLATFORM", "win32"):
            self.assertEqual({tool["name"] for tool in voice_tools.offered(full=True)}, voice_tools.NAMES)
            command = next(tool for tool in voice_tools.offered(full=True) if tool["name"] == "run_command")
            self.assertIn("PowerShell", command["description"])

    def test_linux_offers_less_and_says_so(self):
        with mock.patch.object(system, "PLATFORM", "linux"):
            names = {tool["name"] for tool in voice_tools.offered(full=True)}
            self.assertNotIn("open_app", names)
            self.assertNotIn("read_clipboard", names)
            self.assertIn("run_command", names)
            self.assertEqual(voice_tools.missing("set_volume"), "The volume is not available on Linux yet.")


class TestMacTools(OnAMac):
    def test_the_clipboard_goes_through_pbcopy_and_pbpaste(self):
        box = self.toolbox()
        self.assertEqual(box.write_clipboard("secret plan for bread"), "Copied. The user can paste it now.")
        argv, kw = self.run.calls[-1]
        self.assertEqual(argv, ["pbcopy"])
        self.assertEqual(kw["input"], "secret plan for bread")
        self.assertNotIn("secret plan", " ".join(" ".join(a) for a in self.run.argvs), "the text is never on a command line")
        self.assertEqual(box.read_clipboard(), "copied words")
        self.assertEqual(self.run.argvs[-1], ["pbpaste"])

    def test_the_volume_is_set_with_a_whole_number_only(self):
        box = self.toolbox()
        self.assertEqual(box.set_volume(40), "The volume is now 40 percent.")
        self.assertEqual(self.run.argvs[-1], ["osascript", "-e", "set volume output volume 40"])
        self.assertEqual(box.set_volume(250), "The volume is now 100 percent.")
        self.assertEqual(box.set_volume(), "The volume is 35 percent.")
        with self.assertRaises(voice_tools.Refused):
            box.set_volume('40" & do shell script "say hi')
        self.assertFalse(any("shell script" in " ".join(argv) for argv in self.run.argvs), "model text never reaches AppleScript")

    def test_media_keys_say_what_a_mac_cannot_do(self):
        box = self.toolbox()
        with self.assertRaises(voice_tools.Refused) as told:
            box.media("play_pause")
        self.assertIn("not available on a Mac", str(told.exception))
        self.assertEqual(box.media("mute"), "Done.")
        self.assertEqual(self.run.argvs[-1], ["osascript", "-e", "set volume output muted not (output muted of (get volume settings))"])

    def test_locking_puts_the_screen_to_sleep(self):
        box = self.toolbox()
        self.assertEqual(box.lock_pc(), "Locked.")
        self.assertEqual(self.run.argvs[-1], ["pmset", "displaysleepnow"])

    def test_a_command_runs_in_zsh_as_one_argument(self):
        with mock.patch("jcc.system.os.path.exists", lambda path: path == "/bin/zsh"):
            code, _ = voice_tools.run_shell("echo hi; ls", None, 10)
        self.assertEqual(code, 0)
        self.assertEqual(self.run.argvs[-1], ["/bin/zsh", "-lc", "echo hi; ls"])

    def test_a_hostile_app_name_stays_one_argument_of_open(self):
        box = self.toolbox(opened="")
        hostile = 'Safari -a Terminal --args do shell script'
        box.open_app(hostile)
        self.assertIn(["open", "-a", hostile], self.run.argvs)
        self.run.calls.clear()
        self.assertIn("No app called", box.open_app("-n Terminal"))
        self.assertEqual(self.run.argvs, [], "a name that looks like an option is never passed to open")
        with self.assertRaises(ValueError):
            mac.open_app("--args")

    def test_a_hostile_path_is_opened_as_a_full_path(self):
        box = self.toolbox()
        folder = Path(tempfile.mkdtemp(prefix="jcc-open-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, ignore_errors=True))
        target = folder / "-a Terminal.txt"
        target.write_text("x", "utf-8")
        self.assertTrue(box.open_file(str(target)).startswith("Opened"))
        argv = self.run.argvs[-1]
        self.assertEqual(argv[0], "open")
        self.assertEqual(len(argv), 2)
        self.assertTrue(Path(argv[1]).is_absolute() and not argv[1].startswith("-"))

    def test_files_are_found_with_spotlight_and_by_walking_when_it_finds_nothing(self):
        home = Path(tempfile.mkdtemp(prefix="jcc-home-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(home, ignore_errors=True))
        (home / "Documents" / "deep").mkdir(parents=True)
        (home / "Documents" / "deep" / "budget 2026.xlsx").write_text("x", "utf-8")
        (home / "Documents" / "notes.txt").write_text("x", "utf-8")
        spot = str(home / "Documents" / "deep" / "budget 2026.xlsx")
        self.run.answers["mdfind"] = spot + "\n" + str(home / "Library/Caches/budget.tmp") + "\n"
        self.assertEqual(mac.find_files("budget", home=home), [spot])
        self.assertEqual(self.run.argvs[-1], ["mdfind", "-onlyin", str(home), "-name", "budget"])
        self.run.answers["mdfind"] = ""
        self.assertEqual(mac.find_files("budget 2026", home=home), [spot], "found by walking the usual folders")
        with self.assertRaises(ValueError):
            mac.find_files("'")

    def test_installed_apps_are_read_from_the_app_folders(self):
        root = Path(tempfile.mkdtemp(prefix="jcc-apps-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        for name in ("Safari.app", "Visual Studio Code.app", "notes.txt"):
            (root / name).mkdir()
        self.assertEqual(mac.installed_apps([str(root)]), {"safari": str(root / "Safari.app"), "visual studio code": str(root / "Visual Studio Code.app")})

    def test_music_off_windows_plays_on_youtube(self):
        box = self.toolbox()
        with mock.patch("jcc.music.play_on_youtube", lambda query: f"Now playing on YouTube: {query}") as _:
            self.assertEqual(box.play_music("Clair de Lune Debussy"), "Now playing on YouTube: Clair de Lune Debussy")


class TestQuickOnAMac(OnAMac, EngineTestCase):
    def setUp(self):
        EngineTestCase.setUp(self)
        OnAMac.setUp(self)
        self.cfg = __import__("jcc.config", fromlist=["load"]).load()

    def tearDown(self):
        OnAMac.tearDown(self)
        EngineTestCase.tearDown(self)

    def test_the_app_list_comes_from_the_app_folders_and_opens_with_open(self):
        with mock.patch.object(mac, "installed_apps", lambda: {"safari": "/Applications/Safari.app"}):
            apps = quick.Apps(self.cfg)
            apps.refresh(force=True)
        self.assertEqual(apps.find("safari"), ("safari", "/Applications/Safari.app"))
        quick.launch("/Applications/Safari.app")
        self.assertEqual(self.run.argvs[-1], ["open", "-a", "/Applications/Safari.app"])

    def test_built_in_places_open_the_macs_own_way(self):
        q = quick.Quick(self.cfg, quick.Apps(self.cfg), reminders.Reminders(self.cfg))
        q.act("run", quick.BUILT_IN["task manager"])
        self.assertEqual(self.run.argvs[-1], ["open", "-a", "Activity Monitor"])
        q.act("run", quick.BUILT_IN["downloads"])
        self.assertEqual(self.run.argvs[-1][0], "open")
        self.assertTrue(self.run.argvs[-1][1].endswith("Downloads"))
        q.act("run", quick.BUILT_IN["bluetooth settings"])
        self.assertEqual(self.run.argvs[-1], ["open", "-b", "com.apple.systempreferences"])

    def test_spoken_volume_and_unavailable_things_answer_plainly(self):
        q = quick.Quick(self.cfg, quick.Apps(self.cfg), reminders.Reminders(self.cfg))
        self.assertEqual(q.handle("volume up").say, "Louder.")
        self.assertIn(["osascript", "-e", "set volume output volume 65"], self.run.argvs)      # 35 and five steps of 6, as five presses of the key
        self.assertIn("only available on Windows", q.handle("show the desktop").say)
        self.assertIn("only available on Windows", q.handle("brightness 50").say)
        self.assertEqual(q.handle("lock the pc").say, "Locked.")
        self.assertEqual(self.run.argvs[-1], ["pmset", "displaysleepnow"])


class TestTheWindowOnAMac(OnAMac, EngineTestCase):
    def setUp(self):
        EngineTestCase.setUp(self)
        OnAMac.setUp(self)

    def tearDown(self):
        OnAMac.tearDown(self)
        EngineTestCase.tearDown(self)

    def test_the_app_opens_in_a_chromium_window_of_its_own_with_no_tray(self):
        chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        with mock.patch.object(desktop, "ready", lambda: True), mock.patch.object(system, "browsers", lambda: [chrome]), \
                mock.patch("jcc.placement.screens", lambda: []):
            self.assertEqual(desktop.main(), 0)
        started = self.run.argvs
        self.assertFalse(any("jcc.tray" in argv for argv in started), "the tray is Windows-only")
        helpers = [argv for argv in started if argv[1:2] == ["-m"]]
        self.assertTrue(helpers and all(argv[0] == system.background_python() for argv in helpers))
        window = next(argv for argv in started if Path(argv[0]) == Path(chrome))
        self.assertEqual(window[1], "--app=" + desktop.URL)
        self.assertTrue(any(part.startswith("--user-data-dir=") and part.endswith("window-profile") for part in window))

    def test_without_a_chromium_browser_the_default_browser_opens_it(self):
        opened = []
        with mock.patch.object(desktop, "ready", lambda: True), mock.patch.object(system, "browsers", lambda: []), \
                mock.patch("webbrowser.open", opened.append):
            self.assertEqual(desktop.main(), 0)
        self.assertEqual(opened, [desktop.URL])

    def test_could_not_start_is_an_alert_whose_text_is_never_applescript(self):
        hostile = 'JARVIS" & (do shell script "say hi") & "'
        with mock.patch("builtins.print"):
            desktop.tell(hostile)
        argv = self.run.argvs[-1]
        self.assertEqual(argv[0], "osascript")
        self.assertEqual(argv[-1], hostile, "the text is the script's argument")
        source = " ".join(argv[1:-1])
        self.assertNotIn("shell script", source)


if __name__ == "__main__":
    unittest.main()
