"""Hearing and understanding: the sound tidied before it is sent, a second opinion when Whisper is unsure, the owner's
project names as spelling hints, and speech understood as it is spoken. Nothing here reaches a real service."""
import array
import math
from unittest import mock

from jcc import config, quick, speech
from tests.helpers import EngineTestCase


def tone(seconds, level, rate=16000):
    return array.array("h", (int(level * math.sin(2 * math.pi * 220 * n / rate)) for n in range(int(seconds * rate)))).tobytes()


def silence(seconds, rate=16000):
    return bytes(int(seconds * rate) * 2)


class TheSoundIsTidied(EngineTestCase):
    def test_silence_either_side_is_trimmed_and_a_quiet_voice_brought_up(self):
        quiet = silence(1.5) + tone(1.0, 2000) + silence(2.0)
        tidied = speech.tidy(quiet)
        seconds = len(tidied) / 2 / 16000
        self.assertLess(seconds, 1.6, "the long silences are gone")
        self.assertGreater(seconds, 1.0, "the words and a little either side are kept")
        loudest = max(abs(s) for s in array.array("h", tidied))
        self.assertGreater(loudest, 12000, "a quiet recording is brought up")
        self.assertLessEqual(loudest, 32767)

    def test_a_good_recording_is_left_at_its_level_and_silence_left_alone(self):
        loud = tone(1.0, 24000)
        self.assertEqual(max(abs(s) for s in array.array("h", speech.tidy(loud))), max(abs(s) for s in array.array("h", loud)))
        hush = silence(1.0)
        self.assertEqual(speech.tidy(hush), hush, "nothing to hear: nothing made up")


class ASecondOpinion(EngineTestCase):
    def answer(self, text, logprob):
        return {"text": text, "duration": 2.0, "segments": [{"text": text, "avg_logprob": logprob, "no_speech_prob": 0.01, "compression_ratio": 1.2}]}

    def heard(self, first, second):
        asked = []

        def service(address, method, path, headers, body, timeout=20.0, who=""):
            model = "whisper-large-v3-turbo" if b"whisper-large-v3-turbo" in body else "whisper-large-v3"
            asked.append(model)
            assert headers["Content-Type"].split("boundary=")[-1].encode() in body, "each request carries its own boundary"
            return first if model.endswith("turbo") else second
        with mock.patch.object(speech, "whisper_provider", lambda: ("groq", "gsk_test")), mock.patch.object(speech, "_json", service):
            got = speech.hear(config.load(), tone(1.0, 9000))
        return got["text"], asked

    def test_when_unsure_the_careful_model_hears_it_again_and_the_surer_is_kept(self):
        text, asked = self.heard(self.answer("open note bad", -0.9), self.answer("open Notepad", -0.2))
        self.assertEqual((text, asked), ("open Notepad", ["whisper-large-v3-turbo", "whisper-large-v3"]))

    def test_when_sure_it_is_asked_once(self):
        text, asked = self.heard(self.answer("open Notepad", -0.1), self.answer("never asked", 0))
        self.assertEqual((text, asked), ("open Notepad", ["whisper-large-v3-turbo"]))

    def test_a_second_opinion_that_is_no_surer_does_not_replace_the_first(self):
        text, _ = self.heard(self.answer("open the calculator", -0.8), self.answer("open the calculate her", -1.4))
        self.assertEqual(text, "open the calculator")


class TheOwnersWords(EngineTestCase):
    def test_project_names_are_spelling_hints_when_talking_to_jarvis(self):
        sent = {}

        def service(address, method, path, headers, body, timeout=20.0, who=""):
            sent["body"] = body
            return {"text": "open WII-latest", "segments": [{"text": "open WII-latest", "avg_logprob": -0.1, "no_speech_prob": 0.0}]}
        cfg = config.load()
        cfg.projects["wii"] = mock.Mock(name="project")
        cfg.projects["wii"].name = "WII-latest"
        with mock.patch.object(speech, "whisper_provider", lambda: ("groq", "gsk_test")), mock.patch.object(speech, "_json", service):
            speech.hear(cfg, tone(1.0, 9000))
            self.assertIn(b"WII-latest", sent["body"])
            speech.hear(cfg, tone(1.0, 9000), names=False)
            self.assertNotIn(b"WII-latest", sent["body"], "dictation is not steered towards names")


class UnderstoodAsSpoken(EngineTestCase):
    def test_hesitations_stutters_and_the_name_misheard(self):
        self.assertEqual(quick.normalise("um, open open notepad"), "open notepad")
        self.assertEqual(quick.normalise("Travis, open notepad please"), "open notepad")
        self.assertEqual(quick.normalise("uh can you can you open the calculator"), "open the calculator")
        self.assertEqual(quick.normalise("hmm what is 2 plus 2"), "what is 2 plus 2")

    def test_words_that_are_meant_are_left_alone(self):
        for said in ("I know that that is right", "do you know what time it is", "service the car", "open 2 2 files", "bye bye"):
            self.assertEqual(quick.as_spoken(said).lower(), said.lower() if said != "bye bye" else "bye", said)
