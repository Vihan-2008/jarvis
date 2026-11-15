"""The first command a new user gives ("open calculator", "open notepad") is done by JARVIS itself, at once, even when
it is typed before JARVIS has read the list of installed apps (a fresh install, and someone quick)."""
import json
import unittest

from jcc import quick, reminders, system
from tests.helpers import EngineTestCase


class TheFirstCommand(EngineTestCase):
    def setUp(self):
        super().setUp()
        from jcc import config
        self.cfg = config.load()
        self.acted, self.listed = [], 0

        def start_menu():                       # what Get-StartApps answers on a new Windows PC
            self.listed += 1
            return json.dumps([{"Name": "Calculator", "AppID": "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"},
                               {"Name": "Notepad", "AppID": "Microsoft.WindowsNotepad_8wekyb3d8bbwe!App"}])
        self.apps = quick.Apps(self.cfg, runner=start_menu)
        self.quick = quick.Quick(self.cfg, self.apps, reminders.Reminders(self.cfg), lambda kind, value=None: self.acted.append((kind, value)))

    def test_open_calculator_before_the_app_list_was_read(self):
        self.assertEqual(self.apps.items, {}, "(nothing read yet: a fresh install)")
        result = self.quick.handle("open calculator")
        self.assertIsNotNone(result, "JARVIS opened it itself instead of handing it to an AI")
        self.assertEqual(result.say, "Opening Calculator.")
        self.assertEqual(self.acted, [("app", "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App")])
        self.assertEqual(self.listed, 1)
        self.quick.handle("open calculator")
        self.assertEqual(self.listed, 1, "the list is read once, not for every command")

    def test_an_app_that_is_not_there_is_looked_for_once(self):
        self.apps.runner = lambda: (setattr(self, "listed", self.listed + 1), "[]")[1]
        self.assertIsNone(self.quick.handle("open flight simulator"))
        self.assertIsNone(self.quick.handle("open flight simulator"))
        self.assertEqual(self.listed, 1, "an empty list is not read again and again, holding every command up")

    @unittest.skipIf(system.kind() == "linux", "Linux has no Notepad")
    def test_notepad_opens_even_where_the_start_menu_does_not_list_it(self):
        self.assertEqual(quick.FALLBACK["notepad"], ["notepad.exe"])
        self.assertEqual(quick.MAC_BUILT_IN[("notepad.exe",)], ["open", "-a", "TextEdit"])
        self.apps.runner = lambda: "[]"                       # (Windows Server: no Notepad in the Start menu)
        result = self.quick.handle("open notepad")
        self.assertEqual((result.say, self.acted), ("Opening Notepad.", [("run", ["notepad.exe"])]))




if __name__ == "__main__":
    unittest.main()
