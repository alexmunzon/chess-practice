#!/bin/bash
# Builds and runs the occupancy-tracker gate checks (native/ChessCompanionApp/TrackerGateChecks.swift) against the
# current NativeEngineRuntime.swift, TrackerSetting.swift and a runtime bundle built from the current sources.
# macOS only: headless WKWebView, real local Stockfish, no Simulator, device, network or audio.
# Build outputs go outside the repo: each run gets its own new folder under ${TMPDIR:-/tmp}/chess-check-native
# (its bundle and binary are removed at the end, its text logs kept), so two runs cannot delete each other's files.
# CHECK_NATIVE_OUT=/some/dir uses that folder instead and keeps everything in it.
# Prints one line per check and "n of m checks passed", where m is always EXPECTED below; exits 0 only when exactly
# EXPECTED checks ran and all passed. Each step has an outer time limit, so a hang the program's own watchdog cannot
# stop still ends the run.
# Optional: CHECK_NATIVE_RUNTIME=/path/NativeEngineRuntime.swift and CHECK_NATIVE_SETTING=/path/TrackerSetting.swift
# build against other copies (used to prove the checks fail when a gate is removed).
set -u
EXPECTED=26                                    # update together with Harness.plan in TrackerGateChecks.swift
LIMIT_BUNDLE=120 LIMIT_COMPILE=600 LIMIT_RUN=240  # seconds
REPO=$(cd "$(dirname "$0")/.." && pwd)
BASE="${TMPDIR:-/tmp}/chess-check-native"
RUNTIME=${CHECK_NATIVE_RUNTIME:-$REPO/native/ChessCompanionRuntime/NativeEngineRuntime.swift}
SETTING=${CHECK_NATIVE_SETTING:-$REPO/native/ChessCompanionApp/TrackerSetting.swift}
APP_ADAPTERS=${CHECK_NATIVE_APP_ADAPTERS:-$REPO/native/ChessCompanionApp/AppAdapters.swift}
if [ -n "${CHECK_NATIVE_OUT:-}" ]; then
  OUT=$CHECK_NATIVE_OUT; OWN=0; MODULES=$OUT/module-cache
else
  mkdir -p "$BASE" || exit 2
  OUT=$(mktemp -d "$BASE/run.XXXXXX") || exit 2; OWN=1
  MODULES=$BASE/module-cache   # shared: the compiler's module cache is safe for concurrent builds
fi
case "$OUT" in "$REPO"|"$REPO"/*) echo "Build output must stay outside the repo: $OUT"; exit 2;; esac
mkdir -p "$OUT" || exit 2
rm -f "$OUT/timed-out"
START=$(date +%s)

# limited SECONDS COMMAND...: runs the command; after SECONDS it is killed (with its direct children) and 124 returned.
limited() {
  local secs=$1; shift
  "$@" &
  local pid=$!
  ( n=0
    while kill -0 "$pid" 2>/dev/null; do
      if [ "$n" -ge "$secs" ]; then echo "$secs" > "$OUT/timed-out"; pkill -9 -P "$pid" 2>/dev/null; kill -9 "$pid" 2>/dev/null; exit 0; fi
      sleep 1; n=$((n + 1))
    done ) &
  local watcher=$!
  wait "$pid"; local code=$?
  wait "$watcher"
  [ -f "$OUT/timed-out" ] && return 124
  return $code
}
finish() {   # finish EXIT_CODE: removes the bulky files of a run folder this script created, then exits
  [ "$OWN" = 1 ] && rm -rf "$OUT/Runtime" "$OUT/TrackerGateChecks"
  exit "$1"
}

# The runtime bundle is rebuilt from the current sources each run, so the checks see today's files.
rm -rf "$OUT/Runtime"
if ! (cd "$REPO" && limited $LIMIT_BUNDLE node scripts/build-device-runtime.mjs --out "$OUT/Runtime") > "$OUT/bundle.txt" 2>&1; then
  echo "FAIL: runtime bundle did not build (see $OUT/bundle.txt)"; echo "0 of $EXPECTED checks passed"; finish 1
fi
if ! limited $LIMIT_COMPILE nice -n 10 xcrun swiftc -parse-as-library -swift-version 6 -module-cache-path "$MODULES" \
     -D COMPANION_MONOLITHIC_BUILD -D COMPANION_RUNTIME_SOURCE -D COMPANION_SELFTEST \
     -o "$OUT/TrackerGateChecks" "$RUNTIME" "$SETTING" "$APP_ADAPTERS" \
     "$REPO/native/ChessCompanionCapture/Sources/ChessCompanionCapture/CaptureContracts.swift" \
     "$REPO/native/ChessCompanionVision/ImageDecoder.swift" "$REPO/native/ChessCompanionVision/PixelFeatures.swift" \
     "$REPO/native/ChessCompanionVision/SyntheticRecognizer.swift" \
     "$REPO/native/ChessCompanionIntegration/Adapters.swift" "$REPO/native/ChessCompanionIntegration/RuntimeTransport.swift" \
     "$REPO/native/ChessCompanionIntegration/ReplayTracker.swift" "$REPO/native/ChessCompanionIntegration/ReplayTrackerRuntimeTransport.swift" \
     "$REPO/native/ChessCompanionApp/OfflineStudy.swift" "$REPO/native/ChessCompanionApp/ReplayGame.swift" \
     "$REPO/native/ChessCompanionApp/TrackerGateChecks.swift" \
     > "$OUT/compile.txt" 2>&1; then
  echo "FAIL: TrackerGateChecks did not compile (see $OUT/compile.txt)"; tail -5 "$OUT/compile.txt"; echo "0 of $EXPECTED checks passed"; finish 1
fi
limited $LIMIT_RUN "$OUT/TrackerGateChecks" "$OUT/Runtime" > "$OUT/run.txt" 2>&1
CODE=$?
grep -E '^(PASS|FAIL): ' "$OUT/run.txt"
PASSED=$(grep -c '^PASS: ' "$OUT/run.txt")
FAILED=$(grep -c '^FAIL: ' "$OUT/run.txt")
RAN=$((PASSED + FAILED))
echo "(run time $(( $(date +%s) - START )) s; full output $OUT/run.txt)"
if [ "$CODE" = 0 ] && [ "$FAILED" = 0 ] && [ "$RAN" = "$EXPECTED" ] && grep -qx "$EXPECTED of $EXPECTED checks passed" "$OUT/run.txt"; then
  echo "$PASSED of $EXPECTED checks passed"; finish 0
fi
[ -f "$OUT/timed-out" ] && echo "FAIL: the checks program was stopped by the outer time limit ($LIMIT_RUN s)"
[ "$RAN" != "$EXPECTED" ] && echo "FAIL: $RAN check results printed, $EXPECTED expected"
[ "$CODE" != 0 ] && [ "$FAILED" = 0 ] && echo "FAIL: the checks program exited $CODE without a complete result"
[ "$CODE" = 0 ] && [ "$FAILED" = 0 ] && [ "$RAN" = "$EXPECTED" ] && echo "FAIL: the checks program's own summary line is missing"
# The total is the expected count: checks that never printed count as not passed (a crash after 6 checks prints
# "6 of 26"). If more checks ran than expected, or all printed PASS but the run still failed, the failed run itself is
# counted as one more check, so the line never reads "n of n" on a failure.
TOTAL=$EXPECTED
[ "$RAN" -gt "$EXPECTED" ] && TOTAL=$((RAN + 1))
[ "$RAN" = "$EXPECTED" ] && [ "$PASSED" = "$EXPECTED" ] && TOTAL=$((EXPECTED + 1))
echo "$PASSED of $TOTAL checks passed"; finish 1
