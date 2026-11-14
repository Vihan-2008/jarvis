"""Hearing and speaking: Whisper for listening, ElevenLabs for a natural voice. Both optional.

Listening (speech to text), best available first:
- Whisper. OpenAI's Whisper large v3 model, run by Groq (free key) or OpenAI's own service (paid key).
  The window records what you say and sends the finished sentence here; text comes back in well
  under a second.
- ElevenLabs live transcription, which shows the words while you are still speaking.
- The speech recognition built into the browser, which needs no key at all.
Speaking (text to speech): ElevenLabs when a key is saved, otherwise the browser's own voices.

Keys never leave this service. The window only ever receives one-time ElevenLabs passes that expire
after fifteen minutes, so nothing on the page can reveal or reuse a key.
"""
from __future__ import annotations

import base64
import http.client
import json
import os
import re
import secrets as _rand
import struct
import subprocess
import threading
import time
import urllib.parse
from collections.abc import Iterator

from jcc import secrets
from jcc.redact import redact, register_secret
from jcc.vault import atomic_write

TTS_MODELS = {"eleven_v4_turbo": "Most natural", "eleven_flash_v2_5": "Fastest", "eleven_v3_conversational": "Most expressive"}
STT_MODELS = ("scribe_v3_live", "scribe_v2_realtime")
WHISPER = {
    "groq": {"base": "https://api.groq.com/openai/v1", "model": "whisper-large-v3-turbo", "label": "Whisper large v3 (Groq, free)"},
    "openai": {"base": "https://api.openai.com/v1", "model": "gpt-transcribe", "label": "OpenAI transcription"},
}
LISTEN = ("auto", "whisper", "eleven", "browser")
SPEAK = ("auto", "eleven", "browser")
LANGUAGES = {"en": "English", "auto": "Any language (automatic)", "hi": "Hindi", "es": "Spanish", "fr": "French", "de": "German",
             "it": "Italian", "pt": "Portuguese", "nl": "Dutch", "ru": "Russian", "ja": "Japanese", "ko": "Korean", "zh": "Chinese",
             "ar": "Arabic", "tr": "Turkish", "pl": "Polish", "id": "Indonesian", "bn": "Bengali", "ta": "Tamil", "te": "Telugu",
             "mr": "Marathi", "gu": "Gujarati", "pa": "Punjabi", "ur": "Urdu", "kn": "Kannada", "ml": "Malayalam"}
DEFAULTS = {"voice_id": "", "voice_name": "", "tts_model": "eleven_v4_turbo", "stt_model": "scribe_v3_live", "speed": 1.0,
            "listen": "auto", "speak": "auto", "language": "en", "words": "", "wake": True, "barge_in": True, "sounds": True,
            "duck": True,                    # turn the PC's own sound down while JARVIS listens after its name, so a film does not drown the request
            "mic": "", "speaker": ""}          # the names of a chosen microphone and speakers; "" is the Windows default
PREFERRED_VOICES = ("George", "Daniel", "Brian", "Will", "Roger", "Chris", "Eric", "Sarah", "Alice", "Matilda")
PCM_RATE, MIC_RATE = 24000, 16000
MAX_SPEECH_BYTES, MAX_FILE_BYTES = 4_000_000, 25_000_000
AUDIO_TYPES = {"wav": "audio/wav", "mp3": "audio/mpeg", "m4a": "audio/mp4", "mp4": "video/mp4", "mpeg": "audio/mpeg", "mpga": "audio/mpeg",
               "ogg": "audio/ogg", "webm": "audio/webm", "flac": "audio/flac"}
# What Whisper tends to "hear" in silence or noise. Dropped only when the model itself doubts there was speech.
_PHANTOMS = {"", "you", "thank you", "thanks", "thanks for watching", "thank you for watching", "bye", "the end", "please subscribe",
             "subtitles by the amara org community", "so", "okay", "jarvis"}
_cache: dict[str, tuple[float, object]] = {}


class SpeechError(ValueError):
    """A problem worth showing to the owner in plain words."""

    busy = False   # True when the service asked us to slow down; trying again shortly is reasonable


# ---------------------------------------------------------------------- settings
def settings(cfg) -> dict:
    path = cfg.state_dir / "speech.json"
    try:
        saved = json.loads(path.read_text("utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        saved = {}
    out = dict(DEFAULTS)
    try:
        _apply(out, saved if isinstance(saved, dict) else {}, strict=False)
    except SpeechError:
        pass
    return out


def _apply(current: dict, values: dict, strict: bool) -> None:
    for name, value in values.items():
        if name == "voice_id" and isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9]{8,40}", value):
            current["voice_id"] = value
        elif name == "voice_name" and isinstance(value, str):
            current["voice_name"] = redact(value)[:60]
        elif name == "tts_model" and value in TTS_MODELS:
            current["tts_model"] = value
        elif name == "stt_model" and value in STT_MODELS:
            current["stt_model"] = value
        elif name == "listen" and value in LISTEN:
            current["listen"] = value
        elif name == "speak" and value in SPEAK:
            current["speak"] = value
        elif name == "language" and value in LANGUAGES:
            current["language"] = value
        elif name == "words" and isinstance(value, str):
            current["words"] = redact(" ".join(value.split()))[:300]
        elif name in ("wake", "barge_in", "sounds", "duck") and isinstance(value, bool):
            current[name] = value
        elif name in ("mic", "speaker") and isinstance(value, str):
            from jcc.sound import plain
            current[name] = plain(value)
        elif name == "speed" and isinstance(value, (int, float)) and not isinstance(value, bool):
            current["speed"] = max(0.7, min(1.2, float(value)))
        elif strict:
            raise SpeechError("Unknown speech setting.")


def configure(cfg, values) -> dict:
    if not isinstance(values, dict):
        raise SpeechError("Invalid speech settings.")
    current = settings(cfg)
    _apply(current, values, strict=True)
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(cfg.state_dir / "speech.json", json.dumps(current))
    return current


# ---------------------------------------------------------------------- talking to the services
def base() -> str:
    """The ElevenLabs address. Tests point JCC_ELEVENLABS_BASE at a local stand-in."""
    return (os.environ.get("JCC_ELEVENLABS_BASE") or "https://api.elevenlabs.io").rstrip("/")


def whisper_base(which: str) -> str:
    return (os.environ.get("JCC_WHISPER_BASE") or WHISPER[which]["base"]).rstrip("/")


def key() -> str | None:
    return secrets.get("elevenlabs")


def whisper_provider() -> tuple[str, str] | None:
    """(service, key) for Whisper: the free Groq key first, then an OpenAI key."""
    for which in WHISPER:
        secret = secrets.get(which)
        if secret:
            return which, secret
    return None


class _Pool:
    """Keeps a couple of connections open so each sentence does not pay for a new secure handshake."""

    def __init__(self):
        self.idle: dict[tuple, list] = {}
        self.lock = threading.Lock()

    def take(self, address: str):
        parsed = urllib.parse.urlparse(address)
        name = (parsed.scheme, parsed.hostname, parsed.port)
        with self.lock:
            stack = self.idle.get(name, [])
            while stack:
                connection, at = stack.pop()
                if time.time() - at < 45:
                    return name, connection, True
                connection.close()
        maker = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        return name, maker(parsed.hostname, parsed.port, timeout=30), False

    def give(self, name, connection) -> None:
        with self.lock:
            stack = self.idle.setdefault(name, [])
            if len(stack) < 2:
                stack.append((connection, time.time()))
                return
        connection.close()

    def clear(self) -> None:
        with self.lock:
            for stack in self.idle.values():
                for connection, _ in stack:
                    connection.close()
            self.idle.clear()


_pool = _Pool()


def _request(address: str, method: str, path: str, headers: dict, body: bytes | None, timeout: float, who: str):
    prefix = urllib.parse.urlparse(address).path.rstrip("/")
    for attempt in (0, 1):
        name, connection, reused = _pool.take(address)
        connection.timeout = timeout
        try:
            if connection.sock:
                connection.sock.settimeout(timeout)
            connection.request(method, prefix + path, body=body, headers={"User-Agent": "jarvis-command/1.0", "Accept": "*/*", **headers})
            return name, connection, connection.getresponse()
        except (http.client.HTTPException, OSError):
            connection.close()
            if not reused or attempt:   # a kept connection may have gone stale: one fresh try
                raise SpeechError(f"Could not reach {who}. Check your internet connection.") from None
    raise SpeechError(f"Could not reach {who}.")


def _finish(name, connection, response, limit: int = 4_000_000) -> bytes:
    try:
        raw = response.read(limit)
        if response.read(1):          # more than we accept: do not reuse this connection
            connection.close()
        else:
            _pool.give(name, connection)
        return raw
    except (http.client.HTTPException, OSError):
        connection.close()
        raise SpeechError("The connection was lost. Try again.") from None


def _explain(status: int, body: bytes, who: str = "ElevenLabs") -> str:
    detail = ""
    try:
        data = json.loads(body.decode("utf-8", errors="replace") or "{}")
        inner = (data.get("detail") or data.get("error")) if isinstance(data, dict) else None
        detail = str((inner.get("message") or inner.get("status") or "") if isinstance(inner, dict) else inner or "")
    except ValueError:
        pass
    low = detail.lower()
    if "quota" in low or "credits" in low or status == 402:   # checked first: ElevenLabs reports a used-up allowance as "not authorised"
        return f"Your {who} allowance is used up for now. JARVIS will use the built-in alternative until it renews."
    if status == 401 or "invalid_api_key" in low or "invalid api key" in low:
        return f"{who} did not accept the key. Check that you copied all of it."
    if "missing_permissions" in low or status == 403:
        return f"This {who} key is not allowed to do that." + (" Create a key with Text to Speech, Speech to Text and Voices enabled." if who == "ElevenLabs" else "")
    if status == 429:
        return f"{who} is busy right now. Try again in a moment."
    if status == 404 or "voice_not_found" in low:
        return "That voice is no longer available. Choose another voice." if who == "ElevenLabs" else f"{who} does not know that model."
    if status == 413:
        return "That recording is too large (the limit is 25 MB)."
    return f"{who} could not do that" + (": " + redact(detail)[:140] if detail else f" (error {status}).")


def _json(address: str, method: str, path: str, headers: dict, body: bytes | None = None, timeout: float = 20.0, who: str = "ElevenLabs") -> dict:
    name, connection, response = _request(address, method, path, headers, body, timeout, who)
    raw = _finish(name, connection, response)
    if response.status >= 400:
        problem = SpeechError(_explain(response.status, raw[:4000], who))
        problem.busy = response.status == 429
        raise problem
    try:
        data = json.loads(raw.decode("utf-8") or "{}")
    except ValueError:
        raise SpeechError(f"{who} sent an answer JARVIS could not read.") from None
    return data if isinstance(data, dict) else {"data": data}


def _eleven(method: str, path: str, secret: str, body: dict | None = None, timeout: float = 20.0) -> dict:
    return _json(base(), method, path, {"xi-api-key": secret, "Content-Type": "application/json"},
                 None if body is None else json.dumps(body).encode(), timeout)


def _need_key() -> str:
    secret = key()
    if not secret:
        raise SpeechError("Add your ElevenLabs key in Voice and assistant first.")
    return secret


def warm() -> None:
    """Open the secure connections ahead of time, so the first sentence is not slowed by the handshake."""
    targets = ([base()] if key() else []) + ([whisper_base(whisper_provider()[0])] if whisper_provider() else [])
    for address in targets:
        try:
            name, connection, reused = _pool.take(address)
            if not reused:
                connection.connect()
            _pool.give(name, connection)
        except (http.client.HTTPException, OSError):
            pass


# ---------------------------------------------------------------------- keys
def save_key(cfg, value, which: str = "elevenlabs") -> dict:
    """Check a key with its service, then keep it in Windows Credential Manager only."""
    value = str(value or "").strip()
    if which not in ("elevenlabs", "groq", "openai"):
        raise SpeechError("Unknown key.")
    if not re.fullmatch(r"[A-Za-z0-9_\-]{20,220}", value):
        raise SpeechError("That does not look like a key. Copy it again from the service's API Keys page.")
    register_secret(value)
    if which == "elevenlabs":
        _eleven("GET", "/v2/voices?page_size=1", value)
    else:
        _json(whisper_base(which), "GET", "/models", {"Authorization": "Bearer " + value}, who=which.title())
    secrets.store(which, value)
    _cache.clear()
    return status(cfg)


def forget_key(cfg, which: str = "elevenlabs") -> dict:
    if which not in ("elevenlabs", "groq", "openai"):
        raise SpeechError("Unknown key.")
    secrets.delete(which)
    _cache.clear()
    return status(cfg)


def _cached(name: str, seconds: float, make):
    at, value = _cache.get(name, (0.0, None))
    if value is None or time.time() - at > seconds:
        value = make()
        _cache[name] = (time.time(), value)
    return value


# ---------------------------------------------------------------------- listening with Whisper
def wav(pcm: bytes, rate: int = MIC_RATE) -> bytes:
    """Wrap raw 16-bit mono sound in a WAV header."""
    return b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) + b"data" + struct.pack("<I", len(pcm)) + pcm


def _multipart(fields: list[tuple[str, str]], name: str, audio: bytes, kind: str) -> tuple[bytes, str]:
    edge = "----jarvis" + _rand.token_hex(12)
    parts = [f'--{edge}\r\nContent-Disposition: form-data; name="{field}"\r\n\r\n{" ".join(str(value).split())}\r\n'.encode("utf-8")
             for field, value in fields if str(value).strip()]
    safe = re.sub(r"[^\w.\-]", "_", name)[-60:] or "speech.wav"
    parts.append(f'--{edge}\r\nContent-Disposition: form-data; name="file"; filename="{safe}"\r\nContent-Type: {kind}\r\n\r\n'.encode("utf-8") + audio + b"\r\n")
    parts.append(f"--{edge}--\r\n".encode())
    return b"".join(parts), "multipart/form-data; boundary=" + edge


def _plain(text: str) -> str:
    return re.sub(r"[^\w\s]", "", str(text).lower()).strip()


def hint_text(*sources: str) -> str:
    """Names and unusual words for Whisper, each said once. A repeated word makes Whisper "hear" that word."""
    seen, kept = set(), []
    for source in sources:
        for word in re.split(r"[,;\n]+", str(source or "")):
            word = " ".join(word.split()).strip(" .")
            if word and word.lower() not in seen and len(kept) < 40:
                seen.add(word.lower())
                kept.append(word)
    return (", ".join(kept) + ".")[:600] if kept else ""


def clean_transcript(data: dict, hint: str = "") -> str:
    """The words Whisper heard, without the things it invents when there was no real speech."""
    segments = data.get("segments") if isinstance(data.get("segments"), list) else None
    doubt = 0.0
    if segments:
        kept = []
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            silent, sure = float(segment.get("no_speech_prob") or 0), float(segment.get("avg_logprob") or 0)
            doubt = max(doubt, silent)
            if silent > 0.6 and sure < -0.8:
                continue
            kept.append(str(segment.get("text", "")))
        text = "".join(kept)
    else:
        text = str(data.get("text", ""))
    text = " ".join(text.split())
    plain = _plain(text)
    if plain in _PHANTOMS and (doubt > 0.3 or float(data.get("duration") or 9) < 0.7):
        return ""
    said, hinted = plain.split(), set(_plain(hint).split())
    if len(said) > 1 and hinted and all(word in hinted for word in said):   # only the hint echoed back: nothing was really heard
        return ""
    return text


def transcribe(cfg, audio: bytes, name: str = "speech.wav", language: str | None = None, prompt: str = "", names: bool = False) -> dict:
    """Text for a recording. `audio` is a WAV or any common sound or video file up to 25 MB.

    `names`: this is someone talking to JARVIS, so tell Whisper how its name is spelled. Not for dictation or recordings:
    a name Whisper has been told is also the word it writes down when it hears only a noise."""
    provider = whisper_provider()
    if not provider:
        raise SpeechError("Whisper needs a key. Add a free Groq key (or an OpenAI key) in Voice and assistant.")
    if not audio or len(audio) > MAX_FILE_BYTES:
        raise SpeechError("There is no sound to transcribe, or the recording is larger than 25 MB.")
    which, secret = provider
    current = settings(cfg)
    spoken = language if language in LANGUAGES else current["language"]
    kind = AUDIO_TYPES.get(name.rsplit(".", 1)[-1].lower(), "audio/wav")
    hint = hint_text("JARVIS" if names else "", prompt, current["words"])
    if which == "openai":
        fields = [("model", WHISPER[which]["model"]), ("prompt", hint)] + ([("languages[]", spoken)] if spoken != "auto" else [])
    else:
        fields = [("model", WHISPER[which]["model"]), ("response_format", "verbose_json"), ("temperature", "0"), ("prompt", hint)] + \
                 ([("language", spoken)] if spoken != "auto" else [])
    body, content_type = _multipart(fields, name, audio, kind)
    started = time.time()
    data = _json(whisper_base(which), "POST", "/audio/transcriptions", {"Authorization": "Bearer " + secret, "Content-Type": content_type},
                 body, timeout=120 if len(audio) > 2_000_000 else 30, who="Groq" if which == "groq" else "OpenAI")
    found = data.get("language") or ((data.get("languages") or [{}])[0].get("code") if isinstance(data.get("languages"), list) and data.get("languages") else "")
    return {"text": redact(clean_transcript(data, hint)), "language": str(found or "")[:20], "seconds": round(time.time() - started, 2),
            "engine": which, "audio_seconds": data.get("duration")}


def hear(cfg, pcm: bytes, prompt: str = "", names: bool = True) -> dict:
    """Text for what the microphone recorded (raw 16-bit, 16 kHz, mono)."""
    if len(pcm) < MIC_RATE // 5 * 2:
        return {"text": "", "engine": "", "seconds": 0}
    if len(pcm) > MAX_SPEECH_BYTES:
        raise SpeechError("That was too long to take in at once (about two minutes is the limit).")
    return transcribe(cfg, wav(pcm[:len(pcm) // 2 * 2]), "speech.wav", prompt=prompt, names=names)


def sample_speech(text: str, run=None, rate: int = MIC_RATE) -> bytes:
    """A spoken sentence made by Windows' own voice, as raw 16-bit sound. Used to check listening end to end."""
    encoded = base64.b64encode(str(text)[:400].encode("utf-16-le")).decode()
    script = ("Add-Type -AssemblyName System.Speech;$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;$m=New-Object System.IO.MemoryStream;"
              f"$f=New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo({int(rate)},[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,"
              "[System.Speech.AudioFormat.AudioChannel]::Mono);$s.SetOutputToAudioStream($m,$f);"
              f"$s.Speak([System.Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('{encoded}')));$s.Dispose();[Convert]::ToBase64String($m.ToArray())")
    if run:
        out = run(script)
    else:
        out = subprocess.run(["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True,
                             timeout=40, stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0).stdout
    try:
        return base64.b64decode(out.strip())
    except ValueError:
        return b""


# ---------------------------------------------------------------------- speaking with ElevenLabs
class LocalVoice:
    """Windows' own voice, kept ready in a hidden helper so that a sentence starts without a pause.

    Used when particular speakers are chosen. The voice built into the window can only play on the Windows default
    device, so the sentence is made here instead and the window plays it on the speakers it was told to use."""

    SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
try {
  Add-Type -AssemblyName System.Speech
  $voice = New-Object System.Speech.Synthesis.SpeechSynthesizer
  $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(24000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
} catch { [Console]::Out.WriteLine('!' + [string]$_.Exception.Message); [Console]::Out.Flush(); exit 3 }
[Console]::Out.WriteLine('ready'); [Console]::Out.Flush()
$spoken = ''
while ($true) {
  $line = [Console]::In.ReadLine()
  if ($line -eq $null) { break }
  try {
    $parts = $line.Split(' ')
    $voice.Rate = [int]$parts[0]
    if ($parts[1] -ne '-' -and $parts[1] -ne $spoken) {
      $spoken = $parts[1]
      try { $voice.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::NotSet, [System.Speech.Synthesis.VoiceAge]::NotSet, 0, [System.Globalization.CultureInfo]$spoken) } catch { }
    }
    $sound = New-Object System.IO.MemoryStream
    $voice.SetOutputToAudioStream($sound, $format)
    $voice.Speak([System.Text.Encoding]::Unicode.GetString([Convert]::FromBase64String($parts[2])))
    $voice.SetOutputToNull()
    [Console]::Out.WriteLine([Convert]::ToBase64String($sound.ToArray()))
  } catch { [Console]::Out.WriteLine('!' + [string]$_.Exception.Message) }
  [Console]::Out.Flush()
}
'''

    def __init__(self):
        self.proc, self.lock, self.used = None, threading.Lock(), 0.0

    def _line(self, proc, seconds: float) -> str:
        """One line from the helper, or "" if it takes too long (the helper is then stopped)."""
        timer = threading.Timer(seconds, proc.kill)
        timer.daemon = True
        timer.start()
        try:
            return proc.stdout.readline().strip()
        except (OSError, ValueError):
            return ""
        finally:
            timer.cancel()

    def _start(self):
        if os.name != "nt":
            raise SpeechError("Windows' own voice is available on Windows only.")
        encoded = base64.b64encode(self.SCRIPT.encode("utf-16-le")).decode()
        proc = subprocess.Popen(["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", bufsize=1,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        first = self._line(proc, 25)
        if first != "ready":
            proc.kill()
            raise SpeechError("Windows' own voice could not be started" + (": " + first[1:200] if first.startswith("!") else "."))
        return proc

    def say(self, text: str, rate: int = 0, language: str = "") -> bytes:
        """`text` as raw 16-bit 24 kHz mono sound."""
        text = " ".join(str(text).split())[:5000]
        if not text:
            return b""
        request = "%d %s %s\n" % (max(-10, min(10, int(rate))), language if re.fullmatch(r"[a-z]{2}(-[A-Za-z]{2})?", language or "") else "-",
                                  base64.b64encode(text.encode("utf-16-le")).decode())
        with self.lock:
            for attempt in (1, 2):                      # the helper is closed after a while unused; one fresh start is normal
                try:
                    if not self.proc or self.proc.poll() is not None:
                        self.proc = self._start()
                    self.proc.stdin.write(request)
                    self.proc.stdin.flush()
                    answer = self._line(self.proc, 40)
                except OSError:
                    answer = ""
                self.used = time.time()
                if answer and not answer.startswith("!"):
                    try:
                        return base64.b64decode(answer)
                    except ValueError:
                        answer = ""
                if answer.startswith("!"):
                    raise SpeechError("Windows' own voice could not say that: " + answer[1:200])
                self.close_now()
            raise SpeechError("Windows' own voice did not answer.")

    def close_now(self) -> None:
        proc, self.proc = self.proc, None
        if proc:
            try:
                proc.kill()
                proc.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                pass
            for pipe in (proc.stdin, proc.stdout):
                try:
                    pipe.close()
                except (OSError, ValueError):
                    pass

    def idle_check(self, seconds: float = 240) -> None:
        """Let go of the helper (and its memory) when nothing has been said for a while."""
        with self.lock:
            if self.proc and time.time() - self.used >= seconds:
                self.close_now()


local_voice = LocalVoice()


def local_speech(cfg, text: str) -> bytes:
    """`text` in Windows' own voice, at the speed chosen in the settings, as raw 16-bit 24 kHz mono sound."""
    current = settings(cfg)
    spoken = current["language"] if current["language"] not in ("auto", "en") else ""
    return local_voice.say(text, round((current["speed"] - 1.0) * 10), spoken)


def voices(cfg) -> list[dict]:
    secret = _need_key()

    def load():
        rows, token = [], ""
        for _ in range(3):
            data = _eleven("GET", "/v2/voices?page_size=100&include_total_count=false" + (f"&next_page_token={urllib.parse.quote(token)}" if token else ""), secret)
            for voice in data.get("voices", []):
                labels = voice.get("labels") or {}
                if re.fullmatch(r"[A-Za-z0-9]{8,40}", str(voice.get("voice_id", ""))):
                    rows.append({"id": voice["voice_id"], "name": str(voice.get("name", "Voice"))[:60],
                                 "about": ", ".join(str(labels[k]) for k in ("accent", "gender", "age", "description") if labels.get(k))[:80],
                                 "kind": str(voice.get("category", ""))[:20]})
            token = data.get("next_page_token") or ""
            if not data.get("has_more") or not token:
                break
        order = {name: i for i, name in enumerate(PREFERRED_VOICES)}
        rows.sort(key=lambda v: (order.get(v["name"].split(" ")[0].split("-")[0].strip(), 99), v["name"].lower()))
        return rows
    return _cached("voices", 600, load)


def chosen_voice(cfg) -> tuple[str, str]:
    """The saved voice, or a good default from the account's voices."""
    current = settings(cfg)
    if current["voice_id"]:
        return current["voice_id"], current["voice_name"]
    rows = voices(cfg)
    if not rows:
        raise SpeechError("Your ElevenLabs account has no voices yet. Add one in ElevenLabs, then try again.")
    configure(cfg, {"voice_id": rows[0]["id"], "voice_name": rows[0]["name"]})
    return rows[0]["id"], rows[0]["name"]


def token(kind: str) -> str:
    """A one-time pass the window uses to talk to ElevenLabs directly (live listening)."""
    if kind not in ("realtime_scribe", "tts_websocket"):
        raise SpeechError("Unknown token type.")
    value = str(_eleven("POST", f"/v1/single-use-token/{kind}", _need_key(), {}).get("token", ""))
    if not value:
        raise SpeechError("ElevenLabs did not return a pass for this session.")
    register_secret(value)
    return value


def tts_stream(cfg, text: str, voice_id: str | None = None, model: str | None = None, previous: str = "") -> tuple[str, Iterator[bytes]]:
    """Speech for `text`. Returns (kind, pieces): kind is "pcm" (raw 16-bit 24 kHz mono) or "mp3"."""
    text = " ".join(str(text).split())
    if not text or len(text) > 5000:
        raise SpeechError("There is nothing to say, or it is too long to say in one go.")
    secret, current = _need_key(), settings(cfg)
    voice = voice_id if voice_id and re.fullmatch(r"[A-Za-z0-9]{8,40}", voice_id) else chosen_voice(cfg)[0]
    chosen = model if model in TTS_MODELS else current["tts_model"]
    body = {"text": text, "model_id": chosen, "voice_settings": {"speed": current["speed"]}}
    if previous.strip():
        body["previous_text"] = " ".join(previous.split())[-300:]   # keeps the tone natural from one sentence to the next
    attempts = [("pcm", chosen)] + ([("pcm", "eleven_flash_v2_5")] if chosen != "eleven_flash_v2_5" else []) + [("mp3", "eleven_flash_v2_5")]
    problem = None
    for kind, model_id in attempts:   # newer voices and raw sound are not on every plan: fall back step by step
        path = f"/v1/text-to-speech/{voice}/stream?output_format=" + (f"pcm_{PCM_RATE}" if kind == "pcm" else "mp3_44100_128")
        name, connection, response = _request(base(), "POST", path, {"xi-api-key": secret, "Content-Type": "application/json"},
                                              json.dumps({**body, "model_id": model_id}).encode(), 30, "ElevenLabs")
        if response.status < 400:
            return kind, _pieces(name, connection, response)
        raw = _finish(name, connection, response)
        problem = SpeechError(_explain(response.status, raw[:4000]))
        if response.status in (401, 402, 404, 429):
            break
    raise problem or SpeechError("ElevenLabs could not speak that.")


def _pieces(name, connection, response) -> Iterator[bytes]:
    finished = False
    try:
        while True:
            piece = response.read(4800)
            if not piece:
                finished = True
                return
            yield piece
    finally:
        if finished:
            _pool.give(name, connection)
        else:
            connection.close()


def usage(cfg) -> dict | None:
    """How much of this month's ElevenLabs allowance is used, if the key may read it."""
    secret = key()
    if not secret:
        return None

    def load():
        try:
            data = _eleven("GET", "/v1/user/subscription", secret, timeout=10)
        except SpeechError:
            return {}
        used, limit = data.get("character_count"), data.get("character_limit")
        if not isinstance(used, (int, float)) or not isinstance(limit, (int, float)) or limit <= 0:
            return {}
        return {"used": int(used), "limit": int(limit), "percent": round(100 * used / limit, 1), "plan": str(data.get("tier", ""))[:30],
                "renews": data.get("next_character_count_reset_unix")}
    return _cached("usage", 300, load) or None


# ---------------------------------------------------------------------- what the window needs to know
def engines(cfg) -> tuple[str, str]:
    """(listening, speaking) actually in use, after falling back from choices that have no key."""
    current, whisper, eleven = settings(cfg), whisper_provider(), key()
    order = {"auto": ("whisper", "eleven"), "whisper": ("whisper", "eleven"), "eleven": ("eleven", "whisper"), "browser": ()}[current["listen"]]
    listening = next((name for name in order if (whisper if name == "whisper" else eleven)), "browser")
    speaking = "eleven" if eleven and current["speak"] != "browser" else "browser"
    return listening, speaking


def status(cfg, with_usage: bool = False) -> dict:
    """Never includes a key."""
    listening, speaking = engines(cfg)
    whisper = whisper_provider()
    out = {"configured": bool(key()), "whisper": whisper[0] if whisper else "", "whisper_label": WHISPER[whisper[0]]["label"] if whisper else "",
           "keys": {name: bool(secrets.get(name)) for name in ("elevenlabs", "groq", "openai")},
           "listen": listening, "speak": speaking, "settings": settings(cfg), "models": TTS_MODELS, "languages": LANGUAGES,
           "pcm_rate": PCM_RATE, "mic_rate": MIC_RATE, "socket": base().replace("https://", "wss://").replace("http://", "ws://")}
    if with_usage and out["configured"]:
        out["usage"] = usage(cfg)
    return out


def self_test(cfg) -> dict:
    """Check listening and speaking end to end. Used by the Test button and `jcc voice-check`."""
    report: dict = {"ok": True}
    if whisper_provider():
        sentence = "Hello JARVIS, please open the calculator."
        sound = sample_speech(sentence)
        if len(sound) < MIC_RATE:
            report["listening"] = {"ok": False, "problem": "Windows could not make a test sentence."}
        else:
            try:
                heard = hear(cfg, sound)
                want, got = set(_plain(sentence).split()), set(_plain(heard["text"]).split())
                report["listening"] = {"ok": len(want & got) >= len(want) - 1, "heard": heard["text"], "seconds": heard["seconds"], "engine": heard["engine"]}
            except SpeechError as problem:
                report["listening"] = {"ok": False, "problem": str(problem)}
        report["ok"] = report["ok"] and report["listening"]["ok"]
    if key():
        started, total, first = time.time(), 0, None
        try:
            kind, pieces = tts_stream(cfg, "Voice check complete.")
            for piece in pieces:
                if first is None:
                    first = time.time() - started
                total += len(piece)
            enough = total >= (PCM_RATE // 4 if kind == "pcm" else 2000)
            report["speaking"] = {"ok": enough, "first_audio_seconds": round(first or 0, 2), "kind": kind, "voice": chosen_voice(cfg)[1],
                                  "audio_seconds": round(total / 2 / PCM_RATE, 2) if kind == "pcm" else None}
        except SpeechError as problem:
            report["speaking"] = {"ok": False, "problem": str(problem)}
        report["ok"] = report["ok"] and report["speaking"]["ok"]
    if "listening" not in report and "speaking" not in report:
        raise SpeechError("No speech service is set up yet. JARVIS is using the browser's own voice and listening.")
    return report
