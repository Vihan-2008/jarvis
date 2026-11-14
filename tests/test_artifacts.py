"""The library of artifacts: everything that has been made, from every chat and by hand, each with its versions."""
import json
import time
from pathlib import Path

from jcc import artifacts, config
from jcc.chats import Chats
from tests.helpers import EngineTestCase
from tests.test_gui import GuiTestCase

F = "```"
PAGE = "\n".join(["<!doctype html>", "<html>", "<head><title>Bakery home</title></head>", "<body>", "<h1>Fresh bread</h1>", "</body>", "</html>"])
PAGE2 = PAGE.replace("Fresh bread", "Fresh bread every morning")
PAGE3 = PAGE.replace("Fresh bread", "Bread, cakes and coffee")
DOC = "\n".join(["# Trip plan", "", "Day one: the fort.", "", "Day two: the market.", "", "- pack water", "- book the train", "", "Costs are in the sheet."])
SHEET = "Day,Loaves\nMon,40\nTue,55"


def reply(code, lang="html", name=""):
    return ("File: " + name + "\n" if name else "") + F + lang + "\n" + code + "\n" + F


class LibraryCase(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.load()
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        self.chats = Chats(self.cfg)

    def chat(self, *replies, title="A chat"):
        made = self.chats.create(title)
        for text in replies:
            self.chats.update(made["id"], message={"role": "user", "content": "Make it."})
            self.chats.update(made["id"], message={"role": "assistant", "content": text, "status": "done"})
        return made["id"]

    def listed(self, **how):
        artifacts.sync(self.cfg)
        return artifacts.listing(self.cfg, **how)


class TestWhatAReplyMade(LibraryCase):
    def test_the_library_reads_a_reply_as_the_window_does(self):
        """The same examples are read by the window in tests/artifacts.test.js: the two must agree on every one."""
        cases = json.loads((Path(__file__).parent / "fixtures" / "artifacts.json").read_text("utf-8"))
        self.assertGreater(len(cases), 25)
        for case in cases:
            got = [{"kind": b["kind"], "name": b["name"], "lines": len(b["code"].split("\n"))} for b in artifacts.found_in(case["text"])]
            self.assertEqual(got, case["made"], case["why"])

    def test_the_text_of_a_block_is_kept_exactly(self):
        code = "<svg>\n  <title>Sun</title>\n\n  <circle r=\"3\"/>\n  <!-- a comment -->\n</svg>\n"
        self.assertEqual(artifacts.found_in(F + "svg\n" + code + "\n" + F)[0]["code"], code)
        self.assertEqual(artifacts.found_in("no blocks here"), [])
        self.assertEqual(artifacts.found_in(None), [])


class TestWhatTheChatsHaveMade(LibraryCase):
    def test_every_chat_is_read_and_a_later_block_of_the_same_name_is_a_version(self):
        one = self.chat("Here.\n\n" + reply(PAGE, name="Home"), "Changed.\n\n" + reply(PAGE2, name="home"))
        two = self.chat(reply(DOC, "markdown"), "And a table:\n\n" + reply(SHEET, "csv", "Sales"))
        rows = self.listed()
        self.assertEqual({(r["title"], r["kind"], r["versions"], r["chat"]) for r in rows},
                         {("Home", "page", 2, one), ("Trip plan", "document", 1, two), ("Sales", "sheet", 1, two)})
        self.assertTrue(all(not r["yours"] and not r["starred"] and "key" not in r for r in rows))
        home = artifacts.get(self.cfg, next(r["id"] for r in rows if r["title"] == "Home"))
        self.assertEqual([(v["n"], v["by"], v["size"]) for v in home["versions"]], [(1, "jarvis", len(PAGE)), (2, "jarvis", len(PAGE2))])
        self.assertEqual(home["code"], PAGE2, "what is shown is the newest")
        self.assertEqual(artifacts.version(self.cfg, home["id"], 1)["code"], PAGE)
        self.assertNotIn("code", home["versions"][0], "an earlier version's text is asked for by itself")

    def test_reading_again_adds_nothing_and_a_new_reply_adds_one_version(self):
        cid = self.chat(reply(PAGE, name="Home"))
        first = self.listed()
        self.assertEqual(self.listed(), first, "nothing has changed, so nothing is added")
        self.chats.update(cid, message={"role": "assistant", "content": reply(PAGE, name="Home"), "status": "done"})
        self.assertEqual(self.listed()[0]["versions"], 1, "the same text again is not a new version")
        self.chats.update(cid, message={"role": "assistant", "content": reply(PAGE2, name="Home"), "status": "done"})
        self.assertEqual(self.listed()[0]["versions"], 2)
        self.chats.update(cid, message={"role": "assistant", "content": reply(PAGE, name="Home"), "status": "done"})
        got = artifacts.get(self.cfg, self.listed()[0]["id"])
        self.assertEqual(len(got["versions"]), 3, "going back to earlier words in the chat is a version too")
        self.assertEqual(got["code"], PAGE)

    def test_what_the_owner_typed_is_not_something_jarvis_made(self):
        made = self.chats.create("Mine")
        self.chats.update(made["id"], message={"role": "user", "content": reply(PAGE, name="Pasted")})
        self.assertEqual(self.listed(), [])

    def test_a_private_chat_is_never_read_and_a_deleted_chats_things_are_not_listed(self):
        private = self.chat(reply(PAGE, name="Secret plans"))
        kept = self.chat(reply(DOC, "markdown"))
        self.assertEqual(len(self.listed()), 2)
        note = self.vault / "Conversations" / (private + ".md")
        note.write_text(note.read_text("utf-8").replace("---\n", "---\nprivate: true\n", 1), "utf-8")
        self.assertEqual([r["title"] for r in self.listed()], ["Trip plan"], "what was read before it became private is taken out again")
        self.assertNotIn("Secret plans", json.dumps(artifacts._index(self.cfg)))
        self.chats.set_deleted(kept, True)
        self.assertEqual(self.listed(), [])
        self.chats.set_deleted(kept, False)
        self.assertEqual([r["title"] for r in self.listed()], ["Trip plan"], "the chat is back, and so is what it made")

    def test_many_chats_are_caught_up_with_a_few_at_a_time(self):
        for n in range(5):
            self.chat(reply(PAGE.replace("Bakery home", f"Page {n}")))
        self.assertTrue(artifacts.sync(self.cfg, most=2)["more"])
        self.assertEqual(len(artifacts.listing(self.cfg)), 2)
        self.assertTrue(artifacts.sync(self.cfg, most=2)["more"])
        self.assertFalse(artifacts.sync(self.cfg, most=2)["more"])
        self.assertEqual(len(artifacts.listing(self.cfg)), 5)
        self.assertFalse(artifacts.sync(self.cfg)["more"])

    def test_one_made_while_the_window_is_open_is_found_at_once(self):
        cid = self.chat(reply(PAGE, name="Home"))
        found = artifacts.find(self.cfg, cid, "page", "HOME")
        self.assertEqual((found["title"], found["chat"], found["code"]), ("Home", cid, PAGE))
        self.assertIsNone(artifacts.find(self.cfg, cid, "page", "Other"))
        self.assertIsNone(artifacts.find(self.cfg, "../../x", "page", "Home"))
        self.assertIsNone(artifacts.find(self.cfg, "20200101-000000-abcd", "page", "Home"), "a chat that is not there")

    def test_which_version_a_text_is(self):
        cid = self.chat(reply(PAGE, name="Home"), reply(PAGE2, name="Home"), reply(PAGE, name="Home"))
        ident = artifacts.find(self.cfg, cid, "page", "home")["id"]
        self.assertEqual(artifacts.locate(self.cfg, ident, PAGE), 2, "the newest version that holds it")
        self.assertEqual(artifacts.locate(self.cfg, ident, PAGE2.replace("\n", "\r\n")), 1, "line endings do not matter")
        self.assertIsNone(artifacts.locate(self.cfg, ident, PAGE3))
        self.assertIsNone(artifacts.locate(self.cfg, "art-20200101-000000-abcd", PAGE))
        self.assertIsNone(artifacts.locate(self.cfg, ident, None))

    def test_what_a_chat_made_stays_when_the_chat_itself_is_gone(self):
        cid = self.chat(reply(DOC, "markdown"))
        self.assertEqual(len(self.listed()), 1)
        (self.vault / "Conversations" / (cid + ".md")).unlink()
        self.assertEqual([r["title"] for r in self.listed()], ["Trip plan"], "it is all that is left of that chat")


class TestWhatItsOwnerDoes(LibraryCase):
    def test_something_made_by_hand_and_its_changes(self):
        made = artifacts.save(self.cfg, title="  Ideas   board ", kind="whiteboard", code='{"items": []}')
        self.assertRegex(made["id"], r"^art-\d{8}-\d{6}-[0-9a-f]{4}$")
        self.assertEqual((made["title"], made["kind"], made["lang"], made["chat"], len(made["versions"])), ("Ideas board", "whiteboard", "whiteboard", "", 1))
        again = artifacts.save(self.cfg, made["id"], code='{"items": [1]}', note="a first shape")
        self.assertEqual([(v["n"], v["by"], v["note"]) for v in again["versions"]], [(1, "you", ""), (2, "you", "a first shape")])
        same = artifacts.save(self.cfg, made["id"], code='{"items": [1]}')
        self.assertEqual(len(same["versions"]), 2, "saving the same again adds nothing")
        row = self.listed(only="yours")[0]
        self.assertEqual((row["title"], row["yours"], row["versions"]), ("Ideas board", True, 2))

    def test_work_in_progress_keeps_one_version_up_to_date(self):
        made = artifacts.save(self.cfg, title="Notes", kind="document", code="one")
        for text in ("one two", "one two three"):
            made = artifacts.save(self.cfg, made["id"], code=text, amend=True)
        self.assertEqual((len(made["versions"]), made["code"]), (1, "one two three"), "typing does not fill the history")
        path = self.cfg.state_dir / "artifacts" / (made["id"] + ".json")
        saved = json.loads(path.read_text("utf-8"))
        saved["versions"][-1]["at"] = time.time() - artifacts.WORKING - 5
        path.write_text(json.dumps(saved), "utf-8")
        later = artifacts.save(self.cfg, made["id"], code="a new sitting", amend=True)
        self.assertEqual(len(later["versions"]), 2, "after a while it is a new version")

    def test_a_change_to_what_jarvis_made_is_the_owners_version_and_never_replaces_jarviss(self):
        cid = self.chat(reply(SHEET, "csv", "Sales"))
        ident = self.listed()[0]["id"]
        mine = artifacts.save(self.cfg, ident, code=SHEET + "\nWed,60", amend=True)
        self.assertEqual([(v["n"], v["by"]) for v in mine["versions"]], [(1, "jarvis"), (2, "you")], "work in progress never writes over a version that is not its owner's")
        self.assertEqual(artifacts.version(self.cfg, ident, 1)["code"], SHEET)
        self.chats.update(cid, message={"role": "assistant", "content": reply(SHEET + "\nThu,70", "csv", "Sales"), "status": "done"})
        got = artifacts.get(self.cfg, self.listed()[0]["id"])
        self.assertEqual([(v["n"], v["by"]) for v in got["versions"]], [(1, "jarvis"), (2, "you"), (3, "jarvis")])

    def test_going_back_adds_the_old_version_as_the_newest_and_tells_the_chat(self):
        cid = self.chat(reply(PAGE, name="Home"), reply(PAGE2, name="Home"), reply(PAGE3, name="Home"))
        ident = self.listed()[0]["id"]
        back = artifacts.restore(self.cfg, ident, 1)
        self.assertTrue(back["told"])
        self.assertEqual([(v["n"], v["by"], v["note"]) for v in back["versions"]],
                         [(1, "jarvis", ""), (2, "jarvis", ""), (3, "jarvis", ""), (4, "you", "Version 1, brought back")], "nothing is lost")
        self.assertEqual(back["code"], PAGE)
        last = self.chats.get(cid)["messages"][-1]
        self.assertEqual((last["role"], last.get("restored")), ("assistant", True))
        self.assertIn("The owner went back to version 1 of “Home”. It is the current version again.", last["content"])
        self.assertEqual(artifacts.found_in(last["content"])[0]["code"], PAGE, "in the form the chat reads its own work in")
        self.assertEqual(self.listed()[0]["versions"], 4, "reading the chat again does not bring the same version in twice")
        self.chats.update(cid, message={"role": "assistant", "content": reply(PAGE2, name="Home"), "status": "done"})
        self.assertEqual(self.listed()[0]["versions"], 5, "and the chat carries on from there")
        for bad in (99, 5, None, "1"):
            with self.assertRaises(artifacts.ArtifactError):
                artifacts.restore(self.cfg, ident, bad)

    def test_going_back_to_what_the_current_version_already_holds_is_refused(self):
        self.chat(reply(PAGE, name="Home"), reply(PAGE2, name="Home"), reply(PAGE, name="Home"))
        ident = self.listed()[0]["id"]
        with self.assertRaises(artifacts.ArtifactError) as told:
            artifacts.restore(self.cfg, ident, 1)
        self.assertIn("already", str(told.exception))
        self.assertEqual(len(artifacts.get(self.cfg, ident)["versions"]), 3)

    def test_something_made_by_hand_goes_back_without_a_chat(self):
        made = artifacts.save(self.cfg, title="Notes", kind="document", code="first")
        artifacts.save(self.cfg, made["id"], code="second")
        back = artifacts.restore(self.cfg, made["id"], 1)
        self.assertEqual((back["told"], back["code"], len(back["versions"])), (False, "first", 3))

    def test_a_name_a_star_and_the_search(self):
        self.chat(reply(PAGE, name="Home"), title="one")
        self.chat(reply(DOC, "markdown"), title="two")
        rows = {r["title"]: r for r in self.listed()}
        artifacts.star(self.cfg, rows["Home"]["id"], True)
        self.assertEqual([r["title"] for r in self.listed(only="starred")], ["Home"])
        renamed = artifacts.rename(self.cfg, rows["Home"]["id"], "  The shop's   front page ")
        self.assertEqual(renamed["title"], "The shop's front page")
        with self.assertRaises(artifacts.ArtifactError):
            artifacts.rename(self.cfg, rows["Home"]["id"], "   ")
        self.assertEqual([r["title"] for r in self.listed(query="front SHOP")], ["The shop's front page"])
        self.assertEqual([r["title"] for r in self.listed(query="market")], ["Trip plan"], "what is in it is searched too")
        self.assertEqual([r["title"] for r in self.listed(kind="document")], ["Trip plan"])
        self.assertEqual(self.listed(query="nothing like this"), [])
        # A new name is its owner's; the chat still knows the thing by the name it gave it.
        cid = rows["Home"]["chat"]
        self.chats.update(cid, message={"role": "assistant", "content": reply(PAGE2, name="Home"), "status": "done"})
        self.assertEqual([(r["title"], r["versions"]) for r in self.listed(kind="page")], [("The shop's front page", 2)])

    def test_what_is_removed_comes_back_only_with_a_newer_version(self):
        cid = self.chat(reply(PAGE, name="Home"))
        ident = self.listed()[0]["id"]
        self.assertEqual(artifacts.remove(self.cfg, ident), {"removed": ident})
        self.assertEqual(self.listed(), [])
        self.chats.update(cid, message={"role": "user", "content": "thanks"})
        self.assertEqual(self.listed(), [], "reading the chat again does not bring it back")
        self.assertIsNone(artifacts.find(self.cfg, cid, "page", "Home"))
        with self.assertRaises(artifacts.ArtifactError):
            artifacts.get(self.cfg, ident)
        self.chats.update(cid, message={"role": "assistant", "content": reply(PAGE2, name="Home"), "status": "done"})
        rows = self.listed()
        self.assertEqual([(r["title"], r["versions"]) for r in rows], [("Home", 1)], "a newer version from the chat is a new thing")
        self.assertEqual(artifacts.get(self.cfg, rows[0]["id"])["code"], PAGE2)

    def test_what_is_refused(self):
        for how in ({"kind": "virus", "code": "x"}, {"kind": "document", "code": "   "}, {"kind": "document", "code": "x" * (artifacts.LONGEST + 1)}):
            with self.assertRaises(artifacts.ArtifactError, msg=str(how)[:60]):
                artifacts.save(self.cfg, **how)
        for bad in ("", "../../x", "art-1", "art-20261114-010101-zzzz", "art-20261114-010101-abcd"):
            for act in (artifacts.get, lambda c, i: artifacts.version(c, i, 1), lambda c, i: artifacts.save(c, i, code="x"), artifacts.remove,
                        lambda c, i: artifacts.star(c, i, True), lambda c, i: artifacts.rename(c, i, "x"), lambda c, i: artifacts.restore(c, i, 1)):
                if bad == "" and act is not artifacts.get:
                    continue                           # (an empty id to save means: something new)
                with self.assertRaises(artifacts.ArtifactError, msg=bad):
                    act(self.cfg, bad)
        self.assertEqual(list((self.cfg.state_dir / "artifacts").glob("*.json")) if (self.cfg.state_dir / "artifacts").exists() else [], [])

    def test_a_kind_and_its_language_are_kept_true_to_each_other(self):
        self.assertEqual(artifacts.save(self.cfg, kind="sheet", lang="HTML", code="a,b\n1,2")["lang"], "csv")
        self.assertEqual(artifacts.save(self.cfg, kind="page", lang="whiteboard", code="<p>x</p>")["lang"], "html")
        self.assertEqual(artifacts.save(self.cfg, kind="app", lang="tsx", code="const A = 1")["lang"], "tsx")
        self.assertEqual(artifacts.save(self.cfg, kind="data", code="{}")["lang"], "chart")

    def test_a_key_is_hidden_before_anything_is_written(self):
        secret = "sk-ant-api03-" + "a" * 90
        made = artifacts.save(self.cfg, title="Config " + secret, kind="document", code="The key is " + secret)
        text = "".join(p.read_text("utf-8") for p in (self.cfg.state_dir / "artifacts").glob("*.json"))
        self.assertNotIn(secret, text)
        self.assertNotIn(secret, json.dumps(artifacts.get(self.cfg, made["id"])))

    def test_the_list_is_made_again_from_the_files_if_it_is_lost_or_damaged(self):
        self.chat(reply(PAGE, name="Home"))
        artifacts.save(self.cfg, title="Board", kind="whiteboard", code="{}")
        before = self.listed()
        index = self.cfg.state_dir / "artifacts" / "index.json"
        index.write_text("{ not json", "utf-8")
        self.assertEqual(artifacts.listing(self.cfg), before)
        index.unlink()
        self.assertEqual(artifacts.listing(self.cfg), before)

    def test_a_long_history_keeps_where_it_began(self):
        made = artifacts.save(self.cfg, title="Notes", kind="document", code="version 1")
        keep, artifacts.VERSIONS = artifacts.VERSIONS, 4
        try:
            for n in range(2, 8):
                made = artifacts.save(self.cfg, made["id"], code=f"version {n}")
        finally:
            artifacts.VERSIONS = keep
        self.assertEqual([v["n"] for v in made["versions"]], [1, 5, 6, 7])
        self.assertEqual(artifacts.version(self.cfg, made["id"], 1)["code"], "version 1")


class TestWhatAnIdCannotReach(LibraryCase):
    """What was wrong: a deleted chat's things were only left out of the list, and a chat marked private was only taken
    out the next time the library caught up. Whoever still had the id of one (an open panel, an old link, a guess)
    could read it, every version of it, change it and go back in its history.

    How it was shown: the id of a page was noted, its chat deleted (or marked private), and the page asked for by
    that id: it came back whole. Now it is answered exactly as an id that was never there."""

    def each_way_in(self, ident):
        return {"get": lambda: artifacts.get(self.cfg, ident), "version": lambda: artifacts.version(self.cfg, ident, 1),
                "save": lambda: artifacts.save(self.cfg, ident, code=PAGE3), "amend": lambda: artifacts.save(self.cfg, ident, code=PAGE3, amend=True),
                "restore": lambda: artifacts.restore(self.cfg, ident, 1), "rename": lambda: artifacts.rename(self.cfg, ident, "Mine now"),
                "star": lambda: artifacts.star(self.cfg, ident, True), "remove": lambda: artifacts.remove(self.cfg, ident)}

    def refused(self, ident, why):
        never = "art-20200101-000000-abcd"
        with self.assertRaises(artifacts.ArtifactError) as unknown:
            artifacts.get(self.cfg, never)
        for name, ask in self.each_way_in(ident).items():
            with self.assertRaises(artifacts.ArtifactError, msg=name + ": " + why) as told:
                ask()
            self.assertEqual(str(told.exception), str(unknown.exception), name + ": answered as an id that was never there")
        self.assertIsNone(artifacts.locate(self.cfg, ident, PAGE), why)

    def test_a_deleted_chats_things_cannot_be_had_by_their_id(self):
        cid = self.chat(reply(PAGE, name="Home"), reply(PAGE2, name="Home"))
        ident = artifacts.find(self.cfg, cid, "page", "home")["id"]
        before = json.dumps(artifacts._load(self.cfg, ident))
        self.chats.set_deleted(cid, True)
        self.refused(ident, "its chat is deleted")
        self.assertIsNone(artifacts.find(self.cfg, cid, "page", "home"), "nor by asking for it through its chat")
        self.assertEqual(json.dumps(artifacts._load(self.cfg, ident)), before, "and nothing of it was changed by trying")
        self.assertEqual(self.listed(), [])
        self.chats.set_deleted(cid, False)
        self.assertEqual(artifacts.get(self.cfg, ident)["code"], PAGE2, "the chat is back, and so is what it made, with its history")
        self.assertEqual(artifacts.version(self.cfg, ident, 1)["code"], PAGE)

    def test_a_chat_marked_private_shuts_its_things_at_once_not_at_the_next_catch_up(self):
        cid = self.chat(reply(PAGE, name="Secret plans"))
        ident = artifacts.find(self.cfg, cid, "page", "secret plans")["id"]
        note = self.vault / "Conversations" / (cid + ".md")
        note.write_text(note.read_text("utf-8").replace("---\n", "---\nprivate: true\n", 1), "utf-8")
        self.refused(ident, "its chat is private")                       # (no catching up has run in between)
        self.assertEqual(artifacts.listing(self.cfg), [], "and it is not listed, before any catching up")
        self.assertIsNone(artifacts.find(self.cfg, cid, "page", "secret plans"))

    def test_the_owners_own_change_to_a_private_chats_thing_is_kept_but_not_shown_while_it_is_private(self):
        cid = self.chat(reply(PAGE, name="Home"))
        ident = artifacts.find(self.cfg, cid, "page", "home")["id"]
        artifacts.save(self.cfg, ident, code=PAGE3)
        note = self.vault / "Conversations" / (cid + ".md")
        text = note.read_text("utf-8")
        note.write_text(text.replace("---\n", "---\nprivate: true\n", 1), "utf-8")
        self.assertEqual(self.listed(), [], "what came from a private chat is not shown, their own change to it included")
        self.refused(ident, "its chat is private")
        self.assertEqual(artifacts._load(self.cfg, ident)["versions"][-1]["code"], PAGE3, "their work is kept, not thrown away")
        note.write_text(text, "utf-8")
        self.assertEqual(artifacts.get(self.cfg, ident)["code"], PAGE3, "no longer private: it is theirs to see again")
        self.assertEqual([r["title"] for r in self.listed()], ["Home"])

    def test_a_chat_kept_out_of_an_assistants_context_is_private_by_its_id_as_well(self):
        """The list of chats left such a chat out, but asking for it by its id handed it over."""
        cid = self.chat(reply(PAGE, name="Home"))
        note = self.vault / "Conversations" / (cid + ".md")
        note.write_text(note.read_text("utf-8").replace("---\n", "---\nai_context: exclude\n", 1), "utf-8")
        self.assertNotIn(cid, [row["id"] for row in self.chats.list()])
        with self.assertRaises(ValueError):
            self.chats.get(cid)
        self.assertTrue(self.chats.withheld(cid))
        self.assertIsNone(artifacts.find(self.cfg, cid, "page", "home"))
        self.assertEqual(self.listed(), [])

    def test_something_made_by_hand_and_a_chat_that_is_simply_gone_are_not_shut(self):
        made = artifacts.save(self.cfg, title="Board", kind="whiteboard", code='{"items": []}')
        self.assertEqual(artifacts.get(self.cfg, made["id"])["title"], "Board")
        cid = self.chat(reply(DOC, "markdown"))
        ident = self.listed()[0]["id"]
        (self.vault / "Conversations" / (cid + ".md")).unlink()
        self.assertEqual(artifacts.get(self.cfg, ident)["code"], DOC, "it is all that is left of that chat")
        self.assertFalse(self.chats.withheld(cid))
        self.assertFalse(self.chats.withheld("../../etc"))
        self.assertFalse(self.chats.is_deleted("../../etc"))


class TestTheAddress(GuiTestCase):
    def call(self, **body):
        return self.req("POST", "/api/artifacts", body)

    def test_an_id_from_a_deleted_or_private_chat_is_answered_as_one_that_was_never_there(self):
        chats = Chats(self.state.cfg)
        made = chats.create("A chat")
        chats.update(made["id"], message={"role": "assistant", "content": reply(PAGE, name="Home"), "status": "done"})
        found = self.call(action="find", chat=made["id"], kind="page", name="home", code=PAGE)[1]["found"]
        ident = found["id"]
        never = self.call(action="get", id="art-20200101-000000-abcd")
        chats.set_deleted(made["id"], True)
        for body in ({"action": "get", "id": ident}, {"action": "version", "id": ident, "n": 1}, {"action": "save", "id": ident, "code": PAGE3},
                     {"action": "restore", "id": ident, "n": 1}, {"action": "rename", "id": ident, "title": "x"}, {"action": "star", "id": ident, "on": True},
                     {"action": "remove", "id": ident}):
            got = self.call(**body)
            self.assertEqual(got, never, body["action"])
            self.assertNotIn("Fresh bread", json.dumps(got))
        self.assertEqual(self.call(action="find", chat=made["id"], kind="page", name="home", code=PAGE)[1], {"found": None, "at": None})
        self.assertEqual(self.call(action="list")[1]["items"], [])
        chats.set_deleted(made["id"], False)
        self.assertEqual(self.call(action="get", id=ident)[1]["code"], PAGE)

    def test_the_library_over_the_wire(self):
        status, got = self.call(action="list")
        self.assertEqual((status, got["items"], got["more"]), (200, [], False))
        self.assertEqual(got["kinds"]["whiteboard"], "Whiteboard")
        status, made = self.call(action="save", title="Board", kind="whiteboard", code='{"items": []}')
        self.assertEqual((status, made["title"]), (200, "Board"))
        ident = made["id"]
        self.assertEqual(self.call(action="save", id=ident, code='{"items": [1]}')[1]["versions"][-1]["n"], 2)
        self.assertEqual(self.call(action="version", id=ident, n=1)[1]["code"], '{"items": []}')
        self.assertTrue(self.call(action="star", id=ident, on=True)[1]["starred"])
        self.assertEqual(self.call(action="rename", id=ident, title="Ideas")[1]["title"], "Ideas")
        self.assertEqual(self.call(action="restore", id=ident, n=1)[1]["code"], '{"items": []}')
        self.assertEqual([(r["title"], r["versions"], r["starred"]) for r in self.call(action="list", only="starred")[1]["items"]], [("Ideas", 3, True)])
        self.assertEqual(self.call(action="list", only="nonsense")[1]["items"][0]["title"], "Ideas", "an unknown filter is no filter")
        self.assertEqual(self.call(action="find", chat="20200101-000000-abcd", kind="page", name="x", code="y")[1], {"found": None, "at": None})
        self.assertEqual(self.call(action="remove", id=ident)[1], {"removed": ident})
        self.assertEqual(self.call(action="list")[1]["items"], [])

    def test_what_is_refused_over_the_wire(self):
        for body in ({"action": "get", "id": "../../secrets"}, {"action": "save", "kind": "document", "code": ""}, {"action": "save", "kind": "nope", "code": "x"},
                     {"action": "save", "kind": "document", "code": ["not", "text"]}, {"action": "restore", "id": "art-20261114-010101-abcd", "n": 1}, {"action": "dance"}):
            status, got = self.call(**body)
            self.assertEqual(status, 400, body)
            self.assertNotIn("Traceback", json.dumps(got))
        self.assertEqual(self.req("POST", "/api/artifacts", {"action": "list"}, token=False)[0], 401, "only this app's own window may ask")

    def test_something_large_can_be_kept(self):
        big = "x" * 900_000
        status, made = self.call(action="save", title="Big", kind="document", code=big)
        self.assertEqual((status, made["versions"][0]["size"]), (200, 900_000))


if __name__ == "__main__":
    import unittest
    unittest.main()
