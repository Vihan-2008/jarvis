#!/usr/bin/env bash
# Removes JARVIS: the JARVIS.app the installer made and the install folder.
#
#   bash uninstall.sh [--quiet] [--install-dir DIR] [--delete-data] [--delete-notes]
#
# It stops JARVIS if it is running, and removes the start at login if the installer set one up. Your notes vault and
# the app's data folder (settings, chats, sessions) are kept unless --delete-notes / --delete-data say otherwise (JARVIS's
# Settings > Advanced > Uninstall JARVIS asks); what is deleted goes to the Trash, so it can be put back. It is run on a
# real Mac at GitHub for every change.
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
QUIET=0
DELETE_DATA=0
DELETE_NOTES=0
while [ $# -gt 0 ]; do
  case "$1" in
    --quiet) QUIET=1; shift ;;
    --delete-data) DELETE_DATA=1; shift ;;
    --delete-notes) DELETE_NOTES=1; shift ;;
    --install-dir) INSTALL_DIR="$(cd "${2:?--install-dir needs a folder}" && pwd)"; shift 2 ;;
    *) printf 'unknown option: %s\n' "$1" >&2; exit 1 ;;
  esac
done

# Only a folder the installer made is removed: one that holds the app and the installer's own list of its files.
if [ ! -f "$INSTALL_DIR/jcc/__init__.py" ] || [ ! -f "$INSTALL_DIR/.jarvis-files" ]; then
  printf '%s does not look like a folder the JARVIS installer made, so nothing was removed.\n' "$INSTALL_DIR"
  exit 1
fi

vault="$(sed -n "s/^[[:space:]]*vault[[:space:]]*=[[:space:]]*'\([^']*\)'.*/\1/p" "$INSTALL_DIR/config/local.toml" 2>/dev/null | head -n 1 || true)"
case "$vault" in "~"*) vault="$HOME${vault#\~}" ;; esac
case "$vault/" in
  "$INSTALL_DIR"/*) printf 'Your notes vault (%s) is inside the install folder. Move it somewhere else first; nothing was removed.\n' "$vault"; exit 1 ;;
esac
data="${JCC_STATE_DIR:-$HOME/Library/Application Support/JarvisCommand}"

if [ "$QUIET" = 0 ]; then
  answer=""
  read -r -p "Remove JARVIS from $INSTALL_DIR and its app? Your notes and data are kept. [y/N] " answer || true
  case "$answer" in [Yy]*) ;; *) echo "Nothing was removed."; exit 0 ;; esac
fi

# JARVIS's own programs that are running from this folder: stopped, so nothing is left running from removed files.
# Looked for again until none is left: one of them can start another while they are being stopped (the helper behind
# the menu-bar icon starts its icon again), and that one is stopped too.
stopped=0
for round in 1 2 3 4 5; do
  found=0
  for pid in $(pgrep -f 'jcc(\.| )(desktop|gui|tray|local_history|cloud_memory|maintenance)|jarvis-menu|jarvis-sound-level' 2>/dev/null || true); do
    where="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1 || true)"      # (it may have ended by now)
    program="$(ps -o command= -p "$pid" 2>/dev/null || true)"
    case "$where/ $program" in
      "$INSTALL_DIR"/*|*"$INSTALL_DIR/"*) kill "$pid" 2>/dev/null || true; stopped=1; found=1 ;;
    esac
  done
  [ "$found" = 1 ] || break
  sleep 1
done
if [ "$stopped" = 1 ]; then printf 'Stopped JARVIS.
'; sleep 2; fi      # (it ends before its files are removed)

agent="$(head -n 1 "$INSTALL_DIR/.login-agent" 2>/dev/null || true)"
case "$agent" in
  "$HOME"/Library/LaunchAgents/local.jarvis.background.plist)
    launchctl bootout "gui/$(id -u)" "$agent" >/dev/null 2>&1 || true
    rm -f "$agent"; printf 'JARVIS no longer starts when you log in.\n' ;;
esac

bundle="$(head -n 1 "$INSTALL_DIR/.app-bundle" 2>/dev/null || true)"
case "$bundle" in
  */JARVIS.app)
    if [ -f "$bundle/Contents/MacOS/JARVIS" ]; then rm -rf "$bundle"; printf 'Removed %s\n' "$bundle"; fi ;;
esac

cd /
rm -rf "$INSTALL_DIR"
printf 'Removed the app from %s.\n\n' "$INSTALL_DIR"
to_trash() {   # to_trash <folder>: into the Trash under a name of its own, so it can be put back
  [ -d "$1" ] || return 0
  mkdir -p "$HOME/.Trash"
  mv "$1" "$HOME/.Trash/$(basename "$1") $(date '+%Y-%m-%d %H.%M.%S')" && printf 'Moved to the Trash: %s\n' "$1"
}
if [ "$DELETE_DATA" = 1 ]; then to_trash "$data"; fi
if [ "$DELETE_NOTES" = 1 ] && [ -n "$vault" ]; then to_trash "$vault"; fi
printf 'Kept, for you to keep or delete yourself:\n'
if [ -n "$vault" ] && [ -d "$vault" ]; then printf '  Your notes vault:      %s\n' "$vault"; fi
if [ -d "$data" ]; then printf "  The app's data folder: %s\n" "$data"; fi
printf '  Keys, if you saved any: in the Keychain.\n'
