# Occupancy tracker (pure logic, 2026-11-16, round 7b after six reviews; not wired into the app)

Code `src/core/occupancy-tracker.js`; tests `node --test tests/occupancy-tracker.test.js` (slow cross-check: `OCCUPANCY_CROSS_CHECK=1`);
report `node scripts/simulation/occupancy-tracker-report.mjs [--games 100 --seed 20261116 --out F]` (exits 1 on a wrong move or
wrong/stale trusted picture at agreeFrames >= 2). Squares read only as empty/white/black/unknown; `inferMove` names the move.

## API
`new OccupancyTracker({instanceId (required, unique), agreeFrames=2 (2..10, no route below 2), minFrameGapMs=50, minSettleMs=300,
castlingRookSettleMs=1500, maxSilenceMs=1000, minConfidence=0.95, maxSkippedUnusable=2, promotionTimeoutMs=20000, inTransitTolerance=false,
readyDwellMs=1000, maxPictureGapMs=250 (1..maxSilenceMs)})`.
`confirm({session{sessionId,epoch}, fen, reviewed{5 ticks}, atMs?})` revokes first; six-field FEN; older epoch throws `STALE_IDENTITY`.
`ingest({identity{sessionId,epoch,sequence,frameSha256}, capturedAtMs, squares})`; `answerPromotion({session, questionId, piece,
atMs})`; `invalidate(reason)`; `edit()` / `connect()` (= `invalidate`, round 5); `tick(atMs)`; `snapshot(atMs?)` (with a time it runs
`tick(atMs)` first; round 7: both apply the picture-gap rule, so a time more than maxPictureGapMs past the last picture revokes). Each returns the snapshot plus `event`. No clock reads, no randomness. Every input is copied to plain data once,
then validated (round 5: a getter cannot show validation one value and the tracker another; round 6: the copy has no prototype, so
an own `__proto__` key, as `JSON.parse` makes it, is an extra field and is refused).
**`fen`/`lastMove` null unless `trackingReady`**; `guidanceAllowed` always false. Single-picture rows: `scripts/simulation/occupancy-tracker-single-frame.mjs` only.

## State machine (usable = no square unknown or below minConfidence)
| state | input | result |
|---|---|---|
| any | `invalidate`, malformed picture, same sequence with other hash/time, picture older than clock - maxSilenceMs | revoke |
| any | picture, tick or answer more than maxSilenceMs ahead of the clock (clock not moved, picture not recorded) | revoke `observation-timeout` |
| any | foreign session/epoch; the exact same picture again; not confirmed (incl. older sequence or time) | ignored, no change |
| confirmed, after its first picture | older sequence, or time not later than the last picture | revoke `reordered-picture` (round 6) |
| confirmed, after its first picture | a sequence number skipped | revoke `missing-picture` (round 6) |
| confirmed | more than maxPictureGapMs since the last picture that showed the board (or since the review), seen by a picture or (round 7) by `tick` / `snapshot(atMs)` | revoke `picture-gap` (round 6; tick and snapshot round 7) |
| confirmed | a frameSha256 already seen (last 8,192), new sequence; or captured before the confirm / answer time | evidence only (round 6): feeds the swap memory and every revoke check; never counted, never refreshes timers; ignored `duplicate-frame` / `before-confirmation`. Round 7b: while ready, a repeated image that shows a change revokes `replayed-picture-changed` |
| confirmed | > maxSilenceMs since last counted usable picture | revoke `observation-timeout` |
| confirmed | `no-legal-explanation`, not in transit | revoke |
| confirmed | unusable or in-transit picture | skip: voids pending agreement; > maxSkippedUnusable in a row revokes; ready -> `confirming-change` |
| confirmed | skipped picture lifting a different own square than the remembered lift | revoke `different-piece-lifted` |
| confirmed | a lift remembered, then a usable `unchanged` picture | revoke `lifted-piece-returned` |
| confirmed | any picture since the last completed agreement showed a definite change, then a usable `unchanged` picture | revoke `changed-and-returned` |
| any agreement completing | pieces may have traded squares behind the pictures (see Swap rule) | revoke `pieces-may-have-swapped` |
| castling agreement completing | any picture since the last agreement showed the castling squares other than before / rook-first half / after | revoke `castling-not-seen-safely` (round 6) |
| any agreement | same reading again sooner than minFrameGapMs | ignored `too-soon` (no timer refresh, nothing reset) |
| verifying | agreeFrames x `unchanged`, captured after confirm/answer | `ready` |
| verifying | any move / promotion reading | revoke `confirmed-position-not-seen` |
| ready / confirming-change | reading K (move, promotion squares, unchanged) | count K; another K restarts at 1 |
| confirming-change | agreeFrames x same move spanning max(minSettleMs, readyDwellMs) (castlingRookSettleMs for Rh1-f1 etc. with that right, if larger) | FEN advances, `ready` |
| confirming-change | agreeFrames x promotion squares spanning minSettleMs / agreeFrames x unchanged | question / `ready` on old FEN |
| awaiting-promotion-choice | same promotion squares / anything else / > promotionTimeoutMs | wait / revoke / revoke |
| awaiting-promotion-choice | answer: same session, current id, q/r/b/n | FEN advances, `verifying` (not ready) |
| any | answer: bad piece, stale id, foreign session, none pending, second / malformed or atMs before last picture | rejected, nothing changes (not even the clock) / revoke |
Terminal positions accept no move. **In transit** (`inTransitTolerance`, default OFF since round 4): versus the tracked FEN exactly one
own square (side to move) reads empty, at most one other square unknown, all else unchanged. It can only suspend readiness and
count toward the skip cap; it cannot advance, count toward agreement, refresh the timer or keep a position trusted. Not while a
question is open. **Lift memory** (both modes): a skipped picture that shows exactly one own square emptied, others unchanged or
unknown, is remembered until the next usable picture; a second, different lift revokes, and so does a return to `unchanged`.
**Swap rule** (round 5, both modes): from one completed agreement to the next, the tracker keeps every square that any kept picture
read differently from the expected position (unknown included). When an agreement completes, the squares the agreed move itself
changes are taken to follow the move; if any OTHER disturbed square holds a piece afterwards while the disturbed squares held two or
more piece types of that colour before, the pieces could have traded squares unseen, so it revokes. Covers both colours and cycles of
any length. A definite change that ends with the board `unchanged` always revokes (a parked piece cannot be told from a swap).
**Either-colour rule** (round 7; the fifth review's candidate R1, chosen by the orchestrator over R2): the partner need not
show up in any picture. It can trade squares entirely inside one picture gap, or be a spare or captured piece brought from off
the board. So when an agreement completes, any disturbed square (hidden or misread in some picture) that the move does not change
and that still holds a piece of EITHER side revokes `pieces-may-have-swapped`, whether a move was played or not (including the
verification after a review or a promotion answer). This replaces the round-5 condition (two or more piece types of that colour
disturbed), which it contains. R2 (only the side that moved during a move) was measured first and left the opponent's pieces open.
**Captured-square exception** (round 7b, sixth review G7): the squares a move changes are normally excused, but not a captured
piece's square that read unknown in some picture since the last agreement. While hidden, the piece there could have traded places
with another piece of its colour (the d5 pawn with the d8 queen), so "pawn takes pawn" may really have taken the queen. A hand
covering that square while the capture is in progress gives exactly the same readings (the capturing piece lifted, the target
square unknown), so it cannot be told apart and revokes too; this is the price of the rule. A captured square that was only ever
read empty, or as the capturing colour, is still excused (that sequence is the pure one-gap case below).
**Watching rule** (round 6): every picture the tracker receives while confirmed either feeds that memory or revokes, and a stretch
it did not watch (gap > maxPictureGapMs, a missing or reordered picture) revokes. **Castling** (round 6) is the only legal move that
moves two pieces of one colour, so its own squares cannot show which piece went where (Rh1-g1 then Ke1-f1 ends like O-O); it is
accepted only if every picture since the last agreement showed those four squares as before, as after the rook-first half, or as
after castling.

## Decisions (each with its safety argument)
- **Agreement key = base FEN + exact reading**: two different positions never agree. **Skipped pictures void agreement** (round 4):
  a hand may have changed something unseen, so readiness after any skip needs agreeFrames pictures taken after it.
- **Unknowns skip** (2 in a row) instead of revoking; `maxSkippedUnusable: 0` reproduces the old tracker's rule.
- **Settle time and dwell**: a move needs agreeing pictures spanning max(minSettleMs 300, readyDwellMs 1000). Round 4 used 300 ms
  alone, and a bishop resting 300 ms on e2 on its way to c4 was accepted as Be2 and trusted for one picture (review round 3).
  Since round 5 the move is not accepted, and the tracker is not ready, until the new position has been in view for 1 s; a piece
  that moves on earlier starts a new count and the real move is accepted instead. Cost: about 1 s more before advice. Rook-first castling looks exactly like Rh1-f1, so that move (only while the castling
  right exists) needs 1.5 s; a castling paused longer is taken as the rook move and the king's crossing then revokes (refusal).
- **Promotion**: question only after agreement; id `promotion:<sessionId>:<epoch>:<instanceId>:<n>`; answer, then verify.
- **Time**: tick and answer times obey the picture bound. `confirm({atMs})` may jump: it is the resynchronisation point.
- **Ids**: `instanceId` reuse throws within one JavaScript realm; across processes the caller must supply a fresh one (app: a
  UUID per launch). **Replay**: a replayed feed with its original sequence numbers is refused by the sequence rule; one
  re-stamped with new sequences and times is caught only within the 8,192-hash window (about 14 min at 10 pictures/s).

## What the tracker still cannot detect (both settings, after round 7b)
1. A piece exchanged for another of the same colour on the same square (no picture can show it).
2. **Any exchange completed between two consecutive pictures with nothing read differently** (sixth review, F2). Two pieces
   that trade squares, or a spare that replaces a piece, entirely between one picture and the next, with every square of every
   picture read correctly, is invisible to occupancy: no picture differs from the tracked board. Measured on round 7b (review
   `attacks.mjs`): still board 28 of 28 trusted wrong (G1), spare replacement 4 of 4 (G2), during a normal move 2 of 2 (G3).
   Rounds 6 and 7 described this window as closed; that was wrong. **The protection is physical, and becomes wiring requirement
   14:** a hand needs at least one picture interval to make such an exchange, and the pipeline must read any square a hand
   covers as `unknown` (never as its old colour), so that the exchange shows up as a hidden square, which the swap rule refuses.
3. **The moving piece itself (hole (c)).** If the piece that lands on the destination is not the piece that left the origin,
   every picture shows exactly the occupancy of the legal move. It needs **no hidden square**, works at one hand action per
   picture interval, and includes captures: the mover trades places with another own piece (for example "Ng1-f3" where the bishop
   really lands on f3 and the knight on c1; review G4, 1 of 1 trusted wrong), or is replaced by a spare piece of its colour
   ("Bc4" that is really a spare knight; G5, 1 of 2 on round 7b, 2 of 2 on round 7: the review's capture variant, "Bxf7" by a
   spare queen, hid the captured square and is now refused by the round-7b captured-square rule; the same substitution with no
   square hidden is still invisible, inferred from the readings being identical). Fifth-review set on round 7b: 5 of 5 (3 of 3 partner, 2 of 2 substitute). **Castling** can also end
   with king and rook interchanged (king on f1, rook on g1 reads like O-O): G6, 2 of 5 trusted wrong. **No rule on occupancy
   alone can close this**, because the moving piece is in the hand exactly like any other piece. Only reading piece TYPES (on the
   destination square, on both castling squares, and on any square that was hidden) would close it.
4. A piece that rests on a square for longer than readyDwellMs (1 s) is taken as played there; if it then moves on, the tracker
   revokes (`b3`: Be2 trusted for one picture after a 1,050 ms rest; the board did show Be2 for that second).

Closed in round 7 (either-colour rule), with measured counts on the real tracker: **hole (a)**, two same-colour pieces trading
squares while one square is hidden and the board then looks unchanged or the same side moves: trusted 72 of 144 and 2 of 4 in
round 6, **0 of 144 and 0 of 4** now. **Hole (b)**, a hand hides one square and puts down a spare or captured piece of the same
colour: trusted 22 of 24 in round 6, **0 of 24** now. Before round 7, hole (b) had **no time limit**: the replaced square itself is
hidden, so the picture-gap rule never fires (the review's long pattern hid it for 2 of every 3 pictures over about 1.8 s), whereas
the round-6 version of this document described the window as one picture gap. **Opponent pieces** (`c1-extra-opponent.mjs`): a
hidden opponent piece traded with another opponent piece inside one gap, or replaced by a spare, while the other side plays a
normal move: trusted 12 of 12 with round 6 and with R2, **0 of 12** since round 7. Closed in round 7b: **captured piece traded
while hidden** (G7): 12 of 12 trusted wrong on round 7, **0 of 12** now. What stays open of the old "one-gap window" is only the
case where nothing was read differently (item 2) and the moving piece itself (item 3).

**King-first castling will usually need a re-review.** FIDE rules say to move the king first. A picture with the king lifted
(e1 empty, rook still home) revokes: `no-legal-explanation` with `inTransitTolerance` off (the default), and
`castling-not-seen-safely` with it on (fifth review, `c3-round6-rules.log`); a king set on g1 with the rook still home revokes
`no-legal-explanation`, and a hand over a castling square fails the castling check. So a castling made king first, as it
normally is, will usually revoke and ask the person to review. Rook first, or both pieces moved between two pictures, is accepted.

Round 4 claimed the swap blind spot needed every picture in between to be
unusable or missing; that was wrong: review round 3 swapped knight and bishop through a parking square in four fully readable
pictures and round 4 trusted the swapped board (585 of 585 fuzzed positions, rule on and off). Round 5's swap rule refuses that and
the unknown-square case (`swap-hidden`, trusted 100 of 100 in round 4). Cost: lifting a piece and putting it back (j'adoube),
setting a piece down and taking it back, and any move made while a hand hides a different piece of that colour revoke. Round 7
adds: any occupied square (either colour) that was hidden or misread since the last agreement, and that the move does not change,
revokes, so a hand passing over any piece, or one misread on an occupied square, costs a re-review. Round 7b adds: a capture
whose captured square read unknown since the last agreement (for example a hand over it during the capture) revokes.

## Measured (round 7b; same seeds, SYNTHETIC occupancy, no images)
Round 7b evidence: `/Users/alexmunzon/chess-builds/tracker-round7b-2026-11-16/` (the sixth review's `attacks.mjs`,
`attacks2.mjs`, `fuzz.mjs`, `mutate.mjs` and the cost script, copied there and run against this tracker). Tests:
`node --test tests/occupancy-tracker.test.js`: **97 tests, 96 pass, 1 skipped** (opt-in cross-check, run separately: 1 of 1
passed), 0 fail. No existing assertion was changed in round 7b.
- Sixth-review attacks: G7 captured piece traded while hidden **0 of 12** (round 7: 12 of 12); I1-I4, L, M, P, T1-T5 all 0
  (for example L two or three plies in one gap 0 of 5,188 / 5,188 / 8,376). Still open, as documented above: G1 28 of 28,
  G2 4 of 4, G3 2 of 2 (pure one-gap), G4 1 of 1, G5 1 of 2, G6 2 of 5 (hole (c)), T6 1 of 1 (bare `snapshot()` without a time).
  Fifth-review `c1-hole.mjs`: A 0 of 144, B 0 of 4, D 0 of 24, C 3 of 3, E 2 of 2 (hole (c)).
- Fuzz (`fuzz.mjs`, physical board acted on between pictures): honest 398 episodes, 30,892 pictures: 0 wrong trusted;
  cheat-hidden 1,292 episodes, 29,940 pictures: 0 unexplained, 7 hole (c), 0 pure one-gap; cheat-any 1,291 episodes, 26,344
  pictures: 0 unexplained, 4 hole (c), 414 pure one-gap.
- Mutation check (`mutate.mjs`): 18 of 18 mutants caught by the tests (round 7: 15 of 18; M1g swap rule skipped at the promotion
  question, M1h skipped while verifying, M2f tick gap measured from the last usable picture now each have a test).
- Replayed image (sixth review D3): while ready, a repeated image (same hash, new sequence) that showed a move was answered
  "ready, ignored" in round 7; it now revokes `replayed-picture-changed`.

| re-reviews per 100 positions (50 games, 3,998 positions, agree 2) | round 7 | round 7b |
|---|---|---|
| hand over the board, setting off / on | 61.4 / 62.9 | **61.8 / 63.1** |
| capture, both pieces off | 6.7 | 6.7 |
| every other row (perfect 0; q=0.03 225.6; p=0.003 165.4; both 291.8; lifted 0.1; touch 0.4; king-first 0.15; rook-first 0; swap-hidden 1.25) | same | same |
Wrong accepted moves and wrong trusted pictures: 0 in every row, both columns. The capture row does not move because its model
removes both pieces without hiding a square; the captured-square cost appears in the hand row.

### Round 7 measurements
Round 7 evidence: `/Users/alexmunzon/chess-builds/tracker-round7-2026-11-16/` (logs named `*-R2.log` there are runs of the R2 rule; `*-R1.log` are the final round-7 code; the fifth review's `c1-hole.mjs` and
`c2-cost.mjs` copied there and pointed at this tracker, plus the same scripts run against the round-6 code for the "before"
column). Tests: `node --test tests/occupancy-tracker.test.js`: 88 tests, 87 pass, 1 skipped (opt-in cross-check, run separately: 1 of 1 passed), 0 fail.
Seven existing assertions were changed in round 7 because they pinned behaviour this round removes (a hidden piece followed by an
unchanged board was trusted; the black h8 rook hidden during White's move was accepted; `tick` / `snapshot` 500 ms after the last
picture was ready); each is marked "Round 7" in the test file.

| re-reviews per 100 positions (50 games, 3,998 positions, agree 2) | round 6 | R2 (measured, not used) | round 7 (either colour) |
|---|---|---|---|
| perfect readings | 0 | 0 | 0 |
| q=0.03 | 222.1 | 225.6 | 225.6 |
| p=0.003 | 165.4 | 165.4 | 165.4 |
| p=0.003, q=0.03 | 290.1 | 291.8 | 291.8 |
| hand over the board, setting off / on | 50.6 / 51.9 | 57.8 / 59.4 | **61.4 / 62.9** |
| piece lifted (on) | 0.1 | 0.1 | 0.1 |
| capture, both pieces off | 6.7 | 6.7 | 6.7 |
| touch | 0.4 | 0.4 | 0.4 |
| king-first / rook-first | 0.15 / 0 | 0.15 / 0 | 0.15 / 0 |
| own pieces swapped behind unknowns (`swap-hidden`) | 1.25 (refused 50 of 50) | 1.25 (refused 50 of 50) | 1.25 (refused 50 of 50) |
Wrong accepted moves and wrong trusted pictures: 0 in every row, all three columns. These 50-game runs use the cost script's
row set, so they differ slightly from the 100-game round-5 table below. The report never calls `tick` or `snapshot(atMs)`,
so the round-7 gap rule in `tick` does not change these rows.

### Round 6 measurements (seeded random games, SYNTHETIC occupancy, no images)
Round 6 evidence: `/Users/alexmunzon/chess-builds/occupancy-tracker-2026-11-16/round6/` (same six chunks as round 5, same seeds).
**Every row is identical to round 5 except two:** "piece lifted", setting ON, rises from 0 to 0.05 re-reviews per 100 positions
(castlings with a lifted-king or lifted-rook picture are now refused, `castling-not-seen-safely`), and "hand over the board"
has 1 castling refusal (its rate stays 51.0). The simulation delivers every picture in order, 150 ms apart, so the round-6
watching rules (gap, missing, reordered) never fire there; their cost in the field depends on the camera pipeline (requirements
10-12). Wrong accepted moves and wrong or stale trusted pictures: 0 in every agreeFrames >= 2 row, both settings (except
`touch-settle0`, switched off on purpose). Cross-check: 1,074 moves, 0 differences. Review round 4 scripts: `b2` 0 of 8, `b3`
mis-castling refused both settings; `b1` 4 of 9 still trusted, all inside one 150 ms gap (round 6's one-gap window; closed in round 7 except as listed above).
Review round 3 scripts: `a1b` not trusted, `a3` never ready on Be2, `f1-swap-fuzz` 0 of 585 in all six columns.

### Round 5 measurements (unchanged in round 6 except as noted above)
Evidence: `/Users/alexmunzon/chess-builds/occupancy-tracker-2026-11-16/round5/` (`chunk*.json` / `.log`, made by `run-chunk.mjs`
there: the report's rows run in six chunks to keep each run under 5 minutes, so per-row noise seeds differ from one full run).
Round 4 numbers: `round4/report.json`. 100 games, 8,048 positions, pictures 150 ms apart, instant re-review. **Model change:**
a position now gets enough pictures to stay in view for `readyDwellMs` (8 instead of 3), so each position meets more misreads.
- Wrong accepted moves and wrong or stale trusted pictures: **0 in every row at agreeFrames >= 2, both settings**, including
  `swap-hidden` (round 4: 100 of 100 episodes trusted wrong; now refused 100 of 100). Only `touch-settle0` (settle and dwell
  switched off on purpose) accepts wrong moves: 527 / 547. agreeFrames 1 (emulated, no dwell): 1 wrong at p=0.003, 4 at p=0.01.
- Review round 3 scripts: a1b not trusted (both settings); a3 never ready on Be2; a4 clock stays an integer; `f1-swap-fuzz`
  trusted 0 of 585 in all six columns (round 4: 585 of 585 in four of them).
- Cross-check vs `ObservationTracker` (settle and dwell 0): 1,069 plies + 5 promotions, 0 differences.

| re-reviews per 100 positions (agree 2) | round 4 off / on (noise rows on: review round 3 `t1.log`) | round 5 off / on | round 5, dwell 0, off / on |
|---|---|---|---|
| perfect readings | 0 / 0 | 0 / 0 | - |
| p=0.003 | 80.0 / 76.4 | 167.1 / 164.6 | 78.8 / - |
| q=0.03 | 99.7 / 99.8 | 221.2 / 221.2 | 99.6 / - |
| p=0.003, q=0.03 | 121.3 / 120.2 | 289.7 / 286.7 | 121.9 / - |
| hand over the board (~4,000 pictures) | 0 / 0 | **51.0 / 51.0** | 51.1 / 52.4 |
| piece lifted | 48.6 / 0 | 49.3 / 0 | - |
| capture, both pieces off | 6.9 / 7.2 | 7.1 / 6.7 | - |
| en passant / king-first / rook-first / rook-first held 600 ms | 0.03 / 0.15 / 0 / 0 (off) | 0.03 / 0.08 / 0 / 0 (off) | - |
| piece resting on its path 150 / 300 / 600 / 900 ms | 0.32 (150 only) | 0.32 / 0.49 / 0.68 / 1.13 off; 0.45 / 0.52 / 0.81 / 0.96 on | - |
| own pieces swapped: both lifts / one lift / behind unknowns | refused / refused / **trusted 100 of 100** | refused 100 of 100 each | - |
| promotion answer after 0 / 2 / 5 pictures | 11.4 / 11.0 / 11.3 | 0 / 0 / 10.6 | - |
Reading: the swap rule costs almost nothing on random noise (dwell-0 column = round 4) but refuses about half of all moves made
while a hand hides squares next to the destination (`pieces-may-have-swapped` about 26, plus the simulation's follow-on
`confirmed-position-not-seen` about 25). The dwell doubles the noise rows because each position is shown for longer. ON vs OFF
differs only where a piece is lifted (0 vs 49); `inTransitTolerance` stays OFF by default.

## How to wire it in (numbered requirements; nothing in `replay-runtime.js`, the bundle or `native/` was changed)
Each requirement names the check the wiring work must add before the tracker drives advice.
1. Bundle `core/occupancy-tracker.js` + `core/occupancy-move-inference.js` (15 -> 17 assets; update pins in
   `tests/device-runtime-assets.test.js` and `prepare_app.py`). Never bundle `scripts/simulation/*`. Check: the asset-pin test.
2. `initialize` gains `observationModel: "labels13-v1" | "occupancy-v1"` (schemaVersion 2); a session never mixes models.
   Check: a request mixing models is refused.
3. New kind `answerPromotion` `{session, questionId, piece}`. **Answer time rule (review round 4, finding 5):** `atMs` = the
   `capturedAtMs` of the latest picture the runtime has handled, never a live clock and never from the UI. (Round 6 also feeds
   pictures captured before `atMs` into the swap memory, so a later stamp can no longer hide a swap; the rule keeps it exact.)
   Check: an answer request whose `atMs` differs from the last handled picture's time is rejected by the runtime.
4. Replies add `state.pendingQuestion` (`questionId, from, to, color, options, sanByPiece, expiresAtMs`) or null
   (`REPLAY_REPLY_KEYS`, Swift decoders change); prompt: four SAN buttons, no default; dismiss = `invalidate`.
5. **Ready comes from `trackingReady`.** `src/core/device-game-session.js:96` sets `trackingReady: state.guidanceAllowed`; this
   tracker always returns `guidanceAllowed:false`, so map from its own `trackingReady`. Check: a reply after two agreeing pictures
   says `trackingReady:true`, one after `invalidate` says false.
6. `instanceId`: a fresh UUID per app launch from the native side; after a pause, `confirm` with `atMs` = camera time.
7. **Silence needs a time source (review round 3 finding 3; round 4 finding 5).** The tracker has no clock: a bare `snapshot()`
   stays ready forever if pictures stop. Today `ReplayRuntime`'s clock advances only from picture times
   (`src/core/replay-runtime.js:35-39`) and the `snapshot` request has no time field (`src/core/device-game-session.js:30`), so
   `snapshot(now)` could never time out there. The wiring must (a) add `atMs` to `snapshot` / timer requests, taken by the native
   side from the SAME monotonic clock that stamps `capturedAtMs`; (b) call `tracker.snapshot(atMs)` for them; (c) send one at least
   every 100 ms while advice is on screen (round 7b: was 500 ms, which is longer than the 250 ms gap rule, so advice could stay up
   to 500 ms after the feed stopped); (d) hide advice whose latest ready reply is older than 250 ms (`maxPictureGapMs`; was
   `maxSilenceMs`). Check: two agreeing
   pictures, then a snapshot request stamped 1,001 ms later replies `trackingReady:false, reason:observation-timeout`.
8. **Old method names (finding 4).** `device-game-session.js` calls `tracker.edit()` on its revoke path (line 90) and for
   `invalidate` (line 126), and `tracker.connect(sessionId).epoch` (line 116). `OccupancyTracker.edit()` and `.connect()` now exist
   and both revoke; `connect()` returns no `epoch` (session identity comes from `confirm`), so the adapter must not feed that value
   into pictures. Check: the adapter's revoke path, called while ready, returns `trackingReady:false` and does not throw.
9. **Drop stale engine results (finding 5).** Start engine work only on a FEN from a `trackingReady:true` reply, and remember that
   reply's `revision` and `fen`. When the result arrives, use it only if the LATEST reply is still `trackingReady:true` with the
   same `revision` and the same `fen`; otherwise discard it. Check: a picture that revokes (or a newly accepted move) while the
   engine runs makes the result be discarded.
10. **In-order, undropped delivery (round 4 finding 5).** Every picture the camera pipeline produces is passed to `ingest` once,
   in capture order, with consecutive `sequence` numbers; a frame the pipeline drops still uses up its number, so the tracker sees
   the gap and revokes (`missing-picture`) instead of trusting a board it did not watch. Never renumber to hide drops. Check: a
   run with one dropped frame replies `reason:missing-picture`.
11. **Real capture times.** `capturedAtMs` is the camera's capture time (monotonic, milliseconds), not the time the picture
   reached JavaScript; the gap (250 ms) and silence (1 s) rules are only as true as these stamps. Check: the native adapter test
   shows capture stamps strictly increasing and spaced like the camera's frame interval.
12. **Picture rate.** The camera must deliver at least **6 pictures per second** while a game is tracked. The hard limit is
   `maxPictureGapMs` = 250 ms between capture times, but at exactly 4 per second (250 ms) a picture 1 ms late revokes
   `picture-gap` (review round 5 measured it), so 4 per second has no margin; 6 per second (about 167 ms) leaves about 80 ms for
   jitter. Check: a 6-pictures-per-second feed with +-20 ms capture jitter stays trusted on a still board and through a
   normal move (tracker test `R7 timing`).
13. **Snapshot and tick times include pipeline delay (round 7).** `tick(atMs)` and `snapshot(atMs)` now revoke `picture-gap`
   when `atMs` is more than 250 ms past the capture time of the last picture the tracker has received. A picture still being
   processed counts as not watched, so the time between capture and `ingest` (pipeline latency) plus the picture interval must
   stay under 250 ms when a snapshot is requested, or the snapshot revokes. **Budget:** at 6 pictures per second the interval is
   about 167 ms, which leaves about **83 ms** from capture to `ingest`; at 10 per second (100 ms) it leaves 150 ms. Check: measure
   that latency on the phone before wiring; if it is longer, deliver pictures before snapshot requests or raise the picture rate.
14. **A covered square must read unknown (round 7b, sixth review F2).** Occupancy cannot see an exchange completed between two
   pictures with nothing read differently (see "What the tracker still cannot detect", item 2). The protection is that any square
   under a hand or arm reads `unknown` (or below `minConfidence`) in that picture, never its previous colour. Check: on recorded
   frames with a hand over the board, every square the hand covers is reported unknown or low-confidence.

**Not verified:** pure logic, synthetic independent errors, random games, no images/camera/phone, not wired in, instant re-review.

## Wiring (2026-11-16): connected to the phone runtime, OFF by default, no picture source

**What exists.** The bundled runtime (`native/ChessCompanionRuntime/runtime.js`) holds one `OccupancyTracker` behind five request
kinds (the fifth, `trackerAnswerPromotion`, added 2026-11-17). The tracker file is copied unmodified (18 runtime assets: `core/occupancy-tracker.js` and `core/occupancy-move-inference.js`
added; pinned in `scripts/build-device-runtime.mjs`, `prepare_app.py`, `NativeEngineRuntime.swift` and
`tests/device-runtime-assets.test.js`). **The app has no camera or other picture source, and none is approved.** Nothing in the app
sends readings today; the plumbing is proved only with scripted SYNTHETIC readings (`tests/tracker-wiring.test.js`, and three
self-test checks). The tracker gives no advice: every reply says `guidanceAllowed:false`, and nothing in the app reads its replies yet.

**The setting.** The app stores no settings, so the switch is a launch argument, `--occupancy-tracker-on`, read once per process
(`native/ChessCompanionApp/TrackerSetting.swift`) and passed to `NativeEngineRuntime(resourceDirectory:occupancyTracker:)`
(default `false`). Only a developer launch tool can pass it; no screen can turn it on. **Off (the default):** Swift refuses every
tracker kind with "Occupancy tracker disabled." before readiness checks, slots or WebKit, and `runtime.js` refuses them too
(`TRACKER_DISABLED`) unless the host passes the boolean `true` with the request; Swift passes its own setting there, so the page
gate holds even if both Swift gates were removed (round 2; checked with a macOS build of `NativeEngineRuntime.swift` with its gates
deleted). With the setting off, the two tracker files are loaded but no tracker object is created and no tracker code runs (the
tracker is created on the first request the gate lets through). Engine and Replay requests behave as before.

**Request kinds** (`schemaVersion:1`, `requestId`, `kind`, no `mode`; exact keys; replies `{..., mode:"occupancy-tracking",
guidanceAllowed:false, trackingReady, state}` where `state` is the tracker's own view):
- `trackerStart {session{sessionId,epoch}, fen, reviewed{5 ticks}, atMs}`: `confirm` (always revokes first). `atMs` is required.
- `trackerIngest {reading{identity, capturedAtMs, squares}}`: one picture, passed on exactly as received.
- `trackerSnapshot {atMs}`: `snapshot(atMs)`, so the silence and 250 ms picture-gap rules run. `atMs` is required.
- `trackerStop {}`: `invalidate('stopped')`.
- `trackerAnswerPromotion {session{sessionId,epoch}, questionId, piece, atMs}` (2026-11-17): the person's answer to the open
  promotion question, passed to `answerPromotion`. Rules below ("Promotion answer").

**Pending-slot rule.** The runtime used to have one pending slot that every new request supersedes. Tracker requests now have their
own second slot in `NativeEngineRuntime` (`occupancyPending`): a tracker request never cancels, waits for, or is cancelled by an engine
or Replay request, and `runtime.js` handles it synchronously without touching the engine (no `engine.cancel()`). A second tracker
request while one is pending is refused ("Runtime busy; occupancy tracker request refused."), except `trackerStop`, which is never
refused: it supersedes the pending tracker request. Why not share the old slot: a tracker request
superseding an analysis would be safe but would cancel every analysis at 10 polls per second; an analysis blocking tracker
requests would starve the 250 ms gap rule and revoke on every search. Neither the second slot nor its refusals can keep advice
alive: they only add or drop tracker traffic, and the engine slot is unchanged (`engineKinds`, `trackerKinds`, `mayReplace` are as
before, so `RuntimeGuardChecks.swift` still holds). Runtime close or failure settles both slots.

**Any failed tracker request revokes (round 2).** If a tracker request fails on the Swift side for any reason (refused as busy,
timed out, its task cancelled, a page error, a refusal from the page), Swift then runs `chessDeviceRuntime.revokeOccupancy()` on
the page, which invalidates the tracker if one exists (it never creates one or restores trust). Page scripts run in the order they
are sent, so the revoke runs after the failed request if that request reached the page at all. So a start that Swift reports as
timed out cannot leave a tracker that later becomes ready, a cancelled or superseded stop still revokes, and a reading refused as
busy revokes even if the caller sends it again (round 1 relied on a sequence gap, which a resend hides). **Rule for callers: any
error from a tracker request means trust is gone; only a later successful `trackerStart` (a new human review) can restore it.**
A reply that was already on its way when another request failed can still say ready; callers must use only the latest reply.
Checks: `tests/tracker-wiring.test.js` (revoke entry, no tracker while off) and a macOS harness against the real
`NativeEngineRuntime.swift` in a headless WKWebView (`/Users/alexmunzon/chess-builds/tracker-wiring-2026-11-16/round2/swift/`).

**Boundary guards in `runtime.js`** (each refusal also revokes the tracker first; refusing is always allowed):
- A snapshot without `atMs`, or with a time that is not a nonnegative safe integer: refused `TIME_REQUIRED`, revoked. A bare
  `snapshot()` is never called.
- A reading of the current session whose sequence number is not greater than the last one passed on, or whose capture time is not
  later: refused `OUT_OF_ORDER`, revoked (`invalidated:reading-out-of-order`). Readings are never sorted, deduplicated or
  renumbered; a skipped number reaches the tracker, which revokes `missing-picture` (but a caller that numbers pictures when it sends
them, instead of when they are captured, hides a dropped picture from this rule: requirement 10). This is stricter than the tracker alone, which
  ignores an exact repeat.
- A malformed reading (not exactly identity / capturedAtMs / 64 squares with valid labels) or a malformed request: refused
  `INVALID_REQUEST`, revoked.
- A `trackerStart` time is taken as given. A start stamped far in the future (for example wall-clock milliseconds while pictures
  carry a capture clock, or `Number.MAX_SAFE_INTEGER`) moves the tracker's clock there for good: every later reading is
  `stale-frame` and the tracker never becomes ready again until the runtime is recreated. This fails closed (no trust), but it
  makes the switch useless for that runtime; the start time must come from the same clock as the pictures.
Checks: `tests/tracker-wiring.test.js` (15 tests then, 22 with the promotion tests); each round-1 guard was removed in a private copy and its test failed (evidence:
`/Users/alexmunzon/chess-builds/tracker-wiring-2026-11-16/mutation/`).

**Promotion answer (2026-11-17).** `trackerAnswerPromotion` follows every rule above: Swift refuses it with the setting off (before
readiness checks), it uses the occupancy slot, it is refused as busy while another tracker request is pending (a stop still
supersedes it), the page gate applies, and any Swift-side failure revokes. On the page:
- Malformed (not exactly the four fields, a session that is not `{sessionId, epoch}`, a non-string `questionId`, `atMs` not a
  nonnegative safe integer) or a piece other than `q`, `r`, `b`, `n`: refused `INVALID_REQUEST` and revoked
  (`invalidated:invalid-promotion-answer`), with or without an open question. The tracker itself only rejects an unknown piece
  without revoking; the runtime is stricter because a wrong piece is a caller bug. An oversized answer (over 16,384 bytes) never
  reaches the page: Swift refuses it and revokes, as for any request it cannot classify.
- Late or unmatched answers have **no effect** (reply `state.event:"answer-rejected"`, `accepted:false`, nothing changes, not even
  the revision): another session (`foreign-session`), no open question (`no-pending-question`: after a stop, a new start, any revoke
  or an accepted answer), another question (`stale-question`), or an `atMs` other than the capture time of the last reading passed on
  (`late-answer`; requirement 3's time rule: a newer reading arrived, or the stamp is not a picture time). This follows the tracker,
  whose own rejections change nothing. It cannot keep advice alive: while a question is open the tracker is never ready, and with no
  question open the answer is never passed to the tracker. These checks run before `answerPromotion`, because that method revokes an
  answer stamped before its last picture, which would let a late answer for an old question revoke a tracker that is ready again.
- Conflicting answers revoke (review round 2, 2026-11-17): the page remembers the piece of every accepted answer, across stops and
  new starts, and never forgets one. When 1,024 answers are remembered (far beyond any game), the next answer is refused
  `ANSWER_MEMORY_FULL` and revokes (`invalidated:promotion-memory-full`), so no promotion can be trusted on that page any more:
  fail closed rather than evict (round 2 evicted the oldest of 256, so a conflict on an evicted question was missed). A later answer to the same question with a DIFFERENT piece is doubt: refused `ANSWER_CONFLICT` and revoked
  (`invalidated:conflicting-promotion-answer`), whether the tracker is still verifying or already ready. The identical answer again is
  a no-op (`no-pending-question`). Round 1 rejected the different piece without revoking, so advice stayed on with the first piece.
- Accepted: the tracker moves to `verifying` (never straight to ready) and is ready only after fresh agreeing readings of the
  promoted position captured after `atMs`. An expired question still revokes (`promotion-timeout`) inside `answerPromotion`.
Checks: `tests/tracker-wiring.test.js` (18 promotion and random-source tests, 33 in all), `RuntimeGuardChecks.swift` (6 new live checks, 21 in all:
setting off on a started and an unstarted runtime, busy refusal that revokes, stop superseding a pending answer, oversized answer
revokes, an answer with a `mode` field is refused by Swift and revokes, an answer with no question open passes Swift's reply checks
and keeps trust), and the self-test check `occupancy-tracker-on-honest-promotion-trusted` plus `trackerAnswerPromotion` in
`occupancy-tracker-off-refuses-every-request` (compiled for the phone, not run). Mutation and the reviewer's page attacks: evidence in
`/Users/alexmunzon/chess-builds/promotion-wiring-2026-11-17/mutation/` (round 1) and `round2/`.

**Requirements above, status after this wiring.**
- Done here: 1 (bundle); 3 (`trackerAnswerPromotion`, 2026-11-17, with the time rule); 7(a) and 7(b) (snapshot needs `atMs` and calls `snapshot(atMs)`); 10 at the runtime boundary (in order, once,
  never renumbered: an out-of-order or repeated reading revokes).
- Not applicable to this design: 2, 4 and 8 (the tracker has its own request kinds instead of going through `initialize` /
  `ReplayRuntime` / `device-game-session.js`); 5 (`trackingReady` comes from the tracker's own field).
- Done here: 6 (review round 2, 2026-11-17). The `instanceId` is `device-occupancy-N-<32 hex>`, the hex being 128 random bits from
  the page's `crypto.getRandomValues` when the tracker is created (the same strength as a native UUID, with no new native surface:
  nothing to pass at start, nothing for Swift to validate). A question id from before a page reload therefore never matches one
  asked after it, even with the same session and epoch and a camera clock that restarted; the old answer is rejected
  `stale-question` with nothing changed (test "promotion, review finding 2"). With no random source the tracker is not created and
  the request is refused. Review round 3: a missing `crypto`, a missing or throwing `getRandomValues`, or an all-zero draw
  (a broken source) refuses every tracker request with `RANDOM_UNAVAILABLE` and creates no tracker; engine requests are unaffected,
  and the tracker is created on the first request after the source works.
- **Must hold when a picture source is connected; not verifiable today:** one monotonic clock for `capturedAtMs` and snapshot `atMs`
  (7(a), 11); a snapshot at least every 100 ms while advice is shown, and advice hidden when its latest ready reply is older than
  250 ms (7(c), 7(d)); every picture delivered once and in order, a dropped one keeping its number (10); at least 6 pictures per
  second (12); capture-to-ingest latency within the budget (13); a covered square read `unknown` (14); stale engine results
  dropped by revision and FEN (9), because nothing consumes the tracker yet; and interruptions (background, an edit, leaving the
  mode, reset) sending `trackerStop`. **Nothing in the app sends tracker requests except the self-test**, so whoever connects a
  picture source must add that interruption handling.
- **Still open, unchanged by wiring:** hole (c), the moving piece itself exchanged or substituted; and the nothing-hidden exchange
  between two pictures (item 2 of "What the tracker still cannot detect"). Occupancy alone cannot see either.
