import test from 'node:test';
import assert from 'node:assert/strict';
import { Chess } from 'chess.js';
import { inferMove, occupancyFromFen, OCCUPANCY_SQUARES } from '../src/core/occupancy-move-inference.js';
import { analyseTwins, hypotheses, runReport, occString, wilson } from '../scripts/simulation/occupancy-misread-report.mjs';

const START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
const idx = sq => OCCUPANCY_SQUARES.indexOf(sq);
function after(fen, move) { const c = new Chess(fen); c.move(move); return occupancyFromFen(c.fen()); }

test('two misreads turn e2-e4 into an accepted e2-e3 today; the margin guard (G3m) abstains', () => {
  const occ = after(START, 'e4');
  occ[idx('e4')] = 'empty'; occ[idx('e3')] = 'white';
  const r = inferMove({ fen: START, occupancy: occ });
  assert.equal(r.status, 'move'); assert.equal(r.move.uci, 'e2e3'); // wrong move accepted
  // G3 as implemented in the report: abstain if any other move hypothesis is within 2 squares of the reading.
  const H = hypotheses(START), g = H.byKey.get(occ.map(v => v[0]).join(''));
  assert.ok(g && g.moves[0].san === 'e3');
  assert.ok(g.minMoves <= 2, 'G3m must abstain on the e3 reading'); assert.ok(g.minAll <= 2, 'G3 (all hypotheses) must abstain');
  // And the twin counter lists e2e3 (pawn single vs double push) as a confirmed two-misread twin of e2e4.
  const { twins } = analyseTwins(START, 'e2e4');
  const e3 = twins.find(t => t.wrong === 'e2e3');
  assert.ok(e3?.confirmed); assert.equal(e3.d, 2); assert.equal(e3.pattern, 'pawn-single-vs-double-push');
  assert.deepEqual(e3.squares.map(s => s.type).sort(), ['empty-read-as-piece', 'piece-read-as-empty']);
});

// Brute force: corrupt every pair of squares to every pair of wrong labels and ask inferMove.
// The set of wrong verdicts it accepts must equal the twin counter's confirmed distance-2 twins,
// and no single misread may ever produce a wrong verdict.
// Default cases keep npm test fast (about 1.5 s CPU); MISREAD_BRUTE_FORCE=1 adds two knights, castling, en passant,
// promotion and a middlegame position (about 15-50 s depending on machine load).
const FAST_CASES = [
  [START, 'e2e4'],
];
const SLOW_CASES = [
  ['4k3/8/8/8/8/2N3N1/8/R3K3 w Q - 0 1', 'g3e4'], // two knights can reach e4; rook lines
  ['r3k2r/pppqbppp/2np1n2/4p3/4P3/2NP1N2/PPPQBPPP/R3K2R w KQkq - 0 1', 'e1g1'], // castling
  ['rnbqkbnr/ppp1p1pp/8/3pPp2/6N1/8/PPPP1PPP/RNBQKB1R w KQkq f6 0 4', 'e5f6'], // en passant
  ['1r5k/P7/8/8/8/8/8/K7 w - - 0 1', 'a7a8q'], // promotion (true move itself is ambiguous)
  ['r1bq1rk1/pp2bppp/2n1pn2/3p4/2PP4/2N1PN2/PP3PPP/R2QKB1R w KQ - 0 8', 'f1d3'],
];
function bruteForceMatches(cases) {
  for (const [fen, truth] of cases) {
    const chess = new Chess(fen), m = chess.moves({ verbose: true }).find(x => x.from + x.to + (x.promotion ?? '') === truth);
    chess.move(m);
    const base = occString(chess).split('').map(c => ({ e: 'empty', w: 'white', b: 'black' })[c]);
    const wrongLabels = i => ['empty', 'white', 'black'].filter(v => v !== base[i]);
    const verdict = occ => { const r = inferMove({ fen, occupancy: occ }); return r.status === 'move' ? (r.move.uci === truth ? null : r.move.uci) : r.status === 'unchanged' ? 'unchanged' : null; };
    for (let i = 0; i < 64; i++) for (const a of wrongLabels(i)) { const o = base.slice(); o[i] = a; assert.equal(verdict(o), null, `single misread ${fen} ${i}`); }
    const brute = new Set();
    for (let i = 0; i < 64; i++) for (let j = i + 1; j < 64; j++) for (const a of wrongLabels(i)) for (const b of wrongLabels(j)) {
      const o = base.slice(); o[i] = a; o[j] = b;
      const v = verdict(o); if (v) brute.add(v);
    }
    const counted = new Set(analyseTwins(fen, truth).twins.filter(t => t.d === 2 && t.confirmed).map(t => t.wrong));
    assert.deepEqual([...brute].sort(), [...counted].sort(), fen);
  }
}
test('brute force over every pair of misreads matches the Hamming twin counter', () => bruteForceMatches(FAST_CASES));
test('brute force, slow positions (castling, en passant, promotion, middlegame)', { skip: process.env.MISREAD_BRUTE_FORCE === '1' ? false : 'opt-in: MISREAD_BRUTE_FORCE=1' }, () => bruteForceMatches(SLOW_CASES));

test('Wilson interval and rule of three', () => {
  assert.deepEqual(wilson(0, 1000), { k: 0, n: 1000, rate: 0, low: 0, high: 0.003, method: 'rule-of-three upper bound' });
  const w = wilson(5, 100); assert.ok(w.low < 0.05 && w.high > 0.05 && w.low > 0.02 && w.high < 0.12);
});

const EXPECTED_TINY = { plies: 40, any: 40, moveTwin: 34, d1: 0, d3: 0, mcTrials: 120, mismatches: 0,
  patterns: { 'unchanged-twin': 40, 'other-piece-type-same-destination': 31, 'same-piece-other-destination': 21, 'pawn-single-vs-double-push': 15, 'same-piece-shorter-or-longer-on-line': 10 } };
test('tiny seeded run is deterministic and matches hard-coded counts', () => {
  const a = runReport({ games: 2, plies: 20, seed: 7, trials: 3 }), b = runReport({ games: 2, plies: 20, seed: 7, trials: 3 });
  assert.equal(JSON.stringify(a), JSON.stringify(b));
  const A = a.A_twoMisreadTwins;
  assert.deepEqual({ plies: a.totalPlies, any: A.pliesWithAnyTwin.count, moveTwin: A.pliesWithWrongMoveTwin.count, d1: A.distanceOneHypothesesFound, d3: a.B_threeMisreadTwins.twins, mcTrials: a.C_randomErrorModels[3].montecarloTrials, mismatches: a.fastClassifierCrossCheck.mismatches, patterns: A.byPattern },
    EXPECTED_TINY);
});
