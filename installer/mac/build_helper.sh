#!/usr/bin/env bash
# Builds the helper that measures the Mac's own sound (sound_level.swift) for both kinds of Mac, as one program:
#
#   bash installer/mac/build_helper.sh [OUT_FOLDER]        (default: dist, beside the app)
#
# Needs a Mac with Apple's command line tools. The release workflow runs it before the Mac packages are built, so the
# packages carry a ready-built helper for people who do not have those tools.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
out="${1:-$here/../../dist}"
mkdir -p "$out"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

for arch in arm64 x86_64; do
  xcrun swiftc -O -target "$arch-apple-macos12.3" -o "$work/$arch" "$here/sound_level.swift"
done
lipo -create "$work/arm64" "$work/x86_64" -output "$out/jarvis-sound-level"
codesign --force -s - "$out/jarvis-sound-level"       # (signed by nobody in particular: Apple's own chips start nothing unsigned)
chmod 755 "$out/jarvis-sound-level"
lipo -info "$out/jarvis-sound-level"
