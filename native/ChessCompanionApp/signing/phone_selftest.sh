#!/usr/bin/env bash
# One-command phone self-test for the private Chess Companion app.
#   preflight -> sign (via sign_and_install.sh) -> install -> run (launch --chess-self-test,
#   poll for a fresh report) -> optional restore of the normal app.
# Never deletes anything on the phone, never reads/prints private keys, never asks for passwords.
# Exit codes: 0 all checks passed | 2 report complete, some check failed | 3 interrupted/backgrounded
#             4 launch failed | 5 timeout | 1 anything else (including refused preflight)
set -euo pipefail

SCRIPT_START_EPOCH="$(date -u +%s)"   # freshness marker: the report's startTime must be later
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
KIT="$HERE/sign_and_install.sh"
SUMMARIZER="$HERE/summarize_selftest.py"
BUNDLE_ID="local.chesscompanion.offlinestudy"
REPORT_ON_PHONE="Documents/selftest-report.json"
SELFTEST_MARKER="--chess-self-test"
OUT_MARKER=".phone_selftest"

APP=""; SHA=""; PROV=""; IDENTITY=""; OUT=""; DEVICE=""; TIMEOUT=180
RESTORE_APP=""; RESTORE_SHA=""; ONLY=""; DRY=0; ALLOW_NORMAL=0

die() { echo "ERROR: $*" >&2; exit 1; }
say() { echo; echo "== $*"; }
note() { echo "   $*"; }

usage() {
  cat <<USAGE
Usage: $0 --app UNSIGNED.app --sha256 HEX --provisioning DIR --identity "NAME" --out NEW_DIR
          [--device ID] [--timeout SECONDS] [--restore-app NORMAL.app --restore-sha256 HEX]
          [--only preflight|sign|install|run|restore] [--dry-run] [--allow-normal]
  --provisioning DIR  holds profile.mobileprovision, profile.plist, entitlements.plist
  --out DIR           new folder OUTSIDE the git repo (or one this script made earlier, for --only)
  --only STEP         preflight always runs; then only STEP runs
  --dry-run           run the read-only preflight, print every signing/device command, execute none
  --allow-normal      allow an app WITHOUT self-test code (it will not write a report)
Exit: 0 pass, 2 some check failed, 3 interrupted (wake and unlock the phone, re-run), 4 launch failed, 5 timeout, 1 other
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --app|--sha256|--provisioning|--identity|--out|--device|--timeout|--restore-app|--restore-sha256|--only)
      [ $# -ge 2 ] || die "$1 needs a value"
      case "$1" in
        --app) APP="$2" ;; --sha256) SHA="$2" ;; --provisioning) PROV="$2" ;;
        --identity) IDENTITY="$2" ;; --out) OUT="$2" ;; --device) DEVICE="$2" ;;
        --timeout) TIMEOUT="$2" ;; --restore-app) RESTORE_APP="$2" ;;
        --restore-sha256) RESTORE_SHA="$2" ;; --only) ONLY="$2" ;;
      esac
      shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --allow-normal) ALLOW_NORMAL=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "unknown option: $1" ;;
  esac
done

# ---------- argument checks (refuse rather than guess) ----------
[ -n "$APP" ] && [ -n "$SHA" ] && [ -n "$PROV" ] && [ -n "$IDENTITY" ] && [ -n "$OUT" ] \
  || { usage >&2; die "--app, --sha256, --provisioning, --identity and --out are all required"; }
SHA="$(printf '%s' "$SHA" | tr 'A-F' 'a-f')"
printf '%s' "$SHA" | grep -Eq '^[0-9a-f]{64}$' || die "--sha256 must be 64 hex characters"
case "$TIMEOUT" in ''|*[!0-9]*) die "--timeout must be a whole number of seconds" ;; esac
[ "$TIMEOUT" -ge 30 ] && [ "$TIMEOUT" -le 1800 ] || die "--timeout must be between 30 and 1800"
case "$ONLY" in ''|preflight|sign|install|run|restore) ;; *) die "--only must be preflight, sign, install, run or restore" ;; esac
if [ -n "$RESTORE_APP" ] || [ -n "$RESTORE_SHA" ]; then
  [ -n "$RESTORE_APP" ] && [ -n "$RESTORE_SHA" ] || die "--restore-app and --restore-sha256 go together"
  RESTORE_SHA="$(printf '%s' "$RESTORE_SHA" | tr 'A-F' 'a-f')"
  printf '%s' "$RESTORE_SHA" | grep -Eq '^[0-9a-f]{64}$' || die "--restore-sha256 must be 64 hex characters"
fi
[ "$ONLY" != restore ] || [ -n "$RESTORE_APP" ] || die "--only restore needs --restore-app and --restore-sha256"

want() { [ -z "$ONLY" ] || [ "$ONLY" = "$1" ]; }

# Resolve a possibly-nonexistent path to a physical absolute path (same logic as the kit).
physical_path() {
  local p="$1" tail="" base
  case "$p" in /*) ;; *) p="$PWD/$p" ;; esac
  while [ ! -d "$p" ]; do base="$(basename "$p")"; tail="/$base$tail"; p="$(dirname "$p")"; done
  echo "$(cd "$p" && pwd -P)$tail"
}
repo_root() {
  local r; r="$(git -C "$HERE" rev-parse --show-toplevel 2>/dev/null || true)"
  [ -n "$r" ] || r="$HERE/../../.."
  (cd "$r" && pwd -P)
}

OUT="$(physical_path "$OUT")"
ROOT="$(repo_root)"
case "$OUT/" in "$ROOT"/*) die "--out $OUT is inside the git repo $ROOT. Choose a new folder outside the repo." ;; esac
[ -d "$APP" ] || die "app not found: $APP"
APP="$(physical_path "$APP")"
[ -d "$PROV" ] || die "provisioning folder not found: $PROV"
PROV="$(physical_path "$PROV")"
case "$OUT/" in "$APP"/*|"$PROV"/*) die "--out must not be inside the app or the provisioning folder" ;; esac
if [ -e "$OUT" ]; then
  [ -d "$OUT" ] || die "--out exists and is not a folder: $OUT"
  if [ -z "$ONLY" ]; then
    die "--out $OUT already exists; a full run needs a NEW folder (use --only STEP to continue an earlier run)"
  fi
  [ -f "$OUT/$OUT_MARKER" ] || [ -z "$(ls -A "$OUT")" ] || die "--out $OUT exists and was not created by this script; refusing to write into it"
fi
if [ -n "$RESTORE_APP" ]; then [ -d "$RESTORE_APP" ] || die "restore app not found: $RESTORE_APP"; RESTORE_APP="$(physical_path "$RESTORE_APP")"; fi

# Scratch for read-only preflight files: OUT for real runs, a temp dir for dry runs (OUT untouched).
if [ "$DRY" = 1 ]; then
  WORK="$(mktemp -d "${TMPDIR:-/tmp}/phone_selftest_dry.XXXXXX")"
  trap 'rm -rf "$WORK"' EXIT
else
  mkdir -p "$OUT"; touch "$OUT/$OUT_MARKER"; WORK="$OUT/preflight"; mkdir -p "$WORK"
fi

# Print a command (shell-quoted); execute it unless --dry-run.
run() {
  if [ "$DRY" = 1 ]; then printf '[dry-run]'; else printf '+'; fi
  printf ' %q' "$@"; echo
  [ "$DRY" = 1 ] || "$@"
}
# Same, with stdout+stderr captured to a file (first argument).
run_to() {
  local f="$1"; shift
  if [ "$DRY" = 1 ]; then printf '[dry-run]'; else printf '+'; fi
  printf ' %q' "$@"; printf ' > %q 2>&1\n' "$f"
  [ "$DRY" = 1 ] || "$@" > "$f" 2>&1
}

exe_path() { echo "$1/$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$1/Info.plist")"; }
exe_hash() { shasum -a 256 "$(exe_path "$1")" | awk '{print $1}'; }
bundle_id() { /usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$1/Info.plist"; }
selftest_strings() { LC_ALL=C grep -a -c -F -e "$SELFTEST_MARKER" -e "selftest-report.json" "$(exe_path "$1")" || true; }

# ---------- STEP: preflight (always runs; read-only) ----------
say "STEP preflight (read-only)"
for t in xcrun security python3 shasum git; do command -v "$t" >/dev/null || die "missing tool: $t"; done
[ -x "$KIT" ] || die "signing kit not found or not executable: $KIT"
[ -f "$SUMMARIZER" ] || die "summarizer not found: $SUMMARIZER"
for f in profile.mobileprovision profile.plist entitlements.plist; do
  [ -f "$PROV/$f" ] || die "provisioning folder is missing $f: $PROV"
done
note "out:          $OUT (outside repo $ROOT)"
note "provisioning: $PROV"

# Identity: exactly one match, resolved to its certificate SHA-1 (names only; no key material).
IDS="$(security find-identity -v -p codesigning | grep -F -- "$IDENTITY" || true)"
[ -n "$IDS" ] || die "signing identity not found: $IDENTITY (see: security find-identity -v -p codesigning)"
[ "$(printf '%s\n' "$IDS" | wc -l | tr -d ' ')" = 1 ] || die "identity name matches more than one certificate; be more specific"
CERT_SHA1="$(printf '%s\n' "$IDS" | awk '{print $2}')"
note "identity:     found (certificate SHA-1 $CERT_SHA1)"

# Profile facts.
PROFILE_FACTS="$WORK/profile-facts.txt"
python3 -I - "$PROV/profile.plist" "$PROV/entitlements.plist" "$CERT_SHA1" > "$PROFILE_FACTS" <<'PY'
import plistlib, hashlib, sys, datetime as dt
p = plistlib.load(open(sys.argv[1], "rb")); e = plistlib.load(open(sys.argv[2], "rb"))
exp = p["ExpirationDate"]
if exp.tzinfo is None: exp = exp.replace(tzinfo=dt.timezone.utc)
now = dt.datetime.now(dt.timezone.utc)
appid = p.get("Entitlements", {}).get("application-identifier", "")
certs = [hashlib.sha1(c).hexdigest().upper() for c in p.get("DeveloperCertificates", [])]
print("expires=%s" % exp.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
print("hours_left=%d" % int((exp - now).total_seconds() // 3600))
print("seconds_left=%d" % int((exp - now).total_seconds()))
print("appid=%s" % appid)
print("ent_appid=%s" % e.get("application-identifier", ""))
print("team=%s" % (p.get("TeamIdentifier") or [""])[0])
print("cert_in_profile=%s" % ("yes" if sys.argv[3].upper() in certs else "no"))
print("devices=%s" % ",".join(p.get("ProvisionedDevices", [])))
PY
fact() { awk -F= -v k="$1" '$1==k {sub(/^[^=]*=/, ""); print; exit}' "$PROFILE_FACTS"; }
EXPIRES="$(fact expires)"; SECS_LEFT="$(fact seconds_left)"; HOURS_LEFT="$(fact hours_left)"
APPID="$(fact appid)"; TEAM="$(fact team)"; PROFILE_DEVICES="$(fact devices)"
note "profile:      team $TEAM, app id $APPID, expires $EXPIRES (${HOURS_LEFT} h left)"
[ "$SECS_LEFT" -gt 0 ] || die "provisioning profile EXPIRED at $EXPIRES. Renew it first: $HERE/renew_profile.sh --team $TEAM --out NEW_DIR"
[ "$SECS_LEFT" -gt 3600 ] || die "profile expires within the hour ($EXPIRES); renew first with renew_profile.sh"
[ "$HOURS_LEFT" -ge 24 ] || note "WARNING: profile expires in under 24 h ($EXPIRES); renew soon with renew_profile.sh"
[ "$(fact ent_appid)" = "$APPID" ] || die "entitlements.plist application-identifier does not match the profile"
[ "$(fact cert_in_profile)" = yes ] || die "this identity's certificate is not in the profile; the phone would reject the install"

check_bundle_matches_profile() { # $1 = app
  local bid suffix; bid="$(bundle_id "$1")"; suffix="${APPID#"$TEAM".}"
  case "$suffix" in
    *'*') case "$bid" in "${suffix%\*}"*) ;; *) die "bundle id $bid does not match profile app id $APPID" ;; esac ;;
    *) [ "$bid" = "$suffix" ] || die "bundle id $bid does not match profile app id $APPID" ;;
  esac
  [ "$bid" = "$BUNDLE_ID" ] || die "bundle id $bid is not the Chess Companion id $BUNDLE_ID"
}

# Self-test app.
GOT="$(exe_hash "$APP")"
[ "$GOT" = "$SHA" ] || die "app executable SHA-256 is $GOT, expected $SHA; refusing"
check_bundle_matches_profile "$APP"
N_ST="$(selftest_strings "$APP")"
if [ "$N_ST" -gt 0 ]; then note "app:          $APP (hash MATCH, self-test code present: $N_ST marker(s))"
elif [ "$ALLOW_NORMAL" = 1 ]; then note "app:          WARNING no self-test code (--allow-normal); no report will be written"
else die "app has NO self-test code (no '$SELFTEST_MARKER' string). Build with prepare_app.py --self-test, or pass --allow-normal"; fi
[ ! -e "$APP/_CodeSignature" ] || note "note: app already has a _CodeSignature folder (the kit re-signs a copy)"

# Restore app (normal build).
if [ -n "$RESTORE_APP" ]; then
  [ "$(exe_hash "$RESTORE_APP")" = "$RESTORE_SHA" ] || die "restore app executable SHA-256 does not match --restore-sha256; refusing"
  check_bundle_matches_profile "$RESTORE_APP"
  [ "$(selftest_strings "$RESTORE_APP")" = 0 ] || die "restore app CONTAINS self-test code; it must be the normal build"
  note "restore app:  $RESTORE_APP (hash MATCH, no self-test code)"
fi

# Device: listed, paired, reachable, and inside the profile.
DEV_JSON="$WORK/devices.json"
xcrun devicectl list devices --json-output "$DEV_JSON" >/dev/null 2>&1 || die "xcrun devicectl list devices failed"
DEV_FACTS="$(python3 -I - "$DEV_JSON" "$DEVICE" <<'PY'
import json, sys
devs = json.load(open(sys.argv[1])).get("result", {}).get("devices", [])
want = sys.argv[2].lower()
def ids(d):
    return [x.lower() for x in (d.get("identifier", ""), d.get("hardwareProperties", {}).get("udid", ""),
            d.get("deviceProperties", {}).get("name", "")) if x]
def up(d):
    c = d.get("connectionProperties", {})
    return c.get("pairingState") == "paired" and (c.get("tunnelState") == "connected" or bool(c.get("transportType")))
if want:
    m = [d for d in devs if want in ids(d)]
else:
    m = [d for d in devs if up(d)]
if len(m) != 1:
    print("ERR %d matching device(s)" % len(m)); sys.exit(0)
d = m[0]; c = d.get("connectionProperties", {})
print("OK %s %s %s %s %s %s" % (d.get("identifier"), d.get("hardwareProperties", {}).get("udid", "-"),
      c.get("pairingState", "-"), c.get("tunnelState", "-"), c.get("transportType", "-") or "-",
      d.get("deviceProperties", {}).get("osVersionNumber", "-")))
PY
)"
case "$DEV_FACTS" in
  OK*) ;;
  *) die "device check: ${DEV_FACTS#ERR } (${DEVICE:-no --device given}). Plug in and unlock the phone, or pass --device ID" ;;
esac
set -- $DEV_FACTS
DEVICE="$2"; UDID="$3"; PAIR="$4"; TUNNEL="$5"; TRANSPORT="$6"; IOS="$7"
note "device:       $DEVICE (UDID $UDID, iOS $IOS, $PAIR, tunnel $TUNNEL, transport $TRANSPORT)"
[ "$PAIR" = paired ] || die "phone is not paired with this Mac"
[ "$TUNNEL" = connected ] || [ "$TRANSPORT" != - ] || die "phone is listed but not connected; plug it in and unlock it"
case ",$PROFILE_DEVICES," in *",$UDID,"*) ;; *) die "phone UDID $UDID is not in the profile's device list" ;; esac
echo "preflight OK"
[ "$ONLY" != preflight ] || exit 0

SIGN_DIR="$OUT/selftest-signing"
RESTORE_DIR="$OUT/restore-signing"
RUN_DIR="$OUT/run"

kit_sign() { # $1 dir, $2 app, $3 sha
  run mkdir -p "$1"
  local f; for f in profile.mobileprovision profile.plist entitlements.plist; do run cp "$PROV/$f" "$1/$f"; done
  run "$KIT" sign --app "$2" --sha256 "$3" --identity "$IDENTITY" --out "$1" --device "$DEVICE"
}

# ---------- STEP: sign ----------
if want sign; then
  say "STEP sign (via sign_and_install.sh, into $SIGN_DIR)"
  kit_sign "$SIGN_DIR" "$APP" "$SHA"
  if [ "$DRY" = 0 ]; then
    SIGNED_SHA="$(exe_hash "$SIGN_DIR/ChessCompanion.app")"
    [ "$ALLOW_NORMAL" = 1 ] || [ "$(selftest_strings "$SIGN_DIR/ChessCompanion.app")" -gt 0 ] || die "signed copy lost its self-test code?"
    printf '%s  unsigned-selftest-executable\n%s  signed-selftest-executable\n' "$SHA" "$SIGNED_SHA" > "$OUT/sha256.txt"
    note "signed executable sha256: $SIGNED_SHA"
  fi
fi

# ---------- STEP: install ----------
if want install; then
  say "STEP install (via sign_and_install.sh)"
  [ "$DRY" = 1 ] || [ -d "$SIGN_DIR/ChessCompanion.app" ] || die "no signed app in $SIGN_DIR; run the sign step first"
  run "$KIT" install --out "$SIGN_DIR" --device "$DEVICE" --app "$APP" --sha256 "$SHA"
fi

# ---------- STEP: run ----------
RUN_CODE=""
copy_report() { # $1 destination; never deletes anything on the phone
  run_to "$1.log" xcrun devicectl device copy from --device "$DEVICE" --domain-type appDataContainer \
    --domain-identifier "$BUNDLE_ID" --source "$REPORT_ON_PHONE" --destination "$1" --timeout 30
}
if want run; then
  say "STEP run (launch with $SELFTEST_MARKER, poll for a fresh report, timeout ${TIMEOUT}s)"
  [ "$ALLOW_NORMAL" = 0 ] || die "--allow-normal app has no self-test; the run step would only time out. Use --only sign/install."
  run mkdir -p "$RUN_DIR"
  # Run marker: the report already on the phone (if any). Nothing is deleted; a new report must
  # have startTime after this script started AND differ from this one.
  PREV_START=""
  if copy_report "$RUN_DIR/previous-report.json"; then
    if [ "$DRY" = 0 ] && [ -f "$RUN_DIR/previous-report.json" ]; then
      PREV_START="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1])).get("startTime") or "")' "$RUN_DIR/previous-report.json" 2>/dev/null || true)"
    fi
  else
    note "no earlier report on the phone (or it could not be read); continuing"
  fi
  note "freshness: startTime must be after $(date -u -r "$SCRIPT_START_EPOCH" +%Y-%m-%dT%H:%M:%SZ) (script launch, Mac clock) and differ from '${PREV_START:-none}'"
  [ "$DRY" = 1 ] || printf 'script_start_epoch=%s\nprevious_start=%s\n' "$SCRIPT_START_EPOCH" "$PREV_START" > "$RUN_DIR/run-marker.txt"

  if ! run_to "$RUN_DIR/launch.log" xcrun devicectl device process launch --device "$DEVICE" --terminate-existing "$BUNDLE_ID" "$SELFTEST_MARKER"; then
    cat "$RUN_DIR/launch.log" >&2 || true
    echo "LAUNCH FAILED (exit 4). Unlock the phone, check it trusts the developer (Settings > General > VPN & Device Management), then re-run with --only run." >&2
    exit 4
  fi
  [ "$DRY" = 1 ] || cat "$RUN_DIR/launch.log"

  LATEST="$RUN_DIR/poll-latest.json"
  BRIEF_ARGS=(--brief --fresh-after-epoch "$SCRIPT_START_EPOCH")
  [ -z "$PREV_START" ] || BRIEF_ARGS=("${BRIEF_ARGS[@]}" --not-start "$PREV_START")
  if [ "$DRY" = 1 ]; then
    echo "[dry-run] poll every 5,10,15,20,20... s up to ${TIMEOUT}s:"
    copy_report "$LATEST"
    printf '[dry-run]'; printf ' %q' python3 -I "$SUMMARIZER" "${BRIEF_ARGS[@]}" "$LATEST"; echo
    echo "[dry-run] stop when fresh and not 'in progress', or fresh+INTERRUPTED and unchanged across two polls"
    echo "[dry-run] then save $OUT/selftest-report.json (+ .sha256, summary.txt, summary.json) and print the summary"
  else
    START="$SECONDS"; DELAY=5; LAST_SHA=""; FINAL=""; HAVE_FRESH=0
    while :; do
      ELAPSED=$((SECONDS - START))
      [ "$ELAPSED" -lt "$TIMEOUT" ] || break
      sleep "$DELAY"; [ "$DELAY" -ge 20 ] || DELAY=$((DELAY + 5))
      rm -f "$LATEST"   # local copy only, so an old poll is never re-read
      if ! copy_report "$LATEST" >/dev/null 2>&1 || [ ! -s "$LATEST" ]; then
        note "$((SECONDS - START))s: no report yet"; continue
      fi
      LINE="$(python3 -I "$SUMMARIZER" "${BRIEF_ARGS[@]}" "$LATEST" || true)"
      [ -n "$LINE" ] || LINE="UNREADABLE stale in_progress"
      CUR_SHA="$(shasum -a 256 "$LATEST" | awk '{print $1}')"
      note "$((SECONDS - START))s: $LINE"
      set -- $LINE
      case "$2" in fresh) HAVE_FRESH=1; cp "$LATEST" "$RUN_DIR/last-fresh.json" ;; *) continue ;; esac
      if [ "$3" = done ]; then FINAL="$LATEST"; break; fi
      if [ "$1" = INTERRUPTED ] && [ "$CUR_SHA" = "$LAST_SHA" ]; then FINAL="$LATEST"; break; fi
      LAST_SHA="$CUR_SHA"
    done
    if [ -n "$FINAL" ]; then cp "$FINAL" "$OUT/selftest-report.json"
    elif [ "$HAVE_FRESH" = 1 ]; then cp "$RUN_DIR/last-fresh.json" "$OUT/selftest-report.json"; fi
    if [ -f "$OUT/selftest-report.json" ]; then
      (cd "$OUT" && shasum -a 256 selftest-report.json > selftest-report.json.sha256)
      cat "$OUT/selftest-report.json.sha256" >> "$OUT/sha256.txt"
      python3 -I "$SUMMARIZER" --json "$OUT/selftest-report.json" > "$OUT/summary.json" || true
      say "Summary"
      set +e; python3 -I "$SUMMARIZER" "$OUT/selftest-report.json" | tee "$OUT/summary.txt"; SUM_CODE="${PIPESTATUS[0]}"; set -e
    else
      SUM_CODE=5
    fi
    if [ -z "$FINAL" ]; then
      RUN_CODE=5; echo "TIMEOUT (exit 5): no finished, fresh report within ${TIMEOUT}s. Evidence in $RUN_DIR"
    else
      case "$SUM_CODE" in 0|2|3) RUN_CODE="$SUM_CODE" ;; 5) RUN_CODE=5 ;; *) RUN_CODE=1 ;; esac
    fi
    [ "$RUN_CODE" != 3 ] || echo "INTERRUPTED (exit 3): wake and unlock the phone, then re-run."
  fi
fi

# ---------- STEP: restore ----------
if [ -n "$RESTORE_APP" ] && want restore; then
  say "STEP restore normal app (into $RESTORE_DIR)"
  kit_sign "$RESTORE_DIR" "$RESTORE_APP" "$RESTORE_SHA"
  if [ "$DRY" = 0 ]; then
    N="$(selftest_strings "$RESTORE_DIR/ChessCompanion.app")"
    [ "$N" = 0 ] || die "signed restore app contains self-test strings ($N); NOT installing it"
    note "signed restore executable: $(exe_hash "$RESTORE_DIR/ChessCompanion.app"), 0 self-test strings"
  else
    echo "[dry-run] verify the signed restore copy has 0 self-test strings before installing"
  fi
  if ! run "$KIT" install --out "$RESTORE_DIR" --device "$DEVICE" --app "$RESTORE_APP" --sha256 "$RESTORE_SHA"; then
    echo "RESTORE FAILED: the phone may still have the self-test build installed." >&2; exit 1
  fi
  if [ "$DRY" = 0 ]; then
    printf '%s  unsigned-restore-executable\n%s  signed-restore-executable (installed, 0 self-test strings)\n' \
      "$RESTORE_SHA" "$(exe_hash "$RESTORE_DIR/ChessCompanion.app")" >> "$OUT/sha256.txt"
  fi
  [ "$DRY" = 1 ] || echo "restore OK: normal build installed (signed copy verified free of self-test code before install)"
fi

[ "$DRY" = 0 ] || { echo; echo "dry run complete: nothing was signed, installed, launched or copied."; exit 0; }
exit "${RUN_CODE:-0}"
