# Chess Companion plan

Updated November 15, 2026, 23:00 Madrid. This replaces the November 11–13 plan (see "History of
the plan" at the end). Exact numbers and the files that prove them are in
[VERIFICATION.md](VERIFICATION.md), section "Current state (2026-11-15)". The orchestrator's
handoff is `FABLE-HANDOFF.md`; the append-only evidence log is `HANDOFF.md`.

## Product goal

A private chess practice companion whose whole runtime runs on Alex's iPhone 17 (iOS 27.2): it
recognises the board, a person reviews the position, and local chess rules plus the Stockfish
engine give a move as text (speech later). The eventual camera is Alex's Ray-Ban Meta Gen 1
glasses, but Alex has no physical board, so all work so far uses computer-generated board images.
It is for private practice that everyone involved agrees to, not for covert use in real games.

## The safety rule (this is the product)

Advice exists only for a position a person has fully reviewed: pieces, side to move, castling,
en passant and move counters. Any change, uncertain square or interruption revokes the advice, and
a late reply from the engine can never bring it back. A board picture alone cannot tell whose turn
it is, castling rights, en passant or repetition history, so the review step is never skipped.
Engine output is strong bounded analysis, never "perfect play".

## How to read evidence labels

Every status names its evidence type, kept separate:
**mock** (Swift or JS code with a fake engine/transport), **Mac** (real code run on the Mac),
**Simulator** (iPhone Simulator on the Mac), **real phone** (Alex's iPhone 17), **scripted review**
(the self-test ticks the review boxes automatically), **human review** (a person did it).
"Synthetic" means computer-drawn board images. Synthetic accuracy is never camera or
physical-board accuracy.

## What works today

| Area | State | Evidence type | Where the evidence lives |
| --- | --- | --- | --- |
| App installed on the phone, opens | Installed Nov 15; Alex saw it open and stay open | Real phone, human observation | `chess-builds/iphone-2026-11-15/`, `docs/PHONE_INSTALLATION.md` |
| Rules + Stockfish inside the app (local WebKit runtime, 15 bundled files) | Working, offline | Real phone | `chess-builds/perf-integration-2026-11-15/phone-run2/` |
| Study mode: one picture, five review ticks, text move | 12 self-test checks pass | Real phone, scripted review | same `phone-run2/` |
| Replay mode: 14-frame game, one review, legal move tracking, text advice | 6 self-test checks pass (18/18 in total with Study) | Real phone, scripted review | same `phone-run2/` |
| Safety behaviour (obstruction, untick, reset, background, in-flight switch, step during analysis) | All pass | Real phone, scripted review; also mock | `phone-run2/`, `perf-integration-2026-11-15/mocks/` |
| Recognition speed | 39–122 ms per picture (was about 1.5 s; cause: app compiled without `-O`) | Real phone | `phone-run2/summary.json`, `docs/RECOGNIZER_PERFORMANCE.md` |
| Engine search time | 1.5–2.0 s, one 3.5 s search | Real phone | `phone-run2/selftest-report.json` |
| Mock safety suites | Study 28/28, Replay 21/21, Integration 18/18, ReplayTracker 94/94 | Mock (Mac) | `perf-integration-2026-11-15/mocks/*-run.txt` |
| Node test suite (`npm test`) | 204 tests, 200 pass, 0 fail, 4 opt-in skipped | Mac | `perf-integration-2026-11-15/npm-test.txt` |
| Special-move image game (en passant, promotion, both castlings) | Tracked to the exact position on all 26 positions; not yet in the app | Mac, synthetic, scripted review | `docs/SPECIAL_GAME_SEQUENCE.md`, `chess-builds/special-game-2026-11-15/` |
| Screen-board corner finder (no markers) | Found the board in 99.3–99.5% of 360 simulated scenes, 0 false accepts | Mac, synthetic | `native/ScreenBoardVision/README.md`, `chess-builds/screen-board-2026-11-15/reports/` |
| Occupancy classifier (empty / white / black per square) | 0 confident errors on dev and held-out synthetic frames after a post-freeze blur fix | Mac, synthetic | `docs/OCCUPANCY_CLASSIFIER.md`, `chess-builds/occupancy-classifier-2026-11-15/` |
| Move inference from occupancy | 0 wrong moves in 159,235 random plies with perfect readings | Mac, logic only (no images) | `docs/OCCUPANCY_INFERENCE.md`, `chess-builds/occupancy-2026-11-15/` |
| Phone test in one command (`signing/phone_selftest.sh`) | Used for real three times (two full passes, one interrupted because the phone was asleep) | Real phone | `replay-mode-2026-11-15/phone-run1/`, `perf-integration-2026-11-15/phone-run1..2/` |

The phone now has the optimized **normal** build (no self-test code) with Replay mode.
**Nobody has used either mode by hand.** The three recognition prototypes are separate and none
is in the app; the app still recognises with the older template recogniser on marked synthetic
images.

## Signing deadline

The free Apple signing profile expires **November 22, 2026, 15:22 Madrid**. After that the app on
the phone will not open until it is re-signed and reinstalled: run
`native/ChessCompanionApp/signing/renew_profile.sh` (dry-tested only, never used for real), then
`sign_and_install.sh` with the configured Apple Development identity. A free account must repeat
this every 7 days.

## In progress, no results yet

Started by other workers on the evening of November 15. Nothing below is verified; claim nothing.

- Joining the three recognition prototypes into one offline "board on a screen" pipeline.
- Measuring how often two misread squares fool move inference.
- Bundling the special-move game into Replay mode.
- Engine search-budget study (time versus strength, and the slow first search).
- Mock Device Kit feasibility note (Meta's simulated glasses in the Simulator).

## Next packets, in priority order (same order as `FABLE-HANDOFF.md`)

1. **Join the recognition prototypes** on simulated scenes: corners (`native/ScreenBoardVision`) →
   occupancy classifier (`scripts/recognition/occupancy_classifier.py`) → move inference
   (`src/core/occupancy-move-inference.js`). Measure wrong accepted moves and abstentions end to
   end. *In progress.*
2. **Bundle the special-move game** into Replay and run it on the phone, including the promotion
   prompt. *In progress.*
3. **Mock Device Kit capture path** in the Simulator: a video file fed through Meta's simulated
   glasses. No glasses or approval needed. *Feasibility note in progress.*
4. **Engine budget:** recognition is about 0.1 s, the engine 1.5–2 s; decide search time versus
   strength. *Study in progress.*
5. **Housekeeping:** this refresh of PLAN and VERIFICATION; a real-WebKit test of the path where
   the engine host dies (`onClose`, so far mock only); refresh the private status page.

## Decisions waiting on Alex

- Try the Replay screen by hand on the phone. This is the only missing human evidence.
- Camera and glasses approval for the first real screen-board capture experiment.
- Whether to download the non-commercial ChessReD dataset (about 29 GB) for physical boards.
- A private off-machine backup (needs a GitHub account and repo name from Alex, plus scrubbing his
  Apple ID details from `HANDOFF.md` and `docs/PHONE_INSTALLATION.md` first).
- Sharing the app with anyone first needs the licence steps in `docs/LICENCE_AUDIT.md` (an
  engine "source pack", the app's own source, visible notices). Private use needs nothing.

## Boundaries

**Approved:** Simulator testing; inspecting the connected iPhone and existing signing setup;
signing, installing and opening the private offline app on the phone for text-only testing with
the configured Apple Development identity.

**Not approved:** camera, microphone, Bluetooth, glasses capture, audible speech; new accounts,
spending, credential entry, permanent settings changes; any dataset or model download; push,
deploy, distribution or a remote. Commit only when Alex asks. Generated binaries, engine files and
media stay outside the repo (in `/Users/alexmunzon/chess-builds/`).

## Known limits

- **No human use yet.** All phone review so far is the scripted self-test fixture.
- **Synthetic only.** Every recognition number comes from computer-drawn boards: one piece style,
  flat images, no lens distortion, moiré, motion blur or real lighting. No camera, glasses or
  physical-board accuracy exists. Earlier real-photo and real-video recognisers failed their gates
  and stay disabled (see VERIFICATION.md history).
- **Recognition prototypes are not joined** and not in the app; the screen-board finder is iOS
  typecheck only and has never run on a phone.
- **Move inference** treats promotions as ambiguous by design (ask which piece). One misread
  square is always rejected; two misreads can fool it, and how often is not yet measured. It needs
  a correct reviewed start; one wrong accepted move corrupts the rest of the game.
- **Glasses timing.** Meta's SDK stamps frames with the glasses' clock and documents no mapping to
  phone time, so frame age cannot be bounded yet; live advice stays blocked until it can. An open
  Meta issue reports that camera streaming pauses phone audio (seen on Gen 2; Gen 1 untested).
- **Engine.** Bounded search: strong, not perfect. Moves vary between runs. One slow 3.5 s search
  seen on the phone.
- **Not exercised for real:** the `onClose` path when the engine host dies; `renew_profile.sh`.
- **History.** An imported position has no repetition history, so draw-by-repetition claims are
  not made.

## History of the plan

- **Nov 10:** project pivoted from blackjack to chess; six phases planned (rules core, review UI,
  calibration, pieces and game state, capture and glasses, output and release).
- **Nov 11:** Alex has no physical board, so work switched to the synthetic simulation track
  (`docs/SIMULATION_PLAN.md`); real-photo and real-video recognisers failed their gates.
- **Nov 12–13:** native modules, Mac WebKit engine, Simulator app, private unsigned phone build.
- **Nov 15:** signed and installed on the phone; self-test mode; Replay mode; `-O` speed fix;
  three recognition prototypes; research on recognition, glasses SDK and licences.

The full earlier text of this plan is in git: `git show a13ed1c:docs/PLAN.md`.
