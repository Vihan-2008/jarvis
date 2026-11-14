"""The small "listening" window: a panel with the orb in a corner while another program is in front."""
import contextlib
import json
import time
import unittest

from jcc import assistant, config, mini, placement, policy
from tests.helpers import EngineTestCase
from tests.test_gui import GuiTestCase

FAR = mini.FAR
MAIN, SECOND = (0, 0, 1920, 1080, 1.0), (1920, 0, 4480, 1600, 2.0)
OTHER = 500                                 # the program the owner is working in


class FakeWindows:
    """Windows and Edge, played by hand. An Edge window keeps a title bar above the page and, on a screen, a border
    around it; it lays itself out a moment after it is resized or shown, not at once; it does not lay itself out again when
    it is only moved; and while it is hidden the page's own inner window is gone altogether."""

    def __init__(self, screens=(MAIN,), pageless=False):
        self.screens, self.pageless = list(screens), pageless
        self.wins = {OTHER: {"title": "Report.docx - Word", "rect": [100, 100, 900, 700], "visible": True}}
        self.front, self.next, self.now = OTHER, 1000, 5000.0
        self.pointer, self.held = (0, 0), []          # where the mouse is; where it goes next while its button is held down
        self.calls, self.caption = [], 30

    @contextlib.contextmanager
    def real(self):
        yield

    # -- what Edge does
    def open(self, title: str) -> int:
        handle, self.next = self.next, self.next + 1
        self.wins[handle] = {"title": title, "rect": [FAR, FAR, FAR + mini.WIDE, FAR + mini.HIGH], "visible": True, "bare": False, "tool": False,
                             "region": None, "page": None, "stale": True}
        self.front = handle                             # a window that opens takes the keyboard
        self._lay_out(handle)
        return handle

    def _screen(self, rect):
        middle = ((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)
        return next((s for s in self.screens if s[0] <= middle[0] < s[2] and s[1] <= middle[1] < s[3]), None)

    def _lay_out(self, handle: int) -> None:
        win = self.wins[handle]
        win["stale"] = False
        if not win["visible"] or self.pageless:
            win["page"] = None
            return
        left, top, right, bottom = win["rect"]
        screen = self._screen(win["rect"])
        scale = screen[4] if screen else 1.0
        border = round(7 * scale) if screen else 0     # no border when it is on no screen at all
        caption = round((self.caption if win["bare"] else self.caption + 1) * scale)
        win["page"] = [left + border, top + caption, right - border, bottom - border]

    def pause(self, seconds: float) -> None:
        """Time passes: Edge lays out what it had not laid out yet, and a held mouse moves on."""
        self.now += seconds
        for handle, win in self.wins.items():
            if win.get("stale"):
                self._lay_out(handle)
        if self.held:
            self.pointer = self.held.pop(0)

    # -- what jcc.mini asks of Windows
    def find(self, title):
        return next((handle for handle, win in self.wins.items() if win["title"] == title), 0)

    def exists(self, handle):
        return handle in self.wins

    def foreground(self):
        return self.front

    def visible(self, handle):
        return self.wins[handle]["visible"]

    def rect(self, handle):
        return tuple(self.wins[handle]["rect"])

    def page(self, handle):
        page = self.wins[handle].get("page")
        return tuple(page) if page else None

    def dress(self, handle, bare):
        self.wins[handle].update(tool=True, bare=bare, stale=True)
        self.calls.append(("dress", handle, bare))

    def area(self, handle):
        screen = self._screen(self.wins[handle]["rect"]) if handle in self.wins else None
        if handle in self.wins and not screen:          # the nearest screen
            x = self.wins[handle]["rect"][0]
            screen = min(self.screens, key=lambda s: abs((s[0] + s[2]) // 2 - x))
        return screen or self.screens[0]

    def place(self, handle, x, y, wide, high, show=None):
        win = self.wins[handle]
        resized = (win["rect"][2] - win["rect"][0], win["rect"][3] - win["rect"][1]) != (wide, high)
        shown = show is not None and bool(show) != win["visible"]
        self.calls.append(("place", handle, x, y, wide, high, show))
        if resized or shown:
            win["rect"], win["stale"] = [x, y, x + wide, y + high], True
            if show is not None:
                win["visible"] = bool(show)
            if not win["visible"]:
                win["page"] = None
        else:
            self.move(handle, x, y)

    def move(self, handle, x, y):
        win = self.wins[handle]
        dx, dy = x - win["rect"][0], y - win["rect"][1]
        win["rect"] = [x, y, win["rect"][2] + dx, win["rect"][3] + dy]
        if win.get("page"):
            win["page"] = [win["page"][0] + dx, win["page"][1] + dy, win["page"][2] + dx, win["page"][3] + dy]

    def cut(self, handle, left, top, right, bottom):
        self.wins[handle]["region"] = (left, top, right, bottom)
        return True

    def uncut(self, handle):
        self.wins[handle]["region"] = None

    def cursor(self):
        return self.pointer

    def pressed(self):
        return bool(self.held)

    def show(self, handle, on):
        win = self.wins[handle]
        if win["visible"] != bool(on):
            win["visible"], win["stale"] = bool(on), True
            if not on:
                win["page"] = None

    def focus(self, handle):
        self.front = handle
        self.calls.append(("focus", handle))

    def close(self, handle):
        self.wins.pop(handle, None)
        if self.front == handle:
            self.front = OTHER

    # -- what a person would see of the panel: the part of the window that is not cut away, on the screen
    def seen(self, handle):
        win = self.wins[handle]
        if not win["visible"]:
            return None
        if win["region"] is None:
            return tuple(win["rect"])
        left, top, right, bottom = win["region"]
        if right <= left or bottom <= top:
            return None
        return win["rect"][0] + left, win["rect"][1] + top, win["rect"][0] + right, win["rect"][1] + bottom


class MiniCase(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.load()
        self.fake = FakeWindows()

    def make(self, address="http://127.0.0.1:8765", opens=True):
        popup = mini.Mini(self.cfg, address, launch=lambda: bool(opens and self.fake.open(mini.title_for(address))), windows=lambda: self.fake,
                          clock=lambda: self.fake.now, pause=self.fake.pause)
        return popup

    def settle(self, popup, moving=False):
        deadline = time.time() + 5
        while time.time() < deadline:
            if not popup.starting and not popup.dragging:
                return
            time.sleep(0.005)
        self.fail("it did not settle")

    def ready(self, **kw):
        popup = self.make(**kw)
        self.assertTrue(popup.ensure())
        self.settle(popup)
        return popup


class TestTheSmallWindow(MiniCase):
    def test_it_is_made_ready_out_of_sight_and_the_keyboard_stays_where_it_was(self):
        popup = self.ready()
        fake, handle = self.fake, popup.handle
        self.assertTrue(popup.alive())
        self.assertFalse(popup.shown())
        self.assertIsNone(fake.seen(handle), "nothing of it can be seen")
        self.assertEqual(fake.wins[handle]["rect"][0], FAR, "it never came onto a screen")
        self.assertTrue(fake.wins[handle]["tool"] and fake.wins[handle]["bare"], "no taskbar button, no title bar, no border")
        self.assertEqual(fake.front, OTHER, "Edge took the keyboard as it opened; it went straight back")
        self.assertTrue(popup.ensure(), "asked again, nothing more is opened")
        self.assertEqual(len([w for w in fake.wins.values() if w["title"] == mini.TITLE]), 1)

    def test_shown_it_is_exactly_the_panel_in_the_corner_of_the_screen(self):
        popup = self.ready()
        fake = self.fake
        popup.show()
        corner = (1920 - 18 - 372, 1080 - 18 - 150, 1920 - 18, 1080 - 18)
        self.assertTrue(popup.shown())
        self.assertEqual(fake.page(popup.handle), corner, "the page itself is the size of the panel, in the corner")
        self.assertEqual(fake.seen(popup.handle), corner, "and only the page is seen: Edge's title bar and border are cut away")
        self.assertEqual(fake.front, OTHER, "the program in front keeps the keyboard")
        self.assertNotIn(("focus", popup.handle), fake.calls)

    def test_nothing_of_it_is_seen_until_it_fits(self):
        """Edge lays the window out a moment after it is shown. Until the page is where it belongs, the window is cut down
        to nothing, so no title bar and no half-sized panel ever flash on the screen."""
        popup = self.ready()
        fake, glimpses = self.fake, []
        pause = fake.pause

        def watch(seconds):
            glimpses.append(fake.seen(popup.handle))
            pause(seconds)
        popup.pause = watch
        popup.show()
        self.assertTrue(glimpses, "it had to wait for Edge at least once")
        self.assertEqual(set(glimpses), {None}, "all the while, nothing of it was to be seen")
        self.assertEqual(fake.seen(popup.handle), (1530, 912, 1902, 1062))

    def test_hidden_and_shown_again_it_is_back_at_once(self):
        popup = self.ready()
        fake = self.fake
        popup.show()
        popup.hide()
        self.assertFalse(popup.shown())
        self.assertTrue(popup.alive(), "it is kept, for the next time")
        before = len([call for call in fake.calls if call[0] == "place"])
        popup.show()
        self.assertEqual(fake.seen(popup.handle), (1530, 912, 1902, 1062))
        self.assertEqual(len([call for call in fake.calls if call[0] == "place"]) - before, 1, "one step: it is shown where it was, already cut to size")

    def test_on_a_screen_with_larger_scaling_it_is_as_large_as_everything_else_there(self):
        self.fake = FakeWindows(screens=(MAIN, SECOND))
        self.fake.wins[OTHER]["rect"] = [2200, 200, 3600, 1200]         # the owner is working on the second screen
        popup = self.ready()
        fake = self.fake
        popup.show()
        there = (4480 - 36 - 744, 1600 - 36 - 300, 4480 - 36, 1600 - 36)
        self.assertEqual(fake.seen(popup.handle), there, "twice the points, in that screen's corner")
        self.assertEqual(fake.page(popup.handle), there)
        popup.hide()
        fake.wins[OTHER]["rect"] = [100, 100, 900, 700]                 # ... and then on the main screen again
        popup.show()
        self.assertEqual(fake.seen(popup.handle), (1530, 912, 1902, 1062))
        self.assertEqual(fake.page(popup.handle), (1530, 912, 1902, 1062))

    def test_a_click_in_it_does_not_keep_the_keyboard(self):
        """Edge activates a window that is clicked, whatever the window says. The keyboard goes back to the program in use."""
        popup = self.ready()
        fake = self.fake
        popup.show()
        fake.front = popup.handle                                       # a click on one of its buttons
        popup.show()                                                    # (the app looks at it every moment while it is shown)
        self.assertEqual(fake.front, OTHER)
        fake.wins[700] = {"title": "Netflix - Edge", "rect": [0, 0, 1920, 1080], "visible": True}
        fake.front = 700                                                # the owner moves on to another program
        popup.show()
        fake.front = popup.handle
        popup.hide()                                                    # the conversation ends while the panel has the keyboard
        self.assertEqual(fake.front, 700, "back to the program that had it last")

    def test_it_can_be_put_anywhere_and_comes_back_there(self):
        popup = self.ready()
        fake = self.fake
        popup.show()
        fake.pointer, fake.held = (1600, 980), [(1590, 970), (1500, 900), (1400, 800)]
        self.assertTrue(popup.drag())
        self.assertFalse(popup.drag(), "it is already in hand")
        self.settle(popup)
        self.assertEqual(fake.seen(popup.handle), (1430, 832, 1802, 982), "it followed the pointer, and stays where it was let go")
        self.assertEqual(json.loads((self.cfg.state_dir / "listening-window.json").read_text("utf-8")), {"right": 118, "bottom": 98})
        popup.hide()
        popup.show()
        self.assertEqual(fake.seen(popup.handle), (1430, 832, 1802, 982), "shown again, it is where its owner put it")
        again = self.make()
        self.assertEqual(again.gap, (118, 98), "and after JARVIS has been restarted too")

    def test_let_go_half_off_the_screen_it_is_brought_back_onto_it(self):
        popup = self.ready()
        fake = self.fake
        popup.show()
        fake.pointer, fake.held = (1600, 980), [(1800, 1050), (1900, 1079)]
        popup.drag()
        self.settle(popup)
        self.assertEqual(fake.seen(popup.handle), (1920 - 372, 1080 - 150, 1920, 1080), "wholly on the screen, in its corner")
        self.assertEqual(popup.gap, (0, 0))

    def test_it_does_not_vanish_from_under_the_hand(self):
        popup = self.ready()
        fake = self.fake
        popup.show()
        fake.pointer, fake.held = (1600, 980), [(1590, 970)] * 400
        popup.drag()
        popup.hide()                                                    # the conversation ended while it was being moved
        self.assertTrue(fake.wins[popup.handle]["visible"], "not hidden while it is held")
        fake.held = []
        self.settle(popup)
        self.assertFalse(popup.shown(), "let go, it goes away")

    def test_laid_out_afresh_by_edge_it_is_fitted_again(self):
        popup = self.ready()
        fake = self.fake
        popup.show()
        fake.caption = 40                                               # Edge decides its title bar is taller (the screens changed, say)
        fake._lay_out(popup.handle)
        self.assertNotEqual(fake.page(popup.handle), (1530, 912, 1902, 1062))
        popup.show()
        self.assertEqual(fake.page(popup.handle), (1530, 912, 1902, 1062))
        self.assertEqual(fake.seen(popup.handle), (1530, 912, 1902, 1062))

    def test_an_edge_built_differently_still_gives_a_small_window(self):
        self.fake = FakeWindows(pageless=True)                          # the page inside the window cannot be found
        popup = self.ready()
        fake = self.fake
        self.assertFalse(fake.wins[popup.handle]["bare"], "its title bar is left alone")
        popup.show()
        self.assertTrue(popup.shown())
        self.assertEqual(fake.seen(popup.handle), (1530, 912, 1902, 1062), "an ordinary small window in the corner")
        self.assertEqual(fake.front, OTHER)

    def test_a_window_left_by_an_earlier_run_is_replaced(self):
        old = self.fake.open(mini.TITLE)
        self.fake.front = OTHER
        popup = self.ready()
        self.assertNotIn(old, self.fake.wins, "it showed the page as it was before the restart")
        self.assertNotEqual(popup.handle, old)
        self.assertEqual(len([w for w in self.fake.wins.values() if w["title"] == mini.TITLE]), 1)

    def test_wanted_before_it_exists_it_appears_as_soon_as_it_does(self):
        popup = self.make()
        popup.show()
        self.settle(popup)
        self.assertEqual(self.fake.seen(popup.handle), (1530, 912, 1902, 1062))
        self.assertEqual(self.fake.front, OTHER)

    def test_when_edge_cannot_be_started_it_is_not_tried_over_and_over(self):
        popup = self.make(opens=False)
        self.assertTrue(popup.ensure())
        self.settle(popup)
        self.assertFalse(popup.alive())
        self.assertFalse(popup.ensure(), "not again at once")
        self.fake.now += 121
        self.assertTrue(popup.ensure(), "two minutes later it is tried again")
        self.settle(popup)

    def test_closing_it(self):
        popup = self.ready()
        handle = popup.handle
        popup.show()
        popup.close()
        self.assertNotIn(handle, self.fake.wins)
        self.assertFalse(popup.alive() or popup.shown())

    def test_a_second_jarvis_on_this_pc_has_a_window_of_its_own(self):
        self.assertEqual(mini.title_for("http://127.0.0.1:8765"), "JARVIS · Listening")
        self.assertEqual(mini.title_for("http://127.0.0.1:8799/"), "JARVIS · Listening · 8799")
        mine = self.ready()
        other = self.ready(address="http://127.0.0.1:8799")
        self.assertNotEqual(mine.handle, other.handle)
        self.assertEqual(len(self.fake.wins), 3, "neither replaced the other's window")
        for title in ("JARVIS · Listening", "JARVIS · Listening · 8799"):
            self.assertTrue(policy.OWN_WINDOW.search(title), "the assistant never sees, clicks or types into it")
            self.assertFalse(policy.MAIN_WINDOW.search(title), "and it is not taken for the app window")
        self.assertTrue(policy.MAIN_WINDOW.search("JARVIS — Workspace"))

    def test_a_bad_file_about_its_place_is_ignored(self):
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        for text in ("not json", '{"right": -5, "bottom": 3}', '{"right": true, "bottom": 3}', '{"right": 99999, "bottom": 3}', '{"right": "1"}'):
            (self.cfg.state_dir / "listening-window.json").write_text(text, "utf-8")
            self.assertEqual(self.make().gap, (18, 18), text)


class TestItNeverOpensOverTheWholeScreen(EngineTestCase):
    """Found on the owner's PC: the small window opened over the whole screen. It shared the app window's browser, which
    opens every window the way the app window was opened (full screen, or maximised as it was last left)."""

    def test_it_runs_in_a_browser_of_its_own_at_its_own_size(self):
        cfg = config.load()
        argv = mini.launch_argv(cfg, "edge.exe", "http://127.0.0.1:8765/?mini")
        self.assertIn("--user-data-dir=" + str(cfg.state_dir / mini.PROFILE), argv, "not the app window's profile, so not its browser")
        self.assertNotIn("--user-data-dir=" + str(cfg.state_dir / "window-profile"), argv)
        for never in ("--start-fullscreen", "--start-maximized", "--kiosk"):
            self.assertNotIn(never, argv)
        self.assertIn(f"--window-size={mini.WIDE},{mini.HIGH}", argv)
        app = placement.arguments(cfg, [(0, 0, 1920, 1080)])
        self.assertIn("--start-fullscreen", app, "(the app window itself still opens full screen the first time)")
        prefs = json.loads((cfg.state_dir / mini.PROFILE / "Default" / "Preferences").read_text("utf-8"))
        self.assertIn("http://127.0.0.1:8765,*", prefs["profile"]["content_settings"]["exceptions"]["media_stream_mic"], "its own profile may use the microphone at once too")

    def test_a_window_that_comes_up_maximised_is_given_its_own_size_before_it_is_used(self):
        address = "http://127.0.0.1:8765"
        fake = FakeWindows()
        undone = []
        fake.unmaximise = lambda handle: undone.append(handle) or True
        popup = mini.Mini(config.load(), address, launch=lambda: bool(fake.open(mini.title_for(address))), windows=lambda: fake, pause=lambda s: None)
        popup._start()
        self.assertTrue(popup.handle)
        self.assertEqual(undone, [popup.handle])


class TestJarvisWindowsAreAlwaysDrawn(EngineTestCase):
    def test_how_edge_is_started_for_them(self):
        """Found on the real thing: without these two, a new profile opens with Edge's sign-in notice over the whole small
        window, and the small window stays blank (Edge thinks it is covered) until another program is clicked."""
        args = placement.profile(config.load(), "http://127.0.0.1:8765/")
        self.assertIn("--disable-sync", args)
        features = next(arg for arg in args if arg.startswith("--disable-features="))
        self.assertIn("CalculateNativeWinOcclusion", features.split("=", 1)[1].split(","))


class Popup:
    """The small window, as the assistant sees it."""

    def __init__(self):
        self.did, self.starting, self.moved = [], False, 0

    def show(self):
        self.did.append("show")

    def hide(self):
        self.did.append("hide")

    def alive(self):
        return True

    def ensure(self):
        self.did.append("ensure")
        return True

    def close(self):
        self.did.append("close")

    def drag(self):
        self.moved += 1
        return True


class TestWhoAnswers(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.agent = assistant.Assistant(config.load(), 1234, lambda *a, **k: None, exe="claude")
        self.agent.hand_wait, self.agent.popup, self.front = 0.2, Popup(), False
        self.agent.main_in_front = lambda: self.front
        self.agent._popup_kick = lambda: None           # (the thread that keeps it on the screen has tests of its own)

    def tearDown(self):
        self.agent.close()
        super().tearDown()

    def test_another_program_in_front_the_small_window_takes_it(self):
        agent = self.agent
        agent.poll(0, 0, "app", "main")
        self.assertTrue(agent.hand(""), "the small window is on its way")
        self.assertIn("show", agent.popup.did)
        events = agent.poll(0, 0, "app", "main")["events"]
        self.assertEqual([e.get("to") for e in events if e["k"] == "wake"][0], "mini")
        nothing = {"text": "", "listen": False, "attend": False, "nudge": False}
        agent.hand_wait = 30                                            # (as if its name had been said this very moment)
        with agent.lock:
            agent.pending_voice = ("", time.time(), agent.pending_voice[2], False, False, "mini")
        self.assertEqual(agent.take_pending("main"), nothing, "kept for the window it is meant for")
        self.assertEqual(agent.take_pending("mini"), {"text": "", "listen": True, "attend": False, "nudge": False})

    def test_jarvis_itself_in_front_the_app_window_takes_it(self):
        agent, self.front = self.agent, True
        agent.poll(0, 0, "app", "main")
        agent.hand("what time is it")
        self.assertNotIn("show", agent.popup.did, "no small window over the app itself")
        events = agent.poll(0, 0, "app", "main")["events"]
        self.assertEqual([e.get("to") for e in events if e["k"] == "wake"][0], "main")
        agent.hand_wait = 30
        with agent.lock:
            agent.pending_voice = ("what time is it", time.time(), agent.pending_voice[2], False, False, "main")
        self.assertEqual(agent.take_pending("mini")["text"], "", "not for the small window")
        self.assertEqual(agent.take_pending("main")["text"], "what time is it")

    def test_if_the_window_it_was_meant_for_does_not_come_another_may_take_it(self):
        agent = self.agent
        agent.poll(0, 0, "app", "main")
        agent.hand("open the calculator")                               # nobody takes it within the time allowed
        self.assertEqual(agent.take_pending("main")["text"], "open the calculator", "after that the app window may")

    def test_a_window_that_does_not_say_what_it_is_may_always_take_it(self):
        agent = self.agent
        agent.hand_wait = 30
        with agent.lock:
            agent.pending_voice = ("hello", time.time(), __import__("threading").Event(), False, False, "mini")
        self.assertEqual(agent.take_pending()["text"], "hello", "(an older page, or the tray helper's own window)")

    def test_when_the_small_window_is_on_the_screen(self):
        agent = self.agent
        self.assertFalse(agent._popup_wanted(), "nobody is talking")
        agent.poll(0, 0, "app", "main")
        agent.presence("listening", "app", kind="main")
        self.assertTrue(agent._popup_wanted(), "a conversation in the app window, which is behind another program: shown beside it")
        self.front = True
        self.assertFalse(agent._popup_wanted(), "the app window is the one in use: no need")
        agent.presence("idle", "app", kind="main")
        self.front = False
        self.assertFalse(agent._popup_wanted(), "the conversation is over")
        agent.poll(0, 0, "small", "mini")
        agent.presence("speaking", "small", kind="mini")
        self.front = True
        self.assertTrue(agent._popup_wanted(), "its own conversation: it stays until that is over")
        agent.presence("idle", "small", gone=True, kind="mini")
        self.assertFalse(agent._popup_wanted())

    def test_each_window_hears_what_the_others_are_doing(self):
        agent = self.agent
        agent.poll(0, 0, "app", "main")
        start = agent.poll(0, 0, "small", "mini")["next"]
        agent.presence("listening", "app", kind="main")
        agent.presence("listening", "app", kind="main")                 # said again every few seconds: no news
        agent.presence("thinking", "app", kind="main")
        agent.presence("idle", "app", gone=True, kind="main")
        phases = [(e["w"], e["kind"], e["phase"]) for e in agent.poll(start, 0, "small", "mini")["events"] if e["k"] == "phase"]
        self.assertEqual(phases, [("app", "main", "listening"), ("app", "main", "thinking"), ("app", "main", "idle")])

    def test_it_is_kept_on_the_screen_while_wanted_and_taken_off_after(self):
        agent = self.agent
        del agent._popup_kick                                           # the real one
        agent.started, agent.warming = True, True                       # (running, and no session is made ready here)
        agent.poll(0, 0, "small", "mini")
        agent.presence("listening", "small", kind="mini")
        deadline = time.time() + 3
        while "show" not in agent.popup.did and time.time() < deadline:
            time.sleep(0.02)
        self.assertIn("show", agent.popup.did)
        agent.presence("idle", "small", kind="mini")
        deadline = time.time() + 5
        while "hide" not in agent.popup.did and time.time() < deadline:
            time.sleep(0.05)
        self.assertIn("hide", agent.popup.did, "a moment after the conversation is over")
        deadline = time.time() + 20
        while agent.popup.did[-1] != "ensure" and time.time() < deadline:
            time.sleep(0.1)
        self.assertEqual(agent.popup.did[-2:], ["hide", "ensure"], "and if it was closed meanwhile, a new one is made ready for the next time")

    def test_closing_jarvis_closes_it(self):
        popup = self.agent.popup
        self.agent.close()
        self.assertIn("close", popup.did)


class TestOverTheWire(GuiTestCase):
    def test_the_small_window_asks_to_be_moved(self):
        self.assertEqual(self.req("POST", "/api/window", {"mini": "drag"}), (200, {"ok": True, "moving": False}), "there is no small window here")
        self.state.assistant.popup = Popup()
        self.assertEqual(self.req("POST", "/api/window", {"mini": "drag"}), (200, {"ok": True, "moving": True}))
        self.assertEqual(self.state.assistant.popup.moved, 1)
        self.assertEqual(self.req("POST", "/api/window", {"mini": "drag"}, token=False)[0], 401, "only JARVIS's own pages may ask")
        self.state.assistant.popup = None

    def test_its_end_button_ends_a_conversation_held_by_the_app_window(self):
        start = self.req("GET", "/api/voice/events?since=-1&w=small&kind=mini")[1]["next"]
        status, data = self.req("POST", "/api/voice", {"action": "control", "what": "end"})
        self.assertEqual((status, data["ok"]), (200, True))
        events = self.req("GET", f"/api/voice/events?since={start}&w=app&kind=main")[1]["events"]
        self.assertEqual([(e["k"], e["do"], e["spoken"], e["all"]) for e in events if e["k"] == "ui"], [("ui", "end", False, True)],
                         "every window is told; it was a button, so nothing is said")
        self.assertEqual(self.req("POST", "/api/voice", {"action": "control", "what": "explode"})[0], 400)

    def test_a_window_says_which_kind_it_is(self):
        self.req("GET", "/api/voice/events?since=-1&w=small&kind=mini")
        self.req("GET", "/api/voice/events?since=-1&w=app&kind=main")
        self.req("GET", "/api/voice/events?since=-1&w=old")
        self.assertEqual(self.state.assistant.kinds, {"small": "mini", "app": "main", "old": "main"})
        self.req("POST", "/api/voice", {"action": "presence", "phase": "listening", "w": "small", "kind": "mini"})
        self.assertEqual(self.state.assistant.voices["small"][0], "listening")


if __name__ == "__main__":
    unittest.main()
