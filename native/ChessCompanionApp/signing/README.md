# Signing and install kit (private, not committed work product)

Goal: get the already-built unsigned Chess Companion app onto your iPhone using a free Apple "Personal Team". Nothing here runs by itself. Each step is a separate command you run on purpose.

Everything is written to an output folder outside the repo (default `$TMPDIR/chess-signing-out`). The scripts refuse to run if `--out` is inside the git repo. The original prepared app is never modified; signing works on a copy.

## One-time: add your Apple ID
Xcode > Settings > Accounts > + > Apple ID. Find your Team ID (10 characters) there or at developer.apple.com > Membership. A free account shows as "Personal Team".

## Commands, in order (run from this folder)
```sh
./sign_and_install.sh preflight
```
Prints signing identities, whether the phone is connected, and checks the app file hash against the expected one. It fails with "Add your Apple ID in Xcode..." until an identity exists.

```sh
./sign_and_install.sh provision --team YOURTEAMID
```
Builds the tiny "ProvisioningShell" project (same bundle ID `local.chesscompanion.offlinestudy`) with `-allowProvisioningUpdates`. This makes Xcode create your development certificate and a provisioning profile, and register the phone and bundle ID with your Apple ID. It then saves the profile and the entitlements (the permission list Apple approved) in the output folder. If a certificate was just created, run `preflight` again to see its name.

```sh
./sign_and_install.sh sign --identity "Apple Development: you@example.com (ABCDE12345)"
```
Copies the app, embeds the profile, signs it, and runs `codesign --verify --deep --strict`. Prints the signed hash (it differs from the unsigned one, which is normal).

```sh
./sign_and_install.sh install
./sign_and_install.sh launch
```
`install` reports whether the app is already on the phone, then installs it. `launch` starts it.

Options for all commands: `--out DIR`, `--app PATH`, `--sha256 HEX`, `--device ID` (or env `CHESS_SIGNING_OUT`, `CHESS_APP`, `CHESS_APP_SHA256`, `CHESS_DEVICE`). Use the same `--out` for every step if you change it.

## Known limits
- Free Personal Team profiles expire after 7 days. The app stops opening; re-run `provision`, `sign`, `install`.
- First launch: on the iPhone go to Settings > General > VPN & Device Management, tap your Apple ID, Trust.
- This registers your phone and the bundle ID with your Apple ID, and a free account allows only a few app IDs per week.
- The scripts never read or print private keys and never ask for passwords. macOS may show its own keychain prompt when `codesign` uses your key; that prompt is between you and macOS.
- `provision` tries the phone as a build destination first. Xcode 26.3 may list the phone as ineligible (the phone runs a newer iOS than this Xcode ships support for). The script then falls back to a generic build, whose profile might not include the phone; if install says the profile does not include the device, update Xcode or use Xcode itself to run the shell once on the phone.

## One-command phone self-test and profile renewal

Two wrapper scripts call the kit above (they never re-implement signing) so a phone check is one command. Both refuse rather than guess, never delete anything on the phone, and never print keys.

**Run the self-test on the phone** (wake and unlock the phone first, and keep it awake):
```sh
./phone_selftest.sh --app /path/to/selftest/ChessCompanion.app --sha256 <unsigned executable hash> \
  --provisioning /path/to/signing-folder --identity "Apple Development: ..." --out /new/folder/outside/repo \
  [--restore-app /path/to/normal/ChessCompanion.app --restore-sha256 <hash>] [--timeout 180] [--device ID]
```
It checks first (signing identity exists, phone connected and in the profile, profile not expired, app hash and bundle id match, the app really contains the self-test), then signs, installs, launches with `--chess-self-test`, and waits for a report that is newer than this run (an old report left on the phone is ignored). It saves the report, its SHA-256, the launch log and a summary in `--out`. With `--restore-app` it then signs and installs the normal app, after checking the signed copy has no self-test code. Add `--dry-run` to see every command without running any, or `--only preflight|sign|install|run|restore` to run one step.

Exit codes: `0` all checks passed; `2` finished but a check failed; `3` the app was interrupted (screen slept, locked or went to the background): wake and unlock the phone, then re-run; `4` the app did not launch; `5` no fresh finished report before the timeout; `1` anything else, including a refused check.

`./summarize_selftest.py report.json` prints the same verdict for any saved report (`--json` for machine output).

**Renew the profile.** The free profile lasts 7 days (current one ends 2026-11-22). After that the app will not open until it is re-signed with a new profile and reinstalled:
```sh
./renew_profile.sh --team YOURTEAMID --current /path/to/old/signing-folder --out /new/folder/outside/repo
```
It refuses while the old profile still has more than 24 hours left (`--force` overrides), runs the kit's `provision` step, and prints the new expiry. Then run `phone_selftest.sh` with `--provisioning` pointing at the new folder.
