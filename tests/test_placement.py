"""Where the app window opens: fitted to the screen the first time, where it was left after that."""
import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from jcc import config, desktop, placement
from tests.helpers import EngineTestCase
from tests.test_gui import GuiTestCase

BIG = (0, 0, 1920, 1040)            # a full-HD screen without its taskbar
LAPTOP = (0, 0, 1366, 728)
SECOND = (1920, -212, 3200, 588)    # a second screen to the right, 1280 by 800


class TestWhereTheWindowOpens(unittest.TestCase):
    def test_the_first_time_it_is_the_usual_size_in_the_middle_of_a_big_screen(self):
        self.assertEqual(placement.place({}, [BIG]), {"width": 1280, "height": 860, "x": 320, "y": 90, "max": False})

    def test_on_a_small_screen_it_fits_and_starts_maximized(self):
        spot = placement.place(None, [LAPTOP])
        self.assertTrue(spot["max"], "a small screen: use all of it")
        self.assertLessEqual(spot["height"], 728, "never taller than the screen: nothing may end up below the bottom edge")
        self.assertLessEqual(spot["width"], 1366)
        self.assertGreaterEqual(spot["x"], 0)
        self.assertLessEqual(spot["y"] + spot["height"], 728)
        tiny = placement.place({}, [(0, 0, 640, 440)])
        self.assertEqual((tiny["width"], tiny["height"], tiny["x"], tiny["y"]), (592, 400, 24, 20))

    def test_after_that_it_opens_where_it_was_left(self):
        left = {"x": 100, "y": 60, "width": 1100, "height": 700, "max": False}
        self.assertEqual(placement.place(left, [BIG, SECOND]), left)
        on_second = {"x": 2000, "y": -100, "width": 900, "height": 600, "max": False}
        self.assertEqual(placement.place(on_second, [BIG, SECOND]), on_second, "it stays on the second screen")

    def test_a_window_left_on_a_screen_that_is_gone_comes_back_onto_one_that_exists(self):
        spot = placement.place({"x": 2000, "y": -100, "width": 900, "height": 600, "max": False}, [BIG])
        self.assertEqual((spot["width"], spot["height"]), (900, 600))
        self.assertTrue(0 <= spot["x"] and spot["x"] + 900 <= 1920 and 0 <= spot["y"] and spot["y"] + 600 <= 1040, spot)

    def test_a_window_larger_than_the_screen_is_made_to_fit(self):
        # The old fixed size on the second screen: 860 tall on a screen 800 tall, so the message box was cut off.
        spot = placement.place({"x": 1920, "y": -212, "width": 1280, "height": 860, "max": False}, [BIG, SECOND])
        self.assertEqual(spot, {"width": 1280, "height": 800, "x": 1920, "y": -212, "max": False})
        self.assertEqual(placement.place({"x": 0, "y": 0, "width": 3000, "height": 2000, "max": False}, [LAPTOP]),
                         {"width": 1366, "height": 728, "x": 0, "y": 0, "max": False})

    def test_when_nothing_is_known_about_the_screen_the_usual_size_is_used(self):
        self.assertEqual(placement.place({}, []), {"width": 1280, "height": 860, "x": None, "y": None, "max": False})
        self.assertEqual(placement.place({"x": 5, "y": 6, "width": 900, "height": 600}, []), {"width": 900, "height": 600, "x": None, "y": None, "max": False})

    def test_odd_saved_values_are_not_trusted(self):
        for odd in ({"x": "left", "y": 0, "width": 900, "height": 600}, {"x": 0, "y": 0, "width": True, "height": 600},
                    {"x": 0, "y": 0, "width": 5, "height": 5}, {"x": float("nan"), "y": 0, "width": 900, "height": 600}, ["list"], "text"):
            spot = placement.place(odd, [BIG])
            self.assertEqual((spot["width"], spot["height"], spot["x"], spot["y"]), (1280, 860, 320, 90), odd)


class TestRememberingIt(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.load()
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)

    def saved(self):
        return json.loads((self.cfg.state_dir / "window.json").read_text("utf-8"))

    def test_the_window_says_where_it_is_and_opens_there_next_time(self):
        self.assertEqual(placement.arguments(self.cfg, [BIG], full=False), ["--window-size=1280,860", "--window-position=320,90"])
        self.assertEqual(placement.remember(self.cfg, {"x": 40.4, "y": 30, "width": 1000.6, "height": 720, "max": False}), {"ok": True})
        self.assertEqual(placement.arguments(self.cfg, [BIG], full=False), ["--window-size=1001,720", "--window-position=40,30"])

    def test_a_maximized_window_opens_maximized_and_goes_back_to_the_size_it_had(self):
        placement.remember(self.cfg, {"x": 40, "y": 30, "width": 1000, "height": 720, "max": False})
        placement.remember(self.cfg, {"x": -8, "y": -8, "width": 1936, "height": 1056, "max": True})
        self.assertEqual(placement.arguments(self.cfg, [BIG], full=False), ["--window-size=1000,720", "--window-position=40,30", "--start-maximized"])
        placement.remember(self.cfg, {"x": 300, "y": 200, "width": 800, "height": 600, "max": False})
        self.assertEqual(placement.arguments(self.cfg, [BIG], full=False), ["--window-size=800,600", "--window-position=300,200"])

    def test_maximized_from_the_start_stays_maximized_on_the_screen_it_was_on(self):
        placement.remember(self.cfg, {"x": 1912, "y": -220, "width": 1296, "height": 816, "max": True})
        args = placement.arguments(self.cfg, [BIG, SECOND], full=False)
        self.assertIn("--start-maximized", args)
        left, top = (int(n) for n in args[1].split("=")[1].split(","))
        self.assertTrue(1920 <= left < 3200 and -212 <= top < 588, "on the second screen: " + str(args))

    def test_nonsense_is_refused_and_a_damaged_file_is_ignored(self):
        for bad in (None, [], {"x": 0, "y": 0}, {"x": 0, "y": 0, "width": 10, "height": 600}, {"x": 0, "y": 0, "width": "wide", "height": 600},
                    {"x": 10 ** 7, "y": 0, "width": 900, "height": 600}, {"x": 0, "y": 0, "width": 900, "height": True}):
            with self.assertRaises(ValueError):
                placement.remember(self.cfg, bad)
        (self.cfg.state_dir / "window.json").write_text("{", "utf-8")
        self.assertEqual(placement.arguments(self.cfg, [BIG], full=False), ["--window-size=1280,860", "--window-position=320,90"])
        placement.remember(self.cfg, {"x": 1, "y": 2, "width": 900, "height": 600, "max": False})
        self.assertEqual((self.saved()["width"], self.saved()["max"]), (900, False))

    def test_it_opens_in_full_screen_and_after_that_the_way_it_was_left(self):
        self.assertEqual(placement.arguments(self.cfg, [BIG]), ["--window-size=1280,860", "--window-position=320,90", "--start-fullscreen"], "the first time: full screen")
        self.assertEqual(placement.arguments(self.cfg, [BIG], full=False)[-1], "--window-position=320,90",
                         "a window that opens by itself while the owner is doing something else never takes the whole screen")
        placement.set_pref(self.cfg, "nv-open", "remember")                 # the owner left full screen
        self.assertNotIn("--start-fullscreen", placement.arguments(self.cfg, [BIG]))
        placement.set_pref(self.cfg, "nv-open", "fullscreen")
        self.assertIn("--start-fullscreen", placement.arguments(self.cfg, [BIG]))

    def test_full_screen_is_only_ever_pressed_in_jarviss_own_window(self):
        class Desk:
            def __init__(self, title):
                self.title = title

            def foreground(self):
                return 7

            def title_of(self, handle):
                return self.title
        pressed = []
        self.assertTrue(placement.press_full_screen(Desk("JARVIS · Workspace"), pressed.append))
        self.assertEqual(pressed, [{"action": "key", "keys": "f11"}])
        self.assertFalse(placement.press_full_screen(Desk("Untitled - Notepad"), pressed.append), "another program is in front: nothing is pressed there")
        self.assertEqual(len(pressed), 1)

    def test_this_computers_screens_can_be_read(self):
        areas = placement.screens()
        self.assertIsInstance(areas, list)
        for left, top, right, bottom in areas:
            self.assertTrue(right - left >= 200 and bottom - top >= 200)

    def test_the_launcher_opens_the_window_there(self):
        placement.remember(self.cfg, {"x": 70, "y": 50, "width": 1100, "height": 700, "max": False})
        started = []

        class Process:
            def __init__(self, command, **_):
                started.append([str(part) for part in command])
        with mock.patch.object(desktop, "ready", lambda: True), mock.patch.object(subprocess, "Popen", Process), \
                mock.patch.object(placement, "screens", lambda: [BIG]), mock.patch.object(desktop, "window_browser", lambda: Path("C:/Edge/msedge.exe")):
            self.assertEqual(desktop.main(listen=True), 0)
        window = next(command for command in started if any(part.startswith("--app=") for part in command))
        self.assertEqual(window[1], "--app=http://127.0.0.1:8765/?listen")
        self.assertEqual(window[-2:], ["--window-size=1100,700", "--window-position=70,50"])
        self.assertIn("--user-data-dir=" + str(self.cfg.state_dir / "window-profile"), window, "in JARVIS's own browser profile")
        self.assertIn("--autoplay-policy=no-user-gesture-required", window, "so it can speak the moment it opens, without a click")

    def test_opened_again_the_open_window_comes_to_the_front_and_no_second_one_opens(self):
        started, forward, told = [], [], []

        class Process:
            def __init__(self, command, **_):
                started.append([str(part) for part in command])
        with mock.patch.object(desktop, "ready", lambda: True), mock.patch.object(subprocess, "Popen", Process), \
                mock.patch.object(desktop, "open_window", lambda: 4242), mock.patch.object(desktop, "bring_forward", forward.append), \
                mock.patch("jcc.tray.ask_service", lambda cfg, action, text="": told.append(action)):
            self.assertEqual(desktop.main(), 0)
            self.assertEqual(desktop.main(listen=True), 0)
        self.assertEqual(forward, [4242, 4242])
        self.assertFalse([c for c in started if any(part.startswith("--app=") for part in c)], "no second window")
        self.assertEqual(told, ["listen"], "asked to listen: the open window does")

    def test_the_tests_never_look_at_this_pcs_own_windows(self):
        self.assertIsNone(desktop.open_window())
        self.assertTrue(desktop.MAIN_TITLE.match("JARVIS \u00b7 Workspace"))
        self.assertFalse(desktop.MAIN_TITLE.match("JARVIS \u00b7 Listening"))
        self.assertFalse(desktop.MAIN_TITLE.match("JARVIS \u00b7 Workspace and 2 more pages - Microsoft Edge"))

    def test_its_own_profile_lets_it_speak_and_listen_without_a_click(self):
        args = placement.profile(self.cfg, "http://127.0.0.1:8765/")
        folder = self.cfg.state_dir / "window-profile"
        self.assertEqual(args[0], "--user-data-dir=" + str(folder))
        self.assertIn("--autoplay-policy=no-user-gesture-required", args)
        made = json.loads((folder / "Default" / "Preferences").read_text("utf-8"))
        allowed = made["profile"]["content_settings"]["exceptions"]["media_stream_mic"]
        self.assertEqual(allowed, {"http://127.0.0.1:8765,*": {"setting": 1}}, "the microphone is allowed for JARVIS's own address and nothing else")
        quiet = {"net": {"network_prediction_options": 2}, "webrtc": {"ip_handling_policy": "disable_non_proxied_udp"}}
        self.assertEqual({area: made[area] for area in quiet}, quiet, "it does not connect ahead to addresses a page mentions, and WebRTC sends no packets of its own")
        # A profile made before those two settings were: they are added, and everything the browser keeps there stays.
        (folder / "Default" / "Preferences").write_text('{"changed": "by the browser", "net": {"kept": 1}}', "utf-8")
        placement.profile(self.cfg)
        self.assertEqual(json.loads((folder / "Default" / "Preferences").read_text("utf-8")),
                         {"changed": "by the browser", "net": {"kept": 1, "network_prediction_options": 2}, "webrtc": {"ip_handling_policy": "disable_non_proxied_udp"}})
        before = (folder / "Default" / "Preferences").stat().st_mtime_ns
        placement.profile(self.cfg)
        self.assertEqual((folder / "Default" / "Preferences").stat().st_mtime_ns, before, "once they are there the file is left alone")
        (folder / "Default" / "Preferences").write_text('not what was expected', "utf-8")
        self.assertEqual(placement.profile(self.cfg)[0], "--user-data-dir=" + str(folder), "a file that cannot be read stops nothing")
        from jcc import policy
        self.assertEqual(policy.decide("read_file", {"path": str(folder / "Default" / "Cookies")}, policy.Context(state_dir=str(self.cfg.state_dir))).verdict, policy.DENY,
                         "the assistant itself can never read that profile")
        self.assertEqual(policy.command_kind("Get-Content $env:LOCALAPPDATA\\JarvisCommand\\window-profile\\Default\\Preferences"), "blocked")

    def test_what_the_window_remembers_is_kept_by_the_app(self):
        self.assertEqual(placement.prefs(self.cfg), {})
        placement.set_pref(self.cfg, "nv-theme", "light")
        placement.set_pref(self.cfg, "nv-panel-w", "640")
        self.assertEqual(placement.prefs(self.cfg), {"nv-theme": "light", "nv-panel-w": "640"})
        for key, value in (("theme", "light"), ("nv-THEME", "x"), ("nv-theme", 5), ("nv-theme", "x" * 400), ("../../x", "y"), (None, "y")):
            with self.assertRaises(ValueError):
                placement.set_pref(self.cfg, key, value)
        (self.cfg.state_dir / "window-prefs.json").write_text('{"nv-theme": "dark", "odd key": "x", "nv-n": 5}', "utf-8")
        self.assertEqual(placement.prefs(self.cfg), {"nv-theme": "dark"}, "only what looks like a preference is passed to the page")


class TestTheWindowReportsOverTheWire(GuiTestCase):
    def test_only_the_app_window_can_say_where_it_is(self):
        self.assertEqual(self.req("POST", "/api/window", {"x": 10, "y": 20, "width": 900, "height": 640, "max": False}), (200, {"ok": True}))
        saved = json.loads((self.state.cfg.state_dir / "window.json").read_text("utf-8"))
        self.assertEqual((saved["x"], saved["y"], saved["width"], saved["height"], saved["max"]), (10, 20, 900, 640, False))
        self.assertEqual(self.req("POST", "/api/window", {"x": 10, "y": 20, "width": 900, "height": 640}, token=False)[0], 401)
        self.assertEqual(self.req("POST", "/api/window", {"x": 10, "y": 20, "width": "900", "height": 640})[0], 400)
        self.assertEqual(self.req("POST", "/api/window", {})[0], 400)

    def test_the_page_is_given_what_was_remembered(self):
        self.assertEqual(self.req("POST", "/api/window", {"pref": "nv-theme", "value": "light"}), (200, {"ok": True}))
        self.assertEqual(self.req("POST", "/api/window", {"pref": "nv-theme", "value": "</script><script>alert(1)"})[0], 200)
        self.assertEqual(self.req("POST", "/api/window", {"pref": "bad key", "value": "x"})[0], 400)
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", "/", headers={"Host": f"127.0.0.1:{self.port}"})
        page = c.getresponse().read().decode("utf-8")
        c.close()
        line = next(row for row in page.splitlines() if row.startswith("const PREFS="))
        self.assertIn(r'"nv-theme": "\u003c/script\u003e\u003cscript\u003ealert(1)"', line, "kept safely: it cannot end the script it sits in")
        self.assertNotIn("<", line)
        self.assertEqual(json.loads(line[len("const PREFS="):-1])["nv-theme"], "</script><script>alert(1)", "and the page reads back exactly what was kept")
        self.assertNotIn("__JCC_PREFS__", page)

    def test_going_into_or_out_of_full_screen_is_remembered(self):
        original = placement.press_full_screen
        placement.press_full_screen = lambda *a, **k: True
        try:
            self.assertEqual(self.req("POST", "/api/window", {"fullscreen": False}), (200, {"ok": True, "done": True}))
            self.assertFalse(placement.opens_full(self.state.cfg))
            self.req("POST", "/api/window", {"fullscreen": True})
            self.assertTrue(placement.opens_full(self.state.cfg))
        finally:
            placement.press_full_screen = original

    def test_a_window_that_hits_a_script_error_says_so(self):
        self.assertEqual(self.req("POST", "/api/window", {"problem": "TypeError: x is not a function @ nova-voice.js:12:5 gsk_FAKEgroqKEY1234567890abcdefGHIJ"}), (200, {"ok": True}))
        log = (self.state.cfg.state_dir / "window-problems.log").read_text("utf-8")
        self.assertIn("TypeError: x is not a function @ nova-voice.js:12:5", log)
        self.assertNotIn("gsk_FAKE", log, "a key that happened to be in the message is not kept")
        self.assertEqual(self.req("POST", "/api/window", {"problem": "x"}, token=False)[0], 401)
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", "/", headers={"Host": f"127.0.0.1:{self.port}"})
        page = c.getresponse().read().decode("utf-8")
        c.close()
        self.assertIn('addEventListener("error"', page)

    def test_a_link_in_a_reply_opens_in_the_owners_own_browser(self):
        import webbrowser
        opened, original = [], webbrowser.open
        webbrowser.open = lambda link: opened.append(link) or True
        try:
            self.assertEqual(self.req("POST", "/api/window", {"open": "https://example.com/page?x=1"}), (200, {"ok": True}))
            for bad in ("file:///C:/Windows/system32/calc.exe", "javascript:alert(1)", "https://exa mple.com", "", "mailto:a@b.co"):
                self.assertEqual(self.req("POST", "/api/window", {"open": bad})[0], 400, bad)
            self.assertEqual(self.req("POST", "/api/window", {"open": "https://example.com"}, token=False)[0], 401)
        finally:
            webbrowser.open = original
        self.assertEqual(opened, ["https://example.com/page?x=1"])


if __name__ == "__main__":
    unittest.main()
