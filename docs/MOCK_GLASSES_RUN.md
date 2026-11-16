# Mock-glasses Simulator run (Phases 3-4 of MOCK_DEVICE_KIT_PLAN.md, 2026-11-15/16)

A Simulator-only test copy links Meta's Mock Device Kit (SDK 1.0.1), streams the project's own test video
through simulated Ray-Ban Meta glasses and feeds the existing capture path. **Plumbing and measurements only:
every glasses frame stays `.unknownDAT`; no engine or speech permit is possible.** Outputs:
`/Users/alexmunzon/chess-builds/mock-glasses-2026-11-15/phase3/` (builds) and `phase4/` (runs).

## Build and run
```sh
P=/Users/alexmunzon/chess-builds/mock-glasses-2026-11-15
python3 -B native/ChessCompanionApp/prepare_app.py --simulator --out $P/phase3/mock <usual 5 inputs> \
  --mock-glasses $P/phase1/frameworks --mock-glasses-video $P/phase2/replay-14.mp4
xcrun simctl install 746F2CEB-102D-4CFC-8D11-A5924705537F $P/phase3/mock/ChessCompanion.app
python3 -B $P/phase4b/run_watch.py <label> 270 local.chesscompanion.offlinestudy.mockglasses ChessCompanion -- --mock-glasses
```
- `--mock-glasses` without `--simulator` exits 2. Framework binaries and the video are SHA-256 pinned (build refuses
  a mismatch; the app re-checks the video). Bundle id `local.chesscompanion.offlinestudy.mockglasses`; the normal
  Simulator app is untouched. Frameworks are embedded and ad hoc signed; simulated keychain entitlements go only in
  an `__entitlements` section (as Xcode does for Simulator builds); without them `Wearables.configure()` fails
  with `internalError`, and putting them in the signature makes the Simulator refuse to launch.
- Info.plist: only the keys MWDATCore validates, `MetaAppID "0"`, no ClientToken/TeamID, Analytics and
  CrashReporting `OptOut = true`, no camera or microphone usage keys.
- Without `--mock-glasses` the copy behaves as the normal app (Replay picker present), makes no SDK call (no
  CoreBluetooth line in its log) and logs "launch argument --mock-glasses absent" (`phase4/17-no-argument`).
- Entry hook: one same-line edit in `ChessCompanionApp.swift` (`#if COMPANION_SELFTEST || COMPANION_MOCK_GLASSES`
  before `.modifier(SelfTestHook(...))`); the mock file supplies `SelfTestHook` (SelfTest.swift is never in that
  build). Line numbers are unchanged; an earlier 3-line hook changed the normal binaries (line numbers are compiled in).
- The video is kept out of `app-assets.json` (StudyResources rejects unknown assets); the app checks its own pin.

## Call order that worked (runs 15-full, 18-full)
`configure` -> `MockDeviceKit.enable(config: granted)` -> `pairGlasses(.rayBanMeta)` -> `powerOn` -> `unfold` ->
`don` -> `setCameraFeed(fileURL:)` -> `createSession(SpecificDeviceSelector)` -> `start` (state `started` at once)
-> `addCamera(raw, high, 30)` -> listen -> `stream.start` (`waitingForDevice` -> `starting` -> `streaming` ~1 s).
Matches the probe README. Registration: `unavailable` after configure, `registered` after enable; no account asked.

## Measured (mock only)
- Run 15-full (load ~20): 1762 frames; 720x1280, `420v` (biplanar 4:2:0 video range), sample duration not set;
  30.1 fps steady. Run 18-full (final build, load ~65): 1295 frames, 30.2 fps, same format and behaviour.
- PTS timescale 1,000,000; starts at **0 when a stream starts**, advances at 1.0000 s per receipt second,
  strictly monotonic, **no reset when the 30 s file loops** (reached 48.8 s); a new session/stream restarts at 0.
  So PTS is a per-stream mock clock, not the file timeline and not a wall clock.
- Frame-index code: 1762/1762 (18-full: 1295/1295) decoded in Swift, 0 abstained; 1734 (1275) equal the source
  index of slot `floor((PTS mod 30) / 2)`, the rest all within 70 ms of a 2 s slot boundary. Python reader on 60
  dumped PNGs per run: 60/60 decoded and equal to the Swift reading.
- doff: stream keeps streaming. fold and power-off: stream and session stop; the inverse action alone does not
  resume; a new session and stream are needed. Permission set to denied mid-stream: frames keep coming; denied
  before start: stream never delivers. The device-state listener reported no don/hinge change.

## Safety assertions (in `Documents/mock-glasses-report.json`; round two: `phase4b/full-run`)
Pass: `.unknownDAT` for every frame that reached the coordinator (100 recognizer frames, 189 distinct polled;
the 1749 measurement-stream frames never enter it); no permit possible (engine and speech-text stubs called 0
times: the only place a permit is made); no recommendation in a 50 ms poll; 0 speech requests; no analysis.
With stop acknowledged, complete proposal, full review and speech on, analysis was refused `unknownCaptureAge`.
Negative controls: each of the six checks turns false on a mutated copy. Revoke: fold and power-off pass;
**doff and mid-stream permission denial FAIL** (the mock keeps streaming; no review existed, so the refusal was
`incompleteReview`). A review cannot outlive a running stream, and restarting a stopped stream on the same
camera is refused by the mock, so "unknown frame age" is reachable only with the stream stopped.

## Network and dialogs (round two, `phase4b/run_watch.py`)
Instruments: lsof (0.2 s), nettop (1 s), system-wide log for Meta names/endpoint paths, mDNSResponder, nsurlsessiond,
system-wide lines naming the bundle (network-extension flow records). Proof app (3 runs): a held loopback TCP
connection was seen by lsof and nettop 3/3; a sub-millisecond connect-close was missed 0/3; a fresh `.invalid`
lookup was attributed to the app by mDNSResponder 3/3 (name hashed) and named in a flow record 2/3 (not when
cached). Full run: 0 sockets, 0 DNS queries from the app, 0 flow records, 0 Meta lines, 0 nsurlsessiond lines for
the bundle; Library holds no queued analytics or crash file. No system dialog in any screenshot. `configure()`
creates a CoreBluetooth manager (Simulator XPC invalid, no prompt).
## Not verified
Real glasses, radio latency, glasses clock semantics (#347), phone Bluetooth, Developer Mode, Gen 1, audio
pause. Mock timing says nothing about real frame age. A connection shorter than the polls, from a process
other than the app/mDNSResponder/nsurlsessiond, cannot be ruled out.
