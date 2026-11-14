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


def choose(using: str = "", connected: bool = False, preferred: str = "auto", titles=()) -> str:
    """Which way a message goes: "account" (the connected one), "gmail" (Gmail in the browser) or "app" (the PC's mail app).

    using: what the owner said, if they named one ("in Gmail", "with Outlook").  titles: the windows that are open."""
    said = " ".join(str(using or "").lower().split())
    if re.search(r"gmail|google", said):
        return "gmail"
    if re.search(r"outlook|thunderbird|mail app|windows mail|\bapp\b", said):
        return "app"
    if connected:
        return "account"
    if preferred in ("gmail", "app"):
        return preferred
    return "gmail" if any(re.search(r"\bgmail\b", str(title), re.I) for title in titles) else "app"


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

    @property
    def where(self) -> str:
        return "Gmail" if self.kind == "gmail" else "the mail app"


_SIGNED_OUT = re.compile(r"sign in|google accounts|choose an account", re.I)


def open_draft(kind: str, desktop, to: str, subject: str, body: str, opener=None, wait: float = 12.0, pause=time.sleep) -> Draft:
    """Show the message as a draft the owner can see: in Gmail in their browser, or in the PC's mail app. Nothing is sent."""
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
            return Draft(kind, title, "Gmail is not signed in in the user's browser, so the message could not be written there. Nothing was sent. "
                                      "Ask them to sign in to Gmail, or offer the PC's mail app instead (using: mail app).")
        if title and title != before and looks.search(title):
            return Draft(kind, title)
    return Draft(kind, problem=("The draft was opened in the mail app, but it did not come to the front, so Send was not pressed. Tell the user the draft "
                                "is waiting for them, or that they can connect an email account in JARVIS so messages are sent directly.")
                 if kind != "gmail" else
                 "Gmail was opened with the message filled in, but its window did not come to the front, so Send was not pressed. Nothing was sent. "
                 "Tell the user the draft is waiting for them in Gmail.")


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
                return f"The email to {to} was sent from Gmail."
        return ("Send was pressed in Gmail, but the message window still seems to be open. It may NOT have been sent. Look at the screen to check "
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
            return f"The email to {to} was sent from the mail app."
    return ("Send was pressed in the mail app, but the draft still seems to be open. It may NOT have been sent. Look at the screen to check "
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
