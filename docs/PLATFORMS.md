# JARVIS on Windows, macOS and Linux

macOS and Linux support is new. It was written without a Mac at hand. It is checked two ways: by the automated tests on Windows, macOS and Linux, and on a real Mac at GitHub by `scripts/mac_live_check.py`, which opens TextEdit, lists its controls, fills its text box, clicks and types in it, presses Command-A, ticks a box in its Settings by name, types what dictation heard into it, takes a picture of the screen and of a window, records the microphone, shows the menu-bar icon, presses each shortcut while another app is in front, chooses "Talk to JARVIS" from the menu-bar menu, plays "Hey Jarvis" in the Mac's own voices to the wake word model, and measures a tone the Mac plays. Its owner has installed version 0.1.3 on a real Mac and opens it from its icon; it has not yet been used day to day. Not checked there, because that machine cannot: a real voice at a real microphone, the screen brightness, a second screen, pages inside a browser, and macOS's own permission questions (that machine has them answered already).

On a Mac, macOS itself must allow three things, each asked once and each switched on by you under System Settings, Privacy & Security: **Accessibility** (pressing, typing and clicking in other apps), **Screen & System Audio Recording** (pictures of the screen, other apps' window titles, and measuring the Mac's own sound) and **Microphone**. They are given to the app JARVIS was started from: JARVIS.app, or Terminal if you started it there. JARVIS's Connections page shows which are allowed.

JARVIS was written on and for Windows, and Windows is where everything in it works. This page says, feature by feature, what a Mac and a Linux computer have. "Works, with less" says what is missing.

Start it on a Mac or on Linux from the folder JARVIS is in, with Python 3.12: `python3 -m jcc.desktop`.

| Feature | Windows | macOS | Linux |
|---|---|---|---|
| The app window | works (an Edge app window) | works, with less: an app window of Chrome, Edge, Brave or Chromium when one is installed; otherwise a tab of the default browser | works, with less: as on a Mac (Chrome, Chromium, Edge or Brave from the PATH) |
| Where the window opens (its size and place remembered) | works | works, with less: the size is remembered; the screens are not read, so it is not moved back onto a screen | works, with less: as on a Mac |
| "Could not start" message | works (a message box) | works (an alert) | works, with less: printed only |
| Background helpers (local history, cloud memory, maintenance) | works | works | works |
| Keys kept in the system's key store | works (Credential Manager) | works (the login Keychain) | works, with less: the Secret Service through `secret-tool` when it is installed; otherwise only the `JCC_<NAME>` environment variables |
| Chats, notes, memory, projects | works | works | works |
| Updates by themselves (signed releases, rolled back if the new version does not start) | works | works | not available: update from the source |
| Coding jobs (Claude Code, Codex) in a copy of the project | works | works | works |
| Pausing and cancelling a job (with everything it started) | works | works | works |
| Terminal panel (interactive) | works (PowerShell) | works (your own shell, zsh by default) | works (your own shell, bash by default) |
| One-command terminal | works (PowerShell) | works (your own shell) | works (your own shell) |
| Built-in browser panel | works | not available | not available |
| Tray icon and global shortcuts (Ctrl+Alt+J and the others) | works | works: an icon in the menu bar with the same menu, and the shortcuts with Control+Option: J opens JARVIS, T talks to it, D dictates, Delete stops everything. A small program shows them (the installer builds it, or uses the ready-built one from the download); it needs no permission and never sees a key you type | not available |
| Small listening window over other apps | works | not available | not available |
| "Hey JARVIS" while the app window is open (minimised too; nothing listens once it is closed) | works | works, with less: heard by the small on-device model only, which the installer sets up (numpy, onnxruntime and openWakeWord's "hey jarvis" model; from source: `pip install numpy onnxruntime`, then `python3 scripts/get_wake_word.py`). The words are "Hey Jarvis"; "JARVIS, stop" without "hey" and another name for the assistant need Windows' recogniser. The helper that listens starts when you log in (the installer asks; as on Windows) or when JARVIS is opened | not available |
| Dictation into other apps | works | works (Control+Option+D, or the menu-bar menu; needs the Microphone and Accessibility permissions and a Whisper key, as on Windows) | not available |
| Telling the computer's own sound from a voice in the room | works | works: a small helper measures what the Mac plays (macOS 13 or newer, the Screen Recording permission). The installer builds it when Apple's command line tools are installed and otherwise uses the ready-built one from the download | not available |
| Reminder shown when the window is closed | works (a message box) | works (a notification) | not available |
| Desktop alert when a job finishes | works | not available | not available |
| Assistant: open an app by name | works | works (`open -a`, apps in /Applications and ~/Applications) | not available |
| Assistant: open a file, a folder or a web page | works | works | works |
| Assistant: find files | works (the Windows search index) | works (Spotlight, then the usual folders) | works, with less: the usual folders in your home folder, four levels deep |
| Assistant: run a command | works (PowerShell) | works (zsh) | works (bash) |
| Assistant: read and write the clipboard | works | works | not available |
| Assistant: set the volume | works | works | not available |
| Assistant: media keys | works | works, with less: mute and volume only; play, pause, next and previous are not available | not available |
| Assistant: screen brightness | works (laptop screens) | works, with less: a Mac's own screen, through the service macOS's own settings use; not yet tried on a real Mac screen | not available |
| Assistant: lock the computer | works | works, with less: the display goes to sleep, which locks the Mac when it asks for the password on waking | works, with less: needs `loginctl` (systemd) |
| Assistant: play music | works (the Spotify app, or YouTube) | works, with less: YouTube in the browser only | works, with less: YouTube in the browser only |
| Assistant: play a film or series on a streaming site | works | not available | not available |
| Assistant: send an email | works | works, with less: through a connected account; otherwise the draft is opened and you press Send yourself | works, with less: as on a Mac |
| Assistant: working inside other apps' windows (list, focus and move windows; press buttons; type; keys; scroll; look at the screen) | works | works (the Accessibility interface and the Mac's own keys: Command is `cmd`, Option is `alt`). Logging out, locking and force-quitting are never pressed | not available |
| Computer use (the assistant steering the screen step by step) | works | works (Control+Option+Delete stops it from any app, as Ctrl+Alt+Backspace does on Windows) | not available |
| Screenshots | works | works | not available |
| The approval rules (what JARVIS asks you about first) | works | works (the same rules, with the Mac's and Linux's own risky commands and secret places added) | works (as on a Mac) |

Tools that are not available on a system are not offered to the assistant there at all; if one is asked for anyway, it answers with one plain sentence saying so.
