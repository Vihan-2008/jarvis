"""Help with JARVIS itself: how to set up any feature, and where the owner's data goes when it leaves this computer.

The assistant reaches this through the `app_help` tool, on the computer and from the phone app; the phone relay keeps a
copy (jcc/phone.py context_pack) so it can answer these questions with the laptop off too.

DATA_MAP is the plain truth about every place JARVIS sends data, including the gaps the 2026-11-28 audit found. The
test tests/test_app_help.py fails when a new outside address appears in jcc/ without being listed here, so the map
cannot quietly fall behind the code.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
GUIDES = ("GUIDE.md", "INSTALL.md", "PLATFORMS.md")
MOST = 6000                      # how much one answer may hold

# Every place JARVIS sends data. `hosts` are the fixed addresses in jcc/ that belong to the entry (the test checks them);
# addresses made at run time (the owner's own Supabase project, their phone page, their website) are named in `where`.
DATA_MAP: list[dict] = [
    {"key": "claude", "name": "The Claude brain", "where": "Anthropic, including Anthropic's web search",
     "what": "Each message you send, the last 40 things JARVIS remembers about you, the names of your installed apps, a short "
             "summary of your screen, attached files (with passwords and keys blanked out), the last few chat messages, and "
             "what tools found: screenshots, files JARVIS read, the clipboard, mail and connected-account results.",
     "when": "Every reply that Claude gives (the default brain).", "off": "Choose another brain in the model chip, or sign out of Claude.",
     "hosts": ()},
    {"key": "chatgpt", "name": "ChatGPT through Codex", "where": "OpenAI, including its live web search",
     "what": "The same as the Claude brain, plus the last six exchanges.", "when": "When you choose ChatGPT, or when Claude is unavailable.",
     "off": "Choose another brain, or sign out of ChatGPT.", "hosts": ()},
    {"key": "providers", "name": "AI services you connect with a key", "where": "Only the services you connect: OpenAI, Gemini, xAI, "
     "Perplexity, Groq, DeepSeek, Mistral, OpenRouter, Together, Cerebras, Fireworks, Moonshot, Cohere, or an address you give",
     "what": "Your message, the conversation, and up to 1500 characters of what JARVIS remembers. Never screenshots. Perplexity "
             "gets only the question and the date. Ollama and LM Studio run on this computer and send nothing.",
     "when": "Only after you connect that service.", "off": "Settings, AI services, Disconnect (the key is deleted).",
     "hosts": ("api.openai.com", "generativelanguage.googleapis.com", "api.x.ai", "api.perplexity.ai", "api.groq.com", "api.deepseek.com",
               "api.mistral.ai", "openrouter.ai", "api.together.xyz", "api.cerebras.ai", "api.fireworks.ai", "api.moonshot.ai", "api.cohere.ai")},
    {"key": "classifier", "name": "Sorting requests, quick answers and the Inbox watcher", "where": "Gemini and Groq",
     "what": "Up to 2000 characters of your request and the notes it links to. Private notes are refused, but a note marked "
             "cloud_sync: false is still sent.",
     "when": "When a request is sorted or answered quickly; the Inbox watcher reads Inbox.md every few seconds and can send its "
             "to-do lines without you doing anything.",
     "off": "Set classifier to none and remove the Gemini and Groq keys.", "gap": "cloud_sync: false is not honoured here.", "hosts": ()},
    {"key": "coding", "name": "Coding jobs, planning and reviews", "where": "Anthropic, OpenAI, Google and xAI, through their command-line tools",
     "what": "The task, the chat, the project's files, its Memory and Recent work notes, linked notes and memory search results. "
             "Notes marked cloud_sync: false are sent.",
     "when": "When a coding job runs.", "off": "Don't start coding jobs, or sign those tools out.", "gap": "cloud_sync: false is not honoured here.",
     "hosts": ()},
    {"key": "prompt_master", "name": "Prompt Master", "where": "Anthropic, then your connected AI services",
     "what": "Your draft and up to 6000 characters of project memory.", "when": "Only when you use it.", "off": "Don't use it.", "hosts": ()},
    {"key": "composio", "name": "Online accounts (Composio)", "where": "Composio, the account you connected, and a helper AI at Anthropic or OpenAI",
     "what": "What you asked for and what the account sends back.", "when": "Only after you connect it. Changes ask you first.",
     "off": "Connections, Online accounts, Disconnect (the key is deleted).",
     "hosts": ("backend.composio.dev", "connect.composio.dev", "dashboard.composio.dev")},
    {"key": "connectors", "name": "Connectors (MCP)", "where": "The service you added, and Anthropic",
     "what": "What the assistant asks the connector and what it answers.", "when": "Only connectors you add, in Claude chats.",
     "off": "Remove the connector.", "hosts": ()},
    {"key": "cloud_memory", "name": "Cloud memory", "where": "Your own Supabase project",
     "what": "Your vault's notes in small pieces, with passwords and keys blanked out, and your memory searches. Private notes are "
             "left out, but notes marked explicit-links-only are kept, and every saved conversation in Conversations/ is uploaded "
             "(JARVIS chats, ChatGPT and Claude website captures, Claude Code and Codex transcripts, saved web pages).",
     "when": "Only after you switch it on. Waits on metered networks.",
     "off": "There is no switch in the app yet: delete cloud-memory.json in the JARVIS state folder, or remove the supabase-sync key.",
     "gap": "Explicit-links-only notes and all saved conversations are uploaded, and the app has no off switch.",
     "status": "cloud_memory", "hosts": ()},
    {"key": "vault_git", "name": "Vault backup to GitHub", "where": "A GitHub repository",
     "what": "Your whole vault with no filter: Private/ and notes marked private: true are included.",
     "when": "Only if the backup was set up. Obsidian Git then pushes every 10 minutes.",
     "off": "Turn off auto-push in Obsidian Git's settings and delete github.json in the JARVIS state folder.",
     "gap": "Private notes are not left out of this backup.", "status": "vault_git", "hosts": ("api.github.com",)},
    {"key": "history", "name": "Browser history sync", "where": "Nowhere outside: the extension talks only to JARVIS on this computer",
     "what": "Pages you visit become vault notes. Those notes then reach cloud memory and the vault backup if those are on.",
     "when": "Only with the extension installed.", "off": "Remove the extension.", "hosts": ()},
    {"key": "speech", "name": "Listening and speaking", "where": "Whisper at Groq or OpenAI; ElevenLabs; your browser's own speech service (often Microsoft or Google)",
     "what": "Your voice, and a hint made of names and words you added. The wake word is heard on this computer only.",
     "when": "While you talk to JARVIS or it talks to you.", "off": "Set listening and speaking to Browser, or remove the keys.",
     "hosts": ("api.elevenlabs.io",)},
    {"key": "web", "name": "Web tools", "where": "The sites asked: web pages, YouTube, JustWatch, Open-Meteo, Pollinations, Google search",
     "what": "The address or search words, a film's title and your country (JustWatch), a place name (weather), a picture's "
             "description (in the address, to Pollinations).",
     "when": "When the assistant uses them. In careful mode with private content it asks first.", "off": "Ask JARVIS not to use them.",
     "hosts": ("www.youtube.com", "apis.justwatch.com", "api.open-meteo.com", "geocoding-api.open-meteo.com", "image.pollinations.ai", "www.google.com")},
    {"key": "mail", "name": "Mail", "where": "Your mail server; Gmail (a draft link holds the recipient, subject and body); Outlook's servers",
     "what": "The message you approved.", "when": "Every send asks you first.", "off": "Don't connect mail.", "hosts": ("mail.google.com",)},
    {"key": "sites", "name": "Your websites", "where": "WordPress, Shopify, Wix and Squarespace",
     "what": "What JARVIS reads there, and the changes you publish.", "when": "Only sites you connect. Publishing asks you first.",
     "off": "Remove the site.", "hosts": ("public-api.wordpress.com", "www.wixapis.com", "api.squarespace.com")},
    {"key": "trading", "name": "Trading and bot status", "where": "Your own server", "what": "A signed request for the status; nothing is sent about you.",
     "when": "Only after you connect it.", "off": "Remove the connection.", "hosts": ()},
    {"key": "updates", "name": "Updates", "where": "GitHub", "what": "Only what any web request carries: your IP address and the app's name.",
     "when": "Once a day by default.", "off": "Settings, Updates, Off.", "status": "updates", "hosts": ("github.com",)},
    {"key": "skills", "name": "Skills, accounts and page previews", "where": "GitHub (skills you add), claude.ai and chatgpt.com (their install "
     "scripts), and the code libraries pages may load (jsDelivr, cdnjs, unpkg, Tailwind, Google Fonts)",
     "what": "Your IP address and which page asked.", "when": "When you add a skill, sign in, or open a page JARVIS made.",
     "off": "Don't add skills; pages are sealed unless you allow the internet for one.",
     "hosts": ("cdn.jsdelivr.net", "cdnjs.cloudflare.com", "unpkg.com", "cdn.tailwindcss.com", "fonts.googleapis.com", "fonts.gstatic.com",
               "claude.ai", "chatgpt.com")},
    {"key": "phone", "name": "The phone app", "where": "Your own Supabase project and your own Cloudflare account; with laptop-off "
     "answers on, the AI services you switch on for it, and Whisper for voice notes",
     "what": "Messages, files and voice notes from your phone, and JARVIS's answers, sealed in your Supabase project for up to 7 "
             "days. Private notes are left out of the Phone chat. With laptop-off answers on, the chosen service reads the message "
             "and a short summary of what JARVIS remembers. Nothing goes to the JARVIS project.",
     "when": "Only after you set it up with /phone.", "off": "/phone, Remove the phone app. A lost phone: Remove it there, or pause the "
     "project at supabase.com.", "status": "phone", "hosts": ("api.supabase.com", "api.cloudflare.com")},
]
# Addresses in jcc/ that JARVIS never sends your data to by itself: links it opens in your browser when you ask (quick.py),
# pages that tell you where to get a key, help links, and names inside file formats.
LINKS_ONLY = frozenset({
    "aistudio.google.com", "console.groq.com", "console.x.ai", "console.mistral.ai", "dashboard.cohere.com", "platform.openai.com",
    "platform.deepseek.com", "platform.moonshot.ai", "cloud.cerebras.ai", "fireworks.ai", "www.perplexity.ai", "api.together.ai",
    "ollama.com", "lmstudio.ai", "code.claude.com", "learn.chatgpt.com", "rait-09.github.io", "schemas.openxmlformats.org", "www.w3.org", "supabase.com", "dash.cloudflare.com",
    "calendar.google.com", "discord.com", "docs.google.com", "drive.google.com", "en.wikipedia.org", "maps.google.com", "meet.google.com",
    "open.spotify.com", "outlook.live.com", "photos.google.com", "sheets.google.com", "stackoverflow.com", "translate.google.com",
    "web.telegram.org", "web.whatsapp.com", "www.amazon.in", "www.bing.com", "www.canva.com", "www.facebook.com", "www.flipkart.com",
    "www.hotstar.com", "www.imdb.com", "www.instagram.com", "www.linkedin.com", "www.netflix.com", "www.notion.so", "www.primevideo.com",
    "www.reddit.com", "www.wikipedia.org", "x.com", "zoom.us"})

PHONE_HELP = """\
## Set up the phone app

Use JARVIS from your phone, from anywhere. About five minutes, free, in your own accounts. Type /phone on your computer.

1. Relay: make an empty project at supabase.com, then make an access token (Account, Access Tokens) and paste it. JARVIS
   creates the tables, the relay function and its secrets. The token is not kept.
2. Phone page: make a free Cloudflare account, then an API token with only "Workers Scripts: Edit" and paste it. JARVIS
   uploads the page and its security headers. A token that can do more is refused unless you let JARVIS use it once and
   forget it.
3. Laptop-off answers (optional): switch on "Use when my laptop is off" for each AI key you want the relay to use. Only
   those keys are copied, with a daily limit. Subscriptions (Claude, ChatGPT) answer only while the laptop is on.
4. Add a phone: scan the code on screen to open the page, add it to your Home Screen (iPhone: Share, Add to Home
   Screen; Android: Install), open it from there, type the 8-letter code, then click "Yes, pair it" on the computer.
   The phone can be anywhere; you can read the code out over a call. Needs iOS 17 or Chrome 137.

The phone shares one chat called Phone. Private notes are left out of it. Anything that needs the computer itself
(running commands, controlling apps), money, deleting, trading or installing can only be approved on the computer.
Lost phone: remove it in /phone, or pause the Supabase project from any browser.
"""

_WORDS = re.compile(r"[a-z0-9]+")
_SKIP = frozenset("the a an and or to of in on for is it do i my me how what where does can with this that from be are you your set up use "
                  "get go when".split())


def _live(cfg, which: str) -> str:
    """This computer's own setting for a feature, as one sentence (or nothing when it cannot be read)."""
    state = Path(getattr(cfg, "state_dir", "") or ".")
    try:
        if which == "vault_git":
            return "On this computer: set up." if (state / "github.json").exists() else "On this computer: not set up."
        if which == "cloud_memory":
            saved = json.loads((state / "cloud-memory.json").read_text(encoding="utf-8")) if (state / "cloud-memory.json").exists() else {}
            return "On this computer: on." if saved.get("enabled") else "On this computer: off."
        if which == "updates":
            from jcc import updates
            return "On this computer: " + str(updates.settings(cfg).get("mode", "auto")) + "."
        if which == "phone":
            from jcc import phone
            saved = phone.settings(cfg)
            return ("On this computer: set up, page at " + saved["origin"] + ".") if saved.get("origin") else "On this computer: not set up."
    except Exception:  # noqa: BLE001 - help still answers without the live line
        return ""
    return ""


def _synced_folder(cfg) -> str:
    vault = str(getattr(cfg, "vault", "") or "")
    for marker, company in (("OneDrive", "Microsoft"), ("Dropbox", "Dropbox"), ("Google Drive", "Google"), ("iCloud", "Apple"), ("Mobile Documents", "Apple")):
        if marker.lower() in vault.lower():
            return (f" Your vault is in a {marker} folder, so {company} holds a copy of all of it, Private/ included, whatever "
                    "JARVIS does.")
    return ""


def data_entry(cfg, entry: dict) -> dict:
    lines = [f"Goes to: {entry['where']}.", f"What: {entry['what']}", f"When: {entry['when']}", f"How to switch it off: {entry['off']}"]
    if entry.get("gap"):
        lines.append("Known gap: " + entry["gap"])
    if entry.get("status"):
        live = _live(cfg, entry["status"])
        if live:
            lines.append(live)
    return {"title": "Where your data goes: " + entry["name"], "text": "\n".join(lines)}


def _guide_sections(text: str, source: str) -> list[dict]:
    found = []
    for part in re.split(r"(?m)^## ", text)[1:]:
        title, _, body = part.partition("\n")
        body = body.strip()
        if body:
            found.append({"title": title.strip(), "text": body, "source": source})
    return found


def sections(cfg) -> list[dict]:
    """Everything the help knows, as [{title, text}]: the guides, phone setup, AI keys, and the data map."""
    found: list[dict] = []
    for name in GUIDES:
        path = DOCS / name
        if path.is_file():
            found += _guide_sections(path.read_text(encoding="utf-8", errors="replace"), name)
    found += _guide_sections(PHONE_HELP, "phone")
    try:
        from jcc.providers import CATALOG
        for ident, item in CATALOG.items():
            how = ("It runs on this computer: install it from " + item["get"] + ", then choose it in Settings, AI services."
                   if item.get("local") else
                   ("Get a key at " + item["get"] + ", then paste it in Settings, AI services, Connect." if item.get("get") else
                    "Give its address and a key in Settings, AI services, Connect."))
            found.append({"title": "Connect " + item["name"], "text": item["about"] + " " + how, "source": "providers"})
    except Exception:  # noqa: BLE001
        pass
    found.append({"title": "Where your data goes: overview", "source": "data",
                  "text": "JARVIS sends nothing to the JARVIS project: no telemetry, no crash reports. Each feature below says where its "
                          "data goes. Screenshots and the clipboard go to the chosen brain without filtering, and a note marked "
                          "cloud_sync: false is honoured only by cloud memory." + _synced_folder(cfg)})
    found += [dict(data_entry(cfg, entry), source="data") for entry in DATA_MAP]
    return found


def _words(text: str) -> set[str]:
    return {w for w in _WORDS.findall(text.lower()) if w not in _SKIP and len(w) > 1}


def search(cfg, question: str, most: int = 3) -> list[dict]:
    """The sections that best match a question, best first."""
    asked = _words(question)
    if not asked:
        return []
    about_data = bool(asked & {"data", "privacy", "private", "sent", "send", "sends", "leave", "leaves", "share", "shared", "goes", "cloud"})
    about_setup = bool(set(_WORDS.findall(question.lower())) & {"set", "setup", "install", "connect", "configure", "add", "pair", "start"})
    scored = []
    for item in sections(cfg):
        title, text = _words(item["title"]), _words(item["text"])
        score = 3 * len(asked & title) + len(asked & text)
        if about_data and item.get("source") == "data":
            score += 2
        elif about_setup and item.get("source") == "data":
            score -= 2                         # "how do I set up X" wants the steps, not where X's data goes
        if score:
            scored.append((score, item))
    scored.sort(key=lambda pair: -pair[0])
    return [item for _, item in scored[:most]]


def answer(cfg, question: str) -> str:
    found = search(cfg, question)
    if not found:
        return ("The JARVIS guide has nothing on that. Say so plainly; the guide's topics are: "
                + ", ".join(item["title"] for item in sections(cfg) if item.get("source") in GUIDES or item.get("source") == "phone")[:1500])
    out = "\n\n".join("## " + item["title"] + "\n" + item["text"] for item in found)
    return out[:MOST]
