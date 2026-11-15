#!/usr/bin/env bash
# Builds JARVIS's two small Mac programs for both kinds of Mac, each as one program:
#
#   jarvis-sound-level   measures the Mac's own sound                      (sound_level.swift)
#   jarvis-menu          the menu-bar icon and the shortcuts from any app  (menu_bar.swift)
#   jarvis-launcher      the program inside JARVIS.app                     (launcher.swift)
#
#   bash installer/mac/build_helper.sh [OUT_FOLDER]        (default: dist, beside the app)
#
# Needs a Mac with Apple's command line tools. The release workflow runs it before the Mac packages are built, so the
# packages carry ready-built programs for people who do not have those tools.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
out="${1:-$here/../../dist}"
mkdir -p "$out"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

build() {   # build <program> <source>
  local arch
  for arch in arm64 x86_64; do
    xcrun swiftc -O -target "$arch-apple-macos12.3" -o "$work/$1-$arch" "$here/$2"
  done
  lipo -create "$work/$1-arm64" "$work/$1-x86_64" -output "$out/$1"
  codesign --force -s - "$out/$1"       # (signed by nobody in particular: Apple's own chips start nothing unsigned)
  chmod 755 "$out/$1"
  lipo -info "$out/$1"
}

build jarvis-sound-level sound_level.swift
build jarvis-menu menu_bar.swift
build jarvis-launcher launcher.swift

# "Install JARVIS": the app a person double-clicks in the download (install_app.applescript), so that installing
# needs no Terminal window. Made with Apple's own osacompile, given JARVIS's icon, and signed like the programs above.
app="$out/Install JARVIS.app"
rm -rf "$app"
osacompile -o "$app" "$here/install_app.applescript"
if python3 -c 'import sys' 2>/dev/null; then
  iconset="$work/installer.iconset"; mkdir -p "$iconset"
  for size in 16 32 128 256 512; do
    ( cd "$here/../.." && python3 -m jcc.icon "$iconset/icon_${size}x${size}.png" "$size" ) || true
  done
  if iconutil -c icns "$iconset" -o "$work/installer.icns" 2>/dev/null; then cp "$work/installer.icns" "$app/Contents/Resources/applet.icns"; fi
fi
codesign --force --deep -s - "$app"
plutil -lint "$app/Contents/Info.plist"
echo "made $app"
