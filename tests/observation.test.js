import test from 'node:test';
import assert from 'node:assert/strict';
import { Chess } from 'chess.js';
import { ObservationTracker, SQUARES, validateObservation } from '../src/core/observation.js';

const reviewed = { pieces: true, turn: true, castling: true, enPassant: true, counters: true };
// These are SYNTHETIC OBSERVATIONS generated from chess.js, not image recognition.
function syntheticObservation(chess, sequence, capturedAt, epoch = 1, sourceId = 'synthetic') {
  return { sourceId, epoch, sequence, capturedAt, squares: Object.fromEntries(SQUARES.map(square => {
    const p = chess.get(square);
    return [square, { label: p ? (p.color === 'w' ? p.type.toUpperCase() : p.type) : 'empty', confidence: 1 }];
  })) };
}
function setup(fen = new Chess().fen(), options = {}) {
  let time = 0, sequence = 0;
  const tracker = new ObservationTracker({ clock: () => time, ...options });
  tracker.connect('synthetic'); tracker.confirm({ fen, reviewed });
  const chess = new Chess(fen);
  const frame = (delta = 60) => { time += delta; return syntheticObservation(chess, sequence++, time, tracker.snapshot().epoch); };
  const send = () => tracker.ingest(frame());
  return { tracker, chess, frame, send, advance: n => { time += n; } };
}
test('synthetic observations: starting FEN needs explicit complete human review and two stable frames', () => {
  const { tracker, send } = setup();
  assert.equal(tracker.snapshot().guidanceAllowed, false);
  assert.equal(send().guidanceAllowed, false);
  assert.equal(send().guidanceAllowed, true);
  assert.throws(() => tracker.confirm({ fen: new Chess().fen(), reviewed: { ...reviewed, castling: false } }));
  assert.equal(tracker.snapshot().guidanceAllowed, false);
  assert.throws(() => tracker.confirm({ fen: new Chess().fen().split(' ').slice(0, 4).join(' '), reviewed }));
});
test('synthetic observations: one legal move updates turn, clocks and en passant only after stability', () => {
  const { chess, tracker, send } = setup();
  send(); send(); chess.move('e4');
  assert.equal(send().guidanceAllowed, false);
  assert.equal(tracker.snapshot().fen, new Chess().fen());
  const result = send();
  assert.equal(result.fen, chess.fen({ forceEnpassantSquare: true }));
  assert.equal(result.lastMove.san, 'e4');
  assert.equal(result.historyComplete, false);
});
for (const [name, fen, move] of [
  ['white castling', 'r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1', 'O-O'],
  ['black queenside castling', 'r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1', 'O-O-O'],
  ['en passant', '4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2', 'exd6'],
  ...['q', 'r', 'b', 'n'].map(promotion => ['promotion ' + promotion, '7k/P7/8/8/8/8/8/7K w - - 0 1', { from: 'a7', to: 'a8', promotion }]),
]) test(`synthetic observations: ${name}`, () => {
  const { chess, send } = setup(fen); chess.move(move);
  send(); const result = send();
  assert.equal(result.guidanceAllowed, true);
  assert.equal(result.fen, chess.fen({ forceEnpassantSquare: true }));
});
test('synthetic observations: repeated and reordered callbacks never establish stability or replace current state', () => {
  const { tracker, frame, send } = setup();
  const first = frame(); tracker.ingest(first);
  assert.equal(tracker.ingest(first).guidanceAllowed, false);
  assert.equal(send().guidanceAllowed, true);
  const current = tracker.snapshot();
  assert.equal(tracker.ingest(first).revision, current.revision);
  const next = frame(); next.capturedAt = first.capturedAt;
  assert.equal(tracker.ingest(next).ignored, 'repeated-or-reordered-frame');
});
test('synthetic observations: timestamp span is required even with enough distinct frames', () => {
  const { tracker, frame } = setup(); tracker.ingest(frame(1));
  assert.equal(tracker.ingest(frame(1)).guidanceAllowed, false);
  assert.equal(tracker.ingest(frame(60)).guidanceAllowed, true);
});
test('synthetic observations: occlusion and low confidence require reconfirmation', () => {
  for (const value of [{ label: 'unknown', confidence: 1 }, { label: 'P', confidence: 0.94 }]) {
    const { tracker, frame, send } = setup(); send(); send();
    const input = frame(); input.squares.e2 = value;
    assert.equal(tracker.ingest(input).reason, 'uncertain-squares');
    assert.equal(send().guidanceAllowed, false);
  }
});
test('synthetic observations: multiple skipped plies and illegal layouts abstain', () => {
  const { chess, send } = setup(); chess.move('e4'); chess.move('e5');
  assert.equal(send().reason, 'not-zero-or-one-legal-move');
  assert.equal(send().guidanceAllowed, false);
});
test('synthetic observations: visible king and rook never manufacture castling rights', () => {
  const { chess, tracker, send, frame } = setup('r3k2r/8/8/8/8/8/8/R3K2R w - - 0 1');
  send(); assert.match(send().fen, / w - - /);
  chess.remove('e1'); chess.remove('h1'); chess.put({ type: 'k', color: 'w' }, 'g1'); chess.put({ type: 'r', color: 'w' }, 'f1');
  assert.equal(tracker.ingest(frame()).reason, 'not-zero-or-one-legal-move');
});
test('synthetic observations: source swap, edit, disconnect and reconnect revoke guidance', () => {
  for (const action of ['edit', 'disconnect', 'connect', 'swap']) {
    const { tracker, frame, send } = setup(); send(); send(); const old = frame();
    if (action === 'swap') { old.sourceId = 'other'; tracker.ingest(old); }
    else if (action === 'connect') tracker.connect('synthetic');
    else tracker[action]();
    assert.equal(tracker.snapshot().guidanceAllowed, false);
    assert.equal(send().guidanceAllowed, false);
  }
});
test('synthetic observations: old epoch cannot replace freshly confirmed reconnect state', () => {
  const { tracker, frame, send, chess } = setup(); const old = frame();
  tracker.disconnect(); tracker.connect('synthetic'); tracker.confirm({ fen: chess.fen(), reviewed });
  send(); send(); const latest = tracker.snapshot();
  assert.equal(tracker.ingest(old).ignored, 'stale-session');
  assert.deepEqual(tracker.snapshot(), latest);
});
test('synthetic observations: timeout cannot be revived by a fresh frame without review', () => {
  const { tracker, advance, send } = setup(); send(); send(); advance(1001);
  assert.equal(tracker.tick().reason, 'observation-timeout');
  assert.equal(send().guidanceAllowed, false);
});
test('synthetic observations: stale, future and pre-confirmation frames do not establish guidance', () => {
  for (const timestamp of [-1, 10000]) {
    const { tracker, frame } = setup(); const input = frame(); input.capturedAt = timestamp;
    assert.equal(tracker.ingest(input).guidanceAllowed, false);
  }
  const { tracker, frame, advance, chess } = setup(); const old = frame(); advance(30);
  tracker.confirm({ fen: chess.fen(), reviewed });
  assert.equal(tracker.ingest(old).ignored, 'before-confirmation');
  const freshSetup = setup(); const stale = freshSetup.frame(); freshSetup.advance(1001);
  assert.equal(freshSetup.tracker.ingest(stale).reason, 'stale-or-future-frame');
});
test('synthetic observations: malformed boundary inputs fail closed with bounded shape', () => {
  const { tracker, frame, send } = setup(); send(); send();
  for (const alter of [f => delete f.squares.a1, f => f.squares.a1.confidence = NaN, f => f.squares.a1.label = 'X', f => f.sequence = 1.5, f => f.sourceId = 'x'.repeat(129), f => f.extra = true, f => f.squares.a1.extra = 'x'.repeat(20000)]) {
    const input = frame(); alter(input);
    assert.throws(() => validateObservation(input));
    assert.equal(tracker.ingest(input).guidanceAllowed, false);
  }
});
test('synthetic observations: configuration bounds and backward clocks reject', () => {
  for (const options of [{ stableFrames: 1 }, { stableFrames: 31 }, { minConfidence: 0 }, { timeoutMs: 50 }]) assert.throws(() => new ObservationTracker(options));
  let time = 10; const tracker = new ObservationTracker({ clock: () => time }); tracker.connect('synthetic'); time = 9;
  assert.throws(() => tracker.tick(), /monotonic/);
});

test('synthetic observations: continued stable board remains ready, but changed board clears readiness immediately', () => {
  const { send, chess } = setup(); send(); send();
  assert.equal(send().guidanceAllowed, true);
  chess.move('e4'); assert.equal(send().guidanceAllowed, false);
});
test('synthetic observations: alternating legal successors reset the stability run', () => {
  const { tracker, frame, chess } = setup(); chess.move('e4'); tracker.ingest(frame());
  chess.undo(); chess.move('d4'); assert.equal(tracker.ingest(frame()).guidanceAllowed, false);
  chess.undo(); chess.move('e4'); assert.equal(tracker.ingest(frame()).guidanceAllowed, false);
});
test('synthetic replay: deterministic JSON events, timeout and document bounds', async () => {
  const { replayObservations, syntheticDemo } = await import('../scripts/replay-observations.js');
  const output = replayObservations(syntheticDemo());
  assert.equal(output.kind, 'synthetic-observations');
  assert.equal(output.classifierImplemented, false);
  assert.equal(output.states[3].guidanceAllowed, true);
  assert.equal(output.states[5].lastMove.san, 'e4');
  assert.equal(output.states[6].reason, 'observation-timeout');
  for (const document of [null, {}, { ...syntheticDemo(), events: Array(2001).fill({}) }, { ...syntheticDemo(), events: [{ type: 'tick', at: -1 }] }, { ...syntheticDemo(), events: [{ type: 'unknown', at: 0 }] }]) assert.throws(() => replayObservations(document));
});

 test('synthetic observations: claimable fifty-move draw still permits a legal successor', () => {
  const { chess, send } = setup('7k/8/8/8/8/8/8/KR6 w - - 100 51');
  chess.move('Rb2'); send();
  const result = send();
  assert.equal(result.guidanceAllowed, true);
  assert.equal(result.lastMove.san, 'Rb2');
  assert.equal(result.fen, chess.fen({ forceEnpassantSquare: true }));
});

test('synthetic observations: identical ready frames preserve revision and renew freshness', () => {
  const { tracker, send, advance } = setup(); send();
  const ready = send();
  advance(800); const refreshed = send();
  assert.equal(refreshed.revision, ready.revision);
  assert.equal(refreshed.guidanceAllowed, true);
  advance(800);
  assert.equal(tracker.snapshot().guidanceAllowed, true);
});
test('synthetic observations: changed or uncertain ready frames immediately invalidate prior analysis revision', () => {
  const { tracker, chess, send, frame } = setup(); send();
  const ready = send(); chess.move('e4');
  const changed = send();
  assert.ok(changed.revision > ready.revision);
  assert.equal(changed.guidanceAllowed, false);
  const stable = send(); assert.equal(stable.guidanceAllowed, true);
  assert.equal(send().revision, stable.revision);
  const uncertain = frame(); uncertain.squares.a1.confidence = 0.1;
  const stopped = tracker.ingest(uncertain);
  assert.ok(stopped.revision > stable.revision);
  assert.equal(stopped.guidanceAllowed, false);
});
