#!/usr/bin/env bash
# Signing and install kit for the private Chess Companion app.
# Subcommands: preflight | provision | sign | install | launch   (see README.md)
# Never reads, prints or exports private keys. Never asks for passwords.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT="$HERE/ProvisioningShell/ProvisioningShell.xcodeproj"
BUNDLE_ID="local.chesscompanion.offlinestudy"
DEFAULT_APP="/private/var/folders/40/pkx1ymn10_s42501bl5799wh0000gn/T/chess-iphone-study-ruo4lyj9/build/ChessCompanion.app"
DEFAULT_SHA="43a02cdeed2143bec10fa06afd8d456efb76583ec6c806616a7a2f607edbbdb6"
DEFAULT_DEVICE="0CE608CB-28E6-5A15-9B27-AAE6A9FDFC4A"

APP="${CHESS_APP:-$DEFAULT_APP}"
EXPECTED_SHA="${CHESS_APP_SHA256:-$DEFAULT_SHA}"
DEVICE="${CHESS_DEVICE:-$DEFAULT_DEVICE}"
OUT="${CHESS_SIGNING_OUT:-${TMPDIR:-/tmp}/chess-signing-out}"
TEAM=""
IDENTITY=""

die() { echo "ERROR: $*" >&2; exit 1; }
say() { echo "== $*"; }

usage() {
  cat <<USAGE
Usage: $0 <preflight|provision|sign|install|launch> [options]
  --app PATH         prepared unsigned .app (env CHESS_APP)
  --sha256 HEX       expected executable SHA-256 (env CHESS_APP_SHA256)
  --device ID        CoreDevice id/name/UDID (env CHESS_DEVICE)
  --out DIR          output dir, must be OUTSIDE the git repo (env CHESS_SIGNING_OUT)
  --team TEAMID      10-character Apple team id (provision)
  --identity NAME    e.g. "Apple Development: you@example.com (ABCDE12345)" (sign)
USAGE
}

[ $# -ge 1 ] || { usage; exit 2; }
CMD="$1"; shift
while [ $# -gt 0 ]; do
  case "$1" in
    --app) [ $# -ge 2 ] || die "--app needs a value"; APP="$2"; shift 2 ;;
    --sha256) [ $# -ge 2 ] || die "--sha256 needs a value"; EXPECTED_SHA="$2"; shift 2 ;;
    --device) [ $# -ge 2 ] || die "--device needs a value"; DEVICE="$2"; shift 2 ;;
    --out) [ $# -ge 2 ] || die "--out needs a value"; OUT="$2"; shift 2 ;;
    --team) [ $# -ge 2 ] || die "--team needs a value"; TEAM="$2"; shift 2 ;;
    --identity) [ $# -ge 2 ] || die "--identity needs a value"; IDENTITY="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage; die "unknown option: $1" ;;
  esac
done

# Resolve a possibly-nonexistent path to a physical absolute path.
physical_path() {
  local p="$1" tail="" base
  case "$p" in /*) ;; *) p="$PWD/$p" ;; esac
  while [ ! -d "$p" ]; do
    base="$(basename "$p")"; tail="/$base$tail"; p="$(dirname "$p")"
  done
  echo "$(cd "$p" && pwd -P)$tail"
}

repo_root() {
  local r
  r="$(git -C "$HERE" rev-parse --show-toplevel 2>/dev/null || true)"
  [ -n "$r" ] || r="$HERE/../../.."
  (cd "$r" && pwd -P)
}

check_out_dir() {
  local root out
  case "/$OUT/" in */../*|*/./*) die "output dir must not contain '.' or '..' path segments: $OUT" ;; esac
  root="$(repo_root)"; out="$(physical_path "$OUT")"
  case "$out/" in
    "$root"/*) die "output dir $out is inside the git repo $root. Choose --out outside the repo." ;;
  esac
  OUT="$out"
}

exe_name() { /usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$1/Info.plist"; }
exe_hash() { shasum -a 256 "$1/$(exe_name "$1")" | awk '{print $1}'; }
identity_count() { security find-identity -v -p codesigning 2>/dev/null | awk '/valid identities found/ {print $1}'; }

SHELL_APP() { echo "$OUT/shell-build/Products/Debug-iphoneos/ProvisioningShell.app"; }

cmd_preflight() {
  local fail=0 n
  say "Code-signing identities"
  security find-identity -v -p codesigning || true
  n="$(identity_count || true)"; n="${n:-0}"
  echo "valid identities: $n"
  say "Device state"
  xcrun devicectl list devices || echo "(devicectl failed)"
  say "Prepared app"
  if [ ! -d "$APP" ]; then
    echo "MISSING: $APP"; fail=1
  else
    local got; got="$(exe_hash "$APP")"
    echo "app: $APP"; echo "executable sha256: $got"; echo "expected sha256:   $EXPECTED_SHA"
    if [ "$got" = "$EXPECTED_SHA" ]; then echo "hash: MATCH"; else echo "hash: MISMATCH"; fail=1; fi
    [ -e "$APP/_CodeSignature" ] && echo "note: app already has a _CodeSignature folder"
  fi
  if [ "$n" = "0" ]; then
    echo "NO SIGNING IDENTITY: Add your Apple ID in Xcode > Settings > Accounts first, then run 'provision'." >&2
    fail=1
  fi
  [ "$fail" = 0 ] || exit 1
  echo "preflight OK"
}

# Find the phone's hardware UDID (xcodebuild wants it); fall back to the given id.
device_udid() {
  local j="$OUT/device.json" u=""
  if xcrun devicectl list devices --json-output "$j" >/dev/null 2>&1 && [ -f "$j" ]; then
    u="$(python3 -I - "$j" "$DEVICE" <<'PY' 2>/dev/null || true
import json, sys
d = json.load(open(sys.argv[1])); want = sys.argv[2].lower()
for dev in d.get("result", {}).get("devices", []):
    ids = [dev.get("identifier", ""), dev.get("hardwareProperties", {}).get("udid", ""),
           dev.get("deviceProperties", {}).get("name", "")]
    if want in [i.lower() for i in ids if i]:
        print(dev.get("hardwareProperties", {}).get("udid", "")); break
PY
)"
  fi
  echo "${u:-$DEVICE}"
}

cmd_provision() {
  [ -n "$TEAM" ] || die "provision needs --team TEAMID (10 characters, see Xcode > Settings > Accounts > Team ID)"
  case "$TEAM" in [A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9]) ;; *) die "--team must be 10 uppercase letters/digits" ;; esac
  [ "$(identity_count || echo 0)" != "0" ] || echo "note: no signing identity yet; Xcode may create one now (needs your Apple ID in Xcode)."
  mkdir -p "$OUT"
  local udid; udid="$(device_udid)"
  say "Building provisioning shell for device $udid into $OUT/shell-build"
  local common=(-project "$PROJECT" -configuration Debug
    SYMROOT="$OUT/shell-build/Products" OBJROOT="$OUT/shell-build/obj"
    -allowProvisioningUpdates -allowProvisioningDeviceRegistration
    DEVELOPMENT_TEAM="$TEAM")
  # Attempt 1: scheme + the concrete phone, so Xcode registers the phone in the profile.
  if ! xcodebuild "${common[@]}" -scheme ProvisioningShell -destination "id=$udid" build > "$OUT/provision.log" 2>&1; then
    echo "Attempt 1 (scheme + device destination) failed; last lines:"; tail -12 "$OUT/provision.log"
    echo "Attempt 2: target build for the generic iOS SDK (the profile may then NOT include the phone)."
    if ! xcodebuild "${common[@]}" -target ProvisioningShell -sdk iphoneos build > "$OUT/provision2.log" 2>&1; then
      tail -30 "$OUT/provision2.log"; die "xcodebuild failed; logs: $OUT/provision.log and $OUT/provision2.log"
    fi
  fi
  tail -5 "$OUT/provision.log"
  local shell prof; shell="$(SHELL_APP)"
  prof="$shell/embedded.mobileprovision"
  [ -f "$prof" ] || die "no embedded.mobileprovision in $shell (signing probably did not happen; see $OUT/provision.log)"
  cp "$prof" "$OUT/profile.mobileprovision"
  security cms -D -i "$OUT/profile.mobileprovision" > "$OUT/profile.plist"
  say "Profile"
  for k in Name TeamIdentifier ExpirationDate; do
    echo "$k: $(/usr/libexec/PlistBuddy -c "Print :$k" "$OUT/profile.plist" 2>/dev/null | tr '\n' ' ')"
  done
  # Prefer the exact entitlements Xcode signed the shell with; fall back to the profile's.
  if codesign -d --entitlements :- "$shell" > "$OUT/entitlements.plist" 2>/dev/null && plutil -lint "$OUT/entitlements.plist" >/dev/null 2>&1; then
    echo "entitlements: taken from signed shell app"
  else
    /usr/libexec/PlistBuddy -x -c 'Print :Entitlements' "$OUT/profile.plist" > "$OUT/entitlements.plist" \
      || die "could not extract entitlements"
    echo "entitlements: taken from the profile"
  fi
  plutil -p "$OUT/entitlements.plist"
  echo "provision OK. Next: $0 sign --identity \"Apple Development: ...\" --out $OUT"
}

cmd_sign() {
  [ -n "$IDENTITY" ] || die "sign needs --identity \"Apple Development: ...\" (run: security find-identity -v -p codesigning)"
  [ -f "$OUT/profile.mobileprovision" ] && [ -f "$OUT/entitlements.plist" ] || die "run 'provision' first (missing profile/entitlements in $OUT)"
  [ -d "$APP" ] || die "prepared app not found: $APP"
  [ "$(exe_hash "$APP")" = "$EXPECTED_SHA" ] || die "prepared app executable hash does not match expected; refusing to sign"
  # Resolve the identity name to its certificate hash so the choice is unambiguous.
  local ids hash
  ids="$(security find-identity -v -p codesigning | grep -E '^ *[0-9]+\) [0-9A-F]{40} ' | grep -F "$IDENTITY" || true)"
  [ -n "$ids" ] || die "identity not found: $IDENTITY"
  [ "$(echo "$ids" | wc -l | tr -d ' ')" = 1 ] || die "identity name matches more than one certificate; be more specific"
  hash="$(echo "$ids" | awk '{print $2}')"
  echo "$hash" | grep -Eq '^[0-9A-F]{40}$' || die "could not resolve a certificate hash for: $IDENTITY"
  # Sanity check: is this certificate listed inside the profile? (warning only)
  if ! python3 -I - "$OUT/profile.plist" "$hash" <<'PY'
import plistlib, hashlib, sys
p = plistlib.load(open(sys.argv[1], "rb"))
hs = [hashlib.sha1(c).hexdigest().upper() for c in p.get("DeveloperCertificates", [])]
sys.exit(0 if sys.argv[2].upper() in hs else 1)
PY
  then die "this identity's certificate is not in the provisioning profile ($OUT/profile.plist); refusing to sign"; fi

  local dest="$OUT/ChessCompanion.app"
  [ ! -e "$dest" ] || rm -rf "$dest"   # only ever our own copy inside OUT (checked outside the repo)
  say "Copying prepared app to $dest"
  ditto "$APP" "$dest"
  [ "$(exe_hash "$dest")" = "$EXPECTED_SHA" ] || die "copied app executable hash does not match expected; refusing to sign"
  [ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$dest/Info.plist")" = "$BUNDLE_ID" ] || die "app bundle id is not $BUNDLE_ID; refusing to sign"
  rm -rf "$dest/_CodeSignature"
  cp "$OUT/profile.mobileprovision" "$dest/embedded.mobileprovision"
  # Nested code first (deepest first), then the app itself.
  local item
  while IFS= read -r item; do
    [ -n "$item" ] || continue
    say "Signing nested: ${item#$dest/}"
    codesign --force --sign "$hash" --timestamp=none "$item"
  done < <(find "$dest" -depth \( -name '*.framework' -o -name '*.dylib' -o -name '*.appex' -o -name '*.xpc' \) -print 2>/dev/null)
  say "Signing app"
  codesign --force --sign "$hash" --timestamp=none --entitlements "$OUT/entitlements.plist" "$dest"
  say "Verifying"
  codesign --verify --deep --strict --verbose=2 "$dest"
  echo "signed executable sha256: $(exe_hash "$dest")"
  echo "(differs from the unsigned hash by design: the signature is embedded in the binary)"
  echo "sign OK: $dest"
}

cmd_install() {
  local dest="$OUT/ChessCompanion.app"
  [ -d "$dest" ] || die "no signed app at $dest; run 'sign' first"
  codesign --verify --deep --strict "$dest" 2>/dev/null || die "signed app fails verification; run 'sign' again"
  say "Is $BUNDLE_ID already installed?"
  if xcrun devicectl device info apps --device "$DEVICE" 2>/dev/null | grep -F "$BUNDLE_ID"; then
    echo "yes: an existing copy is installed; install will replace it (app data is kept)."
  else
    echo "not currently installed (or the app list could not be read)."
  fi
  say "Installing"
  xcrun devicectl device install app --device "$DEVICE" "$dest"
  echo "install done. First launch: trust the developer in iPhone Settings > General > VPN & Device Management."
}

cmd_launch() {
  xcrun devicectl device process launch --device "$DEVICE" --terminate-existing "$BUNDLE_ID"
}

case "$CMD" in
  preflight|provision|sign|install|launch) check_out_dir; "cmd_$CMD" ;;
  -h|--help|help) usage ;;
  *) usage; die "unknown subcommand: $CMD" ;;
esac
