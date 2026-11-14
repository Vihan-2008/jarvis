"""The assistant works in one particular window, never in "whatever is in front" and never in JARVIS's own window.

Seen live: a search term meant for Outlook was typed and sent in another app that had come to the front."""
import unittest

from jcc import policy, voice_tools
from tests.helpers import as_windows


class FakeWindows:
    """Four windows, front to back. `stuck` makes Windows refuse to bring anything forward."""

    def __init__(self):
        self.rows = [{"handle": 1, "title": "JARVIS · Workspace"}, {"handle": 2, "title": "old hindi movies - YouTube - Google Chrome"},
                     {"handle": 3, "title": "Claude"}, {"handle": 4, "title": "Inbox - Outlook"}]
        self.programs, self.stuck, self.asked = {1: 10, 2: 20, 3: 30, 4: 40}, False, []

    def foreground(self):
        return self.rows[0]["handle"]

    def title(self, handle):
        return next((row["title"] for row in self.rows if row["handle"] == handle), "")

    def exists(self, handle):
        return any(row["handle"] == handle for row in self.rows)

    def focus(self, handle):
        self.asked.append(handle)
        if not self.stuck:
            self.front(handle)
        return self.foreground() == handle

    def front(self, handle):
        self.rows.sort(key=lambda row: row["handle"] != handle)

    def open(self, handle, title, program):
        self.rows.insert(0, {"handle": handle, "title": title})
        self.programs[handle] = program

    def all(self):
        return list(self.rows)

    def at(self, x, y):
        return self.foreground()

    def process(self, handle):
        return self.programs.get(handle, 0)

    def middle(self, handle):
        return None


class FakeDesktop:
    scale = 1.0

    def __init__(self, windows):
        self.windows, self.done = windows, []

    def window_title(self):
        return self.windows.title(self.windows.foreground())

    def measure(self):
        return 1.0

    def capture(self):
        return 4, 2, b"\x89PNG-fake"

    def perform(self, step):
        self.done.append((self.windows.title(self.windows.foreground()), step))     # where it landed, and what


class FakeControls:
    def __init__(self):
        self.calls, self.how, self.after = [], "pressed", None

    def call(self, payload, timeout=10.0):
        self.calls.append(payload)
        if payload["op"] == "list":
            return {"title": "", "items": [{"t": "Button", "n": "Compose", "x": 40, "y": 60, "on": True}]}
        if payload["op"] in ("find", "at"):
            return {"item": {"t": "Button", "n": payload.get("name", "Thing").title(), "x": 40, "y": 60}}
        if payload["op"] == "press":
            if self.after:
                self.after()
            return {"how": self.how}
        return {"item": {"n": payload.get("name") or "Search"}, "how": "typed"}       # "set": this box has to be typed into at the cursor


@as_windows
class TestWorkingWindow(unittest.TestCase):
    def setUp(self):
        self.windows, self.controls, self.turn, self.gates = FakeWindows(), FakeControls(), "t1", []
        self.desktop = FakeDesktop(self.windows)

        def service(op, payload):
            if op == "turn":
                return {"turn": self.turn}
            self.gates.append((payload["tool"], payload["window"]))
            decision = policy.decide(payload["tool"], payload["args"], policy.Context(window=payload["window"], control=payload["control"]))
            return {"ok": decision.verdict != policy.DENY, "reason": decision.reason}      # (the owner says yes to whatever is asked)

        self.box = voice_tools.Toolbox(self.desktop, service, lambda *a: (0, ""), self.controls, windows=self.windows)
        self._sleep = voice_tools.time.sleep
        voice_tools.time.sleep = lambda seconds: None

    def tearDown(self):
        voice_tools.time.sleep = self._sleep

    def next_request(self):
        self.turn += "x"
        self.box._turn_at = 0.0

    def typed(self):
        return [(where, step.get("text") or step.get("keys")) for where, step in self.desktop.done if step["action"] in ("type", "key")]

    def test_jarvis_own_window_in_front_means_the_window_behind_it(self):
        """Its owner looked at JARVIS, or answered a question in it. The app they were using is still the one meant."""
        self.assertIn("YouTube", self.box.list_controls())
        self.assertEqual(self.controls.calls[-1]["h"], 2)
        self.assertIn('Pressed "Compose" in "old hindi movies - YouTube', self.box.click_control("compose"))
        self.assertEqual([call["h"] for call in self.controls.calls if call["op"] == "press"], [2])
        self.assertEqual(self.windows.asked, [], "pressing a control by name needs no window brought forward")
        self.assertTrue(all("JARVIS" not in window for _, window in self.gates))

    def test_typing_goes_to_the_working_window_even_when_another_app_came_to_the_front(self):
        self.assertIn("Outlook", self.box.focus_window("outlook"))
        self.windows.front(3)                                                  # the owner clicked on another app meanwhile
        self.assertIn('Typed into "Inbox - Outlook"', self.box.type_text("Stephen Turbin", press_enter=True))
        self.assertEqual(self.typed(), [("Inbox - Outlook", "Stephen Turbin"), ("Inbox - Outlook", "enter")])
        self.assertEqual(self.gates[-1], ("type_text", "Inbox - Outlook"), "the safety rules judge the window that is really typed into")

    def test_nothing_is_typed_when_the_window_cannot_be_brought_forward(self):
        self.box.focus_window("outlook")
        self.windows.front(3)
        self.windows.stuck = True
        for attempt in (lambda: self.box.type_text("Stephen Turbin", press_enter=True), lambda: self.box.press_keys("enter"),
                        lambda: self.box.type_into("Stephen Turbin", "Search", press_enter=True), lambda: self.box.click(10, 10), lambda: self.box.scroll(-3)):
            with self.assertRaises(voice_tools.Refused) as refused:
                attempt()
            self.assertIn("could not be brought to the front", str(refused.exception))
        self.assertEqual(self.desktop.done, [], "not a single key or click reached the other app")

    def test_a_click_that_falls_back_to_the_mouse_first_brings_the_window_forward(self):
        self.controls.how = "click"                                            # this control cannot be pressed by name
        self.box.click_control("compose")
        self.assertEqual(self.desktop.done[0][0], "old hindi movies - YouTube - Google Chrome", "the click landed in the right window, not on JARVIS")

    def test_jarvis_own_window_is_never_worked_in(self):
        with self.assertRaises(voice_tools.Refused):
            self.box.focus_window("jarvis")
        for tool in ("type_text", "press_keys", "click", "click_control", "type_into", "scroll", "see_screen", "list_controls"):
            verdict = policy.decide(tool, {"text": "x", "keys": "enter", "name": "Send"}, policy.Context(window="JARVIS · Workspace"))
            self.assertEqual(verdict.verdict, policy.DENY, tool)
        self.assertEqual(policy.decide("type_text", {"text": "x"}, policy.Context(window="JARVIS film review - Notepad")).verdict, policy.ALLOW)

    def test_each_request_starts_from_the_window_its_owner_is_in(self):
        self.box.focus_window("outlook")
        self.box.list_controls()
        self.assertEqual(self.controls.calls[-1]["h"], 4)
        self.next_request()
        self.windows.front(2)                                                  # for the next request the owner is in the browser
        self.box.list_controls()
        self.assertEqual(self.controls.calls[-1]["h"], 2)

    def test_a_new_window_of_the_same_app_is_followed_but_another_app_is_not(self):
        self.box.focus_window("outlook")
        self.controls.after = lambda: self.windows.open(5, "Untitled - Message", 40)   # pressing Compose opens Outlook's own new window
        self.assertIn('it is the one being worked in', self.box.click_control("compose"))
        self.box.type_text("hello")
        self.assertEqual(self.typed()[-1], ("Untitled - Message", "hello"))
        self.controls.after = lambda: self.windows.front(3)                    # this time another program came forward by itself
        self.assertNotIn("being worked in", self.box.click_control("compose"))
        self.box.type_text("more")
        self.assertEqual(self.typed()[-1], ("Untitled - Message", "more"), "still the message window, not the app that pushed in front")

    def test_switching_windows_on_purpose_moves_the_work_there(self):
        self.box.focus_window("outlook")
        original = self.desktop.perform

        def perform(step):
            original(step)
            if step.get("keys") == "alt+tab":
                self.windows.front(2)
        self.desktop.perform = perform
        self.assertIn("YouTube", self.box.press_keys("alt+tab"))
        self.box.type_text("old hindi movies")
        self.assertEqual(self.typed()[-1][0], "old hindi movies - YouTube - Google Chrome")


if __name__ == "__main__":
    unittest.main()
