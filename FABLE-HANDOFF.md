# Chess Companion: handoff for the next Fable orchestrator

Written November 16, 2026, about 05:45 Madrid; last updated November 17, 2026, about 08:20, after an
overnight session (see "Session 2026-11-17" below). UPDATE 2026-11-17 about 11:40: Alex said "Yes, commit";
everything up to here is committed as the 2026-11-17 checkpoint (`git log -1`), NOT pushed. Where sections
below say "uncommitted", read "committed 2026-11-17, not pushed". Last commit `e482729` on `main`, pushed to the PRIVATE GitHub repo
`alexmunzon/chess-practice` (remote `origin`, created 2026-11-16 on Alex's words; every further push
needs his words again). Everything in the "Afternoon session" section below is uncommitted. You are a Fable session that plans, assigns, integrates and reviews; Opus
workers do the focused build work. Read this file first, then `CLAUDE.md` and `AGENTS.md` (binding
rules). The paste-in prompt for a new session is `NEXT-SESSION-PROMPT.md`.

## The product in three sentences

A private chess practice companion whose whole runtime is on the iPhone: recognise the board,
have a person review the position, run local rules and Stockfish, give the move as text (speech
later). The eventual camera is Alex's Ray-Ban Meta Gen 1 glasses; Alex has no physical board, so
everything so far uses computer-generated board images. The safety rule is the product: advice
exists only for a position a person fully reviewed plus legally tracked moves; any change,
uncertainty or interruption revokes it; a late reply can never bring it back; refusing is always
allowed, accepting a wrong move never is.

## Who Alex is and how to talk to him

A smart UCLA student with no coding background. Plain language, define a term once, frame
decisions as outcomes, teach through the work. Raise risks he would not think of (secrets, data
loss, cost, privacy, data sent to third parties) before acting. Never claim something works
without showing the check. He wants the orchestrator to keep workers busy without being asked.

## Where everything is

| What | Where |
| --- | --- |
| Project (git, `main`, remote `origin` = private GitHub repo) | `/Users/alexmunzon/chess-practice` |
| Original Codex checkout, untouched backup | `/Users/alexmunzon/Documents/Codex/2026-10-30/task-3/chess-practice` |
| Build outputs and evidence (31.5 GB, outside the repo) | `/Users/alexmunzon/chess-builds/` |
| Latest phone evidence (33 of 33, 2026-11-16 18:14) | `/Users/alexmunzon/chess-builds/tracker-wiring-2026-11-16/phone-run1/` |
| Unsigned device builds now on the phone | `/Users/alexmunzon/chess-builds/special-replay-2026-11-15/device-normal` and `device-selftest` |
| Provisioning profile and entitlements (no private key) | `/Users/alexmunzon/chess-builds/iphone-2026-11-15/signing/` |
| Scene sets and pipeline evidence | `/Users/alexmunzon/chess-builds/pipeline-2026-11-15/` (`scenes`, `scenes-v2`, `scenes-stress`, `pipeline`, `classifier-v3`, `misread`) |
| Session process review (scripts and tables) | `/Users/alexmunzon/chess-builds/session-review-2026-11-16/` |
| Private status page (artifact) | https://claude.ai/artifact/P2yY3nAJ9BPch3rL1b2Aho (source: `/Users/alexmunzon/chess-builds/status-page/chess-build-status.html`) |

## Verified state (evidence type in every row; simulated images are never camera evidence)

Machine-readable status (checks, frozen hashes, which held-out data is spent, in-flight files,
backlog): `orchestrator-state.json`. One command for all checks: `scripts/check-all.sh` (Node
suite plus the Python recognition tests, now including reader v4 and the frame-age rules; run it
outside the command sandbox, because `npm test` opens 127.0.0.1 listeners and `listen EPERM` means
sandbox, not a code failure). Last full run, 2026-11-16 02:45, orchestrator: 6 of 6 suites passed.
Latest `npm test`, 04:42, orchestrator: 346 tests, 338 pass, 0 fail, 8 skipped.

| Area | State | Evidence type |
| --- | --- | --- |
| Rules + Stockfish in a local WebKit runtime | Working | Real iPhone 17 / iOS 27.2 |
| Study mode and Replay mode, two games, with the pre-started engine and a 100,000-node search (final build `prewarm-wiring-2026-11-16/after2`) | 30/30 self-test checks in 3 of 3 runs; the earlier build `after` 30/30 in 2 of 2; 3 earlier attempts were interrupted by a sleeping screen and are not results | Real phone, scripted review, orchestrator-run |
| Same build in the Simulator | 0 of 5 full passes (27, 25, 27, 28, 28 of 30): about 1 search in 5 runs about 35x slower there and misses the 4.5 s deadline; every miss failed safe (no advice). Not seen on the phone (75 analyses, slowest 0.28 s) | Simulator, agent-reported |
| Phone timings (final build) | recognition 27-76 ms, engine start median 0.33-0.37 s, search median 0.15-0.17 s at about 600k nodes/s; 13 of 25 analyses per run used the pre-started engine | Real phone |
| Mock safety suites | Study 33/33, Replay 31/31, Integration 23/23, ReplayTracker 94/94 (orchestrator-run 02:47; agent-reported unchanged after the follow-up); 37 mutations all caught | Mac, mocked |
| Screen pipeline (corners -> square reader -> move inference, two pictures must agree) | 0 wrong accepted moves on `heldout` and `heldout2` (both spent). Easy positions 114/115 | Simulated images, orchestrator-run |
| Stress pictures, development half (`stressdev`, reader v3) | Accepting from one picture: 5 wrong moves, all from mid-move pictures. Two pictures must agree: 0. Starts accepted 27/36: other piece styles 0/6, lens distortion 1/3, motion blur 2/3. Highlighted squares mostly refused | Simulated images, orchestrator-run |
| Square reader v3.1 (sha `c634a76d…`, blur-gate edge case closed; labels identical to v3 on 97,024 development squares) | v3 on `heldout2`: 0 confident wrong squares of 60,736, starts 11/12 | Simulated images |
| Swift port of the square reader (`native/ScreenOccupancy/`) | Identical labels to Python on all four development splits; self-test passes; type-checks for iOS; not in the app | Mac |
| Occupancy tracker with promotion question (`src/core/occupancy-tracker.js`, round 6) | 79 tests (78 pass, 1 opt-in skipped). Rounds 5 and 6 fixed two more reviews' findings (swaps, paused piece, fake castle, reordered pictures). STILL OPEN: reviewer script b1 trusts a swapped board in 4 of 9 scenarios (one square exchanged inside a single 150 ms picture gap while the other piece is under a hand); not closable from occupancy alone. Round 6 not yet reviewed. Not wired in; Alex decides | Pure logic, synthetic errors, orchestrator re-ran the attack scripts |
| Pre-started engine (`src/core/prewarmed-engine.js`) | 37 tests; reviewer's warm-up leak fixed; 121/121 same move as a fresh engine (orchestrator-run) | Mac, Node; not WebKit |
| Two-misread study | 85.7% of plies have a wrong move that two specific misreads would produce | Pure logic |
| Engine budget study | 100k nodes: 82% same move as an 800k search, 0 of 121 clearly worse | Mac only |
| Meta mock glasses in a Simulator-only app copy | Frames flow; every frame that reached the trust decision stayed "age unknown"; no advice, engine run or speech. No network contact observed under a watch proven to catch held connections and name lookups; a connection shorter than about a millisecond would be missed. Phone build byte-identical before and after | Simulator, mock device, agent-reported with orchestrator spot checks |
| Screen pipeline start-up reader | Library now starts on v3 (was v2 with the blur-gate hole); v2 only by name; 31 tests | Mac, orchestrator-run |
| Square reader v4.3 (flat pieces, last-move highlights; `de58ef04…`) | Frozen after three rejected freezes. Reserved `stressheld` (now spent), 36 games: 0 wrong moves at two-picture agreement for v3.1 and for v4.3; starts 28/36 vs 30/36; re-reviews per 100 positions 20.9 vs 26.8. Not the default | Simulated images, orchestrator-run |
| Corner finder curved-edge check (`native/ScreenBoardVision`) | Finding: the corner finder was NOT what rejected the lens and blur starts; the square reader was. New check rejects curved boards: on 3,017 development pictures 0 wrong accepted before and after, 39 newly rejected (orchestrator-run). Review: 4 of 488 attack pictures still accepted wrong when the lens centre is off the picture centre (old binary 135). Fix round in flight. New binary is in `corner-finder-2026-11-16/`, NOT used by the pipeline | Simulated images |
| Mock glasses frame-age methods (Phase 5) | None of the three methods rejected 100% of injected stale frames: on-screen code 159/162, clock offset 3224/3407 at best, budget+watchdog 674/2190. Live trust gate unchanged; no real latency measured; no network contact, pop-up or account request in 3 of 3 runs | Simulator, mock device, agent-reported; rule checks 38/38 orchestrator-run |

The phone has the optimized **normal** build from `prewarm-wiring-2026-11-16/after2/device-normal`
(sha256 `5ffa41a7…`, pre-started engine, 100,000-node search, no self-test code), installed
2026-11-16 about 04:50. Nobody has used the app by hand. The free signing profile expires
**November 22, 2026, 15:22 Madrid**; after that re-sign with
`native/ChessCompanionApp/signing/renew_profile.sh` then `sign_and_install.sh`.

Decisions already made (do not reopen without new evidence):
- The two-picture agreement rule stays on: it blocked every wrong move on the stress pictures.
- Pipeline headline numbers come from the "self-aware" scoring mode (a human is asked only when
  the pipeline itself knows it is stuck). The older "re-review" mode uses the answer key and is
  optimistic.
- Square reader v3.1 is the default reader. The piece-in-transit rule in the tracker is OFF by
  default until one more review at wiring time (its author and the second reviewer both
  recommend ON after the round-4 fixes).
- No "code ownership" role: change only what the task needs (Alex, 2026-11-16).
- The 11 confident wrong squares on `stressdev` are all on mid-move pictures, and at least
  some are an answer-key artefact, not reader errors: the picture shows a piece drawn on the
  middle square while the key holds the position after the move (worker's reading of the log,
  not checked square by square). Score mid-move pictures against what is drawn before counting
  them against a reader.
- Mock glasses findings to respect: frames keep arriving after the glasses are taken off and
  after permission is denied mid-stream; frame timestamps restart at zero on every stream, so
  they cannot give a frame's age.

## In flight at handoff (uncommitted; verify before relying on any of it)

Nothing was running when this was written (about 23:15). The Mac ran on battery and slept during the evening; keep it on its charger for long runs.

## Afternoon session 2026-11-16 (all uncommitted, all checks re-run by the orchestrator)

`scripts/check-all.sh` 8 of 8 suites at 17:48 (npm 379 tests, 371 pass, 0 fail, 8 skipped); it now
also runs `tests/piece_classifier_v1.py` (9 suites; 11 of 11 on its own).

| Piece | State | Evidence |
| --- | --- | --- |
| Tracker round 7/7b (`src/core/occupancy-tracker.js`, sha `04400009…770f`, 97 tests) | Either-colour rule (reviewer's R1), capture-square rule, gap rule in tick/snapshot, replayed-picture revoke. Reviewed (sixth review); the orchestrator re-ran the reviewer's attacks: hidden-square swap 0 of 144, spare on hidden square 0 of 24, opponent piece 0 of 12, captured piece 0 of 12; 18 of 18 mutants caught (worker-reported). Cost: hand-over-board row 50.6 -> 61.8 re-reviews per 100. | `tracker-round7-2026-11-16/`, `tracker-round7b-2026-11-16/`, `review-occupancy-tracker-round7-2026-11-16/` |
| Tracker holes that STAY open (documented) | The moving piece itself swapped or substituted (5 of 5); an exchange completed between two consecutive pictures with nothing hidden (34 of 34); castling can end with king and rook interchanged (2 of 5); a bare `snapshot()` without a time stays ready. Only piece identification closes the first three. | same |
| Tracker wired into the app, OFF by default | Launch argument `--occupancy-tracker-on` (`TrackerSetting.swift`); four request kinds in their own pending slot; any failed tracker request revokes; stop is never refused; page gate independent. Reviewed twice; the second review's one finding (unclassifiable command did not revoke) was fixed by the orchestrator in `NativeEngineRuntime.submit`, and the reviewer's harness then held 13 of 13. No picture source exists, so only scripted readings exercise it. `answerPromotion` is not wired (a promotion revokes). | `tracker-wiring-2026-11-16/` (round2/, phone2/, phone-run1/), `review-tracker-wiring-2026-11-16/`, `review-tracker-wiring-round2-2026-11-16/` |
| Phone (real iPhone) | Self-test 33 of 33 at 18:14 (30 old + 3 tracker checks), 1 of 1 run. Normal build `phone2/device-normal` (unsigned sha `ed426961…`) restored on the phone, tracker off. | `tracker-wiring-2026-11-16/phone-run1/` |
| Simulator A/B on a calm host | Engine deadline misses 5 of 100 (changed) vs 15 of 100 (previous commit), order alternated, 4 runs each: the change did not slow the engine; earlier imbalance was host load (worker-reported). | `tracker-wiring-2026-11-16/round2/ab-table.txt` |
| Reader start backup (`START_FALLBACK_CLASSIFIER`, `--start-fallback v4`) | Built, OFF. v3.1 first, v4.3 only when v3.1 fits no orientation; the accepting reader reads the rest of the game; a self-check re-reads the start picture (all 64 squares must match). stressdev starts 27 -> 30 of 36, two-picture wrong moves 0 on 5 splits, fallback off identical to committed code (worker-reported; pipeline tests 40 of 40 re-run by the orchestrator). | `reader-fallback-2026-11-16/` |
| Reader v4.3 review | Verdict NO for the backup as first built: its start check accepted 66 of 107 not-the-start pictures in the flat style (orchestrator re-ran: 66 of 107). With the self-check: 11 of 107 (all an extra piece under an 80-95% layer in exactly the board colour). 9 of 24 removed rules are caught by no test. Later-picture reading held up. | `review-reader-v43-2026-11-16/` |
| Piece reader prototype (`scripts/recognition/piece_classifier_v1.py`, sha `e5c31e2ef64f…`, 11 tests, `docs/PIECE_CLASSIFIER.md`) | Learns piece shapes from the reviewed start picture; names a piece only when the best match is 2x the second. Builder: dev2 25,619 of 28,257 correct, 0 wrong; stressdev 40,245 of 42,081, 0 wrong; swaps and substitutions none missed in 7,218 each. Review (counts reproduced): usable as a guard that can only WITHHOLD advice, not as confirmation. Confident-wrong found: mid-game start with reduced material 12 of 5,760; arrow or glare in the start picture 44 in 6 of 12 games; a kind never shown 81 of 6,689; mid-move pictures 5; heavy blur/lens 44 of 25,344. Not registered in the pipeline. | `piece-classifier-2026-11-16/`, `review-piece-reader-2026-11-16/` |

## Session 2026-11-17 (01:00-08:20 Madrid; all uncommitted; details in the matching backlog items)

Full check at 07:15, orchestrator: `scripts/check-all.sh` 11 of 11 suites; `npm test` 397 tests, 389 pass,
0 fail, 8 skipped. After that only `piece_guard.py`, the frame-age harness and their tests and docs changed (guard 32 of 32, frame-age 8 of 8, orchestrator re-ran; final full check: see orchestrator-state.json).

| Work | State | Backlog item |
| --- | --- | --- |
| Engine wiring leftovers | done, reviewed, conditions closed; guard checks 21 of 21 | 6 |
| Frame-age harness round 2 | done, NOT independently reviewed | 7 |
| Test hygiene | done | 8 |
| Corner finder round 2 | selectable, default unchanged; waits on Alex | 2 |
| Reader v4 tests | done; new known-wrong square on flat boards (expected-failure test) | 12 |
| v3.1 start self-check | built OFF; fixes little (55 -> 49 of 107) | 11 |
| Promotion answer for the tracker | wired OFF, reviewed twice, conditions closed | 5 |
| Piece reader v2 | reviewed, hardened (`07632cb07154…`) | 10 |
| Piece guard `piece_guard.py` | seven build rounds, six independent reviews (round 3 REJECTED; rounds 4, 5 and 6 "accept with conditions"); round 7 (`17cf71610139…`, 32 tests) closes the sixth review's one condition and has NOT had its own review; NOT connected | 10 |

Piece guard as it stands (round 5): `check_after_move(image, corners, believed_before, believed_after)`
accepts only single-move shapes (one piece along its line, under-promotion, en passant); withholds on
everything else, on any king or queen move, castling and queen promotion; remembers the last accepted
position; `rebaseline_after_human_review(...)` is the only way to reset it and MUST follow a person's review
(an automatic re-baseline defeats the guard: it cannot see kings, queens or pieces invented on empty
squares; pinned by a test). Outcomes are read with `out.must_withhold()`; an outcome expires when any
later call starts; calls on one guard are serialised by a lock. Fourth review (accept with conditions,
`review-piece-guard-round4-2026-11-17/`): real moves refused for shape 0 of 6,959; near-miss non-moves
accepted 0 of 1,481,235; attacks with pictures 0 of 79 and 0 of 26; baseline attacks 0 of 20. Legal-play
cost, 8 games, 320 moves, simulated pictures (reviewer-measured, builder re-ran after round 5, orchestrator
read the log): withheld ordinary 0 of 84, pawn moves 0 of 105, captures 0 of 71, en passant 0 of 6,
under-promotion 0 of 4; king 21 of 21, queen 20 of 20, castling 7 of 7, queen promotion 2 of 2 (50 of 320).
The first picture after every move withholds by design (the reader's mid-move rule); acceptance comes on
the second picture. EARLIER COST FIGURES (123 "honest moves") were measured on mostly non-legal random
changes and are superseded by this table. Orchestrator re-ran after round 5: guard 27 of 27, reader 30 of
30, v1 11 of 11, the reviewer's thread case now withholds. Agent-reported: reviewer's 26 mutants 23 caught,
survivors k07, k14, k26 (the reviewer's own "cannot change behaviour" list). Fifth review (round 5, accept with
conditions, nothing dangerous; `review-piece-guard-round5-2026-11-17/`): regression 0 dangerous; lock and
sequence 0 of 26; gaps: a re-baseline succeeded on a picture that shows nothing (degenerate corners), a
same-thread re-entrant call deadlocked, 12 of 17 fresh mutants caught. Round 6 (fresh builder,
`piece-guard-2026-11-17/round6/`): a re-baseline needs the reader to name at least 0.75 of the nameable pieces
(all 50 honest re-baselines named 100%, clean renders only); a re-entrant call withholds; docstrings state
when the baseline can move while the caller reads withhold. Orchestrator re-ran after round 6: guard 30 of 30,
reader 30 of 30, v1 11 of 11, the reviewer's bad-corners attack now withholds, cost log unchanged (50 of 320,
re-baselines 50 of 50). Agent-reported: 15 of 17 mutants (m14, m15 near-equivalent). Sixth review (round 6, accept with one condition,
`review-piece-guard-round6-2026-11-17/`): a re-baseline claiming position X on a slightly different picture Y
was accepted 5 of 92 (the changed square reads "unconfirmed", not an objection); everything else refused;
honest re-baselines 12 of 12 midgame and 5 of 7 endgame under blur/JPEG/noise/brightness/theme/2 px jitter
(the 2 failures are king-and-queen-only positions, which can never re-baseline), 11 of 12 and 3 of 7 at 5 px
jitter; test setups judged not weakened. Round 7: a re-baseline withholds when any square is "unconfirmed".
Orchestrator re-ran: guard 32 of 32, reader 30 of 30, v1 11 of 11, the reviewer's c_follow attack now
refused. Agent-reported: the sixth reviewer's 92 attacks 0 dangerous, costs unchanged, 16 of 17 mutants.
Next step if Alex wants the guard used: a fresh review of round 7, then wiring beside the tracker as a
separate reviewed step. Known limits to carry forward: never sees kings or queens; a re-baseline is the
caller's claim of a human review; first picture after a move always withholds; clean rendered pictures only.

## Backlog, in priority order (launch whatever has free files and ready inputs)

1. Square reader v4 is frozen as v4.3 (`de58ef04…`, 55 tests) after three independent reviews, each
   of which rejected the previous freeze (v4.0 translucent panels and low pieces; v4.1 pale panel on
   flat boards; v4.2 glare in the start picture loosened the main rule). The orchestrator re-ran the
   third review's glare attack on v4.3: 0 wrong on 140 boards. v4.3 itself has NOT had its own
   review; open item from its worker: the two-colour limit learned from the start picture can also
   be loosened by glare on a start piece (no wrong square shown).
   `stressheld` was scored ONCE on 2026-11-16 about 11:17-11:44 by the orchestrator and is now SPENT (logs `pipeline-2026-11-15/pipeline/final-stressheld-v3.log` and `-v4.log`; frozen: pipeline `49d7ce83…`, scorer `c7d4fdec…`, original corner finder `b5774046…`, readers v3.1 `c634a76d…` and v4.3 `de58ef04…`). 36 games, simulated images, self-aware mode. Two pictures must agree: 0 wrong moves accepted with v3.1 and 0 with v4.3. One picture: 2 wrong moves each, both on the mid-move game (a pawn drawn half way on f3/d3), blocked by the two-picture rule. Starts accepted: v3.1 28/36, v4.3 30/36 (flat style 0/3 -> 3/3; coordinates 3/3 -> 2/3; unfamiliar style 0/3 and lens distortion 1/3 for both). Re-reviews per 100 positions at two-picture agreement: v3.1 20.9, v4.3 26.8. Confident wrong squares against the answer key: v3.1 5 of 66,624, v4.3 4 of 71,424 (the listed ones are mid-move pictures; not checked square by square). Time per picture on the Mac: 407 ms with v3.1, 456 ms with v4.3.
   DECIDED 2026-11-16 (Alex): v3.1 stays the default; v4.3 only as a start backup. The backup is built
   and OFF (see the afternoon table); the orchestrator recommends leaving it off (11 of 107
   not-the-start pictures still accepted for 3 extra starts). Older note:
   Next: decide the default. v4.3 reads flat pieces and highlights but leaves unknown about 2,800
   (dev) and 6,200 (dev2) squares that v3.1 reads (agent-reported). Orchestrator's recommendation:
   keep v3.1 as the default and try v4.3 only when v3.1 refuses the start picture; that fallback is
   not built. Any further v4 change needs NEW unseen pictures, because no held-out set is left.
2. Corner finder UPDATE 2026-11-17 (uncommitted, not separately reviewed): round 2 is now SELECTABLE
   (`set_finder`, `--corner-finder round2`; binary copied to `pipeline-2026-11-15/pipeline/bin/screen-board-detect-round2`,
   sha `3292bcae…`); DEFAULT STILL THE ORIGINAL (`b5774046…`), default output proven identical on smoke2
   (13 of 13 result files). Agent-reported, simulated pictures, reader v3.1, two-picture rule, both finders
   identical on every measure: wrong moves 0 of 14 / 0 of 421 / 0 of 337 / 0 of 338 (smoke2/dev/dev2/stressdev),
   starts 2 of 2, 12 of 12, 12 of 12, 27 of 36; corners identical within 0.5 px; round 2 refuses 3 lens start
   pictures the reader refused anyway; detect stage 15-58 ms slower per picture (loaded Mac). Pipeline tests
   43 of 43 (orchestrator re-ran). Evidence `corner-swap-2026-11-17/`. Open for Alex: make round 2 the default
   (orchestrator: yes; it is still not a guard against lens distortion). The worker could not trace the
   "277 of 1,006" figure below to a log; the doc cites 105 of the same 422 pictures instead. Earlier record:
   Corner finder: round 2 (`corner-finder-2026-11-16/round2/bin-new2`, sha256 `3292bcae…`) was
   re-reviewed: it MAY replace the pipeline's finder as a strict improvement (ordinary pictures
   0 of 100 newly refused, corners identical; first review's 8 attack sets 0 of 653 wrong), but it
   is not a guard against lens distortion: 24 of 422 two-term-lens pictures accepted with corners
   5.0-16.6% off (original finder 277 wrong of 1,006 distorted pictures, round 2: 24). NOT swapped
   in yet, on purpose: the pipeline binary stays frozen until `stressheld` has been scored. After
   that, copy bin-new2 to `pipeline-2026-11-15/pipeline/bin/` under a new name, re-run the
   development splits, and only then make it the default. The doc's limits section was corrected
   by the orchestrator.
3. Lens undistortion before the corner finder (new): a flat four-corner rectify cannot fit a curved
   board; with the known lens value undone, the reader accepted 3 of 3 lens starts. Needs a
   one-time calibration of the real glasses camera eventually.
4. Motion blur belongs to the square reader: with exact corners it still reads blurred pieces as
   empty (12 px blur).
5. UPDATE 2026-11-17 (uncommitted): `answerPromotion` is WIRED as a fifth tracker request
   `trackerAnswerPromotion` behind the same OFF-by-default setting (runtime.js handler; kind added to
   `occupancyKinds` in Swift). Orchestrator re-ran: npm test 386 tests, 378 pass, 0 fail, 8 skipped;
   tracker-wiring 22 of 22; run-all.sh 5 of 5 suites, guard checks 20 of 20; tracker file sha unchanged.
   Agent-reported: 7 of 7 mutants caught; self-test check compiled, never run. REVIEWED TWICE 2026-11-17, both "accept with conditions", all
   conditions closed (rounds 2 and 3 in `promotion-wiring-2026-11-17/`; reviews `review-promotion-wiring-2026-11-17/`
   and `review-promotion-wiring-round2-2026-11-17/`). First review: 3 of 38 page attacks dangerous (a second,
   different answer was ignored and advice stayed on; old answer matched after a reload). Now: a different
   piece for an answered question revokes (`ANSWER_CONFLICT`); the tracker instance id carries 128 random bits
   (requirement 6 closed); a missing, throwing or all-zero random source means no tracker (`RANDOM_UNAVAILABLE`);
   the answer memory is never evicted and revokes at 1,024. Orchestrator re-ran after the last round: both
   reviewers' attack scripts 0 of 38 and 0 of 29 dangerous; npm test 397 tests, 389 pass, 0 fail, 8 skipped;
   tracker-wiring 33 of 33; run-all.sh 5 of 5, guard checks 21 of 21. Agent-reported: reviewer mutants 11 of 12
   (the survivor is indistinguishable). Simulator self-test of the build BEFORE the last two fix rounds
   (page code only changed since): 32 of 34 and 34 of 34, all four occupancy checks passed in both, failures are
   the slow engine search (`sim-selftest-2026-11-17/`; the second run was clean at HIGHER load, so load alone
   does not explain the slow search). Not run on the phone.
   Earlier record: Occupancy tracker: round 7b is reviewed and wired in OFF by default (afternoon table). Left:
   wire `answerPromotion`; a test in the repo's own check for the Swift gates (today only macOS
   harnesses outside the repo catch their removal: `tracker-wiring-2026-11-16/round2/swift/TrackerGateChecks.swift`,
   whose N4 check is flaky); `RuntimeGuardChecks.swift` label still says 16 assets (now 18); a far-future
   `trackerStart` time disables the tracker until the runtime is recreated (fails closed, documented).
   Whoever connects a picture source must guarantee the doc's Wiring requirements (one monotonic clock,
   in-order pictures, covered squares read unknown, 6 pictures per second, poll every 100 ms, stop on
   every interruption, any tracker error means trust is gone).
6. Engine wiring leftovers: DONE 2026-11-17 (uncommitted), reviewed (accept with conditions, all three
   conditions then closed by the builder). `RuntimeGuardChecks.swift` now drives the real `submit` in a
   headless macOS web view: 15 of 15 (orchestrator re-ran; `run-all.sh` "5 of 5 native suites passed").
   Mutants, agent-reported: 8 of 8 busy-guard and 4 of 4 occupancy-slot copies caught. `run-all.sh`
   (`special-replay-2026-11-15/mocks/`, outside the repo; old copy in `engine-leftovers-2026-11-17/run-all.sh.before`)
   now runs the guard checks. `cancelPrewarm` stays refused while a request is pending (pinned by checks);
   with a Replay or position/move request pending a ready spare engine survives up to about 70 s, holds no
   position, restores no advice (docs corrected). Self-test case no longer counts a timeout as a pass;
   Simulator run 29 of 33 at load 10-15 (1 of 1 run, agent-reported; the changed case passed, the 4 failures
   are engine deadline misses seen before under load): RE-RUN ON A CALM HOST, and no phone run yet. The
   Simulator holds an ad hoc signed self-test build. Evidence `engine-leftovers-2026-11-17/` (round2/),
   `review-engine-leftovers-2026-11-17/`. Still open: the slow-search question.
7. REVIEWED 2026-11-17 (`review-frame-age-2026-11-17/`): "supported with caveats". The 3 misses are a rig
   artifact (late display log plus one out-of-order mock frame at every code change; about 85% confidence; a
   reader misread is not ruled out). BUT the "0 misses" counts below (162 of 162, 0 of 7,821, and the
   reviewer's own 0 of 10,004) HOLD BY CONSTRUCTION and are NOT evidence about the method; fault injection
   detected 8 of 13, mutants 16 of 19; the harness never held a picture longer than 10 s and left post-loop
   pictures unscored; the doc overclaims. The guarantee needs eight assumptions (log never late, one clock, no
   second source showing the same code, correct stream assignment, no misread to a valid code, exposure within
   the margin, board and code in one exposure, first display kept). FOLLOW-UP DONE (round 3, `frame-age-round2-2026-11-17/round3/`;
   agent-reported except the tests): the harness can now fail and found two real weaknesses of method 1:
   a second screen replaying the PREVIOUS stream gets old pictures accepted 2,033 of 8,712 (codes repeat across
   sessions: the code needs a session number), and a reader that returns the next code gets 325 of 1,850
   accepted. Controls, long holds (30-60 s), post-loop and same-session replays: 0 accepted. Faults 12 of 13,
   mutants 19 of 19; doc rewritten to claim only this. Tests 8 of 8 and mock video 21 of 21 (orchestrator
   re-ran). Next for method 1: a per-session value in the code and an error-detecting code; then real glasses.
   Earlier record: Frame age for glasses, round 2 DONE 2026-11-17 (uncommitted; reviewed later, see above): the 3 misses
   were harness error (display log 210-231 ms late against a 50 ms margin). New Mac-only harness on a
   frame-count clock, `native/MockGlassesProbe/frame_age_mac_sim.py` (error at most 2.5 ms);
   `analyze_frame_age.py` refuses to score when the log error exceeds the margin. Agent-reported, simulated
   video on the Mac: old picture accepted 0 of 7,821; fresh refused 57 of 45,122; delayed-but-fresh accepted
   7,230 of 11,021 (cost). Tests 6 of 6 and mock video 21 of 21 (orchestrator re-ran). `FrameAgeHarness.swift`
   (Simulator) still has the late log. Needs real glasses to mean anything. Evidence `frame-age-round2-2026-11-17/`.
8. Test hygiene: DONE 2026-11-17 (uncommitted). Two tests left reader v2 selected, so 34 of 40 pipeline
   tests ran on v2; a `setUp` cleanup now resets the reader and the start fallback. 40 of 40, leaks 0 in
   both orders (orchestrator re-ran). Evidence `test-hygiene-2026-11-17/`.
10. Piece reader v2 REVIEWED 2026-11-17: "yes with conditions" as a guard that can only WITHHOLD advice
   (evidence `review-piece-reader-v2-2026-11-17/`, copied there by the orchestrator; no REVIEW.md, the
   reviewer's reply is the report). Tests 22 of 22. Orchestrator reproduced the two worst findings.
   Dangerous if "consistent" were ever treated as confirmation: (1) a start reviewed wrongly in a
   self-consistent way (knight/bishop or rook/knight swapped on both sides, or board turned 180 degrees) is
   accepted, 3 of 23 doctored starts, 37/78/36 wrong names, and compare() then calls 8 of 8 wrong squares
   "consistent" (re-run: 78 wrong, 8 of 8); (2) a piece paused mid-slide is named, 43 wrong of 43,885 named
   squares (1 of 2 wrong squares "consistent" when the tracker makes the same mistake). No danger found:
   thin-evidence 0 of 76, compare() 0 of 3,104 wrong beliefs called consistent, picture conditions 0 of 245,
   malformed input 0 of 43 wrong (but 12 of 43 CRASH instead of "cannot tell"; a partial position can give an
   overall "consistent"). Mutants 10 of 20 caught (survivors include compare's overall verdict "any" for "all"
   and 4 start-cleanliness limits). Cost on the reviewer's clean renders: starts refused 0 of 60; unsure 12 of
   5,061 non-king/queen squares; kings/queens unsure 847 of 847. Not verified: real footage, dev2, stressdev.
   CONDITIONS: act only on "objection", treat "consistent" as no information; always pass the full believed
   position; a crash withholds advice; correct start review incl. board direction; tests for the survivors;
   consecutive real pictures. Earlier record follows.
   AFTER THE REVIEW, 2026-11-17 (uncommitted): the reader was hardened (bad input answers cannot-tell, no
   crash; a turned board reads unsure; a partial position is never "consistent"; an objection is kept even
   with a malformed entry elsewhere), sha now `07632cb07154…`, 30 tests. New withhold-only guard
   `scripts/recognition/piece_guard.py` (sha `832fd74fd94b…`, `tests/piece_guard.py` 15 tests, in check-all):
   two outcomes only, "withhold" and "no objection" (= no information); withholds on objection, any error,
   refused/missing start, impossible or partial believed position. Guard reviewed once ("accept with
   conditions": equality trap, impossible positions passing, misuse cases; evidence
   `review-piece-guard-2026-11-17/`), builder closed all; orchestrator re-ran tests 30/15/11 and the
   reviewer's follow-up attack (now withholds; `== WITHHOLD` true). Agent-reported: guard mutants 23 of 24
   (survivor unreachable), reader mutants 20 of 20, reviewer's guard attacks 0 dangerous of 101,
   atk_f 0 crashes of 43, atk_d 0 of 3,104, smoke2 unsure 181 of 1,344 unchanged. The round-2 fixes have a
   re-review in flight/after them: see the state file. COST, for Alex to decide (reviewer-measured, 123 honest
   moves): strict default withholds 123 of 123 (the reader never says "empty"); `check_move(arrived, vacated)`
   20 of 123 (all king/queen moves); lenient 0 of 123. Orchestrator recommends `check_move`. NOT CONNECTED to
   the tracker or the app. Evidence `piece-guard-2026-11-17/` (round2/).
   Piece reader v2 was BUILT (2026-11-16 evening, uncommitted; at that time not reviewed: launch a `code-reviewer`
   before quoting its numbers as verified or wiring it): `scripts/recognition/piece_classifier_v2.py`
   (sha `c19efcf5…35b61`), `tests/piece_classifier_v2.py` (22 of 22, re-run by the orchestrator), v1 untouched,
   evidence `piece-classifier-v2-2026-11-16/`. Worker-reported: confident-wrong 0 on every reviewer attack
   family (v1: 214) and on smoke2/dev2/stressdev; unsure rises to about 28% of occupied squares on dev2 and
   stressdev (v1: 9% and 4%); swaps missed 0 (dev2: 2,616 noticed, 417 cannot-tell of 3,033); false alarms 0;
   clean starts wrongly refused 3 of 64, 6 of 84, 17 of 128; names nothing on 8 of 12 low-contrast board
   looks; 12 of 14 mutants caught. Design question for the orchestrator: a kind learned from one start
   square is never named, so kings and queens are NEVER named in a standard game (a king-queen swap is
   "cannot tell", not an objection); decide whether "cannot tell" on a square the tracker marked disturbed
   should itself withhold advice. Then a guard next to the tracker that can only revoke. Original brief:
   Piece reader round 2 (was not started: weekly usage was at 63-66% on 2026-11-16, limit rule 70%):
   refuse or flag unclean start pictures (reviewer's edge-ring prototype caught 96 of 96 dirty starts
   but refused 20 of 64 clean ones, so it needs design); refuse to name kinds learned from fewer than
   about two squares; treat agreement as "no objection", never proof; tests for the fit and gain
   gates (6 of 18 mutants caught today); score mid-move pictures. Then a guard next to the tracker
   that can only revoke. This is what closes the tracker's remaining holes.
11. MEASURED 2026-11-17 (uncommitted): a self-check option for v3.1 starts is built and OFF
   (`START_SELF_CHECK`, scorer flag). It fixes little: not-the-start classic pictures accepted 55 -> 49 of 107
   (reproduced 55 first); good starts newly refused 0 on smoke2/dev/dev2/stressdev; wrong moves 0 -> 0; about
   120 ms per start (agent-reported, simulated pictures). The 49 left are pictures v3.1's own reading takes
   for the start (28 extra piece under an 80-95% layer, 11 piece-coloured shape on an empty square, 10 a
   piece drawn 6-16 px off). Recommendation: leave it off; a real fix needs a better reader; the person's
   start review covers it today. Pipeline tests 48 of 48 (orchestrator re-ran). Evidence
   `start-selfcheck-v31-2026-11-17/`. Earlier record: Default reader v3.1 start check: accepted 55 of 107 not-the-start pictures in the classic style
   (v4.3 review, `attack_start.py classic classic A`). The person's review of the start position
   covers it today. Candidate: the same self-check on v3.1 starts, measured for cost first.
12. Reader v4 tests DONE 2026-11-17 (uncommitted): 8 new tests (class `UnprotectedRuleCases`), mutation
   23 of 24 caught (agent-reported; the survivor M16 is equivalent, `MASK_MIN_SQUARES` may be dead code).
   64 tests, 63 pass + 1 expected failure (orchestrator re-ran), module sha unchanged `de58ef04…`.
   NEW WRONG-SQUARE FINDING (agent-reported, expected-failure test
   `test_fill_coloured_box_standing_on_an_empty_square_KNOWN_WRONG`): on flat-style boards an opaque box in a
   piece colour standing where a piece's base would be on an empty square reads as a confident piece, 4 of 4
   squares per colour; the size check cannot refuse it there, so the doc's "a large occluder is unknown" does
   not hold on flat boards. v4.3 is only the OFF start backup; one more reason to leave it off. Evidence
   `v4-tests-2026-11-17/`. Earlier record: 9 of 24 removed rules are caught by no test (`review-reader-v43-2026-11-16/logs/mutants.log`).
9. Housekeeping: fold this session into `docs/PLAN.md` and `docs/VERIFICATION.md`; refresh the
   status page; real-WebKit test of the engine-host-died path; evidence retention (inventory done:
   31.5 GB, about 9 GB are candidates after Alex's OK; `pipeline-2026-11-15` is still read by
   scripts and tests).

## Decisions waiting on Alex

- NEW 2026-11-17: corner finder round 2 as the default (orchestrator: yes; identical on all development
  splits, fewer distorted pictures accepted; not a lens guard).
- NEW 2026-11-17: piece guard cost. Connected, it would need a human re-review after every king move, queen
  move, castling and queen promotion (50 of 320 moves in 8 legal games). Accept that, or first design a
  reader that can name kings and queens.
- NEW 2026-11-17: commit (and separately push) everything since `e482729`.
- NEW 2026-11-17: phone self-test of today's build (needs the phone unlocked; not run).
- Slow engine search: on 2026-11-17 a Simulator run was clean (34 of 34) at HIGHER load than a run with two
  slow-search failures (32 of 34), so load alone does not explain it.

- Occupancy tracker: DECIDED 2026-11-16 (Alex): one more fix round, then wired in switched off. Done.
  Open for him: whether to continue with the piece reader round 2 (backlog 10), which is what makes
  the tracker worth switching on.
- Reader start backup: built and off; switch it on or leave it (orchestrator: leave it off).
- Piece-in-transit setting: stays OFF; with it ON a lifted piece costs 0 instead of 49 re-reviews
  per 100 positions, wrong acceptances equal in both settings after round 6.
- Slow engine searches (Simulator only so far): accept an occasional "no recommendation" or add a
  warm-up for every engine start.
- Try both Replay games by hand on the phone (the only missing human evidence).
- Camera and real-glasses approval for the first real screen-board capture.
- Off-machine backup: DONE 2026-11-16, private GitHub repo `alexmunzon/chess-practice` (the orchestrator
  searched all pushed commits for his Apple ID email and team ID: 0 occurrences). Each push needs his words.
- Whether to download the non-commercial ChessReD dataset (about 29 GB).
- What to keep of the 31.5 GB of evidence (inventory file above).
- Commit: the afternoon session's work is uncommitted; commit and push only when he asks, each time.

## Boundaries (do not cross without Alex's own words)

- **Approved:** Simulator testing; signing, installing and opening the private app on his phone
  for text-only offline testing with the existing identity. Meta mock glasses, approved
  2026-11-15: Meta's developer terms for private testing on this Mac; work without a Meta
  account and stop if one is required; a Simulator-only copy containing Meta's code and
  declaring Bluetooth and local-network use; reuse of the SDK copy already on the Mac.
- **Not approved:** camera, microphone, real Bluetooth use, real glasses, audible speech; new
  accounts, spending, credential entry, permanent settings changes; any dataset, model or Xcode
  download.
- **Git:** commit only when Alex asks. Never push, open a PR or create a remote without his
  explicit words for that action.
- Generated binaries, engine assets, media and Meta's frameworks stay outside the repo.

## How to run things

- **Build the app:** `python3 -B native/ChessCompanionApp/prepare_app.py` (no Xcode project; it
  calls `swiftc`). Flags: `--simulator`, `--self-test`, `--fixture-directory`,
  `--replay-directory`, `--special-replay-directory`. Working invocations:
  `/Users/alexmunzon/chess-builds/special-replay-2026-11-15/build-all.sh`. Rebuild the runtime
  bundle with `node scripts/build-device-runtime.mjs --out <dir>` whenever `src/core` files in
  the bundle or `runtime.js` change; `prepare_app.py` pins every asset.
- **Mock suites:** `bash /Users/alexmunzon/chess-builds/special-replay-2026-11-15/mocks/run-all.sh`.
- **Phone self-test:** `native/ChessCompanionApp/signing/phone_selftest.sh --app … --sha256 …
  --provisioning /Users/alexmunzon/chess-builds/iphone-2026-11-15/signing --identity "<name>"
  --out <new dir> --timeout 900 --restore-app … --restore-sha256 …`. Find the identity name with
  `security find-identity -v -p codesigning`; never print or export keys. Exit 3 = phone asleep,
  **exit 4 = phone locked**: ask Alex to unlock BEFORE launching, then `--only run` and
  `--only restore`. This Mac's `/bin/bash` is 3.2: put multi-step commands in a script file.
- **Simulator:** iPhone 17, UDID `746F2CEB-102D-4CFC-8D11-A5924705537F`. Engine deadlines fail
  when the Mac is loaded; run timing-sensitive tests only when `uptime` shows a 1-minute load
  under about 8, and report every run as "n of m passed".
- **Pipeline scoring:** `python3 -B scripts/recognition/evaluate_screen_pipeline.py --scenes
  <root> --split <name> --classifier v3 --out <dir>`. Held-out splits are scored by the
  orchestrator only, once, after settings are frozen; say when a split is spent.

## How to run the next session (lessons from the 2026-11-15/16 process review)

Measured: 18 workers in 2 h 22 min; 9.5 worker-hours; a trough of 1-2 workers for 40 minutes
while ready work sat unlaunched; machine load up to 407; four claims to Alex later corrected.

1. **Capacity:** keep 5-6 workers busy, at most 2 CPU-heavy (rendering, engine runs, Swift
   builds, scoring), exactly 1 using the Simulator. Label every brief light or heavy and run
   `uptime` before launching a heavy one. Six heavy workers put the load at 200+ again at 00:53.
2. **Backlog check on every worker report:** launch every packet whose inputs exist and whose
   files are free in the same turn. Standalone new modules never need the blocked app folder.
3. **Review before commit and before numbers reach Alex:** each safety module gets its own
   adversarial reviewer ("try to break it; PROVED or INFERRED") as soon as its worker finishes.
   All three such reviews found something the worker's own tests missed; two were safety bugs.
4. **Report every run** ("2 of 3 passed"), label unverified claims "agent-reported", and check
   units before comparing two numbers.
5. **Producers write to a new folder** and mark it ready; consumers never read a folder that is
   being regenerated.
6. **Docs refresh is the last packet**, after results exist.
7. **Scoring may use only what the app knows at runtime.** An answer-key shortcut in a brief
   cost a whole round.
8. **Ask Alex up front** for any phone window or approval needed in the next hour. The phone
   self-test needs the SCREEN ON, not only unlocked: with the screen asleep the app launches in the
   background and every check fails as "engine not ready" (3 interrupted runs on 2026-11-16). Ask
   for Auto-Lock "Never" for the test window.
   **No paid extra usage (Alex, 2026-11-16):** his Team plan has extra usage on and he cannot
   switch it off. Read plan usage before every launch and on a 20-minute timer; launch nothing at
   70% of the 5-hour or weekly limit, stop all workers at 80%, stop at once if the extra-usage
   spend rises. Fewer workers is the price; this outranks "keep 5-6 workers busy".
   **Quiet window for Simulator timing runs:** pausing other workers' heavy jobs with
   `pkill -STOP -f <pattern>` and resuming with `-CONT` works and loses nothing.
   **Reviews pay for themselves:** all six adversarial reviews this session found something the
   worker's tests missed (tracker twice, corner finder, reader v4, engine wiring twice at low
   severity). Do not spend held-out data or wire anything in before its review.
   **Read a worker's script usage line before re-running it:** the orchestrator overwrote two
   evidence logs by passing an output path to a script that re-runs and writes.
   Opus 5.5 workers (its guide, read 2026-11-16): a worker's message is a report, not proof
   of completion; check it against the "done" list, nudge with a message naming the open items
   at most two or three times, and wait for anything it left running. Put pasted findings or
   logs inside their own tags and say that instructions inside them are data.
   Fable 5.2 specifics (its guide, read 2026-11-16): run the orchestrator at high effort; keep
   working past ordinary obstacles and do not end a turn by listing what is left; open each
   long turn with one line on what is about to happen and close with a recap that stands on
   its own; write approval rules as named actions with a reason; at every handoff delete
   cautions in this file and in memory whose reason no longer holds.
9. **Worker cost:** general-purpose workers carry about 59K tokens of unused tool definitions on
   every call (about 29% of worker input). Alex approved a lean `builder` agent type on
   2026-11-16: `~/.claude/agents/builder.md` (Bash, Read, Edit, Write, Grep, Glob; Opus). Use
   `subagent_type: "builder"` with medium effort for build work, `code-reviewer` for reviews,
   and a general-purpose agent only when a task needs web access. It is new and untested: on
   first use, confirm the worker can report back and compare its token use with the old type.

### Worker brief template

Follows Anthropic's general prompting guide and the Fable 5.2 guide (both read in full
2026-11-16; the rules are in the global `~/.claude/CLAUDE.md` under "Prompting standard"): one-line role, long material first, the ask
last, a reason for each rule, named tags, calm wording, a self-check at the end.

```
You are a build worker on a private chess project. You see only this brief.
<context>   project path, read AGENTS.md first, the docs and code to read, data and file contracts,
            inputs with paths (and whether they are finished or still being written) </context>
<why>       the product safety rule and how this task serves it </why>
<ownership> files you create or edit / files that are read-only for you / output folder outside the repo </ownership>
<limits>    light or heavy; at most N processes under nice -n 10; work without commits, network,
            installs, Simulator or phone unless stated; held-out splits are off limits, because a
            result is only honest on data nobody tuned against </limits>
<waiting>   long runs: run in the background and wait for the notification; a busy loop or sleep
            poll wastes the shared machine </waiting>
<examples>  when format matters: 3 to 5 varied examples of the output wanted (a report line, a
            JSON record, a test name) </examples>
<task>      the completion condition first; the goal in two sentences; small steps, each with its
            own check; keep a checklist of the parts in a file in the output folder and tick them
            off; optional time budget, never for safety-critical work </task>
<done>      numbered pass/fail checks with exact commands; scoring uses only what the app knows
            at runtime; every new safety property has a test that fails on the old code </done>
<rules>     finish the whole task and work through ordinary obstacles (errors, timeouts, failing
            tools); read the code before claiming; general solution, not shaped to the tests; stay
            inside the scope; say if a test or this brief is wrong; a stop condition is a
            valid result; remove temporary files before reporting </rules>
<report>    before reporting, check your result against <done>. About 300 words, written for a
            reader who has not seen your work; evidence and conclusions, not your reasoning: commands and pasted
            output tails; ALL runs as n of m; each claim marked PROVED, INFERRED or not verified;
            anything outside scope that you noticed </report>
```
