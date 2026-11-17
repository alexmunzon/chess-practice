#!/bin/bash
# One command for every project check: the Node suite plus the Python recognition tests.
# Run from anywhere, OUTSIDE a command sandbox (npm test opens 127.0.0.1 listeners; "listen EPERM"
# means sandbox, not a code failure). Prints one line per suite and "n of m suites passed".
# Exit 0 only if every suite passed. Usage: scripts/check-all.sh [--quick]  (--quick skips Python)
cd "$(dirname "$0")/.." || exit 1
LOG_DIR="${CHECK_LOG_DIR:-${TMPDIR:-/tmp}/chess-check-$$}"
mkdir -p "$LOG_DIR"
echo "load: $(uptime | sed 's/.*load averages*: //')   logs: $LOG_DIR"
passed=0; total=0; failed_names=""
run_suite() {
  name="$1"; shift
  total=$((total + 1))
  if "$@" > "$LOG_DIR/$name.log" 2>&1; then
    passed=$((passed + 1)); echo "PASS  $name  ($(tail -40 "$LOG_DIR/$name.log" | grep -E '^ℹ (tests|pass|fail|skipped)|^Ran |^OK|^PASS' | tr '\n' ' '))"
  else
    failed_names="$failed_names $name"; echo "FAIL  $name  (see $LOG_DIR/$name.log)"; tail -15 "$LOG_DIR/$name.log" | sed 's/^/      /'
  fi
}
run_suite npm-test npm test
if [ "$1" != "--quick" ]; then
  for t in screen_pipeline occupancy_classifier_v3 occupancy_classifier_v4 occupancy_classifier piece_classifier_v1 piece_classifier_v2 piece_guard screen_game_scenes mock_glasses_video mock_glasses_frame_age; do
    if [ -f "tests/$t.py" ]; then run_suite "py-$t" python3 -B "tests/$t.py"; fi
  done
fi
echo "$passed of $total suites passed"
[ -z "$failed_names" ] || { echo "failed:$failed_names"; exit 1; }
