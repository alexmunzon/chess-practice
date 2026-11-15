import test from 'node:test';
import assert from 'node:assert/strict';
import { Chess } from 'chess.js';
import { inferMove, occupancyFromFen, OCCUPANCY_SQUARES } from '../src/core/occupancy-move-inference.js';

const START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
const idx = sq => OCCUPANCY_SQUARES.indexOf(sq);
// The true occupancy after playing `move` from `fen`, computed by chess.js itself.
function after(fen, move) { const c = new Chess(fen); c.move(move); return occupancyFromFen(c.fen()); }
const infer = (fen, move) => inferMove({ fen, occupancy: after(fen, move) });
function withSquares(occ, changes) { const o = occ.slice(); for (const [sq, v] of Object.entries(changes)) o[idx(sq)] = v; return o; }

test('square order is a1..h8', () => {
  assert.equal(OCCUPANCY_SQUARES[0], 'a1'); assert.equal(OCCUPANCY_SQUARES[7], 'h1'); assert.equal(OCCUPANCY_SQUARES[8], 'a2'); assert.equal(OCCUPANCY_SQUARES[63], 'h8');
  assert.equal(occupancyFromFen(START)[idx('e2')], 'white'); assert.equal(occupancyFromFen(START)[idx('e7')], 'black'); assert.equal(occupancyFromFen(START)[idx('e4')], 'empty');
});

test('quiet move', () => {
  const r = infer(START, 'e4');
  assert.equal(r.status, 'move'); assert.equal(r.move.uci, 'e2e4'); assert.equal(r.move.san, 'e4');
  const expected = new Chess(START); expected.move('e4');
  assert.equal(r.fenAfter, expected.fen({ forceEnpassantSquare: true }));
});

test('unchanged board', () => assert.deepEqual(inferMove({ fen: START, occupancy: occupancyFromFen(START) }), { status: 'unchanged' }));

test('capture', () => {
  const fen = 'rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 2';
  const r = infer(fen, 'exd5'); assert.equal(r.status, 'move'); assert.equal(r.move.uci, 'e4d5');
});

test('castling both sides, both colours', () => {
  const fen = 'r3k2r/pppqbppp/2np1n2/4p3/4P3/2NP1N2/PPPQBPPP/R3K2R w KQkq - 0 1';
  for (const [f, san, uci] of [[fen, 'O-O', 'e1g1'], [fen, 'O-O-O', 'e1c1'], [fen.replace(' w ', ' b '), 'O-O', 'e8g8'], [fen.replace(' w ', ' b '), 'O-O-O', 'e8c8']]) {
    const r = infer(f, san); assert.equal(r.status, 'move', san); assert.equal(r.move.uci, uci); assert.equal(r.move.san, san);
  }
});

test('en passant (captured pawn square empties)', () => {
  const fen = 'rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3';
  const r = infer(fen, 'exf6'); assert.equal(r.status, 'move'); assert.equal(r.move.uci, 'e5f6');
  // Same destination, but leaving f5 occupied, is not a legal explanation.
  const occ = withSquares(after(fen, 'exf6'), { f5: 'black' });
  assert.equal(inferMove({ fen, occupancy: occ }).status, 'no-legal-explanation');
});

test('promotion: queen vs under-promotion is ambiguous, with and without capture', () => {
  const fen = '1r5k/P7/8/8/8/8/8/K7 w - - 0 1';
  for (const [move, from, to] of [['a8=Q', 'a7', 'a8'], ['axb8=N', 'a7', 'b8']]) {
    const r = infer(fen, move);
    assert.equal(r.status, 'ambiguous'); assert.equal(r.cause, 'promotion-piece-choice');
    assert.deepEqual(r.candidates.map(c => c.promotion).sort(), ['b', 'n', 'q', 'r']);
    assert.ok(r.candidates.every(c => c.from === from && c.to === to));
  }
});

test('capture vs non-capture by different pieces onto the same square: occupancy differs', () => {
  // f6 is empty: exf6 e.p. captures (f5 empties), Ng4-f6 does not. Both land on f6.
  const fen = 'rnbqkbnr/ppp1p1pp/8/3pPp2/6N1/8/PPPP1PPP/RNBQKB1R w KQkq f6 0 4';
  const ep = infer(fen, 'exf6'), knight = infer(fen, 'Nf6+');
  assert.equal(ep.move.uci, 'e5f6'); assert.equal(knight.move.uci, 'g4f6');
  assert.notDeepEqual(after(fen, 'exf6'), after(fen, 'Nf6+'));
});

test('two same-colour pieces able to reach one square: occupancy distinguishes origin', () => {
  const fenN = '4k3/8/8/8/8/2N3N1/8/4K3 w - - 0 1'; // Nc3-e4 and Ng3-e4 both legal
  const a = infer(fenN, { from: 'c3', to: 'e4' }), b = infer(fenN, { from: 'g3', to: 'e4' });
  assert.equal(a.status, 'move'); assert.equal(a.move.uci, 'c3e4'); assert.equal(a.move.san, 'Nce4');
  assert.equal(b.status, 'move'); assert.equal(b.move.uci, 'g3e4'); assert.equal(b.move.san, 'Nge4');
  const fenR = '4k3/8/8/8/8/8/8/R3K2R w - - 0 1'; // Ra1-f1? blocked; Rh1-f1 and Rh1-g1 vs Ra1-d1
  assert.equal(infer(fenR, 'Rd1').move.uci, 'a1d1'); assert.equal(infer(fenR, 'Rf1').move.uci, 'h1f1');
});

test('check and checkmate moves', () => {
  const mateIn1 = 'rnbqkbnr/ppppp2p/5p2/6p1/4P3/8/PPPP1PPP/RNBQKBNR w KQkq g6 0 3';
  const r = infer(mateIn1, 'Qh5#'); assert.equal(r.status, 'move'); assert.equal(r.move.san, 'Qh5#');
  const check = infer('4k3/8/8/8/8/8/8/R3K3 w - - 0 1', 'Ra8+'); assert.equal(check.move.san, 'Ra8+');
  // After checkmate nothing is legal: any change is unexplained, no change is "unchanged".
  const mated = r.fenAfter;
  assert.equal(inferMove({ fen: mated, occupancy: occupancyFromFen(mated) }).status, 'unchanged');
  assert.equal(inferMove({ fen: mated, occupancy: withSquares(occupancyFromFen(mated), { a7: 'empty', a6: 'black' }) }).status, 'no-legal-explanation');
});

test('two plies skipped and one flipped square are unexplained', () => {
  const c = new Chess(START); c.move('e4'); c.move('e5');
  assert.equal(inferMove({ fen: START, occupancy: occupancyFromFen(c.fen()) }).status, 'no-legal-explanation');
  for (const [sq, v] of [['a3', 'white'], ['e7', 'empty'], ['e8', 'white']]) {
    assert.equal(inferMove({ fen: START, occupancy: withSquares(after(START, 'e4'), { [sq]: v }) }).status, 'no-legal-explanation', sq);
  }
});

test('unknown squares: relevant -> uncertain; irrelevant -> uncertain by default, decides only with the explicit assumption', () => {
  const occ = after(START, 'e4');
  // e4 is where the move landed; e3 is an alternative destination. Both relevant.
  for (const sq of ['e4', 'e3']) {
    const o = withSquares(occ, { [sq]: 'unknown' });
    assert.equal(inferMove({ fen: START, occupancy: o }).status, 'uncertain');
    const relaxed = inferMove({ fen: START, occupancy: o }, { assumeUntouchedUnknowns: true });
    assert.equal(relaxed.status, 'uncertain'); assert.deepEqual(relaxed.relevantUnknownSquares, [sq]);
  }
  // h8 (black rook) cannot be changed by any White legal move from the start position.
  const o = withSquares(occ, { h8: 'unknown' });
  assert.deepEqual(inferMove({ fen: START, occupancy: o }), { status: 'uncertain', unknownSquares: ['h8'] });
  const relaxed = inferMove({ fen: START, occupancy: o }, { assumeUntouchedUnknowns: true });
  assert.equal(relaxed.status, 'move'); assert.equal(relaxed.move.uci, 'e2e4'); assert.deepEqual(relaxed.assumedUnchangedSquares, ['h8']);
  // If the known squares already rule out every hypothesis, no reading of the unknown could help.
  assert.equal(inferMove({ fen: START, occupancy: withSquares(occ, { h8: 'unknown', a5: 'black' }) }).status, 'no-legal-explanation');
});

test('malformed input is rejected', () => {
  const good = occupancyFromFen(START);
  for (const bad of [null, [], 'x', { fen: START }, { fen: START, occupancy: good.slice(1) }, { fen: START, occupancy: [...good.slice(1), 'W'] },
    { fen: 42, occupancy: good }, { fen: 'not a fen', occupancy: good }, { fen: '8/8/8/8/8/8/8/8 w - - 0 1', occupancy: good }]) {
    assert.throws(() => inferMove(bad));
  }
});

// Deterministic PRNG (mulberry32).
function rng(seed) { let a = seed >>> 0; return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }

// Random legal move: random own piece that has moves, then a random move of it (deterministic).
// Per-square generation keeps the test fast; chess.js full verbose generation is ~1 ms per call.
const boardOcc = chess => OCCUPANCY_SQUARES.map(sq => { const p = chess.get(sq); return p ? (p.color === 'w' ? 'white' : 'black') : 'empty'; });
function randomMove(chess, random) {
  const squares = OCCUPANCY_SQUARES.filter(sq => chess.get(sq)?.color === chess.turn());
  while (squares.length) {
    const k = Math.floor(random() * squares.length), moves = chess.moves({ square: squares[k], verbose: true });
    if (moves.length) return moves[Math.floor(random() * moves.length)];
    squares.splice(k, 1);
  }
  return null;
}

test('property: 300 seeded random games x 80 plies never yield a wrong unique move', () => {
  const random = rng(20261115), counts = { plies: 0, move: 0, ambiguous: 0, bruteForceChecks: 0 };
  for (let g = 0; g < 300; g++) {
    const chess = new Chess();
    for (let ply = 0; ply < 80; ply++) {
      const truth = randomMove(chess, random);
      if (!truth) break;
      const fen = chess.fen({ forceEnpassantSquare: true });
      chess.move(truth);
      const uci = truth.from + truth.to + (truth.promotion ?? '');
      const occupancy = boardOcc(chess);
      const r = inferMove({ fen, occupancy });
      counts.plies++;
      if (r.status === 'move') { assert.equal(r.move.uci, uci, `wrong unique move at ${fen}`); assert.equal(r.fenAfter.split(' ')[0], chess.fen().split(' ')[0]); counts.move++; }
      else if (r.status === 'ambiguous') { assert.ok(r.candidates.some(c => c.uci === uci), `truth missing at ${fen}`); counts.ambiguous++; }
      else assert.fail(`unexpected ${r.status} at ${fen} for ${uci}`);
      // Every 100th ply: brute force (play every legal move with chess.js) must give the same match set.
      if (counts.plies % 100 === 0) {
        const before = new Chess(fen), key = occupancy.join();
        const brute = before.moves({ verbose: true }).filter(m => { before.move(m); const hit = boardOcc(before).join() === key; before.undo(); return hit; }).map(m => m.from + m.to + (m.promotion ?? '')).sort();
        assert.deepEqual(r.status === 'move' ? [r.move.uci] : r.candidates.map(c => c.uci).sort(), brute, `pruned vs brute force at ${fen}`);
        counts.bruteForceChecks++;
      }
    }
  }
  console.log('# property outcomes', JSON.stringify(counts));
  assert.ok(counts.plies >= 300 * 20);
});
