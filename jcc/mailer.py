"""Sending email for the owner.

Three ways, best first:
1. Through their own mail account: the address plus an app password, which is kept only in Windows
   Credential Manager. This is exact; the mail server says whether the message was accepted.
2. In Gmail in their own browser, when that is the mail they use: the message is opened there as a
   draft and, after their yes, sent with Gmail's own shortcut.
3. Through the mail app on this PC: a draft is opened and its Send button is pressed.
Whichever way, nothing is sent until the owner has said yes to the exact message (jcc/policy.py).
choose() picks the way from what the owner said, what they use and what is open: someone with Gmail
open in front of them does not want the message to appear in Outlook.
"""
from __future__ import annotations

import json
import os
import re
import smtplib
import ssl
import time
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from urllib.parse import quote

from jcc import secrets
from jcc.vault import atomic_write

ADDRESS = re.compile(r"[^@\s,;<>\"']+@[^@\s,;<>\"']+\.[^@\s,;<>\"']+")
PROVIDERS = {
    "gmail.com": ("smtp.gmail.com", 587), "googlemail.com": ("smtp.gmail.com", 587),
    "yahoo.com": ("smtp.mail.yahoo.com", 587), "yahoo.in": ("smtp.mail.yahoo.com", 587), "yahoo.co.in": ("smtp.mail.yahoo.com", 587),
    "yahoo.co.uk": ("smtp.mail.yahoo.com", 587), "ymail.com": ("smtp.mail.yahoo.com", 587), "rocketmail.com": ("smtp.mail.yahoo.com", 587),
    "icloud.com": ("smtp.mail.me.com", 587), "me.com": ("smtp.mail.me.com", 587), "mac.com": ("smtp.mail.me.com", 587),
    "zoho.com": ("smtp.zoho.com", 587), "zoho.in": ("smtp.zoho.in", 587), "zohomail.in": ("smtp.zoho.in", 587),
    "aol.com": ("smtp.aol.com", 587), "gmx.com": ("mail.gmx.com", 587), "gmx.net": ("mail.gmx.net", 587),
    "fastmail.com": ("smtp.fastmail.com", 587), "rediffmail.com": ("smtp.rediffmail.com", 587),
}
NO_PASSWORD_SIGN_IN = {"outlook.com", "hotmail.com", "live.com", "msn.com", "outlook.in", "hotmail.co.uk", "live.in"}
NO_APP = ("No mail app is set up on this PC, so the draft could not be opened. The user can connect an email account in JARVIS "
          "(Voice and assistant, then Email) so messages are sent directly.")


THROUGH = ("auto", "gmail", "app")       # what the owner chose for when no account is connected

# What the owner may call each way. Whatever they name, the message goes that way or not at all: the account it is sent
# from is part of the message, so it is never picked or switched behind their back.
_APP_WORDS = re.compile(r"outlook|thunderbird|mail app|windows mail|\bapp\b", re.I)
_BROWSER_WORDS = re.compile(r"browser|comet|chrome|\bedge\b|firefox|brave|safari|\btab\b", re.I)
_GOOGLE_WORDS = re.compile(r"gmail|google", re.I)
_ACCOUNT_WORDS = re.compile(r"connected|composio|\baccount\b", re.I)
_GOOGLE_MAIL = ("@gmail.com", "@googlemail.com")
_app_name: str | None = None


def app_label() -> str:
    """The PC's own mail app, as its owner knows it: "Outlook on this PC"."""
    global _app_name
    if _app_name is None:
        _app_name = ""
        try:
            from jcc import system
            if system.kind() == "windows":
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                    r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\mailto\UserChoice") as key:
                    prog = str(winreg.QueryValueEx(key, "ProgId")[0])
                for pattern, name in ((r"outlook|olk", "Outlook"), (r"thunderbird", "Thunderbird"),
                                      (r"windowscommunicationsapps|windowslive|msmail", "Windows Mail")):
                    if re.search(pattern, prog, re.I):
                        _app_name = name
                        break
            elif system.kind() == "mac":
                _app_name = "Mail"
        except (OSError, ImportError, ValueError):
            _app_name = ""
    return (_app_name + " on this PC") if _app_name else "the mail app on this PC"


def outlook_label(account: str) -> str:
    """What JARVIS calls an account in classic Outlook on this PC: in its questions, its answers and the email's "from"."""
    return f"Outlook on this PC ({str(account).lower()})"


def ways(smtp: bool = False, online: bool = False, address: str = "", preferred: str = "auto", titles=(), smtp_address: str = "",
         app: str = "", outlook=()) -> list[tuple[str, str]]:
    """Every way an email can go out right now, as (way, what the owner calls it). outlook: the accounts the owner let
    JARVIS use in classic Outlook on this PC (jcc/outlook.py); each is a way of its own, "outlook:<address>"."""
    found = []
    if online:
        found.append(("online", f"your connected account ({address})" if address else "your connected account"))
    if smtp:
        found.append(("account", f"your email account in JARVIS ({smtp_address})" if smtp_address else "your email account in JARVIS"))
    for account in outlook or ():
        found.append(("outlook:" + str(account).lower(), outlook_label(account)))
    label = app or app_label()
    if not (outlook and re.match(r"\s*outlook\b", label, re.I)):
        found.append(("app", label))         # (while Outlook itself sends, a draft in the same Outlook would be the same mail twice over)
    if preferred == "gmail" or any(re.search(r"\bgmail\b", str(title), re.I) for title in titles):
        found.append(("gmail", "Gmail in your browser"))
    return found


def listing(found) -> str:
    """ "your connected account (a@b.co), Outlook on this PC, or Gmail in your browser" """
    names = [label for _, label in found]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + ", or " + names[-1]


_OUTLOOK_MAIL = ("@outlook.com", "@hotmail.com", "@live.com", "@msn.com")
_FILLER = frozenset("my the a an from with using use via through in on by send it its me email e-mail mail account address "
                    "work school office business personal outlook connected composio new classic app one this pc please but and".split())
_CONNECTED = re.compile(r"\b(connected|composio)\b")
# "not the connected one", "anything except Outlook", "instead of asha.k": a negator directly before what is ruled out.
# ("no, the connected account" is a yes: a bare "no" rules nothing out.)
_NEGATED = re.compile(r"\b(?:not|instead of|rather than|other than|except)\s+(?:(?:the|my|that|from|using|use|through|via|with|in)\s+)*"
                      r"([a-z0-9][a-z0-9.@+_\-]*)")
_SAME_AS = {"composio": "connected", "google": "gmail"}           # (what a ruled-out word is called in the list of ways)


def _choose_negated(said: str, connected: bool, preferred: str, titles, online: bool, address: str, smtp_address: str,
                    outlook: list[str], app: str) -> str:
    """choose() when the owner ruled a way out ("not asha.k", "not Outlook"): never that way. The rest of what they said
    chooses among the others, and when that is not clear, they are asked."""
    found = ways(connected, online, address, preferred, titles, smtp_address, app=app, outlook=outlook)
    out = {_SAME_AS.get(word.strip("."), word.strip(".")) for word in _NEGATED.findall(said)}
    out = {word for word in out if len(word) > 2 and word not in ("the", "one", "this", "that", "its", "you", "your")}
    excluded = {way for way, label in found if any(word in label.lower() or word == way for word in out)}
    rest = " ".join(_NEGATED.sub(" ", said).split())
    if [w for w in re.findall(r"[a-z0-9][a-z0-9.\-_+@]*", rest) if w not in _FILLER]:
        picked = choose(rest, connected, preferred, titles, online, address, smtp_address, outlook, app)
        return "ask" if picked in excluded else picked
    left = [way for way, _ in found if way not in excluded]
    return left[0] if len(left) == 1 else "ask"


def choose(using: str = "", connected: bool = False, preferred: str = "auto", titles=(), online: bool = False, address: str = "",
           smtp_address: str = "", outlook=(), app: str = "") -> str:
    """Which way a message goes: "online" (the account connected through Composio: the one the assistant reads mail in),
    "account" (an account set up in JARVIS itself), "outlook:<address>" (that account in classic Outlook on this PC),
    "gmail" (Gmail in the browser) or "app" (the PC's mail app). Or "ask": more than one could send it and the owner has
    not said which. Or "none": they named one that cannot send it.

    using: what the owner said, if they named one ("from asha.k", "with Outlook", "connected account").
    connected: an account is set up in JARVIS itself (smtp_address).  online: one is connected through Composio (address,
    once it is known).  outlook: the Outlook accounts the owner let JARVIS use.  titles: the windows that are open.
    app: what the PC's mail app is called (looked up when not given)."""
    said = " ".join(str(using or "").lower().split())
    gmail_open = preferred == "gmail" or any(re.search(r"\bgmail\b", str(title), re.I) for title in titles)
    outlook = [str(a).lower() for a in outlook or () if str(a).strip()]
    if said and _NEGATED.search(said):
        return _choose_negated(said, connected, preferred, titles, online, address, smtp_address, outlook, app)
    if outlook:
        picked = _choose_with_outlook(said, outlook, connected, preferred, titles, online, address, smtp_address, app)
        if picked:
            return picked
    if said:
        if _APP_WORDS.search(said):
            return "app"
        if _BROWSER_WORDS.search(said):
            return "gmail"
        named = ADDRESS.search(said)
        if named:
            wanted = named.group(0).lower()
            if connected and wanted == smtp_address.lower():
                return "account"
            if online and (not address or wanted == address.lower()):
                return "online"           # (an address not known yet is checked by the helper: it sends from that one or not at all)
            return "none"
        if _GOOGLE_WORDS.search(said) and not _ACCOUNT_WORDS.search(said):
            # Gmail in the browser and a connected Google account may be two different people's mail: only one, or say which.
            if online and (address.lower().endswith(_GOOGLE_MAIL) or not gmail_open):
                return "online"
            return "ask" if online else "gmail"
        if online:
            return "online"               # "connected account", "asha.k", "my school email": the helper sends from that one or says it cannot
        return "account" if connected and _ACCOUNT_WORDS.search(said) else "none"
    if preferred in ("gmail", "app") and not online and not connected:
        return preferred                  # (the owner chose where their mail is written when no account is connected)
    found = ways(connected, online, address, preferred, titles, smtp_address, app="-")
    return found[0][0] if len(found) == 1 else "ask"


def _choose_with_outlook(said: str, outlook: list[str], connected: bool, preferred: str, titles, online: bool, address: str,
                         smtp_address: str, app: str) -> str:
    """choose() while Outlook on this PC is switched on: "" leaves the choice to the rules for when it is off."""
    address, smtp_address = address.lower(), smtp_address.lower()
    if not said:
        found = ways(connected, online, address, preferred, titles, smtp_address, app=app, outlook=outlook)
        return found[0][0] if len(found) == 1 else "ask"
    named = ADDRESS.search(said)
    if online and _CONNECTED.search(said):
        # JARVIS calls the Composio one "your connected account": an answer that says so never goes through Outlook.
        # ("not the connected one" never reaches here: choose() takes out what the owner ruled out first.)
        wanted = named.group(0).lower().strip(".") if named else ""
        # (unless it names an address that is not the connected one: then which of the two they meant is not clear)
        return "ask" if wanted and wanted != address and (address or wanted in outlook) else "online"
    app_is_outlook = bool(re.match(r"\s*outlook\b", app or app_label(), re.I))
    if named:
        wanted = named.group(0).lower().strip(".")
        if wanted in outlook:
            # The same account in Outlook and through Composio: two ways to send one person's mail, so the owner says which.
            return "ask" if online and address and wanted == address else "outlook:" + wanted
        if _APP_WORDS.search(said) and not app_is_outlook:
            return ""                     # (another mail app: as when Outlook is off)
        if connected and wanted == smtp_address:
            return "account"
        if online and (not address or wanted == address):
            return "online"
        return "none"                     # (an Outlook account the owner did not tick included: it is never used)
    if re.search(r"\boutlook\b", said) or (app_is_outlook and _APP_WORDS.search(said)):
        picks = {"outlook:" + a: a for a in outlook}
        if online and address.endswith(_OUTLOOK_MAIL):
            picks["online"] = address
        words = [w for w in re.findall(r"[a-z0-9][a-z0-9.\-_+]*", said) if w not in _FILLER]
        if words:                         # ("Outlook, but with asha.k": the other words say which of them)
            picks = {way: known for way, known in picks.items() if known and all(w in known for w in words)} or picks
        return next(iter(picks)) if len(picks) == 1 else "ask"
    if _APP_WORDS.search(said) or _BROWSER_WORDS.search(said):
        return ""                         # (another mail app, or Gmail in the browser)
    candidates = {"outlook:" + a: a for a in outlook}
    if online:
        candidates["online"] = address
    if connected:
        candidates["account"] = smtp_address
    words = [w for w in re.findall(r"[a-z0-9][a-z0-9.\-_+]*", said) if w not in _FILLER]
    if words:
        hits = [way for way, known in candidates.items() if known and all(w in known for w in words)]
        if len(hits) == 1:
            return hits[0]
        if not hits and _GOOGLE_WORDS.search(said) and not any(a.endswith(_GOOGLE_MAIL) for a in outlook):
            return ""                     # ("my Gmail", and no Outlook account is a Gmail one: as when Outlook is off)
        return "ask"
    if online and _ACCOUNT_WORDS.search(said):
        return "ask"                      # ("my account": Outlook's accounts are the owner's too)
    found = ways(connected, online, address, preferred, titles, smtp_address, app=app, outlook=outlook)
    return found[0][0] if len(found) == 1 else "ask"


def gmail_link(to: str, subject: str, body: str) -> str:
    """Gmail's own address for a new message with everything filled in."""
    return ("https://mail.google.com/mail/?view=cm&fs=1&to=" + quote(", ".join(recipients(to))) + "&su=" + quote(str(subject)[:300]) +
            "&body=" + quote(str(body)[:6000]))


@dataclass
class Draft:
    kind: str                     # gmail | app
    title: str = ""               # the draft window's title, once it is open
    problem: str = ""             # why there is no draft to send
    opened: float = field(default_factory=time.monotonic)
    label: str = ""               # what the owner calls it: "Outlook on this PC"

    @property
    def where(self) -> str:
        return self.label or ("Gmail in your browser" if self.kind == "gmail" else "the mail app on this PC")


_SIGNED_OUT = re.compile(r"sign in|google accounts|choose an account", re.I)


def open_draft(kind: str, desktop, to: str, subject: str, body: str, opener=None, wait: float = 12.0, pause=time.sleep, label: str = "") -> Draft:
    """Show the message as a draft the owner can see: in Gmail in their browser, or in the PC's mail app. Nothing is sent."""
    where = Draft(kind, label=label).where
    before = desktop.window_title()
    if kind == "gmail":
        link = gmail_link(to, subject, body)
        if opener is None:
            import webbrowser
            opener = webbrowser.open
        looks = re.compile(r"gmail|compose|new message|mail\.google", re.I)
    else:
        link = "mailto:" + quote(", ".join(recipients(to))) + "?subject=" + quote(str(subject)[:300]) + "&body=" + quote(str(body)[:6000])
        if opener is None:
            from jcc import system
            opener = system.open_url      # a mailto link, opened by the owner's own mail app
        looks = re.compile(r"mail|outlook|gmail|message|compose|thunderbird|" + re.escape(str(subject)[:16] or "\x00"), re.I)
    try:
        opener(link)
    except OSError:
        return Draft(kind, problem=NO_APP if kind != "gmail" else "The browser could not be opened, so the message was not written. Nothing was sent.")
    deadline, title = time.monotonic() + wait, ""
    while time.monotonic() < deadline:
        pause(0.5)
        title = desktop.window_title()
        if kind == "gmail" and title and _SIGNED_OUT.search(title):
            return Draft(kind, title, "NOT sent. Gmail is not signed in in the user's browser, so the message could not be written there. "
                                      "Ask them to sign in to Gmail, or which other account to send it from.", label=label)
        if title and title != before and looks.search(title):
            return Draft(kind, title, label=label)
    return Draft(kind, problem=f"NOT sent. A draft was opened in {where}, but its window did not come to the front, so Send was not pressed. "
                               "Tell the user the draft is waiting there for them to press Send, or that they can name another account to send it from. "
                               "Never call it sent.", label=label)


def press_send(draft: Draft, desktop, uia, handle_of, to: str, pause=time.sleep) -> str:
    """Send the draft that open_draft() showed. The owner has said yes to this exact message."""
    title = draft.title
    if draft.kind == "gmail":
        while time.monotonic() - draft.opened < 4.0:          # Gmail takes a moment to finish loading the message
            pause(0.5)
        now = desktop.window_title()
        if not re.search(r"gmail|compose|new message", now, re.I):
            return "The draft is open in Gmail, but another window came to the front, so Send was not pressed. NOT sent. Ask the user to press Send in Gmail."
        title = now
        desktop.perform({"action": "key", "keys": "ctrl+enter"})    # Gmail's own shortcut for Send
        for _ in range(16):
            pause(0.5)
            if desktop.window_title() != title:
                return f"Sent to {to} from {draft.where}."
        return (f"Send was pressed in {draft.where}, but the message window still seems to be open. It may NOT have been sent. Look at the screen to check "
                "before telling the user it was sent.")
    looks = re.compile(r"mail|outlook|gmail|message|compose|thunderbird|" + re.escape(title[:16] or "\x00"), re.I)
    pause(1.2)   # let the draft finish loading
    how = ""
    try:
        found = (uia.call({"op": "find", "h": handle_of(), "name": "Send"}, timeout=6.0) or {}).get("item")
        if found and re.fullmatch(r"send( now| message| email| \(.{1,20}\))?", str(found.get("n", "")).strip(), re.I):
            result = uia.call({"op": "press", "h": handle_of(), "name": found["n"]}, timeout=6.0) or {}
            how = result.get("how") or ""
            if how == "click":
                from jcc.computer import picture_point
                look = getattr(desktop, "look", None)
                if look:
                    look(handle_of())                  # positions are counted on the screen that shows the mail window
                at = picture_point(desktop, found["x"], found["y"])
                desktop.perform({"action": "click", "x": at[0], "y": at[1]})
    except (TimeoutError, OSError, ValueError):
        how = ""
    if not how:
        if not looks.search(desktop.window_title()):
            return "The draft is open, but another window came to the front, so Send was not pressed. NOT sent. Ask the user to send it."
        desktop.perform({"action": "key", "keys": "ctrl+enter"})
    for _ in range(12):
        pause(0.5)
        if desktop.window_title() != title:
            return f"Sent to {to} from {draft.where}."
    return (f"Send was pressed in {draft.where}, but the draft still seems to be open. It may NOT have been sent. Look at the screen to check "
            "before telling the user it was sent.")


def recipients(to: str) -> list[str]:
    found = [part.strip() for part in re.split(r"[,;]", str(to)) if part.strip()]
    if not found or len(found) > 10 or not all(ADDRESS.fullmatch(part) for part in found):
        raise ValueError("That does not look like an email address. Ask the user for the address.")
    return found


def settings(cfg) -> dict:
    path = cfg.state_dir / "mail.json"
    try:
        saved = json.loads(path.read_text("utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        saved = {}
    return saved if isinstance(saved, dict) else {}


def status(cfg) -> dict:
    saved = settings(cfg)
    connected = bool(saved.get("address") and secrets.get("mail"))
    return {"connected": connected, "address": saved.get("address", "") if connected else "", "name": saved.get("name", ""),
            "host": saved.get("host", "") if connected else ""}


def _open(host: str, port: int, factory=None):
    if factory:
        return factory(host, port)
    context = ssl.create_default_context()
    if port == 465:
        return smtplib.SMTP_SSL(host, port, timeout=20, context=context)
    server = smtplib.SMTP(host, port, timeout=20)
    server.starttls(context=context)
    return server


def _explain(error: Exception, host: str) -> str:
    if isinstance(error, smtplib.SMTPAuthenticationError):
        extra = (" For Gmail, turn on 2-Step Verification, then create an app password at myaccount.google.com/apppasswords and paste "
                 "its 16 letters here (your normal password will not work).") if "gmail" in host else " Most providers need an app password, not your normal one."
        return "The mail server did not accept that address and password." + extra
    if isinstance(error, smtplib.SMTPRecipientsRefused):
        return "The mail server refused that recipient address."
    if isinstance(error, (smtplib.SMTPException, ssl.SSLError)):
        return "The mail server refused the message: " + str(error)[:160]
    return "The mail server could not be reached. Check the internet connection and try again."


def connect(cfg, address: str, password: str, host: str = "", port=0, name: str = "", factory=None) -> dict:
    address, password = str(address).strip(), str(password).strip()
    if not ADDRESS.fullmatch(address):
        raise ValueError("Enter your full email address.")
    domain = address.rsplit("@", 1)[1].lower()
    if not host and domain in NO_PASSWORD_SIGN_IN:
        raise ValueError("Outlook and Hotmail no longer let apps sign in with a password. Leave this empty: JARVIS will use your mail app for those.")
    if not host:
        if domain not in PROVIDERS:
            raise ValueError("JARVIS does not know the mail server for that address. Enter its outgoing (SMTP) server name as well.")
        host, port = PROVIDERS[domain]
    host = str(host).strip().lower()
    try:
        port = int(port) or 587
    except (TypeError, ValueError):
        port = 587
    if not re.fullmatch(r"[a-z0-9.-]{4,120}", host) or port not in (25, 465, 587, 2525):
        raise ValueError("Enter a normal mail server name and port (587 or 465).")
    if "gmail" in host or "yahoo" in host:
        password = password.replace(" ", "")   # app passwords are shown in groups of four
    if not 6 <= len(password) <= 200:
        raise ValueError("Paste the app password your mail provider gave you.")
    try:
        server = _open(host, port, factory)
        try:
            server.login(address, password)
        finally:
            try:
                server.quit()
            except (smtplib.SMTPException, OSError):
                pass
    except (smtplib.SMTPException, OSError, ssl.SSLError) as error:
        raise ValueError(_explain(error, host)) from None
    secrets.store("mail", password)
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(cfg.state_dir / "mail.json", json.dumps({"address": address, "host": host, "port": port, "name": " ".join(str(name).split())[:60]}))
    return status(cfg)


def verify(cfg, factory=None) -> str:
    """Sign in to the connected account once, to make sure it still works. Raises ValueError with a plain reason if not."""
    saved, password = settings(cfg), secrets.get("mail")
    if not saved.get("address") or not password:
        raise ValueError("No email account is connected.")
    try:
        server = _open(str(saved.get("host", "")), int(saved.get("port") or 587), factory)
        try:
            server.login(saved["address"], password)
        finally:
            try:
                server.quit()
            except (smtplib.SMTPException, OSError):
                pass
    except (smtplib.SMTPException, OSError, ssl.SSLError) as error:
        raise ValueError(_explain(error, str(saved.get("host", "")))) from None
    return f"Signed in to {saved.get('host', 'the mail server')} as {saved['address']}."


def disconnect(cfg) -> dict:
    secrets.delete("mail")
    (cfg.state_dir / "mail.json").unlink(missing_ok=True)
    return status(cfg)


def send(cfg, to: str, subject: str, body: str, factory=None) -> str:
    """Send through the connected account. Raises ValueError with a plain reason when it fails."""
    saved, password = settings(cfg), secrets.get("mail")
    if not saved.get("address") or not password:
        raise ValueError("No email account is connected.")
    targets = recipients(to)
    message = EmailMessage()
    message["From"] = f'{saved["name"]} <{saved["address"]}>' if saved.get("name") else saved["address"]
    message["To"] = ", ".join(targets)
    message["Subject"] = " ".join(str(subject).split())[:300] or "(no subject)"
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=saved["address"].rsplit("@", 1)[1])
    message.set_content(str(body)[:20000] or " ")
    try:
        server = _open(saved["host"], int(saved.get("port") or 587), factory)
        try:
            server.login(saved["address"], password)
            refused = server.send_message(message)
        finally:
            try:
                server.quit()
            except (smtplib.SMTPException, OSError):
                pass
    except (smtplib.SMTPException, OSError, ssl.SSLError) as error:
        raise ValueError(_explain(error, saved.get("host", ""))) from None
    if refused:
        return "Sent, but the server refused: " + ", ".join(refused)
    return f"Sent to {', '.join(targets)} from {saved['address']}."


def send_with_app(desktop, uia, handle_of, to: str, subject: str, body: str, opener=None, wait: float = 12.0, pause=time.sleep, kind: str = "app") -> str:
    """Open a draft (in the PC's mail app, or in Gmail) and send it. The owner has already approved the message."""
    draft = open_draft(kind, desktop, to, subject, body, opener, wait, pause)
    if draft.problem:
        return draft.problem
    return press_send(draft, desktop, uia, handle_of, to, pause)
