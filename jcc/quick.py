"""Instant commands: simple requests JARVIS can carry out itself in a few milliseconds.

"Open Notepad", "what time is it", "set a timer for ten minutes", "volume up" and the like do not
need an AI. They are recognised here only when the whole sentence is one of these simple forms;
anything longer or less certain goes to the assistant as usual.
"""
from __future__ import annotations

import ast
import json
import operator
import os
import re
import subprocess
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from jcc import reminders as rem, system
from jcc.vault import atomic_write

SITES = {
    "youtube": "https://www.youtube.com", "gmail": "https://mail.google.com", "google": "https://www.google.com",
    "google maps": "https://maps.google.com", "maps": "https://maps.google.com", "google drive": "https://drive.google.com",
    "drive": "https://drive.google.com", "google docs": "https://docs.google.com", "docs": "https://docs.google.com",
    "google sheets": "https://sheets.google.com", "sheets": "https://sheets.google.com", "google calendar": "https://calendar.google.com",
    "calendar": "https://calendar.google.com", "whatsapp": "https://web.whatsapp.com", "whatsapp web": "https://web.whatsapp.com",
    "github": "https://github.com", "netflix": "https://www.netflix.com", "amazon": "https://www.amazon.in",
    "flipkart": "https://www.flipkart.com", "twitter": "https://x.com", "x": "https://x.com", "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com", "linkedin": "https://www.linkedin.com", "reddit": "https://www.reddit.com",
    "wikipedia": "https://www.wikipedia.org", "chatgpt": "https://chatgpt.com", "claude": "https://claude.ai",
    "spotify": "https://open.spotify.com", "hotstar": "https://www.hotstar.com", "prime video": "https://www.primevideo.com",
    "google photos": "https://photos.google.com", "photos": "https://photos.google.com", "translate": "https://translate.google.com",
    "google translate": "https://translate.google.com", "outlook": "https://outlook.live.com", "canva": "https://www.canva.com",
    "stack overflow": "https://stackoverflow.com", "notion": "https://www.notion.so", "discord": "https://discord.com/app",
    "telegram": "https://web.telegram.org", "zoom": "https://zoom.us", "google meet": "https://meet.google.com", "meet": "https://meet.google.com",
}
SEARCH = {
    "google": "https://www.google.com/search?q={}", "youtube": "https://www.youtube.com/results?search_query={}",
    "wikipedia": "https://en.wikipedia.org/w/index.php?search={}", "amazon": "https://www.amazon.in/s?k={}",
    "flipkart": "https://www.flipkart.com/search?q={}", "maps": "https://www.google.com/maps/search/{}",
    "google maps": "https://www.google.com/maps/search/{}", "github": "https://github.com/search?q={}",
    "spotify": "https://open.spotify.com/search/{}", "reddit": "https://www.reddit.com/search/?q={}",
    "images": "https://www.google.com/search?tbm=isch&q={}", "google images": "https://www.google.com/search?tbm=isch&q={}",
    "netflix": "https://www.netflix.com/search?q={}", "prime video": "https://www.primevideo.com/search/?phrase={}",
    "hotstar": "https://www.hotstar.com/in/explore?search_query={}", "gmail": "https://mail.google.com/mail/u/0/#search/{}",
    "google drive": "https://drive.google.com/drive/search?q={}", "x": "https://x.com/search?q={}",
    "linkedin": "https://www.linkedin.com/search/results/all/?keywords={}", "imdb": "https://www.imdb.com/find/?q={}",
    "bing": "https://www.bing.com/search?q={}", "stack overflow": "https://stackoverflow.com/search?q={}",
}
# Where a film or a series is looked for and played (jcc/voice_tools.py play_show).
WATCH = {name: SEARCH[name] for name in ("netflix", "prime video", "hotstar")}
# What the button that starts a show is called. Not a trailer, and not Netflix's "Play Something".
PLAY_BUTTON = re.compile(r"(?!.*\b(?:trailer|preview|something|playlist|next|previous)\b)"
                         r"(?:play|resume|watch now|watch|continue watching|play from (?:the )?(?:beginning|start)|(?:play|resume|continue) .{1,48})$", re.I)
_SITE_NAMES = {"you tube": "youtube", "yt": "youtube", "prime": "prime video", "amazon prime": "prime video", "amazon prime video": "prime video",
               "primevideo": "prime video", "disney+ hotstar": "hotstar", "disney hotstar": "hotstar", "jiohotstar": "hotstar", "jio hotstar": "hotstar",
               "map": "maps", "wiki": "wikipedia", "drive": "google drive", "twitter": "x", "stackoverflow": "stack overflow", "mail": "gmail",
               "google mail": "gmail", "google search": "google", "the web": "google", "web": "google", "internet": "google"}


def site_name(site: str) -> str:
    """The site a name means, in the form the tables above use ("Netflix.com" -> "netflix", "you tube" -> "youtube")."""
    low = " ".join(str(site or "").lower().replace("’", "'").split())
    low = re.sub(r"^(?:https?://)?(?:www\.)?", "", low)
    low = re.sub(r"^(?:the |my )", "", low)
    low = re.sub(r"(?:\.com|\.in|\.org|\.tv| app| website| site)$", "", low).strip(" ./")
    return _SITE_NAMES.get(low, low)


def site_search(site: str, words: str) -> str:
    """That site's own search for these words. "" when the site is not one JARVIS knows, or the words are an address."""
    name, words = site_name(site), " ".join(str(words).split())
    if not words or re.match(r"^(?:https?://|www\.)", words, re.I) or name not in SEARCH:
        return ""
    return SEARCH[name].format(quote(words))
BUILT_IN = {  # things Windows can always open, whatever the Start menu calls them
    "file explorer": ["explorer.exe"], "explorer": ["explorer.exe"], "files": ["explorer.exe"], "my files": ["explorer.exe"],
    "task manager": ["taskmgr.exe"], "control panel": ["control.exe"], "command prompt": ["cmd.exe", "/c", "start", "cmd.exe"],
    "cmd": ["cmd.exe", "/c", "start", "cmd.exe"], "downloads": ["explorer.exe", "shell:Downloads"],
    "documents": ["explorer.exe", "shell:Personal"], "pictures": ["explorer.exe", "shell:My Pictures"],
    "desktop folder": ["explorer.exe", "shell:Desktop"], "recycle bin": ["explorer.exe", "shell:RecycleBinFolder"],
    "windows settings": ["explorer.exe", "ms-settings:"], "settings": ["explorer.exe", "ms-settings:"],
    "bluetooth settings": ["explorer.exe", "ms-settings:bluetooth"], "wifi settings": ["explorer.exe", "ms-settings:network-wifi"],
    "wi-fi settings": ["explorer.exe", "ms-settings:network-wifi"], "display settings": ["explorer.exe", "ms-settings:display"],
    "sound settings": ["explorer.exe", "ms-settings:sound"],
}
ALIASES = {"chrome": "google chrome", "edge": "microsoft edge", "vs code": "visual studio code", "vscode": "visual studio code",
           "code": "visual studio code", "calc": "calculator", "word": "word", "excel": "excel", "powerpoint": "powerpoint",
           "ppt": "powerpoint", "terminal": "terminal", "windows terminal": "terminal", "powershell": "windows powershell",
           "snip": "snipping tool", "paint": "paint", "store": "microsoft store", "camera": "camera", "clock": "clock",
           "obsidian": "obsidian", "browser": "", "my browser": ""}
# The same built-in places on a Mac, by the Windows command above. The table stays the one list of names; only how each
# is opened differs. (Linux opens the folders and has no equivalent for the rest.)
_HOME = str(Path.home())
MAC_BUILT_IN = {
    ("explorer.exe",): ["open", _HOME], ("taskmgr.exe",): ["open", "-a", "Activity Monitor"], ("control.exe",): ["open", "-b", "com.apple.systempreferences"],
    ("cmd.exe", "/c", "start", "cmd.exe"): ["open", "-a", "Terminal"], ("explorer.exe", "shell:Downloads"): ["open", _HOME + "/Downloads"],
    ("explorer.exe", "shell:Personal"): ["open", _HOME + "/Documents"], ("explorer.exe", "shell:My Pictures"): ["open", _HOME + "/Pictures"],
    ("explorer.exe", "shell:Desktop"): ["open", _HOME + "/Desktop"], ("explorer.exe", "shell:RecycleBinFolder"): ["open", _HOME + "/.Trash"],
}
LINUX_BUILT_IN = {("explorer.exe",): ["xdg-open", _HOME], ("explorer.exe", "shell:Downloads"): ["xdg-open", _HOME + "/Downloads"],
                  ("explorer.exe", "shell:Personal"): ["xdg-open", _HOME + "/Documents"], ("explorer.exe", "shell:My Pictures"): ["xdg-open", _HOME + "/Pictures"],
                  ("explorer.exe", "shell:Desktop"): ["xdg-open", _HOME + "/Desktop"]}


def built_in_here(argv: list[str]) -> list[str] | None:
    """How this system opens one of the BUILT_IN places: the Windows command itself on Windows, the Mac's or Linux's own
    way elsewhere, None where there is none."""
    kind = system.kind()
    if kind == "windows":
        return list(argv)
    if kind == "mac" and argv and str(argv[-1]).startswith("ms-settings:"):
        return ["open", "-b", "com.apple.systempreferences"]          # (any Windows settings page: the Mac's System Settings)
    return (MAC_BUILT_IN if kind == "mac" else LINUX_BUILT_IN).get(tuple(argv))


PANES = {"files": "files", "file": "files", "terminal": "terminal", "browser": "browser", "web": "browser", "activity": "activity",
         "work": "work", "my work": "work", "preview": "preview"}
VK = {"volume_mute": 0xAD, "volume_down": 0xAE, "volume_up": 0xAF, "next": 0xB0, "previous": 0xB1, "play_pause": 0xB3}
_PREFIX = re.compile(r"^(?:(?:hey|ok|okay|hi|yo)[ ,]+)?(?:jarvis[ ,!.]+)?(?:(?:please|kindly|can you|could you|would you|will you|"
                     r"i want you to|i need you to|i'd like you to|go ahead and|just)[ ,]+)*", re.I)
_SUFFIX = re.compile(r"(?:[ ,]+(?:please|for me|now|right now|thanks|thank you|jarvis))+[.!?]*$", re.I)
_WORD_OPS = [(r"\bmultiplied by\b|\btimes\b|\bx\b|×", "*"), (r"\bdivided by\b|\bover\b|÷", "/"), (r"\bplus\b|\badded to\b|\band\b", "+"),
             (r"\bminus\b|\bsubtract(?:ed)? (?:from|by)\b|\btake away\b", "-"), (r"\bto the power of\b|\braised to\b|\^", "**"),
             (r"\bsquared\b", "**2"), (r"\bcubed\b", "**3"), (r"\bmod(?:ulo)?\b", "%"), (r"(\d+(?:\.\d+)?)\s*(?:percent|%)\s*of\b", r"(\1/100)*")]
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Mod: operator.mod,
        ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos, ast.FloorDiv: operator.floordiv}


@dataclass
class Result:
    say: str
    steps: list[str] = field(default_factory=list)
    ui: str = ""            # an instruction for the window itself, such as "pane:files" or "new-chat"
    private: bool = False


def normalise(text: str, keep_case: bool = False) -> str:
    """The request without greetings and politeness ("hey JARVIS, could you ... please")."""
    clean = " ".join(str(text).replace("’", "'").split())
    clean = _SUFFIX.sub("", _PREFIX.sub("", clean if keep_case else clean.lower()))
    return clean.strip(" .!?,")


_LEAD = r"(?:(?:ok(?:ay)?|alright|all right|well|no|yes|thanks|thank you|that'?s (?:alright|all right|okay|ok|fine|good|great)|that is (?:alright|okay|fine|good))[ ,]+)*"
_STOP = re.compile(_LEAD + r"(?:you (?:can|may|should) shop|(?:you (?:can|may|should) |please |just )?(?:stop|stop it|stop that|stop there|stop this|stop talking|stop speaking|stop everything|"
                   r"be quiet|quiet|shut up|hush|silence|enough|that'?s enough|that is enough|never ?mind|cancel|cancel that|cancel it|cancel this|forget it|"
                   r"forget that|abort|nothing|leave it|drop it))")     # ("you can shop" is how "you can stop" is sometimes heard)
_SLEEP = re.compile(_LEAD + r"(?:you (?:can|may) )?(?:go to sleep|sleep|sleep now|go back to sleep|stop listening|stand by|standby|rest|take a break|"
                    r"that'?s all(?: for)?|that is all(?: for)?|that'?ll be all|that will be all|i'?m done|i am done|we'?re done|we are done)")
_END = re.compile(_LEAD + r"(?:please )?(?:end|end it|end session|end the session|end this session|end chat|end the chat|end this chat|end (?:the |this )?conversation|"
                  r"end (?:the |this )?voice chat|end (?:the |this )?call|close (?:the |this )?session|stop (?:the |this )?session|finish (?:the |this )?session|"
                  r"exit|exit voice chat|leave voice chat|quit voice chat|goodbye|good bye|bye|bye bye|see you|see you later|you can go|dismissed)")


def session_word(said: str) -> "Result | None":
    """Words that steer the voice session itself. `said` is already lower case, without greetings and politeness.

    stop: drop what is being done and said, and keep listening.  sleep: wait to be called by name.  end: leave voice chat."""
    if _END.fullmatch(said):
        return Result("", ui="end")
    if _SLEEP.fullmatch(said):
        return Result("", ui="sleep")
    if _STOP.fullmatch(said):
        return Result("", ui="rest")
    return None


def control_word(said: str) -> str:
    """"rest", "sleep" or "end" if the words after the wake word are a command for the session itself; otherwise ""."""
    found = session_word(normalise(said))
    return found.ui if found else ""


def calculate(expression: str):
    """Arithmetic only. Returns a number, or None if the text is not plain arithmetic."""
    text = " " + expression.lower().replace(",", "") + " "
    for pattern, symbol in _WORD_OPS:
        text = re.sub(pattern, " " + symbol + " " if not symbol.startswith("(") else symbol, text)
    text = text.strip()
    if not text or len(text) > 80 or not re.fullmatch(r"[\d\s.+\-*/%()]+", text) or not re.search(r"\d", text) or not re.search(r"[+\-*/%]", text):
        return None

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            left, right = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Pow) and (abs(right) > 64 or abs(left) > 1e6):
                raise ValueError("too large")
            return _OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](walk(node.operand))
        raise ValueError("not arithmetic")
    try:
        value = walk(ast.parse(text, mode="eval"))
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError, TypeError, RecursionError):
        return None
    if isinstance(value, float):
        value = round(value, 6)
        if value == int(value) and abs(value) < 1e15:
            value = int(value)
    return value


class Apps:
    """The apps in the Start menu, looked up once in the background so opening one is instant."""

    def __init__(self, cfg, runner=None):
        self.cfg, self.runner = cfg, runner
        self.path = cfg.state_dir / "apps.json"
        self.items: dict[str, str] = {}
        self.loaded = 0.0
        self.lock = threading.Lock()
        try:
            saved = json.loads(self.path.read_text("utf-8")) if self.path.exists() else {}
            self.items, self.loaded = dict(saved.get("apps", {})), float(saved.get("at", 0))
        except (OSError, ValueError, TypeError):
            pass

    def refresh(self, force: bool = False) -> None:
        if not force and time.time() - self.loaded < 6 * 3600 and self.items:
            return
        if system.kind() == "mac" and not self.runner:
            from jcc import mac
            self._keep(mac.installed_apps())          # {name: the app's folder}, opened with `open -a`
            return
        if system.kind() != "windows" and not self.runner:
            return
        try:
            if self.runner:
                raw = self.runner()
            else:
                raw = subprocess.run(["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
                                      "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"], capture_output=True, text=True,
                                     encoding="utf-8", errors="replace", timeout=30, stdin=subprocess.DEVNULL,
                                     creationflags=subprocess.CREATE_NO_WINDOW).stdout
            rows = json.loads(raw or "[]")
            rows = rows if isinstance(rows, list) else [rows]
            found = {str(r["Name"]).lower(): str(r["AppID"]) for r in rows if isinstance(r, dict) and r.get("Name") and r.get("AppID")}
        except (OSError, ValueError, subprocess.SubprocessError, KeyError, TypeError):
            return
        self._keep(found)

    def _keep(self, found: dict[str, str]) -> None:
        if found:
            with self.lock:
                self.items, self.loaded = found, time.time()
            try:
                self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
                atomic_write(self.path, json.dumps({"at": self.loaded, "apps": found}))
            except OSError:
                pass

    def refresh_soon(self) -> None:
        threading.Thread(target=self.refresh, daemon=True, name="apps-list").start()

    def find(self, name: str) -> tuple[str, str] | None:
        """(display name, AppID) for the best match, or None."""
        want = ALIASES.get(name, name).strip()
        if not want:
            return None
        with self.lock:
            items = dict(self.items)
        if want in items:
            return want, items[want]
        starts = sorted((n for n in items if n.startswith(want + " ") or n.startswith(want)), key=len)
        if starts and (len(starts) == 1 or len(want) >= 4):
            return starts[0], items[starts[0]]
        words = sorted((n for n in items if re.search(r"\b" + re.escape(want) + r"\b", n)), key=len)
        if len(words) == 1 or (words and len(want) >= 5):
            return words[0], items[words[0]]
        return None


def near(name: str, names, most: int = 6) -> list[str]:
    """Installed apps whose names are close to this one: for a name that was misheard or half remembered."""
    import difflib
    want = " ".join(str(name).lower().split())
    if not want:
        return []

    def skeleton(text: str) -> str:                         # how it sounds, roughly: first letter, then the consonants
        letters = re.sub(r"[^a-z]", "", text)
        return letters[:1] + re.sub(r"[aeiouyhw]", "", letters[1:])
    scored = []
    for other in names:
        plain = str(other).lower()
        first = plain.split()[0] if plain.split() else plain
        score = max(difflib.SequenceMatcher(None, want, plain).ratio(), difflib.SequenceMatcher(None, want.split()[0], first).ratio() * 0.95,
                    difflib.SequenceMatcher(None, skeleton(want.split()[0]), skeleton(first)).ratio() * 0.9,
                    *(difflib.SequenceMatcher(None, want, word).ratio() * 0.93 for word in plain.split() if len(word) >= 4))
        if any(word in plain.split() for word in want.split() if len(word) >= 4):
            score = max(score, 0.8)
        if score >= 0.62:
            scored.append((score, str(other)))
    return [found.title() for _, found in sorted(scored, key=lambda row: (-row[0], len(row[1])))[:most]]


def launch(app_id: str) -> None:
    """Start an app from the list: by its Start menu ID on Windows, by its folder on a Mac (see Apps.refresh)."""
    if system.kind() == "mac":
        from jcc import mac
        mac.open_app(app_id)
        return
    subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + app_id], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=system.no_window())


def press(code: int, times: int = 1) -> None:
    """Press a media or volume key. A Mac has no plain way for a program to press those keys: the volume and mute are
    set directly instead, and play, pause and skip are said to be missing."""
    kind = system.kind()
    if kind == "mac":
        from jcc import mac
        if code in (VK["volume_up"], VK["volume_down"]):
            mac.change_volume(times if code == VK["volume_up"] else -times)
        elif code == VK["volume_mute"]:
            mac.toggle_mute()
        else:
            raise ValueError("Play, pause and skip are not available on a Mac yet. Use the keys on the keyboard, or the app itself.")
        return
    if kind != "windows":
        raise ValueError("Media keys are not available on Linux yet.")
    import ctypes
    for _ in range(times):
        ctypes.windll.user32.keybd_event(code, 0, 0, 0)
        ctypes.windll.user32.keybd_event(code, 0, 2, 0)


class Quick:
    def __init__(self, cfg, apps: Apps, reminders: rem.Reminders, act=None, now=None):
        self.cfg, self.apps, self.reminders = cfg, apps, reminders
        self.act = act or self._act       # tests replace this to record actions instead of doing them
        self.now = now or datetime.now
        self.cased = ""

    # ------------------------------------------------------------------ real actions
    def _act(self, kind: str, value=None):
        if kind == "video":       # the first video YouTube lists for these words: (its title, its address), or None
            from jcc.webread import find_videos
            try:
                rows = find_videos(value, limit=1)
            except ValueError:
                return None
            if not rows:
                return None
            webbrowser.open(rows[0]["url"])
            return rows[0]["title"], rows[0]["url"]
        if kind == "music":       # (words, where): play them and say what is now playing
            if system.kind() != "windows":
                raise ValueError("Playing in the Spotify app is only available on Windows for now. Ask for it on YouTube instead.")
            from jcc import music, voice_tools
            from jcc.computer import Desktop
            found = self.apps.find("spotify")
            return music.play(value[0], value[1], voice_tools._Windows(), Desktop(), (lambda: bool(found and (launch(found[1]) or True))), None, bool(found))
        windows = system.kind() == "windows"
        if kind == "app":
            launch(value)
        elif kind == "run":
            argv = built_in_here(value)
            if not argv:
                raise ValueError(f"That is not available on {system.name()}.")
            subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=system.no_window())
        elif kind == "url":
            webbrowser.open(value)
        elif kind == "key":
            press(VK[value[0]], value[1])
        elif kind == "lock":
            from jcc.voice_tools import lock_screen
            lock_screen()
        elif not windows and kind in ("desktop", "brightness", "screenshot"):
            raise ValueError({"desktop": "Showing the desktop", "brightness": "Changing the screen brightness",
                              "screenshot": "Taking a screenshot"}[kind] + " is only available on Windows for now.")
        elif not windows and kind == "volume":
            if system.kind() != "mac":
                raise ValueError("The volume is not available on Linux yet.")
            from jcc import mac
            return mac.volume() if value is None else mac.set_volume(value)
        elif not windows and kind == "focus":
            return None                           # other apps' windows cannot be seen here: the app is opened instead
        elif kind == "desktop":
            import ctypes
            for code, up in ((0x5B, 0), (0x44, 0), (0x44, 2), (0x5B, 2)):
                ctypes.windll.user32.keybd_event(code, 0, up, 0)
        elif kind in ("volume", "brightness"):
            from jcc import winctl
            if kind == "volume":
                return winctl.volume() if value is None else winctl.set_volume(value)
            return winctl.brightness(value)
        elif kind == "focus":
            from jcc import winctl
            found = winctl.find_window(value)
            if found:
                winctl.focus(found["handle"])
            return found["title"] if found else None
        elif kind == "playing":                   # has this PC played anything in the last seconds? None: not known
            from jcc import pcsound
            return pcsound.shared.lately()
        elif kind == "screens":
            from jcc import screens
            return screens.screens()
        elif kind == "move":                      # a window onto another screen: (part of its title or "" for the one in front, which screen)
            from jcc import screens, winctl
            from jcc.policy import OWN_WINDOW
            title, where = value
            found = screens.screens()
            if len(found) < 2:
                raise ValueError("Only one screen is connected, so there is nowhere to move it.")
            row = winctl.find_window(title) if title else next((r for r in winctl.windows() if not OWN_WINDOW.search(r["title"])), None)
            if not row or OWN_WINDOW.search(row["title"]):
                return None
            here = screens.of_window(row["handle"], found)
            target = screens.choose(found, here, where)
            if not target:
                raise ValueError("I could not tell which screen you mean. There are " + screens.describe(found)[:-1].replace(" screens: ", ": ", 1) + ".")
            if here and target["number"] != here["number"] and not screens.move_window(row["handle"], target, found):
                raise ValueError("Windows would not move that window.")
            return row["title"], target, bool(here and target["number"] == here["number"])
        elif kind == "weather":
            from jcc import memory
            return memory.weather(value)
        elif kind == "screenshot":
            from jcc.computer import Desktop
            from jcc.policy import PRIVATE_WINDOW
            desktop = Desktop()
            if PRIVATE_WINDOW.search(desktop.window_title()):
                raise ValueError("A private window is in front, so I did not take a picture of it.")
            folder = Path.home() / "Pictures" / "JARVIS"
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / ("screenshot-" + self.now().strftime("%Y%m%d-%H%M%S") + ".png")
            target.write_bytes(desktop.capture()[2])
            return str(target)
        return None

    # ------------------------------------------------------------------ recognising
    def handle(self, text: str, allow_pc: bool = True) -> Result | None:
        said = normalise(text)
        if not said or len(said) > 140 or "\n" in text:
            return None
        self.cased = normalise(text, True)   # the same words with the user's own capital letters, for things that are kept
        acting = (self._sound, self._levels, self._window, self._open, self._search) if allow_pc else ()
        for step in (self._time, self._timers, *acting, self._weather, self._sums, self._notes, self._ui):
            try:
                result = step(said)
            except ValueError as problem:
                return Result(str(problem))
            if result:
                return result
        return None

    def _time(self, said: str) -> Result | None:
        now = self.now()
        if re.fullmatch(r"(what(?:'s| is) the time|what time is it|what is the time now|time now|tell me the time|current time|the time)", said):
            return Result("It's " + now.strftime("%I:%M %p").lstrip("0") + ".")
        if re.fullmatch(r"(what(?:'s| is) (?:the|today's) date|what day is it(?: today)?|what(?:'s| is) today|today's date|what date is it(?: today)?|what(?:'s| is) the day today)", said):
            return Result("It's " + now.strftime("%A, %d %B %Y").replace(" 0", " ") + ".")
        return None

    def _timers(self, said: str) -> Result | None:
        match = re.fullmatch(r"(?:set|start|put|make) (?:a |an |the )?timer (?:for|of) (.+)", said) or re.fullmatch(r"timer (?:for )?(.+)", said) or \
            re.fullmatch(r"(?:set |start )?(?:a |an )?(.+?) timer", said)
        if match:
            # Only when the whole sentence is the timer: "ten minutes", or "ten minutes called tea". Anything more goes to the assistant.
            seconds, label = rem.pure_duration(match.group(1)), ""
            named = re.fullmatch(r"(.+?) (?:called|named|labelled|labeled|for) (?:the |my )?([\w' -]{2,40})", match.group(1))
            if not seconds and named and not re.search(r"\b(and|then|after|also)\b", named.group(2)):
                seconds, label = rem.pure_duration(named.group(1)), named.group(2).strip()
            if seconds:
                self.reminders.add(label[:1].upper() + label[1:] if label else "Timer", time.time() + seconds, "timer")
                return Result(f"Timer set for {rem.spoken_span(seconds)}.", ["Set a timer"])
            return None
        match = re.fullmatch(r"remind me (?:to |about |that )?(.+?) (in .+|at .+|tomorrow.*)", self.cased, re.I) or \
            re.fullmatch(r"remind me (in .+?|at .+?|tomorrow(?: at [\d:apm. ]+)?) (?:to |about |that )(.+)", self.cased, re.I)
        if match:
            first, second = match.group(1), match.group(2)
            when, what = (first.lower(), second) if re.match(r"(in|at|tomorrow)\b", first, re.I) else (second.lower(), first)
            due, today = None, self.now().date()
            if when.startswith("in "):
                seconds = rem.pure_duration(when[3:])
                due, today = (time.time() + seconds if seconds else None), datetime.fromtimestamp(time.time()).date()   # counted from the real clock
            else:
                due = rem.pure_clock(when, self.now())
            if due:
                self.reminders.add(what, due, "reminder")
                at = datetime.fromtimestamp(due)
                day = "" if at.date() == today else " tomorrow" if (at.date() - today).days == 1 else at.strftime(" on %A")
                return Result(f"I'll remind you to {what} at {at.strftime('%I:%M %p').lstrip('0')}{day}.", ["Set a reminder"])
            return None
        if re.fullmatch(r"(?:cancel|stop|clear|delete|remove) (?:the |my |all |all my |all the )?(?:timers?|reminders?|alarms?)", said):
            count = self.reminders.cancel()
            return Result("Cancelled." if count else "There was nothing to cancel.", ["Cancelled timers and reminders"])
        if re.fullmatch(r"(?:what|which|list|show|tell me)(?: are| me)?(?: my| the)? (?:timers|reminders)(?: do i have| are set| i have)?", said):
            rows = self.reminders.listing()
            if not rows:
                return Result("You have no timers or reminders.")
            parts = [(("a timer" if r["text"] == "Timer" else r["text"]) + " in " + rem.spoken_span(max(1, r["due"] - time.time()))) for r in rows[:5]]
            return Result("You have " + "; ".join(parts) + ".")
        return None

    def _sound(self, said: str) -> Result | None:
        if re.fullmatch(r"(?:turn (?:it |the volume |the sound )?up|volume up|louder|make it louder|increase (?:the )?volume|raise (?:the )?volume|turn up the volume)", said):
            self.act("key", ("volume_up", 5))
            return Result("Louder.", ["Turned the volume up"])
        if re.fullmatch(r"(?:turn (?:it |the volume |the sound )?down|volume down|quieter|softer|make it quieter|decrease (?:the )?volume|lower (?:the )?volume|turn down the volume)", said):
            self.act("key", ("volume_down", 5))
            return Result("Quieter.", ["Turned the volume down"])
        if re.fullmatch(r"(?:un)?mute(?: it| the sound| the volume| my (?:pc|computer|laptop))?", said):
            self.act("key", ("volume_mute", 1))
            return Result("Done.", ["Toggled mute"])
        if re.fullmatch(r"(?:pause|unpause|resume|continue|keep playing|carry on)(?: (?:the |my |this |that )?(?:music|song|video|track|audio|movie|film|show|episode|it|playing))?|"
                        r"(?:pause|stop|hold) (?:it|that|this)(?: for (?:a )?(?:second|moment|minute|bit))?|play|(?:play|resume|continue)(?: playing)? (?:the |my |this |that )?(?:music|song|video|track|audio|movie|film|show|episode)|"
                        r"(?:stop|continue) (?:the |my |this |that )?(?:music|song|video|track|audio|movie|film|show|episode)", said):
            stops = re.match(r"(?:pause|stop|hold)\b", said)
            what = re.search(r"\b(music|song|video|track|audio|movie|film|show|episode)\b", said)
            # The key is a toggle. With nothing playing on this PC (the film is on the television), "pause" would START
            # whatever was last paused here; and "resume" while something plays would stop it. Where that is known
            # (a voice chat has been listening), the key is only pressed when it does what was asked.
            playing = self.act("playing")
            if playing is False and stops:
                return Result("Nothing is playing on this PC, so there is nothing for me to " + ("stop" if stops.group(0) == "stop" else "pause") + ".")
            if playing is True and not stops:
                return Result("It is already playing.")
            self.act("key", ("play_pause", 1))
            # Said at once, so it is clear what was understood: "Pausing the movie." (The key itself does not say whether
            # something was playing, so this says what was asked for.)
            doing = "Stopping" if stops and stops.group(0) == "stop" else "Pausing" if stops else "Playing" if said == "play" else "Resuming"
            return Result(doing + (" the " + what.group(1) if what else "") + ".", ["Play or pause"])
        if re.fullmatch(r"(?:next|skip)(?: (?:the |this )?(?:song|track|one|video))?|(?:play (?:the )?)?next (?:song|track)", said):
            self.act("key", ("next", 1))
            return Result("Next.", ["Next track"])
        if re.fullmatch(r"(?:previous|last|go back(?: a| one)?)(?: (?:the )?(?:song|track|one))|play (?:the )?previous (?:song|track)", said):
            self.act("key", ("previous", 1))
            return Result("Going back.", ["Previous track"])
        return None

    def _levels(self, said: str) -> Result | None:
        match = re.fullmatch(r"(?:(?:set|turn|change|put|make) )?(?:the )?(volume|sound|brightness)(?: level)? (?:to |at )?(\d{1,3})(?: ?%| percent)?", said)
        if match:
            what, level = ("brightness" if match.group(1) == "brightness" else "volume"), min(100, int(match.group(2)))
            now = self.act(what, level)
            return Result(f"{what.title()} {now if isinstance(now, int) else level} percent.", [f"Set the {what} to {level} percent"])
        if re.fullmatch(r"(?:what(?:'s| is) the|how (?:loud|high) is the) (?:volume|sound)(?: level)?(?: now| at)?", said):
            return Result(f"The volume is {self.act('volume', None)} percent.")
        up = re.fullmatch(r"(?:(?:turn|make) (?:the |my )?(?:screen|display) )?brighter|(?:turn )?(?:the )?brightness up|(?:increase|raise) (?:the )?(?:screen )?brightness|turn up (?:the )?brightness", said)
        down = re.fullmatch(r"(?:(?:turn|make) (?:the |my )?(?:screen|display) )?(?:dimmer|darker)|(?:turn )?(?:the )?brightness down|(?:dim|darken) (?:the |my )?(?:screen|display)|"
                            r"(?:decrease|lower|reduce) (?:the )?(?:screen )?brightness|turn down (?:the )?brightness", said)
        if up or down:
            current = self.act("brightness", None)
            target = max(0, min(100, (current if isinstance(current, int) else 50) + (20 if up else -20)))
            now = self.act("brightness", target)
            return Result(f"Brightness {now if isinstance(now, int) else target} percent.", ["Changed the screen brightness"])
        return None

    def _weather(self, said: str) -> Result | None:
        match = re.fullmatch(r"(?:what(?:'s| is) the |how(?:'s| is) the |tell me the |check the )?weather(?: like)?(?: today| now| right now| tomorrow)? "
                             r"(?:in|at|for) ([\w .,'-]{2,60}?)(?: today| now| right now| tomorrow)?", said)
        if not match or re.search(r"\band\b|,", match.group(1)):
            return None
        try:
            lines = str(self.act("weather", match.group(1)) or "").split("\n")
        except ValueError:
            return None   # an unknown place, or the service is down: let the assistant deal with it
        if not lines[0]:
            return None
        later = lines[2] if "tomorrow" in said and len(lines) > 2 else lines[1] if len(lines) > 1 else ""
        return Result((lines[0] + " " + later).strip(), ["Checked the weather"])

    def _window(self, said: str) -> Result | None:
        match = re.fullmatch(r"switch (?:back )?(?:over )?to (?:the |my )?(.+?)(?: window| app)?", said)
        if match and len(match.group(1)) <= 40:
            title = self.act("focus", match.group(1))
            if title:
                return Result("Here it is.", ["Switched to " + str(title)[:60]])
            return self._open("open " + match.group(1))
        if re.fullmatch(r"lock(?: (?:the|my|this))?(?: (?:pc|computer|laptop|screen|device))?", said):
            self.act("lock")
            return Result("Locked.", ["Locked the PC"])
        if re.fullmatch(r"show (?:me )?(?:the |my )?desktop|minimi[sz]e (?:everything|all|all (?:the )?windows)", said):
            self.act("desktop")
            return Result("Done.", ["Showed the desktop"])
        # More than one screen: "move this to the other screen", "put Chrome on my laptop screen", "send it to screen 2".
        match = re.fullmatch(r"(?:move|put|send|bring|throw|shift|drag) (?:(this|that|it|this window|that window|the window)|(?:the |my )?(.+?)(?: window| app)?) "
                             r"(?:over )?(?:on ?to|to|on) (?:the |my )?((?:.+ )?(?:screen|monitor|display)(?: (?:number )?\w+)?|laptop)", said)
        if match and len(match.group(2) or "") <= 40:
            moved = self.act("move", (match.group(2) or "", match.group(3)))
            if moved:
                title, target, already = moved
                place = "the laptop screen" if target.get("builtin") else "the main screen" if target.get("main") else f"screen {target['number']}"
                return Result(f"It is already on {place}." if already else f"Moved it to {place}.", ["Moved " + str(title)[:60] + " to " + place])
            if match.group(2):
                return Result(f"I could not find a window called {match.group(2)}.")
        if re.fullmatch(r"(?:how many|which|what) (?:screens|monitors|displays) (?:do i have|are (?:there|connected|plugged in|attached)|have i got)(?: (?:right )?now)?", said):
            from jcc import screens
            found = self.act("screens") or []
            return Result(screens.describe(found).replace("2 screens:", "Two screens:").replace("3 screens:", "Three screens:") if found else "I could not tell which screens are connected.")
        if re.fullmatch(r"(?:take|grab|capture|save) (?:a |one )?(?:screenshot|screen shot|picture of (?:the|my) screen)", said):
            saved = self.act("screenshot")
            return Result("Saved a screenshot to your Pictures folder.", ["Saved " + (Path(saved).name if saved else "a screenshot")], private=True)
        return None

    def _open(self, said: str) -> Result | None:
        match = re.fullmatch(r"(?:open|launch|start|run|go to|bring up|pull up|fire up|show me)(?: up)? (?:the |my )?(.+?)(?: app| application| program| website| site)?", said)
        if not match:
            return None
        name = match.group(1).strip()
        if re.search(r"\b(and|then|after|with|in|on|to|for|from|into|which|that|file|folder|project|chat|panel|tab|window)\b|,", name) or len(name) > 40:
            return None
        if name in BUILT_IN:
            self.act("run", BUILT_IN[name])
            return Result("Opening " + name + ".", ["Opened " + name])
        if self._told_about(name):
            return None        # the user has said something about this one ("open Netflix in the browser"): the assistant knows how they want it
        found = self.apps.find(name)
        if name in SITES and not (found and found[0] == ALIASES.get(name, name)):
            # "Open Google" is the website, not the first app whose name begins with it (Google Chrome).
            self.act("url", SITES[name])
            return Result("Opening " + name.title() + ".", ["Opened " + SITES[name]])
        if found:
            self.act("app", found[1])
            return Result("Opening " + found[0].title() + ".", ["Opened " + found[0].title()])
        if re.fullmatch(r"(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|org|net|in|io|ai|co|edu|gov|app|dev|tv|me|uk|us)(?:/\S*)?", name):
            self.act("url", "https://" + name)
            return Result("Opening " + name + ".", ["Opened " + name])
        return None

    def _told_about(self, name: str) -> bool:
        """Whether the user has told JARVIS something about this app or site (remembered facts). Then the assistant decides."""
        try:
            from jcc import memory
            return any(re.search(r"\b" + re.escape(name) + r"\b", fact, re.I) for fact in memory.facts(self.cfg))
        except (OSError, ValueError):
            return False

    def _search(self, said: str) -> Result | None:
        from jcc.music import VAGUE
        match = re.fullmatch(r"(?:play|put on|watch|show me)(?: me)? (?:a |an |the |some )?(.+?)(?: videos?)? on youtube", said)
        if match and len(match.group(1)) <= 100 and not VAGUE.search(match.group(1)):
            # "Play ..." means play it: the first video starts, instead of a page of results to choose from.
            found = self.act("video", match.group(1))
            if found:
                return Result(f"Playing {found[0][:80]}." if found[0] else f"Playing {match.group(1)} on YouTube.", [f"Opened {found[1]}"])
            self.act("url", SEARCH["youtube"].format(quote(match.group(1))))       # no video could be picked: at least the results are shown
            return Result(f"Here's {match.group(1)} on YouTube.", [f"Searched YouTube for {match.group(1)}"])
        match = re.fullmatch(r"(?:play|put on) (?:the song |the track )?(.+?) (?:on|in|with|using) (?:the )?spotify(?: app)?", said)
        if match and len(match.group(1)) <= 100:
            if VAGUE.search(match.group(1)):
                return None        # "play it on Spotify": the assistant knows what "it" is
            told = str(self.act("music", (match.group(1), "spotify")) or "")
            playing = re.search(r'(?:Now playing in Spotify: |already playing )"(.+)"', told)
            if playing:
                return Result(f"Playing {playing.group(1)} on Spotify.", ["Played it in Spotify"])
            return Result(f"I searched Spotify for {match.group(1)}, but it did not start playing. Tell me the exact song and artist and I'll try again.",
                          ["Searched Spotify for " + match.group(1)])
        sites = "|".join(sorted((re.escape(name) for name in SEARCH), key=len, reverse=True))
        match = re.fullmatch(r"(?:search|look up|look for|find)(?: for| up)? (.+?) (?:on|in) (?:the )?(" + sites + r")", said)
        site, query = None, None
        if match:
            query, site = match.group(1), match.group(2)
        else:
            match = re.fullmatch(r"(google|youtube|wikipedia) (.+)", said)
            if match:
                site, query = match.group(1), match.group(2)
        if not site or not query or len(query) > 100 or VAGUE.search(query):
            return None            # ("search for it on Netflix": the assistant knows what "it" is)
        self.act("url", SEARCH[site].format(quote(query)))
        return Result(f"Here's {query} on {site.title()}.", [f"Searched {site.title()} for {query}"])

    def _sums(self, said: str) -> Result | None:
        match = re.fullmatch(r"(?:what(?:'s| is)|calculate|compute|work out|how much is|what does) (.+?)(?: equal| equals| make| come to)?", said)
        if not match:
            return None
        value = calculate(match.group(1))
        if value is None:
            return None
        return Result(f"{match.group(1).strip()} is {value:,}." if isinstance(value, int) else f"{match.group(1).strip()} is {value}.")

    def _notes(self, said: str) -> Result | None:
        match = re.fullmatch(r"(?:make|take|add|write|jot)(?: down)? a (?:quick )?note(?: that| saying| to| about|:)? (.+)", self.cased, re.I) or \
            re.fullmatch(r"note(?: down| that)?:? (.+)", self.cased, re.I)
        if match:
            from jcc import memory
            memory.add_note(self.cfg, match.group(1))
            return Result("Noted.", ["Added a note"])
        match = re.fullmatch(r"remember (?:that )?(.+)", self.cased, re.I)
        if match and not re.match(r"(to|when|how|what|where|who|the time|our|last|that time)\b", match.group(1), re.I):
            from jcc import memory
            memory.remember(self.cfg, match.group(1))
            return Result("I'll remember that.", ["Saved to memory"])
        return None

    def _ui(self, said: str) -> Result | None:
        match = re.fullmatch(r"(?:open|show)(?: me)? (?:the |my )?(files?|terminal|browser|web|activity|my work|work|preview) (?:panel|pane|tab|view)", said)
        if match:
            return Result("Here you go.", ui="pane:" + PANES[match.group(1)])
        if re.fullmatch(r"(?:start |open |make )?(?:a )?new (?:chat|conversation)", said):
            return Result("New chat.", ui="new-chat")
        match = re.fullmatch(r"(?:switch to |turn on |use |go )?(dark|light)(?: mode| theme)", said)
        if match:
            return Result(match.group(1).title() + " mode.", ui="theme:" + match.group(1))
        if re.fullmatch(r"(?:go |enter |make it )?full ?screen", said):
            return Result("", ui="fullscreen")
        if re.fullmatch(r"(?:close|hide) (?:the |this )?(?:panel|side panel|pane)", said):
            return Result("", ui="close-panel")
        return session_word(said)
