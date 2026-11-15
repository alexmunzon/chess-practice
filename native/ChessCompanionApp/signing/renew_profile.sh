#!/usr/bin/env bash
# Renew the free 7-day provisioning profile for the private Chess Companion app.
# Wraps "sign_and_install.sh provision" (does not reimplement it) and prints the new expiry.
# Refuses while the current profile still has more than 24 h left, unless --force.
# Needs network (Xcode talks to Apple). Never reads/prints private keys, never asks for passwords.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
KIT="$HERE/sign_and_install.sh"
BUNDLE_ID="local.chesscompanion.offlinestudy"
TEAM=""; OUT=""; CURRENT=""; DEVICE=""; FORCE=0; DRY=0

die() { echo "ERROR: $*" >&2; exit 1; }
usage() {
  cat <<USAGE
Usage: $0 --team TEAMID --out NEW_DIR [--current OLD_PROVISIONING_DIR] [--device ID] [--force] [--dry-run]
  --team     10-character Apple team id (Xcode > Settings > Accounts)
  --out      new folder OUTSIDE the git repo; receives profile.mobileprovision, profile.plist, entitlements.plist
  --current  folder (or profile.plist) of the profile in use now; used for the 24 h check
  --force    renew even if the current profile has more than 24 h left (or --current is not given)
  --dry-run  check everything, print the provision command, run nothing
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --team|--out|--current|--device)
      [ $# -ge 2 ] || die "$1 needs a value"
      case "$1" in --team) TEAM="$2" ;; --out) OUT="$2" ;; --current) CURRENT="$2" ;; --device) DEVICE="$2" ;; esac
      shift 2 ;;
    --force) FORCE=1; shift ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "unknown option: $1" ;;
  esac
done

[ -n "$TEAM" ] && [ -n "$OUT" ] || { usage >&2; die "--team and --out are required"; }
printf '%s' "$TEAM" | grep -Eq '^[A-Z0-9]{10}$' || die "--team must be 10 uppercase letters/digits"
[ -x "$KIT" ] || die "signing kit not found: $KIT"

physical_path() {
  local p="$1" tail="" base
  case "$p" in /*) ;; *) p="$PWD/$p" ;; esac
  while [ ! -d "$p" ]; do base="$(basename "$p")"; tail="/$base$tail"; p="$(dirname "$p")"; done
  echo "$(cd "$p" && pwd -P)$tail"
}
ROOT="$(r="$(git -C "$HERE" rev-parse --show-toplevel 2>/dev/null || true)"; [ -n "$r" ] || r="$HERE/../../.."; cd "$r" && pwd -P)"
OUT="$(physical_path "$OUT")"
case "$OUT/" in "$ROOT"/*) die "--out $OUT is inside the git repo $ROOT. Choose a new folder outside the repo." ;; esac
[ ! -e "$OUT" ] || die "--out $OUT already exists; give a NEW folder so the old profile is never overwritten"

profile_info() { # $1 profile.plist -> "expires=... hours_left=... appid=... devices=..."
  python3 -I - "$1" <<'PY'
import plistlib, sys, datetime as dt
p = plistlib.load(open(sys.argv[1], "rb"))
exp = p["ExpirationDate"]
if exp.tzinfo is None: exp = exp.replace(tzinfo=dt.timezone.utc)
left = (exp - dt.datetime.now(dt.timezone.utc)).total_seconds()
print("expires=%s" % exp.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
print("hours_left=%d" % int(left // 3600))
print("seconds_left=%d" % int(left))
print("team=%s" % (p.get("TeamIdentifier") or [""])[0])
print("appid=%s" % p.get("Entitlements", {}).get("application-identifier", ""))
print("devices=%s" % ",".join(p.get("ProvisionedDevices", [])))
PY
}
field() { printf '%s\n' "$1" | awk -F= -v k="$2" '$1==k {sub(/^[^=]*=/, ""); print; exit}'; }

echo "== Current profile"
if [ -n "$CURRENT" ]; then
  [ -d "$CURRENT" ] && CURRENT="$CURRENT/profile.plist"
  [ -f "$CURRENT" ] || die "current profile not found: $CURRENT"
  INFO="$(profile_info "$CURRENT")"
  echo "current: $CURRENT"
  echo "team $(field "$INFO" team), expires $(field "$INFO" expires) ($(field "$INFO" hours_left) h left)"
  [ "$(field "$INFO" team)" = "$TEAM" ] || echo "WARNING: current profile team $(field "$INFO" team) differs from --team $TEAM"
  if [ "$(field "$INFO" seconds_left)" -gt 86400 ] && [ "$FORCE" = 0 ]; then
    die "current profile still has more than 24 h left; nothing to renew. Use --force to renew anyway (a free account allows only a few app IDs per week)."
  fi
elif [ "$FORCE" = 0 ]; then
  die "pass --current OLD_PROVISIONING_DIR so the 24 h check can run, or --force"
else
  echo "(no --current given; --force set)"
fi

CMD=("$KIT" provision --team "$TEAM" --out "$OUT")
[ -z "$DEVICE" ] || CMD=("${CMD[@]}" --device "$DEVICE")
echo "== Provision (Xcode contacts Apple; your Apple ID must already be in Xcode > Settings > Accounts)"
if [ "$DRY" = 1 ]; then
  printf '[dry-run]'; printf ' %q' "${CMD[@]}"; echo
  echo "[dry-run] then print the new expiry from $OUT/profile.plist and check app id and device list"
  echo "dry run complete: nothing was provisioned."
  exit 0
fi
printf '+'; printf ' %q' "${CMD[@]}"; echo
"${CMD[@]}"

[ -f "$OUT/profile.plist" ] && [ -f "$OUT/profile.mobileprovision" ] && [ -f "$OUT/entitlements.plist" ] \
  || die "provision finished but $OUT is missing profile files"
NEW="$(profile_info "$OUT/profile.plist")"
echo "== New profile"
echo "NEW EXPIRY: $(field "$NEW" expires) ($(field "$NEW" hours_left) h from now)"
[ "$(field "$NEW" appid)" = "$TEAM.$BUNDLE_ID" ] || echo "WARNING: new profile app id is $(field "$NEW" appid), expected $TEAM.$BUNDLE_ID"
echo "devices in profile: $(field "$NEW" devices)"
[ -n "$(field "$NEW" devices)" ] || echo "WARNING: the new profile lists no devices; the phone will refuse the install."
echo "Next: re-sign and reinstall with phone_selftest.sh (or sign_and_install.sh) using --provisioning $OUT"
