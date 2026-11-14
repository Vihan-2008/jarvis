#!/usr/bin/env bash
# Makes dist/JARVIS.dmg from the same content as JARVIS-mac.zip. For a Mac only: hdiutil exists nowhere else.
# The release workflow runs it on a macOS runner. It was written without a Mac at hand and first runs in CI.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
[ "$(uname -s)" = Darwin ] || { echo "build_dmg.sh needs macOS (hdiutil)." >&2; exit 1; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
python3 "$here/build.py" --stage "$work/JARVIS Installer"
mkdir -p "$repo/dist"
rm -f "$repo/dist/JARVIS.dmg"
hdiutil create -volname "JARVIS" -srcfolder "$work/JARVIS Installer" -ov -format UDZO "$repo/dist/JARVIS.dmg"
echo "Made $repo/dist/JARVIS.dmg"
