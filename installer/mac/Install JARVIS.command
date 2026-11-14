#!/bin/bash
# Double-click this file in Finder to install JARVIS. It runs install.sh, which sits beside it.
cd "$(dirname "$0")" || exit 1
status=0
bash ./install.sh "$@" || status=$?
echo
read -r -p "Press Return to close this window. " _ || true
exit "$status"
