"""The voice session: stop, sleep and end; who is listening; "Hey JARVIS" on its own; playing what was found."""
import http.client
import json
import pathlib
import time
import unittest

from jcc import assistant, config, pcsound, policy, quick, voice_tools, wake, webread
from tests.helpers import EngineTestCase, as_windows
from tests.test_gui import GuiTestCase
from tests.test_wake import FakeListener, FakeRecorder, hit


class TestSessionWords(unittest.TestCase):
    def test_stop_sleep_and_end_are_three_different_things(self):
        for said in ("Stop.", "JARVIS, stop", "Jarvis stop", "okay stop it", "That's alright, you can stop now.", "you can shop now", "never mind",
                     "cancel that", "be quiet", "shut up", "that's enough", "Hey Jarvis, cancel"):
            self.assertEqual(quick.control_word(said), "rest", said)
        for said in ("go to sleep", "Jarvis go to sleep", "stop listening", "that's all for now", "I'm done", "stand by"):
            self.assertEqual(quick.control_word(said), "sleep", said)
        for said in ("END.", "End session", "Jarvis end session", "end the session please", "goodbye", "Bye Jarvis", "close the session", "exit"):
            self.assertEqual(quick.control_word(said), "end", said)

    def test_ordinary_requests_are_not_mistaken_for_them(self):
        for said in ("stop the music", "stop the timer", "end the movie at ten", "cancel my timers", "what time is it", "shop for shoes",
                     "tell me when the session ends", "goodbye yellow brick road on youtube", "quiet songs please", "sleep sounds on youtube"):
            self.assertEqual(quick.control_word(said), "", said)


class TestWhoIsListening(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.load()
        self.agent = assistant.Assistant(self.cfg, 1234, lambda *a, **k: None, exe="claude")
        self.agent.hand_wait = 0.2

    def tearDown(self):
        self.agent.close()
        super().tearDown()

    def test_a_window_that_closes_is_gone_at_once(self):
        """A closed window used to count as "in a conversation" for up to 45 seconds, and "Hey JARVIS" was ignored meanwhile."""
        agent = self.agent
        agent.poll(0, 0, "one")
        agent.presence("listening", "one")
        self.assertTrue(agent.window_open() and agent.voice_busy())
        self.assertEqual(agent.heard("what time is it"), {"busy": True}, "that window is listening itself")
        agent.presence("idle", "one", gone=True)
        self.assertFalse(agent.window_open() or agent.voice_busy())
        self.assertEqual(agent.heard("what time is it"), {"window": False}, "so the tray helper opens a window for it straight away")

    def test_one_of_two_windows_closing_leaves_the_other(self):
        agent = self.agent
        agent.poll(0, 0, "one")
        agent.poll(0, 0, "two")
        agent.presence("speaking", "two")
        agent.presence("idle", "one", gone=True)
        self.assertTrue(agent.window_open() and agent.voice_busy())
        self.assertEqual(agent.voice_phase_now(), "speaking")

    def test_a_window_that_stops_saying_it_is_busy_is_not_busy(self):
        agent = self.agent
        agent.poll(0, 0, "one")
        agent.presence("thinking", "one")
        agent.voices["one"] = ("thinking", time.time() - 13)          # it has not repeated that for longer than it would if it were alive
        self.assertFalse(agent.voice_busy())
        agent.presence("nonsense", "one")
        self.assertEqual(agent.voice_phase_now(), "idle")

    def test_hey_jarvis_on_its_own_asks_the_window_to_attend(self):
        agent = self.agent
        self.assertFalse(agent.hand("", attend=True))
        self.assertTrue(agent.poll(0, 0, "one")["waiting"])
        self.assertEqual(agent.take_pending(), {"text": "", "listen": False, "attend": True, "nudge": False})
        self.assertFalse(agent.hand(""))
        self.assertEqual(agent.take_pending(), {"text": "", "listen": True, "attend": False, "nudge": False}, "nothing followed its name: the window listens itself")
        self.assertFalse(agent.hand("open the calculator", attend=True))
        self.assertEqual(agent.take_pending(), {"text": "open the calculator", "listen": False, "attend": False, "nudge": False})

    def test_stop_sleep_and_end_reach_the_window(self):
        agent = self.agent
        upto = agent.poll(0, 0, "one")["next"]
        for word in ("rest", "sleep", "end"):
            self.assertTrue(agent.control(word)["ok"])
        events = agent.poll(upto, 0, "one")["events"]
        self.assertEqual([(e["k"], e["do"], e["spoken"]) for e in events], [("ui", "rest", True), ("ui", "sleep", True), ("ui", "end", True)])
        self.assertTrue(all(e["all"] is True for e in events), "every window is told: the one holding the conversation acts (none did, once)")
        agent.control("end", spoken=False)                              # the small window's End button: nothing is said
        self.assertEqual([(e["do"], e["spoken"], e["all"]) for e in agent.poll(upto, 0, "one")["events"]][-1], ("end", False, True))
        with self.assertRaises(ValueError):
            agent.control("format the disk")

    def test_how_long_an_idle_session_stays_awake_is_a_setting(self):
        self.assertEqual(assistant.settings(self.cfg)["sleep_minutes"], 15)
        self.assertEqual(assistant.configure(self.cfg, {"sleep_minutes": 30})["sleep_minutes"], 30)
        for bad in (-1, 7, "15", True, False, None, 1000):
            with self.assertRaises(ValueError):
                assistant.configure(self.cfg, {"sleep_minutes": bad})
        # 0 is "never": awake until it is told to go to sleep. (A yes or no written into the settings file is not a number.)
        self.assertEqual(assistant.configure(self.cfg, {"sleep_minutes": 0})["sleep_minutes"], 0)
        (self.cfg.state_dir / "assistant.json").write_text('{"sleep_minutes": false}', "utf-8")
        self.assertEqual(assistant.settings(self.cfg)["sleep_minutes"], 15)
        assistant.configure(self.cfg, {"sleep_minutes": 30})
        self.assertEqual(self.agent.poll(0, 0, "one")["settings"]["sleep_minutes"], 30, "the window is told")

    def test_was_that_the_pcs_own_sound(self):
        asked = []

        class Sound:
            def want(self, seconds=30.0):
                pass

            def verdict(self, start, levels, before=None):
                asked.append((round(time.time() - start), len(levels), len(before or [])))
                return {"pc": True, "playing": True, "heard": True, "score": 0.9}
        self.agent.sound = Sound()
        now = time.time() * 1000
        self.assertTrue(self.agent.echo(now - 2000, [0.1] * 100, [0.01] * 150 + ["x", None, True])["pc"])
        self.assertEqual(asked, [(2, 100, 150)], "only numbers are passed on")
        for bad in ("soon", None, now - 500_000, now + 60_000):
            with self.assertRaises(ValueError):
                self.agent.echo(bad, [0.1] * 100)

    def test_a_window_waiting_for_its_name_keeps_track_of_what_the_pc_plays(self):
        # Without the background helper a window listens for "Hey JARVIS" itself. A film that says the name must not wake it,
        # so the app has to know what the PC was playing at that moment.
        wanted = []

        class Sound:
            def want(self, seconds=30.0):
                wanted.append(seconds)
        self.agent.sound = Sound()
        self.agent.presence("idle", "one")
        self.assertEqual(wanted, [], "an idle window with the helper running: nothing to keep track of")
        self.agent.presence("idle", "one", wake=True)
        self.assertEqual(len(wanted), 1)
        self.agent.presence("idle", "one", gone=True, wake=True)
        self.assertEqual(len(wanted), 1, "a window that has closed is not listening")
        self.assertFalse(self.agent.voice_busy(), "waiting for the name is not a conversation")


class TestTrayAndWindowTogether(GuiTestCase):
    def tray(self, body):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("POST", "/api/tray", body=json.dumps(body), headers={"Host": f"127.0.0.1:{self.port}", "X-JCC-Tray": self.state.tray_key, "Content-Type": "application/json"})
        r = c.getresponse()
        out = (r.status, json.loads(r.read()))
        c.close()
        return out

    def test_the_whole_path_over_the_wire(self):
        self.state.assistant.hand_wait = 0.2
        self.assertEqual(self.tray({"action": "attend"}), (200, {"window": False}))
        status, data = self.req("GET", "/api/voice/events?since=0&w=abc")
        self.assertTrue(data["waiting"])
        self.assertEqual(self.req("POST", "/api/voice", {"action": "pending"})[1], {"text": "", "listen": False, "attend": True, "nudge": False})
        self.req("POST", "/api/voice", {"action": "presence", "phase": "speaking", "w": "abc"})
        self.assertEqual(self.tray({"action": "status"})[1], {"window": True, "app": True, "voice": True, "phase": "speaking", "waiting": False})
        self.assertEqual(self.tray({"action": "control", "text": "rest"})[0], 200, '"JARVIS, stop" gets through while it is talking')
        self.assertEqual(self.tray({"action": "control", "text": "explode"})[0], 400)
        events = self.req("GET", f"/api/voice/events?since={data['next']}&w=abc")[1]["events"]
        self.assertIn(("ui", "rest", True, True), [(e["k"], e.get("do"), e.get("spoken"), e.get("all")) for e in events])
        self.req("POST", "/api/voice", {"action": "presence", "phase": "idle", "w": "abc", "gone": True})
        self.assertEqual(self.tray({"action": "status"})[1], {"window": False, "app": False, "voice": False, "phase": "idle", "waiting": False}, "the window said goodbye")
        self.assertEqual(self.req("POST", "/api/voice", {"action": "settings", "settings": {"sleep_minutes": 5}})[1]["sleep_minutes"], 5)
        status, verdict = self.req("POST", "/api/voice", {"action": "echo", "start": time.time() * 1000 - 1500, "levels": [0.05] * 60, "before": []})
        self.assertEqual((status, verdict["pc"]), (200, False))
        self.assertEqual(self.req("POST", "/api/voice", {"action": "echo", "start": "x", "levels": []})[0], 400)
        self.assertEqual(self.req("POST", "/api/voice", {"action": "presence", "phase": "idle", "w": "abc", "wake": True}), (200, {"ok": True}))
        self.assertEqual(self.tray({"action": "status"})[1]["voice"], False, "a window waiting for its name is not in a conversation")
        self.assertIn(self.req("POST", "/api/voice", {"action": "playing"})[1]["playing"], (True, False))


class TestNobodyIsLeftWaiting(unittest.TestCase):
    def test_if_the_opened_window_never_picks_the_request_up_the_owner_is_told(self):
        from jcc import tray
        answers, told, original = [{"waiting": True}, {"waiting": True}, {"waiting": False}], [], tray.ask_service
        tray.ask_service = lambda cfg, action, text="": answers.pop(0) if answers else {"waiting": True}
        import time as clock
        sleep, clock.sleep = clock.sleep, lambda seconds: None
        try:
            self.assertTrue(tray._make_sure(None, told.append, seconds=5))
            self.assertEqual(told, [], "picked up: nothing to say")
            deadline = [clock.time() + 0.2]
            self.assertFalse(tray._make_sure(None, told.append, seconds=0.2))
            self.assertEqual(len(told), 1)
            self.assertIn("say it again", told[0])
        finally:
            tray.ask_service, clock.sleep = original, sleep


class TestTrayHelper(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.load()
        self.delivered, self.beeps, self.heard_audio, self.did, self.busy = [], [], [], [], False
        FakeListener.made, FakeRecorder.said = [], True

    def make(self, *replies, sound=None):
        replies = list(replies)

        def hear(audio):
            self.heard_audio.append(audio)
            return replies.pop(0) if replies else ""
        return wake.Ears(self.cfg, self.delivered.append, lambda text: None, FakeListener, FakeRecorder, hear, self.beeps.append, lambda: self.busy,
                         control=lambda word: self.did.append(("control", word)), attend=lambda: self.did.append(("attend",)),
                         listen=lambda: self.did.append(("listen",)), sound=sound)

    def test_jarvis_stop_gets_through_even_while_jarvis_is_talking(self):
        self.busy = True
        ears = self.make()
        ears._heard(hit("hey jarvis stop", 0.7, "ctrl"))
        ears._heard(hit("jarvis end session", 0.55, "ctrl"))
        ears._heard(hit("jarvis go to sleep", 0.8, "wake+"))
        self.assertEqual(self.did, [("control", "rest"), ("control", "end"), ("control", "sleep")])
        self.assertEqual((self.delivered, self.heard_audio), ([], []), "no transcription is needed, so it is immediate")
        ears._heard(hit("jarvis stop", 0.3, "ctrl"))                      # too faint to act on
        ears._heard(hit("hey jarvis what time is it", 0.9, "wake+"))      # an ordinary request: the busy window hears that itself
        self.assertEqual(len(self.did), 3)

    def test_its_name_alone_opens_the_session_and_the_next_sentence_is_the_request(self):
        ears = self.make("Hey Jarvis.", "open the calculator")
        ears._heard(hit("hey jarvis", grammar="wake"))
        self.assertEqual((self.did, self.delivered), ([("attend",)], ["open the calculator"]), "the window shows it is listening while the helper records")

    def test_its_name_alone_and_then_silence_leaves_the_session_listening(self):
        FakeRecorder.said = False
        ears = self.make("Hey Jarvis.")
        ears._heard(hit("hey jarvis", grammar="wake"))
        self.assertEqual((self.did, self.delivered), ([("attend",), ("listen",)], []))

    def test_only_when_nothing_follows_its_name_does_jarvis_speak_first(self):
        agent = assistant.Assistant(self.cfg, 1234, lambda *a, **k: None, exe="claude")
        try:
            agent.hand_wait = 0.1
            agent.hand(nudge=True)
            self.assertEqual(agent.take_pending(), {"text": "", "listen": True, "attend": False, "nudge": True}, "the window asks, then listens")
            agent.hand("open Spotify", nudge=True)
            self.assertEqual(agent.take_pending(), {"text": "open Spotify", "listen": False, "attend": False, "nudge": False}, "a request is simply answered")
            agent.hand("", attend=True)
            self.assertIs(agent.take_pending()["nudge"], False, "while the request is still being recorded, JARVIS stays quiet")
        finally:
            agent.close()

    def test_what_follows_its_name_can_be_a_command_for_the_session(self):
        ears = self.make("Hey Jarvis.", "never mind")
        ears._heard(hit("hey jarvis", grammar="wake"))
        self.assertEqual((self.did, self.delivered), ([("attend",), ("control", "rest")], []))

    def test_a_video_playing_after_its_name_is_not_taken_as_the_request(self):
        class Sound:
            asked = []

            def want(self, seconds=30.0):
                pass

            def verdict(self, start, levels, before=None):
                Sound.asked.append(len(levels))
                return {"pc": True}
        ears = self.make("Hey Jarvis.", "and that is why the hero never returned", sound=Sound())
        ears._heard(hit("hey jarvis", grammar="wake"))
        self.assertEqual((self.delivered, self.did), ([], [("attend",), ("listen",)]), "the film's words were not even transcribed")
        self.assertEqual((len(self.heard_audio), Sound.asked), (1, [len(pcsound.levels_of(FakeRecorder.sound))]))


RESULTS = """<html><body><script>var ytInitialData = {"contents": {"list": [
 {"videoRenderer": {"videoId": "abcdefghijk", "title": {"runs": [{"text": "Guide (1965) "}, {"text": "Full Movie"}]}, "lengthText": {"simpleText": "2:46:53"},
                    "ownerText": {"runs": [{"text": "Shemaroo"}]}, "viewCountText": {"simpleText": "2,177,117 views"}}},
 {"adRenderer": {"videoId": "not-a-video"}},
 {"videoRenderer": {"videoId": "ABCDEFGHIJ1", "title": {"simpleText": "Boot Polish (1954)"}}},
 {"videoRenderer": {"videoId": "abcdefghijk", "title": {"simpleText": "the same one again"}}}]}};</script></body></html>"""


class FakeOpener:
    def __init__(self, body, kind="text/html"):
        self.body, self.kind, self.asked = body, kind, []

    def open(self, request, timeout=15):
        self.asked.append((request.full_url, dict(request.header_items())))
        body, kind = self.body, self.kind

        class Response:
            status = 200

            class headers:  # noqa: N801
                @staticmethod
                def get_content_type():
                    return kind

                @staticmethod
                def get_content_charset():
                    return "utf-8"

            def read(self, limit=-1):
                return body.encode("utf-8")

            def geturl(self):
                return request.full_url

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False
        return Response()


@as_windows
class TestPlayingWhatWasFound(unittest.TestCase):
    def test_the_first_videos_are_read_from_the_results_page(self):
        opener = FakeOpener(RESULTS)
        rows = webread.find_videos("  old   hindi classic  ", opener)
        self.assertEqual(rows, [{"title": "Guide (1965) Full Movie", "length": "2:46:53", "by": "Shemaroo", "views": "2,177,117 views",
                                 "url": "https://www.youtube.com/watch?v=abcdefghijk"},
                                {"title": "Boot Polish (1954)", "length": "", "by": "", "views": "", "url": "https://www.youtube.com/watch?v=ABCDEFGHIJ1"}])
        self.assertEqual(opener.asked[0][0], "https://www.youtube.com/results?search_query=old%20hindi%20classic")
        self.assertNotIn("JARVIS", json.dumps(opener.asked[0][1]), "an ordinary browser's name is sent, nothing about this app or its owner")
        self.assertEqual([r["url"][-11:] for r in webread.find_videos("x", FakeOpener('junk "videoId":"zzzzzzzzzzz" more "videoId":"yyyyyyyyyyy"'))],
                         ["zzzzzzzzzzz", "yyyyyyyyyyy"], "a page laid out differently still gives videos to open")
        self.assertEqual(webread.find_videos("x", FakeOpener("<html>nothing here</html>")), [])
        for bad in ("", " ", "x" * 200):
            with self.assertRaises(ValueError):
                webread.find_videos(bad, opener)

    def test_a_page_is_read_with_its_links(self):
        page = """<html><head><title>News</title></head><body><nav><a href="/menu">Menu</a></nav>
            <p>Top story. <a href="/story/1">Read the  first story</a> and <a href="https://other.example/x#part">another site</a>.</p>
            <a href="javascript:alert(1)">bad</a><a href="mailto:a@b.c">mail</a><a href="/story/1">again</a><a href="#top">top</a></body></html>"""
        original = webread.check_address
        webread.check_address = lambda url, resolve=None: url
        try:
            text = webread.read_page("https://news.example/today", FakeOpener(page))
        finally:
            webread.check_address = original
        self.assertIn("Top story.", text)
        self.assertTrue(text.rstrip().endswith("Links on this page (open one with open_website):\n- Read the first story: https://news.example/story/1\n- another site: https://other.example/x"),
                        text[-300:])
        self.assertNotIn("javascript", text)
        self.assertNotIn("/menu", text, "the site's menu is left out")

    def test_play_on_youtube_starts_a_video_instead_of_a_list(self):
        acted = []

        def act(kind, value=None):
            acted.append((kind, value))
            return ("Guide (1965) Full Movie", "https://www.youtube.com/watch?v=abcdefghijk") if kind == "video" and "guide" in value else None
        helper = quick.Quick(None, quick.Apps(None) if False else type("NoApps", (), {"find": lambda self, name: None})(), None, act=act)
        done = helper.handle("Play the Guide movie on YouTube")
        self.assertEqual((done.say, acted), ("Playing Guide (1965) Full Movie.", [("video", "guide movie")]))
        acted.clear()
        done = helper.handle("play something obscure on youtube")                      # nothing found: fall back to the results page
        self.assertEqual(acted[0], ("video", "something obscure"))
        self.assertEqual(acted[1][0], "url")
        self.assertIn("youtube.com/results", acted[1][1])

    def test_the_assistant_can_look_for_videos_and_then_open_one(self):
        gates = []

        def service(op, payload):
            if op == "turn":
                return {"turn": "t"}
            gates.append(payload["tool"])
            return {"ok": True}
        box = voice_tools.Toolbox(None, service, lambda *a: (0, ""), type("NoControls", (), {"call": lambda self, payload, timeout=10: {}})(), handle=lambda: 5)
        original = webread.find_videos
        webread.find_videos = lambda query, opener=None, limit=6: [{"title": "Guide (1965)", "length": "2:46:53", "by": "Shemaroo", "views": "2M views",
                                                                    "url": "https://www.youtube.com/watch?v=abcdefghijk"}]
        try:
            self.assertEqual(box.find_videos("old hindi movie"), "1. Guide (1965) (2:46:53), by Shemaroo, 2M views\n   https://www.youtube.com/watch?v=abcdefghijk")
            webread.find_videos = lambda query, opener=None, limit=6: []
            self.assertIn("No videos were found", box.find_videos("zzz"))
        finally:
            webread.find_videos = original
        self.assertEqual(gates, ["find_videos", "find_videos"])
        self.assertIn("find_videos", {tool["name"] for tool in voice_tools.TOOLS})
        self.assertEqual(policy.decide("find_videos", {"query": "x"}, policy.Context()).verdict, policy.ALLOW)
        self.assertEqual(policy.marks("find_videos", {}), (True, False), "the titles are outside content: careful mode from here on")
        self.assertEqual(policy.decide("find_videos", {"query": "x"}, policy.Context(exposed=True, private=True)).verdict, policy.CONFIRM)


if __name__ == "__main__":
    unittest.main()


class TestTheWindowsOwnListening(unittest.TestCase):
    """What only the window script decides. (It runs in the app window, so this reads the script itself.)"""

    def test_a_noise_cannot_be_written_down_as_the_name(self):
        # Whisper writes down a name it has been told when it hears only a noise. While a window waits to hear "Hey JARVIS",
        # and while you dictate, it is therefore not told any name. Nor for what is said over other sound: asked to expect
        # "JARVIS" there, it wrote the name in front of a film's line, and what begins with its name counts as said to it.
        source = (pathlib.Path(__file__).resolve().parent.parent / "jcc" / "static" / "nova-voice.js").read_text("utf-8")
        self.assertIn("mode === 'dictate' || mode === 'wake' || noisy ? 'plain=1' : 'hint='", source)
        self.assertEqual(source.count("/api/speech/stt"), 1, "every transcription goes through that one place")
        self.assertNotIn("mode === 'barge' || mode === 'wake') return null", source, "the PC's own sound is checked while waiting for the name too")
