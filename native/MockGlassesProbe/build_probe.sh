#!/bin/sh
# Compile and link (never run) the Meta mock-glasses probes for the iOS Simulator.
# Usage: build_probe.sh <frameworks dir> <out dir>
# The frameworks dir must contain MWDATCore/MWDATCamera/MWDATMockDevice .framework
# folders copied from the SDK's ios-arm64_x86_64-simulator slices.
set -eu
[ $# -eq 2 ] || { echo "usage: $0 <frameworks dir> <out dir>" >&2; exit 2; }
FW=$(cd "$1" && pwd)
mkdir -p "$2"; OUT=$(cd "$2" && pwd)
HERE=$(cd "$(dirname "$0")" && pwd)
SDK=$(xcrun --sdk iphonesimulator --show-sdk-path)
TARGET=arm64-apple-ios17.2-simulator
for f in MWDATCore MWDATCamera MWDATMockDevice; do
  [ -f "$FW/$f.framework/$f" ] || { echo "missing $FW/$f.framework" >&2; exit 2; }
done
FLAGS="-target $TARGET -sdk $SDK -swift-version 6 -F $FW
  -framework MWDATCore -framework MWDATCamera -framework MWDATMockDevice
  -Xlinker -rpath -Xlinker @executable_path/Frameworks
  -module-cache-path $OUT/module-cache"

echo "== swiftc --version"; xcrun swiftc --version
echo "== [1/2] import probe (compile + link)"
# shellcheck disable=SC2086
xcrun --sdk iphonesimulator swiftc $FLAGS "$HERE/ImportProbe.swift" -o "$OUT/ImportProbe"
echo "== otool -L ImportProbe"; xcrun otool -L "$OUT/ImportProbe"
echo "== [2/2] Phase 3 call-sequence probe (compile + link)"
# shellcheck disable=SC2086
xcrun --sdk iphonesimulator swiftc $FLAGS "$HERE/CallSequenceProbe.swift" -o "$OUT/CallSequenceProbe"
echo "== otool -L CallSequenceProbe"; xcrun otool -L "$OUT/CallSequenceProbe"
echo "BUILD OK (binaries were not executed)"
