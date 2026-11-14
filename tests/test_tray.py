"""Tray helper: icon data and settings. The window itself is not opened here."""
import struct
import unittest
from types import SimpleNamespace

from jcc import tray


class TestTray(unittest.TestCase):
    def test_icon_is_a_valid_ico(self):
        data = tray.icon_bytes(32)
        reserved, kind, count = struct.unpack("<HHH", data[:6])
        width, height, _, _, planes, bits, size, offset = struct.unpack("<BBBBHHII", data[6:22])
        self.assertEqual((reserved, kind, count, width, height, planes, bits, offset), (0, 1, 1, 32, 32, 1, 32, 22))
        self.assertEqual(len(data), offset + size)
        header = struct.unpack("<IiiHH", data[22:38])
        self.assertEqual(header, (40, 32, 64, 1, 32))
        centre = 22 + 40 + (16 * 32 + 16) * 4
        self.assertEqual(data[centre + 3], 255, "the middle of the icon is solid")
        self.assertEqual(data[22 + 40 + 3], 0, "the corners are see-through")

    def test_settings_default_on_and_can_be_switched_off(self):
        self.assertEqual(tray.hotkeys(SimpleNamespace(raw={})), {"tray": True, "hotkey": True})
        self.assertEqual(tray.hotkeys(SimpleNamespace(raw={"desktop": {"tray": False, "hotkey": False}})),
                         {"tray": False, "hotkey": False})
        self.assertEqual(tray.hotkeys(SimpleNamespace(raw={"desktop": "bad"})), {"tray": True, "hotkey": True})

    def test_a_shortcut_another_program_owns_falls_back_to_the_next_choice(self):
        taken = {0x20, ord("D"), ord("Y"), ord("U")}          # Ctrl+Alt+Space and every dictation choice are already in use elsewhere
        tried = []
        active = tray.claim(lambda ident, key: tried.append(key) or key not in taken)
        self.assertEqual(active, {tray.HOTKEY_OPEN: "Ctrl+Alt+J", tray.HOTKEY_STOP: "Ctrl+Alt+Backspace", tray.HOTKEY_TALK: "Ctrl+Alt+T"})
        self.assertNotIn(tray.HOTKEY_DICTATE, active, "with every choice taken the shortcut is simply left out")
        self.assertEqual(tray.claim(lambda ident, key: True)[tray.HOTKEY_TALK], "Ctrl+Alt+Space", "the usual shortcut is used when it is free")


if __name__ == "__main__":
    unittest.main()
