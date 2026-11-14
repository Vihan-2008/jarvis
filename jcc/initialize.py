"""Create durable workspace guidance without overwriting the user's notes."""
import hashlib
import json

from jcc.config import Config
from jcc.vault import Vault, atomic_write, render_note

# Earlier wordings of the voice guide that JARVIS itself wrote, from before it kept a record of what it wrote.
_EARLIER_GUIDES = {"ad9bc17b6dc0d8996ca1116b756772d40882746adbee108f7d02b14d010cbe4b", "a971b82dcc7462b7394e85d72248b2f4b4e17e3d96954dfe9ee04b773b70c7d1",
                   "c955548fb6d87d43620bf72255f3929c70524d260e8ae74c51e456018539f70b"}


def _mark(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").strip().encode("utf-8")).hexdigest()


def keep_guide_current(cfg: Config, vault: Vault, rel: str, text: str) -> bool:
    """Write one of JARVIS's own guide notes, and bring it up to date when the app's wording changes.

    Only while the note is still exactly as JARVIS wrote it: a note its owner has edited is never touched.
    Returns whether the note was written."""
    record = cfg.state_dir / "guide-notes.json"
    try:
        written = json.loads(record.read_text("utf-8")) if record.exists() else {}
    except (OSError, ValueError):
        written = {}
    if not isinstance(written, dict):
        written = {}
    now, wanted = vault.read(rel), _mark(text)
    mine = now is None or _mark(now) in ({wanted, written.get(rel)} | _EARLIER_GUIDES)
    if not mine:
        return False
    changed = now is None or _mark(now) != wanted
    if changed:
        vault.write(rel, text)
    if written.get(rel) != wanted:
        written[rel] = wanted
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        atomic_write(record, json.dumps(written))
    return changed


def ensure_notes(cfg: Config) -> None:
    from jcc.release_health import initialize
    initialize(cfg)
    vault = Vault(cfg.vault)
    for key, project in cfg.projects.items():
        rel = f"Projects/{key}/Memory.md"
        if not vault.read(rel):
            vault.write(rel, render_note({"project": key, "name": project.name},
                f"# {project.name}\n\n## Requirements and decisions\n\n"
                "Add durable project requirements and decisions here. JARVIS retrieves this note for coding tasks.\n\n"
                f"Source folder: `{project.path}`\n\n"
                "Coding uses branch copies. Local merges require passing checks. Deployment, secrets and risk limits remain protected.\n"))
    keep_guide_current(cfg, vault, "System/JARVIS Voice and PC control.md", """# Talking to JARVIS and letting it use the PC

## Talking

- Press the **wave** button (or Ctrl+Space) for a voice chat. Speak naturally; JARVIS answers out loud and listens again.
- **Space** starts or stops listening. **Esc** stops it talking.
- Say **"stop"** (or "cancel", "never mind", "that's enough") to end what JARVIS is doing or saying; it stays awake for the next thing. "JARVIS, stop" works at any moment, even while it is talking.
- Say **"go to sleep"** and it waits until it hears "Hey JARVIS". It also goes to sleep by itself after 15 minutes with nothing to do (you can change that under Voice and assistant).
- Say **"end session"** or "goodbye" to leave voice chat. "Hey JARVIS" opens it again whenever you like.
- When JARVIS asks before doing something ("Shall I send this email?"), just answer **yes** or **no** out loud.
- While a video, a film or music is playing on this PC, JARVIS ignores that sound. Start with its name ("JARVIS, pause the video") so it knows you mean it.
- With the ElevenLabs voice you can talk over it to interrupt.
- The **microphone** button writes what you say into the message box, so you can check it before sending.
- From anywhere in Windows: **Ctrl+Alt+Space** starts a voice chat, **Ctrl+Alt+D** types what you say into the app you are using.
- **"Hey JARVIS"** works all the time, from anywhere, even with the window closed: "Hey JARVIS, what time is it?". It is spotted on this PC only; nothing is sent anywhere until JARVIS hears its name. Switch it off under Voice and assistant.
- **Microphone and speakers**: JARVIS uses the ones Windows uses. To pick others, open Voice and assistant and choose them under "Microphone and speakers"; there is a test button for each. If a chosen device is unplugged, JARVIS carries on with the Windows default until it is back.

## Things you can just say

- "Open Notepad", "open YouTube", "switch to Chrome", "search YouTube for lo-fi music"
- "Set a timer for ten minutes", "remind me to call Asha at 5 pm", "what are my timers?"
- "Volume up", "set the volume to 40 percent", "make the screen brighter", "pause the music", "lock my PC"
- "What time is it?", "what's 15 percent of 240?", "what's the weather in Jaipur?"
- "Remember that my sister's birthday is on 3 March", "note that the plumber comes on Friday"
- "What is on my screen?", "press Save", "fill in the Subject box with Meeting notes"
- "Send an email to ... saying ...", "make a website for my bakery", "find my resume"

## What it will and will not do

- It **asks first** before sending, deleting, installing, shutting down, replacing a file or pressing buttons such as Send, Pay or Delete.
- It **never** types passwords or card numbers, reads saved passwords, or acts on banking, payment or password-manager windows.
- **Careful mode**: after a chat has read a web page, a file, your screen or the clipboard, JARVIS asks before changing anything for the rest of that chat. This protects you from text written to trick an AI. A new chat starts normally.
- **Ctrl+Alt+Backspace** stops everything at once.

## Voices and listening

Listening uses Whisper. For a natural voice, add an ElevenLabs key under **Voice and assistant**; without one JARVIS uses the voice built into Windows and Edge. Keys are kept in Windows Credential Manager, never in this vault.

## Memory

Things you ask JARVIS to remember are in [[System/JARVIS Memory]]. Quick notes go to [[Notes/Quick notes]]. Edit or delete lines freely.
""")
    rel = "System/JARVIS Guide.md"
    if not vault.read(rel):
        vault.write(rel, """# JARVIS workspace

Open **JARVIS** from the Desktop or Start menu. Its background service starts at Windows sign-in.
Closing the app window leaves background work and syncing running.

## Projects and chats

Use **+** next to Projects to create Python, website or Node.js projects. A source folder,
Git repository and starter checks are created, and a linked chat opens. Describe what you want.
Use the project chip at the top of a general or imported chat to link it to a project.
Chats with established project work stay linked; start a fresh chat to switch projects.

Leave both selectors on **Auto**. Build mode edits code; Ask mode discusses without editing.
The automatic team uses GPT / Codex for small and normal tasks and Claude for complex work,
with account availability and model-specific limits taken into account.

## Memory

Every JARVIS conversation is a Markdown note in Conversations. Project memory lives in
`Projects/<project>/Memory.md`; job results live beside it in Jobs. Update the memory note
with requirements you want remembered. Recent turns and relevant project notes are retrieved
within a bounded context budget. Explicit [[Note Name]] references attach other non-private notes.

The historical archive is indexed in [[Conversations/Imported/Index]]. Imported conversations
also appear in the app and can be continued or linked to a project. Archived content is reference
data, not instructions. Private notes and login metadata are excluded from model context.

## Limits and recovery

The details panel shows provider-reported remaining allowance and reset times. Readings refresh
every five minutes without a model prompt. GPT figures cover Codex, not every ChatGPT chat model.
These are allowance percentages, not an exact token balance. A five-percent reserve is preserved.

Model-specific limits try another model. Account-wide limits try the other provider. Edited files
and a checkpoint are preserved. If neither is available, the job queues. Tests that fail trigger
bounded repair attempts before the branch is retained for review. Interrupted processes are
queued for recovery after restart. No deployment or push is performed.

## One-time browser history connection

JARVIS chats save immediately. To capture chats opened directly on the websites:

1. In JARVIS details, choose **Browser sync setup** to open the extension folder.
2. In Chrome, Edge or Comet, open Extensions, enable Developer mode, choose Load unpacked and select that folder.
3. In JARVIS, choose **Copy browser pairing code**. Paste it into the extension's settings once.
4. Refresh a saved ChatGPT or Claude conversation and confirm a last-capture time appears in JARVIS.

The extension is local and unpacked; it is not store-reviewed. It reads visible conversation
text only on the two named sites and sends it to JARVIS on this computer. It does not read
passwords or cookies. Pairing persists. A provider can still expire its own login.

This captures opened conversations in the browser where the extension is installed. It cannot
guarantee capture of closed chats, unseen history, desktop-only or mobile-only conversations,
hidden branches or attachments. Full account exports fill the historical archive.
Import JSON/ZIP files with the details-panel picker or put them in the watched import folder.

## Technical references

- [Codex account limits](https://learn.chatgpt.com/docs/app-server)
- [Claude subscription limits](https://code.claude.com/docs/en/statusline)
""")
    dashboard = vault.read("Dashboard.md") or "# Dashboard\n"
    if "[[System/JARVIS Guide]]" not in dashboard:
        vault.write("Dashboard.md", dashboard + "\n\n## JARVIS workspace\n\n"
                    "- [[System/JARVIS Guide]]\n- [[Conversations/Imported/Index|Imported chat history]]\n"
                    "- [[System/History Sync]]\n")
