# Chess Companion plan

Updated November 16, 2026, about 05:45 Madrid (the handoff time), after the overnight session. The
last commit is still checkpoint `46ce560` (6 commits, no remote); everything since is uncommitted.
This replaces the November 11–13 plan (see "History of the plan" at the end). Exact
numbers and the files that prove them are in [VERIFICATION.md](VERIFICATION.md), section
"Current state (2026-11-16)". The orchestrator's handoff is `FABLE-HANDOFF.md`; the append-only
evidence log is `HANDOFF.md`. Two reader and corner-finder fix rounds were still running at that
time; their numbers here are not final.

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
**mock** (code run with a fake engine or transport), **Mac** (real code run on the Mac),
**Simulator** (iPhone Simulator on the Mac), **real phone** (Alex's iPhone 17), **scripted review**
(the self-test ticks the review boxes automatically), **human review** (a person did it).
"Simulated images" means computer-drawn board pictures. Their accuracy is never camera or
physical-board accuracy. **Orchestrator-run** means the orchestrator ran the check itself;
**agent-reported** means a worker reported it and the orchestrator did not re-run it.

## What works today

| Area | State | Evidence type | Where the evidence lives |
| --- | --- | --- | --- |
| App installed on the phone, opens | Installed Nov 15; Alex saw it open and stay open | Real phone, human observation | `chess-builds/iphone-2026-11-15/`, `docs/PHONE_INSTALLATION.md` |
| Rules + Stockfish inside the app (local WebKit runtime) | Working, offline | Real phone | `chess-builds/special-replay-2026-11-15/phone-run1/` |
| Study mode: one picture, five review ticks, text move | Part of the 30/30 self-test below (12 checks in the earlier 25/25 run) | Real phone, scripted review | same `phone-run1/`; `prewarm-wiring-2026-11-16/` |
| Replay mode: 14-frame game | Part of the 30/30 self-test below (6 checks in the earlier 25/25 run) | Real phone, scripted review | same `phone-run1/`; `prewarm-wiring-2026-11-16/` |
| Replay mode: special-move game (en passant, promotion, both castlings) | 7 checks in the earlier 25/25 run (Nov 15, superseded as "latest" by the 30/30 row below) | Real phone, scripted review | same `phone-run1/` |
| **Study and Replay, two games, with the pre-started engine and a 100,000-node search** (final build `prewarm-wiring-2026-11-16/after2`) | **30/30 self-test checks in 3 of 3 runs**; the earlier build `after` passed 30/30 in 2 of 2; 3 earlier attempts were interrupted by a sleeping screen and are not results. Supersedes the 25/25 run as the latest phone evidence | Real phone, scripted review, orchestrator-run | `chess-builds/prewarm-wiring-2026-11-16/phone-run1/`, `phone-run2/`; [PREWARMED_ENGINE.md](PREWARMED_ENGINE.md) |
| Same build in the Simulator | **0 of 5 full passes** (27, 25, 27, 28, 28 of 30). About 1 search in 5 runs about 35x slower there and misses the 4.5 s deadline; every miss failed safe (no advice). Not seen on the phone (75 analyses, slowest 0.28 s) | Simulator, agent-reported | `chess-builds/prewarm-wiring-2026-11-16/` (sim runs) |
| Safety behaviour (obstruction, untick, reset, background, switching, late engine reply, missing piece) | All pass in the Nov 15 phone run; included in the 30/30 self-test | Real phone, scripted review; also mock | `phone-run1/`, `special-replay-2026-11-15/mocks/` |
| Recognition speed | 27–76 ms per picture on the final build (23–79 ms in the Nov 15 run) | Real phone | `prewarm-wiring-2026-11-16/phone-run*/` |
| Engine start and search time | Final build: engine start median 0.33–0.37 s, search median 0.15–0.17 s at about 600k nodes/s; 13 of 25 analyses per run used the pre-started engine. Earlier builds: about 1.4–2.0 s per search | Real phone | `prewarm-wiring-2026-11-16/phone-run*/`; Nov 15 run `phone-run1/selftest-report.json` |
| Mock safety suites | Study 33/33, Replay 31/31, Integration 23/23, ReplayTracker 94/94 (orchestrator-run 02:47; agent-reported unchanged after the follow-up). 37 mutations all caught. Earlier: Study 28/28, Replay 26/26, Tracker 94/94, Integration 18/18 | Mock (Mac) | `special-replay-2026-11-15/mocks/*-run.txt` |
| Node test suite (`npm test`) | 346 tests, 338 pass, 0 fail, 8 skipped (orchestrator-run 04:42). Earlier: 216 tests at Nov 16 00:20. All checks: `scripts/check-all.sh`, last full run 02:45, 6 of 6 suites passed (orchestrator-run) | Mac | `scripts/check-all.sh`; `orchestrator-state.json` |
| Pre-started engine (`src/core/prewarmed-engine.js`) | 37 tests; reviewer's warm-up leak fixed; 121/121 same move as a fresh engine (orchestrator-run). Now wired into the phone build (see the 30/30 row) | Mac, Node; the phone run is separate | [PREWARMED_ENGINE.md](PREWARMED_ENGINE.md) |
| Board-on-a-screen pipeline (corners → square reader → move inference, two pictures must agree) | 0 wrong accepted moves on `heldout` and `heldout2` (both spent). Easy positions 114/115. Start-up reader is now v3 (was v2); 31 tests | Mac, simulated images only, orchestrator-run | `chess-builds/pipeline-2026-11-15/pipeline/eval-heldout*/`; [SCREEN_PIPELINE.md](SCREEN_PIPELINE.md) |
| Stress pictures, development half (`stressdev`, reader v3) | Accepting from one picture: 5 wrong moves, all from mid-move pictures. Two pictures must agree: 0. Starts accepted 27/36 (other piece styles 0/6, lens distortion 1/3, motion blur 2/3). Highlighted squares mostly refused. The held-out half `stressheld` is untouched | Mac, simulated images only, orchestrator-run | [SCREEN_BOARD_STRESS.md](SCREEN_BOARD_STRESS.md); [SCREEN_GAME_SCENES.md](SCREEN_GAME_SCENES.md) |
| Square reader v3 / v3.1 | v3: 0 confident wrong squares of 60,736 on held-out set 2, starts 11/12. v3.1 (blur-gate edge case closed) gives identical labels on 97,024 development squares; it is the default reader | Mac, simulated images only | [OCCUPANCY_CLASSIFIER_V3.md](OCCUPANCY_CLASSIFIER_V3.md), `eval-heldout2-v3/` |
| Square reader v4.3 (flat pieces, last-move highlights) | Frozen (`de58ef04…`, 55 tests) after three independent reviews each rejected the previous freeze (v4.0, v4.1, v4.2). Reserved set `stressheld`, scored once and now spent, 36 games: 0 wrong moves accepted when two pictures must agree, for v3.1 and for v4.3; starting pictures accepted 28/36 (v3.1) and 30/36 (v4.3); re-reviews per 100 positions 20.9 and 26.8. v4.3 is not the default and has not had its own review. See [OCCUPANCY_CLASSIFIER_V4.md](OCCUPANCY_CLASSIFIER_V4.md) | Simulated images, orchestrator-run |
| Swift port of the square reader (`native/ScreenOccupancy/`) | Same labels as the Python reader on all four development splits; type-checks for iOS; not in the app | Mac | `native/ScreenOccupancy/README.md` |
| Corner finder curved-edge check (`native/ScreenBoardVision`) | The check rejects curved boards: on 3,017 development pictures 0 wrong accepted before and after, 39 newly rejected (orchestrator-run). It is an improvement, not a guard against lens distortion: after the re-review of the fixed binary, 24 of 422 two-term-lens pictures were still accepted with corners 5.0–16.6% off (the original finder: 277 wrong of 1,006 distorted pictures). Lens undistortion is needed. Not used by the pipeline yet, on purpose, until `stressheld` is scored | Mac, simulated images only | [SCREEN_BOARD_STRESS.md](SCREEN_BOARD_STRESS.md) |
| Occupancy tracker with promotion question (`src/core/occupancy-tracker.js`) | After five reviews it still has a hole: it can trust a swapped board (one-gap swap, wrong position trusted 72 of 144; a hand putting down a spare piece, 22 of 24). Occupancy alone cannot close it. **Not wired in; Alex decides** | Mac, logic only, synthetic errors, orchestrator re-ran the attack scripts | [OCCUPANCY_TRACKER.md](OCCUPANCY_TRACKER.md) |
| Two-misread study | 85.7% of moves have a two-misread "twin"; the two-picture agreement rule cuts wrong moves by 4–5 orders of magnitude in the error model | Mac, logic only (no images) | `docs/OCCUPANCY_MISREADS.md`, `pipeline-2026-11-15/misread/report.json` |
| Engine budget study | 100k nodes: 82% same move as an 800k search, 0 of 121 clearly worse (the 100k budget is now on the phone) | Mac only | `docs/ENGINE_BUDGET.md`, `chess-builds/engine-budget-2026-11-15/ladder.md` |
| Mock glasses (Meta Mock Device Kit) in a Simulator-only app copy | Frames flow; every frame that reached the trust decision stayed "age unknown"; no advice, engine run or speech. No network contact seen, but a connection shorter than about a millisecond would be missed. Phone build byte-identical before and after. No real glasses involved | Simulator, mock device, agent-reported with orchestrator spot checks | `docs/MOCK_GLASSES_RUN.md`, `docs/MOCK_DEVICE_KIT_PLAN.md` |
| Mock glasses frame-age methods | **No method rejected every stale frame**: on-screen code 159/162, clock offset 3224/3407 at best, budget plus watchdog 674/2190. The live trust gate is unchanged. **No real latency was measured** | Simulator, mock device, agent-reported; rule checks 38/38 orchestrator-run | [MOCK_GLASSES_FRAME_AGE.md](MOCK_GLASSES_FRAME_AGE.md) |
| Evidence inventory | `chess-builds` holds 31.5 GB; about 9 GB are deletion candidates after Alex's OK. Nothing deleted | Mac (file sizes) | `chess-builds/session-review-2026-11-16/evidence-inventory.md` |

The phone now has the optimized normal build (no self-test code) from
`prewarm-wiring-2026-11-16/after2/device-normal` (sha256 `5ffa41a7…`), installed 2026-11-16 about
04:50, with both Replay games, the pre-started engine and the 100,000-node search. **Nobody has used
the app by hand.** The pipeline is not in the app; the app still reads marked synthetic images with
the older template recogniser.

## Signing deadline

The free Apple signing profile expires **November 22, 2026, 15:22 Madrid**. After that the app on
the phone will not open until it is re-signed and reinstalled: run
`native/ChessCompanionApp/signing/renew_profile.sh` (dry-tested only, never used for real), then
`sign_and_install.sh` with the configured Apple Development identity. A free account must repeat
this every 7 days.

## In flight at handoff (uncommitted)

Claim nothing final about these. The handoff lists two fix rounds that were running at 05:45:
square reader v4.1 (its later state is in the "Square reader v4" row above) and the corner finder
round 2 (re-reviewed; see the corner finder row). Finished this session but uncommitted: the engine
wiring (reviewed twice, proven on the phone), the library default reader, occupancy tracker rounds
5 and 6, the frame-age harness and the evidence inventory.

## Next packets, in priority order

This is the handoff's backlog order (`FABLE-HANDOFF.md`, "Backlog").

1. **Square reader v4.3:** decide the default (recommended: v3.1 stays the default, v4.3 is tried
   only when v3.1 refuses a start picture; not built). `stressheld` is spent. Open: 4 flat-style attack squares where a piece drawn exactly on a square is
   scored wrong by the reviewer's key.
2. **Corner finder round 2** (`bin-new2`, sha256 `3292bcae…`): may replace the pipeline's finder as
   a strict improvement. Not swapped in until `stressheld` has been scored; then copy under a new
   name, re-run the development splits, and only then make it the default.
3. **Lens undistortion before the corner finder.** With the known lens value undone, the reader
   accepted 3 of 3 lens starts. Eventually needs a one-time calibration of the real glasses camera.
4. **Motion blur** belongs to the square reader: with exact corners it still reads blurred pieces
   as empty (12 px blur).
5. **Occupancy tracker:** round 6 was reviewed (fifth review). The next fix round is rule "R2" plus
   small fixes; whether to do it is Alex's decision (below).
6. **Engine wiring leftovers** (low severity) and the slow-search tier seen in the Simulator:
   collect more phone runs before deciding on a warm-up for every engine start.
7. **Frame age for glasses:** method 1 (on-screen code) is the candidate; it needs real glasses to
   mean anything. Live advice stays blocked.
8. **Test hygiene:** two pipeline tests leave reader v2 selected. Alex has not asked for a change.
9. **Housekeeping:** refresh the private status page; a real-WebKit test of the engine-host-died
   path; evidence retention (31.5 GB, about 9 GB are candidates after Alex's OK).

Earlier packets now done: the pipeline's start-up reader is v3; the Swift port of the square
reader; stress scenes; the first Simulator run of Meta's mock-glasses code; the pre-started engine
and the 100,000-node search on the phone.

## Decisions waiting on Alex

- **Occupancy tracker** (five reviews, each found something; occupancy alone cannot tell which piece
  is on a square). Choices: (1) one more fix round, wired behind a setting that is off by default,
  for measuring only; (2) stop investing until a reader can identify pieces; (3) accept the hole
  for honest solo practice and wire it in after the fix round. The orchestrator recommends 1.
- **Piece-in-transit setting:** stays OFF. With it ON a lifted piece costs 0 instead of 49
  re-reviews per 100 positions; wrong acceptances are equal in both settings after round 6.
- **Slow engine searches** (Simulator only so far): accept an occasional "no recommendation", or add
  a warm-up for every engine start.
- Try both Replay games by hand on the phone. This is the only missing human evidence.
- Camera and real-glasses approval for the first real screen-board capture.
- A private off-machine backup (needs a GitHub account and repo name from Alex, plus scrubbing his
  Apple ID details from `HANDOFF.md` and `docs/PHONE_INSTALLATION.md` first).
- Whether to download the non-commercial ChessReD dataset (about 29 GB) for physical boards.
- What to keep of the 31.5 GB of evidence (inventory file above).
- Commit: nothing since `46ce560` is committed; commit only when Alex asks.
- Sharing the app with anyone first needs the licence steps in `docs/LICENCE_AUDIT.md`.

## Boundaries

**Approved:** Simulator testing; inspecting the connected iPhone and existing signing setup;
signing, installing and opening the private offline app on the phone for text-only testing with
the configured Apple Development identity. For mock glasses (Alex, in chat, Nov 15): Meta's
developer terms agreed for private testing; work without a Meta account; a Simulator-only copy
containing Meta's code; reuse the SDK copy already on the Mac.

**Not approved:** real glasses, camera, microphone, Bluetooth, audible speech; new accounts,
spending, credential entry, permanent settings changes; an Xcode update; any dataset or model
download; push, deploy, distribution or a remote. Commit only when Alex asks. Generated binaries,
engine files and media stay outside the repo (in `/Users/alexmunzon/chess-builds/`).

## Known limits

- **No human use yet.** All phone review so far is the scripted self-test fixture.
- **Simulated images only.** Every recognition number comes from computer-drawn boards on a
  simulated screen. No camera, glasses or physical-board accuracy exists.
- **Pipeline numbers are optimistic where they count re-reviews in the older "re-review" mode:** it
  uses the answer key to decide when a simulated person re-checks the position. Headline numbers now
  come from the "self-aware" mode, where a human is asked only when the pipeline knows it is stuck.
  Medium and hard scenes are often withheld rather than read.
- **Wrong "unchanged".** The two-picture rule in the pipeline does not cover a wrong "nothing
  moved" reading. It is the largest remaining error in the misread model (about 1.3e-5 per
  picture at a 1% square error rate) and leaves the position stale for one more picture; it does
  not put a wrong position in place.
- **Promotions** are ambiguous by design (the app must ask which piece). A wrong reviewed start
  corrupts the whole game.
- **Glasses timing.** Meta's SDK stamps frames with the glasses' clock and documents no mapping to
  phone time, so live advice stays blocked. In the mock-glasses run, frame timestamps restart at
  zero on every stream, frames keep arriving after the glasses are taken off or permission is
  denied, and no frame-age method rejected every stale frame; no real latency was measured. An open Meta issue reports camera streaming pausing
  phone audio (seen on Gen 2; Gen 1 untested).
- **Engine.** Bounded search (100,000 nodes on the phone): strong, not perfect; 82% same move as an
  800k-node search. Slow searches seen in the Simulator are unexplained; every one failed safe.
- **Occupancy tracker hole.** Occupancy alone cannot tell which piece is on a square, so a swap
  under a hand can be trusted. It is not wired in.
- **Corner finder and lenses.** The curved-edge check is not a guard: lens-distorted boards can
  still pass with wrong corners. The pipeline needs lens undistortion.
- **Not exercised for real:** the `onClose` path; `renew_profile.sh`; game switching during a
  real engine search (stand-in engine only). No camera, glasses, microphone, Bluetooth or
  human-use result exists anywhere.

## History of the plan

- **Nov 10:** project pivoted from blackjack to chess; six phases planned (rules core, review UI,
  calibration, pieces and game state, capture and glasses, output and release).
- **Nov 11:** no physical board, so work moved to synthetic simulation (`docs/SIMULATION_PLAN.md`);
  real-photo and real-video recognisers failed their gates.
- **Nov 12–13:** native modules, Mac WebKit engine, Simulator app, private unsigned phone build.
- **Nov 15:** signed and installed on the phone; self-test mode; Replay mode; `-O` speed fix;
  three recognition prototypes; research on recognition, glasses SDK and licences.
- **Nov 15–16 night:** prototypes joined into one pipeline; square reader v3; special-move Replay
  on the phone; misread, engine and mock-glasses studies; checkpoint `46ce560`.
- **Nov 16 overnight session:** pre-started engine and 100,000-node search on the phone (30/30 in
  3 of 3 runs; superseded the 25/25 run); pipeline start-up reader v3; stress pictures; reader v4
  rejected once and re-fixed; corner finder curved-edge check; occupancy tracker rounds 5 and 6
  after five reviews; first mock-glasses Simulator runs and the frame-age study; evidence
  inventory. Docs refreshed at the handoff (about 05:45; reader v4.1 notes from 06:40).

The full earlier text of this plan is in git: `git show a13ed1c:docs/PLAN.md`.
