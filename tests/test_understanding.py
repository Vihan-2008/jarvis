"""Understanding the user: what the assistant is told about the moment, and the tools that finish the job.

Each case here is something that really went wrong in the owner's own voice chats: music played on YouTube although
Spotify had just been opened, "play it on Spotify" searched for the word "it", an email that went through Outlook
although Gmail was open (and was called sent when it was a draft), a click on the browser's own "Kiran" button
instead of the Netflix profile, and a Netflix search that ended up on Google.
"""
import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from jcc import assistant, config, mailer, music, policy, quick, reminders, uia, voice_tools
from tests.helpers import EngineTestCase, as_windows
from tests.test_assistant_voice import AssistantCase, FakeControls, FakeDesktop


class Windows:
    """The windows on a made-up desktop: {handle: (title, program)}, front first."""

    def __init__(self, rows, front=None):
        self.rows, self.front, self.focused = dict(rows), front if front is not None else next(iter(rows), 0), []

    def all(self):
        return [{"handle": handle, "title": title} for handle, (title, _) in self.rows.items()]

    def app(self, handle):
        return self.rows.get(handle, ("", ""))[1]

    def title(self, handle):
        return self.rows.get(handle, ("", ""))[0]

    def exists(self, handle):
        return handle in self.rows

    def foreground(self):
        return self.front

    def focus(self, handle):
        self.focused.append(handle)
        self.front = handle
        return True

    def process(self, handle):
        return handle

    def at(self, x, y):
        return self.front

    def middle(self, handle):
        return 100, 100


class Keys:
    def __init__(self, on_enter=None):
        self.done, self.on_enter = [], on_enter

    def perform(self, step):
        self.done.append(step)
        if step == {"action": "key", "keys": "enter"} and self.on_enter:
            self.on_enter()

    def window_title(self):
        return "Spotify Premium"


class TestWhatIsOnTheScreen(unittest.TestCase):
    def test_the_assistant_is_told_what_is_in_front_and_what_else_is_open(self):
        rows = [{"handle": 1, "title": "JARVIS · Workspace"}, {"handle": 2, "title": "Inbox (3) - me@example.com - Gmail - Comet"},
                {"handle": 3, "title": "Spotify Premium"}, {"handle": 4, "title": "HDFC NetBanking - Comet"}, {"handle": 5, "title": ""}]
        apps = {1: "msedge", 2: "comet", 3: "Spotify", 4: "comet"}
        said = assistant.situation(rows, apps.get)
        self.assertEqual(said, 'On screen, in front: "Inbox (3) - me@example.com - Gmail - Comet" [comet]. Also open: "Spotify Premium" [Spotify]; a private window.')
        self.assertNotIn("JARVIS", said, "its own window is not where the user is working")
        self.assertNotIn("NetBanking", said, "a private window is not named")
        self.assertEqual(assistant.situation([], apps.get), "On screen: no app window is open.")
        many = [{"handle": n, "title": f"Window {n}"} for n in range(1, 30)]
        self.assertLessEqual(assistant.situation(many, lambda handle: "").count("Window"), 8)

        def broken(handle):
            raise OSError("gone")
        self.assertIn('"Window 1"', assistant.situation(many[:1], broken), "a window whose program cannot be read is still named")

    def test_which_program_is_which(self):
        self.assertEqual(music.spotify_window(Windows({7: ("Drake - God's Plan", "Spotify"), 8: ("Spotify - Google Search - Comet", "comet")}, 8)), 7,
                         "found by its program: its title is the song while one is playing")
        self.assertEqual(music.spotify_window(Windows({8: ("Spotify - Google Search - Comet", "comet")})), 0)


class TestTheAssistantKnowsWhatJarvisDidItself(AssistantCase):
    def agent(self, *scripts):
        agent = self.make(*scripts)
        agent.look = lambda: 'On screen, in front: "Spotify Premium" [Spotify].'
        return agent

    def prompts(self):
        return [sent["message"]["content"][0]["text"] for proc in self.procs for sent in proc.sent]

    def test_every_message_says_what_is_on_the_screen_and_what_was_done_without_the_ai(self):
        agent = self.agent([[("text", "Hello.")], [("text", "Playing it.")], [("text", "Okay.")]])
        agent.apps.items = {"spotify": "id-spotify"}
        first = agent.say("hello there", spoken=True)
        events = self.finish(agent)
        chat = first["chat"]
        opened = agent.say("open spotify", chat, spoken=True)            # carried out by JARVIS itself, in no time, without the AI
        self.assertEqual((opened["model"], self.acted), ("instant", [("app", "id-spotify")]))
        agent.say("play a song by Drake", chat, spoken=True)
        self.finish(agent, len(events) + 4)
        prompts = self.prompts()
        self.assertIn('On screen, in front: "Spotify Premium" [Spotify].', prompts[0])
        self.assertNotIn("Since your last reply", prompts[0])
        self.assertIn("Since your last reply JARVIS did these directly, without you:", prompts[1])
        self.assertIn('The user said "open spotify". Done: Opened Spotify.', prompts[1])
        self.assertTrue(prompts[0].rstrip().endswith("[Spotify].)"), "the screen line closes the message")
        self.assertTrue(prompts[1].rstrip().endswith("The screen is as before.)"), "and is not repeated word for word while nothing has changed")
        self.assertTrue(agent.flags(chat)["private"], "window titles are the owner's own data")
        before = agent.poll(0)["next"]
        agent.say("and another", chat, spoken=True)
        self.finish(agent, before)
        self.assertNotIn("Since your last reply", self.prompts()[2], "told once")

    def test_jarvis_speaks_the_moment_it_starts_on_something(self):
        agent = self.agent([[("tool", ("mcp__jarvis__play_music", {"query": "Hotline Bling by Drake", "where": "spotify"})), ("text", "Playing Hotline Bling in Spotify.")],
                            [("tool", ("mcp__jarvis__media", {"action": "play_pause"})), ("text", "Paused.")]])
        info = agent.say("play hotline bling", spoken=True)
        events = self.finish(agent)
        said = [(e["k"], e.get("t")) for e in events if e["k"] in ("lead", "text")]
        self.assertEqual(said[0], ("lead", "Putting on Hotline Bling by Drake."), "said before the tool has even run")
        before = agent.poll(0)["next"]
        agent.say("hush the song for a bit", info["chat"], spoken=True)
        self.assertNotIn("lead", [e["k"] for e in self.finish(agent, before)], "something that takes no time needs no lead-in")
        typed = self.agent(*([[]] * len(self.procs)), [[("tool", ("mcp__jarvis__open_app", {"name": "Notepad"})), ("text", "Opened.")]])
        typed.say("open notepad for me and thank you kindly, it is for my notes")
        self.assertNotIn("lead", [e["k"] for e in self.finish(typed)], "a typed chat is read, not heard")

    def test_what_the_lead_in_says(self):
        for name, args, said in (("mcp__jarvis__open_app", {"name": "Spotify"}, "Opening Spotify."),
                                 ("mcp__jarvis__open_website", {"address_or_search": "Brooklyn Nine-Nine", "site": "Netflix.com"}, "Searching Netflix for Brooklyn Nine-Nine."),
                                 ("mcp__jarvis__open_website", {"address_or_search": "https://mail.google.com/mail/u/0/#inbox"}, "Opening that."),
                                 ("mcp__jarvis__open_website", {"address_or_search": "best pizza near me"}, "Searching for best pizza near me."),
                                 ("mcp__jarvis__play_show", {"title": "Brooklyn Nine-Nine"}, "Putting on Brooklyn Nine-Nine."),
                                 ("mcp__jarvis__send_email", {"to": "a@b.co", "subject": "Hi", "body": "Hello"}, "Writing the email."),
                                 ("WebSearch", {"query": "news"}, "Looking that up."), ("mcp__jarvis__media", {"action": "next"}, ""),
                                 ("mcp__jarvis__set_timer", {"duration": "5 minutes"}, ""), ("mcp__jarvis__play_music", {}, "One moment.")):
            self.assertEqual(assistant.lead_words(name, args), said, name)
        self.assertNotIn("gsk_", assistant.lead_words("mcp__jarvis__open_app", {"name": "gsk_FAKEgroqKEY1234567890abcdefGHIJ"}))

    def test_the_instructions_say_what_matters(self):
        for must in ("Stay where the user is", "Never give a word like \"it\" to a tool", "A page of search results is not \"playing\"",
                     "only when the report says so", "never ask them to confirm", "Only a [heard] message may be answered that way"):
            self.assertIn(must, assistant.SYSTEM, must)
        (self.cfg.state_dir).mkdir(parents=True, exist_ok=True)
        (self.cfg.state_dir / "apps.json").write_text(json.dumps({"at": time.time(), "apps": {"spotify": "a", "comet": "b", "uninstall raptor": "c", "netflix": "d",
                                                                                               "x64 native tools command prompt for vs 2022": "e"}}), "utf-8")
        facts = assistant.pc_facts(self.cfg, browser="Comet")
        self.assertIn("The user's web browser is Comet", facts)
        self.assertIn("Comet, Netflix, Spotify.", facts)
        self.assertNotIn("Uninstall", facts)
        self.assertNotIn("Native Tools", facts)
        prompt = assistant.system_prompt(self.cfg, {**assistant.settings(self.cfg), "pc_control": True}, assistant.active_assistant(self.cfg))
        self.assertIn("This PC:", prompt)
        self.assertNotIn("This PC:", assistant.system_prompt(self.cfg, {**assistant.settings(self.cfg), "pc_control": False}, assistant.active_assistant(self.cfg)))


@as_windows
class TestPlayingMusicForReal(unittest.TestCase):
    def play(self, query, rows, front=None, after=None, where="spotify", **more):
        windows = Windows(rows, front)
        keys = Keys(lambda: after and windows.rows.__setitem__(7, (after, "Spotify")))
        return music.play(query, where, windows, keys, pause=lambda seconds: None, **more), keys, windows

    def test_spotify_searches_and_presses_enter_and_says_what_is_now_playing(self):
        said, keys, windows = self.play("Hotline Bling by Drake", {3: ("Inbox - Gmail - Comet", "comet"), 7: ("Spotify Premium", "Spotify")}, after="Drake - Hotline Bling")
        self.assertEqual(said, 'Now playing in Spotify: "Drake - Hotline Bling".')
        self.assertEqual(keys.done, [{"action": "key", "keys": "ctrl+k"}, {"action": "type", "text": "Hotline Bling by Drake"}, {"action": "key", "keys": "enter"}])
        self.assertEqual(windows.focused, [7], "Spotify was brought to the front first: nothing is typed into another window")

    def test_it_never_says_playing_when_spotify_does_not_show_a_song(self):
        said, keys, _ = self.play("Drake", {7: ("Spotify Premium", "Spotify")})
        self.assertIn("does not show a new song playing", said)
        self.assertIn("Do not say it is playing", said)
        pressed = []
        said, _, windows = self.play("Drake", {7: ("Spotify Premium", "Spotify")}, press_play=lambda handle: pressed.append(handle) or True)
        self.assertEqual(pressed, [7], "an artist's page opened instead of a song starting: its Play button is pressed")

    def test_a_window_that_cannot_come_to_the_front_gets_nothing_typed(self):
        class Stubborn(Windows):
            def focus(self, handle):
                return False
        windows, keys = Stubborn({3: ("Notepad", "notepad"), 7: ("Spotify Premium", "Spotify")}, 3), Keys()
        said = music.play_in_spotify("Drake", windows, keys, pause=lambda seconds: None)
        self.assertIn("could not be brought to the front", said)
        self.assertEqual(keys.done, [])

    def test_where_music_plays_when_no_place_is_named(self):
        found = [{"title": "Lo-fi beats", "url": "https://www.youtube.com/watch?v=abcdefghijk"}]
        opened = []
        said = music.play("lofi beats", "", Windows({3: ("Notepad", "notepad")}), Keys(), finder=lambda query, limit=1: found, opener=opened.append)
        self.assertEqual((said, opened), ('Now playing on YouTube: "Lo-fi beats".', ["https://www.youtube.com/watch?v=abcdefghijk"]), "no Spotify on this PC")
        said, keys, _ = self.play("lofi beats", {7: ("Spotify Premium", "Spotify")}, after="Lofi Girl - Snowman", where="")
        self.assertIn("Spotify", said, "the Spotify app is open, so that is where music plays")
        launched = []
        said = music.play("x", "spotify", Windows({3: ("Notepad", "notepad")}), Keys(), launch=lambda: launched.append(1), pause=lambda seconds: None, has_spotify=True)
        self.assertEqual(launched, [1])
        self.assertIn("could not be started", said)
        self.assertIn("Nothing is playing", music.play_on_youtube("zzz", finder=lambda query, limit=1: [], opener=opened.append))

    def test_words_that_name_no_song(self):
        for vague in ("it", "that", "this one", "something", "some music", "a song", "the same", "play that", "the first one"):
            self.assertTrue(music.VAGUE.search(vague), vague)
        for real in ("Hotline Bling", "It's My Life by Bon Jovi", "This Is America", "Drake", "that's what I like"):
            self.assertFalse(music.VAGUE.search(real), real)


class Page(FakeControls):
    """A window whose controls change as things are pressed (a browser showing a streaming site)."""

    def __init__(self, screens):
        self.screens, self.at_, self.pressed = screens, 0, []

    def call(self, payload, timeout=10.0):
        items = [dict(item) for item in self.screens[min(self.at_, len(self.screens) - 1)]]
        uia.mark_pages(items)
        op = payload.get("op")
        if op == "list":
            return {"title": "Netflix - Comet", "items": items}
        index = uia.choose(items, str(payload.get("name", "")), op == "set")
        if index < 0:
            return {"item": None}
        if op == "press":
            self.pressed.append(items[index]["n"])
            self.at_ += 1
            return {"item": items[index], "how": "pressed"}
        return {"item": items[index]}


def control(kind, name, x=400, y=400, w=120, h=40):
    return {"t": kind, "n": name, "x": x, "y": y, "w": w, "h": h, "on": True, "secret": False}


BAR = [control("Button", "Back", 20, 40), control("Edit", "Address and search bar", 700, 40, 900, 30), control("Button", "Kiran", 1840, 40, 60, 30)]
PAGE = control("Document", "Netflix", 960, 580, 1900, 960)


@as_windows
class TestTools(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jcc-understand-"))
        self.questions, self.answer, self.mail, self.opened = [], True, {"connected": False, "through": "auto"}, []
        self.desktop = FakeDesktop()

        def service(op, payload):
            if op == "mail":
                if payload.get("use"):
                    self.mail["through"] = payload["use"]
                return dict(self.mail)
            if op == "turn":
                return {"turn": "t1"}
            if op == "gate":
                ctx = policy.Context(level="sending", window=payload["window"], control=payload["control"], state_dir=str(self.tmp / "state"))
                decision = policy.decide(payload["tool"], payload["args"], ctx)
                if decision.verdict == policy.DENY:
                    return {"ok": False, "reason": decision.reason}
                if policy.needs_owner(decision, ctx):
                    self.questions.append(decision.question)
                    if not self.answer:
                        return {"ok": False}
                return {"ok": True, "permit": "one-time"}
            return {"opened": "Spotify", "sent": False}
        self.service = service
        self._sleep, self._open = voice_tools.time.sleep, voice_tools.webbrowser.open
        voice_tools.time.sleep = lambda seconds: None
        voice_tools.webbrowser.open = lambda link: self.opened.append(link) or True

    def tearDown(self):
        voice_tools.time.sleep, voice_tools.webbrowser.open = self._sleep, self._open
        shutil.rmtree(self.tmp, ignore_errors=True)

    def box(self, windows, controls=None):
        box = voice_tools.Toolbox(self.desktop, self.service, lambda command, folder, timeout: (0, ""), controls or FakeControls(), windows=windows)
        box.state_dir = self.tmp
        box.where, box.owner_names = (lambda title: None), (lambda: [])      # (nothing is looked up on the internet, and nobody's name is read from this PC)
        return box

    def text(self, box, tool, **args):
        return voice_tools.handle(box, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}})["result"]["content"][0]["text"]

    def test_a_search_stays_on_the_site_the_user_is_on(self):
        box = self.box(Windows({2: ("Home - Netflix - Comet", "comet")}))
        said = self.text(box, "open_website", address_or_search="Brooklyn Nine-Nine", site="Netflix")
        self.assertEqual(self.opened, [], "Netflix is open: it is searched in its own tab, not opened a second time")
        self.assertIn({"action": "type", "text": "https://www.netflix.com/search?q=Brooklyn%20Nine-Nine"}, self.desktop.done)
        self.assertIn('the netflix search for "Brooklyn Nine-Nine"', said)
        self.text(box, "open_website", address_or_search="lofi", site="you tube")
        self.text(box, "open_website", address_or_search="weather tomorrow")
        self.text(box, "open_website", address_or_search="shoes", site="some shop nobody knows")
        self.assertEqual(self.opened, ["https://www.youtube.com/results?search_query=lofi", "https://www.google.com/search?q=weather%20tomorrow",
                                       "https://www.google.com/search?q=shoes%20some%20shop%20nobody%20knows"])
        self.assertEqual(self.questions, [], "a search is never asked about")

    def test_the_page_is_preferred_over_the_browsers_own_button_of_the_same_name(self):
        # "Open the Kiran profile" pressed the browser's own profile button, which has the same name as the Netflix profile.
        page = Page([BAR + [PAGE, control("Hyperlink", "Kiran", 700, 500, 150, 150), control("Hyperlink", "Kids", 900, 500, 150, 150)]])
        box = self.box(Windows({2: ("Netflix - Comet", "comet")}), page)
        self.assertIn('Pressed "Kiran"', self.text(box, "click_control", name="Kiran"))
        listing = self.text(box, "list_controls")
        self.assertLess(listing.index("Button: Kiran"), listing.index("-- on the page --"))
        self.assertGreater(listing.index("Hyperlink: Kiran"), listing.index("-- on the page --"), "and the assistant is shown which is which")
        items = [dict(item) for item in page.screens[0]]
        uia.mark_pages(items)
        self.assertEqual([item["n"] for item in items if item.get("page")], ["Kiran", "Kids"])
        self.assertEqual(items[uia.choose(items, "kiran")]["t"], "Hyperlink")
        self.assertEqual(items[uia.choose(items, "", True)]["n"], "Address and search bar", "with no box on the page, the only box there is")

    def test_a_show_is_found_opened_and_played(self):
        results = BAR + [PAGE, control("Hyperlink", "Brooklyn Nine-Nine", 300, 400, 200, 120), control("Hyperlink", "Brooklyn", 600, 400, 200, 120)]
        detail = BAR + [PAGE, control("Button", "Play trailer", 500, 600), control("Button", "Resume", 400, 600), control("Button", "My List", 700, 600)]
        player = BAR + [PAGE, control("Button", "Pause", 100, 1000), control("Button", "Seek Back", 200, 1000)]
        page = Page([results, detail, player])
        box = self.box(Windows({2: ("Home - Netflix - Comet", "comet")}), page)
        said = self.text(box, "play_show", title="brooklyn nine nine")
        self.assertEqual(self.opened, [], "in the Netflix tab that is open")
        self.assertIn({"action": "type", "text": "https://www.netflix.com/search?q=brooklyn%20nine%20nine"}, self.desktop.done)
        self.assertEqual(page.pressed, ["Brooklyn Nine-Nine", "Resume"], "the show, then Resume: not the trailer")
        self.assertEqual(said, 'Now playing "Brooklyn Nine-Nine" on Netflix (in the tab that was already open).')
        self.assertEqual(self.questions, [])

    def test_a_show_that_is_not_found_is_not_called_playing(self):
        page = Page([BAR + [PAGE, control("Hyperlink", "Something Else", 300, 400), control("Hyperlink", "Another Show", 600, 400)]])
        box = self.box(Windows({2: ("Netflix - Comet", "comet")}), page)
        said = self.text(box, "play_show", title="Brooklyn Nine-Nine", on="netflix")
        self.assertIn("Nothing is playing yet", said)
        self.assertIn("Something Else; Another Show", said, "the assistant is shown what is there, so it can choose")
        gate = Page([BAR + [PAGE, control("Hyperlink", "Kiran", 700, 500), control("Hyperlink", "Kids", 900, 500), control("Button", "Manage Profiles", 800, 700)]])
        said = self.text(self.box(Windows({2: ("Netflix - Comet", "comet")}), gate), "play_show", title="Brooklyn Nine-Nine")
        self.assertIn("is asking who is watching. The profiles are: Kiran, Kids.", said)
        no_button = Page([BAR + [PAGE, control("Hyperlink", "Brooklyn Nine-Nine", 300, 400)], BAR + [PAGE, control("Button", "My List", 700, 600)]])
        said = self.text(self.box(Windows({2: ("Netflix - Comet", "comet")}), no_button), "play_show", title="Brooklyn Nine-Nine")
        self.assertIn("NOT playing yet", said)
        self.assertIn("does not know how to play things on", self.text(box, "play_show", title="x", on="some other site"))

    def test_music_goes_to_spotify_through_the_tool(self):
        windows = Windows({3: ("Notepad", "notepad"), 7: ("Spotify Premium", "Spotify")}, 3)
        self.desktop.perform = lambda step: (self.desktop.done.append(step), step == {"action": "key", "keys": "enter"} and windows.rows.__setitem__(7, ("Drake - God's Plan", "Spotify")))
        box = self.box(windows)
        self.assertEqual(self.text(box, "play_music", query="God's Plan by Drake", where="spotify"), 'Now playing in Spotify: "Drake - God\'s Plan".')
        self.assertEqual(box.working, 7)
        self.assertIn("Name the song", self.text(box, "play_music", query="it"))
        self.assertEqual(self.questions, [])

    def test_email_is_written_where_the_user_writes_mail_and_sent_only_after_a_yes(self):
        # Gmail was open in the browser, and the message appeared in Outlook. Then it was called sent while it was a draft.
        windows = Windows({2: ("Inbox (3) - me@example.com - Gmail - Comet", "comet")})
        drafts, sends = [], []
        original = mailer.open_draft, mailer.press_send
        mailer.open_draft = lambda kind, desktop, to, subject, body, *a, **k: drafts.append((kind, to, subject, body)) or mailer.Draft(kind, "Compose Mail - Gmail - Comet")
        mailer.press_send = lambda draft, desktop, controls, handle_of, to, *a, **k: sends.append((draft.kind, to)) or f"The email to {to} was sent from Gmail."
        try:
            box = self.box(windows)
            said = self.text(box, "send_email", to="rahul@example.com", subject="test", body="hello")
            self.assertEqual((drafts, sends), ([("gmail", "rahul@example.com", "test", "hello")], [("gmail", "rahul@example.com")]))
            self.assertEqual(said, "The email to rahul@example.com was sent from Gmail.")
            self.assertEqual(self.questions, ["Shall I send this email to rahul@example.com?"], "asked once, when it is about to go")
            self.assertEqual(self.mail["through"], "gmail", "remembered: next time Gmail is the first choice even when it is not open")
            self.answer, self.questions[:] = False, []
            said = self.text(box, "send_email", to="rahul@example.com", subject="test", body="hello")
            self.assertIn("was NOT sent", said)
            self.assertIn("draft in Gmail", said)
            self.assertEqual(len(sends), 1, "no yes, no Send")
            self.answer = True
            self.text(self.box(Windows({2: ("Document1 - Word", "winword")})), "send_email", to="a@b.co", subject="s", body="b", using="the mail app")
            self.assertEqual(drafts[-1][0], "app", "the user named the mail app")
            self.mail = {"connected": False, "through": "auto"}
            self.text(self.box(Windows({2: ("Document1 - Word", "winword")})), "send_email", to="a@b.co", subject="s", body="b")
            self.assertEqual(drafts[-1][0], "app", "nothing says Gmail: the PC's own mail app")
            mailer.open_draft = lambda kind, *a, **k: mailer.Draft(kind, problem="Gmail is not signed in in the user's browser. Nothing was sent.")
            self.assertIn("not signed in", self.text(box, "send_email", to="a@b.co", subject="s", body="b", using="gmail"))
        finally:
            mailer.open_draft, mailer.press_send = original

    def test_which_way_an_email_goes(self):
        for using, connected, preferred, titles, way in (("", True, "auto", [], "account"), ("", False, "auto", ["Inbox - Gmail - Comet"], "gmail"),
                                                         ("", False, "auto", ["Notepad"], "app"), ("", False, "gmail", ["Notepad"], "gmail"),
                                                         ("in Outlook", False, "gmail", ["Inbox - Gmail"], "app"), ("gmail", True, "auto", [], "gmail"),
                                                         ("", False, "app", ["Inbox - Gmail - Comet"], "app")):
            self.assertEqual(mailer.choose(using, connected, preferred, titles), way, (using, connected, preferred, titles))
        self.assertEqual(mailer.gmail_link("a@b.co; c@d.org", "Hi there", "Hello\nworld"),
                         "https://mail.google.com/mail/?view=cm&fs=1&to=a%40b.co%2C%20c%40d.org&su=Hi%20there&body=Hello%0Aworld")

    def test_gmail_is_sent_with_its_own_shortcut_and_checked(self):
        class Desk:
            def __init__(self, titles):
                self.titles, self.done = list(titles), []

            def window_title(self):
                return self.titles.pop(0) if len(self.titles) > 1 else self.titles[0]

            def perform(self, step):
                self.done.append(step)
        opened = []
        desk = Desk(["Inbox - Gmail - Comet", "Compose Mail - me@example.com - Gmail - Comet"])
        draft = mailer.open_draft("gmail", desk, "a@b.co", "Hi", "Hello", opened.append, pause=lambda s: None)
        self.assertEqual((draft.problem, draft.title, opened), ("", "Compose Mail - me@example.com - Gmail - Comet", [mailer.gmail_link("a@b.co", "Hi", "Hello")]))
        draft.opened -= 10
        desk.titles = ["Compose Mail - me@example.com - Gmail - Comet", "Compose Mail - me@example.com - Gmail - Comet", "Gmail - Comet"]
        self.assertEqual(mailer.press_send(draft, desk, None, lambda: 5, "a@b.co", pause=lambda s: None), "The email to a@b.co was sent from Gmail.")
        self.assertEqual(desk.done, [{"action": "key", "keys": "ctrl+enter"}])
        desk = Desk(["Compose Mail - Gmail - Comet"])
        self.assertIn("may NOT have been sent", mailer.press_send(draft, desk, None, lambda: 5, "a@b.co", pause=lambda s: None))
        desk = Desk(["Untitled - Notepad"])
        self.assertIn("NOT sent", mailer.press_send(draft, desk, None, lambda: 5, "a@b.co", pause=lambda s: None))
        self.assertEqual(desk.done, [], "another window is in front: nothing is pressed")
        signed_out = mailer.open_draft("gmail", Desk(["Inbox", "Sign in - Google Accounts - Comet"]), "a@b.co", "Hi", "Hello", opened.append, pause=lambda s: None)
        self.assertIn("not signed in", signed_out.problem)

    def test_every_tool_call_leaves_a_line_for_looking_into_it_later(self):
        box = self.box(Windows({2: ("Home - Netflix - Comet", "comet")}))
        self.text(box, "open_website", address_or_search="Brooklyn Nine-Nine", site="netflix")
        self.text(box, "play_music", query="it")
        rows = [json.loads(line) for line in (self.tmp / "assistant-log.jsonl").read_text("utf-8").splitlines()]
        self.assertEqual([(row["tool"], row["failed"]) for row in rows], [("open_website", False), ("play_music", True)])
        self.assertEqual(rows[0]["args"], {"address_or_search": "Brooklyn Nine-Nine", "site": "netflix"})
        self.assertIn("Name the song", rows[1]["said"])


class TestInstantCommands(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.load()
        self.acted, self.returns = [], {}
        apps = quick.Apps(self.cfg)
        apps.items = {"google chrome": "id-chrome", "spotify": "id-spotify", "netflix": "id-netflix", "notepad": "id-notepad"}
        self.quick = quick.Quick(self.cfg, apps, reminders.Reminders(self.cfg), self.act)

    def act(self, kind, value=None):
        if kind == "playing":                     # (a question, not something done: whether this PC is playing is not known here)
            return None
        self.acted.append((kind, value))
        return self.returns.get(kind)

    def say(self, text):
        result = self.quick.handle(text)
        return result.say if result else None

    def test_open_google_is_the_website_not_the_first_app_that_begins_with_it(self):
        self.assertEqual(self.say("Open Google."), "Opening Google.")
        self.assertEqual(self.acted, [("url", "https://www.google.com")])
        self.acted.clear()
        self.assertEqual(self.say("open chrome"), "Opening Google Chrome.")
        self.assertEqual(self.say("open spotify"), "Opening Spotify.", "an app of exactly that name is the app")
        self.assertEqual(self.acted, [("app", "id-chrome"), ("app", "id-spotify")])

    def test_what_the_user_has_said_about_an_app_is_left_to_the_assistant(self):
        from jcc import memory
        self.assertEqual(self.say("open netflix"), "Opening Netflix.")
        memory.remember(self.cfg, "Wants Netflix opened in the Comet browser, not the Netflix app")
        self.acted.clear()
        self.assertIsNone(self.say("open netflix"), "the assistant knows how they want it")
        self.assertEqual(self.acted, [])

    def test_it_and_that_are_never_searched_for(self):
        for text in ("Play it on Spotify.", "search for it on Netflix", "play that on youtube", "look up this on google", "play something on spotify"):
            self.assertIsNone(self.say(text), text)
        self.assertEqual(self.acted, [], "the assistant, which knows what was meant, deals with these")

    def test_play_on_spotify_really_plays(self):
        self.returns["music"] = 'Now playing in Spotify: "J. Cole - No Role Modelz".'
        self.assertEqual(self.say("Play No Role Modelz by J. Cole on the Spotify app."), "Playing J. Cole - No Role Modelz on Spotify.")
        self.assertEqual(self.acted, [("music", ("no role modelz by j. cole", "spotify"))])
        self.returns["music"] = '"x" was typed into Spotify\'s search and Enter was pressed, but Spotify does not show a new song playing.'
        self.assertIn("did not start playing", self.say("play x on spotify"))

    def test_everyday_words_for_what_is_playing(self):
        # What comes back says what was understood, in a word or two ("Pausing the movie."), so nobody has to wonder.
        for text, reply in (("pause", "Pausing."), ("Pause it.", "Pausing."), ("resume", "Resuming."), ("continue", "Resuming."), ("continue playing", "Resuming."),
                            ("continue the show", "Resuming the show."), ("resume the movie", "Resuming the movie."), ("play", "Playing."),
                            ("pause the video", "Pausing the video."), ("stop the music", "Stopping the music."), ("pause the movie", "Pausing the movie."),
                            ("hold it for a second", "Pausing."), ("keep playing", "Resuming."), ("carry on", "Resuming.")):
            self.acted.clear()
            self.assertEqual(self.say(text), reply, text)
            self.assertEqual(self.acted, [("key", ("play_pause", 1))], text)
        self.acted.clear()
        for text in ("play it", "play that one", "play Hotline Bling", "continue drafting the email", "resume my work on the essay"):
            self.assertIsNone(self.say(text), text)
        self.assertEqual(self.acted, [])

    def test_a_search_inside_a_site(self):
        self.assertEqual(self.say("search for Brooklyn Nine-Nine on Netflix"), "Here's brooklyn nine-nine on Netflix.")
        self.assertEqual(self.acted, [("url", "https://www.netflix.com/search?q=brooklyn%20nine-nine")])
        for site, words, address in (("Netflix.com", "dark", "https://www.netflix.com/search?q=dark"), ("Prime", "the boys", "https://www.primevideo.com/search/?phrase=the%20boys"),
                                     ("the YouTube app", "lofi", "https://www.youtube.com/results?search_query=lofi"), ("gmail", "invoice", "https://mail.google.com/mail/u/0/#search/invoice")):
            self.assertEqual(quick.site_search(site, words), address, site)
        self.assertEqual(quick.site_search("netflix", "https://example.com"), "", "an address is not a search")
        self.assertEqual(quick.site_search("a site nobody knows", "x"), "")
        for name, plays in (("Play", True), ("Resume", True), ("Play Season 2 Episode 4", True), ("Watch now", True), ("Play trailer", False), ("Play Something", False),
                            ("Playlist", False), ("Next Episode", False)):
            self.assertEqual(bool(quick.PLAY_BUTTON.match(name)), plays, name)


if __name__ == "__main__":
    unittest.main()
