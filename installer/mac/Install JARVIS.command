#!/bin/bash
# Double-click this file in Finder to install JARVIS. It runs install.sh, which is in the hidden folder beside it
# (".jarvis-app", with the app's own files).
cd "$(dirname "$0")" || exit 1
status=0
if [ -f ./.jarvis-app/install.sh ]; then
  bash ./.jarvis-app/install.sh "$@" || status=$?
else
  bash ./install.sh "$@" || status=$?
fi
echo
read -r -p "Press Return to close this window. " _ || true
exit "$status"
