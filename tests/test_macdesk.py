"""JARVIS's hands and eyes on a Mac (jcc/macdesk.py), with the Mac itself stood in for: a made-up desktop with three
windows, their controls and two screens. These run on any system. What the real macOS answers is checked on a real Mac by
scripts/mac_live_check.py.
"""
import json
import struct
import subprocess
import tempfile
import time
import unittest
import zlib
from pathlib import Path
from unittest import mock

from jcc import computer, config, macdesk, policy, system, voice_tools
from tests.helpers import EngineTestCase
from tests.test_computer import Model, wait_until


def node(el, role, title="", at=(0, 0), size=(80, 24), **more):
    return {"el": el, "role": role, "subrole": more.get("subrole", ""), "title": title, "description": more.get("description", ""),
            "placeholder": more.get("placeholder", ""), "value": more.get("value", ""), "position": at, "size": size,
            "enabled": more.get("enabled", True), "children": []}


def png(width, height):
    """A real, tiny PNG file that says it is this large."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\x00" * 64)) + chunk(b"IEND", b"")


class NotAllowed(OSError):
    """(The same name as the one in jcc/macax.py: that is how jcc/macdesk.py knows it.)"""


class FakeMac:
    """Stands in for the Mac in jcc/macax.py."""

    def __init__(self):
        self.windows = [{"handle": 11, "pid": 100, "app": "TextEdit", "name": "Notes.txt", "box": (100, 100, 900, 700)},
                        {"handle": 12, "pid": 200, "app": "Safari", "name": "", "box": (0, 25, 1440, 900)},
                        {"handle": 13, "pid": 300, "app": "Google Chrome", "name": "JARVIS Workspace", "box": (1500, 50, 2700, 900)}]
        self.hidden = [{"handle": 14, "pid": 100, "app": "TextEdit", "name": "Old.txt", "box": (0, 0, 500, 400)}]
        self.front, self.told = 100, {200: [(12, (0, 25, 1440, 875), "Apple")]}
        self.trees = {11: [node("save", "AXButton", "Save", (120, 110)), node("bold", "AXCheckBox", "Bold", (220, 110)),
                           node("body", "AXTextArea", "", (100, 150), (800, 550)), node("find", "AXTextField", "", (700, 110), placeholder="Search"),
                           node("pass", "AXTextField", "Password", (500, 110), subrole="AXSecureTextField"),
                           node("ghost", "AXButton", "Hidden", (120, 2000)), node("group", "AXGroup", "A group", (100, 100), (800, 30)),
                           node("off", "AXButton", "Revert", (320, 110), enabled=False), node("label", "AXStaticText", "", (420, 110), value="3 words")],
                      12: [node("back", "AXButton", "Back", (10, 30)), node("page", "AXWebArea", "Apple", (0, 80), (1440, 820)),
                           node("buy", "AXLink", "Buy", (200, 300)), node("email", "AXTextField", "Email", (200, 400), (300, 30))]}
        self.unpressable, self.unfillable = {"bold-no"}, set()
        self.pressed, self.filled, self.focused, self.events, self.finished, self.released = [], [], [], [], 0, 0
        self.allowed, self.sees, self.asked_screen, self.placed = True, True, 0, []

    def rows(self, every=False):
        return [dict(w) for w in self.windows + (self.hidden if every else [])]

    def front_pid(self):
        return self.front

    def titles(self, pid):
        return self.told.get(pid, [])

    def raise_window(self, handle):
        row = next((w for w in self.windows if w["handle"] == handle), None)
        if not row:
            raise OSError("That window is gone.")
        self.windows.remove(row)
        self.windows.insert(0, row)
        self.front = row["pid"]

    def walk(self, handle, limit=6000, seconds=6.0):
        if not self.allowed:
            raise NotAllowed("macOS has not yet allowed JARVIS to control other apps.")
        if handle not in self.trees:
            raise OSError("The window did not list its controls.")
        row = next(w for w in self.rows(True) if w["handle"] == handle)
        left, top, right, bottom = row["box"]
        return {"title": row["name"], "frame": (left, top, right - left, bottom - top), "nodes": self.trees[handle], "keep": [1]}

    def done(self, walked):
        self.finished += 1

    def release(self, references):
        self.released += 1

    def at(self, x, y):
        for nodes in self.trees.values():
            for item in nodes:
                (left, top), (wide, high) = item["position"], item["size"]
                if left <= x <= left + wide and top <= y <= top + high and item["role"] != "AXGroup":
                    return {"nodes": [item], "keep": [1]}
        return {"nodes": [], "keep": []}

    def press(self, el):
        self.pressed.append(el)
        return el not in self.unpressable

    def fill(self, el, text):
        self.filled.append((el, text))
        return el not in self.unfillable

    def focus(self, el):
        self.focused.append(el)
        return True

    def displays(self):
        return [{"handle": 1, "left": 0, "top": 0, "width": 1440, "height": 900, "main": True, "pixels": 2880, "builtin": True},
                {"handle": 2, "left": 1440, "top": 0, "width": 1920, "height": 1080, "main": False, "pixels": 1920, "builtin": False}]

    def sees_screen(self):
        return self.sees

    def ask_screen(self):
        self.asked_screen += 1

    def trusted(self):
        return self.allowed

    def click(self, x, y, right=False, double=False):
        self.events.append(("click", x, y, right, double))

    def move(self, x, y):
        self.events.append(("move", x, y))

    def scroll(self, lines):
        self.events.append(("scroll", lines))

    def key(self, code, flags=0):
        self.events.append(("key", code, flags))

    def type_text(self, text):
        self.events.append(("type", text))

    def place_window(self, handle, left, top, width, height):
        self.placed.append((handle, left, top, width, height))
        return True


class Camera:
    """Stands in for the Mac's screencapture and sips: writes a picture file of the size a real one would have."""

    def __init__(self, pixels_per_point=2):
        self.calls, self.ratio = [], pixels_per_point

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        target = Path(argv[-1])
        if argv[0] == "screencapture":
            area = next((a for a in argv if a.startswith("-R")), "")
            wide, high = (int(n) for n in area[2:].split(",")[2:]) if area else (1200, 800)
            target.write_bytes(png(wide * self.ratio, high * self.ratio))
        elif argv[0] == "sips":
            was = macdesk.png_size(target.read_bytes())
            wanted = int(argv[argv.index("--resampleWidth") + 1])
            target.write_bytes(png(wanted, round(was[1] * wanted / was[0])))
        return subprocess.CompletedProcess(argv, 0, b"", b"")


class OnAMac(unittest.TestCase):
    def setUp(self):
        self.mac = FakeMac()
        patch = mock.patch.object(system, "PLATFORM", "darwin")
        patch.start()
        self.addCleanup(patch.stop)


class TestWhatAControlIsCalled(OnAMac):
    def test_a_macs_controls_get_the_names_jarvis_already_uses(self):
        kinds = {role: macdesk.describe(node("x", role, "Name", (10, 10)))["t"] for role in
                 ("AXButton", "AXCheckBox", "AXTextField", "AXTextArea", "AXLink", "AXPopUpButton", "AXWebArea", "AXStaticText", "AXMenuItem", "AXSomethingNew")}
        self.assertEqual(kinds, {"AXButton": "Button", "AXCheckBox": "CheckBox", "AXTextField": "Edit", "AXTextArea": "Edit", "AXLink": "Hyperlink",
                                 "AXPopUpButton": "ComboBox", "AXWebArea": "Document", "AXStaticText": "Text", "AXMenuItem": "MenuItem", "AXSomethingNew": "Custom"})
        self.assertEqual(macdesk.describe(node("x", "AXRadioButton", "General", (10, 10), subrole="AXTabButton"))["t"], "TabItem")

    def test_its_name_its_middle_and_whether_it_is_a_password_box(self):
        save = macdesk.describe(node("save", "AXButton", "  Save   as ", (120, 110), (80, 24)))
        self.assertEqual((save["n"], save["x"], save["y"], save["w"], save["h"], save["on"], save["secret"]), ("Save as", 160, 122, 80, 24, True, False))
        self.assertEqual(macdesk.describe(node("x", "AXButton", "", (1, 1), description="Close tab"))["n"], "Close tab")
        self.assertEqual(macdesk.describe(node("x", "AXStaticText", "", (1, 1), value="3 words"))["n"], "3 words")
        self.assertEqual(macdesk.describe(node("x", "AXTextField", "", (1, 1), placeholder="Search"))["n"], "Search")
        self.assertTrue(macdesk.describe(node("x", "AXTextField", "Password", (1, 1), subrole="AXSecureTextField"))["secret"])

    def test_what_is_not_shown_is_not_described(self):
        self.assertIsNone(macdesk.describe({**node("x", "AXButton", "No place"), "position": None}))
        self.assertIsNone(macdesk.describe(node("x", "AXButton", "Too small", (5, 5), (2, 2))))
        frame = (100, 100, 800, 600)
        self.assertIsNone(macdesk.describe(node("x", "AXButton", "Scrolled away", (120, 2000)), frame), "outside the window it belongs to")
        self.assertIsNotNone(macdesk.describe(node("x", "AXButton", "In view", (120, 110)), frame))


class TestTheWindows(OnAMac):
    def setUp(self):
        super().setUp()
        self.win = macdesk.Windows(self.mac)

    def test_they_are_listed_front_to_back_with_the_apps_name(self):
        self.assertEqual([(row["handle"], row["title"]) for row in self.win.all()],
                         [(11, "Notes.txt - TextEdit"), (12, "Apple - Safari"), (13, "JARVIS Workspace - Google Chrome")])
        self.assertEqual(self.win.title(12), "Apple - Safari", "macOS gave no title (Screen Recording is off): Accessibility is asked")
        self.assertTrue(policy.OWN_WINDOW.search(self.win.title(13)), "JARVIS's own window is still known as its own")
        self.assertEqual(self.win.title(14), "Old.txt - TextEdit", "a window that is not on the screen right now still has its title")

    def test_the_one_in_front_and_the_one_at_a_point(self):
        self.assertEqual(self.win.foreground(), 11)
        self.assertEqual((self.win.at(150, 150), self.win.at(50, 50), self.win.at(5000, 5000)), (11, 12, 0), "the one on top at that spot")
        self.assertEqual((self.win.process(12), self.win.app(12), self.win.middle(11)), (200, "safari", (500, 400)))
        self.assertEqual((self.win.exists(14), self.win.exists(99), self.win.exists(0)), (True, False, False))

    def test_a_window_is_brought_to_the_front(self):
        sleep = time.sleep
        with mock.patch.object(macdesk.time, "sleep", lambda seconds: sleep(0)):
            self.assertTrue(self.win.focus(12))
            self.assertEqual(self.win.foreground(), 12)
            self.assertFalse(self.win.focus(99), "a window that is gone")

    def test_with_no_mac_to_ask_there_are_simply_no_windows(self):
        nothing = macdesk.Windows()                            # (the tests' own rule: the real Mac is never asked)
        self.assertEqual((nothing.all(), nothing.foreground(), nothing.title(5), nothing.exists(5), nothing.focus(5), nothing.at(1, 1)), ([], 0, "", False, False, 0))


class TestAWindowsControls(OnAMac):
    def setUp(self):
        super().setUp()
        self.controls = macdesk.Controls(self.mac)

    def test_they_are_listed_as_on_windows(self):
        got = self.controls.call({"op": "list", "h": 11})
        self.assertEqual(got["title"], "Notes.txt")
        self.assertEqual([(i["t"], i["n"]) for i in got["items"]],
                         [("Button", "Save"), ("CheckBox", "Bold"), ("Edit", ""), ("Edit", "Search"), ("Edit", "Password"), ("Button", "Revert")],
                         "named controls and every box; not what is out of sight, not plain groups and text")
        self.assertFalse(next(i for i in got["items"] if i["n"] == "Revert")["on"])
        self.assertEqual(self.mac.finished, 1, "what was read is let go of again")
        with_texts = self.controls.call({"op": "list", "h": 11, "texts": True})
        self.assertIn(("Text", "3 words"), [(i["t"], i["n"]) for i in with_texts["items"]])

    def test_what_is_on_a_web_page_is_marked_as_the_page(self):
        items = self.controls.call({"op": "list", "h": 12})["items"]
        self.assertEqual([(i["n"], bool(i.get("page"))) for i in items], [("Back", False), ("Apple", False), ("Buy", True), ("Email", True)])

    def test_pressing_by_name(self):
        self.assertEqual(self.controls.call({"op": "find", "h": 11, "name": "save"})["item"]["n"], "Save")
        self.assertEqual(self.controls.call({"op": "press", "h": 11, "name": "Save"})["how"], "pressed")
        self.assertEqual(self.controls.call({"op": "press", "h": 11, "name": "Bold"})["how"], "switched")
        self.assertEqual(self.mac.pressed, ["save", "bold"])
        self.mac.unpressable.add("save")
        self.assertEqual(self.controls.call({"op": "press", "h": 11, "name": "Save"})["how"], "click", "it has no press of its own: the caller clicks it")
        self.assertIsNone(self.controls.call({"op": "press", "h": 11, "name": "Nothing like this"})["item"])
        self.assertIsNone(self.controls.call({"op": "press", "h": 11, "name": "Hidden"})["item"], "a control that is out of sight is not pressed")

    def test_filling_a_box(self):
        got = self.controls.call({"op": "set", "h": 11, "name": "Search", "text": "bread"})
        self.assertEqual((got["how"], self.mac.filled), ("set", [("find", "bread")]))
        got = self.controls.call({"op": "set", "h": 11, "name": "", "text": "Dear all"})
        self.assertEqual((got["item"]["t"], got["how"]), ("Edit", "set"), "no name given: the first box")
        self.mac.unfillable.add("find")
        got = self.controls.call({"op": "set", "h": 11, "name": "Search", "text": "bread"})
        self.assertEqual((got["how"], self.mac.focused[-1]), ("focus", "find"), "it does not take text that way: the cursor is put there and the caller types")

    def test_a_password_box_is_never_filled_and_a_web_pages_box_is_typed_into(self):
        got = self.controls.call({"op": "set", "h": 11, "name": "Password", "text": "hunter2"})
        self.assertEqual(got["how"], "secret")
        self.assertEqual(self.mac.filled, [])
        got = self.controls.call({"op": "set", "h": 12, "name": "Email", "text": "me@example.com"})
        self.assertEqual((got["how"], self.mac.filled, self.mac.focused), ("focus", [], ["email"]), "a page only notices text that is typed")

    def test_the_control_under_a_point(self):
        self.assertEqual(self.controls.call({"op": "at", "x": 130, "y": 120})["item"]["n"], "Save")
        self.assertIsNone(self.controls.call({"op": "at", "x": 5000, "y": 5000})["item"])
        self.assertEqual(self.mac.released, 2)

    def test_a_window_that_is_gone_and_a_mac_that_has_not_allowed_it(self):
        with self.assertRaises(OSError):
            self.controls.call({"op": "list", "h": 99})
        self.mac.allowed = False
        got = self.controls.call({"op": "list", "h": 11})
        self.assertEqual((got["say"], "macOS has not yet allowed" in got["error"]), (True, True), "the owner is told what to switch on, in plain words")

    def test_a_window_that_does_not_answer_cannot_hang_jarvis(self):
        self.mac.walk = lambda handle, limit=6000, seconds=6.0: time.sleep(1.5)
        started = time.time()
        with self.assertRaises(TimeoutError):
            self.controls.call({"op": "list", "h": 11}, 0.2)
        self.assertLess(time.time() - started, 1.0)


class TestKeys(OnAMac):
    def test_a_shortcut_as_the_mac_counts_keys(self):
        command, shift, option, control = 1 << 20, 1 << 17, 1 << 19, 1 << 18
        self.assertEqual(macdesk.keys("cmd+s"), (1, command))
        self.assertEqual(macdesk.keys("command+shift+n"), (45, command | shift))
        self.assertEqual(macdesk.keys("win+tab"), (48, command), "the key where the Windows key is")
        self.assertEqual(macdesk.keys("ctrl+option+left"), (123, control | option))
        self.assertEqual((macdesk.keys("enter"), macdesk.keys("esc"), macdesk.keys("f5"), macdesk.keys("cmd")), ((36, 0), (53, 0), (96, 0), (55, 0)))
        for odd in ("", "cmd+hyper", "plus"):
            with self.assertRaises(ValueError):
                macdesk.keys(odd)

    def test_every_key_jarvis_lets_the_ai_name_is_known_on_a_mac(self):
        for name in list(computer.KEYS) + list("abcdefghijklmnopqrstuvwxyz0123456789"):
            self.assertIsInstance(macdesk.keys(name)[0], int, name)

    def test_the_shortcuts_that_are_never_pressed(self):
        for keys in ("cmd+shift+q", "ctrl+cmd+q", "command+option+esc", "win+alt+escape"):
            self.assertTrue(macdesk.never(keys.split("+")), keys)
            self.assertEqual(policy.decide("press_keys", {"keys": keys}, policy.Context()).verdict, policy.DENY, keys)
        self.assertFalse(macdesk.never(["cmd", "q"]))
        self.assertTrue(macdesk.blocked(["cmd", "q"]) and macdesk.blocked(["command", "space"]), "not pressed by the step-by-step panel")
        self.assertFalse(macdesk.blocked(["cmd", "s"]))

    def test_the_approval_rules_know_a_macs_shortcuts(self):
        ask = lambda keys, **ctx: policy.decide("press_keys", {"keys": keys}, policy.Context(**ctx))    # noqa: E731
        self.assertEqual(ask("cmd+s").verdict, policy.ALLOW)
        self.assertEqual(ask("cmd+space").verdict, policy.CONFIRM, "Spotlight starts anything by name")
        self.assertEqual(ask("cmd+delete").verdict, policy.CONFIRM, "moves what is selected to the Trash")
        self.assertEqual(ask("cmd+option+delete").verdict, policy.CONFIRM)
        self.assertEqual(ask("cmd+q").verdict, policy.ALLOW)
        self.assertEqual(ask("cmd+q", exposed=True).verdict, policy.CONFIRM, "in careful mode, closing something is asked about")
        self.assertEqual(ask("cmd+enter", window="New Message - Mail").verdict, policy.CONFIRM, "Command-Return sends mail")

    def test_the_step_by_step_ai_is_told_it_is_on_a_mac_and_held_to_the_macs_rules(self):
        self.assertIn("You operate a Mac", computer.system_prompt())
        self.assertIn("cmd+s", computer.system_prompt())
        step = lambda keys: computer.parse_action(json.dumps({"action": "key", "keys": keys, "reason": "x"}), 100, 100)    # noqa: E731
        self.assertEqual(step("cmd+s")["action"], "key")
        self.assertEqual(step("cmd+q")["action"], "need_user")
        self.assertEqual(step("cmd+space")["action"], "need_user")
        with mock.patch.object(system, "PLATFORM", "win32"):
            self.assertIn("You operate a Windows computer", computer.system_prompt())
            self.assertEqual(step("win+r")["action"], "need_user")


class TestHowAShortcutIsPressed(unittest.TestCase):
    """The part of jcc/macax.py that sends keys, with macOS's own library stood in for."""

    def mac(self, down=()):
        from jcc import macax
        sent, flags = [], {}

        class Library:
            def AXIsProcessTrusted(self):
                return 1

            def CGEventCreateKeyboardEvent(self, source, code, is_down):
                flags[len(flags) + 1] = [code, is_down, None]
                return len(flags)

            def CGEventSetFlags(self, event, marks):
                flags[event][2] = marks

            def CGEventPost(self, tap, event):
                sent.append(tuple(flags[event]))

            def CFRelease(self, ref):
                pass

            def CGEventSourceKeyState(self, state, key):
                return 1 if key in down else 0
        one = object.__new__(macax.Mac)
        one.lib = Library()
        return one, sent

    def test_the_modifier_keys_go_down_first_and_come_up_last(self):
        command, shift = 1 << 20, 1 << 17
        with mock.patch.object(time, "sleep", lambda seconds: None):
            mac, sent = self.mac()
            mac.key(1, command | shift)                         # Command-Shift-S
            self.assertEqual(sent, [(55, 1, command), (56, 1, command | shift), (1, 1, command | shift), (1, 0, command | shift),
                                    (56, 0, command), (55, 0, 0)], "afterwards no key is down and nothing is marked as held")
            mac, sent = self.mac()
            mac.key(36)
            self.assertEqual(sent, [(36, 1, 0), (36, 0, 0)], "a key on its own is just that key")

    def test_whether_a_modifier_is_held_is_asked_of_the_keys_themselves(self):
        self.assertFalse(self.mac()[0].modifiers_held())
        self.assertTrue(self.mac(down=(58,))[0].modifiers_held(), "Option is down")
        self.assertTrue(self.mac(down=(54,))[0].modifiers_held(), "the right-hand Command key counts too")
        self.assertFalse(self.mac(down=(0,))[0].modifiers_held(), "a letter is not a modifier")


class TestTheScreenThePointerAndTheKeys(OnAMac):
    def setUp(self):
        super().setUp()
        self.camera = Camera()
        self.desk = macdesk.Desktop(self.mac, self.camera, macdesk.Windows(self.mac))

    def test_pictures_and_positions_are_of_the_screen_showing_the_window(self):
        chosen = self.desk.look()
        self.assertEqual((chosen["number"], self.desk.origin, self.desk.scale, self.desk.count), (1, (0, 0), 1440 / 1280, 2))
        self.assertEqual(self.desk.real(640, 400), (720, 450))
        self.assertEqual(self.desk.shown(720, 450), (640.0, 400.0))
        self.desk.look(13)                                    # JARVIS's own window is on the second screen
        self.assertEqual((self.desk.screen, self.desk.origin, self.desk.scale), (2, (1440, 0), 1.5))
        self.assertEqual(self.desk.real(100, 100), (1590, 150))
        self.assertEqual(self.desk.look(screen=1)["number"], 1, "or the screen asked for by number")
        self.assertEqual(self.desk.window_title(), "Notes.txt - TextEdit")

    def test_a_picture_of_the_screen_is_taken_by_the_macs_own_tools(self):
        wide, high, data = self.desk.capture()
        self.assertEqual((wide, high, macdesk.png_size(data)), (1280, 800, (1280, 800)), "a sharp screen's 2880 dots, made as wide as its 1440 points allow")
        shot, smaller = self.camera.calls
        self.assertEqual(shot[:3], ["screencapture", "-x", "-R0,0,1440,900"])
        self.assertEqual(smaller[:3], ["sips", "--resampleWidth", "1280"])
        self.assertFalse(Path(shot[-1]).exists(), "the picture file is not kept")
        wide, high, _ = self.desk.capture(screen=2)
        self.assertEqual((wide, self.camera.calls[2][2]), (1280, "-R1440,0,1920,1080"))

    def test_without_screen_recording_no_picture_is_taken_and_the_owner_is_told(self):
        self.mac.sees = False
        with self.assertRaises(OSError) as refused:
            self.desk.capture()
        self.assertIn("Screen & System Audio Recording", str(refused.exception))
        self.assertEqual((self.mac.asked_screen, self.camera.calls), (1, []), "macOS is asked to show its own question; nothing is pictured")

    def test_a_step_becomes_what_the_mac_is_told_to_do(self):
        self.desk.look()
        self.desk.perform({"action": "click", "x": 640, "y": 400})
        self.desk.perform({"action": "double_click", "x": 10, "y": 10})
        self.desk.perform({"action": "right_click", "x": 10, "y": 10})
        self.desk.perform({"action": "type", "text": "Dear all,\nhello"})
        self.desk.perform({"action": "key", "keys": "cmd+s"})
        self.desk.perform({"action": "scroll", "amount": -3})
        self.desk.move_pointer(500, 400)
        self.assertEqual(self.mac.events, [("click", 720, 450, False, False), ("click", 11, 11, False, True), ("click", 11, 11, True, False),
                                           ("type", "Dear all,\nhello"), ("key", 1, 1 << 20), ("scroll", -9), ("move", 500.0, 400.0)])
        with self.assertRaises(ValueError):
            self.desk.perform({"action": "key", "keys": "cmd+shift+q"})
        self.assertEqual(len(self.mac.events), 7, "logging out is pressed for nobody")

    def test_the_screens_are_described_as_on_windows(self):
        from jcc import screens
        found = screens.number(macdesk.raw_screens(self.mac))
        self.assertEqual([(s["number"], s["main"], s["left"], s["width"], s["work"]) for s in found],
                         [(1, True, 0, 1440, (0, 25, 1440, 900)), (2, False, 1440, 1920, (1440, 25, 3360, 1080))])
        self.assertEqual(macdesk.window_box(11, self.mac), (100, 100, 900, 700))
        self.assertTrue(macdesk.move_window(11, found[1], found, self.mac))
        handle, left, top, width, height = self.mac.placed[0]
        self.assertEqual(handle, 11)
        self.assertTrue(1440 <= left and left + width <= 3360 and 25 <= top and top + height <= 1080, "wholly on the other screen")

    def test_pictures_for_the_chat(self):
        wide, high, data = macdesk.picture_of_window(11, self.mac, self.camera)
        self.assertEqual(self.camera.calls[0][:4], ["screencapture", "-x", "-l11", "-o"])
        with self.assertRaises(ValueError):
            macdesk.picture_of_window(99, self.mac, self.camera)
        macdesk.picture_of_screen(2, 0, self.mac, self.camera)
        self.assertEqual(self.camera.calls[-2][2], "-R1440,0,1920,1080")
        self.mac.sees = False
        with self.assertRaises(ValueError) as refused:
            macdesk.picture_of_screen(0, 0, self.mac, self.camera)
        self.assertIn("has not yet allowed JARVIS to see the screen", str(refused.exception))


class TestTheAssistantsToolsOnAMac(OnAMac):
    """The same tools as on Windows, end to end, with the made-up Mac underneath."""

    def setUp(self):
        super().setUp()
        self.asked = []

        def service(op, payload):
            self.asked.append((op, payload))
            return {"ok": True, "permit": "p"} if op == "gate" else {}
        windows = macdesk.Windows(self.mac)
        self.box = voice_tools.Toolbox(macdesk.Desktop(self.mac, Camera(), windows), service, None, macdesk.Controls(self.mac), windows=windows)
        self.box.state_dir = Path(tempfile.mkdtemp(prefix="jcc-macdesk-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.box.state_dir, ignore_errors=True))
        sleep = time.sleep
        for module in (voice_tools.time, macdesk.time):
            patch = mock.patch.object(module, "sleep", lambda seconds: sleep(0))
            patch.start()
            self.addCleanup(patch.stop)

    def test_the_windows_are_listed_and_one_is_brought_forward(self):
        self.assertEqual(self.box.list_windows().splitlines(), ["Notes.txt - TextEdit", "Apple - Safari", "JARVIS Workspace - Google Chrome"])
        self.assertEqual(self.box.focus_window("safari"), 'The window in front is now "Apple - Safari".')
        self.assertEqual(self.mac.front, 200)
        with self.assertRaises(voice_tools.Refused):
            self.box.focus_window("jarvis workspace")

    def test_controls_are_listed_and_pressed_by_name(self):
        listed = self.box.list_controls()
        self.assertIn('Working in the window "Notes.txt', listed)
        self.assertIn("Button: Save at (142, 108)", listed, "positions are points of the picture of that screen")
        self.assertEqual(self.box.click_control("Save"), 'Pressed "Save" in "Notes.txt - TextEdit".')
        self.assertEqual(self.mac.pressed, ["save"])
        self.mac.unpressable.add("bold")
        self.assertEqual(self.box.click_control("Bold"), 'Clicked "Bold" in "Notes.txt - TextEdit".')
        self.assertEqual(self.mac.events[-1][:3], ("click", 260, 122), "no press of its own: clicked in its middle, in the Mac's own points")

    def test_typing_goes_into_the_window_being_worked_in(self):
        self.assertEqual(self.box.type_into("bread", "Search"), 'Filled "Search" in "Notes.txt - TextEdit".')
        self.mac.unfillable.add("find")
        self.assertEqual(self.box.type_into("bread", "Search"), 'Typed at the cursor in "Search" of "Notes.txt - TextEdit".')
        self.assertEqual(self.mac.events[-1], ("type", "bread"))
        with self.assertRaises(voice_tools.Refused) as refused:
            self.box.type_into("hunter2", "Password")
        self.assertIn("password box", str(refused.exception))
        self.assertEqual(self.box.type_text("hello"), 'Typed into "Notes.txt - TextEdit".')
        self.assertEqual(self.box.press_keys("cmd+s"), 'Pressed cmd+s in "Notes.txt - TextEdit".')
        self.assertEqual(self.mac.events[-1], ("key", 1, 1 << 20))
        self.box.scroll(-2)
        self.assertEqual(self.mac.events[-2:], [("move", 500.0, 400.0), ("scroll", -6)], "the pointer is put over the window, then the wheel turns")

    def test_the_screen_is_looked_at_and_clicked(self):
        seen = self.box.see_screen()
        self.assertIn("Working in: Notes.txt - TextEdit", seen[0]["text"])
        self.assertIn("Picture size 1280x800", seen[0]["text"])
        self.assertIn("screen 1 of 2", seen[0]["text"])
        self.assertEqual(seen[1]["mimeType"], "image/png")
        said = self.box.click(160, 110)
        self.assertEqual(said, 'Clicked "Save" in "Notes.txt - TextEdit".')
        self.assertEqual(self.mac.events[-1], ("click", 180, 124, False, False))

    def test_when_macos_has_not_allowed_it_the_owner_is_told_what_to_switch_on(self):
        self.mac.allowed = False
        with self.assertRaises(voice_tools.Refused) as refused:
            self.box.list_controls()
        self.assertIn("macOS has not yet allowed JARVIS to control other apps", str(refused.exception))


class TestStepByStepOnAMac(EngineTestCase):
    def test_a_task_is_carried_out_with_the_macs_screen_and_pointer(self):
        mac = FakeMac()
        cfg = config.load()
        sleep = computer.time.sleep
        patches = [mock.patch.object(system, "PLATFORM", "darwin"), mock.patch.object(computer.time, "sleep", lambda seconds: sleep(min(seconds, 0.01)))]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        computer.configure(cfg, True, "auto")
        model = Model([{"action": "click", "x": 640, "y": 400, "reason": "Open the menu."}, {"action": "key", "keys": "cmd+s", "reason": "Save."},
                       {"action": "done", "reason": "Saved."}])
        pc = computer.Computer(cfg, model, macdesk.Desktop(mac, Camera(), macdesk.Windows(mac)))
        pc.start("Save the open document")
        self.assertTrue(wait_until(lambda: not pc.running, 15))
        self.assertEqual(mac.events, [("click", 720, 450, False, False), ("key", 1, 1 << 20)])
        self.assertEqual(pc.outcome, "Saved.")
        self.assertIn("You operate a Mac", model.calls[0]["messages"][0]["content"])
        self.assertIn("Screenshot size: 1280x800", model.calls[0]["messages"][1]["content"][0]["text"])

    def test_a_sign_in_window_in_front_stops_it(self):
        mac = FakeMac()
        mac.windows[0]["name"] = "Sign in - Bank"
        cfg = config.load()
        computer.configure(cfg, True, "auto")
        pc = computer.Computer(cfg, Model([{"action": "click", "x": 1, "y": 1, "reason": "x"}]), macdesk.Desktop(mac, Camera(), macdesk.Windows(mac)))
        pc.start("Look at the page")
        self.assertTrue(wait_until(lambda: not pc.running, 15))
        self.assertEqual(mac.events, [])
        self.assertIn("private window", pc.outcome)


if __name__ == "__main__":
    unittest.main()
