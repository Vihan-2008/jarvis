"""Hearing someone who speaks to JARVIS while other sound fills the room, and being interrupted while it works.

Seen live: with a film playing on another device JARVIS waited until the film paused before it understood anything,
because it listened for quiet to know that a sentence had ended. In such a room the question is who is speaking."""
import json
import threading
import time

from jcc import assistant, config, speech, wake, wakeword
from tests.helpers import EngineTestCase
from tests.test_assistant_voice import AssistantCase
from tests.test_wake import FakeListener, FakeRecorder
from tests.test_wakeword import FakeMic, ScriptedSpotter, tone

PIECE = wakeword.STEP * 2


class TestWhoIsSpeaking(EngineTestCase):
    def test_in_a_room_with_a_film_the_person_is_told_from_the_film_by_their_own_voice(self):
        following = wakeword.Following(quiet=0.15, floor=0.02, high=0.04, voice=0.2)
        self.assertTrue(following.busy and following.stands_out())
        for _ in range(4):
            following._take(tone(0.08, 0.035))                     # the film, as loud as it was before
        self.assertFalse(following.heard_speech, "the film is the room, not someone speaking")
        for _ in range(6):
            following._take(tone(0.08, 0.2))                       # the person
        self.assertTrue(following.heard_speech)
        self.assertEqual(following.quiet_for(), 0.0)
        # They stop. The film carries on, and has one loud moment: that does not make it the person again.
        for level in (0.035, 0.03, 0.075, 0.03, 0.035, 0.03):
            following._take(tone(0.08, level))
        time.sleep(0.2)
        self.assertGreater(following.quiet_for(), 0.15)
        self.assertTrue(following.finished_speaking(), "the end is found although the room never went quiet")

    def test_a_quiet_room_is_heard_as_before(self):
        plain = wakeword.Following(quiet=0.15, floor=0.002, high=0.004, voice=0.2)
        self.assertFalse(plain.busy)
        plain._take(tone(0.08, 0.03))
        self.assertTrue(plain.heard_speech, "a soft word after a loud name still counts in a quiet room")
        self.assertTrue(plain.stands_out())

    def test_it_knows_when_the_person_cannot_be_told_from_the_room(self):
        self.assertFalse(wakeword.Following(floor=0.05, high=0.09, voice=0.1).stands_out(), "a film as loud as the voice")
        self.assertTrue(wakeword.Following(floor=0.02, high=0.04, voice=0.1).stands_out())

    def test_the_name_tells_how_loud_the_person_is_and_the_room_before_it_how_loud_the_room_is(self):
        hits = []
        listener = wakeword.NeuralListener(hits.append, {}, microphone=FakeMic, spotter=lambda files: ScriptedSpotter([0.0] * 30 + [0.95]))
        listener.start()
        for _ in range(18):
            listener.mic.each(tone(0.08, 0.03))                    # a film, before the name
        for _ in range(12):
            listener.mic.each(tone(0.08, 0.25))                    # "Hey JARVIS"
        listener.mic.each(tone(0.08, 0.25))
        deadline = time.time() + 2
        while not hits and time.time() < deadline:
            time.sleep(0.02)
        recorder = hits[0]["recorder"]
        self.assertTrue(recorder.busy)
        self.assertAlmostEqual(recorder.voice, 0.25 / 2 ** 0.5, delta=0.03)
        self.assertLess(recorder.high, 0.05)
        self.assertTrue(recorder.stands_out())
        listener.stop()

    def test_a_first_whole_sentence(self):
        self.assertEqual(wake.first_sentence("Pause the movie. I told you he would come back."), "Pause the movie.")
        self.assertEqual(wake.first_sentence("Set a timer for. Ten minutes"), "", "an unfinished sentence is not a request yet")
        self.assertEqual(wake.first_sentence("pause the movie"), "")
        self.assertEqual(wake.first_sentence(""), "")


class Drowned(FakeRecorder):
    """What follows the name in a room as loud as the person: no end can be found by listening."""
    busy, voiced = True, 1.5

    def __init__(self):
        super().__init__()
        self.stopped = False

    def stands_out(self):
        return False

    def quiet_for(self):
        return 0.0

    def so_far(self):
        return self.sound

    def finished_speaking(self):
        return False

    def stop(self):
        self.stopped = True
        return self.sound


class Sound:
    """Stands in for the meter of the PC's own sound."""

    def __init__(self, playing=True, pc=False):
        self.playing, self.pc = playing, pc

    def want(self, seconds=30):
        pass

    def playing_now(self, seconds=1.0):
        return self.playing

    def verdict(self, start, levels, before=None):
        return {"pc": self.pc}


class TestTheTrayHelper(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.load()
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        self.delivered, self.named, self.heard_audio, self.level, self.set = [], [], [], [60], []
        FakeListener.made, FakeRecorder.said = [], True

    def make(self, *replies, busy=False, sound=None):
        replies = list(replies)

        def hear(audio):
            self.heard_audio.append(audio)
            return replies.pop(0) if replies else ""

        def write(percent):
            self.set.append(percent)
            self.level[0] = percent
        ears = wake.Ears(self.cfg, self.delivered.append, lambda text: None, FakeListener, FakeRecorder, hear, lambda pitch: None, lambda: busy,
                         control=lambda word: None, attend=lambda: None, listen=lambda: None, sound=sound, name_said=self.named.append,
                         volume=(lambda: self.level[0], write))
        ears.peek_after, ears.peek_every = 0.05, 0.1
        return ears

    def hit(self, recorder=None, confidence=0.95):
        recorder = recorder or FakeRecorder()
        recorder.start()
        return {"text": "hey jarvis", "confidence": confidence, "grammar": "wake", "neural": True, "pcm": b"\x01\x02" * 32000, "began": time.time() - 2,
                "recorder": recorder, "at": time.time()}

    def test_where_no_end_can_be_heard_the_first_sentence_that_stays_the_same_is_the_request(self):
        ears = self.make("Pause the movie. I told", "Pause the movie. I told you he would come back", "never asked for")
        recorder, started = Drowned(), time.time()
        ears._heard(self.hit(recorder))
        self.assertEqual(self.delivered, ["Pause the movie."], "the film's next line is not part of it")
        self.assertLess(time.time() - started, 3, "and it did not wait for the film to pause")
        self.assertTrue(recorder.stopped)
        self.assertEqual(len(self.heard_audio), 2)

    def test_and_if_time_runs_out_the_first_whole_sentence_is_taken(self):
        ears = self.make("Open", "Open Netflix. You will never find it")
        ears.peek_every = 3.0                                # (only one look before the time is up)
        original = time.time
        recorder = Drowned()
        clock = [0.0]
        try:
            wake.time.time = lambda: original() + clock[0]
            threading.Timer(0.4, lambda: clock.__setitem__(0, 20.0)).start()     # nine seconds pass
            ears._heard(self.hit(recorder))
        finally:
            wake.time.time = original
        self.assertEqual(self.delivered, ["Open Netflix."], "what was said to JARVIS came first; the rest is the room")

    def test_its_name_during_a_conversation_is_passed_to_the_window_that_holds_it(self):
        ears = self.make("open Spotify.", busy=True)
        hit = self.hit()
        ears._heard(hit)
        self.assertEqual(self.named, [hit["at"]], "the window has the microphone: it is told when the name was said")
        self.assertEqual((self.delivered, self.heard_audio), ([], []), "and the helper itself does nothing more")
        ears = self.make(busy=True, sound=Sound(pc=True))
        ears._heard(self.hit())
        self.assertEqual(len(self.named), 1, "a film on this PC saying the name is not passed on")

    def test_the_pcs_own_sound_is_turned_down_while_the_request_is_said_and_put_back_before_anything_is_done(self):
        order = []
        ears = self.make("turn it up.", sound=Sound())
        ears.deliver = lambda text: order.append(("request", self.level[0]))
        ears._heard(self.hit())
        self.assertEqual(self.set, [15, 60], "down to a quarter, then back to what it was")
        self.assertEqual(order, [("request", 60)], "back up before the request is acted on")
        self.assertFalse((self.cfg.state_dir / "listening-volume.json").exists())

    def test_it_is_left_alone_when_nothing_plays_when_it_is_quiet_already_or_when_switched_off(self):
        ears = self.make("what time is it?", sound=Sound(playing=False))
        ears._heard(self.hit())
        self.level[0] = 10
        ears = self.make("what time is it?", sound=Sound())
        ears._heard(self.hit())
        self.level[0] = 60
        speech.configure(self.cfg, {"duck": False})
        ears = self.make("what time is it?", sound=Sound())
        ears._heard(self.hit())
        self.assertEqual(self.set, [])
        self.assertEqual(len(self.delivered), 3)

    def test_a_volume_changed_by_hand_meanwhile_is_not_touched(self):
        ears = self.make("what time is it?", sound=Sound())
        ears.deliver = lambda text: None
        real = ears._rest
        ears._rest = lambda *a: (self.level.__setitem__(0, 35), real(*a))[1]      # someone moves the slider while JARVIS listens
        ears._heard(self.hit())
        self.assertEqual((self.set, self.level[0]), ([15], 35))

    def test_a_film_saying_the_name_does_not_turn_anything_down(self):
        ears = self.make(sound=Sound(pc=True))
        ears._heard(self.hit())
        self.assertEqual(self.set, [])

    def test_a_volume_left_turned_down_is_put_back_when_the_helper_starts(self):
        path = self.cfg.state_dir / "listening-volume.json"
        writes = []
        path.write_text(json.dumps({"volume": 60, "low": 15, "at": time.time() - 100}), "utf-8")
        self.assertTrue(wake.restore_volume(self.cfg, (lambda: 15, writes.append)))
        self.assertEqual((writes, path.exists()), ([60], False))
        path.write_text(json.dumps({"volume": 60, "low": 15}), "utf-8")
        self.assertFalse(wake.restore_volume(self.cfg, (lambda: 40, writes.append)), "it has been changed since: left as it is")
        self.assertEqual((writes, path.exists()), ([60], False))
        path.write_text("not what was expected", "utf-8")
        self.assertFalse(wake.restore_volume(self.cfg, (lambda: 15, writes.append)))
        self.assertFalse(wake.restore_volume(self.cfg, (lambda: 15, writes.append)), "nothing to put back")


class TestInterruptingWhileItWorks(AssistantCase):
    def test_nothing_new_is_begun_while_its_owner_speaks_and_the_work_carries_on_if_that_was_not_for_it(self):
        agent = self.make([[("text", "Working"), ("hang", None)]])
        info = agent.say("tidy my desktop", spoken=True)
        time.sleep(0.2)
        sid = agent.turns[info["chat"]].session.id
        self.assertEqual(agent.gate(sid, "list_windows", {}), {"ok": True})
        self.assertEqual(agent.hold(info["chat"], True), {"held": True})
        results = []
        worker = threading.Thread(target=lambda: results.append(agent.gate(sid, "list_windows", {})))
        worker.start()
        time.sleep(0.3)
        self.assertEqual(results, [], "the next action waits to hear what was said")
        agent.hold(info["chat"], False)
        worker.join(2)
        self.assertEqual(results, [{"ok": True}], "it was not for JARVIS: the work carries on where it was")

    def test_an_interruption_stops_the_old_request_and_no_late_action_of_it_fires(self):
        agent = self.make([[("text", "Working"), ("hang", None)]], [[("text", "Opening the other one.")]])
        info = agent.say("open the first report", spoken=True)
        time.sleep(0.2)
        sid = agent.turns[info["chat"]].session.id
        agent.hold(info["chat"], True)
        results = []
        worker = threading.Thread(target=lambda: results.append(agent.gate(sid, "open_file", {"path": "C:\\reports\\first.txt"})))
        worker.start()
        time.sleep(0.2)
        agent.stop(info["chat"])
        worker.join(2)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["ok"], "what was waiting is refused, not carried out late")
        self.assertIn("interrupted", results[0]["reason"])
        self.assertFalse(agent.gate(sid, "open_file", {"path": "C:\\reports\\first.txt"})["ok"], "and nothing of the old request is done afterwards")
        self.finish(agent)
        # What was said instead is a request of its own, and the AI is told what had already been done.
        second = agent.say("no, the second report", chat_id=info["chat"], spoken=True, interrupts=["Opened the reports folder", "Looked for first.txt"])
        self.finish(agent, ident=second["id"])
        sent = self.procs[-1].sent[-1]["message"]["content"][0]["text"]
        self.assertIn("while you were still working on their last request", sent)
        self.assertIn("Opened the reports folder; Looked for first.txt", sent)
        self.assertIn("never say that something already done was undone", sent)

    def test_holding_never_lasts_and_asks_nothing_of_a_chat_that_is_not_working(self):
        agent = self.make()
        self.assertEqual(agent.hold("no-such-chat", True), {"held": False})
        self.assertEqual(agent.hold(None, False), {"held": False})

    def test_what_was_heard_over_other_voices_is_said_so_and_a_first_sentence_jarvis_can_do_itself_is_the_request(self):
        agent = self.make([[("text", "Paused.")]])
        info = agent.say("Which film is this? I told you he would come back.", spoken=True, noisy=True)
        self.finish(agent, ident=info["id"])
        sent = self.procs[-1].sent[-1]["message"]["content"][0]["text"]
        self.assertIn("other voices or a film were sounding", sent)
        assistant.configure(self.cfg, {"pc_control": True})
        agent = self.make()
        done = agent.say("Pause the movie. I told you he would come back.", spoken=True, noisy=True, near=True)
        self.assertTrue(done.get("instant"), "the film's line after it does not stop JARVIS from just doing it")
        self.assertEqual(self.acted[-1], ("key", ("play_pause", 1)))
        typed = agent.say("Pause the movie. I told you he would come back.", spoken=False, noisy=True, near=True)
        self.assertFalse(typed.get("instant"), "only for what was heard")
        self.finish(agent, ident=typed["id"])

    def test_a_line_overheard_among_other_voices_is_never_acted_on_straight_away(self):
        # "Pause." is also something people in a film say. Picked up by the open microphone over other sound, not said
        # to JARVIS by name, and not plainly by someone nearer than that sound: the AI judges it; nothing is done at once.
        assistant.configure(self.cfg, {"pc_control": True})
        agent = self.make([[("text", "not for me")]])
        unsure = agent.say("Pause the movie.", spoken=True, heard=True, noisy=True)
        self.assertFalse(unsure.get("instant"))
        self.assertEqual(self.acted, [], "no key was pressed")
        self.finish(agent, ident=unsure["id"])
        sent = self.procs[-1].sent[-1]["message"]["content"][0]["text"]
        self.assertTrue(sent.startswith("[heard] "), sent[:40])
        # Plainly said by someone near the microphone, it is done at once, as in a quiet room.
        agent = self.make()
        near = agent.say("Pause the movie.", spoken=True, heard=True, noisy=True, near=True)
        self.assertTrue(near.get("instant"))
        self.assertEqual(self.acted[-1], ("key", ("play_pause", 1)))
        quiet = agent.say("Pause the movie.", spoken=True, heard=True)
        self.assertTrue(quiet.get("instant"), "a quiet room: as it always was")
        named = agent.say("Pause the movie.", spoken=True, noisy=True, near=True)
        self.assertTrue(named.get("instant"), "said to JARVIS by name over the film, by someone plainly nearer than it: done at once")

    def test_words_that_did_not_stand_out_from_the_film_are_never_acted_on_straight_away_even_after_its_name(self):
        # Measured: with a film as loud as the speaker, the film's line is what gets written down. "Stop." is a line too.
        assistant.configure(self.cfg, {"pc_control": True})
        agent = self.make([[("text", "Sorry, I could not make that out over the sound. Say it again?")]])
        info = agent.say("Pause the movie.", spoken=True, noisy=True)
        self.assertFalse(info.get("instant"))
        self.assertEqual(self.acted, [], "no key was pressed")
        self.finish(agent, ident=info["id"])
        sent = self.procs[-1].sent[-1]["message"]["content"][0]["text"]
        self.assertTrue(sent.startswith("[spoken] "), "it was said to JARVIS, so it is answered")
        self.assertIn("may not be the user's at all", sent)
        self.assertIn("could not make them out over the sound", sent)
        # Plainly from someone near: the AI is not told to doubt the words.
        agent = self.make([[("text", "Which film?")]])
        clear = agent.say("What is this film called?", spoken=True, noisy=True, near=True)
        self.finish(agent, ident=clear["id"])
        sent = self.procs[-1].sent[-1]["message"]["content"][0]["text"]
        self.assertIn("other voices or a film were sounding", sent)
        self.assertNotIn("may not be the user's at all", sent)

    def leads(self, agent):
        return [(e["t"], bool(e.get("ack"))) for e in agent.poll(0)["events"] if e["k"] == "lead"]

    def test_a_request_that_takes_a_moment_is_acknowledged_at_once(self):
        agent = self.make([[("hang", None)]])
        agent.ack_after = 0.05
        info = agent.say("open my Netflix home page and continue the show I was watching", spoken=True)
        time.sleep(0.4)
        said = self.leads(agent)
        self.assertEqual(len(said), 1, "one word, once")
        self.assertIn(said[0][0], assistant.ACKS)
        self.assertTrue(said[0][1], "marked as an acknowledgement, so the window need not say the first step on top of it")
        agent.stop(info["chat"])
        self.finish(agent)

    def test_no_acknowledgement_for_a_question_for_what_was_overheard_or_for_what_was_typed(self):
        for text, how in (("what time is it in Tokyo", {"spoken": True}), ("open my Netflix home page", {"spoken": True, "heard": True}),
                          ("open my Netflix home page", {"spoken": False})):
            agent = self.make([[("hang", None)]])
            agent.ack_after = 0.05
            info = agent.say(text, **how)
            time.sleep(0.3)
            self.assertEqual(self.leads(agent), [], f"{text!r} {how}")
            agent.stop(info["chat"])
            self.finish(agent)

    def test_no_acknowledgement_once_the_ai_has_begun_to_answer_or_the_request_was_stopped(self):
        agent = self.make([[("text", "Opening it now."), ("hang", None)]])
        agent.ack_after = 0.3
        info = agent.say("open my Netflix home page", spoken=True)
        time.sleep(0.7)
        self.assertEqual(self.leads(agent), [], "its own words came first")
        agent.stop(info["chat"])
        self.finish(agent)
        agent = self.make([[("hang", None)]])
        agent.ack_after = 0.3
        info = agent.say("open my Netflix home page", spoken=True)
        time.sleep(0.05)
        agent.stop(info["chat"])
        time.sleep(0.5)
        self.assertEqual(self.leads(agent), [], "stopped before a word was due")
        self.finish(agent)

    def test_its_name_during_a_conversation_reaches_the_windows(self):
        agent = self.make()
        at = time.time()
        self.assertTrue(agent.name_said(str(at))["ok"])
        self.assertIn({"k": "name", "at": at}, [{"k": e["k"], "at": e.get("at")} for e in agent.poll(0)["events"]])
        agent.name_said("nonsense")
        agent.name_said(str(at - 9999))
        times = [e["at"] for e in agent.poll(0)["events"] if e["k"] == "name"]
        self.assertTrue(all(abs(t - time.time()) < 5 for t in times[1:]), "a time that cannot be right is taken as now")

    def test_it_can_stay_awake_until_it_is_told_to_sleep(self):
        self.assertEqual(assistant.configure(self.cfg, {"sleep_minutes": 0})["sleep_minutes"], 0)
        self.assertEqual(assistant.settings(self.cfg)["sleep_minutes"], 0)
        self.assertEqual(assistant.configure(self.cfg, {"sleep_minutes": 30})["sleep_minutes"], 30)
