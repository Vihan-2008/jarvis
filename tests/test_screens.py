"""More than one screen. Seen live on the owner's desk: a 1920 by 1080 monitor as the main screen, and to its right and a
little above it the laptop's own 2560 by 1600 screen at 200%. JARVIS only ever looked at, and counted positions from,
the main screen: a window on the laptop screen could not be seen, and what it was told about it pointed elsewhere."""
import unittest

from jcc import computer, config, policy, quick, reminders, screens, voice_tools
from tests.helpers import EngineTestCase, as_windows
from tests.test_working_window import FakeControls, FakeWindows

MONITOR = {"handle": 11, "left": 0, "top": 0, "width": 1920, "height": 1080, "work": (0, 0, 1920, 1040), "scale": 1.0, "main": True, "name": "\\\\.\\DISPLAY2", "builtin": False}
LAPTOP = {"handle": 12, "left": 1920, "top": -212, "width": 2560, "height": 1600, "work": (1920, -212, 4480, 1308), "scale": 2.0, "main": False, "name": "\\\\.\\DISPLAY1", "builtin": True}
LEFT = {"handle": 13, "left": -3840, "top": 0, "width": 3840, "height": 2160, "work": (-3840, 0, 0, 2100), "scale": 1.5, "main": False, "name": "\\\\.\\DISPLAY3", "builtin": False}


def desk(*rows):
    return screens.number([dict(row) for row in rows])


class TestWhichScreen(unittest.TestCase):
    def test_screens_are_numbered_the_way_people_count_them(self):
        found = desk(LAPTOP, MONITOR, LEFT)
        self.assertEqual([(s["number"], s["handle"]) for s in found], [(1, 11), (2, 13), (3, 12)], "the main one first, then left to right")
        self.assertEqual(screens.number([{**MONITOR, "width": 0}]), [], "something that is no screen at all is left out")

    def test_a_point_or_a_window_is_on_the_screen_that_shows_it(self):
        found = desk(MONITOR, LAPTOP, LEFT)
        at = lambda x, y: screens.holding_point(found, x, y)["handle"]      # noqa: E731
        self.assertEqual((at(10, 10), at(1919, 1079), at(1920, 0), at(4479, -212), at(-1, 5)), (11, 11, 12, 12, 13))
        self.assertEqual(at(900, -100), 11, "above the main screen there is nothing: the nearest screen")
        self.assertEqual(at(9000, 9000), 12)
        box = lambda *b: screens.holding_box(found, b)["handle"]            # noqa: E731
        self.assertEqual(box(1700, 100, 2700, 700), 12, "most of it is on the laptop screen")
        self.assertEqual(box(1000, 100, 2000, 700), 11)
        self.assertEqual(box(-900, 2500, -100, 2900), 13, "wholly off every screen: the nearest")
        self.assertIsNone(screens.holding_point([], 1, 1))

    def test_said_in_words(self):
        found = desk(MONITOR, LAPTOP, LEFT)
        self.assertEqual([screens.where(s, found) for s in found], ["", "to the left", "to the right"])
        self.assertEqual(screens.where({**LAPTOP, "left": 0, "top": 1080}, desk(MONITOR, {**LAPTOP, "left": 0, "top": 1080})), "below")
        told = screens.describe(desk(MONITOR, LAPTOP))
        self.assertEqual(told, "2 screens: screen 1 (the main screen, 1920 by 1080); screen 2 (to the right of the main screen, 2560 by 1600 at 200%, the laptop's own screen).")
        self.assertEqual(screens.describe(desk(LAPTOP | {"main": True})), "One screen, 2560 by 1600 at 200%.")
        self.assertEqual(screens.describe([]), "")

    def test_a_screen_is_chosen_by_number_or_by_word(self):
        found = desk(MONITOR, LAPTOP, LEFT)
        main, left, laptop = found
        pick = lambda words, here=main: (screens.choose(found, here, words) or {}).get("handle")      # noqa: E731
        self.assertEqual((pick(2), pick("3"), pick("screen 2"), pick("the second monitor"), pick("third")), (13, 12, 13, 13, 12))
        self.assertEqual((pick("main"), pick("the primary display"), pick("my laptop screen"), pick("built-in")), (11, 11, 12, 12))
        self.assertEqual((pick("right"), pick("the left monitor"), pick("left", laptop), pick("right", left)), (12, 13, 11, 11))
        self.assertEqual((pick("other"), pick("the next screen", left), pick("other", laptop)), (13, 12, 11), "round them in order")
        self.assertEqual((pick("biggest"), pick("the smallest one")), (13, 11))
        self.assertEqual((pick(7), pick("above"), pick("left", left), pick("the moon"), pick("")), (None,) * 5)
        pair = desk(MONITOR, LAPTOP)
        self.assertEqual(screens.choose(pair, pair[1], "the monitor")["handle"], 11, "with a laptop and one monitor, the monitor is the one that is not the laptop's")
        self.assertEqual(screens.choose(pair, pair[0], "external")["handle"], 11)
        self.assertIsNone(screens.choose(found, main, "external"), "two of them: which one is not said")
        self.assertIsNone(screens.choose([], None, 1))

    def test_a_window_keeps_its_share_of_the_screen_when_it_moves(self):
        monitor, laptop = desk(MONITOR, LAPTOP)
        # the right half of the monitor's usable part becomes the right half of the laptop screen's
        self.assertEqual(screens.fit((960, 0, 1920, 1040), monitor, laptop), (3200, -212, 1280, 1520))
        left, top, width, height = screens.fit((100, 100, 1060, 640), monitor, laptop)
        self.assertTrue(1920 <= left and left + width <= 4480 and -212 <= top and top + height <= 1308, "wholly on the screen it moves to")
        # ...and never larger than that screen, or smaller than a window can usefully be
        self.assertEqual(screens.fit((1920, -212, 4480, 1308), laptop, monitor), (0, 0, 1920, 1040))
        self.assertEqual(screens.fit((10, 10, 20, 20), monitor, laptop)[2:], (200, 150))

    def test_the_list_from_windows_is_used_as_given_and_a_failure_is_no_screens(self):
        self.assertEqual([s["number"] for s in screens.screens(lambda: [dict(LAPTOP), dict(MONITOR)])], [1, 2])

        def broken():
            raise OSError("no")
        self.assertEqual(screens.screens(broken), [])


class TestPositionsOnTheScreenBeingLookedAt(unittest.TestCase):
    """A picture is of one screen. A point in it stands for a true position on the whole desktop, and back."""

    def desktop(self, origin, scale):
        d = computer.Desktop.__new__(computer.Desktop)         # (no Windows needed for the sums)
        d.origin, d.scale, d.screen, d.count, d.all = origin, scale, 2, 2, []
        return d

    def test_a_point_of_the_picture_and_the_true_position_it_stands_for(self):
        d = self.desktop((1920, -212), 2.0)                    # the laptop screen, 2560 wide, shown 1280 wide
        self.assertEqual(d.real(0, 0), (1920, -212))
        self.assertEqual(d.real(640, 400), (3200, 588))
        self.assertEqual(d.real(100, 50), (2120, -112), "a position above the main screen's top edge is negative, and right")
        self.assertEqual(d.shown(3200, 588), (640.0, 400.0))
        self.assertEqual(computer.picture_point(d, 2120, -112), (100.0, 50.0))
        main = self.desktop((0, 0), 1.5)
        self.assertEqual((main.real(1279, 719), main.shown(960, 540)), ((1918, 1078), (640.0, 360.0)))

    def test_a_stand_in_that_only_knows_a_scale_still_works(self):
        class Old:
            scale = 2.0
        self.assertEqual(computer.picture_point(Old(), 400, 100), (200.0, 50.0))

        class Measured:
            def measure(self):
                return 4.0
        self.assertEqual(computer.picture_point(Measured(), 400, 100), (100.0, 25.0))


class TwoScreens:
    """Stands in for the real desktop: two screens, and it remembers which one is being looked at."""

    def __init__(self, windows, where):
        self.windows, self.where, self.done, self.all = windows, where, [], desk(MONITOR, LAPTOP)
        self.origin, self.scale, self.screen, self.count, self.shots = (0, 0), 1.5, 1, 2, []

    def window_title(self):
        return self.windows.title(self.windows.foreground())

    def look(self, window=0, screen=0):
        chosen = next((s for s in self.all if s["number"] == screen), None) if screen else None
        chosen = chosen or self.all[self.where.get(window or self.windows.foreground(), 1) - 1]
        self.origin, self.scale, self.screen = (chosen["left"], chosen["top"]), chosen["width"] / 1280, chosen["number"]
        return chosen

    def measure(self):
        self.look()
        return self.scale

    def real(self, x, y):
        return round(self.origin[0] + float(x) * self.scale), round(self.origin[1] + float(y) * self.scale)

    def shown(self, x, y):
        return (float(x) - self.origin[0]) / self.scale, (float(y) - self.origin[1]) / self.scale

    def capture(self, window=0, screen=0):
        self.look(window, screen)
        self.shots.append(self.screen)
        return 1280, int(self.all[self.screen - 1]["height"] / self.scale), b"\x89PNG-fake"

    def perform(self, step):
        self.done.append(step)


class Controls(FakeControls):
    """The controls of a window, at the true positions Windows reports."""
    items = [{"t": "Button", "n": "Compose", "x": 40, "y": 60, "on": True}]

    def call(self, payload, timeout=10.0):
        if payload["op"] == "list":
            self.calls.append(payload)
            return {"title": "", "items": [dict(item) for item in self.items]}
        return super().call(payload, timeout)


@as_windows
class TestTheAssistantOnTwoScreens(unittest.TestCase):
    def setUp(self):
        self.windows, self.controls, self.moved = FakeWindows(), Controls(), []
        self.film = next(row["handle"] for row in self.windows.rows if "Outlook" in row["title"])
        self.desktop = TwoScreens(self.windows, {self.film: 2})

        def service(op, payload):
            if op == "turn":
                return {"turn": "t1"}
            decision = policy.decide(payload["tool"], payload["args"], policy.Context(window=payload["window"], control=payload["control"]))
            return {"ok": decision.verdict != policy.DENY, "reason": decision.reason}

        self.box = voice_tools.Toolbox(self.desktop, service, lambda *a: (0, ""), self.controls, windows=self.windows)
        self.box.screens = lambda: self.desktop.all
        self.box.box_of = lambda handle: (2000, 0, 3000, 600) if self.desktop.where.get(handle, 1) == 2 else (100, 100, 900, 700)

        def move_to(handle, target, all_):
            self.moved.append((handle, target["number"]))
            self.desktop.where[handle] = target["number"]
            return True
        self.box.move_to = move_to
        self._sleep = voice_tools.time.sleep
        voice_tools.time.sleep = lambda seconds: None

    def tearDown(self):
        voice_tools.time.sleep = self._sleep

    def test_the_picture_is_of_the_screen_that_shows_the_window_being_worked_in(self):
        self.box.focus_window("outlook")
        text = self.box.see_screen()[0]["text"]
        self.assertEqual(self.desktop.shots, [2], "the laptop screen, where that window is: not the main screen")
        self.assertIn("Picture size 1280x800", text)
        self.assertIn("This is screen 2 of 2", text)
        self.assertIn("screen 1 (the main screen, 1920 by 1080)", text)
        self.assertIn("the laptop's own screen", text)

    def test_another_screen_can_be_asked_for_by_number_and_a_click_then_lands_there(self):
        self.box.focus_window("outlook")
        self.box.see_screen(screen=1)
        self.assertEqual(self.desktop.shots, [1])
        self.assertEqual(self.box._real(640, 360), (960, 540), "the middle of the main screen")
        with self.assertRaises(Exception) as none:
            self.box.see_screen(screen=5)
        self.assertIn("There is no screen 5", str(none.exception))
        with self.assertRaises(Exception):
            self.box.see_screen(screen="the big one")

    def test_positions_of_controls_are_points_of_that_screens_picture(self):
        self.box.focus_window("outlook")
        # Windows reports the Send button at its true position on the laptop screen (to the right of, and above, the main one)
        self.controls.items = [{"t": "Button", "n": "Send", "x": 2120, "y": -112, "w": 80, "h": 30, "on": True, "page": False}]
        listed = self.box.list_controls()
        self.assertIn("Button: Send at (100, 50)", listed, "counted from that screen's corner, in the picture's own pixels")
        self.assertEqual(self.box._real(100, 50), (2120, -112), "and a click on that point goes back to the true position")

    def test_one_screen_says_nothing_about_screens(self):
        self.desktop.all, self.desktop.count, self.desktop.where = desk(MONITOR), 1, {}
        self.box.focus_window("outlook")
        self.assertNotIn("screen 1", self.box.see_screen()[0]["text"])

    def test_a_window_is_moved_to_another_screen_by_number_or_by_word(self):
        self.box.focus_window("outlook")
        self.assertEqual(self.box.move_window("main"), f'Moved "{self.windows.title(self.film)}" to the main screen.')
        self.assertEqual(self.moved, [(self.film, 1)])
        self.assertIn("is already on the main screen", self.box.move_window(1))
        self.assertIn("to screen 2, to the right of the main one", self.box.move_window("the laptop screen", title="outlook"))
        self.assertEqual(self.moved[-1], (self.film, 2))
        with self.assertRaises(Exception) as none:
            self.box.move_window("screen 4")
        self.assertIn("There is no screen", str(none.exception))
        self.assertIn("2 screens:", str(none.exception), "and it is told which screens there are")
        with self.assertRaises(Exception) as missing:
            self.box.move_window("other", title="no such window")
        self.assertIn("No open window matches", str(missing.exception))

    def test_with_one_screen_there_is_nowhere_to_move_it(self):
        self.box.screens = lambda: desk(MONITOR)
        self.box.focus_window("outlook")
        with self.assertRaises(Exception) as alone:
            self.box.move_window("other")
        self.assertIn("Only one screen is connected", str(alone.exception))
        self.assertEqual(self.moved, [])


class TestSaidOutLoud(EngineTestCase):
    """The things said most often about screens are done at once, without asking an AI."""

    def setUp(self):
        super().setUp()
        self.cfg = config.load()
        self.acted, self.returns = [], {}
        self.quick = quick.Quick(self.cfg, quick.Apps(self.cfg), reminders.Reminders(self.cfg), self.act)

    def act(self, kind, value=None):
        self.acted.append((kind, value))
        return self.returns.get(kind)

    def say(self, text):
        result = self.quick.handle(text)
        return result.say if result else None

    def test_move_a_window_to_another_screen(self):
        monitor, laptop = desk(MONITOR, LAPTOP)
        self.returns["move"] = ("Inbox - Outlook", laptop, False)
        self.assertEqual(self.say("move this to the other screen"), "Moved it to the laptop screen.")
        self.assertEqual(self.say("Hey JARVIS, put Chrome on my laptop screen please"), "Moved it to the laptop screen.")
        self.assertEqual(self.say("send it to screen 2"), "Moved it to the laptop screen.")
        self.assertEqual(self.say("move that window over to the left monitor"), "Moved it to the laptop screen.")
        self.assertEqual(self.say("move spotify to the second monitor"), "Moved it to the laptop screen.")
        self.assertEqual(self.acted, [("move", ("", "other screen")), ("move", ("chrome", "laptop screen")), ("move", ("", "screen 2")),
                                      ("move", ("", "left monitor")), ("move", ("spotify", "second monitor"))])
        self.returns["move"] = ("Inbox - Outlook", monitor, True)
        self.assertEqual(self.say("move this to the main screen"), "It is already on the main screen.")
        self.returns["move"] = ("Inbox - Outlook", {**monitor, "main": False, "number": 3}, False)
        self.assertEqual(self.say("put it on screen 3"), "Moved it to screen 3.")

    def test_a_window_that_is_not_open_and_things_that_are_not_about_screens(self):
        self.returns["move"] = None
        self.assertEqual(self.say("move spotify to the other screen"), "I could not find a window called spotify.")
        self.acted.clear()
        for text in ("move this to the trash", "put the kettle on", "send it to Sam", "move the meeting to monday"):
            self.quick.handle(text)
        self.assertEqual([kind for kind, _ in self.acted if kind == "move"], [], "none of these is about a screen")

    def test_which_screens_are_connected(self):
        self.returns["screens"] = desk(MONITOR, LAPTOP)
        self.assertEqual(self.say("how many screens do I have"),
                         "Two screens: screen 1 (the main screen, 1920 by 1080); screen 2 (to the right of the main screen, 2560 by 1600 at 200%, the laptop's own screen).")
        self.returns["screens"] = desk(MONITOR)
        self.assertEqual(self.say("which monitors are connected"), "One screen, 1920 by 1080.")


if __name__ == "__main__":
    unittest.main()
