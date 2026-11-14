"""Mods: the owner's own commands, hooks, panels and status line."""
import json
import unittest

from jcc import assistant, config, mods
from jcc.chats import Chats
from tests.test_assistant_voice import AssistantCase
from tests.test_gui import GuiTestCase
from tests.helpers import EngineTestCase


class TestCommands(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.load()

    def test_a_command_stands_for_a_longer_request(self):
        mods.save_command(self.cfg, "/Standup", "What I did today", "Summarise what I did today from my notes, in three short points. $ARGUMENTS")
        self.assertEqual([c["name"] for c in mods.load(self.cfg)["commands"]], ["standup"], "the name is kept without its slash, in small letters")
        self.assertEqual(mods.expand(self.cfg, "/standup for the team"), ("Summarise what I did today from my notes, in three short points. for the team", "standup"))
        self.assertEqual(mods.expand(self.cfg, "/STANDUP"), ("Summarise what I did today from my notes, in three short points. ", "standup"))
        mods.save_command(self.cfg, "tidy", "", "Tidy this text and keep its meaning.")
        self.assertEqual(mods.expand(self.cfg, "/tidy  hello  wrld\nsecond line"), ("Tidy this text and keep its meaning.\n\nhello  wrld\nsecond line", "tidy"),
                         "with no place marked for it, what follows the name is put after the request")
        self.assertEqual(mods.expand(self.cfg, "/tidy"), ("Tidy this text and keep its meaning.", "tidy"))

    def test_anything_else_is_left_as_it_is(self):
        mods.save_command(self.cfg, "tidy", "", "Tidy this text.")
        for text in ("tidy this", "/unknown thing", "/ tidy", "what does /tidy do", "//tidy", "/tidy/now", ""):
            self.assertEqual(mods.expand(self.cfg, text), (text, ""), text)

    def test_what_is_refused(self):
        for name in ("", "two words", "-dash", "x" * 40, "ünï", "a/b", "../etc"):
            with self.assertRaises(mods.ModError, msg=name):
                mods.save_command(self.cfg, name, "", "text")
        for name in ("compact", "research", "help", "/code"):
            with self.assertRaises(mods.ModError, msg=name) as taken:
                mods.save_command(self.cfg, name, "", "text")
            self.assertIn("one of JARVIS's own commands", str(taken.exception))
        with self.assertRaises(mods.ModError):
            mods.save_command(self.cfg, "empty", "", "   ")
        self.assertEqual(mods.load(self.cfg)["commands"], [])

    def test_changing_and_removing(self):
        mods.save_command(self.cfg, "tidy", "first", "One.")
        mods.save_command(self.cfg, "tidy", "second", "Two.")
        self.assertEqual(mods.load(self.cfg)["commands"], [{"name": "tidy", "about": "second", "text": "Two."}], "saved again under the same name, it is changed")
        self.assertEqual(mods.delete_command(self.cfg, "/tidy")["commands"], [])
        self.assertEqual(mods.expand(self.cfg, "/tidy x"), ("/tidy x", ""))

    def test_a_key_pasted_into_a_command_is_not_kept(self):
        mods.save_command(self.cfg, "deploy", "", "Deploy with the key sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGH")
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz0123456789", json.dumps(mods.load(self.cfg)))

    def test_the_list_for_the_window(self):
        mods.save_command(self.cfg, "tidy", "Tidy text", "Tidy this text.")
        listed = mods.listing(self.cfg)
        self.assertEqual([c["name"] for c in listed["builtin"]][:4], ["work", "mode", "new", "research"], "the ones used most come first")
        # Every panel is a command too (the side panel holds only Files, Terminal and Browser), and nothing was dropped.
        for name in ("work", "mode", "status", "projects", "undo", "folder", "stop", "settings", "files", "terminal", "browser", "artifacts", "agents", "pair", "court",
                     "security", "routines", "activity", "efficiency", "tasks", "recall", "shared", "control", "voice", "connections", "models", "updates", "mods", "help"):
            self.assertIn(name, [c["name"] for c in listed["builtin"]])
        self.assertEqual(len({c["name"] for c in listed["builtin"]}), len(listed["builtin"]), "each name once")
        self.assertEqual(listed["commands"], [{"name": "tidy", "about": "Tidy text", "text": "Tidy this text."}])
        self.assertEqual(listed["packs"], [], "no skill pack is switched on here")
        self.assertEqual(set(listed["when"]), {"open", "answer", "job", "reminder"})
        self.assertEqual(listed["status"], {"on": False, "items": ["brain", "claude"]})

    def test_a_spoilt_file_is_read_as_far_as_it_makes_sense(self):
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        (self.cfg.state_dir / "mods.json").write_text(json.dumps({"commands": [{"name": "ok", "text": "Fine."}, {"name": "Bad Name", "text": "x"}, {"name": "empty", "text": " "}, "junk"],
                                                                  "hooks": [{"id": "zz", "when": "open", "do": "say", "text": "hi"}, {"id": "0a1b2c3d", "when": "never", "do": "say", "text": "hi"},
                                                                            {"id": "0a1b2c3d", "when": "open", "do": "toast", "text": "Good morning"}],
                                                                  "panels": [{"id": "../../x", "name": "bad"}, {"id": "11223344", "name": "Timer"}], "status": {"on": True, "items": ["clock", "nonsense"]}}), "utf-8")
        got = mods.load(self.cfg)
        self.assertEqual([c["name"] for c in got["commands"]], ["ok"])
        self.assertEqual([(h["when"], h["do"], h["text"], h["on"]) for h in got["hooks"]], [("open", "toast", "Good morning", True)])
        self.assertEqual(got["panels"], [{"id": "11223344", "name": "Timer", "online": False}])
        self.assertEqual(got["status"], {"on": True, "items": ["clock"]})
        (self.cfg.state_dir / "mods.json").write_text("not json at all", "utf-8")
        self.assertEqual(mods.load(self.cfg)["commands"], [])


class TestHooksPanelsAndStatus(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.load()

    def test_when_something_happens(self):
        made = mods.save_hook(self.cfg, "job", "say", "Your build is ready.")["hooks"]
        self.assertEqual([(h["when"], h["do"], h["text"], h["on"]) for h in made], [("job", "say", "Your build is ready.", True)])
        ident = made[0]["id"]
        self.assertFalse(mods.switch_hook(self.cfg, ident, False)["hooks"][0]["on"])
        changed = mods.save_hook(self.cfg, "job", "toast", "Build finished.", ident)["hooks"]
        self.assertEqual([(h["id"], h["do"], h["text"], h["on"]) for h in changed], [(ident, "toast", "Build finished.", False)], "changed in place; still switched off")
        mods.save_hook(self.cfg, "open", "command", "/standup for today")
        self.assertEqual(len(mods.load(self.cfg)["hooks"]), 2)
        self.assertEqual(mods.delete_hook(self.cfg, ident)["hooks"][0]["when"], "open")

    def test_what_a_hook_may_not_be(self):
        for when, do, text in (("never", "say", "x"), ("open", "run", "x"), ("open", "say", "  "), ("open", "command", "standup"), ("open", "command", "del /q C:\\")):
            with self.assertRaises(mods.ModError, msg=(when, do, text)):
                mods.save_hook(self.cfg, when, do, text)
        with self.assertRaises(mods.ModError) as endless:
            mods.save_hook(self.cfg, "answer", "command", "/standup")
        self.assertIn("without end", str(endless.exception))
        self.assertEqual(mods.load(self.cfg)["hooks"], [])
        for index in range(mods.MOST["hooks"]):
            mods.save_hook(self.cfg, "open", "toast", f"Note {index}")
        with self.assertRaises(mods.ModError):
            mods.save_hook(self.cfg, "open", "toast", "One too many")

    def test_a_page_pinned_as_a_panel(self):
        page = "<!doctype html><title>Timer</title><button>Start</button>"
        made = mods.save_panel(self.cfg, "Kitchen timer", page)
        ident = made["made"]
        self.assertEqual(made["panels"], [{"id": ident, "name": "Kitchen timer", "online": False}], "sealed from the internet unless it was allowed when pinned")
        live = mods.save_panel(self.cfg, "Weather", page, online=True)
        self.assertEqual([p["online"] for p in live["panels"]], [False, True])
        self.assertEqual(mods.save_panel(self.cfg, "Odd", page, online="yes")["panels"][-1]["online"], False, "only a plain yes")
        for extra in live["panels"][1:] + [mods.load(self.cfg)["panels"][-1]]:
            mods.delete_panel(self.cfg, extra["id"])
        self.assertEqual(mods.panel_html(self.cfg, ident), page)
        self.assertTrue((self.cfg.state_dir / "mods" / f"panel-{ident}.html").is_file(), "kept on this PC, in JARVIS's own folder")
        for bad in ("../../secrets", "0000000g", "", ident[:-1]):
            with self.assertRaises(mods.ModError, msg=bad):
                mods.panel_html(self.cfg, bad)
        with self.assertRaises(mods.ModError):
            mods.save_panel(self.cfg, "Empty", "   ")
        with self.assertRaises(mods.ModError):
            mods.save_panel(self.cfg, "Huge", "x" * (mods.PANEL_BYTES + 1))
        with self.assertRaises(mods.ModError):
            mods.save_panel(self.cfg, "", page)
        self.assertEqual(mods.delete_panel(self.cfg, ident)["panels"], [])
        self.assertFalse((self.cfg.state_dir / "mods" / f"panel-{ident}.html").exists())
        with self.assertRaises(mods.ModError):
            mods.panel_html(self.cfg, ident)

    def test_the_status_line(self):
        self.assertEqual(mods.set_status(self.cfg, True, ["clock", "brain", "clock", "nonsense"])["status"], {"on": True, "items": ["clock", "brain"]})
        self.assertEqual(mods.set_status(self.cfg, False, None)["status"], {"on": False, "items": ["clock", "brain"]})
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        (self.cfg.state_dir / "quota-claude.json").write_text(json.dumps({"windows": [{"name": "five hour", "remaining_percent": 90.4, "reset_at": 1794474599}, {"name": "seven day", "remaining_percent": 59}]}), "utf-8")
        now = mods.status_now(self.cfg, "Claude Haiku")
        self.assertEqual(now["brain"], "Claude Haiku")
        self.assertEqual([(w["name"], w["left"]) for w in now["claude"]], [("five hour", 90), ("seven day", 59)])
        self.assertNotIn("codex", now, "not read yet: left out")
        self.assertRegex(now["clock"], r"^\d\d:\d\d$")


class TestACommandInAConversation(AssistantCase):
    def test_the_chat_shows_what_was_typed_and_the_ai_gets_the_request_in_full(self):
        mods.save_command(self.cfg, "tidy", "", "Tidy this text and keep its meaning: $ARGUMENTS")
        agent = self.make([[("text", "Hello, world.")]])
        agent.look = lambda: ""
        started = agent.say("/tidy helo wrld")
        self.finish(agent)
        messages = Chats(self.cfg).get(started["chat"])["messages"]
        self.assertEqual(messages[0]["content"], "/tidy helo wrld", "the conversation keeps what was typed")
        sent = json.dumps(self.procs[0].sent)
        self.assertIn("Tidy this text and keep its meaning: helo wrld", sent)
        self.assertNotIn("/tidy", sent)
        self.assertEqual(messages[-1]["content"], "Hello, world.")

    def test_a_command_is_never_taken_for_something_jarvis_does_by_itself(self):
        mods.save_command(self.cfg, "pause", "", "Explain what pausing a film does to its frame rate.")
        agent = self.make([[("text", "It holds the last frame.")]])
        agent.look = lambda: ""
        started = agent.say("/pause")
        self.finish(agent)
        self.assertEqual(self.acted, [], "not the instant \"pause\" for the music")
        self.assertEqual(Chats(self.cfg).get(started["chat"])["messages"][-1]["content"], "It holds the last frame.")


class TestModsOverTheWire(GuiTestCase):
    def test_everything_the_tab_does(self):
        status, listed = self.req("POST", "/api/mods", {"action": "list"})
        self.assertEqual((status, listed["commands"], listed["hooks"], listed["panels"]), (200, [], [], []))
        status, got = self.req("POST", "/api/mods", {"action": "command", "name": "tidy", "about": "Tidy", "text": "Tidy this."})
        self.assertEqual((status, [c["name"] for c in got["commands"]]), (200, ["tidy"]))
        status, got = self.req("POST", "/api/mods", {"action": "command", "name": "help", "text": "x"})
        self.assertEqual(status, 400)
        self.assertIn("own commands", got["error"])
        status, got = self.req("POST", "/api/mods", {"action": "hook", "when": "job", "do": "say", "text": "Done."})
        ident = got["hooks"][0]["id"]
        self.assertEqual(self.req("POST", "/api/mods", {"action": "hook_switch", "id": ident, "on": False})[1]["hooks"][0]["on"], False)
        status, got = self.req("POST", "/api/mods", {"action": "panel", "name": "Timer", "html": "<b>Timer</b>"})
        panel = got["made"]
        self.assertEqual(self.req("POST", "/api/mods", {"action": "panel_html", "id": panel})[1], {"html": "<b>Timer</b>", "name": "Timer"})
        self.assertEqual(self.req("POST", "/api/mods", {"action": "panel_html", "id": "../x"})[0], 400)
        self.assertEqual(self.req("POST", "/api/mods", {"action": "status", "on": True, "items": ["clock"]})[1]["status"], {"on": True, "items": ["clock"]})
        status, now = self.req("POST", "/api/mods", {"action": "status_now"})
        self.assertEqual((status, set(now) >= {"brain", "clock"}), (200, True))
        self.assertEqual(self.req("POST", "/api/mods", {"action": "unpanel", "id": panel})[1]["panels"], [])
        self.assertEqual(self.req("POST", "/api/mods", {"action": "unhook", "id": ident})[1]["hooks"], [])
        self.assertEqual(self.req("POST", "/api/mods", {"action": "uncommand", "name": "tidy"})[1]["commands"], [])
        self.assertEqual(self.req("POST", "/api/mods", {"action": "explode"})[0], 400)
        self.assertEqual(self.req("POST", "/api/mods", {"action": "list"}, token=False)[0], 401)


if __name__ == "__main__":
    unittest.main()
