# Verification

## Verified checkpoint — 17 November 2026

Parent final combined check: **12/12 suites**, including native **26/26**; npm **389 pass, 0 fail, 8 skip** out of 397. Guard **36/36**, pipeline **51/51**, freshness **16/16**. Updated real-phone self-test **34/34** with zero speech requests; normal build restored. Earlier interrupted phone attempt and signing-folder failure are retained in the session record.

Guard, runtime, freshness and corner selection changes received fresh independent review. Four development splits match the prior reviewed detector results: **376/376 JSON files**, excluding timing/debug paths; this is equivalence, not new accuracy. All held-out sets remain spent; no new held-out evaluation. King/queen experimental work remains incomplete, tracking stays off and the piece guard stays disconnected. Source CI has pinned dependencies and least-privilege settings; actual Linux runs are recorded in [GitHub Actions](https://github.com/alexmunzon/chess-practice/actions).

Exact commands, all run outcomes, component-versus-app evidence limits, failures and local evidence paths are in [the completed session record](../SESSION-HANDOFF-2026-11-17.md). This checkpoint supersedes the earlier summaries below.


## Current checkpoint — November 17, 2026

This section supersedes older status summaries below. Historical logs and their original evidence paths are retained; most build artifacts live outside the public repository and are not reproducible merely by following those paths on another computer.

| Check | Recorded result | Scope and limit |
| --- | --- | --- |
| Full check before the current fix work | 11 of 11 suites passed; Node 397 tests, 389 passed, 8 skipped, 0 failed | Orchestrator-run on the Mac; log directory `$TMPDIR/chess-check-1575`. This predates subsequent edits, so it is not a pass for the final working tree. |
| Native tracker gate check before the runtime fix | 26 of 26 passed | Orchestrator-run on Mac WebKit; one check accepted the old duplicate-`kind` behavior. The known gap still needed a fix and independent review despite a green run. |
| Latest committed phone build (`53a8bfa`) | 34 of 34 checks in two complete runs | Real iPhone, scripted review, synthetic pictures; `CB/phone-selftest-2026-11-17/phone-run2/` and `phone-run3/`. An earlier interrupted attempt is not a complete run. |
| Frame freshness tests before current fixes | 16 of 16 passed | Mac simulation only; does not establish freshness of real glasses pictures. |
| Piece guard at current work start | Restored round-seven guard: 32 of 32 passed | Orchestrator-run; known review findings remain. Later round-eight work requires fresh checks and review. |

`CB` means the maintainer's external `chess-builds` evidence directory. The full-suite logs were read during this documentation refresh; the other rows preserve the orchestrator's recorded evidence and are not new runs by the documentation worker. Final fix-round and integration results must be recorded separately when they finish.

**Engine correction:** the November 17 in-flow measurements show a Simulator-only freeze, not “35x slower” search. In 18 of 21 misses the engine searched normally, then went silent; in three it did not answer the first command. The cause is not established and load alone does not explain it. The recorded phone sample had zero misses in 470 searches. This does not prove that a phone can never fail. The investigation is parked; see `CB/slow-search-experiment-2026-11-17/FINDINGS.md`.

**Evidence limits:** synthetic accuracy is not physical-board accuracy; scripted review is not human usability validation; a Mac check is not a phone test. The existing held-out image sets have already been scored and cannot support a fresh unseen-data claim. Live camera, real glasses and audible output remain unverified. Current source changes have not inherited the phone validation of `53a8bfa`.

## Historical checkpoint — November 16, 2026

Refreshed November 16, 2026, at the handoff (about 05:45 Madrid; reader v4.1 notes from 06:40). The
last commit is still checkpoint `46ce560` on `main` (6 commits, no remote); everything since is
uncommitted. It updates and supersedes the version written at 01:30 on November 16 and the
"Current state (2026-11-15)" version before it (rows dated 2026-11-15 below are from that version and
still hold unless a newer row replaces them or says "superseded"). **At the time, this section superseded the older sections below; the November 17 checkpoint above is now newer.** Those older sections are history: they stay exactly as written,
including their Codex evidence paths, and where they say something is "pending", "untested" or
give an older test count, this section is the current answer.

Short names: `CB` = `/Users/alexmunzon/chess-builds`. Evidence types are kept separate:
**mock**, **Mac**, **Simulator**, **real phone**, **scripted review**, **human review**.
Who ran it is also kept separate: **orchestrator-run** means the orchestrator ran the check itself;
**agent-reported** means a worker reported it and the orchestrator did not re-run it. A row with
neither label was written before this split; read it as it was.
"Synthetic" or "simulated images" = computer-drawn board images; their accuracy is never camera or physical-board
accuracy. Nothing here is "hardware validated" and no engine result is "perfect play".

### Test suite

| Claim | Exact number | Evidence type | Command or file that proves it | Date |
| --- | --- | --- | --- | --- |
| Node test suite | **346 tests, 338 pass, 0 fail, 8 skipped**, 2026-11-16 04:42, orchestrator-run. Supersedes 216 tests, 210 pass, 0 fail, 6 skipped (00:20) | Mac | `npm test` (run outside the command sandbox: `listen EPERM` means sandbox, not a code failure); earlier log `CB/review-all-2026-11-16/npmtest.log` | 2026-11-16 |
| All checks in one command | 6 of 6 suites passed, 2026-11-16 02:45, orchestrator-run. Two suites (reader v4, frame-age rules) were added to the script afterwards; each passed alone | Mac | `scripts/check-all.sh`; `orchestrator-state.json` | 2026-11-16 |
| Python suites (latest recorded) | screen_pipeline 31/31, occupancy_classifier_v3 21/21, occupancy_classifier 11/11, screen_game_scenes 32/32, frame-age rules 3 tests with 38/38 rule checks (orchestrator-run). Reader v4: 48 tests for v4.1 (orchestrator-run 06:40); the older 42/42 was for the rejected first freeze | Mac | `orchestrator-state.json` (`pythonTests`); `FABLE-HANDOFF.md` backlog item 1 | 2026-11-16 |
| Earlier count, before the night's work | see `CB/perf-integration-2026-11-15/npm-test.txt` (0 fail) | Mac | that log | 2026-11-15 |

### Phone (iPhone 17, iOS 27.2)

| Claim | Exact number | Evidence type | Command or file that proves it | Date |
| --- | --- | --- | --- | --- |
| App installed and opens | Profile checks 40/40; signed-product checks 29/29; Alex saw it open and stay open | Real phone; human observation of opening only | `CB/iphone-2026-11-15/evidence/profile-validation.json`, `signed-product-validation.json`; `docs/PHONE_INSTALLATION.md` | 2026-11-15 |
| Signing profile expiry | 2026-11-22 14:22:26 UTC = 15:22 Madrid; after that the app will not open until re-signed and reinstalled | Real phone (profile file) | `CB/iphone-2026-11-15/evidence/profile-validation.json` (`expiresUTC`) | 2026-11-15 |
| First self-test on the phone (12-file runtime) | 12/12, complete, 0 speak requests; report SHA-256 starts `43679b46` | Real phone, scripted review | `CB/selftest-2026-11-15/phone-run4/selftest-report.json` | 2026-11-15 |
| Self-test with tracker bundled (15-file runtime) | 12/12, complete, 0 speak requests; SHA-256 starts `42f92f62` | Real phone, scripted review | `CB/integration-2026-11-15/phone-run1/selftest-report.json` | 2026-11-15 |
| Replay mode, unoptimized build | 18/18 (12 Study + 6 Replay); recognition 1,442–1,538 ms in the shown fixtures | Real phone, scripted review | `CB/replay-mode-2026-11-15/phone-run1/summary.txt` | 2026-11-15 |
| Optimized build, first attempt | Interrupted, exit 3, 0/7 (app started inactive; "engine not ready"); no timing evidence | Real phone | `CB/perf-integration-2026-11-15/phone-run1/summary.txt` | 2026-11-15 |
| Optimized build (superseded by the 30/30 runs below) | **18/18**, complete, 0 speak requests, exit 0 | Real phone, scripted review | `CB/perf-integration-2026-11-15/phone-run2/summary.txt`, `selftest-report.json` | 2026-11-15 |
| Recognition time per picture (optimized) | 39–122 ms (unoptimized builds: about 1,440–1,830 ms, per `HANDOFF.md` checkpoints) | Real phone | `phone-run2/summary.json` (`timingsMs.recognition`) | 2026-11-15 |
| Replay frame step (recognition + 2 tracker requests) | 52–88 ms per game frame (first frame 25.5 ms) | Real phone | `phone-run2/selftest-report.json` (`steps[].stepMs`) | 2026-11-15 |
| Engine search time | 1,504–1,986 ms, plus one 3,463 ms search (after-e4 fixture) | Real phone | `phone-run2/summary.json` and `selftest-report.json` (`engineSearchMs`) | 2026-11-15 |
| Replay game followed | 14 frames, 7 legal text recommendations; obstructed frame (16 unknown squares) revoked tracking until a renewed review | Real phone, scripted review | `phone-run2/selftest-report.json` (the `replay-*` checks) | 2026-11-15 |
| Safety checks on the phone | Obstruction, four-of-five review, side-to-move `x`, untick, in-flight switch, background handler, reset, step during analysis, tracker/engine never concurrent, leaving mode: all pass | Real phone, scripted review | `phone-run2/summary.txt` | 2026-11-15 |
| Special-move Replay self-test (earlier phone run, superseded by the 30/30 runs below) | **25/25**, complete, 0 speak requests, exit 0; run ended 23:32 Madrid | Real phone, scripted review | `CB/special-replay-2026-11-15/phone-run1/summary.txt`, `summary.json` | 2026-11-15 |
| Special-move game checks in that run | 7/7: every ply tracked; game switch mid-game revokes; late engine reply after an occlusion revoke shows nothing; occlusion and missing piece revoke until a renewed review; text advice only at tracked positions; tracker and engine never concurrent | Real phone, scripted review | same `summary.txt` (`special-*` checks) | 2026-11-15 |
| Timings in that run | Recognition 23–79 ms per picture; Study analysis 1,386–1,880 ms; engine search inside Replay 1,395–2,023 ms; engine start 271–462 ms | Real phone | `phone-run1/selftest-report.json` | 2026-11-15 |
| Earlier build on the phone (replaced 2026-11-16 about 04:50) | Normal build with both Replay games, verified free of self-test code before install; never used by hand | Real phone | `CB/special-replay-2026-11-15/phone-run1-restore.log`, `device-normal/` | 2026-11-15 |
| **Pre-started engine and 100,000-node search, Study and Replay with two games (final build `after2`)** | **30/30 self-test checks in 3 of 3 runs**. The earlier build `after` passed 30/30 in 2 of 2. 3 earlier attempts were interrupted by a sleeping screen and are not results (the screen must be on, not only unlocked) | Real phone, scripted review, orchestrator-run | `CB/prewarm-wiring-2026-11-16/phone-run1/`, `phone-run2/`; `docs/PREWARMED_ENGINE.md` | 2026-11-16 |
| Phone timings, final build | Recognition 27–76 ms; engine start median 0.33–0.37 s; search median 0.15–0.17 s at about 600k nodes/s; 13 of 25 analyses per run used the pre-started engine; 75 analyses, slowest 0.28 s | Real phone | same `phone-run1/`, `phone-run2/` | 2026-11-16 |
| **Build now on the phone** | Optimized **normal** build from `CB/prewarm-wiring-2026-11-16/after2/device-normal` (sha256 `5ffa41a7…`; the self-test build is `d3596d58…`), pre-started engine, 100,000-node search, no self-test code; installed about 04:50. Nobody has used it by hand | Real phone | `CB/prewarm-wiring-2026-11-16/` | 2026-11-16 |

The background check calls the app's handler in-process; it is not real backgrounding by a
person. The in-flight switch is event ordering inside the self-test, not finger-driven timing.

### Simulator and mocks

| Claim | Exact number | Evidence type | Command or file that proves it | Date |
| --- | --- | --- | --- | --- |
| Replay mode in the Simulator, unoptimized, heavily loaded Mac | 15/18, 17/18, 17/18, 17/18 (all failures were engine deadlines under load) | Simulator, scripted review | `CB/replay-mode-2026-11-15/sim-run1..4-report.json` | 2026-11-15 |
| Optimized build in the Simulator | 18/18 three times, Mac load average 3.3–9.3 | Simulator, scripted review | `CB/perf-integration-2026-11-15/sim-run1..3-report.json`, `uptime-run1..3.txt` | 2026-11-15 |
| Mock safety suites | Study 28/28, Replay 21/21, Integration 18/18, ReplayTracker 94/94 | Mock | `CB/perf-integration-2026-11-15/mocks/study-run.txt`, `replay-run.txt`, `integration-run.txt`, `tracker-run.txt` | 2026-11-15 |
| Special-move Replay in the Simulator | Run 1: 25/25; run 2: 24/25 (an engine-deadline miss under load); special checks 7/7 in both. A third run under load: 21/25, special 6/7 | Simulator, scripted review | `CB/special-replay-2026-11-15/sim-run1..3-report.json`, `uptime-run*.txt` | 2026-11-15 |
| Mock suites after special-move Replay | Study 28/28, Replay 26/26, Tracker 94/94, Integration 18/18 | Mock | `CB/special-replay-2026-11-15/mocks/*-run.txt` | 2026-11-15 |
| Same build as the 30/30 phone runs, in the Simulator | **0 of 5 full passes** (27, 25, 27, 28, 28 of 30). Interpretation superseded November 17: intermittent engine freezes caused deadline misses; cause unresolved. Every recorded miss failed safe (no advice). Not seen in the recorded phone sample; a per-start warm-up is not an established fix | Simulator, scripted review, agent-reported | `CB/prewarm-wiring-2026-11-16/` (sim runs); `orchestrator-state.json` | 2026-11-16 |
| Mock safety suites, latest | Study 33/33, Replay 31/31, Integration 23/23, ReplayTracker 94/94 (orchestrator-run 02:47; agent-reported unchanged after the follow-up); 37 mutations all caught. Supersedes the 28/28, 26/26, 94/94, 18/18 row above | Mock | `orchestrator-state.json` (`mockSuites`) | 2026-11-16 |
| Swift tracker vs JavaScript tracker | 28/28 replies deep-equal to the golden transcript | Mac | `CB/replay-tracker-swift-2026-11-15/cross-language.stdout.txt` | 2026-11-15 |

### Recognition speed fix (missing `-O`)

| Claim | Exact number | Evidence type | Command or file that proves it | Date |
| --- | --- | --- | --- | --- |
| Cause of slow phone recognition | App compiled with no `-O`; same Mac code about 3,000 ms per frame at `-Onone` vs 41 ms at `-O`, about 27 ms after the patches | Mac | `docs/RECOGNIZER_PERFORMANCE.md`; `CB/recognizer-perf-2026-11-15/report.md` (timings reported in the doc; raw bench output not re-opened) | 2026-11-15 |
| Speed fix changed no decisions | 78/78 frames, 4,992/4,992 squares byte-identical; replay sequence 15 frames / 960 squares | Mac | `CB/perf-integration-2026-11-15/identity/identity.jsonl` | 2026-11-15 |

### Synthetic image games (Mac only, not in the app unless stated)

| Claim | Exact number | Evidence type | Command or file that proves it | Date |
| --- | --- | --- | --- | --- |
| Bundled 14-frame replay game: Swift vs Python recogniser | 15 frames, 960 squares, 0 disagreements; manifest SHA-256 starts `0c2a46b3` | Mac, synthetic | `CB/replay-sequence-2026-11-15/native-conformance.json` | 2026-11-15 |
| Special-move game (25 plies: en passant, promotion, both castlings) | All 26 positions tracked to the exact expected FEN; 28 frames, 1,792 squares, 0 Swift-vs-Python disagreements; manifest starts `9d1c5fc8` | Mac, synthetic, scripted review | `SPECIAL_GAME_DIR=… node --test tests/special-game-sequence.test.js`; `CB/special-game-2026-11-15/native-conformance.json` | 2026-11-15 |

### Recognition prototypes, single-stage scores (Nov 15; since joined into the pipeline below; none is in the app)

| Claim | Exact number | Evidence type | Command or file that proves it | Date |
| --- | --- | --- | --- | --- |
| Screen-board corner finder, dev | 210 scenes, 99.5% found, 0 false accepts, mean corner error 0.13 px, mean 113.7 ms per frame | Mac, synthetic | `CB/screen-board-2026-11-15/reports/dev-final.json` | 2026-11-15 |
| Screen-board corner finder, held-out (run once after freezing) | 150 scenes, 99.3% found, 0 false accepts, mean corner error 0.12 px, mean 97.5 ms | Mac, synthetic | `CB/screen-board-2026-11-15/reports/heldout-final.json` | 2026-11-15 |
| Screen-board finder rejects non-boards | 48 negatives (no board, 6x6, 9x9, 10x10), 0 accepted | Mac, synthetic | same two reports (`negatives`) | 2026-11-15 |
| Occupancy classifier (empty / white / black) | Dev 3,328/3,328 squares; held-out 832/832; challenge 328 correct, 312 abstained, 0 confident errors | Mac, synthetic | `python3 -B tests/occupancy_classifier.py`; `CB/occupancy-classifier-2026-11-15/evaluation-all.txt` | 2026-11-15 |
| Classifier failure found and fixed after freezing | Frozen v1 made 452 confident errors (23.5%) at blur radius 5; v2 adds a sharpness gate and abstains | Mac, synthetic | `docs/OCCUPANCY_CLASSIFIER.md`; reported in that doc, `CB/occupancy-classifier-2026-11-15/sweep.json` not re-opened | 2026-11-15 |
| Move inference from perfect occupancy | 159,235 random plies: 99.36% unique and correct, 1,013 ambiguous (all promotion piece choice), 0 wrong; two runs byte-identical (SHA-256 starts `81d1300e`) | Mac, logic only, no images | `node scripts/simulation/occupancy-ambiguity-report.mjs`; `CB/occupancy-2026-11-15/run1.json`, `run2.json` | 2026-11-15 |
| Move inference with one misread square | 159,235 trials, all `no-legal-explanation`, 0 wrong moves (two misreads: see the misread study below) | Mac, logic only | `CB/occupancy-2026-11-15/run1.json` (`singleSquareMisread`) | 2026-11-15 |

### Board-on-a-screen pipeline (corners → square reader → move inference), simulated images only

One run each, frozen settings, run by the orchestrator. "Wrong accepted" = the pipeline advanced
the game with a wrong move. "Re-review" figures let the scorer use the answer key to decide when a
simulated person re-checks the position, so they are **optimistic**. Headline numbers now come from
the "self-aware" mode, where a human is asked only when the pipeline itself knows it is stuck. The two held-out-2 runs score different numbers of positions (v3 accepts more starts).

| Claim | Exact number | Evidence type | Command or file that proves it | Date |
| --- | --- | --- | --- | --- |
| Held-out set 1, square reader v2, one picture per position | 0 wrong accepted; starts accepted 7/12; 166/244 pictures correct with re-review (easy 134/135); 29 confident wrong squares of 15,552 | Mac, simulated images only | `CB/pipeline-2026-11-15/pipeline/eval-heldout/report-heldout.json` (no `.log` file found beside it) | 2026-11-15 |
| Held-out set 2, square reader v2 | 0 wrong accepted; starts 10/12; 3 confident wrong squares of 54,976; re-reviews per 100 positions 14.3 (one picture) and 33.45 (two-picture agreement) | Mac, simulated images only | `CB/pipeline-2026-11-15/pipeline/eval-heldout2-v2/report-heldout2.json`, `eval-heldout2-v2.log` | 2026-11-15 |
| Held-out set 2, square reader v3 | 0 wrong accepted; starts 11/12; 0 confident wrong squares of 60,736; re-reviews per 100 positions 12.6 and 33.4 | Mac, simulated images only | `CB/pipeline-2026-11-15/pipeline/eval-heldout2-v3/report-heldout2.json`, `eval-heldout2-v3.log` | 2026-11-16 |
| Wrong single-picture readings stopped by the two-picture rule | 0 in both held-out-2 runs (held-out-1 report predates this counter) | Mac, simulated images only | `guardBlockedWrongInferences` in the two held-out-2 reports | 2026-11-16 |
| Square reader v3 status | Superseded: the pipeline library now starts on v3 (was v2 with the blur-gate hole); v2 only by name; 31 tests. Orchestrator-run | Mac | `scripts/recognition/screen_pipeline.py`; `docs/SCREEN_PIPELINE.md`; `docs/OCCUPANCY_CLASSIFIER_V3.md` | 2026-11-16 |
| Square reader v3.1 (sha256 `c634a76d…`, blur-gate edge case closed) | Labels identical to v3 on 97,024 development squares. The held-out scores above were made with v3, not v3.1 | Mac, simulated images only | `orchestrator-state.json` (`frozen`); `docs/OCCUPANCY_CLASSIFIER_V3.md` | 2026-11-16 |
| Stress pictures, development half (`stressdev`, reader v3) | Accepting from one picture: 5 wrong moves, all from mid-move pictures. Two pictures must agree: 0. Starts accepted 27/36: other piece styles 0/6, lens distortion 1/3, motion blur 2/3. Highlighted squares mostly refused. 11 confident wrong squares, all on mid-move pictures; at least some are an answer-key artefact (worker's reading of the log, not checked square by square). Held-out half `stressheld` untouched. Orchestrator-run | Mac, simulated images only | `docs/SCREEN_BOARD_STRESS.md`, `docs/SCREEN_GAME_SCENES.md`; `CB/pipeline-2026-11-15/` | 2026-11-16 |
| Square reader v4.3 (flat pieces, last-move highlights) | Frozen (`de58ef04…`, 55 tests) after three independent reviews each rejected the previous freeze (v4.0, v4.1, v4.2). Reserved set `stressheld`, scored once and now spent, 36 games: 0 wrong moves accepted when two pictures must agree, for v3.1 and for v4.3; starting pictures accepted 28/36 (v3.1) and 30/36 (v4.3); re-reviews per 100 positions 20.9 and 26.8. v4.3 is not the default and has not had its own review. See [OCCUPANCY_CLASSIFIER_V4.md](OCCUPANCY_CLASSIFIER_V4.md) | Simulated images, orchestrator-run |
| Swift port of the square reader (`native/ScreenOccupancy/`) | Identical labels to Python on all four development splits; self-test passes; type-checks for iOS; not in the app | Mac | `native/ScreenOccupancy/README.md`; `CB/screen-occupancy-swift-2026-11-16/` | 2026-11-16 |
| Corner finder curved-edge check (`native/ScreenBoardVision`) | Finding: the corner finder was NOT what rejected the lens and blur starts; the square reader was. The new check rejects curved boards: on 3,017 development pictures 0 wrong accepted before and after, 39 newly rejected (orchestrator-run). Review of round 2 (`bin-new2`, sha256 `3292bcae…`): ordinary pictures 0 of 100 newly refused, corners identical; first review's 8 attack sets 0 of 653 wrong; but 24 of 422 two-term-lens pictures accepted with corners 5.0–16.6% off (original finder: 277 wrong of 1,006 distorted pictures). An improvement, not a guard; lens undistortion is needed. NOT used by the pipeline | Mac, simulated images only; review attack pictures | `docs/SCREEN_BOARD_STRESS.md`; `CB/corner-finder-2026-11-16/`, `CB/review-corner-finder-2026-11-16/` | 2026-11-16 |
| Occupancy tracker with promotion question (`src/core/occupancy-tracker.js`, round 6) | 79 tests (78 pass, 1 opt-in skipped). Five reviews; the fifth reviewed round 6 and found no other break. Open hole: (a) one-gap swap, wrong position trusted 72 of 144; (b) a hand puts down a spare or captured piece of the same colour, trusted 22 of 24, with no time limit; (c) the moving piece itself is the swap partner, 5 of 5, not closable by any rule. Reviewer's rule "R2" would close (a) and (b) at 50.6 -> 57.8 re-reviews per 100 positions (hand-over-board row). Not wired in; Alex decides | Mac, pure logic, synthetic errors; orchestrator re-ran the attack scripts | `docs/OCCUPANCY_TRACKER.md`; `CB/review-occupancy-tracker-round5-2026-11-16/` | 2026-11-16 |

### Afternoon session 2026-11-16 (added 2026-11-17 from `FABLE-HANDOFF.md`)

Everything in this block is uncommitted, except that the latest commit `e482729` was pushed on
2026-11-16 to the PRIVATE GitHub repo `alexmunzon/chess-practice` (remote `origin`, on Alex's words;
each further push needs them again). Rows above keep their wording; where one says "no remote", "not
wired in", "not built" or "no review of its own", this block is the newer answer.

| Claim | Exact number | Evidence type | Command or file that proves it | Date |
| --- | --- | --- | --- | --- |
| All checks and Node suite | `scripts/check-all.sh` 8 of 8 suites at 17:48; `npm test` 379 tests, 371 pass, 0 fail, 8 skipped (18:05). The script now also runs `tests/piece_classifier_v1.py` (9 suites; 11 of 11 on its own). Supersedes 346 tests, 338 pass | Mac, orchestrator-run | `scripts/check-all.sh`; `orchestrator-state.json` | 2026-11-16 |
| Occupancy tracker round 7/7b (sha `04400009…770f`) | 97 tests (96 pass, 1 skipped). Reviewed (sixth review). Attacks re-run by the orchestrator: hidden-square swap 0 of 144, spare on hidden square 0 of 24, opponent piece 0 of 12, captured piece 0 of 12; 18 of 18 mutants caught (worker-reported). Hand-over-board row 50.6 -> 61.8 re-reviews per 100. Supersedes the round 6 row | Mac, pure logic, synthetic errors | `CB/tracker-round7-2026-11-16/`, `tracker-round7b-2026-11-16/`, `review-occupancy-tracker-round7-2026-11-16/` | 2026-11-16 |
| Tracker holes that STAY open | Moving piece itself swapped or substituted 5 of 5; exchange between two consecutive pictures with nothing hidden 34 of 34; castling can end with king and rook interchanged 2 of 5; a bare `snapshot()` without a time stays ready. Only piece identification closes the first three | Mac, pure logic, synthetic errors | same folders | 2026-11-16 |
| Tracker wired into the app, OFF by default | Launch argument `--occupancy-tracker-on` (`TrackerSetting.swift`); any failed tracker request revokes; stop is never refused. Reviewed twice; the second review's one finding (unclassifiable command did not revoke) was fixed by the orchestrator in `NativeEngineRuntime.submit`, then the reviewer's harness held 13 of 13. No picture source exists; only scripted readings exercise it. `answerPromotion` not wired (a promotion revokes). Swift gates are caught only by macOS harnesses outside the repo (`TrackerGateChecks.swift`, its N4 check flaky) | Mac, Swift harnesses, scripted readings | `CB/tracker-wiring-2026-11-16/`, `review-tracker-wiring-2026-11-16/`, `review-tracker-wiring-round2-2026-11-16/` | 2026-11-16 |
| Phone self-test with tracker wired in (tracker off) | 33 of 33 at 18:14 (30 old + 3 tracker checks), 1 of 1 run. Normal build `phone2/device-normal` (unsigned sha `ed426961…`) restored on the phone, tracker off | Real phone, scripted review, orchestrator-run | `CB/tracker-wiring-2026-11-16/phone-run1/` | 2026-11-16 |
| Simulator A/B on a calm host | Engine deadline misses 5 of 100 (changed) vs 15 of 100 (previous commit), order alternated, 4 runs each; the change did not slow the engine (worker-reported) | Simulator, agent-reported | `CB/tracker-wiring-2026-11-16/round2/ab-table.txt` | 2026-11-16 |
| Reader start backup (`--start-fallback v4`), OFF | Built. `stressdev` starts 27 -> 30 of 36, two-picture wrong moves 0 on 5 splits, fallback off identical to committed code (worker-reported); pipeline tests 40 of 40 (orchestrator-run). Alex decided: v3.1 stays the default | Mac, simulated images, worker-reported | `CB/reader-fallback-2026-11-16/` | 2026-11-16 |
| Reader v4.3 review | Verdict NO for the backup as first built: start check accepted 66 of 107 not-the-start pictures in the flat style (orchestrator re-ran: 66 of 107); with the self-check 11 of 107. 9 of 24 removed rules caught by no test. Default reader v3.1 start check accepted 55 of 107 in the classic style | Simulated images, reviewer | `CB/review-reader-v43-2026-11-16/` | 2026-11-16 |
| Piece reader v1 (sha `e5c31e2ef64f…`, 11 tests) | Builder: dev2 25,619 of 28,257 correct, 0 wrong; stressdev 40,245 of 42,081, 0 wrong; swaps and substitutions none missed in 7,218 each. Review (counts reproduced): a guard that can only WITHHOLD advice, not confirmation. Confident-wrong: mid-game start with reduced material 12 of 5,760; arrow or glare in the start picture 44 in 6 of 12 games; a kind never shown 81 of 6,689; mid-move pictures 5; heavy blur/lens 44 of 25,344. Not in the pipeline | Simulated images | `docs/PIECE_CLASSIFIER.md`; `CB/piece-classifier-2026-11-16/`, `review-piece-reader-2026-11-16/` | 2026-11-16 |
| Piece reader v2 (sha `c19efcf5…35b61`, 22 of 22 tests re-run by the orchestrator) | Built, review in progress 2026-11-17, numbers agent-reported: confident-wrong 0 on every reviewer attack family (v1: 214) and on smoke2/dev2/stressdev; unsure about 28% of occupied squares on dev2 and stressdev (v1: 9% and 4%); swaps missed 0 (dev2: 2,616 noticed, 417 cannot-tell of 3,033); false alarms 0; clean starts wrongly refused 3 of 64, 6 of 84, 17 of 128; names nothing on 8 of 12 low-contrast board looks; 12 of 14 mutants caught. Kings and queens are never named in a standard game. Not wired | Simulated images, agent-reported | `CB/piece-classifier-v2-2026-11-16/` | 2026-11-16 |

### Misread study (logic only, no images)

| Claim | Exact number | Evidence type | Command or file that proves it | Date |
| --- | --- | --- | --- | --- |
| Moves with a two-misread twin | 85.67% of 39,923 plies have a wrong move that two specific misreads would make inference accept | Mac, logic only | `CB/pipeline-2026-11-15/misread/report.json` (`A_twoMisreadTwins`) | 2026-11-15 |
| Two-picture agreement rule, 1% square error rate | Wrong share of final moves 1.9e-9 (3.8e-5 per picture without the rule) | Mac, logic only, error model | same report, `C_randomErrorModels`, `G1-two-frame` | 2026-11-15 |
| Wrong "unchanged" reading, 1% error rate | 1.3e-5 per picture. The rule as built in the scored pipeline (`46ce560`) does not cover it; it is the largest remaining error; effect is a stale position for one more picture, not a wrong position | Mac, logic only, error model | same report (`wrongUnchanged`); `docs/OCCUPANCY_MISREADS.md` | 2026-11-15 |

### Engine budget study (Mac only)

| Claim | Exact number | Evidence type | Command or file that proves it | Date |
| --- | --- | --- | --- | --- |
| Quality versus node budget | 5k to 200k nodes on 121 positions: same move as an 800k-node reference 75.2% → 88.4%; 19/19 tactics at every budget | Mac, loaded machine; phone timing for a node budget is an estimate | `CB/engine-budget-2026-11-15/ladder.md`; `docs/ENGINE_BUDGET.md` | 2026-11-15 |
| Quality at 100,000 nodes (the budget now on the phone) | 82% same move as an 800k-node search; 0 of 121 clearly worse | Mac only | `docs/ENGINE_BUDGET.md`; `CB/engine-budget-2026-11-15/ladder.md` | 2026-11-15 |
| Pre-started engine (`src/core/prewarmed-engine.js`) | 37 tests; the reviewer's warm-up leak is fixed; 121/121 same move as a fresh engine (orchestrator-run). Round 2 timing at 100,000 nodes on a loaded Mac: fresh 1615 ms, pre-started 590 ms (rough). Phone result: see the 30/30 rows | Mac, Node; not WebKit | `docs/PREWARMED_ENGINE.md`; `CB/prewarmed-engine-2026-11-16/` | 2026-11-16 |
| Start-up cost per analysis on the phone (superseded by the pre-started engine: median 0.33–0.37 s on the final build) | 574–986 ms beyond the 1,000 ms search (median about 707 ms, 6 analyses), 2,463 ms in the one outlier | Real phone (timing), derived | `CB/perf-integration-2026-11-15/phone-run2/summary.json` | 2026-11-15 |

### Mock glasses (Meta Mock Device Kit)

| Claim | Exact number | Evidence type | Command or file that proves it | Date |
| --- | --- | --- | --- | --- |
| Owner approvals | Given by Alex in chat on 2026-11-15: Meta terms agreed for private testing; work without a Meta account; Simulator-only copy; reuse the SDK already on the Mac | Human decision | `docs/MOCK_DEVICE_KIT_PLAN.md` | 2026-11-15 |
| Link probe | Compiled and linked ("BUILD OK, binaries were not executed"); nothing ran | Mac | `CB/mock-glasses-2026-11-15/phase1/logs/build_probe.log` | 2026-11-15 |
| Test videos | Verified, 0 failures (e.g. special-game video 1,680/1,680 frames) | Mac | `CB/mock-glasses-2026-11-15/phase2/reports/verify.log` | 2026-11-15 |
| First Simulator run of Meta's code (Simulator-only app copy) | Frames flow; every frame that reached the trust decision stayed "age unknown"; no advice, engine run or speech. No network contact observed under a watch proven to catch held connections and name lookups; a connection shorter than about a millisecond would be missed. Phone build byte-identical before and after. Frames keep arriving after the glasses are taken off and after permission is denied mid-stream; frame timestamps restart at zero on every stream | Simulator, mock device, agent-reported with orchestrator spot checks | `docs/MOCK_GLASSES_RUN.md` | 2026-11-16 |
| Frame-age methods (Phase 5) | None of the three methods rejected 100% of injected stale frames: on-screen code 159/162, clock offset 3224/3407 at best, budget plus watchdog 674/2190. The live trust gate is unchanged. No real latency measured; no network contact, pop-up or account request in 3 of 3 runs. Rule checks 38/38 (orchestrator-run). Method 1's 3 misses came from a harness timing error larger than the 0.05 s margin | Simulator, mock device, agent-reported | `docs/MOCK_GLASSES_FRAME_AGE.md`; `CB/mock-glasses-phase5-2026-11-16/` | 2026-11-16 |

### Evidence inventory (2026-11-16)

| Claim | Exact number | Evidence type | Command or file that proves it | Date |
| --- | --- | --- | --- | --- |
| Size of the evidence folder | `CB` holds 31.5 GB in 35 folders; about 9 GB are deletion candidates (app builds and compiler caches) after Alex's OK; nothing deleted. `pipeline-2026-11-15` is still read by scripts and tests | Mac (`du`) | `CB/session-review-2026-11-16/evidence-inventory.md` | 2026-11-16 |

### Independent reviews (2026-11-16)

- App changes: no safety-rule violation found (the reviewer's reading, about 85% confidence). Open
  items: switching game during a real engine analysis is tested only with a stand-in engine; a
  possible stuck "Start local engine" button after a switch is unconfirmed.
- Everything else: no scoring hole found; the document mismatches it listed are fixed here.
  Orchestrator-reported; review notes not re-opened.
- Later reviews (2026-11-16, handoff): six adversarial reviews, each found something the workers'
  own tests missed (occupancy tracker twice, corner finder, reader v4, engine wiring twice at low
  severity). Their findings are in the rows above; the engine-wiring leftovers (low severity) are
  `RuntimeGuardChecks.swift` testing the rule and not the real `submit`, `cancelPrewarm` refused
  while another request is pending, one self-test case accepting a timeout as a pass, and
  `run-all.sh` not running `RuntimeGuardChecks`.

### Not verified, or in progress with no results yet

- **No human has used the app by hand.** All phone review is the scripted self-test fixture.
- No camera, glasses, microphone, Bluetooth or audible-speech result of any kind.
- No physical-board or camera recognition accuracy; every recognition number above comes from
  simulated images.
- The pipeline is not in the app and has never run on a phone.
- `renew_profile.sh` has never been used for real; the engine-host-died (`onClose`) path has only
  mock evidence.
- **No real glasses latency, no real frame age.** The pre-started engine's handling of iOS
  suspending or killing an idle spare is covered by an idle check and a fallback but untested on a
  device (`docs/PREWARMED_ENGINE.md`); the Simulator's slow-search tier is unexplained.
- **Still open, not final:** square reader v4.3 (frozen, `stressheld` spent 2026-11-16; default not decided); corner
  finder round 2 (not used by the pipeline); occupancy tracker (hole open, not wired in); lens
  undistortion (not started); motion blur in the square reader (not started).
- `stressheld` was scored once on 2026-11-16 and is spent, like `heldout` and `heldout2`. No unseen picture set is left.
- Added 2026-11-17: still not verified or open after the afternoon session: the tracker has no picture
  source and has never run on real pictures; its holes above stay open; piece reader v2 is under
  review (agent-reported); v4.3 reader tests miss 9 of 24 removed rules; the Swift tracker gates have
  no test inside the repo's own check; no human has used the app by hand.

---

# Current verification — November 12, 2026

> **Superseded.** Everything from here down is the historical record, kept as written. For the
> current state see "Current state (2026-11-16)" at the top of this file.

## Actual iPhone installation and opening — November 15, 2026

> Later on November 15 the phone ran the full self-test (18/18) with measured recognition and
> engine times; see "Current state (2026-11-16)" above.

The staged kit completed. Actual iPhone17/iOS27.2 installation is confirmed by device inventory; launch was accepted after user-confirmed developer trust, and Alex confirmed the app opens and stays open. He then closed/swiped it away. Profile/app checks passed 40/40 and signed-product checks 29/29. Exact signed and original unsigned artifacts, separate failed/successful logs and limits are at `/Users/alexmunzon/chess-builds/iphone-2026-11-15/`. See `docs/PHONE_INSTALLATION.md`. Physical-phone recognition/engine UI acceptance and performance are still untested; no glasses or audible-output result is claimed.


## Private phone build preparation — November 13, 2026

Alex reconfirmed the reported phone as **iPhone 17 / iOS 27.2** on November 13. This remains user-reported, not physically queried. The unchanged Simulator-tested source compiled and linked successfully as a private unsigned arm64 iOS device app with all five study fixtures, using the installed iPhoneOS 26.2 SDK path supplied to Swift and deployment target 17.2. The Mach-O itself encodes minimum OS 17.2 and SDK 17.2; both observed facts are retained without assigning a cause. All 46 artifact checks passed. The unsigned executable SHA-256 is `43a02cdeed2143bec10fa06afd8d456efb76583ec6c806616a7a2f607edbbdb6`; bundle ID `local.chesscompanion.offlinestudy`. Actual iOS 27.2 compatibility and phone performance remain unverified.

Evidence and exact prepared artifact: `/Users/alexmunzon/Documents/Codex/2026-11-12/task/outputs/iphone-offline-preparation-2026-11-13/` (`Phone-build.md`, `build-report.json`, `verification.json`). Prepared unsigned app: `/private/var/folders/40/pkx1ymn10_s42501bl5799wh0000gn/T/chess-iphone-study-ruo4lyj9/build/ChessCompanion.app`. No app source changed. No signing identity, profile, account or physical-device inventory was queried; no signing, installation, launch, audio or glasses operation occurred.

Physical-phone approval is still required to inspect the actual connected target/existing signing setup, sign using an existing configured identity/profile if available, install, launch and exercise this private app with text-only output. Stop for new accounts, registration, credential entry, spending or permanent settings changes. Simulator approval does not cover physical-device actions. Do not invent a device ID, team, identity, profile or successful compatibility result. The separate actual-UI in-flight fixture-switch timing limit remains documented; its mock passed 10/10.


## Simulator follow-up — November 13, 2026

All four playable fixtures have now completed the actual Simulator recognition → explicit FEN review → validation → analysis flow. Promotion returned legal `e1e2` (“king from e1 to e2”), separately rules/text checked; earlier moves were `e2e4`, `c7c5`, `e1d2`. The obstructed board exposed 16 unknown squares and blocked advice. Actual UI checks also passed for invalid rules-state FEN with matching pieces (side-to-move `x`), background/foreground review and recommendation invalidation, and reset after backgrounding. A rapid Analyze → Home sequence completed its UI actions within 290 ms; returning showed no stale recommendation and unchecked review. This does not prove exact engine receipt time or delivery of a late callback.

No app source changed in this follow-up; current source and signed artifact hashes match the prior build. A freshly compiled standalone mock lifecycle suite passed 10/10, including held analysis reply after a position switch. Prior 172/172 Node regression remains applicable to the hash-matched source and was not needlessly repeated.

Remaining strict acceptance limit: exact in-flight position-switch timing could not be reliably observed through CUA navigation within the one-second search. Keep the held-reply mock evidence distinct from actual Simulator execution; do not claim the full strict checklist is complete. No new runtime failure or code defect was found. Local Simulator approval is already granted and remains valid for the same scope. No physical phone, glasses, capture-age or audible-output validation, commit, push or distribution occurred.

Current evidence and quickstart: `/Users/alexmunzon/Documents/Codex/2026-11-12/task/outputs/chess-simulator-followup-2026-11-13/` (`results.json`, `identity.json`, `promotion-rules-check.json`, `mock-lifecycle.json`, `Quickstart-and-results.md`). Historical evidence remains untouched in the adjacent `chess-simulator-runtime/` folder.


## Approved Simulator UI checkpoint — partial

The local iPhone 17 / iOS 26.2 Simulator test is now explicitly approved. The app was ad hoc signed, strictly verified, installed and launched on the existing Simulator. Actual UI flows produced `e2e4` from the starting position, `c7c5` after 1. e4 and `e1d2` from the en passant fixture. Each visible text matched a separate Node rules/text check. Four-of-five review blocked validation; unchecking a review revoked the recommendation; incomplete FEN was rejected. Promotion recognition and sample FEN loading passed, but promotion analysis remains untested.

One UI fix makes each recognized square a single labelled accessibility element; duplicate child labels disappeared in the Simulator. The full Node suite passed 172/172 after the change; the updated Simulator build compiled, signed and passed strict signature verification. Independent read-only review found no remaining concrete code issue. Native scroll/drag repeatedly failed with CUA `noWindowsAvailable`; exposed AX Scroll Up/Down actions worked intermittently, including after rotation to landscape. The last screenshot call was aborted by the user, so UI interaction paused without retry. This is a partial actual-Simulator checkpoint, not a completed offline acceptance milestone.

Remaining actual UI checks: promotion review/analysis, obstructed-board blocking, invalid rules-state FEN with matching placement, reset, background/foreground invalidation and in-flight switching/late completion. Existing mock evidence for these lifecycle gates remains distinct. No physical phone, glasses or audible output validation occurred. The existing local Simulator approval remains valid; no further permission is pending for these same tests. Preserve all prior work, the original unsigned artifact and consumed Mac approvals. No commit, push or distribution occurred.

Exact current evidence, commands, source/artifact hashes, observed outputs and limitations: `/Users/alexmunzon/Documents/Codex/2026-11-12/task/outputs/chess-simulator-runtime/` (`runtime-journal.json`, `rebuild-report.json`, `rebuild-signing.json`, `observed-move-checks.json`, `npm-test.txt`, `independent-review.md`). The signed updated build is at `/private/var/folders/40/pkx1ymn10_s42501bl5799wh0000gn/T/chess-accessibility-build-x711t4_3/build/ChessCompanion.app`; bundle ID `local.chesscompanion.offlinestudy.simulator`; destination UDID `746F2CEB-102D-4CFC-8D11-A5924705537F`.


## Composed Mac fix and multi-position Simulator build

The composed Mac harness passed after disabling inactive scheduling for the detached WebKit engine. Three 1,000 ms real Stockfish searches completed, as did three separate legal-text checks. Occlusion, incomplete and mismatched review, edit, reset and late completion after backgrounding passed. The first move was `e2e4`, and the harness used a text-only sink. [Full Mac result](/Users/alexmunzon/Documents/Codex/2026-11-12/continue-my-chess-project-using-the/outputs/Composed-Mac-Result.json).

An unsigned arm64 iOS Simulator build now bundles four playable positions plus an obstructed board. All 172 Node tests passed. All ten mocked lifecycle cases passed, including a held engine reply after position switching. Mac pixel checks matched each playable image's 64-square reference and preserved 16 unknowns for the obstructed board. Mac asset checks rejected partial and extra manifests and a tampered fixture. Separately, the Node worker produced a rules-checked recommendation for all four playable positions. Simulator signing, installation, launch and interaction are pending. No physical iPhone, glasses or audio test ran. [Build and exact source hashes](/Users/alexmunzon/Documents/Codex/2026-11-12/continue-my-chess-project-using-the/outputs/Simulator-Build-Evidence.json).

## Mac page timers, Worker output and cancellation

One Mac run at the existing deadlines sampled one `infoString` and seven `infoDepth` messages after Go. The 100 ms page probe fired on schedule by the page clock. The frozen trace recorded neither the 1,000 ms probe nor the 2,500 ms search timer, and it contained no Worker error or best move. The native timeout, Swift cancellation dispatch and JavaScript Worker abort signal carried the same request ID. The trace ended before an analysis reply arrived, so the failed reply code was unavailable. The 11 recognition and review assertions passed. No legal text or output was produced. [Execution record](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-project-at-users/outputs/worker-timer-trace-2026-11-12/execution.json).

Seven simulated Worker cases exercised classification, sampling limits, timer delivery and error codes. All 172 Node tests passed. Independent review checked both the prepared Mac build and the result. [Checkpoint](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-project-at-users/outputs/worker-timer-trace-2026-11-12/STATUS.md).

## Mac search command, Worker callback and timer

One Mac evaluation at the existing deadlines verified that posting `go movetime 1000` returned and the page received a Worker message callback 3 ms later by its clock. The trace does not capture that message's contents. The report contains no Worker error, JavaScript search timer, or best move marker. Swift's timer expired 15,007.84 ms after dispatch. JavaScript finish then appeared and a failed reply reached Swift 5.09 ms after the native timer marker. The order is consistent with cancellation following the native deadline. The late reply's error code and the reason for the absent JavaScript timer marker remain unknown. Synthetic recognition and FEN validation passed, with zero legal-text or text-sink calls. [Execution record](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-project-at-users/outputs/worker-search-trace-2026-11-12/execution.json), [raw Mac report](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-project-at-users/outputs/worker-search-trace-2026-11-12/mac-run.stdout.json).

Five simulated Worker cases verified the new markers and reply routing. The full Node suite passed 172/172. The trace remains Mac evaluation evidence, and the prior unsigned build remains the extent of iPhone verification. [Checkpoint](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-project-at-users/outputs/worker-search-trace-2026-11-12/STATUS.md).

## Mac dispatch and Worker trace

The offline synthetic image and complete FEN review assertions passed again. The position validation reply reached Swift. For the first analysis, Swift dispatched the request, JavaScript received it, the Worker constructor returned, and Stockfish answered `uciok` and `readyok`. JavaScript recorded the attempt to post `go movetime 1000`. The native timer fired 13,957.02 ms after receipt of that marker. The captured trace has no best move, engine completion or failure, JavaScript analysis reply, legal-text call or text-sink call. The Mac process exited 1 after 24,662.15 ms. [Execution record](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-project-at-users/outputs/worker-trace-2026-11-12/execution.json).

The Go marker precedes the call to `postMessage`. The present trace cannot establish whether that call returned, a later Worker event arrived, the JavaScript timer ran, or engine cleanup began. The focused Node simulation verified trace ordering and per-request correlation. The full Node suite passed 172/172. Independent review verified the generated sources and assets and checked the interpretation of the run. The existing unsigned iOS artifact retains its prior compile-only evidence. [Trace checkpoint](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-project-at-users/outputs/worker-trace-2026-11-12/STATUS.md).

## Composed offline study — recognition/review pass; first analysis times out

The corrected adapter and saved builds were hash-verified before one approved Mac run. It failed in 21,932.40 ms with a generic native deadline error; that report cannot distinguish the analysis/text-check cycle or operation. The original generic result remains unchanged. [Execution](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/composed-study-resume-2026-11-12/execution.json).

A narrow evaluation-only diagnostic change preserves all nine production sources, original calls/predicates and deadlines. Foundation-only checks passed **17/17** and independent source review found no remaining concrete issue. The diagnostic harness compiled cleanly from 11 exact snapshots. A separately approved run exited 1 in **21,536.72 ms**: **firstAnalysis**, analyze ordinal 1, expired after **15,010.27 ms**. There were zero completed analyses, legal-text calls or text-sink calls; stderr was empty. Initial automatic permission review timed out before dispatch; the tool-permitted retry launched exactly one process. [Diagnostic preparation](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/composed-study-resume-2026-11-12/diagnostics/preparation.json), [execution and trace](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/composed-study-resume-2026-11-12/diagnostics/execution.json).

Eleven assertions passed: pinned synthetic inputs/runtime manifest, local asset readiness, the expected 16 unknown squares and blocking, exact 64-cell agreement with a separate frozen reference/FEN, no inferred review fields, incomplete/mismatched-review rejection and full reviewed FEN validation. This verifies the corrected integer-confidence path for these two synthetic images. Review is scripted ground truth, not live human confirmation. Worker creation, UCI readiness, actual search and JS/native reply progress remain unobserved. No Stockfish result, explicit output, edit/reset or delayed-background acceptance was reached in this run. No cause or need to increase deadlines is established.

The same 1,000 ms searches plus separate legal-text checks passed twice under Node in **1,467.15 / 1,361.74 ms**. That is a separate-runtime comparator, not a WebKit explanation. The required full Node suite passed **172/172** with the existing loopback authorization. [Comparator](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/composed-study-resume-2026-11-12/node-budget-probe.json), [regression](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/composed-study-resume-2026-11-12/npm-tests.txt), [independent review](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/composed-study-resume-2026-11-12/review.md).

The earlier 3.91-second composed failure at occluded-image recognition and its native Int/Double correction remain preserved in [the prior record](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-project-at-users/outputs/composed-study/execution.json). The corrected iOS artifact is still unsigned and was read as a resource directory only. No iPhone/simulator/glasses/camera/audio execution occurred. The next bounded dispatch/Worker trace is queued in HANDOFF.md; no automatic retry is running.

## Native preparation — current bounded evidence

The user-selected architecture is an entirely iPhone-local runtime on iPhone 17 / iOS 27.2: recognition, state/rules, Stockfish and speech. The Mac remains a build/evaluation host. The modules below are preparation for that integration; there is no completed, installed or hardware-validated iPhone app. The final full Node regression for the native backend/replay continuation passed **172/172**, with zero failures or skips, including the previously authorized loopback HTTP checks. The earlier 138-test count below belongs to the preceding simulation tree.

| Check | Observed result | Limit |
| --- | --- | --- |
| Installed SDK inventory | iPhoneOS and iPhoneSimulator 26.2 SDK paths exist; SDK queries succeed | Does not repair or explain generic Xcode destination selection |
| Direct DAT 1.0.1 device probe | Swift 6.2.4 typecheck exit 0, 8.20 s; unsigned library link exit 0, 1.03 s | Imports/typealiases only, no SDK calls or app build |
| Swift synthetic recognizer | 78 reused PNG frame records / 4,992 square decisions, zero Python/native disagreements including abstentions; geometry availability agrees | Mac port conformance for known artwork/markers, not fresh held-out or physical accuracy |
| Swift recognition of decoded video | 78 actual MP4-decoded frames / 4,992 decisions, zero Python/native disagreements; geometry agrees | Same synthetic sequence decoded by FFmpeg on Mac; no native iPhone video decoder or hardware result |
| Native capture contracts | 10/10 Mac mock lifecycle checks; direct iOS/DAT typecheck passed | Mock pixels/rules/engine/speech; no real camera or audio |
| Native local engine host | iOS ARM64 typecheck passed; separately authorized Mac WebKit fixture passed rules, actual Stockfish and cancellation in 1,482.83 ms | Mac fixture only; iPhone Worker/WASM, memory and app behavior unverified |
| Portable replay continuity bridge | 10/10 focused tests using real chess.js rules | Standalone and unbundled; explicit review fixtures and replay clock, no native continuity or output permit |
| Native recognition/rules/runtime adapters | 13/13 standalone Swift checks; complete iOS source typecheck passed | Mock transport/runtime plus frozen real DeviceBackend/Stockfish JSON acceptance, no additional WebKit/device/audio execution |
| Offline iPhone study app | 8/8 mocked lifecycle checks; full source compiled/linked and private resources assembled, no `LC_CODE_SIGNATURE` | Unsigned arm64 iOS 17.2 app; never installed/launched, no actual UI/pipeline or audio verification |

The DAT probe used the installed iPhoneOS 26.2 SDK and target `arm64-apple-ios17.2`. Read-only inspection found an arm64 iOS dynamic library with minimum OS 17.2, both DAT framework load commands and no `LC_CODE_SIGNATURE`. Its Mach-O build-version SDK field is 17.2, while the invoked SDK path/settings are 26.2; both facts are preserved without assigning a cause. The earlier generic `xcodebuild` simulator/device errors remain recorded failures, but the inference that a compiler SDK installation or upgrade was required is withdrawn. No app signing, installation, account, pairing or device action was performed.

The 78 vision records contain 37 distinct image hashes and 372 unknown-square decisions; agreement includes abstentions and is not 4,992 correctly identified pieces. Native vision also passed a direct iOS typecheck, but that mode excludes `SWIFT_PACKAGE`: `Bundle.module` and real package resource copying remain unverified. PNG port conformance does not establish native/Pillow JPEG or color-profile parity. The recognizer still emits review-only pieces with no inferred historical state. Native capture tests check bounded queues, frame/review identity, cancellation, legal-output validation through injected mocks and stale-speech rejection. DAT media timestamps are not treated as host capture times; unknown real capture age blocks all engine/speech permits.

The native runtime source serves bundled rules/Stockfish assets through an isolated WebKit host, without a Mac service. The user explicitly approved its bounded offline WebKit fixture. The first default-sandbox attempt exited 1 after macOS could not create WebKit/LaunchServices sandbox extensions. A separately approved single expanded-command run of the same executable and local v2 bundle exited 0: full starting-position validation, actual Stockfish `e4` with regenerated text, and cancellation passed in 1,482.83 ms; stderr was empty. This establishes custom-scheme modules and Worker/WASM for that Mac fixture. No browser profiles, camera, microphone, glasses or audible speech were used. iPhone behavior and app integration remain open.

The executable hash is `b4f09e58cc1d70cc58393cc70e041a98f8d96302cf377c96e2c7b1fb459680b8`; the tested host source hash is `52d82cc4b7d90318e011048324479d3d8ad968fcf8ede5c4130dbc20b9ff6713`. A subsequent entry cancellation check protects a newer request from an already-cancelled old task; that final source is compiled and contract-tested separately, without another WebKit execution. Exact commands, both outcomes, log hashes and scope are preserved in `outputs/native-readiness-2026-11-11/runtime/webkit-execution.json` in the continuation session.

The current private engine asset manifest is `471e56746249cb421a59c2466d2febf2ff1791af16b6391efb79aafb44fc47d5` (`work/iphone-runtime-assets-v2`). The earlier v1 manifest is preserved. The v2 backend echoes the original normalized FEN and checked move in rules replies for native validation. The full WASM is 99,169,054 bytes. This bundle does not yet include the standalone replay continuity bridge; no native continuous-game assembly is claimed. The runtime and integration Swift package manifests are source definitions only; package execution/resource assembly remains unverified.

`native/ChessCompanionIntegration` connects native recognition and capture contracts to local rules/engine transport. It validates exact full FEN, request/frame identity, safe JavaScript integer ranges and checked move fields. Invalid new requests revoke prior work; cancellation stays scoped to the owning task even across wrappers. The frozen real JS fixture used actual Stockfish with a 100 ms search request (depth 12, reported search time 105 ms); Swift accepted unchanged FEN, move, successor position, status and speech fields, with only request ID and test identity rebound. This verifies the cross-language JSON contract separately from WebKit. The synthetic adapter accepts only explicitly trusted replay frames and rejects DAT input. Evidence: continuation `outputs/native-readiness-2026-11-11/integration/summary.md`.

The offline app builds monolithically from exact shared-source snapshots. It assigns no live capture timestamp to the saved fixture and leaves live glasses mode unavailable. The first full compile hit a Swift 6.2.4 IR-generation crash; explicit SwiftUI callback closures fixed the second build without a toolchain change. Both logs and the successful resource/binary hashes are retained in continuation `outputs/native-readiness-2026-11-11/app/`. Binary SHA-256: `8e7a95adf261112068649dbb21850e756e4b15f98559fb52f77aae3632e09df4`. Package-based builds, signing/install, app launch, phone layout/performance and audible output remain unverified. The final full Node regression after app source changes passed 172/172; the mocked app checks are separately scoped.

Evidence: continuation [native-readiness outputs](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/native-readiness-2026-11-11/), including [direct probe and binary inspection](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/native-readiness-2026-11-11/direct-probe/summary.md), [vision conformance](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/native-readiness-2026-11-11/vision/port-conformance.json), [vision build scope](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/native-readiness-2026-11-11/vision/build-evidence.json) and [capture checks](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/native-readiness-2026-11-11/capture/summary.json). Module contracts and remaining runtime gates are in `native/ChessCompanionVision/README.md`, `native/ChessCompanionCapture/README.md` and `native/ChessCompanionRuntime/README.md`.

## Completed simulation milestone — preceding verified tree

The simulation-first continuation is implemented: original vector-piece renderer, frozen legal fixtures, separated pixel index/truth sidecars, visible-marker/template pixel recognition, review-only UI/API, and actual PNG/decoded-MP4 evaluation through legal tracking, Stockfish and a **text-only** speech sink. The recognizer receives opaque image bytes only, without FEN, filenames encoding state, labels, seeds or scene metadata. The interactive app still requires real user review; the evaluator explicitly uses an automated initial-state fixture.

Final results for **each** input path (78 PNGs / 78 decoded MP4 frames):

| Check | Result |
| --- | --- |
| Development exact accepted boards | 54/54 |
| Held-out sequence/scene exact accepted boards | 14/14 |
| Challenge frames withholding guidance | 10/10 |
| Incorrect accepted squares / boards | 0 / 0 |
| Required stable legal full-state checkpoints | 34/34 |
| Stale-session probes blocking engine/text output | 15/15 |
| Actual bounded Stockfish → text speech | 1 legal recommendation |

Known template artwork and visible colored markers limit these results. Frames are correlated pairs; opening splits share an initial board and all positive frames share piece artwork. The challenge set covers hand-like occlusion, missing marker, unfamiliar slender pieces, white-patch glare approximation and severe blur. Motion is stepped, not continuous physical camera motion. Replay uses deterministic timestamps; per-frame wall medians were 267.55 ms (PNG) and 233.76 ms (decoded video), so this is not proof of live 10 fps processing. No physical-board, phone, glasses capture, actual browser interaction or heard-audio result is claimed.

Independent review fixed transparent inputs exposing hidden RGB pixels and an evaluation gap that allowed correct pieces to mask failed legal tracking. Nonopaque PNG/WebP inputs now reject, including palette transparency; opaque RGBA remains supported. Tracking coverage independently fails skipped-move sequences. Recognition thresholds/templates were frozen before first held-out inference and unchanged by these validation/scoring fixes. The initial report remains preserved separately.

At the end of that simulation milestone, combined `npm test`: **138/138 passed**, including 12 local HTTP tests and actual rendered pixels → review-only draft → explicit automated review fixture → real Stockfish → speech text. The local listener used the user's existing approval. Eight Python suites: **63/63 passed**, including 15 synthetic pixel, 11 manual calibration and existing recognition/metric tests. These runs predate the native continuation above. No original Apple Vision runtime retry was made: its recorded CVPixelBuffer blocker is unchanged. No additional CoreML model run was made in that final simulation regression.

The manual photo/corner flow also completed its actual development-image smoke: image-bound reviewed geometry, 64-square proposal, 35 explicit unknowns, every historical field unset, no engine/speech invocation, and request temporary files removed. These are workflow checks on an old development photo, not new physical accuracy.

Authorized dependency checks at that stage: DAT 1.0.1 resolved at revision `0bd369298eef6a980ad0bdb6c8a5502f2c02a08c`. Both generic signing-disabled compile checks exited 70 **before compilation**, reporting the missing iOS 26.2 platform. Import compatibility was untested then; the later installed-SDK inventory and successful direct probe above supersede that limitation for the small import/typealias surface. No installation/upgrade/signing/account/device action followed. The separate authorized GPU-visible CoreML comparison recovered the historical outputs but still failed 1/2,496 logits; the restricted-runtime 33/2,496 result remains separately preserved. Both authorized public media downloads returned HTTP 403; those acquisition routes are closed.

Evidence: continuation `outputs/simulation-2026-11-11/` contains `png-report.json`, `mp4-report.json`, the original report, frozen/final source hashes, corpus, video, quickstart and final verification logs. `outputs/completion-build-2026-11-11/` contains the manual-photo, CoreML, acquisition and SDK evidence. See `SIMULATION_PLAN.md` for commands and the optional later ordinary glasses capture of a displayed board. All prior dirty work and blackjack are preserved; no browser access or permanent permission settings were changed.

## Earlier continuation records

The following sections preserve earlier iterations; the dated results above supersede their current-status statements where new evidence exists. Older unknown-phone and missing-SDK statements are historical, not current blockers.

## Bounded numerical diagnosis — latest iteration

The original numerical failure was independently reproduced from preserved artifacts: one logit exceeds the unchanged tolerance. Model/reference hashes, normalized input bytes, tensor shapes/layout/class order, numerical comparison arithmetic and output indexing checked out. A separate versioned runner recorded one prediction followed by three on one loaded model: all four outputs per input were identical, but each full three-reference comparison failed **33/2,496 logits**, with all 192 labels matching. The unchanged pinned executable reproduced the current case-0 diagnostic output exactly. Numerical validation remains **failed**, with original and current results preserved separately.

Current runtime: macOS 15.7.4, CoreML 3405.2.1, requested CPU_AND_GPU, low-precision accumulation disabled; no default Metal device was visible. Exact backend/device assignment and the cause of changed historical outputs remain unproven. Shared compile/load was 1.468 seconds, and every measured prediction exceeded one second. No optimized runner, model replacement, tolerance/threshold change or live-deadline change was adopted. Details and exact decision: `NUMERICAL_DIAGNOSIS.md`.

One evidenced harness-provenance bug was fixed: `tests/recognition_whole.py` now removes inherited CPU-only configuration and checks every native output's explicit configuration before labeling/scoring it. This does not explain the saved outlier or repair numerical parity. **5 numerical/profile tests, 5 normalization tests and 42 review/lifecycle tests passed**; `git diff --check` passed. The initial default-temp-directory failure is retained; the successful invocation used the existing photo bridge's private-TMPDIR pattern within current writable paths, with no permission change. No original Vision retry, HTTP rerun, download, install, browser or device action occurred in this iteration. Outputs: `numerical-diagnosis-2026-11-11/` in the continuation session.

## Authorized HTTP follow-up — latest result

After the user explicitly authorized local loopback tests, `node --test tests/server.test.js` ran with per-command sandbox escalation: **7/7 passed**, exit code 0. This resolves the previous HTTP EPERM blocker for this authorized run. Coverage includes request/confirmation contracts, real local Stockfish over HTTP, cancellation/client disconnect, stale engine/recognizer rejection, image request limits and review-only recognition output.

Together with the earlier **93/93 non-HTTP Node tests**, all **100 Node tests passed across the two runs**; the earlier **35/35 Python tests** also passed. No implementation changed between those final runs. This is not a fresh combined full-suite invocation. No permanent permission configuration, browser or device access was used. The recognition, numerical, latency, new-footage and physical-device limitations below remain unchanged.

Exact command/output and authorization scope: session outputs `http-verification-2026-11-11/`. Earlier statements that HTTP tests were excluded or permissions were not expanded describe those earlier iterations; this follow-up used only the newly authorized test scope.

## Recorded input and measured processor latency — latest iteration

Added a bounded `RecordedFrameQueue`: one active processor plus one latest pending frame, explicit offline source/session/sequence identity, monotonic timestamps, actual frame-byte hashes, an 8 MiB frame bound, freshness watchdog, cancellation and review-only results. Reconnect, delayed completion, ignored aborts, serialization callbacks and changing input properties cannot restore old guidance or bypass frame ordering/bounds. The queue is not wired to an engine, speech, browser or glasses SDK.

Final permitted tests: **93/93 Node**, including **19 queue regressions**, and **35/35 Python**. Real local Stockfish is included in the Node suite; most capture/output lifecycle cases use injected adapters. The seven HTTP cases remained excluded because their loopback EPERM restriction was already recorded and retrying was declined. No original Vision runtime retry occurred. `git diff --check` passed.

Actual offline photo-processor checks used only the old Staxringold development image:

- An explicitly offline 15-second queue window produced a review-only proposal in **11,582.52 ms**, preserving `numericalValidationPassed:false` and exact model/runner/frame hashes. No engine or audio was attached.
- The unchanged default **1,000 ms** deadline aborted the real processor; it settled in **1,097.02 ms**, published no proposal and left no new request temp directories. This measures watchdog/process cleanup, not a hard real-time guarantee.
- A second standalone process completed in **11,423.94 ms**. Compile/load took 1,653.10/1,391.13 ms; individual predictions in the shared loaded model took **2,797.89–3,549.30 ms**. The existing runner makes three predictions per image. These are cached-environment diagnostics, not a clean cold-start or device benchmark. Startup is not dominant; a persistent worker alone cannot meet one second. No deadline, pinned runner, threshold or numerical gate was weakened. See `LIVE_PIPELINE.md` for stage timings and the next separately versioned single-pass diagnostic.

Connected page retrieval found two public, distinct-author video candidates with source/license evidence. One ordinary native media download per candidate failed with `URLError: <urlopen error [Errno 8] nodename nor servname provided, or not known>`. No retries, permission changes or browser fallback followed. No new frames, labels or recognition scores exist; source suitability and training overlap remain unknown. `PUBLIC_VIDEO_SOURCES.md` records the candidates and the accessible-media dependency. The automatic geometry arm was **not run**, not scored as abstention.

Final branch/HEAD remain `main` / `412397d513c99cb2f1485b676ff033563d2947f2`. Blackjack remains clean at `c60a2d16087e5def1681538b13ec0c2697d24046`. Prior dirty work, historical media/model artifacts and earlier evidence were preserved. No browser, permissions, installs, SDK/device setup, commit, push or publication occurred. Session outputs: `/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/recorded-input-2026-11-11/`.

## Geometry-comparison iteration — November 11, 2026

The proposed **new held-out A/B experiment did not run**: no ready fresh independently annotated local set has all four visible corners, and the existing Apple Vision execution failure remains unresolved. No permission expansion, browser, alternative detector/runtime bypass, downloads, installations or SDK/device setup occurred. The inspected unused Pexels 6184294 samples are cropped/blurred/occluded and unsuitable for clean geometry isolation; upstream training overlap is also unknown. Paired phone details remain unknown and are not a prerequisite for this offline work.

Completed instead:

- Added `scripts/recognition/replay_geometry_comparison.py` and `paired_metrics.py`: strict recorded-artifact comparison using the same cstr classifier contract and preexisting fixed canonical orientation. No new detector/classifier inference runs inside the evaluator. It binds source/model/code/manifest hashes, joins geometry artifacts to their historical run, rejects malformed geometry and mismatched source/model/threshold data, separates runtime errors from genuine detector abstention, and always labels the result development replay.
- Replayed the existing five diagnostic video frames. Automatic geometry abstained 5/5 times, so raw classifier accuracy is **null**, not 0%. The annotated-corner control has 7/74 raw known occupied types correct; **0/74 accepted-correct yield**, and **15/15 accepted known occupied-type predictions wrong** (all false empty). Unknown/occluded cells remain unscored; exact-board accuracy is null for both arms. Full denominators and class/color/score-bin/temporal analysis are in `PAIRED_EVALUATION.md`. No confidence threshold or recognition behavior was tuned. Evaluator/error reporting improved; recognition accuracy did not.
- Verified the existing CPU ONNX classifier still runs on one reused development frame, reproducing all 64 saved labels and confidence values exactly. Approximate load 446 ms, crop/inference 510 ms, one Mac diagnostic. This checks the existing classifier path only; it is neither a Vision replacement nor a fresh held-out result.
- Tested an actual saved erroneous proposal against the current draft/live boundaries: all historical fields stay unknown, incomplete FEN validation fails, direct proposal ingestion is rejected, and **zero engine calls / zero spoken messages** occur. `LiveSession` still requires a separate caller human-review assertion and valid fresh stable legal observations; that boolean is caller responsibility, not proof of actual human review.

Fresh permitted regressions: **74/74 Node tests**, **35/35 Python tests**. The Python total includes 18 new metric/artifact-boundary regressions plus the existing 17. Actual app-handler tests cover complete draft-history/review gating and stale imports; existing observation/live-session tests cover unknown squares, illegal/skipped transitions, stability/timeouts and stale speech. No redundant live-state subsystem was added. `git diff --check` passes.

The seven HTTP tests were excluded due to the previously recorded loopback EPERM and the instruction not to retry. Native Vision calibration, a new held-out geometry run, fresh full two-arm inference, numerical CoreML revalidation, browser recognition, physical capture and actual audio remain not run. Previously recorded exact environment errors remain in the earlier record below.

Reproducible protocol/results: `docs/PAIRED_EVALUATION.md`. Session outputs: `/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/geometry-comparison-2026-11-11/paired-replay-verified.json`, `classifier-runtime-check.json`, `review-boundary.json`, and `checks/`. Original evidence artifacts were not overwritten. Blackjack remains clean; no commit/push/publication.

The small next data requirement is a new source-disjoint recording with all four playing-surface corners, visible canonical coordinate evidence, several varied positions, frozen timestamps/corners, and independently reviewed per-square piece/color/occupancy labels with unknown reasons. Keep hand/motion/partial-board segments as separate abstention challenges; keep another source untouched for any tuning. Record training-exclusion evidence where available, otherwise state unknown overlap. Both arms must then run the same unchanged classifier/preprocessing in an authorized environment with the original detector functioning. Legal histories are not invented for geometry scoring; real continuous guidance needs a separate reviewed initial state and device tests.


This continuation reconciled the prior-worker handoff and preserved the existing dirty tree before completing focused fixes. Branch remains `main` at `412397d513c99cb2f1485b676ff033563d2947f2`; no commit, reset, cleanup, push or deployment. Blackjack remained clean at `c60a2d16087e5def1681538b13ec0c2697d24046`. No browser, camera, microphone, Bluetooth or permission changes were used.

## Current fixes and fresh permitted checks

- Photo proposals keep turn, castling, en passant and both move counters unknown. The editor requires explicit values, including an explicit castling-none choice. Invalid drafts clear the FEN preview; direct FEN loading cannot bypass draft review. Delayed JSON imports cannot overwrite resets, confirmations or newer imports. These are actual app-handler tests in a minimal DOM harness, not a browser test.
- LiveSession retains speech cancellation identity after an adapter acknowledges queued audio. Uncertainty, changed board, timeout, reconnect and stop abort queued/current output. Failed speech, including non-Error rejection, cancels output and permits retry. Adapter compliance and real audible output remain unverified.
- Numerical model diagnostics preserve the JSON/stdout report and exit 1 when numerical validation fails. The saved failed report exercised this path; the comparison itself still fails one logit and inference was not rerun.

Final permitted Node suite: **74/74 passed**, excluding `tests/server.test.js` because retrying its seven blocked loopback cases was explicitly declined. This suite includes real local Stockfish startup, legal move/mate, timeout/cancellation, legal tracking, review/import guards and speech lifecycle mocks. Exact command selection and output are in the continuation outputs. The prior worker's historical 76/76 pass predates these fixes and does not certify this tree.

Python offline regressions: **17/17 passed** (`recognition_numerical_gate.py`: 3, `recognition_video.py`: 5, `recognition_video_controls.py`: 4, `recognition_photo.py`: 5). These verify report exit status, partial-label scoring, crops/transforms and normalization, not real-board accuracy.

`node scripts/replay-live-session.js` passed with synthetic reviewed square labels, actual Stockfish, and text-only speech: “pawn from e2 to e4.” at reported depth 11. No camera or audio output was used. `git diff --check` passed.

## Blocked or unverified in this environment

Initial `npm test` ran 76 tests: 69 passed; seven HTTP cases failed to bind loopback with `Error: listen EPERM: operation not permitted 127.0.0.1` (`code: EPERM`, `errno: -1`, `syscall: listen`). They were not retried after the instruction to leave permissions unchanged. This is a runtime restriction, not evidence of seven application assertion failures; final HTTP behavior remains unverified here.

Swift compilation succeeded with an explicit `/tmp` module cache after the default cache location was denied. Apple Vision execution then exited 1 with `sysctlbyname for kern.hv_vmm_present failed with status -1` and `NSOSStatusErrorDomain Code=-6662`, “Failed to create CVPixelBuffer Width = 256, Height = 256, Format = 'BGRA'”. This occurred in sandboxed execution; its root cause is not proven. No fresh macOS calibration or video inference succeeded, and no permission expansion or browser fallback was attempted.

Current browser recognition journey, audible speech, paired phone/OS, Meta registration/capture, Gen 1 audio routing and camera/audio coexistence remain unverified. Current iOS sample requirements exceed the previously recorded local toolchain. Official iOS issue #358 also reports camera/TTS contention on Gen 2; applicability to this Gen 1 pair is unknown. See `HARDWARE_COMPATIBILITY.md`.

## Recognition evidence remains a failed gate

Saved genuine-video results: automatic geometry **0/5 detections**; raw whole-photo classifier **0/74 known occupied types correct**, with **120/236 accepted known labels wrong**; annotated-corner ONNX control **7/74 known occupied types correct**. Unknown/occluded predictions were often accepted. The tiny 2/3 exact starting-photo result does not establish general accuracy.

This continuation reproduced all saved metrics for the ten raw/rotation predictions using the current scorer and frozen labels, without rerunning inference. The current evaluator hash differs from the saved report for an unknown reason; manifest and preprocessing hashes match. Historical evidence remains unchanged. No exact-position or complete-FEN score is available for the partial-label video; four-second sampling cannot validate the default one-second tracker freshness window.

Snapshot, logs and exact error text are preserved under `/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/`. `docs/VIDEO_EVALUATION.md` specifies the next held-out comparison of automatic and independently annotated geometry. Automatic vision-to-speech remains disabled.

---

# Historical baseline verification — November 10, 2026

Environment: user's Mac, Node 24.21, installed Apple Swift/Vision/CoreImage and Python/Pillow/NumPy. Local loopback only. No camera, microphone, Bluetooth, glasses or external chess account used.

## Automated software tests

`npm test`: **55 passed, 0 failed**, approximately 2.1 seconds on this run. Complete log: `evidence/all-tests.txt`.

Coverage includes:
- Start-position perft 20/400/8902 and Kiwipete 48/2039.
- Castling, en passant, all promotion choices, mate, stalemate and material checks.
- Claimable fifty-move threshold versus automatic seventy-five-move threshold, with checkmate precedence.
- Rejection of impossible castling/en-passant state and promotion inventories; not a claim of full historical reachability validation.
- Real full Stockfish startup, legal best move, mate in one, bounded search, illegal-output rejection and actual child-process cancellation (about 104 ms in the test).
- Human review, stale/foreign request rejection, FEN mismatch, cancellation and interruption.
- Delayed move responses: the actual app's event handlers disable confirmation/analysis during mutation, recover after failure and discard superseded responses. This is a minimal DOM test harness, not a second browser test.
- Loopback Host/Origin rejection, unsupported paths, content type, oversized JSON, static asset allowlist/CSP and real HTTP-to-Stockfish result.
- Twenty-six synthetic labeled-observation replay/tracker tests. These cover special moves, unknown/low-confidence squares, timeouts, source/epoch/sequence ordering, repeated observations, stable frame spans, identical-board revision preservation, changed-board invalidation and bounded replay. **These are not image recognition tests.**

`npm audit --omit=dev`: **0 vulnerabilities** reported. This is the registry audit result, not a comprehensive security certification. Evidence: `evidence/dependency-audit.txt`.

## Actual Chrome interaction

The browser loaded http://127.0.0.1:4174 and visibly confirmed:
- Initial board, manual e2–e4 practice move, explicit confirmation and Stockfish's legal e5 response. Observed depth 21, search elapsed 1,507 ms, score −0.26 for Black.
- Starting-board analysis returned e4 at depth 20, 1,503 ms. Search depth and chosen moves vary by runtime and budget.
- Invalid FEN removed analysis/highlights and disabled analysis; reset recovered.
- Cancel immediately cleared output and required confirmation again.
- Checkmate showed no legal move and disabled analysis.
- Board flip changed first displayed square from a8 to h1 and back.
- Manual setup rejected an empty board for missing kings. Placed White king g6, White queen f7 and Black king h8, validated, confirmed and obtained **Qg7#**, mate score 1. This was a manually entered board, not recognized from an image. The engine reported depth 245 after 54 ms for this trivial forced mate; depth is engine output, not an independent strength metric.
- Final correction checks: halfmove 100 remained analyzable with a draw-claim status; eight white pawns plus two queens was rejected.

Screenshots: `evidence/chess-ui-2026-11-10.jpg` and `evidence/chess-manual-mate-2026-11-10.jpg`. No mobile viewport, local-file chooser, audio, phone or glasses test is claimed.

## Board calibration lab

Recompiled with `swiftc native/BoardVision/BoardCandidates.swift -o /tmp/chess-board-candidates`, then reran `python3 tests/vision_calibration.py /tmp/chess-board-candidates /tmp/chess-vision-benchmark-integration`. Evidence: `evidence/vision-tests.txt`.

- Four of five synthetic positive scenes proposed boards: frontal, perspective, rotation and glare. Blur abstained.
- Two negative controls, covered and plain rectangle, abstained.
- Detected synthetic mean corner error: 9.74–11.27 source pixels on 800×800 scenes.
- Manual four-corner mapping/orientation, 64-square grid, geometry rejection and human-confirmation gates passed.
- One real physical chessboard photo, Staxringold's Wikimedia CC BY-SA 3.0 starting position, produced **no automatic candidates**. Source/license and result: `native/BoardVision/README.md` and `benchmark-2026-11-10.json`.

This tiny diagnostic set is not real-world accuracy evidence. No piece classifier or FEN-from-image capability exists. Automatic calibration remains experimental; manual calibration is separate from confirming a complete chess position.

## Review corrections incorporated

An independent read-only review found three medium issues: claimable draw treated as terminal, impossible promotion inventory accepted, and a pending-move analysis race. All were corrected with new regression tests and final browser checks where applicable.

## Remaining gates

Independent real-image/video recognition dataset and classifier; calibrated confidence/abstention evaluation; integration of actual recognizer observations with state tracking and UI; complete move-history/repetition adjudication; phone/glasses SDK/device compatibility, capture permissions/transport, interruption/reconnect tests, output/audio and on-device heat/battery/latency. Current observation tracking is a tested standalone seam, not wired into browser analysis. Source-only prototype packaging does not constitute GPL binary-distribution review.
