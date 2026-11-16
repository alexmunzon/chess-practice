# Occupancy tracker (pure logic, 2026-11-16, round 6 after four reviews; not wired into the app)

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
`tick(atMs)` first). Each returns the snapshot plus `event`. No clock reads, no randomness. Every input is copied to plain data once,
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
| confirmed | more than maxPictureGapMs since the last picture that showed the board (or since the review) | revoke `picture-gap` (round 6) |
| confirmed | a frameSha256 already seen (last 8,192), new sequence; or captured before the confirm / answer time | evidence only (round 6): feeds the swap memory and every revoke check; never counted, never refreshes timers; ignored `duplicate-frame` / `before-confirmation` |
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

## What occupancy can never detect (both settings, after round 6)
1. A piece exchanged for another of the same colour on the same square (no picture can show it).
2. **The one-gap window.** A square whose piece is replaced by another piece of the same colour (and a different type) entirely
   between two consecutive pictures, so no picture shows that square disturbed. The partner piece may be in plain view as the
   piece being moved, or hidden under a hand: review round 4 (`b1`) replaced the c1 bishop with the b1 knight inside one 150 ms gap
   while b1 read unknown, and the tracker trusted the swapped board (also after Ng1-f3). Round 6 closes the same trick in any
   longer gap (`picture-gap`), but inside one gap it cannot be closed without refusing every move, because the moving piece is
   in the hand exactly like a hidden piece. **Size at the defaults: one replacement must be completed within maxPictureGapMs = 250
   ms (in practice one picture interval, about 150 ms at 7 pictures/s) with every picture delivered in order.**
3. A piece that rests on a square for longer than readyDwellMs (1 s) is taken as played there; if it then moves on, the tracker
   revokes (`b3`: Be2 trusted for one picture after a 1,050 ms rest; the board did show Be2 for that second).
Round 4 claimed the swap blind spot needed every picture in between to be
unusable or missing; that was wrong: review round 3 swapped knight and bishop through a parking square in four fully readable
pictures and round 4 trusted the swapped board (585 of 585 fuzzed positions, rule on and off). Round 5's swap rule refuses that and
the unknown-square case (`swap-hidden`, trusted 100 of 100 in round 4). Cost: lifting a piece and putting it back (j'adoube),
setting a piece down and taking it back, and any move made while a hand hides a different piece of that colour revoke.

## Measured (round 6; seeded random games, SYNTHETIC occupancy, no images)
Round 6 evidence: `/Users/alexmunzon/chess-builds/occupancy-tracker-2026-11-16/round6/` (same six chunks as round 5, same seeds).
**Every row is identical to round 5 except two:** "piece lifted", setting ON, rises from 0 to 0.05 re-reviews per 100 positions
(castlings with a lifted-king or lifted-rook picture are now refused, `castling-not-seen-safely`), and "hand over the board"
has 1 castling refusal (its rate stays 51.0). The simulation delivers every picture in order, 150 ms apart, so the round-6
watching rules (gap, missing, reordered) never fire there; their cost in the field depends on the camera pipeline (requirements
10-12). Wrong accepted moves and wrong or stale trusted pictures: 0 in every agreeFrames >= 2 row, both settings (except
`touch-settle0`, switched off on purpose). Cross-check: 1,074 moves, 0 differences. Review round 4 scripts: `b2` 0 of 8, `b3`
mis-castling refused both settings; `b1` 4 of 9 still trusted, all inside one 150 ms gap (the one-gap window above).
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
   every 500 ms while advice is on screen; (d) hide advice whose latest reply is older than `maxSilenceMs`. Check: two agreeing
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
12. **Picture rate.** The camera must deliver pictures at least every 250 ms (`maxPictureGapMs`) while a game is tracked, or the
   tracker revokes `picture-gap`. Check: a 4-pictures-per-second feed stays trusted on a still board.

**Not verified:** pure logic, synthetic independent errors, random games, no images/camera/phone, not wired in, instant re-review.
