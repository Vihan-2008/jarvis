# Installing JARVIS

JARVIS runs on your own computer. It needs **Python 3.11 or newer** and nothing else: no extra Python packages. Your
notes are kept in an ordinary folder (an Obsidian vault) that you own.

The packages are on the project's GitHub **Releases** page:

| File | For |
|---|---|
| `JARVIS-Setup.exe` | Windows: double-click to install. |
| `JARVIS-windows.zip` | Windows, if you prefer a zip: unpack it and run `install.ps1`. |
| `JARVIS.dmg` or `JARVIS-mac.zip` | Mac: open it and double-click `Install JARVIS.command`. |

## The installers are not code-signed

The project does not pay for code-signing certificates, so your computer will warn you the first time:

- **Windows SmartScreen** says "Windows protected your PC". Click **More info**, then **Run anyway**.
- **macOS Gatekeeper** says the file "cannot be opened because it is from an unidentified developer". In Finder,
  **right-click** (or Control-click) `Install JARVIS.command`, choose **Open**, then **Open** again. On newer macOS
  versions you may instead have to go to **System Settings > Privacy & Security** and click **Open Anyway**.

If you would rather not, read the scripts first (they are plain text) or run JARVIS from source (below): nothing is
downloaded as a program, so there is nothing to warn about.

## Windows

1. Run `JARVIS-Setup.exe` (or unpack `JARVIS-windows.zip` and right-click `install.ps1` > **Run with PowerShell**).
2. Answer the questions: where to keep your notes (Enter accepts `Documents\JARVIS Vault`) and whether to install
   Obsidian.
3. Open **JARVIS** from the Desktop or the Start menu.

No administrator rights are needed. To run it without questions, or to choose places yourself:

```
powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1 -Quiet -Vault "D:\Notes\JARVIS"
```

Other options: `-InstallDir`, `-ShortcutDir`, `-NoShortcuts`, `-InstallObsidian` / `-NoObsidian`, `-Autostart`
(start JARVIS's background part when you sign in), `-Python` (a particular `python.exe`).

## Mac

1. Open `JARVIS.dmg` (or unpack `JARVIS-mac.zip`) and double-click **Install JARVIS.command** (see the Gatekeeper note
   above).
2. Answer the questions in the Terminal window that opens. One of them offers to set up "Hey JARVIS": two Python
   packages (numpy and onnxruntime, about 60 MB, kept in a Python environment of JARVIS's own inside the install
   folder) and the wake word's small model (4 MB, fetched from its makers and checked; they allow non-commercial use).
3. Open **JARVIS** from `Applications` in your home folder.
4. The first time JARVIS presses a button in another app, looks at the screen or listens, macOS asks you to allow it.
   You can switch these on beforehand under System Settings, Privacy & Security: **Accessibility**, **Screen & System
   Audio Recording** and **Microphone**. JARVIS's Connections page shows which are allowed.

Or, in Terminal: `bash install.sh --quiet --vault ~/Notes/JARVIS`. Other options: `--install-dir`, `--no-app`,
`--install-obsidian` / `--no-obsidian`, `--wake-word` / `--no-wake-word`, `--login` / `--no-login`.

The installer also asks whether JARVIS should start in the background when you log in (as it does on Windows), so
"Hey JARVIS", the menu-bar icon and the shortcuts work without opening it first. The uninstaller removes that again.
If your Python came from python.org and its "Install Certificates" step was never run, JARVIS uses the Mac's own list
of trusted certificates, so downloads and the online services work anyway.

The installer also puts in two small programs: one tells the Mac's own sound from your voice, the other is the icon
in the menu bar and the shortcuts that work from any app (Control+Option with J, T, D or Delete). Each is built on your
Mac when Apple's command line tools are installed; otherwise the ready-built one from the download is used.

**The Mac installer is new.** For every change it is run on a real Mac at GitHub twice: once quietly, and once from
the downloaded package through `Install JARVIS.command` with its questions answered, after which the app is opened (it
answers, and its menu-bar icon runs) and uninstalled. Not tried there: Finder's double-click and Gatekeeper's warning,
and macOS's own permission questions. If it
fails, please open an issue with what it printed, and meanwhile run JARVIS from source.

## What the installer does

- Finds Python 3.11 or newer. If there is none it tells you how to get it (on Windows it offers to install it with
  winget; on a Mac, see python.org or `brew install python`). It never downloads an installer by itself.
- Copies the app into its own folder (`%LOCALAPPDATA%\Programs\JARVIS` on Windows, `~/Applications/JARVIS` on a Mac).
- Sets up your notes vault: the folders and starter notes JARVIS uses, and a `Start here.md` that explains them. An
  existing folder is never emptied and an existing note is never overwritten.
- Saves where the vault is in the app's `config/local.toml`.
- Makes a **JARVIS** shortcut (Windows: Desktop and Start menu) or `JARVIS.app` (Mac).
- Offers to install Obsidian, the free app for reading and editing your notes.
- Leaves an uninstaller in the app's folder.

Running it again upgrades JARVIS in place. Your `config/local.toml` and any other file you put in the app folder are
kept.

## What it does not do

- It does not ask for administrator rights, change system settings or install anything without asking.
- It does not edit Obsidian's own settings. To open your notes in Obsidian, choose **Open folder as vault** and pick
  the vault folder (the installer prints its path).
- It does not ask for, or store, any keys or passwords. You add keys later in the app; they are kept in the system's
  own key store (Windows Credential Manager or the macOS Keychain), never in a file.

## Where things are kept

| What | Windows | Mac |
|---|---|---|
| The app | `%LOCALAPPDATA%\Programs\JARVIS` | `~/Applications/JARVIS` |
| Your settings | `config\local.toml` in the app folder | `config/local.toml` in the app folder |
| Your notes (vault) | `Documents\JARVIS Vault`, or where you chose | `~/Documents/JARVIS Vault`, or where you chose |
| The app's data (chats, sessions, settings) | `%LOCALAPPDATA%\JarvisCommand` | `~/Library/Application Support/JarvisCommand` |
| Keys | Windows Credential Manager | Keychain |

## Uninstalling

- Windows: `powershell -NoProfile -ExecutionPolicy Bypass -File "%LOCALAPPDATA%\Programs\JARVIS\uninstall.ps1"`
- Mac: `bash ~/Applications/JARVIS/uninstall.sh`

Close JARVIS first. The uninstaller removes the shortcuts (or `JARVIS.app`) and the app folder, including
`config/local.toml`. It **never** removes your notes vault or the app's data folder; it prints where they are, so you
can keep them or delete them yourself.

## Running from source

```
git clone <this repository>
cd <the clone>
python -m jcc.firstrun          # sets up your notes vault; add --vault PATH to choose where
python -m jcc.desktop           # opens JARVIS
```

(On a Mac or Linux, use `python3`.) On Windows, `scripts\install-desktop.ps1` adds Desktop and Start menu shortcuts
for the clone, and `scripts\install-autostart.ps1` starts JARVIS's background part at sign-in.

## Building the packages

```
python installer/windows/build.py     # dist/JARVIS-Setup.exe and dist/JARVIS-windows.zip (Setup.exe on Windows only)
python installer/mac/build.py         # dist/JARVIS-mac.zip (any system)
bash installer/mac/build_dmg.sh       # dist/JARVIS.dmg (macOS only)
python installer/windows/test_install.py   # builds, installs, upgrades and uninstalls in a temporary folder
```

The version comes from the `VERSION` file. Pushing a tag `v<VERSION>` makes the release workflow build all four
packages and attach them to that tag's GitHub release.

## Updates

From version 0.1.4 on, JARVIS keeps itself up to date (Settings, Updates):

- **Automatically** (the usual setting): once a day JARVIS asks GitHub, where its releases are published, which version
  is the newest. Nothing about you is sent. A newer version is fetched in the background and installed the next time
  JARVIS starts, or at once with **Install and restart**.
- **Tell me, and I choose when**: JARVIS says a version is out and installs it when you press Install.
- **Never look for updates.**

What makes it safe:

- Every release carries a list of its packages with their fingerprints, signed with a private key that never leaves its
  maker's computer. JARVIS has the matching public key built in, and installs a package only when the list's signature
  checks out and the download matches its fingerprint exactly. Someone who took over the GitHub account or the download
  could not make such a signature, so every copy of JARVIS would refuse what they put there.
- Installing runs the same installer you used, quietly, as an upgrade: your settings (`config/local.toml`), notes,
  chats, keys and choices (starting at sign-in, "Hey JARVIS") are kept, and files of your own in the app's folder are
  never touched.
- A copy of the app as it was is kept first (the last three are kept). If the installer fails, or the new version does
  not answer within two minutes, the copy is put back and the version you had starts again. That version is then not
  tried again by itself.
- No update is installed while a coding job is running.
- What happened is written to `update.log` in JARVIS's data folder, and Settings, Updates says it in a sentence.

Versions before 0.1.4 cannot update themselves: install 0.1.4 once over them (your settings are kept), and from then on
updates come by themselves. A copy of JARVIS run from its source code (a git checkout) is updated with git, and Linux
has no ready-made package, so neither is updated this way.

For the maker: after the release workflow has built a version's packages, `python scripts/sign_release.py vX.Y.Z` (on the
computer that holds the signing key) adds the signed list to the release. Until it has, copies of JARVIS show the
version but do not install it. Keep a copy of the signing key (`python scripts/sign_release.py --export-key`) somewhere
safe, such as a password manager: without it no further release can be signed, and every copy would need to be
installed again by hand with a new key.
