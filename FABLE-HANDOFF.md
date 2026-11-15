# Chess Companion: handoff for the next Fable orchestrator

Written November 15, 2026, 22:30 Madrid, at commit `832a578` on `main`. You are a Fable session
that plans, assigns, integrates and reviews; Opus workers do the focused build work. Read this
file first, then `CLAUDE.md` and `AGENTS.md` (binding rules). `HANDOFF.md` is the long
append-only evidence log: read only its last three sections unless you need history.

## The product in three sentences

A private chess practice companion whose whole runtime is on the iPhone: recognise the board,
have a person review the position, run local rules and Stockfish, give the move as text (speech
later). The eventual camera is Alex's Ray-Ban Meta Gen 1 glasses; Alex has no physical board, so
everything so far uses computer-generated board images. The safety rule is the product: advice
exists only for a position a person fully reviewed, any change, uncertainty or interruption
revokes it, and a late reply can never bring it back.

## Who Alex is and how to talk to him

A smart UCLA student with no coding background. Plain language, define a term once, frame
decisions as outcomes, teach through the work. Raise risks he would not think of (secrets,
data loss, cost, privacy) before building. Never claim something works without showing the check.

## Where everything is

| What | Where |
| --- | --- |
| Project (git, `main`, 4 commits, no remote) | `/Users/alexmunzon/chess-practice` |
| Original Codex checkout, untouched backup | `/Users/alexmunzon/Documents/Codex/2026-10-30/task-3/chess-practice` |
| Old Codex evidence, read-only | `/Users/alexmunzon/Documents/Codex/` |
| All build outputs and evidence since the move | `/Users/alexmunzon/chess-builds/` (one dated folder per packet) |
| Latest phone evidence | `/Users/alexmunzon/chess-builds/perf-integration-2026-11-15/phone-run2/` |
| Latest unsigned device builds | `/Users/alexmunzon/chess-builds/perf-integration-2026-11-15/device-normal` and `device-selftest` |
| Provisioning profile and entitlements (no private key) | `/Users/alexmunzon/chess-builds/iphone-2026-11-15/signing/` |
| Private status page (artifact) | https://claude.ai/artifact/P2yY3nAJ9BPch3rL1b2Aho |

## Verified state

Check command: `npm test` → 204 tests, 200 pass, 0 fail, 4 opt-in skipped. It opens 127.0.0.1
listeners, so it fails inside a command sandbox (`listen EPERM`); that is the sandbox.

| Area | State | Evidence type |
| --- | --- | --- |
| Rules + Stockfish in a local WebKit runtime (15 assets) | Working | Real iPhone 17 / iOS 27.2 |
| Study mode (one position, five explicit review ticks) | 12 checks pass | Real phone, scripted review |
| Replay mode (14-frame game, one review, legal tracking, text advice) | 6 checks pass | Real phone, scripted review |
| Recognition speed on phone | 39–122 ms per image (was about 1.5 s; cause was a missing `-O`) | Real phone |
| Engine search on phone | 1.5–2.0 s, one 3.5 s outlier | Real phone |
| Mock safety suites | Study 28/28, Replay 21/21, Integration 18/18, ReplayTracker 94/94 | Mac, mocked |
| Special-move image game (en passant, promotion, both castlings) | Tracked correctly, not bundled in the app | Mac |
| Screen-board detection, occupancy pixel classifier, occupancy move inference | Three separate prototypes, not joined | Simulated images only |

The phone has the optimized **normal** build (no self-test code) with Replay mode. Nobody has
used the app by hand. The free signing profile expires **November 22, 2026, 15:22 Madrid**.

Keep evidence types separate in everything you write: mock, Mac, Simulator, real phone,
scripted review, human review. Synthetic accuracy is not camera or physical-board accuracy.

## How to run things

- **Build the app:** `python3 -B native/ChessCompanionApp/prepare_app.py` (there is no Xcode
  project for the app; it calls `swiftc` directly). `--simulator`, `--self-test`,
  `--fixture-directory`, `--replay-directory`. Exact working invocations are in the build reports
  under `/Users/alexmunzon/chess-builds/perf-integration-2026-11-15/`. Rebuild the runtime bundle
  first with `node scripts/build-device-runtime.mjs --out <dir>` whenever `src/core` or
  `native/ChessCompanionRuntime/runtime.js` changes; `prepare_app.py` pins every asset.
- **Self-test mode:** compiled only with `--self-test`, runs only with launch argument
  `--chess-self-test`, writes `Documents/selftest-report.json`. Review in it is scripted and
  labelled so. It is the way to test on the phone without anyone tapping.
- **Phone, one command:** `native/ChessCompanionApp/signing/phone_selftest.sh` signs, installs,
  runs, fetches and summarises the report, then restores the normal app. Exit 3 means the phone
  screen was asleep: ask Alex to wake and unlock it, then re-run. Find the signing identity name
  with `security find-identity -v -p codesigning`; never print or export keys.
- **Renew signing:** `native/ChessCompanionApp/signing/renew_profile.sh` (dry-tested only).
- **Simulator:** iPhone 17, UDID `746F2CEB-102D-4CFC-8D11-A5924705537F`, bundle
  `local.chesscompanion.offlinestudy.simulator`, ad hoc signing. Engine deadlines fail when the
  Mac is heavily loaded; check `uptime` before trusting a Simulator failure.

## Orchestration pattern that worked

- Alex's standing instruction: several workers in parallel, **Opus 5.5 at medium effort**.
- Every brief has five parts: (1) goal and limits, (2) "done" as pass/fail checks, (3) small
  tasks, (4) do the work, run the checks, fix inside scope, (5) report results, check output and
  what was not verified. Workers see only the brief: name exact files they own, exact files they
  must not touch, the output folder, and the hard limits.
- Give each worker **non-overlapping files**. `native/ChessCompanionApp/` and the runtime bundle
  are the contention points: one writer at a time there. Anything that changes `src/core` or
  `runtime.js` invalidates app builds until the bundle is rebuilt and re-pinned.
- The tree is now committed, so **git worktrees work** for isolation. Earlier today they did not,
  which is why workers shared the tree with strict file ownership. A worker that must not disturb
  an in-progress build can also deliver a patch file instead of editing the repo.
- **Phone actions stay with the orchestrator.** Workers never run `devicectl` install or launch,
  never sign with the Apple Development identity, never commit.
- Verify before repeating a worker's claim: re-run the key check, or say "agent-reported".
- Ten Opus workers at once made Simulator engine tests flaky through CPU load. Keep heavy
  Simulator runs to a quiet machine.
- Network drops kill workers mid-run; resume them by message, they keep their context.

## Boundaries (do not cross without Alex's own words)

- **Approved:** Simulator testing; signing, installing and opening the private app on his phone
  for text-only offline testing with the existing identity.
- **Not approved:** camera, microphone, Bluetooth, glasses capture, audible speech; new accounts,
  spending, credential entry, permanent settings changes; any dataset or model download.
- **Git:** commit only when Alex asks. Never push, open a PR or create a remote without his
  explicit words for that action. `HANDOFF.md` and `docs/PHONE_INSTALLATION.md` contain his Apple
  ID email and team ID: scrub them before anything leaves this Mac.
- Generated binaries, engine assets and media stay outside the repo.

## Next packets, in priority order

1. **Join the recognition prototypes** into one offline "board on a screen" pipeline on simulated
   scenes: `native/ScreenBoardVision` (corners) → `scripts/recognition/occupancy_classifier.py`
   (empty / white / black from colours learned at the confirmed start) →
   `src/core/occupancy-move-inference.js` (the one legal move, or abstain). Measure wrong accepted
   moves and abstentions end to end. Known gaps: two misread squares can fool move inference
   (unmeasured); promotions are ambiguous by design; the classifier needed a post-freeze fix for
   heavy blur; simulated scenes have no lens distortion or moiré. See
   `docs/RECOGNITION_RESEARCH.md`, `OCCUPANCY_CLASSIFIER.md`, `OCCUPANCY_INFERENCE.md`.
2. **Bundle the special-move game** into Replay (`docs/SPECIAL_GAME_SEQUENCE.md`) and run it on
   the phone, including a promotion prompt path.
3. **Mock Device Kit capture path** in the Simulator (Meta's simulated glasses fed by a video
   file): no glasses or approval needed. See `docs/GLASSES_SDK_RESEARCH.md`. Hard problems it
   will surface: frame timestamps are on the glasses' clock with no documented mapping to phone
   time (live advice stays blocked until frame age is bounded), and an open Meta issue where
   camera streaming pauses phone audio.
4. **Engine budget:** recognition is now about 0.1 s, the engine 1.5–2 s. Decide search time
   versus strength, and investigate the occasional slow first search.
5. **Housekeeping:** fold today's results into `docs/PLAN.md` and `docs/VERIFICATION.md` (both
   stale); a real-WebKit test of the engine-host-died path; refresh the status page.

## Decisions waiting on Alex

- Try the Replay screen by hand on the phone (the only missing human evidence).
- Camera and glasses approval for the first real screen-board capture experiment.
- Whether to download the non-commercial ChessReD dataset (about 29 GB) for physical boards.
- A private off-machine backup (needs a GitHub account and repo name from him, and the scrub).
- Sharing the app with anyone needs the licence steps in `docs/LICENCE_AUDIT.md` first.
