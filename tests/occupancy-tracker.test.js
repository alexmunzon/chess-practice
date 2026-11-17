import test from 'node:test';
import assert from 'node:assert/strict';
import { Chess } from 'chess.js';
import { OccupancyTracker, PROMOTION_PIECES, isGameOver } from '../src/core/occupancy-tracker.js';
import { SingleFrameSimulationTracker } from '../scripts/simulation/occupancy-tracker-single-frame.mjs';
import { OCCUPANCY_SQUARES } from '../src/core/occupancy-move-inference.js';
import { positionPayload, loadPosition } from '../src/core/position.js';
import { rng, randomMove, runReport, crossCheck } from '../scripts/simulation/occupancy-tracker-report.mjs';

// SYNTHETIC occupancy pictures built from chess.js boards; no images or classifier involved.
const reviewed = { pieces: true, turn: true, castling: true, enPassant: true, counters: true };
const START = new Chess().fen();
const fenOf = chess => chess.fen({ forceEnpassantSquare: true });
const hash = n => n.toString(16).padStart(64, '0');
function squaresOf(chess, overrides = {}) {
  return Object.fromEntries(OCCUPANCY_SQUARES.map(sq => {
    const piece = chess.get(sq);
    return [sq, overrides[sq] ?? { label: piece ? (piece.color === 'w' ? 'white' : 'black') : 'empty', confidence: 1 }];
  }));
}
// Every reply must hide the FEN unless tracking is ready (check 2h), checked on every call.
function guard(view) {
  if (!view.trackingReady) { assert.equal(view.fen, null); assert.equal(view.lastMove, null); }
  else assert.equal(view.status, 'ready');
  assert.equal(view.guidanceAllowed, false);
  return view;
}
// Round 6: every test runs at the DEFAULT options (readyDwellMs 1000, maxPictureGapMs 250) unless it names an option it is
// about. Pictures are 150 ms apart; a move needs MOVE pictures (1,050 ms in view), a promotion question QUESTION (300 ms).
const MOVE = 8, QUESTION = 3;
function setup(fen = START, options = {}) {
  const tracker = new OccupancyTracker({ instanceId: uid(), ...options });
  const session = SESSION;
  let seq = 0, time = 0;
  guard(tracker.confirm({ session, fen, reviewed }));
  const chess = new Chess(fen);
  const picture = ({ board = chess, dt = 150, overrides, hash: fixedHash } = {}) => { time += dt; seq++; return { identity: { sessionId: 's1', epoch: 1, sequence: seq, frameSha256: fixedHash ?? hash(seq) }, capturedAtMs: time, squares: squaresOf(board, overrides) }; };
  const send = opts => guard(tracker.ingest(picture(opts)));
  // n pictures; all but the last must be pending (not ready); returns the last reply.
  const hold = (n, opts) => { for (let k = 1; k < n; k++) assert.equal(send(opts).trackingReady, false, `picture ${k} of ${n}`); return send(opts); };
  return { tracker, chess, session, picture, send, hold, now: () => time, wait: ms => { time += ms; } };
}
const unknownAt = sq => ({ [sq]: { label: 'unknown', confidence: 1 } });
const SESSION = { sessionId: 's1', epoch: 1 };
let uidCounter = 0;
const uid = (prefix = 't') => `${prefix}${++uidCounter}`;
// The single place answers are built (an old-API adapter for the round-1 failure proof edits only this function).
function answer(tracker, { questionId, piece, atMs, session = SESSION }) {
  return tracker.answerPromotion({ session, questionId, piece, atMs });
}

test('isGameOver matches positionPayload.gameOver', () => {
  for (const fen of [START, '7k/5QQ1/8/8/8/8/8/K7 b - - 0 1', '7k/5Q2/6K1/8/8/8/8/8 b - - 0 1', '7k/8/8/8/8/8/8/K6B w - - 0 1', '7k/8/8/8/8/8/R7/K1R5 w - - 150 90', '7k/8/8/8/8/8/R7/K1R5 w - - 149 90'])
    assert.equal(isGameOver(loadPosition(fen)), positionPayload(loadPosition(fen)).gameOver, fen);
});

// ---- a. readiness only after the confirmed position is seen ---------------------------------------
test('a: ready only after agreeFrames pictures of the confirmed position, at least minFrameGapMs apart', () => {
  const { tracker, send } = setup();
  assert.equal(guard(tracker.snapshot()).status, 'verifying');
  assert.equal(send().trackingReady, false);
  assert.equal(send({ dt: 10 }).event, 'too-soon');
  const ready = send();
  assert.equal(ready.trackingReady, true); assert.equal(ready.fen, START); assert.equal(ready.reason, 'confirmed-position-seen');
});
test('a: a first picture that does not match the confirmed position revokes; later matching pictures do not restore', () => {
  const { chess, send } = setup(); chess.move('e4');
  assert.equal(send().reason, 'confirmed-position-not-seen');
  chess.undo();
  for (let i = 0; i < 4; i++) assert.equal(send().trackingReady, false);
});
test('a: confirm needs a complete six-field FEN, all five ticks and a current session; failures throw and revoke', () => {
  const { tracker, send, session } = setup(); send(); send();
  assert.throws(() => tracker.confirm({ session, fen: START, reviewed: { ...reviewed, castling: false } }));
  assert.equal(guard(tracker.snapshot()).status, 'needs-confirmation');
  assert.throws(() => tracker.confirm({ session, fen: START.split(' ').slice(0, 4).join(' '), reviewed }));
  assert.throws(() => tracker.confirm({ session, fen: START, reviewed, extra: 1 }));
  tracker.confirm({ session: { sessionId: 's1', epoch: 2 }, fen: START, reviewed });
  assert.throws(() => tracker.confirm({ session, fen: START, reviewed }), e => e.code === 'STALE_IDENTITY');
  assert.equal(tracker.snapshot().reason, 'stale-review');
  for (const bad of [{ agreeFrames: 0 }, { agreeFrames: 11 }, { minConfidence: 0 }, { maxSilenceMs: 50 }, { promotionTimeoutMs: 0 }, { maxSkippedUnusable: -1 }, { instanceId: '' }, { instanceId: undefined }, { maxPictureGapMs: 0 }, { maxPictureGapMs: 1001 }]) assert.throws(() => new OccupancyTracker({ instanceId: 't', ...bad }));
});

// ---- b. move agreement ----------------------------------------------------------------------------
test('b: a move is accepted after agreeFrames agreeing pictures; FEN, SAN and move reported; unchanged afterwards stays ready', () => {
  const { chess, send } = setup(); send(); send();
  chess.move('e4');
  const first = send();
  assert.equal(first.status, 'confirming-change'); assert.equal(first.fen, null);
  for (let k = 2; k < MOVE; k++) assert.equal(send().event, 'agreement-pending', `picture ${k}: not yet 1 s in view`);
  const accepted = send();
  assert.equal(accepted.event, 'move-accepted');
  assert.equal(accepted.fen, fenOf(chess)); assert.equal(accepted.lastMove.san, 'e4'); assert.equal(accepted.lastMove.uci, 'e2e4');
  assert.equal(send().event, 'unchanged'); assert.equal(send().trackingReady, true);
});
test('b: one differing inference resets the count; pictures of two different positions never confirm each other', () => {
  const { chess, send, hold } = setup(); send(); send();
  const e3 = new Chess(); e3.move('e3'); chess.move('e4');
  send(); assert.equal(send({ board: e3 }).event, 'agreement-pending');
  assert.equal(send().event, 'agreement-pending', 'e4 picture after e3 picture starts a new count');
  assert.equal(hold(MOVE - 1).lastMove.san, 'e4');
  // Two consecutive plies shown as separate pictures: the later one has no legal explanation from the tracked FEN.
  const { chess: c2, send: s2 } = setup(); s2(); s2();
  c2.move('d4'); s2(); const behind = new Chess(); behind.move('d4');
  c2.move('d5');
  const r = s2();
  assert.equal(r.reason, 'no-legal-explanation'); assert.equal(s2({ board: behind }).trackingReady, false);
});
test('b: agreeFrames 3 needs three pictures', () => {
  const three = setup(START, { agreeFrames: 3 }); three.send(); assert.equal(three.send().trackingReady, false); assert.equal(three.send().trackingReady, true);
  three.chess.move('Nf3'); assert.equal(three.hold(MOVE).lastMove.san, 'Nf3');
  // With the dwell off, the count alone decides: three pictures.
  const count = setup(START, { agreeFrames: 3, readyDwellMs: 0 }); count.send(); count.send(); count.send();
  count.chess.move('Nf3'); count.send({ dt: 150 }); assert.equal(count.send().trackingReady, false); assert.equal(count.send().lastMove.san, 'Nf3');
});
test('b: castling and en passant are tracked from occupancy alone', () => {
  for (const [fen, move] of [['r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1', 'O-O-O'], ['4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2', 'exd6']]) {
    const { chess, send, hold } = setup(fen); send(); send(); chess.move(move);
    assert.equal(hold(MOVE).fen, fenOf(chess));
  }
});

// ---- c. no legal explanation ----------------------------------------------------------------------
test('c: skipped ply, knocked piece and a single misread revoke until a new confirm', () => {
  for (const make of [
    c => { c.move('e4'); c.move('e5'); },
    c => { c.remove('a7'); }, // knocked piece of the side not to move (an own piece missing is "in transit", see below)
    c => { c.move('e4'); c.remove('h7'); },
  ]) {
    const { chess, send, tracker, session } = setup(); send(); send();
    make(chess);
    assert.equal(send().reason, 'no-legal-explanation');
    for (let i = 0; i < 3; i++) assert.equal(send().trackingReady, false);
    tracker.confirm({ session, fen: fenOf(chess), reviewed }); send();
    assert.equal(send().trackingReady, true, 'only a new full review restores tracking');
  }
});

// ---- d. unknown squares, silence -------------------------------------------------------------------
test('d: pictures with unknown squares never advance the game, and agreement restarts after them (round 4)', () => {
  const { chess, send, hold } = setup(); send(); send(); chess.move('e4');
  send();
  assert.equal(send({ overrides: unknownAt('e4') }).event, 'skipped-unusable');
  // Round 5: low confidence on an EMPTY square (a3). On the a1 rook it would leave pawn and rook exchangeable: see 'R5 F1' tests.
  assert.equal(send({ overrides: { a3: { label: 'white', confidence: 0.5 } } }).event, 'skipped-unusable', 'low confidence counts as unknown');
  assert.equal(send().event, 'agreement-pending');
  const accepted = hold(MOVE - 1);
  assert.equal(accepted.lastMove.san, 'e4');
});
test('d: an unusable picture suspends readiness without revoking; agreeFrames usable pictures restore it', () => {
  const { chess, send, hold } = setup(); send(); send();
  chess.move('e4'); // the board changed, but the camera only sees it with unknown squares
  // Round 7 (rule R1): was unknownAt('h8'); hiding the black rook during White's move now revokes (it could have been
  // replaced unseen), so an empty square (h6) keeps this check about an unusable picture suspending readiness.
  const hidden = send({ overrides: unknownAt('h6') });
  assert.equal(hidden.trackingReady, false); assert.equal(hidden.reason, 'unusable-picture'); assert.equal(hidden.fen, null);
  assert.equal(hold(MOVE).lastMove.san, 'e4');
  // Round 7 changed this expectation: occluding the h8 ROOK and then seeing the same board used to restore
  // readiness; with no move in between the rook could have been replaced unseen, so it now revokes. An occluded EMPTY
  // square still only suspends readiness.
  send({ overrides: unknownAt('h5') }); send();
  assert.equal(send().trackingReady, true, 'same position seen again after an occlusion of an empty square');
  send({ overrides: unknownAt('h8') }); send();
  assert.equal(send().reason, 'pieces-may-have-swapped', 'occluded piece, no move: revokes (round 7)');
});
test('d: more than maxSkippedUnusable unusable pictures in a row revoke; strict maxSkippedUnusable 0 revokes on the first', () => {
  const { send } = setup(); send(); send();
  send({ overrides: unknownAt('a1') }); send({ overrides: unknownAt('a1') });
  assert.equal(send({ overrides: unknownAt('a1') }).reason, 'too-many-unusable-pictures');
  const strict = setup(START, { maxSkippedUnusable: 0 }); strict.send(); strict.send();
  assert.equal(strict.send({ overrides: unknownAt('a1') }).reason, 'uncertain-squares');
});
test('d: an unusable picture whose known squares contradict every hypothesis still revokes', () => {
  const { send, chess } = setup(); send(); send(); chess.remove('a7');
  assert.equal(send({ overrides: unknownAt('h8') }).reason, 'no-legal-explanation');
});
test('d: more than maxSilenceMs without a usable picture revokes (via a late picture or tick)', () => {
  const late = setup(); late.send(); late.send();
  assert.equal(late.send({ dt: 1001 }).reason, 'observation-timeout');
  assert.equal(late.send().trackingReady, false);
  const ticked = setup(); ticked.send(); ticked.send();
  // Round 7: was now() + 500; a tick more than maxPictureGapMs (250) after the last picture now revokes 'picture-gap'.
  assert.equal(guard(ticked.tracker.tick(ticked.now() + 250)).trackingReady, true);
  assert.equal(guard(ticked.tracker.tick(ticked.now() + 1001)).reason, 'observation-timeout');
  // unusable pictures do not refresh the watchdog
  const blind = setup(START, { maxSkippedUnusable: 50 }); blind.send(); blind.send();
  for (let i = 0; i < 4; i++) blind.send({ dt: 250, overrides: unknownAt('a1') });
  assert.equal(blind.send({ dt: 250, overrides: unknownAt('a1') }).reason, 'observation-timeout');
  assert.throws(() => ticked.tracker.tick(-1));
});

// ---- e. promotion question -------------------------------------------------------------------------
const PROMOTIONS = [
  ['white push', '7k/P7/8/8/8/8/8/7K w - - 0 1', 'a7', 'a8'],
  ['white capture-promotion', 'r3k3/1P6/8/8/8/8/8/4K3 w - - 0 1', 'b7', 'a8'],
  ['knight promotion gives check', '8/4k1P1/8/8/8/8/8/4K3 w - - 0 1', 'g7', 'g8'],
  ['black promotion, queen and rook give check', '4k3/8/8/8/8/8/p7/4K3 b - - 0 1', 'a2', 'a1'],
];
for (const [name, fen, from, to] of PROMOTIONS) test(`e: ${name}: all four answers give the right FEN`, () => {
  let sawCheck = false;
  for (const piece of PROMOTION_PIECES) {
    const { chess, send, tracker, now } = setup(fen); send(); send();
    const reference = new Chess(fen); const move = reference.move({ from, to, promotion: piece }); sawCheck ||= move.san.includes('+');
    chess.move({ from, to, promotion: 'q' }); // the picture is identical for every piece
    assert.equal(send().event, 'agreement-pending', 'no question before agreement');
    assert.equal(send().event, 'agreement-pending', 'no question before minSettleMs');
    const asked = send();
    assert.equal(asked.status, 'awaiting-promotion-choice'); assert.equal(asked.fen, null);
    assert.deepEqual([asked.pendingQuestion.from, asked.pendingQuestion.to], [from, to]);
    const answered = guard(answer(tracker, { questionId: asked.pendingQuestion.questionId, piece, atMs: now() }));
    assert.equal(answered.accepted, true); assert.equal(answered.status, 'verifying'); assert.equal(answered.answeredMove.san, move.san);
    assert.equal(send().trackingReady, false, 'answer, then agreeFrames fresh pictures');
    const seen = send();
    assert.equal(seen.reason, 'promotion-position-seen'); assert.equal(seen.fen, fenOf(reference)); assert.equal(seen.lastMove.san, move.san);
  }
  if (name.includes('check')) assert.ok(sawCheck);
});
function promotionAsked(options) {
  const h = setup('7k/P7/8/8/8/8/8/7K w - - 0 1', options); h.send(); h.send();
  h.chess.move({ from: 'a7', to: 'a8', promotion: 'q' }); h.send(); h.send();
  const asked = h.send(); assert.equal(asked.event, 'promotion-question');
  return { ...h, q: asked.pendingQuestion };
}
test('e: wrong-format, stale, unsolicited and second answers are rejected without advancing', () => {
  const unsolicited = setup(); unsolicited.send(); unsolicited.send();
  assert.equal(answer(unsolicited.tracker, { questionId: 'promotion:s1:1:t1:1', piece: 'q', atMs: unsolicited.now() }).rejected, 'no-pending-question');
  assert.equal(unsolicited.tracker.snapshot().trackingReady, true);
  const { tracker, q, now } = promotionAsked();
  for (const piece of ['k', 'Q', 'queen', 'p', '']) {
    const r = guard(answer(tracker, { questionId: q.questionId, piece, atMs: now() }));
    assert.equal(r.rejected, 'invalid-piece'); assert.equal(r.status, 'awaiting-promotion-choice');
  }
  assert.equal(guard(answer(tracker, { questionId: 'promotion:s1:1:t1:0', piece: 'q', atMs: now() })).rejected, 'stale-question');
  assert.equal(guard(answer(tracker, { questionId: q.questionId, piece: 'q', atMs: now(), session: { sessionId: 's1', epoch: 2 } })).rejected, 'foreign-session');
  assert.equal(answer(tracker, { questionId: q.questionId, piece: 'n', atMs: now() }).accepted, true);
  const second = guard(answer(tracker, { questionId: q.questionId, piece: 'q', atMs: now() }));
  assert.equal(second.rejected, 'already-answered'); assert.equal(second.status, 'verifying');
  const malformed = promotionAsked();
  assert.equal(guard(malformed.tracker.answerPromotion({ session: SESSION, questionId: malformed.q.questionId, piece: 'q', atMs: malformed.now(), extra: 1 })).reason, 'invalid-promotion-answer');
  assert.equal(answer(malformed.tracker, { questionId: malformed.q.questionId, piece: 'q', atMs: malformed.now() }).rejected, 'no-pending-question');
});
test('e: while waiting, pictures of the promoted position keep the silence watchdog alive but count toward promotionTimeoutMs', () => {
  const { tracker, send, q, now } = promotionAsked({ promotionTimeoutMs: 3000 });
  for (let i = 0; i < 12; i++) assert.equal(send({ dt: 250 }).event, 'awaiting-promotion-choice'); // 3000 ms: 3x the silence limit
  assert.equal(send({ dt: 250 }).reason, 'promotion-timeout');
  assert.equal(answer(tracker, { questionId: q.questionId, piece: 'q', atMs: now() }).rejected, 'no-pending-question');
  assert.equal(send().trackingReady, false);
  // An answer stamped after the deadline is rejected as expired.
  const late = promotionAsked({ promotionTimeoutMs: 500 });
  assert.equal(answer(late.tracker, { questionId: late.q.questionId, piece: 'q', atMs: late.q.expiresAtMs + 1 }).rejected, 'question-expired');
  assert.equal(late.tracker.snapshot().reason, 'promotion-timeout');
  const onTime = promotionAsked({ promotionTimeoutMs: 3000 });
  assert.equal(answer(onTime.tracker, { questionId: onTime.q.questionId, piece: 'q', atMs: onTime.now() + 900 }).accepted, true);
});
test('e: a picture showing a further change while the question is open revokes', () => {
  const { chess, send, tracker, q, now } = promotionAsked();
  chess.move('Kg7');
  assert.equal(send().reason, 'changed-while-awaiting-promotion');
  assert.equal(answer(tracker, { questionId: q.questionId, piece: 'q', atMs: now() }).accepted, false);
  const back = promotionAsked(); back.chess.undo();
  assert.equal(back.send().reason, 'changed-while-awaiting-promotion', 'pawn put back also revokes');
});
test('e: the question needs agreement on the same promotion squares', () => {
  const { chess, send } = setup('1r5k/P7/8/8/8/8/8/7K w - - 0 1'); send(); send();
  const push = new Chess(chess.fen()); push.move({ from: 'a7', to: 'a8', promotion: 'q' });
  chess.move({ from: 'a7', to: 'b8', promotion: 'q' });
  send({ board: push }); const r = send();
  assert.equal(r.event, 'agreement-pending'); assert.equal(r.pendingQuestion, null);
  assert.equal(send().event, 'agreement-pending'); assert.equal(send().event, 'promotion-question');
});

// ---- f. picture identity ----------------------------------------------------------------------------
test('f: older/repeated sequence ignored; same sequence with a different hash or time revokes; foreign session ignored', () => {
  const { tracker, picture, send } = setup(); send(); send();
  const p = picture(); tracker.ingest(p);
  const rev = tracker.snapshot().revision;
  assert.equal(tracker.ingest(p).ignored, 'repeated-frame');
  for (const [field, alter] of [['epoch', f => { f.identity.epoch = 9; }], ['session', f => { f.identity.sessionId = 'other'; }]]) {
    const foreign = picture(); alter(foreign); foreign.identity.sequence = p.identity.sequence + 1; foreign.capturedAtMs = p.capturedAtMs + 1;
    assert.equal(tracker.ingest(foreign).ignored, 'foreign-session', field);
  }
  assert.equal(tracker.snapshot().revision, rev); assert.equal(tracker.snapshot().trackingReady, true);
  // Round 6: while confirmed, an older sequence number revokes (it was 'ignored' before; a late picture can hide a swap).
  const older = picture(); older.identity.sequence = 1;
  assert.equal(guard(tracker.ingest(older)).reason, 'reordered-picture');
  const pre = setup(); const before = pre.picture(); pre.tracker.invalidate('x');
  assert.equal(pre.tracker.ingest(before).ignored, 'not-confirmed', 'while not confirmed nothing revokes');
  for (const alter of [f => { f.identity.frameSha256 = hash(999); }, f => { f.capturedAtMs += 1; }]) {
    const h = setup(); h.send(); h.send(); const a = h.picture(); h.tracker.ingest(a);
    const conflict = structuredClone(a); alter(conflict);
    assert.equal(guard(h.tracker.ingest(conflict)).reason, 'frame-identity-conflict');
  }
});
test('f: malformed pictures return a structured error and revoke', () => {
  for (const alter of [f => delete f.squares.a1, f => { f.squares.a1.label = 'P'; }, f => { f.squares.a1.confidence = 2; }, f => { f.capturedAtMs = 1.5; }, f => { f.identity.frameSha256 = 'x'; }, f => { f.extra = 1; }]) {
    const { tracker, picture, send } = setup(); send(); send();
    const p = picture(); alter(p);
    const r = guard(tracker.ingest(p));
    assert.equal(r.reason, 'invalid-observation'); assert.equal(typeof r.error, 'string');
  }
  const { tracker } = setup(); assert.equal(tracker.ingest(null).reason, 'invalid-observation');
});

// ---- g. nothing after invalidate or revoke restores readiness ---------------------------------------
test('g: pictures and answers after invalidate or revoke never restore readiness', () => {
  const { tracker, send, q, chess, now } = promotionAsked();
  assert.equal(guard(tracker.invalidate('background')).reason, 'invalidated:background');
  assert.equal(answer(tracker, { questionId: q.questionId, piece: 'q', atMs: now() }).accepted, false);
  for (let i = 0; i < 3; i++) assert.equal(send().trackingReady, false);
  chess.undo(); for (let i = 0; i < 3; i++) assert.equal(send().trackingReady, false);
  assert.equal(tracker.tick(1e6).trackingReady, false);
});

// ---- reviewer attacks (round 2; each failed against the round-1 module) ----------------------------
const unknownSquares = (...sqs) => Object.fromEntries(sqs.map(sq => [sq, { label: 'unknown', confidence: 1 }]));
const lowSquares = (...sqs) => Object.fromEntries(sqs.map(sq => [sq, { label: 'black', confidence: 0.5 }]));
test('attack S1: answer after the board changed behind unusable pictures never reports the stale position as ready', () => {
  for (const overrides of [unknownSquares('h8', 'g7'), lowSquares('h8', 'g7'), unknownSquares('a1')]) {
    const { chess, send, tracker, q, now } = promotionAsked();
    chess.move('Kg7'); // Black replies before the human answers
    send({ overrides }); send({ overrides });
    const answered = guard(answer(tracker, { questionId: q.questionId, piece: 'q', atMs: now() + 50 }));
    assert.equal(answered.trackingReady, false); assert.equal(answered.fen, null);
    const next = send();
    assert.equal(next.status, 'needs-confirmation', 'the reply is exposed (while waiting, or by the first fresh usable picture)');
    assert.match(next.reason, /^(confirmed-position-not-seen|changed-while-awaiting-promotion)$/);
  }
});
test('attack S1: after an answer only agreeFrames fresh pictures captured after atMs make it ready', () => {
  const { tracker, send, q, now, picture } = promotionAsked();
  const answeredAt = now() + 200;
  answer(tracker, { questionId: q.questionId, piece: 'r', atMs: answeredAt });
  const early = picture({ dt: 100 }); // captured before the answer, delivered after it: evidence only (round 6), not counted
  assert.equal(tracker.ingest(early).ignored, 'before-confirmation');
  assert.equal(send({ dt: 150 }).trackingReady, false);
  const ready = send();
  assert.equal(ready.reason, 'promotion-position-seen'); assert.match(ready.fen, /^R6k/); assert.equal(ready.lastMove.promotion, 'r');
});
test('attack S3.1: the same frameSha256 under a new sequence never counts twice (moves and verification)', () => {
  const { chess, send, tracker } = setup(); send(); send(); chess.move('e4');
  const a = 'a'.repeat(64);
  send({ hash: a });
  const dup = send({ hash: a });
  assert.equal(dup.ignored, 'duplicate-frame'); assert.equal(dup.trackingReady, false); assert.equal(dup.movesAccepted, 0);
  const fresh = setup(); const b = 'b'.repeat(64);
  fresh.send({ hash: b }); assert.equal(fresh.send({ hash: b }).trackingReady, false);
  // a frozen feed (only duplicates) does not count as watching the board: it revokes once the gap passes maxPictureGapMs
  assert.equal(fresh.send({ hash: b }).reason, 'picture-gap');
  assert.equal(tracker.snapshot().movesAccepted, 0);
});
test('attack S3.2: question ids carry session, epoch and instanceId and differ across tracker instances', () => {
  const [x, y] = [uid('x'), uid('y')];
  const ids = [x, y].map(instanceId => promotionAsked({ instanceId }).q.questionId);
  assert.notEqual(ids[0], ids[1]); assert.equal(ids[0], `promotion:s1:1:${x}:1`);
  const { tracker, q, now } = promotionAsked();
  assert.equal(answer(tracker, { questionId: q.questionId, piece: 'q', atMs: now(), session: { sessionId: 's2', epoch: 1 } }).rejected, 'foreign-session');
  assert.equal(tracker.snapshot().status, 'awaiting-promotion-choice');
});
test('attack S3.3: atMs is required and may not precede the last picture, so the promotion watchdog cannot be bypassed', () => {
  for (const atMs of [undefined, -1, 1.5]) {
    const { tracker, q } = promotionAsked({ promotionTimeoutMs: 1 });
    const r = guard(tracker.answerPromotion({ session: SESSION, questionId: q.questionId, piece: 'q', ...(atMs === undefined ? {} : { atMs }) }));
    assert.equal(r.reason, 'invalid-promotion-answer'); assert.equal(r.accepted, false);
  }
  const { tracker, q, now } = promotionAsked();
  assert.equal(answer(tracker, { questionId: q.questionId, piece: 'q', atMs: now() - 1 }).reason, 'invalid-promotion-answer');
  const expired = promotionAsked({ promotionTimeoutMs: 1 });
  assert.equal(answer(expired.tracker, { questionId: expired.q.questionId, piece: 'q', atMs: expired.now() + 2 }).rejected, 'question-expired');
});
test('attack S3.5: one far-future picture revokes but does not block normal pictures after a re-review', () => {
  const { tracker, send, session, picture, now } = setup(); send(); send();
  const bogus = picture(); bogus.capturedAtMs = 1e12;
  assert.equal(guard(tracker.ingest(bogus)).reason, 'observation-timeout');
  tracker.confirm({ session, fen: START, reviewed, atMs: now() }); // re-review stamped with the camera's time
  const normal = () => picture(); // the camera's own times continue normally
  tracker.ingest(normal()); assert.equal(guard(tracker.ingest(normal())).trackingReady, true);
});
test('attack probe T5: two plies with unusable pictures between never become ready on a wrong FEN', () => {
  for (const n of [0, 1, 2, 3]) {
    const { chess, send } = setup(); send(); send(); chess.move('e4'); send(); chess.move('e5');
    const replies = [];
    for (let i = 0; i < n; i++) replies.push(send({ overrides: unknownSquares('e7', 'e5') }));
    replies.push(send(), send());
    for (const r of replies) assert.ok(!r.trackingReady || r.fen === fenOf(chess), `n=${n}`);
    assert.equal(replies.at(-1).trackingReady, false);
  }
});

// ---- round 4: second reviewer (each failed against the round-3 module) ------------------------------------------
const lifted = (chess, ...squares) => { const c = new Chess(chess.fen()); for (const sq of squares) c.remove(sq); return c; };
const edit = (fen, ops) => { const c = new Chess(fen); for (const [op, sq, piece] of ops) { if (op === 'rm') c.remove(sq); else c.put(piece, sq); } return c; };
const T = { inTransitTolerance: true };
test('R4 S2-1: two own pieces swapped through two in-transit pictures revoke (different-piece-lifted), both colours', () => {
  for (const [fen, n, r, rank, colour] of [[START, 'g1', 'h1', '1', 'w'], ['rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1', 'g8', 'h8', '8', 'b']]) {
    const { send } = setup(fen, T); send(); send();
    assert.equal(send({ board: edit(fen, [['rm', n]]) }).event, 'skipped-in-transit');
    const second = send({ board: edit(fen, [['rm', n], ['rm', r], ['put', n, { type: 'r', color: colour }]]) });
    assert.equal(second.reason, 'different-piece-lifted', rank);
    const swapped = edit(fen, [['rm', n], ['rm', r], ['put', n, { type: 'r', color: colour }], ['put', r, { type: 'n', color: colour }]]);
    assert.equal(send({ board: swapped }).trackingReady, false); assert.equal(send({ board: swapped }).trackingReady, false);
  }
});
test('R4 S2-1+: a lift that ends unchanged revokes (a fast swap looks exactly like a piece put back)', () => {
  const { chess, send } = setup(START, T); send(); send();
  send({ board: lifted(chess, 'g1') });
  const swapped = edit(START, [['rm', 'g1'], ['rm', 'h1'], ['put', 'g1', { type: 'r', color: 'w' }], ['put', 'h1', { type: 'n', color: 'w' }]]);
  assert.equal(send({ board: swapped }).reason, 'lifted-piece-returned');
  const back = setup(START, T); back.send(); back.send(); back.send({ board: lifted(back.chess, 'g1') });
  assert.equal(back.send().reason, 'lifted-piece-returned', 'j\'adoube costs a re-review, as with the rule off');
});
test('R4 S2-1+: a lift seen under unknown squares is remembered; a swap behind it ends unchanged and revokes (rule on or off)', () => {
  const fine = setup(START, T); fine.send(); fine.send();
  const hidden = fine.send({ board: lifted(fine.chess, 'g1'), overrides: unknownAt('f3') });
  assert.equal(hidden.event, 'skipped-unusable'); assert.equal(hidden.liftedSquare, 'g1', 'a lift seen under unknowns is remembered too');
  const swapped = edit(START, [['rm', 'g1'], ['rm', 'h1'], ['put', 'g1', { type: 'r', color: 'w' }], ['put', 'h1', { type: 'n', color: 'w' }]]);
  assert.equal(fine.send({ board: swapped }).reason, 'lifted-piece-returned');
  const off = setup(); off.send(); off.send(); off.send({ board: lifted(off.chess, 'g1'), overrides: unknownAt('f3') });
  assert.equal(off.send({ board: swapped }).reason, 'lifted-piece-returned', 'same with the rule off');
});
test('R4 S2-2: any skipped picture (unknowns or in transit) voids agreement collected before it', () => {
  for (const options of [{}, T]) {
    const { chess, send, hold } = setup(START, options); send(); send(); chess.move('e4');
    send();
    if (options.inTransitTolerance) assert.equal(send({ board: lifted(new Chess(), 'e2') }).event, 'skipped-in-transit');
    else assert.equal(send({ overrides: unknownAt('h6') }).event, 'skipped-unusable'); // round 7 (R1): was h8, the black rook
    assert.equal(send().event, 'agreement-pending', 'count restarts after the skipped picture');
    assert.equal(hold(MOVE - 1).lastMove.san, 'e4');
  }
  // Round 7: the occluded square was a8 (a rook); with the round-7 rule that now revokes, so an empty square (a5) keeps this check
  // about skipped pictures voiding agreement.
  const pre = setup(); pre.send({ overrides: unknownAt('a5') }); pre.send();
  pre.send({ overrides: unknownAt('a5') });
  assert.equal(pre.send().trackingReady, false, 'one settled picture after a skipped one is not enough');
  assert.equal(pre.send().trackingReady, true);
});
test('R4 S2-3: a move needs agreeing pictures spanning minSettleMs (300 ms); a piece set down in passing is not taken', () => {
  const D0 = { readyDwellMs: 0 }; // this test is about minSettleMs alone
  const { chess, send } = setup(START, D0); send(); send(); chess.move('Nf3');
  send({ dt: 150 }); assert.equal(send({ dt: 150 }).event, 'agreement-pending', '150 ms is too short');
  assert.equal(send({ dt: 150 }).lastMove.san, 'Nf3');
  const touch = setup('4k3/8/8/8/8/8/8/R3K3 w Q - 0 1', D0); touch.send(); touch.send();
  const passing = edit('4k3/8/8/8/8/8/8/R3K3 w Q - 0 1', [['rm', 'a1'], ['put', 'a2', { type: 'r', color: 'w' }]]);
  touch.send({ board: passing, dt: 100 }); assert.equal(touch.send({ board: passing, dt: 100 }).movesAccepted, 0);
  touch.chess.move('Ra5'); touch.send({ dt: 100 }); touch.send({ dt: 100 }); touch.send({ dt: 100 });
  assert.equal(touch.send({ dt: 100 }).lastMove.san, 'Ra5');
});
test('R4 S2-3: rook-first castling ends as castling (rook move held 900 ms is not accepted: castlingRookSettleMs 1500)', () => {
  const fen = 'r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1';
  const { chess, send, hold } = setup(fen); send(); send();
  const rookFirst = edit(fen, [['rm', 'h1'], ['put', 'f1', { type: 'r', color: 'w' }]]);
  for (let i = 0; i < 7; i++) assert.equal(send({ board: rookFirst }).movesAccepted, 0); // 900 ms
  chess.move('O-O'); assert.equal(hold(MOVE).lastMove.san, 'O-O');
  // a real Rf1 (held 1,500 ms) is still accepted
  const real = setup(fen); real.send(); real.send(); real.chess.move('Rf1');
  assert.equal(real.hold(11).lastMove.san, 'Rf1');
});
test('R4 S3b: tick and answer times obey the forward bound; a rejected answer never moves the clock', () => {
  const { tracker, send, now, session } = setup(); send(); send();
  const before = tracker.snapshot().virtualClockMs;
  assert.equal(guard(tracker.tick(1e12)).reason, 'observation-timeout');
  assert.equal(tracker.snapshot().virtualClockMs, before);
  tracker.confirm({ session, fen: START, reviewed }); send(); assert.equal(send().trackingReady, true, 'normal pictures still work');
  const a = promotionAsked(); const clock = a.tracker.snapshot().virtualClockMs;
  assert.equal(answer(a.tracker, { questionId: 'promotion:nope', piece: 'q', atMs: a.now() + 900 }).rejected, 'stale-question');
  assert.equal(a.tracker.snapshot().virtualClockMs, clock, 'rejected answer did not move the clock');
  const far = answer(a.tracker, { questionId: 'promotion:nope', piece: 'q', atMs: 1e12 });
  assert.equal(far.rejected, 'time-jump'); assert.equal(far.reason, 'observation-timeout', 'checked before anything else, even for a stale id');
  assert.equal(a.tracker.snapshot().virtualClockMs, clock);
  void now;
});
test('R4 S3f: too-soon pictures neither refresh the silence timer nor reset anything', () => {
  const { chess, send } = setup(START, { minFrameGapMs: 900, maxPictureGapMs: 1000 }); send(); send({ dt: 900 }); chess.move('e4');
  send({ dt: 300 });
  assert.equal(send({ dt: 400 }).event, 'too-soon'); assert.equal(send({ dt: 400 }).event, 'too-soon');
  assert.equal(send({ dt: 250 }).reason, 'observation-timeout', '1050 ms since the last counted picture');
});
test('R4 S3c: an instanceId cannot be reused in the same process', () => {
  const id = uid('dup'); new OccupancyTracker({ instanceId: id });
  assert.throws(() => new OccupancyTracker({ instanceId: id }), /instanceId/);
});
test('R4 S3d: a replayed feed with its original sequence numbers is refused by the sequence rule', () => {
  const { tracker, picture, send } = setup(); const recorded = [picture(), picture(), picture()];
  for (const p of recorded) tracker.ingest(p);
  send();
  // Round 6: while confirmed, the first replayed picture revokes; after that nothing is confirmed and the rest are ignored.
  assert.equal(guard(tracker.ingest(recorded[0])).reason, 'reordered-picture');
  for (const p of recorded.slice(1)) assert.equal(tracker.ingest(p).ignored, 'repeated-or-reordered-frame');
});
test('R4 S3e / S2: agreeFrames below 2 is refused by every route; the single-picture emulation lives only in scripts/simulation', async () => {
  const module = await import('../src/core/occupancy-tracker.js');
  assert.equal(Object.keys(module).some(k => /single|simulation/i.test(k)), false);
  assert.throws(() => new OccupancyTracker({ instanceId: uid(), agreeFrames: 1 }));
  assert.throws(() => new OccupancyTracker({ instanceId: uid(), agreeFrames: 1 }, Symbol('simulation-only')));
  const sim = new SingleFrameSimulationTracker({ instanceId: uid('sim') });
  assert.equal(sim.options.agreeFrames, 1);
});

// ---- in-transit pictures (round 3 rule, round 4 default OFF): a lifted piece is skipped like an unusable picture ----
test('transit: a lifted-piece picture between positions does not revoke; the move is then accepted by agreement', () => {
  const { chess, send, hold } = setup(START, T); send(); send();
  const r = send({ board: lifted(chess, 'e2') });
  assert.equal(r.event, 'skipped-in-transit'); assert.equal(r.reason, 'piece-in-transit'); assert.equal(r.liftedSquare, 'e2');
  assert.equal(r.trackingReady, false); assert.equal(r.fen, null); assert.equal(r.movesAccepted, 0);
  chess.move('e4');
  const accepted = hold(MOVE);
  assert.equal(accepted.event, 'move-accepted'); assert.equal(accepted.lastMove.san, 'e4'); assert.equal(accepted.fen, fenOf(chess));
});
test('transit: more than maxSkippedUnusable in-transit pictures in a row revoke; they never refresh the silence limit', () => {
  const { chess, send } = setup(START, T); send(); send();
  const board = lifted(chess, 'g1');
  send({ board }); send({ board });
  assert.equal(send({ board }).reason, 'too-many-unusable-pictures');
  const slow = setup(START, { ...T, maxSkippedUnusable: 50 }); slow.send(); slow.send();
  for (let i = 0; i < 4; i++) assert.equal(slow.send({ dt: 250, board: lifted(slow.chess, 'g1') }).event, 'skipped-in-transit');
  assert.equal(slow.send({ dt: 250, board: lifted(slow.chess, 'g1') }).reason, 'observation-timeout');
});
test('transit: a missing piece of the side NOT to move, two missing pieces, a colour change or an extra piece revoke at once', () => {
  for (const make of [c => lifted(c, 'e7'), c => lifted(c, 'e2', 'd2'), c => { const b = lifted(c, 'e2'); b.remove('a1'); b.put({ type: 'r', color: 'b' }, 'a1'); return b; },
    c => { const b = lifted(c, 'e2'); b.put({ type: 'p', color: 'w' }, 'e5'); return b; }]) {
    const { chess, send } = setup(START, T); send(); send();
    assert.equal(send({ board: make(chess) }).reason, 'no-legal-explanation');
  }
});
test('transit: middle states of a capture, en passant and king-first castling still revoke', () => {
  const cap = setup('4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1', T); cap.send(); cap.send();
  assert.equal(cap.send({ board: lifted(cap.chess, 'e4', 'd5') }).reason, 'no-legal-explanation', 'both pieces off the board');
  const ep = setup('4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2', T); ep.send(); ep.send();
  assert.equal(ep.send({ board: edit('4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2', [['rm', 'e5'], ['put', 'd6', { type: 'p', color: 'w' }]]) }).reason, 'no-legal-explanation');
  const fen = 'r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1', kf = setup(fen, T); kf.send(); kf.send();
  assert.equal(kf.send({ board: lifted(kf.chess, 'e1') }).event, 'skipped-in-transit');
  assert.equal(kf.send({ board: edit(fen, [['rm', 'e1'], ['put', 'g1', { type: 'k', color: 'w' }]]) }).reason, 'no-legal-explanation');
});
// Round 5 changed this test's expectation (it used to accept e4): the same pictures fit "knight to e4, pawn to g1", so
// accepting e4 could trust a wrong placement. It now revokes when the agreement completes.
test('transit: lifting one piece, then playing a different piece revokes (the two could have traded squares; round 5)', () => {
  const { chess, send, hold } = setup(START, T); send(); send();
  send({ board: lifted(chess, 'g1') }); // Ng1 lifted and put back between pictures, then e2-e4 played
  chess.move('e4');
  assert.equal(send().event, 'agreement-pending');
  const done = hold(MOVE - 1);
  assert.equal(done.reason, 'pieces-may-have-swapped'); assert.equal(done.movesAccepted, 0);
});
test('transit: inTransitTolerance defaults to false (old revoke) and must be a boolean', () => {
  const strict = setup(); strict.send(); strict.send();
  assert.equal(strict.tracker.options.inTransitTolerance, false);
  assert.equal(strict.send({ board: lifted(strict.chess, 'e2') }).reason, 'no-legal-explanation');
  assert.throws(() => new OccupancyTracker({ instanceId: uid(), inTransitTolerance: 'yes' }));
});
test('transit: not applied while a promotion question is open (the promoted piece lifted again revokes)', () => {
  const { chess, send } = promotionAsked(T);
  assert.equal(send({ board: lifted(chess, 'a8') }).reason, 'changed-while-awaiting-promotion');
});

// ---- 3. property test: random legal games, perfect readings, oracle promotion answers -----------
const PROMOTION_RICH = '7k/PPPP4/8/8/8/8/pppp4/7K w - - 0 1';
// 3 pictures per position (8 at the default readyDwellMs), 150 ms apart; a promotion position gets agreeFrames more.
function playThrough(tracker, games, seed) {
  const random = rng(seed), agree = tracker.options.agreeFrames; let seq = 0, time = 0, plies = 0, promotions = 0, questions = 0, revokes = 0, staleReady = 0;
  const finals = [];
  for (let g = 0; g < games; g++) {
    const chess = new Chess(g % 2 ? PROMOTION_RICH : START), session = { sessionId: 'prop', epoch: g + 1 };
    tracker.confirm({ session, fen: fenOf(chess), reviewed, atMs: time });
    let last = null;
    const look = () => {
      // At least 3; with the round-5 dwell, enough to keep the new position in view for readyDwellMs (8 at 1000 ms).
      const perPosition = Math.max(3, Math.ceil(tracker.options.readyDwellMs / 150) + 1);
      for (let k = 0; k < perPosition + (last?.promotion ? agree : 0); k++) {
        time += 150; seq++;
        const r = guard(tracker.ingest({ identity: { ...session, sequence: seq, frameSha256: hash(seq) }, capturedAtMs: time, squares: squaresOf(chess) }));
        if (r.event === 'revoked') revokes++;
        if (r.trackingReady && r.fen !== fenOf(chess)) staleReady++;
        if (r.event === 'promotion-question') { questions++; guard(tracker.answerPromotion({ session, questionId: r.pendingQuestion.questionId, piece: last.promotion, atMs: time })); }
      }
    };
    for (let ply = 0; ply < (g % 2 ? 30 : 60); ply++) {
      look();
      if (isGameOver(chess)) break;
      last = randomMove(chess, random); if (!last) break;
      chess.move(last); plies++; if (last.promotion) promotions++;
    }
    look();
    finals.push([tracker.snapshot().fen, fenOf(chess)]);
  }
  return { plies, promotions, questions, revokes, staleReady, finals };
}
test('property: seeded random games with perfect readings track to the exact final FEN (agreeFrames 2, 3; 1 via the simulation emulation)', () => {
  for (const agreeFrames of [1, 2, 3]) for (const inTransitTolerance of [false, true]) {
    const tracker = agreeFrames === 1 ? new SingleFrameSimulationTracker({ instanceId: uid('p'), inTransitTolerance }) : new OccupancyTracker({ instanceId: uid('p'), agreeFrames, inTransitTolerance });
    const r = playThrough(tracker, 4, 20261116 + agreeFrames);
    assert.equal(r.revokes, 0); assert.equal(r.staleReady, 0);
    assert.ok(r.promotions >= 4, `${r.promotions} promotions`);
    assert.equal(r.questions, r.promotions);
    for (const [tracked, truth] of r.finals) assert.equal(tracked, truth);
    assert.ok(r.plies > 120, `${r.plies} plies`);
  }
});

// ---- 4. cross-check against the existing 13-label tracker (slow: opt-in) --------------------------
test('cross-check: same readiness, accepted moves and FENs as ObservationTracker on perfect readings; one question per promotion',
  { skip: process.env.OCCUPANCY_CROSS_CHECK ? false : 'opt-in: set OCCUPANCY_CROSS_CHECK=1 (about 10 s of chess.js work)' }, () => {
  const plain = crossCheck({ minNonPromotionPlies: 200, seed: 77, startFens: [START] });
  assert.equal(plain.mismatches, 0, JSON.stringify(plain.examples));
  assert.ok(plain.nonPromotionPlies >= 200);
  assert.equal(plain.acceptedMovesNew, plain.acceptedMovesOld); assert.equal(plain.acceptedMovesNew, plain.nonPromotionPlies + plain.promotions);
  const promo = crossCheck({ minNonPromotionPlies: 10, plies: 24, seed: 78, startFens: [PROMOTION_RICH] });
  assert.equal(promo.mismatches, 0, JSON.stringify(promo.examples));
  assert.ok(promo.promotions >= 3); assert.equal(promo.questions, promo.promotions); assert.equal(promo.acceptedMovesNew, promo.acceptedMovesOld);
});

// ---- report determinism, noisy readings with unknowns, delayed answers, in-between pictures ---------
test('report: tiny run is deterministic; agreeFrames >= 2 never accepts a wrong move or reports a stale position', () => {
  const args = { games: 1, plies: 30, seed: 5, agree: [1, 2], p: [0, 0.01], q: [0, 0.03], crossCheckPlies: 0,
    extraRows: [{ agreeFrames: 2, p: 0, q: 0, answerDelay: 2, patience: 0.5, games: 'promotion-rich' },
      ...['hand', 'lifted', 'swap-seen', 'swap-fast', 'rook-first-paused', 'touch'].flatMap(inBetween => [false, true].map(inTransitTolerance => ({ agreeFrames: 2, p: 0, q: 0, inBetween, trackerOptions: { inTransitTolerance } })))], promotionGames: 2 };
  const a = JSON.stringify(runReport(args)), b = JSON.stringify(runReport(args));
  assert.equal(a, b);
  const report = JSON.parse(a);
  for (const row of report.rows) {
    if (row.p === 0 && row.q === 0 && !row.inBetween && !row.answerDelay) { assert.equal(row.revokes, 0); assert.equal(row.gamesTrackedToFinalFen, row.games); }
    if (row.agreeFrames >= 2) { assert.equal(row.wrongAcceptedMoves, 0, JSON.stringify(row)); assert.equal(row.wrongTrusted, 0, JSON.stringify(row)); }
  }
  assert.ok(report.rows.some(r => r.q === 0.03 && r.agreeFrames === 2 && r.pictures > 0));
  assert.ok(report.rows.find(r => r.answerDelay === 2).promotionPrompts > 0);
});

// ---- round 5: third reviewer (F1, F2, F6 each fail against the round-4 module) ----------------------------------
const AFTER_E5 = 'rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2';
// Occupancy-level picture builder: `over` maps squares to labels on top of `fen`'s occupancy.
function rig(fen, options = {}) {
  const tracker = new OccupancyTracker({ instanceId: uid('r5'), ...options });
  const base = Object.fromEntries(OCCUPANCY_SQUARES.map(sq => { const p = new Chess(fen).get(sq); return [sq, p ? (p.color === 'w' ? 'white' : 'black') : 'empty']; }));
  let seq = 0, time = 1000;
  tracker.confirm({ session: SESSION, fen, reviewed, atMs: time });
  const pic = (over = {}, dt = 150) => {
    time += dt; seq++;
    const squares = Object.fromEntries(OCCUPANCY_SQUARES.map(sq => [sq, { label: over[sq] ?? base[sq], confidence: 1 }]));
    return guard(tracker.ingest({ identity: { ...SESSION, sequence: seq, frameSha256: hash(seq) }, capturedAtMs: time, squares }));
  };
  pic(); assert.equal(pic().trackingReady, true);
  // raw: a picture with an explicit sequence number and capture time (does not move the rig's own counters).
  const raw = (over, sequence, at, h = 1e6 + sequence) => guard(tracker.ingest({ identity: { ...SESSION, sequence, frameSha256: hash(h) }, capturedAtMs: at,
    squares: Object.fromEntries(OCCUPANCY_SQUARES.map(sq => [sq, { label: over[sq] ?? base[sq], confidence: 1 }])) }));
  return { tracker, pic, raw, now: () => time, seq: () => seq };
}
const placementOf = fen => fen.split(' ')[0];
const swappedPlacement = (fen, a, b) => { const c = new Chess(fen), pa = c.get(a), pb = c.get(b); c.remove(a); c.remove(b); c.put(pb, a); c.put(pa, b); return placementOf(c.fen()); };
// Runs a picture sequence; fails if any reply is ready on a placement other than `truth` (null = no reply may be ready).
function neverTrustsWrong(r, sequence, truthAt) {
  const replies = [];
  sequence.forEach((over, k) => { const reply = r.pic(over); replies.push(reply); if (reply.trackingReady) assert.equal(placementOf(reply.fen), truthAt(k), `picture ${k}`); });
  return replies;
}
for (const inTransitTolerance of [false, true]) {
  test(`R5 F1: knight and bishop swapped through a parking square in fully readable pictures are never trusted (transit ${inTransitTolerance})`, () => {
    const r = rig(AFTER_E5, { inTransitTolerance });
    const swapped = swappedPlacement(AFTER_E5, 'g1', 'f1');
    // N to e2, B to g1, N to f1, then the swapped board held: no reply may be ready (every ready FEN would be the old placement).
    const replies = neverTrustsWrong(r, [{ g1: 'empty', e2: 'white' }, { f1: 'empty', e2: 'white' }, {}, {}, {}, {}], () => swapped);
    assert.equal(replies.at(-1).status, 'needs-confirmation');
  });
  test(`R5 F1: the same swap ending as a "move" (B on g1, N on e2 read as Be2, held 1.2 s) is refused (transit ${inTransitTolerance})`, () => {
    const r = rig(AFTER_E5, { inTransitTolerance });
    const truth = (() => { const c = new Chess(AFTER_E5); c.remove('g1'); c.remove('f1'); c.put({ type: 'b', color: 'w' }, 'g1'); c.put({ type: 'n', color: 'w' }, 'e2'); return placementOf(c.fen()); })();
    const replies = neverTrustsWrong(r, [{ g1: 'empty', e2: 'white' }, ...Array(9).fill({ f1: 'empty', e2: 'white' })], () => truth);
    assert.equal(replies.at(-1).reason, 'pieces-may-have-swapped'); assert.equal(replies.at(-1).movesAccepted, 0);
  });
  test(`R5 F1: two own pieces swapped behind unknown squares (both hidden in one picture) are refused (transit ${inTransitTolerance})`, () => {
    const r = rig(START, { inTransitTolerance });
    const replies = neverTrustsWrong(r, [{ g1: 'unknown', h1: 'unknown' }, {}, {}, {}], () => swappedPlacement(START, 'g1', 'h1'));
    assert.equal(replies.at(-1).reason, 'pieces-may-have-swapped');
  });
  test(`R5 F1: a three-piece cycle behind unknowns and lift pictures is refused (transit ${inTransitTolerance})`, () => {
    const r = rig(START, { inTransitTolerance });
    const cycled = (() => { const c = new Chess(); const [n, b, q] = ['g1', 'f1', 'd1'].map(s => c.get(s)); for (const s of ['g1', 'f1', 'd1']) c.remove(s); c.put(q, 'g1'); c.put(n, 'f1'); c.put(b, 'd1'); return placementOf(c.fen()); })();
    neverTrustsWrong(r, [{ g1: 'unknown', f1: 'unknown' }, { f1: 'unknown', d1: 'unknown' }, {}, {}, {}], () => cycled);
    assert.equal(r.tracker.snapshot().status, 'needs-confirmation');
  });
  test(`R5 F1: the opponent's knight and bishop swapped behind unknowns while White moves are refused (transit ${inTransitTolerance})`, () => {
    const r = rig(START, { inTransitTolerance });
    const c = new Chess(); c.move('e4');
    const truth = (() => { const t = new Chess(fenOf(c)); const [n, b] = [t.get('g8'), t.get('f8')]; t.remove('g8'); t.remove('f8'); t.put(b, 'g8'); t.put(n, 'f8'); return placementOf(t.fen()); })();
    const e4 = { e2: 'empty', e4: 'white' };
    const replies = neverTrustsWrong(r, [{ ...e4, g8: 'unknown', f8: 'unknown' }, ...Array(8).fill(e4)], () => truth);
    assert.equal(replies.at(-1).reason, 'pieces-may-have-swapped');
  });
}
test('R5 F1: refusals stay targeted: a piece resting on its path, castling and occlusions of a single piece still track', () => {
  const r = rig(AFTER_E5);
  for (let k = 0; k < 3; k++) r.pic({ f1: 'empty', e2: 'white' });
  let last; for (let k = 0; k < 8; k++) last = r.pic({ f1: 'empty', c4: 'white' });
  assert.equal(last.lastMove.san, 'Bc4');
  const fen = 'r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1', castle = rig(fen);
  castle.pic({ h1: 'empty', f1: 'white' });
  for (let k = 0; k < 8; k++) last = castle.pic({ h1: 'empty', e1: 'empty', f1: 'white', g1: 'white' });
  assert.equal(last.lastMove.san, 'O-O');
  const hidden = rig(START); hidden.pic({ g1: 'unknown' });
  // Round 7 changed this pin: it used to be trusted (the knight could have traded places with a piece inside one picture gap,
  // the documented residual window). The round-7 rule closes that window, so a hidden piece followed by an unchanged board revokes.
  assert.equal(hidden.pic().trackingReady, false); assert.equal(hidden.pic().reason, 'pieces-may-have-swapped', 'round 7');
});
test('R5 F1: a definite change that ends with the board unchanged revokes (changed-and-returned)', () => {
  const r = rig(START);
  r.pic({ g1: 'empty', f3: 'white' });
  assert.equal(r.pic().reason, 'changed-and-returned');
});

test('R5 F2: a piece resting 300, 600 or 900 ms on its way is never accepted; the real move is, after readyDwellMs', () => {
  for (const restPictures of [3, 5, 7]) for (const inTransitTolerance of [false, true]) {
    const r = rig(AFTER_E5, { inTransitTolerance });
    const bc4 = new Chess(AFTER_E5); bc4.move('Bc4');
    const replies = neverTrustsWrong(r, [...Array(restPictures).fill({ f1: 'empty', e2: 'white' }), ...Array(8).fill({ f1: 'empty', c4: 'white' })], () => placementOf(fenOf(bc4)));
    assert.ok(replies.every(x => x.lastMove?.san !== 'Be2' && x.acceptedMove?.san !== 'Be2'), `rest ${restPictures}`);
    assert.equal(replies.at(-1).fen, fenOf(bc4));
  }
});
test('R5 F2: a move is accepted only once its pictures span readyDwellMs (default 1000 ms); the option is validated', () => {
  const r = rig(START);
  assert.equal(r.tracker.options.readyDwellMs, 1000);
  const e4 = { e2: 'empty', e4: 'white' };
  for (let k = 0; k < 7; k++) assert.equal(r.pic(e4).trackingReady, false, `picture ${k}: ${150 * k} ms`);
  assert.equal(r.pic(e4).lastMove.san, 'e4', '1050 ms');
  const short = rig(START, { readyDwellMs: 450 });
  for (let k = 0; k < 3; k++) short.pic(e4);
  assert.equal(short.pic(e4).lastMove.san, 'e4');
  for (const readyDwellMs of [-1, 1.5, '1000']) assert.throws(() => new OccupancyTracker({ instanceId: uid(), readyDwellMs }));
});

test('R5 F6: inputs are validated as plain copies: a getter cannot hand the tracker a different value after validation', () => {
  const flip = (obj, key, good) => { let reads = 0; Object.defineProperty(obj, key, { enumerable: true, get: () => (++reads === 1 ? good : NaN) }); return obj; };
  const r = rig(START);
  const squares = Object.fromEntries(OCCUPANCY_SQUARES.map(sq => { const p = new Chess().get(sq); return [sq, { label: p ? (p.color === 'w' ? 'white' : 'black') : 'empty', confidence: 1 }]; }));
  r.tracker.ingest(flip({ identity: { ...SESSION, sequence: 99, frameSha256: 'f'.repeat(64) }, squares }, 'capturedAtMs', r.now() + 150));
  assert.ok(Number.isSafeInteger(r.tracker.snapshot().virtualClockMs));
  assert.equal(r.tracker.tick(r.now() + 3_600_000).reason, 'observation-timeout');
  const c = new OccupancyTracker({ instanceId: uid() });
  c.confirm(flip({ session: SESSION, fen: START, reviewed }, 'atMs', 5000));
  assert.equal(c.snapshot().virtualClockMs, 5000);
  const { tracker, q, now } = promotionAsked();
  const answered = tracker.answerPromotion(flip({ session: SESSION, questionId: q.questionId, piece: 'q' }, 'atMs', now()));
  assert.equal(answered.accepted, true); assert.ok(Number.isSafeInteger(answered.virtualClockMs));
  const thrower = { session: SESSION, questionId: 'x', piece: 'q' }; Object.defineProperty(thrower, 'atMs', { enumerable: true, get: () => { throw new Error('boom'); } });
  assert.equal(promotionAsked().tracker.answerPromotion(thrower).reason, 'invalid-promotion-answer');
});

test('R5 F3/F4: snapshot(atMs) runs the silence check; edit() and connect() revoke instead of throwing', () => {
  const r = rig(START);
  assert.equal(r.tracker.snapshot().trackingReady, true, 'without a time the reply is as fresh as the last picture');
  assert.equal(r.tracker.snapshot(r.now() + 250).trackingReady, true); // round 7: was + 500 (now a picture-gap revoke)
  assert.equal(r.tracker.snapshot(r.now() + 1001).reason, 'observation-timeout');
  assert.throws(() => rig(START).tracker.snapshot(NaN));
  for (const call of ['edit', 'connect']) {
    const x = rig(START); const out = guard(x.tracker[call]('anything'));
    assert.equal(out.trackingReady, false); assert.equal(out.event, 'revoked');
  }
});

// ---- round 6: fourth reviewer (each finding test fails against the round-5 module) ------------------------------
// Principle: every picture received while confirmed either feeds the disturbance memory or revokes, and any stretch the
// tracker did not watch longer than maxPictureGapMs (250 ms) revokes.
const PROMO6 = '7k/P7/8/8/8/8/8/KNB5 w - - 0 1';
for (const inTransitTolerance of [false, true]) {
  test(`R6 F1: pictures captured before a promotion answer still count as evidence; a swap in that window is refused (transit ${inTransitTolerance})`, () => {
    for (const lead of [300, 600]) {
      const r = rig(PROMO6, { inTransitTolerance });
      const promo = { a7: 'empty', a8: 'white' };
      let q; for (let k = 0; k < QUESTION && !q; k++) q = r.pic(promo).pendingQuestion;
      assert.ok(q);
      // The answer is stamped `lead` ms after the last picture; the knight/bishop swap is shown only in pictures captured
      // before that time (round 5 dropped them as 'before-confirmation' and then trusted the swapped board).
      const answered = r.tracker.answerPromotion({ session: SESSION, questionId: q.questionId, piece: 'q', atMs: r.now() + lead });
      assert.equal(answered.accepted, true);
      const swappedFen = swappedPlacement('Q6k/8/8/8/8/8/8/KNB5 b - - 0 1', 'b1', 'c1');
      const replies = [r.pic({ ...promo, b1: 'empty', d2: 'white' }, 100), r.pic({ ...promo, c1: 'empty', d2: 'white' }, 100)];
      for (let k = 0; k < 8; k++) replies.push(r.pic(promo, 150));
      for (const x of replies) assert.ok(!x.trackingReady || placementOf(x.fen) === swappedFen, `lead ${lead}`);
      assert.equal(r.tracker.snapshot().status, 'needs-confirmation', `lead ${lead}`);
    }
  });
  test(`R6 F2: while confirmed, a picture out of order or a missing sequence number revokes (transit ${inTransitTolerance})`, () => {
    const late = rig(AFTER_E5, { inTransitTolerance }); const s0 = late.seq(), t0 = late.now();
    assert.equal(late.raw({}, s0 + 3, t0 + 450).reason, 'missing-picture', 'pictures s0+1 and s0+2 never arrived');
    assert.equal(late.raw({ g1: 'empty', e2: 'white' }, s0 + 1, t0 + 150).trackingReady, false);
    const back = rig(AFTER_E5, { inTransitTolerance }); back.pic();
    assert.equal(back.raw({}, back.seq() - 1, back.now() + 100).reason, 'reordered-picture');
    const same = rig(AFTER_E5, { inTransitTolerance });
    assert.equal(same.raw({}, same.seq() + 1, same.now()).reason, 'reordered-picture', 'same capture time, new sequence');
    // A repeated image (same hash, new sequence) is evidence only: an old image that contradicts the board revokes.
    const dup = rig(START, { inTransitTolerance }); const old = dup.raw({}, dup.seq() + 1, dup.now() + 150, 77);
    assert.equal(old.trackingReady, true);
    const e4 = { e2: 'empty', e4: 'white' }; let k = dup.seq() + 1, t = dup.now() + 150;
    for (let i = 0; i < 8; i++) dup.raw(e4, ++k, (t += 150));
    assert.equal(dup.tracker.snapshot().lastMove.san, 'e4');
    assert.equal(dup.raw({}, ++k, (t += 150), 77).reason, 'no-legal-explanation', 'replayed pre-move image');
  });
  test(`R6 F3: a stretch longer than maxPictureGapMs (250 ms) without a picture revokes, hidden piece or not (transit ${inTransitTolerance})`, () => {
    for (const gap of [251, 700, 990]) {
      const r = rig(START, { inTransitTolerance });
      r.pic({ b1: 'unknown' });
      assert.match(r.pic({ b1: 'unknown' }, gap).reason, /^(picture-gap|observation-timeout)$/, `gap ${gap}`); // silence may fire first
      const clean = rig(START, { inTransitTolerance });
      assert.equal(clean.pic({}, gap).reason, 'picture-gap', `clean pictures, gap ${gap}`);
    }
    const edge = rig(START, { inTransitTolerance }); assert.equal(edge.pic({}, 250).trackingReady, true, '250 ms is allowed');
    // After a review, the first picture must also come within the gap.
    const t = new OccupancyTracker({ instanceId: uid() }); t.confirm({ session: SESSION, fen: START, reviewed, atMs: 1000 });
    const squares = squaresOf(new Chess());
    assert.equal(t.ingest({ identity: { ...SESSION, sequence: 1, frameSha256: hash(1) }, capturedAtMs: 1300, squares }).reason, 'picture-gap');
  });
  test(`R6 F4: castling is accepted only if no picture showed its squares in another arrangement (transit ${inTransitTolerance})`, () => {
    const CASTLE = 'r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1';
    const done = { h1: 'empty', g1: 'white', e1: 'empty', f1: 'white' }, long = { a1: 'empty', c1: 'white', e1: 'empty', d1: 'white' };
    for (const [first, final, truthMoves] of [[{ h1: 'empty', g1: 'white' }, done, [['h1', 'g1'], ['e1', 'f1']]], [{ a1: 'empty', c1: 'white' }, long, [['a1', 'c1'], ['e1', 'd1']]]]) {
      const r = rig(CASTLE, { inTransitTolerance });
      const truth = (() => { const c = new Chess(CASTLE); for (const [a, b] of truthMoves) { const p = c.get(a); c.remove(a); c.put(p, b); } return placementOf(c.fen()); })();
      const replies = neverTrustsWrong(r, [first, ...Array(MOVE).fill(final)], () => truth);
      assert.equal(replies.at(-1).reason, 'castling-not-seen-safely');
    }
    const hidden = rig(CASTLE, { inTransitTolerance });
    hidden.pic({ f1: 'unknown', g1: 'unknown' });
    assert.equal(neverTrustsWrong(hidden, Array(MOVE).fill(done), () => null).at(-1).reason, 'castling-not-seen-safely');
    // Pinned: a castling seen directly, or rook first then king, is still accepted.
    const direct = rig(CASTLE, { inTransitTolerance }); let last;
    for (let k = 0; k < MOVE; k++) last = direct.pic(done);
    assert.equal(last.lastMove.san, 'O-O');
    const rookFirst = rig(CASTLE, { inTransitTolerance }); rookFirst.pic({ h1: 'empty', f1: 'white' }); rookFirst.pic({ h1: 'empty', f1: 'white' });
    for (let k = 0; k < MOVE; k++) last = rookFirst.pic(done);
    assert.equal(last.lastMove.san, 'O-O');
  });
}
test('R6 F6: an own "__proto__" key (as JSON.parse makes it) is an extra field and is refused', () => {
  const r = rig(START);
  const good = { identity: { ...SESSION, sequence: r.seq() + 1, frameSha256: hash(5000) }, capturedAtMs: r.now() + 150, squares: squaresOf(new Chess()) };
  const viaJson = JSON.parse(JSON.stringify(good).replace(/^\{/, '{"__proto__":{"evil":1},'));
  const reply = guard(r.tracker.ingest(viaJson));
  assert.equal(reply.reason, 'invalid-observation'); assert.equal(reply.trackingReady, false);
});
test('R6 pins: refusals that are the price of the swap rule (hidden rook during a pawn move; a piece put back)', () => {
  const r = rig(START); r.pic({ e2: 'empty', e4: 'white', a1: 'unknown' });
  let last; for (let k = 0; k < MOVE; k++) last = r.pic({ e2: 'empty', e4: 'white' });
  assert.equal(last.reason, 'pieces-may-have-swapped', 'pawn and the hidden a1 rook could have traded squares');
  const back = rig(START); back.pic({ g1: 'empty', f3: 'white' });
  assert.equal(back.pic().reason, 'changed-and-returned', 'a piece set down and taken back costs a re-review');
});

// ---- round 7: fifth reviewer (each safety test fails against the round-6 module) ---------------------------------
// Round 7 rule (reviewer's R1, either colour): a square hidden or disturbed since the last agreement that the move does not
// change and that still holds a piece of EITHER side revokes, because that piece may have been traded inside one picture gap or
// replaced by a spare/captured piece. Attacks ported from the reviewer's c1-hole.mjs (families A, B, D, D2) plus the
// round-7 opponent probe.
const putOn = (fen, sq, piece) => { const c = new Chess(fen); c.remove(sq); c.put(piece, sq); return placementOf(c.fen()); };
const trustedWrong = (replies, truth) => replies.filter(x => x.trackingReady && placementOf(x.fen) !== truth).length;
for (const inTransitTolerance of [false, true]) {
  test(`R7 hole (a): two same-colour pieces trading squares while one square is hidden are never trusted (transit ${inTransitTolerance})`, () => {
    let runs = 0;
    for (const [X, Y] of [['b1', 'c1'], ['d1', 'c1'], ['a1', 'b1'], ['e2', 'b1'], ['e1', 'd1'], ['g1', 'h1']])
      for (const k of [1, 2, 3]) for (const g of [150, 249, 250, 251]) {
        const r = rig(START, { inTransitTolerance });
        const truth = swappedPlacement(START, X, Y);
        // X under a hand for k pictures; Y exchanged with X inside one gap of g ms; then the (swapped) board in plain view.
        const out = [r.pic({ [X]: 'unknown' })];
        for (let i = 1; i < k; i++) out.push(r.pic({ [X]: 'unknown' }, i === 1 ? g : 150));
        out.push(r.pic({}, k === 1 ? g : 150)); for (let i = 0; i < 10; i++) out.push(r.pic());
        assert.equal(trustedWrong(out, truth), 0, `hidden ${X} x${k}, ${Y} replaced in ${g} ms`);
        runs++;
      }
    assert.equal(runs, 72);
    // The same trade ending with a move of the same side (Nf3 or e4) while b1 is hidden.
    for (const [from, to] of [['g1', 'f3'], ['e2', 'e4']]) {
      const r = rig(START, { inTransitTolerance });
      const after = new Chess(); after.move({ from, to });
      const truth = swappedPlacement(fenOf(after), 'b1', 'c1');
      const out = [r.pic({ b1: 'unknown' }), r.pic({ b1: 'unknown' })];
      for (let i = 0; i < MOVE; i++) out.push(r.pic({ [from]: 'empty', [to]: 'white' }));
      assert.equal(trustedWrong(out, truth), 0, `${from}${to}`);
      assert.equal(out.at(-1).reason, 'pieces-may-have-swapped');
    }
  });
  test(`R7 hole (b): a hidden piece replaced by a spare piece of the same colour is never trusted, however long (transit ${inTransitTolerance})`, () => {
    const W = type => ({ type, color: 'w' });
    for (const [Y, spare] of [['c1', 'n'], ['d1', 'n'], ['a1', 'q'], ['b1', 'b'], ['e2', 'q']]) for (const pattern of ['uu', 'uucuucuuc']) {
      const r = rig(START, { inTransitTolerance });
      const truth = putOn(START, Y, W(spare)); const out = [];
      for (const ch of pattern) out.push(r.pic(ch === 'u' ? { [Y]: 'unknown' } : {}));
      for (let i = 0; i < 10; i++) out.push(r.pic());
      assert.equal(trustedWrong(out, truth), 0, `${Y} -> spare ${spare}, pattern ${pattern}`);
    }
    // Same, ending with a move of the SAME piece type (Bf1-c4 while the c1 bishop is replaced by a spare knight).
    const OPEN = 'r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3';
    const after = new Chess(OPEN); after.move('Bc4');
    const truth = putOn(fenOf(after), 'c1', W('n'));
    for (const hides of [[{ c1: 'unknown' }, { c1: 'unknown' }], [{ c1: 'unknown' }, { c1: 'unknown' }, { c1: 'unknown', f1: 'unknown' }]]) {
      const r = rig(OPEN, { inTransitTolerance });
      const out = hides.map(h => r.pic(h));
      for (let i = 0; i < MOVE; i++) out.push(r.pic({ f1: 'empty', c4: 'white' }));
      assert.equal(trustedWrong(out, truth), 0, `Bc4 with ${hides.length} hidden pictures`);
      assert.equal(out.at(-1).status, 'needs-confirmation');
    }
  });
}
for (const inTransitTolerance of [false, true]) {
  test(`R7 opponent hole: an opponent piece traded or replaced by a spare while the other side moves is never trusted (transit ${inTransitTolerance})`, () => {
    const after = new Chess(); after.move('e4'); const AFTER = fenOf(after);
    const e4 = { e2: 'empty', e4: 'white' };
    for (const [X, Y] of [['b8', 'c8'], ['g8', 'h8'], ['d8', 'c8']]) {
      // X under a hand, X and Y trade squares inside one gap, White plays e4.
      const r = rig(START, { inTransitTolerance });
      const out = [r.pic({ [X]: 'unknown' })];
      for (let i = 0; i < 9; i++) out.push(r.pic(e4));
      assert.equal(trustedWrong(out, swappedPlacement(AFTER, X, Y)), 0, `hidden ${X}, traded with ${Y}`);
      assert.equal(out.at(-1).reason, 'pieces-may-have-swapped');
    }
    for (const [Y, type] of [['c8', 'n'], ['a8', 'q'], ['b8', 'b']]) {
      // Y under a hand for two pictures and replaced by a spare black piece while White plays e4.
      const r = rig(START, { inTransitTolerance });
      const out = [r.pic({ [Y]: 'unknown' }), r.pic({ [Y]: 'unknown', ...e4 })];
      for (let i = 0; i < 8; i++) out.push(r.pic(e4));
      assert.equal(trustedWrong(out, putOn(AFTER, Y, { type, color: 'b' })), 0, `${Y} -> spare ${type}`);
      assert.equal(out.at(-1).reason, 'pieces-may-have-swapped');
    }
  });
}
test('R7 hole (c) pinned, NOT a safety property: the moving piece itself swapped or substituted is still trusted (occupancy cannot see it)', () => {
  // "Ng1-f3" where the bishop really lands on f3 and the knight on c1 (c1 exchanged inside one gap). If this ever stops
  // being trusted, update docs/OCCUPANCY_TRACKER.md ("What occupancy can never detect").
  const r = rig(START);
  const out = [r.pic({ g1: 'unknown' }), r.pic({ g1: 'unknown', f3: 'unknown' })];
  for (let i = 0; i < MOVE; i++) out.push(r.pic({ g1: 'empty', f3: 'white' }));
  assert.equal(out.at(-1).lastMove.san, 'Nf3');
});
test('R7 gap rule in tick and snapshot: a feed that stops revokes once the clock is more than maxPictureGapMs past the last picture', () => {
  const r = rig(START);
  assert.equal(r.tracker.snapshot(r.now() + 900).reason, 'picture-gap', 'round 6 still said ready 900 ms after the last picture');
  const t = rig(START);
  assert.equal(guard(t.tracker.tick(t.now() + 250)).trackingReady, true, '250 ms is allowed');
  assert.equal(guard(t.tracker.tick(t.now() + 251)).reason, 'picture-gap');
  // Also while a move is being agreed, and right after a review with no picture yet.
  const m = rig(START); m.pic({ e2: 'empty', e4: 'white' });
  assert.equal(guard(m.tracker.snapshot(m.now() + 300)).reason, 'picture-gap');
  const c = new OccupancyTracker({ instanceId: uid() }); c.confirm({ session: SESSION, fen: START, reviewed, atMs: 1000 });
  assert.equal(guard(c.tick(1251)).reason, 'picture-gap');
});
test('R7 timing: 6 pictures per second with +-20 ms capture jitter stays trusted through a normal move; 4 per second has no margin', () => {
  const r = rig(START);
  const random = rng(7); let seq = r.seq(); const t0 = r.now();
  const jitter = k => (k % 5 === 0 ? (k % 10 ? 20 : -20) : Math.round(random() * 40) - 20); // includes +20 / -20 extremes
  const at = k => t0 + Math.round(k * 1000 / 6) + jitter(k);
  const e4 = { e2: 'empty', e4: 'white' };
  const replies = [];
  for (let k = 1; k <= 30; k++) replies.push(r.raw(k <= 6 ? {} : e4, ++seq, at(k)));
  assert.ok(replies.every(x => x.event !== 'revoked'), JSON.stringify(replies.find(x => x.event === 'revoked')));
  assert.ok(replies.slice(0, 6).every(x => x.trackingReady), 'still board stays ready');
  assert.equal(replies.at(-1).trackingReady, true); assert.equal(replies.at(-1).lastMove.san, 'e4');
  assert.equal(r.tracker.snapshot(at(30) + 200).trackingReady, true, 'a snapshot between pictures stays ready');
  // At exactly 4 per second (250 ms) one late picture by 1 ms revokes: the documented reason to ask for 6 per second.
  const four = rig(START, {}); assert.equal(four.pic({}, 250).trackingReady, true);
  assert.equal(four.pic({}, 251).reason, 'picture-gap');
});

// ---- round 7b: independent review of round 7 (each safety test fails against the round-7 module or a named mutant) ----
const D5 = 'rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 2'; // 1.e4 d5, White to play exd5
for (const inTransitTolerance of [false, true]) {
  test(`R7b F1: a captured piece whose square was hidden before the capture is not trusted (review G7, transit ${inTransitTolerance})`, () => {
    // d5 under a hand while its pawn trades places with the d8 queen (or c8 bishop, a8 rook) inside one gap; then exd5 takes
    // the piece that is really on d5. Round 7 removed "the pawn" and trusted a board with the black pawn missing from Y.
    for (const Y of ['d8', 'c8', 'a8']) for (const hidden of [1, 2]) {
      const r = rig(D5, { inTransitTolerance });
      const out = []; for (let i = 0; i < hidden; i++) out.push(r.pic({ d5: 'unknown' }));
      for (let i = 0; i < 9; i++) out.push(r.pic({ e4: 'empty', d5: 'white' }));
      assert.ok(out.every(x => !x.trackingReady), `${Y} x${hidden}: no reply may be trusted (the true board has the black pawn on ${Y})`);
      assert.equal(out.at(-1).reason, 'pieces-may-have-swapped', `${Y} x${hidden}`);
    }
    // Same with the capturing pawn already lifted while d5 is hidden (two hands): the readings equal an honest hand covering
    // d5 during the capture, so that honest case revokes too (the documented price of this rule).
    const two = rig(D5, { inTransitTolerance });
    const out = [two.pic({ e4: 'empty', d5: 'unknown' })];
    for (let i = 0; i < 9; i++) out.push(two.pic({ e4: 'empty', d5: 'white' }));
    assert.ok(out.every(x => !x.trackingReady)); assert.equal(out.at(-1).status, 'needs-confirmation');
    // En passant: the captured pawn's square (d5) hidden before exd6 revokes as well.
    const EP = 'rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 3';
    const ep = rig(EP, { inTransitTolerance }); ep.pic({ d5: 'unknown' });
    let last; for (let i = 0; i < 9; i++) last = ep.pic({ e5: 'empty', d5: 'empty', d6: 'white' });
    assert.equal(last.reason, 'pieces-may-have-swapped');
  });
}
test('R7b F1 pins: a capture whose captured square was never hidden is still accepted (hand over the origin, or a clean capture)', () => {
  const clean = rig(D5); let last;
  for (let i = 0; i < 8; i++) last = clean.pic({ e4: 'empty', d5: 'white' });
  assert.equal(last.lastMove.san, 'exd5');
  const origin = rig(D5); origin.pic({ e4: 'unknown' });
  for (let i = 0; i < 8; i++) last = origin.pic({ e4: 'empty', d5: 'white' });
  assert.equal(last.lastMove.san, 'exd5');
});
for (const inTransitTolerance of [false, true]) {
  test(`R7b T1: the swap rule applies when the promotion question is asked (mutant M1g, transit ${inTransitTolerance})`, () => {
    // b1 (knight) under a hand while the pawn promotes; knight and c1 bishop may have traded inside one gap.
    const r = rig(PROMO6, { inTransitTolerance });
    const promo = { a7: 'empty', a8: 'white' };
    const out = [r.pic({ ...promo, b1: 'unknown' })];
    for (let k = 0; k < QUESTION + 1; k++) out.push(r.pic(promo));
    assert.ok(out.every(x => !x.pendingQuestion), 'no question is asked');
    assert.equal(r.tracker.snapshot().reason, 'pieces-may-have-swapped');
  });
  test(`R7b T1: the swap rule applies while verifying after a review and after a promotion answer (mutant M1h, transit ${inTransitTolerance})`, () => {
    for (const sq of ['a8', 'c1', 'e2']) {
      const { send } = setup(START, { inTransitTolerance });
      const out = [send({ overrides: unknownAt(sq) })]; for (let i = 0; i < 4; i++) out.push(send());
      assert.ok(out.every(x => !x.trackingReady), `review, ${sq} hidden`);
      assert.equal(out.at(-1).reason, 'pieces-may-have-swapped');
    }
    const r = rig(PROMO6, { inTransitTolerance }); const promo = { a7: 'empty', a8: 'white' };
    let q; for (let k = 0; k < QUESTION && !q; k++) q = r.pic(promo).pendingQuestion;
    assert.equal(r.tracker.answerPromotion({ session: SESSION, questionId: q.questionId, piece: 'q', atMs: r.now() }).accepted, true);
    const out = [r.pic({ ...promo, b1: 'unknown' })]; for (let i = 0; i < 4; i++) out.push(r.pic(promo));
    assert.ok(out.every(x => !x.trackingReady), 'after the answer, b1 hidden');
    assert.equal(out.at(-1).reason, 'pieces-may-have-swapped');
  });
}
test('R7b T1 (cost): the tick gap is measured from the last picture received, not the last usable one (mutant M2f)', () => {
  const r = rig(START);
  r.pic({ a5: 'unknown' }); // unusable, but the board was watched
  const reply = guard(r.tracker.tick(r.now() + 200)); // 350 ms after the last usable picture, 200 after the last picture
  assert.notEqual(reply.reason, 'picture-gap'); assert.equal(reply.status, 'confirming-change');
});
test('R7b D3: a repeated image that shows a changed board revokes while ready (round 7 answered "ready, ignored")', () => {
  const r = rig(START); const s = r.seq(), t = r.now();
  assert.equal(r.raw({}, s + 1, t + 150, 77).trackingReady, true);
  const replay = r.raw({ e2: 'empty', e4: 'white' }, s + 2, t + 300, 77);
  assert.equal(replay.reason, 'replayed-picture-changed'); assert.equal(replay.trackingReady, false);
});
