# JARVIS on Windows, macOS and Linux

macOS and Linux support is new. It was written without a Mac at hand and is checked by automated tests; it has not yet been used day to day on a real Mac.

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
| Coding jobs (Claude Code, Codex) in a copy of the project | works | works | works |
| Pausing and cancelling a job (with everything it started) | works | works | works |
| Terminal panel (interactive) | works (PowerShell) | works (your own shell, zsh by default) | works (your own shell, bash by default) |
| One-command terminal | works (PowerShell) | works (your own shell) | works (your own shell) |
| Built-in browser panel | works | not available | not available |
| Tray icon and global shortcuts (Ctrl+Alt+J and the others) | works | not available | not available |
| Small listening window over other apps | works | not available | not available |
| "Hey JARVIS" while the app window is closed | works | not available | not available |
| Dictation into other apps | works | not available | not available |
| Telling the computer's own sound from a voice in the room | works | not available | not available |
| Reminder shown when the window is closed | works (a message box) | works (a notification) | not available |
| Desktop alert when a job finishes | works | not available | not available |
| Assistant: open an app by name | works | works (`open -a`, apps in /Applications and ~/Applications) | not available |
| Assistant: open a file, a folder or a web page | works | works | works |
| Assistant: find files | works (the Windows search index) | works (Spotlight, then the usual folders) | works, with less: the usual folders in your home folder, four levels deep |
| Assistant: run a command | works (PowerShell) | works (zsh) | works (bash) |
| Assistant: read and write the clipboard | works | works | not available |
| Assistant: set the volume | works | works | not available |
| Assistant: media keys | works | works, with less: mute and volume only; play, pause, next and previous are not available | not available |
| Assistant: screen brightness | works (laptop screens) | not available | not available |
| Assistant: lock the computer | works | works, with less: the display goes to sleep, which locks the Mac when it asks for the password on waking | works, with less: needs `loginctl` (systemd) |
| Assistant: play music | works (the Spotify app, or YouTube) | works, with less: YouTube in the browser only | works, with less: YouTube in the browser only |
| Assistant: play a film or series on a streaming site | works | not available | not available |
| Assistant: send an email | works | works, with less: through a connected account; otherwise the draft is opened and you press Send yourself | works, with less: as on a Mac |
| Assistant: working inside other apps' windows (list, focus and move windows; press buttons; type; keys; scroll; look at the screen) | works | not available | not available |
| Computer use (the assistant steering the screen step by step) | works | not available | not available |
| Screenshots | works | not available | not available |
| The approval rules (what JARVIS asks you about first) | works | works (the same rules, with the Mac's and Linux's own risky commands and secret places added) | works (as on a Mac) |

Tools that are not available on a system are not offered to the assistant there at all; if one is asked for anyway, it answers with one plain sentence saying so.
