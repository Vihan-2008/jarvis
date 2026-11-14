# JARVIS

An assistant that lives on your own computer. Talk to it or type; it answers, does things on your PC, and has coding
agents build and fix software in a safe copy of your project. It asks before anything is sent, deleted or paid for.

It is a local app: a small service on `127.0.0.1` and a window. There is no JARVIS account and no JARVIS server.
The AI comes from the accounts you already have.

**Website:** https://vihan-2008.github.io/jarvis/ · **Download:** [the latest release](https://github.com/Vihan-2008/jarvis/releases/latest)

## What it does

- **Talk to it.** "Hey JARVIS", then say what you want. It can be interrupted, and it tells its own voice from yours.
- **It does things on your PC.** Opens apps and pages, finds and writes files, runs commands, fills in forms.
  Sending, deleting and paying always wait for your yes; you choose how much else it asks about.
- **Coding with agents.** A request becomes a job for Claude Code or Codex in its own copy of your project
  (a git worktree). The project's checks run, you look at the change, and only then is it merged. A planner and a
  builder can work as a pair, and one list shows what every agent is doing.
- **Security check.** Finds the usual holes in a project, has the ones you tick fixed in a copy, shows you the
  change, applies it, and can undo it.
- **Routines.** Things done again and again at the times you choose, each run sent as if you had typed it.
- **Artifacts.** Pages, pictures, diagrams, documents, slides, sheets, charts and whiteboards open beside the chat,
  with every version kept.
- **The Court of JARVIS.** One idea, five stages (grand jury, prosecution, analysts with web research, tribunal,
  executioner), a verdict worked out in code.
- **Your notes are its memory.** It keeps what it learns in a folder of Markdown notes (an Obsidian vault): your
  second brain, readable and editable by you.

Every feature is described in [the guide](docs/GUIDE.md). How JARVIS compares with T3 Code and Cursor, feature by
feature, is in [docs/PARITY.md](docs/PARITY.md). From version 0.1.4 on, JARVIS updates itself: it installs only
releases signed by its maker, and goes back to the version you had if a new one does not start (see
[docs/INSTALL.md](docs/INSTALL.md#updates)).

## Install

| | |
|---|---|
| **Windows** | Download `JARVIS-Setup.exe` from [Releases](https://github.com/Vihan-2008/jarvis/releases/latest) and run it. |
| **macOS** | Download `JARVIS.dmg` or `JARVIS-mac.zip` from [Releases](https://github.com/Vihan-2008/jarvis/releases/latest). |
| **From source** | `git clone https://github.com/Vihan-2008/jarvis`, then `python -m jcc.firstrun` and `python -m jcc.desktop`. |

The installer puts the app in your user folder (no administrator rights), sets up the notes vault, and can install
Obsidian if you want it. Details, and how to uninstall: [docs/INSTALL.md](docs/INSTALL.md).

The installers are not code-signed yet, so Windows SmartScreen and macOS Gatekeeper will warn before they run.

### What you need

- Python 3.11 or newer. The app uses only Python's standard library: there is nothing to `pip install`.
- A Chromium-family browser for the app's window (Edge, Chrome, Brave). Any browser works as a fallback.
- For coding: the [Claude Code](https://code.claude.com) and/or Codex command-line tools, signed in with your own
  subscription.
- Optional keys of your own, kept in your system's key store, never in a file: Groq (speech-to-text), ElevenLabs
  (the voice), Gemini and others (see Settings, Connections).

### Windows, macOS, Linux

Everything works on Windows, where the app was built and is used every day. On a Mac the app runs with the wake
word, an icon in the menu bar, shortcuts that work from any app, dictation into other apps, working in other apps'
windows, step-by-step control and telling the Mac's own sound from your voice; the built-in browser panel and the
small listening window are Windows-only for now. The Mac side is run by the automated tests and by a check on a real Mac at GitHub
(`scripts/mac_live_check.py`); it has been installed and opened on a real Mac, not yet used day to day. Linux has the core app (chat, coding agents,
artifacts, routines, security check). The table is in [docs/PLATFORMS.md](docs/PLATFORMS.md).

## How it keeps you safe

- It listens only on `127.0.0.1`, takes its port for itself alone, and answers only its own window (a per-launch
  token; other websites and other host names are refused).
- Keys live in the system key store (Windows Credential Manager, the macOS Keychain) or in environment variables.
  They are stripped from the environment of every coding job and are never written to notes, logs or chats.
- One set of rules decides every action the assistant takes (`jcc/policy.py`). An approval covers exactly the
  action and the details you were shown, once.
- Coding agents work in a copy of your project, never in your real folder, and nothing is merged before its checks
  pass. Deploying, pushing, servers and secrets are refused outright.
- What it reads from the web, e-mail and notes is treated as information, never as instructions. After reading
  outside content it asks more.
- Notes in a `Private` folder, or marked `private: true`, are never sent to a model.

Found a hole? See [SECURITY.md](SECURITY.md).

## Working on it

```
python -m unittest discover -s tests -t .     # about 930 tests, standard library only
node --test tests/*.test.js                   # the window's own tests
```

Comments and test names are plain sentences; see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE). Bundled third-party files keep their own licenses (`jcc/static/vendor/`).

JARVIS is an independent open-source project. It is not affiliated with, or endorsed by, any company; the name is
only the app's name.
