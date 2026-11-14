#!/usr/bin/env bash
# Installs JARVIS for the current Mac user. No administrator password is needed.
#
#   bash install.sh [--install-dir DIR] [--vault DIR] [--bundle-dir DIR] [--no-app]
#                   [--install-obsidian | --no-obsidian] [--wake-word | --no-wake-word]
#                   [--quiet] [--source DIR] [--python PATH]
#
# What it does, in order:
#   1. Finds python3, version 3.11 or newer. If there is none it says how to get one and stops.
#   2. Copies the app's files into --install-dir (default ~/Applications/JARVIS). Run again over an existing install
#      it upgrades it: config/local.toml and every other file the installer did not put there are kept.
#   3. Writes ".python" in the install folder: one line, the full path of the python3 it found.
#   4. Optionally sets up "Hey JARVIS": a Python environment of JARVIS's own inside the install folder with the two
#      packages the wake word needs (numpy, onnxruntime), and the wake word's small model, fetched and checked.
#   5. Installs the helper that tells the Mac's own sound from your voice: built here when Apple's command line
#      tools are installed, otherwise the ready-built one from the download.
#   6. Runs "python3 -m jcc.firstrun" to set up the notes vault (an Obsidian vault) and remember where it is.
#   7. Makes ~/Applications/JARVIS.app (or in --bundle-dir), a plain app that starts "python3 -m jcc.desktop".
#   8. Optionally installs Obsidian (Homebrew, or opens its download page).
#   9. Writes uninstall.sh into the install folder.
#
# This script is new. It is run on a real Mac at GitHub for every change (into a temporary folder, with --quiet);
# nobody has yet run it by double-clicking in Finder. Bash 3.2 (the one macOS ships) is enough.
set -euo pipefail

INSTALL_DIR="$HOME/Applications/JARVIS"
BUNDLE_DIR="$HOME/Applications"
VAULT=""
MAKE_APP=1
OBSIDIAN="ask"
WAKE="ask"
QUIET=0
SOURCE=""
PYTHON=""

say() { printf '%s\n' "$*"; }
fail() { printf 'JARVIS setup stopped: %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --install-dir) INSTALL_DIR="${2:?--install-dir needs a folder}"; shift 2 ;;
    --vault) VAULT="${2:?--vault needs a folder}"; shift 2 ;;
    --bundle-dir) BUNDLE_DIR="${2:?--bundle-dir needs a folder}"; shift 2 ;;
    --no-app) MAKE_APP=0; shift ;;
    --install-obsidian) OBSIDIAN="yes"; shift ;;
    --no-obsidian) OBSIDIAN="no"; shift ;;
    --wake-word) WAKE="yes"; shift ;;
    --no-wake-word) WAKE="no"; shift ;;
    --quiet) QUIET=1; shift ;;
    --source) SOURCE="${2:?--source needs a folder}"; shift 2 ;;
    --python) PYTHON="${2:?--python needs a path}"; shift 2 ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) fail "unknown option: $1 (try --help)" ;;
  esac
done

ask_yes() {   # ask_yes "Question" default(y|n)
  if [ "$QUIET" = 1 ]; then [ "$2" = y ]; return; fi
  local hint="[y/N]"; [ "$2" = y ] && hint="[Y/n]"
  local answer=""
  read -r -p "$1 $hint " answer || true
  [ -z "$answer" ] && answer="$2"
  case "$answer" in [Yy]*) return 0 ;; *) return 1 ;; esac
}

# --------------------------------------------------------------------------------------------------------- source
here="$(cd "$(dirname "$0")" && pwd)"
if [ -z "$SOURCE" ]; then
  # The app's files sit beside this script in the downloaded package. Run from a copy of the repository, the
  # script is in installer/mac and the app is two folders up.
  for candidate in "$here" "$(cd "$here/../.." && pwd)"; do
    if [ -f "$candidate/jcc/__init__.py" ]; then SOURCE="$candidate"; break; fi
  done
fi
[ -n "$SOURCE" ] && [ -f "$SOURCE/jcc/__init__.py" ] || fail "could not find the JARVIS app files (a \"jcc\" folder). Use --source to say where they are."
SOURCE="$(cd "$SOURCE" && pwd)"

# --------------------------------------------------------------------------------------------------------- Python
good_python() {   # prints the interpreter's full path when it is Python 3.11 or newer
  "$1" -c 'import sys; assert sys.version_info >= (3, 11); print(sys.executable)' 2>/dev/null
}
find_python() {
  if [ -n "$PYTHON" ]; then good_python "$PYTHON"; return; fi
  local candidate
  for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 \
      /Library/Frameworks/Python.framework/Versions/Current/bin/python3 "$(command -v python3 || true)"; do
    [ -n "$candidate" ] && [ -x "$candidate" ] || continue
    # /usr/bin/python3 is a placeholder until Apple's command line tools are installed, and calling it then pops up
    # an installer window. Use it only when those tools are there.
    if [ "$candidate" = /usr/bin/python3 ] && ! xcode-select -p >/dev/null 2>&1; then continue; fi
    if good_python "$candidate"; then return 0; fi
  done
  return 1
}

say "Installing JARVIS for this Mac user (no administrator password needed)."
if ! PY="$(find_python)" || [ -z "$PY" ]; then
  say "JARVIS needs Python 3.11 or newer, and none was found on this Mac."
  say "Get it from https://www.python.org/downloads/macos/ or, with Homebrew, run: brew install python"
  say "Then run this installer again."
  exit 1
fi
say "Using Python: $PY"

# ---------------------------------------------------------------------------------------------------------- files
mkdir -p "$INSTALL_DIR"
INSTALL_DIR="$(cd "$INSTALL_DIR" && pwd)"
upgrade=0
[ -f "$INSTALL_DIR/jcc/__init__.py" ] && upgrade=1
if [ "$upgrade" = 0 ] && [ -n "$(ls -A "$INSTALL_DIR")" ]; then
  fail "the folder $INSTALL_DIR already has other files in it and is not a JARVIS install. Choose an empty folder with --install-dir."
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
# Files that are never copied: the person's own settings, build and test material, the owner's deployment tool.
( cd "$SOURCE" && find . -type f \
    ! -path './.git/*' ! -path './.github/*' ! -path './.claude/*' ! -path './tests/*' ! -path './installer/*' \
    ! -path './website/*' ! -path './dist/*' ! -path '*/__pycache__/*' ! -name '*.pyc' ! -name '.DS_Store' \
    ! -path './LEDGER.md' ! -path './scripts/deploy.py' ! -path './config/local.toml' ! -path './.python' \
    ! -path './.jarvis-files' ! -path './.app-bundle' ! -path './install.sh' ! -path './uninstall.sh' \
    ! -path './Install JARVIS.command' ! -path './sound_level.swift' ! -path './.venv/*' | sed 's|^\./||' | LC_ALL=C sort ) > "$work/files"

if [ "$SOURCE" != "$INSTALL_DIR" ]; then
  # A plain copy loop: newer macOS versions ship a different rsync, and cp behaves the same everywhere.
  while IFS= read -r name; do
    mkdir -p "$INSTALL_DIR/$(dirname "$name")"
    cp -p "$SOURCE/$name" "$INSTALL_DIR/$name"
  done < "$work/files"
  # A file an earlier version shipped and this one does not would otherwise linger and could still be imported.
  # Only files named in the earlier list are removed: anything the person added is never touched.
  if [ -f "$INSTALL_DIR/.jarvis-files" ]; then
    LC_ALL=C sort "$INSTALL_DIR/.jarvis-files" > "$work/old"
    LC_ALL=C comm -23 "$work/old" "$work/files" | while IFS= read -r stale; do
      case "$stale" in ""|/*|*..*) continue ;; esac
      [ -f "$INSTALL_DIR/$stale" ] && rm -f "$INSTALL_DIR/$stale"
    done
  fi
  cp "$work/files" "$INSTALL_DIR/.jarvis-files"
  uninstaller=""
  for candidate in "$here/uninstall.sh" "$SOURCE/installer/mac/uninstall.sh"; do
    if [ -f "$candidate" ]; then uninstaller="$candidate"; break; fi
  done
  [ -n "$uninstaller" ] || fail "uninstall.sh is missing from the installer package."
  cp "$uninstaller" "$INSTALL_DIR/uninstall.sh"
  chmod 755 "$INSTALL_DIR/uninstall.sh"
fi
if [ "$upgrade" = 1 ]; then say "Upgraded the app in $INSTALL_DIR (your settings and your own files there were kept)."
else say "Copied the app to $INSTALL_DIR."; fi
printf '%s\n' "$PY" > "$INSTALL_DIR/.python"

# ------------------------------------------------------------------------------------------- "Hey JARVIS" (optional)
# The wake word is heard by a small model that runs on this Mac. It needs two Python packages (numpy, onnxruntime) and
# three model files (about 4 MB), fetched from where their makers publish them and checked before they are kept. The
# packages go into a Python environment of JARVIS's own inside the install folder, so nothing else on the Mac changes.
venv="$INSTALL_DIR/.venv"
has_wake() { [ -x "$venv/bin/python" ] && "$venv/bin/python" -c 'import numpy, onnxruntime' >/dev/null 2>&1; }
want_wake=0
if has_wake; then want_wake=1                     # set up by an earlier install: kept, and brought up to date below
elif [ "$WAKE" = yes ]; then want_wake=1
elif [ "$WAKE" = ask ] && [ "$QUIET" = 0 ]; then
  say ""
  say 'JARVIS can listen for "Hey JARVIS" with a small model that runs on this Mac. Setting it up downloads two Python'
  say "packages (about 60 MB) and the model (4 MB; its makers allow non-commercial use)."
  ask_yes 'Set up "Hey JARVIS"?' y && want_wake=1
fi
if [ "$want_wake" = 1 ]; then
  if { has_wake || "$PY" -m venv "$venv" >/dev/null 2>&1; } && \
     "$venv/bin/python" -m pip install --quiet --disable-pip-version-check numpy onnxruntime; then
    PY="$venv/bin/python"
    printf '%s\n' "$PY" > "$INSTALL_DIR/.python"
    if ( cd "$INSTALL_DIR" && "$PY" scripts/get_wake_word.py ); then
      say '"Hey JARVIS" is set up. Switch it on in JARVIS under Settings, Voice.'
    else
      say 'The wake word model could not be fetched, so "Hey JARVIS" stays off. To try again later, run in the install folder:'
      say "  \"$PY\" scripts/get_wake_word.py"
    fi
  else
    say 'The Python packages for the wake word could not be installed, so "Hey JARVIS" stays off. Everything else works.'
    has_wake || rm -rf "$venv"
  fi
fi

# -------------------------------------------------------------------------------- telling the Mac's own sound apart
# A small program that reports how loud the Mac's own sound is (and nothing else), so a film is not taken for you.
# Built here when Apple's command line tools are installed; otherwise the ready-built one from the download is used.
helper="$INSTALL_DIR/bin/jarvis-sound-level"
swift_source=""
for candidate in "$here/sound_level.swift" "$SOURCE/installer/mac/sound_level.swift"; do
  if [ -f "$candidate" ]; then swift_source="$candidate"; break; fi
done
if [ -n "$swift_source" ] && xcode-select -p >/dev/null 2>&1 && xcrun -f swiftc >/dev/null 2>&1; then
  mkdir -p "$INSTALL_DIR/bin"
  if xcrun swiftc -O -o "$helper.new" "$swift_source" >/dev/null 2>&1; then
    mv -f "$helper.new" "$helper"
  else
    rm -f "$helper.new"
  fi
fi
if [ -f "$helper" ]; then
  chmod 755 "$helper"
  # A program that arrived in a download is marked by macOS and refused when another program starts it. This one
  # is part of what you are installing, so the mark is taken off this one file.
  xattr -d com.apple.quarantine "$helper" 2>/dev/null || true
  say "Installed the helper that tells the Mac's own sound from your voice."
else
  say "The helper that tells the Mac's own sound from your voice was not installed (it needs Apple's command line tools). JARVIS works without it."
fi

# ---------------------------------------------------------------------------------------------------------- vault
firstrun=(-m jcc.firstrun --app-dir "$INSTALL_DIR" --yes)
if [ -n "$VAULT" ]; then
  firstrun+=(--vault "$VAULT")
elif [ "$QUIET" = 0 ] && ! grep -Eq '^[[:space:]]*vault[[:space:]]*=' "$INSTALL_DIR/config/local.toml" 2>/dev/null; then
  offered="$HOME/Documents/JARVIS Vault"
  say ""
  say "JARVIS keeps its memory as plain notes in a folder you own (an Obsidian vault)."
  answer=""
  read -r -p "Where should your notes be kept? Press Return for $offered: " answer || true
  firstrun+=(--vault "${answer:-$offered}")
fi
[ "$QUIET" = 1 ] && firstrun+=(--no-open)
( cd "$INSTALL_DIR" && "$PY" "${firstrun[@]}" ) || fail "setting up the notes vault did not finish (see the message above)."

# -------------------------------------------------------------------------------------------------------- the app
if [ "$MAKE_APP" = 1 ]; then
  bundle="$BUNDLE_DIR/JARVIS.app"
  version="$(head -n 1 "$INSTALL_DIR/VERSION" 2>/dev/null || echo 0.0.0)"
  mkdir -p "$bundle/Contents/MacOS" "$bundle/Contents/Resources"
  cat > "$bundle/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>JARVIS</string>
  <key>CFBundleDisplayName</key><string>JARVIS</string>
  <key>CFBundleIdentifier</key><string>local.jarvis.desktop</string>
  <key>CFBundleExecutable</key><string>JARVIS</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>${version}</string>
  <key>CFBundleVersion</key><string>${version}</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSMicrophoneUsageDescription</key><string>JARVIS listens when you talk to it, and for "Hey JARVIS" when you have switched that on.</string>
  <key>NSAppleEventsUsageDescription</key><string>JARVIS opens and works in other apps when you ask it to.</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST
  # The launcher names the install folder; printf %q quotes it so any folder name is safe in the script.
  {
    printf '#!/bin/bash\n'
    printf '# Starts JARVIS from its install folder. Written by the JARVIS installer.\n'
    printf 'cd %q || exit 1\n' "$INSTALL_DIR"
    printf 'PY="$(head -n 1 .python 2>/dev/null || true)"\n'
    printf '[ -x "$PY" ] || PY="$(command -v python3)"\n'
    printf 'exec "$PY" -m jcc.desktop "$@"\n'
  } > "$bundle/Contents/MacOS/JARVIS"
  chmod 755 "$bundle/Contents/MacOS/JARVIS"
  printf '%s\n' "$bundle" > "$INSTALL_DIR/.app-bundle"
  say "Made $bundle"
fi

# ------------------------------------------------------------------------------------------------------- Obsidian
want=0
if [ "$OBSIDIAN" = yes ]; then want=1
elif [ "$OBSIDIAN" = ask ] && [ "$QUIET" = 0 ] && [ ! -d /Applications/Obsidian.app ]; then
  ask_yes "Install Obsidian (a free app to read and edit your notes)?" y && want=1
fi
if [ "$want" = 1 ]; then
  if command -v brew >/dev/null 2>&1; then
    brew install --cask obsidian || say "Homebrew could not install Obsidian; get it from https://obsidian.md/download"
  else
    say "Homebrew is not installed, so the Obsidian download page is opening instead."
    open "https://obsidian.md/download" || true
  fi
fi

say ""
say "JARVIS is installed."
say "  App:          $INSTALL_DIR"
[ "$MAKE_APP" = 1 ] && say "  Open it:      $BUNDLE_DIR/JARVIS.app"
say "  Uninstaller:  $INSTALL_DIR/uninstall.sh"
say "  Or run:       cd \"$INSTALL_DIR\" && \"$PY\" -m jcc.desktop"
say ""
say "The first time JARVIS presses a button in another app, looks at the screen or listens, macOS asks you to allow it."
say "You can also switch these on beforehand: System Settings, Privacy & Security, then Accessibility, Screen & System"
say "Audio Recording, and Microphone. JARVIS's Connections page shows which are allowed."
