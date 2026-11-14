"""Always listening for "Hey JARVIS", from anywhere, without sending anything anywhere.

Windows' own offline speech recogniser listens to the microphone on this PC and knows one thing:
the wake word. Ordinary talk is recognised as ordinary talk and dropped on the spot; it never leaves
the computer. Only a sentence that begins with the wake word is passed on: that one sentence is
transcribed properly by Whisper and given to JARVIS as a spoken request.

This runs inside the tray helper, so it works whether or not the JARVIS window is open.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import threading
import time

from jcc.vault import atomic_write

SCRIPT = r'''
param([string]$Names = 'jarvis', [string]$WaveFile = '', [int]$Parent = 0, [string]$Pipe = '')
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
function Say($o) { [Console]::Out.WriteLine((ConvertTo-Json $o -Compress)); [Console]::Out.Flush() }
try {
  Add-Type -AssemblyName System.Speech
  $info = [System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers() | Where-Object { $_.Culture.Name -like 'en-*' } | Select-Object -First 1
  if (-not $info) { Say @{ error = 'no-recognizer' }; exit 2 }
  $engine = New-Object System.Speech.Recognition.SpeechRecognitionEngine($info)
  $wake = New-Object System.Speech.Recognition.Choices
  foreach ($name in $Names.Split('|')) { foreach ($hello in @('hey ', 'ok ', 'okay ', 'hi ', 'hello ', '')) { $wake.Add($hello + $name) } }
  $only = New-Object System.Speech.Recognition.GrammarBuilder($wake); $only.Culture = $info.Culture
  $g1 = New-Object System.Speech.Recognition.Grammar($only); $g1.Name = 'wake'
  $more = New-Object System.Speech.Recognition.GrammarBuilder($wake); $more.Culture = $info.Culture; $more.AppendDictation()
  $g2 = New-Object System.Speech.Recognition.Grammar($more); $g2.Name = 'wake+'
  # Ordinary talk gets a grammar of its own, so it is recognised as itself instead of being squeezed into the wake word.
  $other = New-Object System.Speech.Recognition.DictationGrammar; $other.Name = 'other'
  # "JARVIS, stop" and the like are known as whole phrases, so they are caught reliably even while JARVIS itself is talking.
  $say = New-Object System.Speech.Recognition.Choices
  foreach ($word in @('stop', 'stop it', 'stop now', 'stop talking', 'cancel', 'cancel that', 'be quiet', 'quiet', 'enough', 'never mind', 'shut up',
                      'go to sleep', 'sleep', 'stop listening', 'end session', 'end the session', 'end', 'goodbye', 'bye')) { $say.Add($word) }
  $ctl = New-Object System.Speech.Recognition.GrammarBuilder($wake); $ctl.Culture = $info.Culture; $ctl.Append($say)
  $g3 = New-Object System.Speech.Recognition.Grammar($ctl); $g3.Name = 'ctrl'
  $engine.LoadGrammar($g1); $engine.LoadGrammar($g2); $engine.LoadGrammar($g3); $engine.LoadGrammar($other)
  $from = 'default'
  if ($WaveFile) { $engine.SetInputToWaveFile($WaveFile); $from = 'file' }
  elseif ($Pipe) {
    # A chosen microphone: JARVIS records it and passes the sound in through a private pipe. The recogniser asks a stream
    # how long it is and to rewind, which a pipe cannot answer, and it takes a short read as the end of the sound.
    try {
      Add-Type -AssemblyName System.Core
      Add-Type -TypeDefinition @'
using System; using System.IO;
public class JarvisSound : Stream {
  private readonly Stream inner;
  public JarvisSound(Stream s) { inner = s; }
  public override bool CanRead { get { return true; } }
  public override bool CanSeek { get { return false; } }
  public override bool CanWrite { get { return false; } }
  public override long Length { get { return Int64.MaxValue / 4; } }
  public override long Position { get { return 0; } set { } }
  public override void Flush() { }
  public override long Seek(long offset, SeekOrigin origin) { return 0; }
  public override void SetLength(long value) { }
  public override void Write(byte[] buffer, int offset, int count) { }
  public override int Read(byte[] buffer, int offset, int count) {
    int got = 0;
    while (got < count) { int n = inner.Read(buffer, offset + got, count - got); if (n <= 0) break; got += n; }
    return got;
  }
}
'@
      $sound = New-Object JarvisSound((New-Object System.IO.Pipes.AnonymousPipeClientStream([System.IO.Pipes.PipeDirection]::In, $Pipe)))
      $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
      $engine.SetInputToAudioStream($sound, $format); $from = 'chosen'
    } catch { $engine.SetInputToDefaultAudioDevice() }     # this PC will not allow that: Windows' default microphone still works
  }
  else { $engine.SetInputToDefaultAudioDevice() }
} catch { Say @{ error = [string]$_.Exception.Message }; exit 3 }
Say @{ ready = $true; recognizer = $info.Culture.Name; input = $from }
while ($true) {
  if ($Parent -and -not (Get-Process -Id $Parent -ErrorAction SilentlyContinue)) { break }
  try { $r = $engine.Recognize([TimeSpan]::FromSeconds(6)) } catch { Say @{ error = [string]$_.Exception.Message }; if ($from -eq 'chosen') { break }; Start-Sleep -Seconds 3; continue }
  if (-not $r) { if ($WaveFile) { break } else { continue } }
  if ($r.Grammar.Name -eq 'other') { continue }
  $sound = New-Object System.IO.MemoryStream; $r.Audio.WriteToWaveStream($sound)
  Say @{ text = [string]$r.Text; confidence = [math]::Round($r.Confidence, 3); grammar = $r.Grammar.Name; wav = [Convert]::ToBase64String($sound.ToArray()) }
}
'''
HELLO = r"(?:(?:hey|hi|ok|okay|hello|yo)[\s,]+)?"


def names(cfg) -> list[str]:
    """The words that wake JARVIS: its own name, and the name of the assistant in use."""
    found = ["jarvis"]
    try:
        from jcc.assistant import active_assistant
        extra = re.sub(r"[^a-z ]", "", active_assistant(cfg)["name"].lower()).strip()
        if len(extra) >= 3 and extra not in found:
            found.append(extra)
    except Exception:  # noqa: BLE001 - the name is optional here
        pass
    return found


def mentions(text: str, wake_names: list[str]) -> bool:
    """Is the wake word anywhere in this? (For a clip that ends with the name: someone may have been talking just before it.)"""
    spelled = "|".join([*(re.escape(n) for n in wake_names), "jarvice", "jervis", "javis", "jarvas", "jarves", "jarvus"])
    return bool(re.search(r"\b(?:" + spelled + r")\b", str(text), re.I))


DANGLING = re.compile(r"\b(?:for|to|and|or|the|a|an|of|in|on|at|with|by|from|about|that|my|is|are|then|but|if|as|into|called|named)[.!?…]*$", re.I)


def complete(text: str) -> bool:
    """Does this read like a finished sentence? ("Set a timer for." does not: there is more to come.)"""
    text = str(text).strip()
    return bool(re.search(r"[.!?…][\"')\]]?$", text)) and not DANGLING.search(text) and len(text.split()) >= 2


def first_sentence(text: str) -> str:
    """The first sentence of what was written down, if it is a whole one ("Pause the movie." from "Pause the movie. I told you")."""
    found = re.match(r"\s*(.{3,200}?[.!?])(?:\s|$)", text or "")
    return found.group(1).strip() if found and complete(found.group(1)) else ""


def _speakers():
    """(read, write) for this computer's own speaker volume, 0 to 100."""
    from jcc import system
    if system.kind() == "mac":
        from jcc import mac
        return mac.volume, mac.set_volume
    from jcc import winctl
    return winctl.volume, winctl.set_volume


NEEDS_MODEL = ('On a Mac, "Hey JARVIS" is heard by a small model that runs on the Mac itself, and it is not installed yet. '
               "Run the JARVIS installer again and say yes to the wake word (or see docs/PLATFORMS.md). Talking to JARVIS in its window works without it.")


def restore_volume(cfg, volume=None) -> bool:
    """Put the speaker volume back if JARVIS turned it down to listen and then never put it back (it was closed or
    crashed in those few seconds). Called when the helper starts. True if it did."""
    path = cfg.state_dir / "listening-volume.json"
    try:
        kept = json.loads(path.read_text("utf-8"))
        read, write = volume or _speakers()
        if isinstance(kept, dict) and int(read()) == int(kept.get("low", -1)) and 0 < int(kept["volume"]) <= 100:
            write(int(kept["volume"]))
            return True
    except Exception:  # noqa: BLE001 - nothing to put back, or it cannot be read: leave the volume as it is
        pass
    finally:
        path.unlink(missing_ok=True)
    return False


def split(text: str, wake_names: list[str]) -> str | None:
    """What was asked after the wake word ("" if only the wake word was said), or None if the sentence does not start with it."""
    spelled = "|".join([*(re.escape(n) for n in wake_names), "jarvice", "jervis", "javis", "jarvas", "jarves", "jarvus"])
    match = re.match(r"^\W*" + HELLO + r"(?:" + spelled + r")\b[\s,.!?:;-]*(.*)$", " ".join(str(text).split()), re.I | re.S)
    return match.group(1).strip() if match else None


class Listener:
    """The background recogniser (a hidden PowerShell process). Calls `heard(hit)` for each sentence that starts with the wake word."""

    def __init__(self, heard, wake_names: list[str], wave_file: str = "", device: int | None = None, microphone=None):
        self.heard, self.names, self.wave_file = heard, list(wake_names), wave_file
        self.proc, self.ready, self.problem = None, threading.Event(), ""
        # A chosen microphone (Windows' number for it): recorded here and passed to the recogniser. None is the Windows default,
        # which the recogniser opens by itself.
        self.device, self.make_microphone, self.mic, self.feed, self.input = device, microphone, None, None, ""

    def start(self) -> None:
        if os.name != "nt":
            # Windows' own recogniser is what this class starts. Elsewhere the name is heard by the on-device model alone
            # (jcc/wakeword.py), which Ears starts beside this; this sentence is only shown when that is missing too.
            from jcc import system
            raise ValueError(NEEDS_MODEL if system.kind() == "mac" else "The wake word works on Windows and on a Mac only.")
        encoded = base64.b64encode(SCRIPT.encode("utf-16-le")).decode()
        theirs, startup = None, None
        if self.device is not None and not self.wave_file:
            try:
                theirs = self._open_microphone()
                startup = subprocess.STARTUPINFO()
                startup.lpAttributeList = {"handle_list": [theirs]}     # the recogniser receives this one handle and nothing else
            except (ValueError, OSError):
                theirs = None                                           # it cannot be opened: listen on the Windows default instead
        # The script is passed whole, so nothing is written to disk and Windows' script-file rules do not apply.
        argv = ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
                "& ([scriptblock]::Create([System.Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('%s')))) -Names '%s' -WaveFile '%s' -Parent %d -Pipe '%s'"
                % (encoded, "|".join(n.replace("'", "") for n in self.names), self.wave_file.replace("'", "''"), 0 if self.wave_file else os.getpid(),
                   int(theirs) if theirs is not None else "")]
        try:
            self.proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                                         errors="replace", bufsize=1, creationflags=subprocess.CREATE_NO_WINDOW, **({"startupinfo": startup} if startup else {}))
        finally:
            if theirs is not None:
                import _winapi
                _winapi.CloseHandle(theirs)
        threading.Thread(target=self._read, args=(self.proc,), daemon=True, name="wake-word").start()

    def _open_microphone(self):
        """Start recording the chosen microphone into a private pipe. Returns the recogniser's end of that pipe."""
        import _winapi
        import msvcrt
        theirs, ours = _winapi.CreatePipe(None, 1 << 17)
        os.set_handle_inheritable(theirs, True)
        feed = msvcrt.open_osfhandle(ours, 0)

        def write(piece: bytes) -> None:
            view = memoryview(piece)
            while view:
                view = view[os.write(feed, view):]      # fails once the recogniser has gone, which stops the recording too

        if self.make_microphone:
            mic = self.make_microphone(self.device)
        else:
            from jcc.sound import Microphone
            mic = Microphone(self.device, 1600)
        try:
            mic.start(write)
        except Exception:
            os.close(feed)
            _winapi.CloseHandle(theirs)
            raise
        self.mic, self.feed = mic, feed
        return theirs

    def _read(self, proc) -> None:
        for line in proc.stdout:
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if data.get("ready"):
                self.input = str(data.get("input", ""))
                self.ready.set()
            elif data.get("error"):
                self.problem = str(data["error"])[:200]
                self.ready.set()
            elif data.get("wav"):
                try:
                    self.heard({"text": str(data.get("text", "")), "confidence": float(data.get("confidence") or 0), "grammar": str(data.get("grammar", "")),
                                "wav": base64.b64decode(data["wav"])})
                except Exception:  # noqa: BLE001 - one bad sentence must not stop the listening
                    pass
        self.ready.set()
        try:
            proc.stdout.close()
        except OSError:
            pass

    def running(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    def stop(self) -> None:
        proc, self.proc = self.proc, None
        if proc and proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                pass
        mic, feed, self.mic, self.feed = self.mic, self.feed, None, None
        if mic:
            threading.Thread(target=mic.stop, daemon=True, name="wake-microphone-stop").start()   # it may be waiting on the pipe; never hold up the caller
        if feed is not None:
            try:
                os.close(feed)
            except OSError:
                pass


class Ears:
    """Decides what to do when the wake word is heard, and keeps the listener in step with the settings."""

    def __init__(self, cfg, deliver, notify=None, listener=None, recorder=None, hear=None, beep=None, busy=None, device=None,
                 control=None, attend=None, listen=None, sound=None, spotter=None, name_said=None, volume=None):
        self.cfg, self.deliver, self.notify = cfg, deliver, notify or (lambda text: None)
        self.make_listener, self.make_recorder, self.hear, self.beep = listener or Listener, recorder, hear, beep or (lambda pitch: None)
        self.busy = busy or (lambda: False)          # True while JARVIS is already in a spoken conversation (so it never answers itself)
        self.listener, self.names, self.handling, self.lock = None, [], False, threading.Lock()
        self.problem, self.retry_at, self.started_at = "", 0.0, 0.0
        self.find_device, self.device = device or self._chosen, None     # which microphone: Windows' number for a chosen one, or None for the default
        # control(word): "JARVIS, stop / go to sleep / end session".  attend(): its name was said, show that it is listening.
        # listen(): nothing followed the name, so the session listens by itself.
        self.control, self.attend, self.listen = control, attend, listen
        # name_said(at): its name was heard while a spoken conversation is going on. The window that holds the conversation
        # has the microphone; it is told when, and takes what is being said from that moment.
        self.name_said = name_said
        self.volume = volume                         # (reads, sets) the speaker volume; None: Windows' own (jcc/winctl.py)
        self.peek_after, self.peek_every = 0.9, 1.6  # in a room where no end can be heard: when what was said is first written down, and how often after
        self.sound = sound                           # tells the PC's own sound (a video, music) from a person: jcc/pcsound.py
        # The neural wake word (jcc/wakeword.py), where this PC can run it. It hears the name far better than Windows' own
        # recogniser, which keeps running beside it for "JARVIS, stop" and for an assistant with another name.
        # spotter: None = use it if it can run (never in tests, which bring their own listener); False = never; or a function
        # (heard, device) -> listener.
        self.make_spotter = spotter if spotter is not None else (None if listener is None else False)
        self.neural, self.neural_device, self.neural_retry, self.controlled = None, None, 0.0, ("", 0.0)

    def _chosen(self):
        from jcc import sound
        return sound.chosen_input(self.cfg)

    @property
    def note(self) -> str:
        """Something the owner should know that is not a failure."""
        listener = self.listener
        if listener and self.device is not None and getattr(listener, "input", "") == "default":
            return "The chosen microphone could not be used for the wake word on this PC, so the Windows default microphone is listening for it."
        return ""

    def microphone(self) -> str:
        """The name of the chosen microphone the wake word is listening on ("" while it is the Windows default)."""
        listener = self.listener
        if not listener or self.device is None or getattr(listener, "input", "") != "chosen":
            return ""
        try:
            from jcc import sound
            return sound.inputs()[self.device]
        except (IndexError, OSError):
            return ""

    def wanted(self) -> bool:
        from jcc import speech
        return bool(speech.settings(self.cfg)["wake"]) and (self.hear is not None or bool(speech.whisper_provider()))

    def sync(self) -> bool:
        """Start, stop or restart the listener so it matches the settings. Returns whether it is listening."""
        with self.lock:
            wanted, current = self.wanted(), names(self.cfg)
            device = self.find_device() if wanted else None
            neural = self._sync_neural(wanted, device)
            if self.listener and not self.listener.running():
                # It stopped by itself. If that happened straight away it cannot run here (for example Windows' English
                # speech recognition is not installed): say why once, and try again only every ten minutes.
                why = getattr(self.listener, "problem", "")
                if why or time.time() - self.started_at < 15:
                    self.problem = ("Windows' English speech recognition is not installed on this PC, so the wake word cannot be used. "
                                    "The Talk shortcut still works.") if why == "no-recognizer" else \
                        "The wake word could not start" + (": " + why if why else ". The microphone may be in use or switched off.")
                    self.retry_at = time.time() + 600
                    if neural:
                        self.problem = ""                # the neural wake word is listening: nothing is wrong for the owner
                    else:
                        self.notify(self.problem)
                self.listener = None
            if self.listener and (not wanted or current != self.names or device != self.device):   # switched off, renamed, or another microphone
                self.listener.stop()
                self.listener = None
            if not wanted:
                self.problem, self.retry_at = "", 0.0
            if wanted and not self.listener and time.time() >= self.retry_at:
                self.names, self.device = current, device
                listener = self.make_listener(self._heard, current, **({} if device is None else {"device": device}))
                try:
                    listener.start()
                except (ValueError, OSError) as problem:
                    self.problem, self.retry_at = ("" if neural else str(problem)), time.time() + 600
                    if not neural:
                        self.notify(self.problem)
                    return neural
                self.listener, self.started_at = listener, time.time()
                if getattr(listener, "ready", None) is not None and listener.ready.wait(0) and not getattr(listener, "problem", ""):
                    self.problem = ""
            if self.listener and time.time() - self.started_at >= 15:
                self.problem = ""
            return bool(self.listener) or neural

    def _sync_neural(self, wanted: bool, device) -> bool:
        """Start, stop or restart the neural wake word. Returns whether it is listening."""
        make = self.make_spotter
        if make is False:
            return False
        if self.neural and (not wanted or device != self.neural_device or not self.neural.running()):
            self.neural.stop()
            self.neural = None
        if wanted and not self.neural and time.time() >= self.neural_retry:
            try:
                if make is None:
                    from jcc import wakeword
                    files = wakeword.parts(self.cfg)
                    if not files:
                        self.neural_retry = time.time() + 3600      # its parts are not installed on this PC
                        return False
                    neural = wakeword.NeuralListener(self._heard, files, device=device, sound=self.sound)
                else:
                    neural = make(self._heard, device)
                neural.start()
            except Exception:  # noqa: BLE001 - whatever is wrong with it, Windows' own recogniser still listens
                self.neural_retry = time.time() + 600
                return False
            self.neural, self.neural_device = neural, device
        return bool(self.neural)

    @property
    def engine(self) -> str:
        """Which wake word is listening: "neural" (the on-device model), "windows" (Windows' own recogniser) or ""."""
        return "neural" if self.neural else "windows" if self.listener else ""

    def stop(self) -> None:
        with self.lock:
            if self.listener:
                self.listener.stop()
                self.listener = None
            if self.neural:
                self.neural.stop()
                self.neural = None

    def _transcribe(self, sound: bytes, wav: bool, plain: bool = False) -> str:
        """plain: no name is suggested to Whisper (a name it has been told is also what it writes down for a noise)."""
        if self.hear:
            return self.hear(sound)
        from jcc import speech
        hint = "" if plain else ", ".join(n.title() for n in self.names[1:])
        return (speech.transcribe(self.cfg, sound, "wake.wav", prompt=hint, names=not plain) if wav else speech.hear(self.cfg, sound, hint, names=not plain))["text"]

    def _really_the_name(self, hit: dict) -> bool:
        """A match by the neural wake word that was not a certain one: checked before anything happens."""
        from jcc.wakeword import SURE
        if hit["confidence"] >= SURE:
            return True
        try:
            said = self._transcribe(hit["pcm"], False, plain=True)
        except (ValueError, OSError):
            return hit["confidence"] >= 0.5              # the speech service is unreachable: go by the model alone
        return mentions(said, self.names)

    def _once(self, word: str) -> bool:
        """True unless this very command was passed on a moment ago (both wake words can hear the same "JARVIS, stop")."""
        last, at = self.controlled
        if word == last and time.time() - at < 3:
            return False
        self.controlled = (word, time.time())
        return True

    def _pc_said_it(self, hit: dict) -> bool:
        """Was the name said by a film or a video playing on this PC, not by a person?"""
        if not self.sound:
            return False
        try:
            from jcc.pcsound import levels_of
            return bool(self.sound.verdict(hit["began"], levels_of(hit["pcm"])).get("pc"))
        except Exception:  # noqa: BLE001 - if that cannot be told, it is taken as said
            return False

    def _heard(self, hit: dict) -> None:
        self.names = self.names or names(self.cfg)
        neural = bool(hit.get("neural"))
        # "JARVIS, stop" works at any moment, even while JARVIS itself is talking, and needs no transcription.
        if not neural and self.control and hit["confidence"] >= (0.5 if hit["grammar"] == "ctrl" else 0.62):
            from jcc.quick import control_word
            word = control_word(split(hit["text"], self.names) or "")
            if word:
                if self._once(word):                     # (the neural wake word may just have passed the same words on)
                    self.beep(660)
                    self.control(word)
                return
        if neural and self.name_said and not self.handling and self.busy():
            if not self._pc_said_it(hit) and self._really_the_name(hit):
                self.name_said(hit["at"])
            return
        if (not neural and hit["confidence"] < 0.4) or self.handling or self.busy():
            return
        self.handling = True
        recorder, louder = None, (lambda: None)
        try:
            if neural:
                # The neural wake word heard the name. What is said next is already being recorded, from the same stream.
                recorder, began = hit["recorder"], hit["at"]
                if self.sound:
                    self.sound.want(40)
                if self._pc_said_it(hit):
                    return
                louder = self._turn_down()              # a film on this PC must not drown what is said next
                if not self._really_the_name(hit):
                    return
                asked = ""
            else:
                # Whatever is said next is recorded from this very moment, while the name is still being checked. Otherwise the
                # first words of "Hey JARVIS ... open Spotify" would be lost in between.
                recorder, began = self._record()
                try:
                    said = self._transcribe(hit["wav"], True)
                except (ValueError, OSError):
                    said = hit["text"]                       # the speech service is unreachable: fall back on what was understood locally
                asked = split(said, self.names)
                if asked is None:                            # Whisper heard no wake word: a false alarm, unless the local match was a strong one
                    asked = split(hit["text"], self.names) if hit["confidence"] >= 0.85 and hit["grammar"] == "wake" else None
                    if asked is None:
                        return
                if hit["grammar"] == "wake":
                    asked = ""       # that clip held the name and nothing else: words Whisper adds to it were not said by anyone
            self.beep(880)
            alone = len(asked) < 2                       # its name on its own: the session opens, and what is said next is the request
            if alone and self.attend:
                self.attend()
            more, recorder = self._rest(recorder, began, 7.0 if alone else 0.0), None
            louder()                                     # what was said is recorded: the sound goes back up before anything is done about it
            louder = lambda: None                        # noqa: E731
            asked = " ".join((("" if alone else asked) + " " + more).split())
            if len(asked) < 2:
                if self.listen:
                    self.listen()                        # nothing was said after the name: the session asks, and listens by itself
                else:
                    self.beep(440)
                return
            from jcc.quick import control_word
            word = control_word(asked) if self.control else ""
            if word:
                if self._once(word):
                    self.control(word)                   # "Hey JARVIS ... stop": a command for the session, not a request
            else:
                self.deliver(asked)
        finally:
            louder()
            if recorder is not None:
                try:
                    recorder.stop()
                except Exception:  # noqa: BLE001 - a recorder that will not stop must not stop the wake word
                    pass
            self.handling = False

    # ------------------------------------------------------------------ the PC's own sound, while JARVIS listens
    def _turn_down(self):
        """If something is playing on this PC, turn its sound down while the request is being said, and return what puts it
        back. A film a hand's width from the microphone is louder there than the person is: turned down, the request can
        be told from it and understood. (Sound from another device cannot be turned down from here.)"""
        from jcc import speech
        nothing = lambda: None                           # noqa: E731
        if not self.sound or not speech.settings(self.cfg).get("duck", True):
            return nothing
        try:
            if not self.sound.playing_now(1.0):
                return nothing
            read, write = self.volume or _speakers()
            before = int(read())
            if before <= 12:
                return nothing                           # it is quiet enough already
            low = max(6, before // 4)
            atomic_write(self.cfg.state_dir / "listening-volume.json", json.dumps({"volume": before, "low": low, "at": time.time()}))
            write(low)
        except Exception:  # noqa: BLE001 - whatever goes wrong here, listening goes on at the volume there is
            return nothing

        def back():
            try:
                if int(read()) == low:                   # (someone who changed it meanwhile meant to)
                    write(before)
            except Exception:  # noqa: BLE001
                pass
            finally:
                (self.cfg.state_dir / "listening-volume.json").unlink(missing_ok=True)
        done = []
        return lambda: (done.append(1), back()) if not done else None

    def _record(self):
        """Start recording the microphone now. Returns (the recorder or None, when it began)."""
        try:
            if self.make_recorder:
                recorder = self.make_recorder()
            else:
                from jcc.dictate import Recorder
                recorder = Recorder(quiet=0.8, device=self.find_device())
            if self.sound:
                self.sound.want(40)                  # know what the PC itself plays while this is recorded
            began = time.time()
            recorder.start()
            return recorder, began
        except ValueError as problem:
            self.notify(str(problem))
            return None, 0.0

    def _rest(self, recorder, began: float, patience: float) -> str:
        """What was said after the wake word, from the recording that began when it was heard.

        patience: how long to wait for someone to start speaking. After the name alone, a few seconds. When the request was
        already in the same breath as the name, no time at all: only a sentence that is still going on is waited for."""
        if recorder is None:
            return ""
        # In a room with other sound where the person's voice does not stand out from it, no end will be found by
        # listening for one. There, what has been said so far is written down every second or two, and as soon as it
        # reads as a finished sentence twice running, that sentence is the request. Never more than nine seconds.
        blind = bool(getattr(recorder, "busy", False)) and not recorder.stands_out()
        rolling, settled, tried_at = None, "", time.time() + self.peek_after
        deadline, speaking_by = time.time() + (9 if getattr(recorder, "busy", False) else 20), time.time() + patience
        # A recorder that can say how long it has been quiet lets the answer start sooner: the words are written down during
        # the first short pause, and if they read like a finished sentence nothing more is waited for.
        quick, early = hasattr(recorder, "quiet_for"), None
        while time.time() < deadline and not recorder.finished_speaking():
            if not recorder.heard_speech and time.time() > speaking_by:
                break                                    # nothing (more) was said
            if blind:
                if rolling and rolling["done"].is_set():
                    sentence = first_sentence(rolling["text"])
                    if sentence and sentence == settled:
                        recorder.stop()
                        return sentence
                    settled, rolling = sentence, None
                if not rolling and time.time() >= tried_at and recorder.heard_speech:
                    rolling, tried_at = self._write_down(recorder.so_far()), time.time() + self.peek_every
            elif quick:
                quiet = recorder.quiet_for()
                if early and not quiet:
                    early = None                         # they went on speaking: what was written down is only the beginning
                elif not early and quiet >= 0.3 and recorder.voiced >= 0.3:
                    early = self._write_down(recorder.so_far())
                elif early and quiet >= 0.5 and early["done"].is_set() and complete(early["text"]):
                    break
            time.sleep(0.03 if quick else 0.05)
        sound = recorder.stop()
        if not recorder.heard_speech or getattr(recorder, "voiced", 1.0) < (0.25 if patience else 0.4):
            return ""                                    # silence, or a click or a breath: not words
        if self.sound:
            try:
                from jcc.pcsound import levels_of
                if self.sound.verdict(began + 0.05, levels_of(sound)).get("pc"):
                    return ""                        # what followed its name was a video or music playing on this PC, not a person
            except Exception:  # noqa: BLE001 - if that cannot be told, it is taken as said
                pass
        if early and (not recorder.quiet_for() or len(sound) - early["length"] > 16000):
            early = None                                 # more than half a second of sound came after it was written down
        if early and early["done"].wait(6) and early["text"]:
            return early["text"]
        try:
            said = " ".join(self._transcribe(sound, False).split())
        except (ValueError, OSError) as problem:
            self.notify(str(problem))
            return ""
        # No end was found before time ran out, in a room with other sound: what was said to JARVIS came first, and the
        # rest is most likely the room. A first sentence that is complete is the request.
        return (first_sentence(said) or said) if blind else said

    def _write_down(self, sound: bytes) -> dict:
        """Start transcribing what has been said so far, alongside the recording."""
        early = {"done": threading.Event(), "text": "", "length": len(sound)}

        def work():
            try:
                early["text"] = " ".join(self._transcribe(sound, False).split())
            except (ValueError, OSError):
                early["text"] = ""
            early["done"].set()
        threading.Thread(target=work, daemon=True, name="wake-early").start()
        return early
