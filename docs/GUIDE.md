# Using JARVIS

(This guide describes the app on Windows, where every part of it works. What differs on a Mac is in [PLATFORMS.md](PLATFORMS.md).)

Open **JARVIS** from the Desktop or Start menu. No terminal is needed. It opens in a standalone
Edge app window; the local service starts at Windows sign-in and continues after the window closes.
The UI uses a browser engine, rather than a separately bundled native renderer.

## The interface

The home screen shows the animated core and one chat bar. Click the bar to expand it, type, and
press Enter. The core moves to the corner and the chat opens. Everything else is reached from:

- **The chat list** (left, Ctrl+B): New chat, search (Ctrl+K), My work, projects, and your chats.
  Each chat has a `⋯` menu with Star, Rename, Archive and Delete. Deleted chats can be restored.
- **The chat bar**: `+` adds files, photos or a screenshot; the sliders button chooses Auto, Just
  answer or Build and how carefully to think; the model chip picks the AI; the round button sends.
- **The side panel** (icons at the top right): Files, Terminal, Browser, Activity and more open
  beside the chat and can be resized by dragging the panel edge.
- **The account button** (bottom left): Settings, Help, shortcuts, light or dark appearance,
  full screen and the expert tools.

Hovering over any button explains it in plain words. Ctrl+/ lists the keyboard shortcuts.

### Replies

While JARVIS works, the chat shows each step as it happens and the reply text as it is written.
Claude Code is run with its streaming output and Codex with its JSON events; both are reduced to
`live.jsonl` in the job folder (`jcc/live.py`). If an installed Claude Code version rejects the
streaming flags, JARVIS notes that once and uses the earlier single-result mode. Stop ends a
reply; Retry and Edit send the message again. Several chats can work at the same time. A
message that has to wait (two requests already running, or an earlier message in the same chat
or project) starts by itself, and a notice appears when a chat in the background finishes.

### The fast assistant and voice

Typed and spoken messages go to one warm Claude session per chat (`jcc/assistant.py`). The model is
Claude Haiku unless you pick Sonnet or Opus under **Voice and assistant**. Several chats can be
answered at the same time. Choosing **Build**, a GPT model, or attaching a picture uses the coding
agents instead, as before.

- **Speed**: simple requests ("open Notepad", "set a timer for ten minutes", "volume up", "what's
  12 times 8", "what's the weather in Jaipur") are done at once with no AI at all
  (`jcc/quick.py`). For everything else a spare AI session is kept ready, so even the first
  message of a new chat starts answering in about a second.
- **Voice chat** (the wave button, or Ctrl+Space): JARVIS listens, answers out loud sentence by
  sentence, and listens again. Space starts and stops listening, Esc stops it talking. The core
  moves with the real loudness of the voice. You can interrupt by talking: its voice dips at
  once and it stops when real words from you are heard. It keeps working while the window is
  covered or minimised.
- **Listening**: OpenAI's Whisper (large v3) through the free Groq key, about a fifth of a second
  per sentence. With an OpenAI key it uses their current transcription model instead. ElevenLabs
  live transcription and the recogniser built into Edge are the alternatives; JARVIS falls back
  by itself if a service is busy. The free Groq tier allows about twenty requests a minute.
- **Speaking**: ElevenLabs when you add a key under Voice and assistant (kept in Windows
  Credential Manager), streamed as it is made; otherwise the natural voices built into Edge.
- **Wake word, while JARVIS is open**: say "Hey JARVIS" (or "Hey JARVIS, open Notepad" in one breath)
  from anywhere while a JARVIS window is open, minimised included. Close JARVIS and nothing listens:
  the microphone is free until you press Talk or Dictate. The tray helper listens with Windows' own
  offline recogniser (`jcc/wake.py`), which knows only the wake word: ordinary talk never leaves
  the PC. A sentence that starts with it is transcribed by Whisper and handed to JARVIS, and the
  window opens by itself to answer. It stays out of a spoken conversation that is already going
  on. Switch it off under Voice and assistant. The first time the window opens this way, Edge
  asks once for permission to use the microphone.
- **The session**: after "Hey JARVIS" the conversation stays open, so no wake word is needed for the
  next thing. "Stop" ends what JARVIS is doing or saying, "go to sleep" makes it wait for its name,
  "end session" leaves voice chat; "JARVIS, stop" is caught by the tray helper at any moment, even
  while JARVIS itself is talking. An idle session sleeps after 15 minutes (a setting). Questions that
  need a yes ("Shall I send this email?") are answered out loud.
- **The PC's own sound is ignored** (`jcc/pcsound.py`): Windows reports how loud everything it plays
  is at each moment. Sound at the microphone that rises and falls in step with that is a video, a
  film or music, not a person, and is dropped before anything is transcribed. While something is
  playing through speakers the microphone can hear, only what is said to JARVIS by name counts, and
  a spoken "yes" needs the name too, so a film cannot give instructions or approve anything.
- **One working window** (`jcc/voice_tools.py`): while it works for you, JARVIS types and clicks only
  in the window it opened, switched to or clicked in, never in "whatever is in front" and never in
  its own window. If that window cannot be brought to the front, nothing is typed at all.
- **Playing things**: `find_videos` reads YouTube's results (no key needed) so JARVIS can pick a video
  and open it; "play ... on YouTube" starts the first one directly. `read_web_page` lists a page's
  links so one of them can be opened.
- **Microphone and speakers**: Windows' default devices unless you choose others under Voice and
  assistant (each has a test button). The choice is kept by the device's name and applies
  everywhere: voice chat, dictation, the wake word (JARVIS records the chosen microphone and
  hands the sound to the recogniser through a private pipe) and JARVIS's voice and sounds. The
  natural voices built into Edge can only play on the Windows default, so on chosen speakers the
  built-in voice is Windows' own, made on this PC (`speech.LocalVoice`); an ElevenLabs voice plays
  on any speakers. If a chosen device is unplugged, the Windows default carries on until it is back.
- **Dictation**: the microphone button writes what you say into the message box.
- **Recordings**: attach an audio or video file (up to 25 MB) and it is written out as text.
- **Acting on the PC** (`jcc/voice_tools.py`): open apps, files and websites; switch windows;
  press buttons and fill boxes by name through Windows' accessibility layer (`jcc/uia.py`), or
  by looking at the screen; type and press keys; run PowerShell; find, read and write files;
  timers and reminders; volume and brightness; weather; read a web page; notes and things to
  remember; create projects and hand building to the coding agents; send email; make pictures.
- **Email**: connect your address with an app password (Voice and assistant, Email) and
  messages are sent directly after your yes. Otherwise a draft is opened in your mail app.
- **Assistants**: give JARVIS other roles with their own name, instructions, model and voice.
- **Memory**: "remember that..." is kept in the note `System/JARVIS Memory`, which you can edit.
- **Deep research** (chat bar options): several web searches and a report with sources.
- **Pictures**: made with the free Pollinations service; the description is sent to it.
- **Your own connectors**: put MCP servers in `%LOCALAPPDATA%\JarvisCommand\connectors.json`
  (`{"mcpServers": {...}}`). Their tools go through the same approval rules.
- **Your paper-trading app** (`/trading`, `jcc/trading.py`): if you run a paper-trading app with
  a JARVIS status feed on a server of your own (the open-source one is at
  https://github.com/Vihan-2008/trading-ai: paper money only, and its README says how to run it
  on your own computer or server), connect it with its dashboard address and a
  read-only token made on that server (`trading-ai jarvis-token new`), never the dashboard's
  password. The token is kept in the system's key store. JARVIS then shows, and says when you
  ask ("how is my trading doing?"), the result overall and per market (crypto, US stocks,
  India), whether its services are running, whether the kill switch or a pause is on, and the
  latest decisions. It is read only by how it is built: one GET to one fixed address, over
  https, never following a redirect, and only numbers, ids and codes are passed on to the
  assistant. **Open dashboard** opens the app's own dashboard in the browser panel, where you
  sign in yourself to change anything. **Set goal** keeps a monthly goal on this PC (what the
  trading should pay for, with prices) and shows how the month is going against it; the goal
  never changes how the app trades, and paper money pays for nothing. When the server shares its
  real-money status, the panel's **Real money** section shows the same **Set up** checklist as the
  trading dashboard's Real money page (install, start, choose what to copy, a sell code per
  portfolio), ticking each step off by itself. The commands to type on the trading server are on
  the dashboard's page, not in JARVIS: JARVIS never holds or runs them.
- **Phone app** (`/phone`, `jcc/phone.py`): chat with JARVIS from your phone, from anywhere, on
  mobile data too. It runs in two free accounts of your own, never the JARVIS project's: a relay in
  your own Supabase project, where messages stay for up to 7 days, and the phone page on your own
  Cloudflare account. Type `/phone`, paste a Supabase access token and a Cloudflare API token made
  from the "Edit Cloudflare Workers" template, and JARVIS sets up both; a token that can do more
  than that is flagged before it is kept. Then add a phone: open the page on it, add it to the home
  screen, type the pairing code, and say yes on the computer. Each message is signed with a key
  that never leaves that phone, and the computer checks the signature before acting. Phone
  messages run in one careful "Phone" chat that asks before anything is done, never reads private
  notes or other chats, and never looks at the screen, clicks, types or uses the clipboard;
  commands, coding agents, spending and deleting are approved only at the computer. Optional
  laptop-off answers: switch on one of your own AI keys and a smaller assistant answers while the
  computer is off (that service then reads those messages). Notifications only say that there is
  something new. **Remove everything** deletes what the relay holds, the page and every pairing.
- **Light mode**: fewer particles, a frame cap, one AI session and no spare. It switches on by
  itself on PCs with about 8 GB of memory or no graphics card.

Screens the assistant looks at are sent to Anthropic through your Claude subscription, like any
other message. Speech goes to Groq (or OpenAI) to be transcribed and replies go to ElevenLabs to
be spoken, when those are in use. The older step-by-step control panel (Gemini) remains under the
expert tools.

### What the assistant may do

Every action passes one check in the service before it runs (`jcc/policy.py`); the AI cannot
answer it for you.

- **Never**: typing passwords, card numbers or keys; reading saved passwords, browser profiles
  or JARVIS's own settings; acting on banking, payment, password-manager or Windows-security
  windows; commands that wipe disks, the user folder or Windows security.
- **Only after your yes** (in the window or by voice): sending, deleting, installing, shutting
  down, replacing a file, pressing buttons such as Send, Pay, Delete or Agree, typing into a
  command window. "Ask me before anything risky" can be switched off; the rest cannot.
- **Careful mode**: web pages, files, the screen and the clipboard can contain text written to
  trick an AI. Once a chat has read any of these, JARVIS asks before changing anything or
  sending anything out, for the rest of that chat, whatever the settings. A new chat starts clean.
- Things the app does for the assistant (email, timers, memory, coding jobs) are carried out
  from a one-time permit holding exactly what was approved.
- Stop, Esc or Ctrl+Alt+Backspace halts everything at once.

### Side panel

- **Files**: browse a project as a tree, create a file, edit and save it (Ctrl+S), preview a web
  page, or add a file to your message. Saving refuses hidden, credential and private files, and
  any file whose contents were shown masked. Asking in the chat with Build also creates and edits
  files, in a separate branch copy that is checked before it is merged.
- **Terminal**: a real PowerShell console (Windows pseudo-console plus the bundled xterm.js,
  MIT licence, `jcc/static/vendor`). Interactive and full-screen programs work.
- **Browser**: a real browser. A hidden Edge (or Chrome) with its own profile loads the page and
  its live picture is shown in the panel, so sites cannot refuse to be embedded. Cookies and
  sign-ins persist. JARVIS offers to save a sign-in when you submit one; saved sign-ins are kept
  in Windows Credential Manager and filled only when you press Fill sign-in. While the panel is
  open, the page you are on is sent with your next message; the chip in the chat bar shows this
  and its ✕ leaves the page out. Sign-in, banking and payment pages are never sent automatically.
  It has tabs, plays sound, saves downloads to DownloadsJARVIS, lets pages ask you for a file,
  and goes full screen for videos (or with the full-screen button).
- **Preview**: code or a web page from a reply, run in a sealed frame.
- **Computer**: optional and off by default. When switched on, JARVIS can click and type to carry
  out one task you give it. By default each step waits for your OK. It refuses tasks and windows
  that involve sign-ins, payments, banking or trading, never types passwords, stops after 30
  steps or 10 minutes, and stops at once with the Stop button or Ctrl+Alt+Backspace. A picture
  of your screen is sent to the free Gemini model for each step.

### Desktop helper

`jcc.tray` adds a tray icon (click to open JARVIS) and shortcuts that work from anywhere:

| Shortcut | What it does |
|---|---|
| Ctrl+Alt+J | Open JARVIS |
| Ctrl+Alt+Space | Start talking to JARVIS (the window does not need to be in front) |
| Ctrl+Alt+D | Dictate: speak, and the words are typed where your cursor is. Press again, or pause, to finish |
| Ctrl+Alt+Backspace | Emergency stop for anything JARVIS is doing on the PC |

Switch the icon or the shortcuts off under `[desktop]` in `config/local.toml`.

### Updating the installed app

`python scripts/deploy.py` copies this commit to the installed app: it saves the installed copy
to a zip first, refuses while coding jobs run, restarts JARVIS, checks the new version answers
and puts the saved copy back if it does not. `--check` only shows what would change and
`--rollback` restores the last saved copy.

### How the app protects itself

- The service listens on this computer only, refuses other host names (DNS rebinding) and needs a
  per-launch token on every request. The window page, which carries that token, is only given to
  programs of the same Windows account.
- Scripts run only from the app's own files or with a per-load code; previews of generated
  pages run in a sealed page of their own.
- The built-in browser is driven over a private pipe, so it opens no network port. Saved
  sign-ins are kept in Windows Credential Manager and offered only on protected (https) pages.
- Keys live only in environment variables or Windows Credential Manager. They are never written
  to the vault, receipts, logs or chats, and are masked if they appear in any text.

## Included

- Clean chat-first interface, project creation, project-linked chats and imported conversations.
- Python, static website and Node.js starters with Git and checks. Node.js must already be installed.
- Automatic coding-agent selection between Claude Code and GPT / Codex. Gemini CLI is excluded.
- Model selection by task complexity, live allowance checks and a five-percent reserve.
- Model-specific fallback, provider-wide fallback, preserved edits, checkpoints and queued retries.
- Bounded attempts to repair failing checks, with branch retention if no attempt passes.
- Restart recovery for interrupted jobs. Jobs on the same project run serially.
- Obsidian Markdown as durable chat, project-memory, history and job-result storage.
- Import of Claude / ChatGPT JSON or ZIP exports. Full exported records are retained as reference.
- Optional local browser extension to capture conversations opened on the two websites.

## Default coding choices

| Task | First choice | Fallback provider |
|---|---|---|
| Small | Codex / GPT-6 Luna | Claude Haiku |
| Normal | Codex / GPT-6.1 Sol | Claude Sonnet |
| Complex | Claude Opus | Codex / GPT-6 Astra |

Fresh provider-reported allowances can change this order. A model-specific context or access limit
tries another configured model; an account-wide limit skips that provider. CLI errors and failing
checks never count as a successful artifact just because a process returned zero.

## Memory and project behavior

Chats are under `Conversations/`. Project requirements live in `Projects/<key>/Memory.md` and
completed job notes in `Projects/<key>/Jobs/`. The app retrieves bounded recent chat history and
project memory; it does not send your whole archive to every model. Explicit wikilinks attach
other non-private notes. Content in imported histories and checkpoints is untrusted reference.

New projects live under `%LOCALAPPDATA%\JarvisCommand\projects`. Their registry is
`%LOCALAPPDATA%\JarvisCommand\projects.json`. Existing configured projects remain supported.
Coding happens in separate branch copies under the jobs folder. Local merge requires passing
checks, an unchanged clean base branch, and no protected-file changes. Nothing is pushed or deployed.
Tests and checks execute project code; branch copies are not a complete security boundary.

Claude's normal tool permission rules and Codex workspace-write are retained. Codex does not
isolate all file reads. Environment credentials and parent agent-session tool connections are
removed from coding jobs. No bypass-permission flags are used. Agent skill/plugin installation
is forbidden inside unattended job prompts.

## Usage display

Both saved account logins are reused. Read-only CLI control calls fetch allowances every five
minutes, without running a model prompt. The UI shows remaining percentage, reset times and last
reading time. Codex readings cover Codex allowance on ChatGPT, not every ChatGPT web-chat model.
These services do not provide an exact subscription-wide raw-token balance. Failed reads remain
explicitly unavailable or stale. Provider sign-ins may eventually expire or be revoked.

[Codex account-limit protocol](https://learn.chatgpt.com/docs/app-server),
[Claude usage fields](https://code.claude.com/docs/en/statusline).
The Claude control-call usage interface is version-dependent; it was verified locally during setup.

## Website history sync — one-time setup

JARVIS chats save immediately with no extra setup. For chats opened on ChatGPT or Claude websites,
open **Browser sync setup** in Settings → Memory & sync and follow `browser-sync/README.md`. Load the local
extension and pair it once with **Copy browser pairing code**. The pairing persists across restarts.
The extension is unpacked and not store-reviewed. It reads visible messages on those two sites,
stores a bounded offline queue and sends only to the local JARVIS service. It does not read cookies
or passwords. It is not automatically installed or silently granted access.

It captures saved conversations while open in that browser. It does not crawl all account history,
cover other devices, or reconstruct hidden messages and attachments. Import full account exports
for historical coverage. The app's file picker accepts JSON/ZIP; the watched import folder is
`%LOCALAPPDATA%\JarvisCommand\imports`. Download manifests are not conversation data.

## Startup and installation

To install JARVIS on Windows or a Mac, see [docs/INSTALL.md](INSTALL.md). The installers set up
the notes vault with `python -m jcc.firstrun`, which you can also run yourself from source.

Running from source on Windows, `scripts/install-desktop.ps1` creates Desktop and Start menu
shortcuts for the folder it is in, and `scripts/install-autostart.ps1` adds one Startup shortcut
that launches the background service hidden, without an app window. Remove that shortcut from the
Windows Startup folder to disable automatic launch. Existing sign-ins are left untouched.
The older `Open JARVIS.cmd` remains compatible but is no longer needed for normal use.

Read the in-vault `System/JARVIS Guide.md` for the user guide.

## Verification

`python -m unittest discover -s tests -t .`

The suite uses fake agents and disposable Git projects to test routing, persistence, permissions,
project creation, imports, quota-based selection, model/provider handoff, checks and merge gates.
Live account and file-creation checks are separate. A passing fake-agent suite alone does not
prove that every provider/model is available or that real subscription exhaustion was exercised.
