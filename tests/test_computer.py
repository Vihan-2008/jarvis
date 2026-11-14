"""Computer control, tested with a fake screen and a fake model. No real mouse, keyboard or network."""
import json
import struct
import time
import unittest
import zlib

from jcc import computer, config
from tests.helpers import EngineTestCase


class FakeDesktop:
    def __init__(self, title="Untitled - Notepad"):
        self.title, self.done, self.shots, self.scale = title, [], 0, 1.0

    def window_title(self):
        return self.title

    def capture(self):
        self.shots += 1
        return 4, 2, computer.png(4, 2, bytes(24))

    def perform(self, step):
        self.done.append(step)


class Model:
    """Returns the queued steps one by one and records what it was sent."""

    def __init__(self, steps):
        self.steps, self.calls = list(steps), []

    def __call__(self, url, headers, body):
        self.calls.append(body)
        step = self.steps.pop(0) if self.steps else {"action": "done", "reason": "Nothing left."}
        return 200, {"choices": [{"message": {"content": json.dumps(step)}}], "usage": {"total_tokens": 900}}


def wait_until(check, seconds=6):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if check():
            return True
        time.sleep(0.03)
    return False


class TestComputerControl(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.load()
        self._sleep = computer.time.sleep
        computer.time.sleep = lambda seconds: self._sleep(min(seconds, 0.01))

    def tearDown(self):
        computer.time.sleep = self._sleep
        super().tearDown()

    def make(self, steps, title="Untitled - Notepad"):
        self.desktop, self.model = FakeDesktop(title), Model(steps)
        return computer.Computer(self.cfg, self.model, self.desktop)

    def test_off_by_default_and_task_guard(self):
        pc = self.make([])
        self.assertEqual(computer.settings(self.cfg), {"enabled": False, "mode": "ask"})
        with self.assertRaises(ValueError):
            pc.start("Open Notepad and write a shopping list")
        computer.configure(self.cfg, True, "ask")
        for task in ("Log in to my bank and check the balance", "Deploy the app to the server",
                     "Open the trading dashboard and buy shares", "Type my password into the form", "x"):
            with self.assertRaises(ValueError, msg=task):
                pc.start(task)
        self.assertEqual(self.desktop.shots, 0)
        with self.assertRaises(ValueError):
            computer.configure(self.cfg, "yes", "ask")

    def test_ask_mode_waits_for_each_approval(self):
        computer.configure(self.cfg, True, "ask")
        pc = self.make([{"action": "click", "x": 2, "y": 1, "reason": "Open the menu."},
                        {"action": "type", "text": "milk, eggs", "reason": "Write the list."},
                        {"action": "done", "reason": "The list is written."}])
        pc.start("Open Notepad and write a shopping list")
        self.assertTrue(wait_until(lambda: pc.proposal))
        self._sleep(0.2)
        self.assertEqual(self.desktop.done, [], "nothing may happen before the owner approves")
        self.assertEqual(pc.status()["proposal"]["label"], "Click at (2, 1)")
        pc.decide("approve")
        self.assertTrue(wait_until(lambda: pc.proposal and pc.proposal["action"] == "type"))
        self.assertEqual([s["action"] for s in self.desktop.done], ["click"])
        pc.decide("skip")
        self.assertTrue(wait_until(lambda: not pc.running))
        self.assertEqual([s["action"] for s in self.desktop.done], ["click"])
        self.assertEqual(pc.outcome, "The list is written.")
        sent = self.model.calls[0]["messages"][1]["content"]
        self.assertTrue(sent[1]["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertIn("shopping list", sent[0]["text"])

    def test_auto_mode_runs_and_stops_at_limits(self):
        computer.configure(self.cfg, True, "auto")
        pc = self.make([{"action": "scroll", "amount": -3, "reason": "Look further down."}] * 100)
        pc.start("Scroll through the open document")
        self.assertTrue(wait_until(lambda: not pc.running, 15))
        self.assertEqual(len(self.desktop.done), computer.MAX_STEPS)
        self.assertIn("limit", pc.outcome)

    def test_stop_and_emergency_file(self):
        computer.configure(self.cfg, True, "ask")
        pc = self.make([{"action": "click", "x": 1, "y": 1, "reason": "Go."}] * 5)
        pc.start("Click the first button in the open window")
        self.assertTrue(wait_until(lambda: pc.proposal))
        pc.decide("stop")
        self.assertTrue(wait_until(lambda: not pc.running))
        self.assertEqual(self.desktop.done, [])
        computer.configure(self.cfg, True, "auto")
        pc = self.make([{"action": "wait", "reason": "Loading."}] * 50)
        pc.start("Wait for the page in the open window to load")
        (self.cfg.state_dir / "computer-stop").write_text("1", "utf-8")
        self.assertTrue(wait_until(lambda: not pc.running))
        self.assertIn("emergency", pc.outcome)

    def test_private_window_in_front_blocks_everything(self):
        computer.configure(self.cfg, True, "auto")
        pc = self.make([{"action": "click", "x": 1, "y": 1, "reason": "Go."}], title="Sign in - Your Bank")
        pc.start("Click the first button in the open window")
        self.assertTrue(wait_until(lambda: not pc.running))
        self.assertEqual((self.desktop.done, self.desktop.shots, self.model.calls), ([], 0, []))
        self.assertIn("private window", pc.outcome)

    def test_model_replies_are_validated(self):
        ok = computer.parse_action('{"action":"click","x":10,"y":20,"reason":"ok"}', 100, 100)
        self.assertEqual((ok["action"], ok["x"], ok["y"]), ("click", 10, 20))
        for reply in ('{"action":"click","x":500,"y":20}', '{"action":"type","text":"gsk_abcdefghij1234567890abcd"}',
                      '{"action":"key","keys":"win+r"}', '{"action":"key","keys":"ctrl+alt+delete"}',
                      '{"action":"run_program","text":"format c:"}', "not json at all", '{"action":"type","text":""}'):
            self.assertEqual(computer.parse_action(reply, 100, 100)["action"], "need_user", reply)
        self.assertEqual(computer.parse_action('{"action":"key","keys":"Ctrl+S"}', 9, 9)["keys"], "ctrl+s")
        self.assertEqual(computer.parse_action('{"action":"scroll","amount":-99}', 9, 9)["amount"], -15)

    def test_png_is_valid(self):
        data = computer.png(3, 2, bytes(range(18)))
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", data[16:24]), (3, 2))
        start = data.index(b"IDAT") + 4
        size = struct.unpack(">I", data[start - 8:start - 4])[0]
        self.assertEqual(len(zlib.decompress(data[start:start + size])), 2 * (1 + 9))


if __name__ == "__main__":
    unittest.main()
