#!/usr/bin/env node
// Seeded, deterministic measurement of how MISREAD squares can make occupancy inference accept a
// WRONG move, and of candidate guards against it. Pure logic, no images, synthetic error models.
// Usage: node scripts/simulation/occupancy-misread-report.mjs [--games 500] [--plies 80] [--seed 20261115]
//          [--trials 20] [--out file.json]
// --trials = Monte Carlo trials per ply per error model (each trial draws 3 independent frames).
// Guards are wrappers implemented here as PROPOSALS; src/core/occupancy-move-inference.js is unchanged.
import { writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { Chess } from 'chess.js';
import { inferMove, OCCUPANCY_SQUARES } from '../../src/core/occupancy-move-inference.js';

export const DEFAULT_OUT = '/Users/alexmunzon/chess-builds/pipeline-2026-11-15/misread/report.json';
export const P_VALUES = [0.001, 0.003, 0.01, 0.03];

// Same PRNG (mulberry32) and move choice as occupancy-ambiguity-report.mjs.
export function rng(s) { let a = s >>> 0; return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
function randomMove(chess, random) {
  const squares = OCCUPANCY_SQUARES.filter(sq => chess.get(sq)?.color === chess.turn());
  while (squares.length) {
    const k = Math.floor(random() * squares.length), moves = chess.moves({ square: squares[k], verbose: true });
    if (moves.length) return moves[Math.floor(random() * moves.length)];
    squares.splice(k, 1);
  }
  return null;
}

// Occupancy as a 64-char string, a1..h8: e(mpty) w(hite) b(lack) u(nknown).
const CODE = { empty: 'e', white: 'w', black: 'b', unknown: 'u' }, NAME = { e: 'empty', w: 'white', b: 'black', u: 'unknown' };
const idx = sq => (Number(sq[1]) - 1) * 8 + 'abcdefgh'.indexOf(sq[0]);
const toArray = s => Array.from(s, c => NAME[c]);
export const occString = chess => OCCUPANCY_SQUARES.map(sq => { const p = chess.get(sq); return p ? p.color : 'e'; }).join('');
export const uciOf = m => m.from + m.to + (m.promotion ?? '');
function after(base, m) {
  const o = base.split(''), c = m.color;
  o[idx(m.from)] = 'e'; o[idx(m.to)] = c;
  if (m.flags.includes('e')) o[idx(m.to[0] + m.from[1])] = 'e';
  if (m.flags.includes('k')) { o[idx('h' + m.from[1])] = 'e'; o[idx('f' + m.from[1])] = c; }
  if (m.flags.includes('q')) { o[idx('a' + m.from[1])] = 'e'; o[idx('d' + m.from[1])] = c; }
  return o.join('');
}
export function hamming(a, b) { let d = 0; for (let i = 0; i < 64; i++) if (a[i] !== b[i]) d++; return d; }

/** Hypotheses inferMove considers ("unchanged" + every legal move), grouped by resulting occupancy. */
export function hypotheses(fen) {
  const chess = new Chess(fen), base = occString(chess), byKey = new Map();
  byKey.set(base, { occ: base, unchanged: true, moves: [] });
  for (const m of chess.moves({ verbose: true })) {
    const occ = after(base, m);
    if (!byKey.has(occ)) byKey.set(occ, { occ, unchanged: false, moves: [] });
    byKey.get(occ).moves.push(m);
  }
  const groups = [...byKey.values()];
  // Margins: smallest distance to any OTHER group, with and without the "unchanged" group.
  for (const g of groups) { g.minAll = Infinity; g.minMoves = Infinity; }
  for (let i = 0; i < groups.length; i++) for (let j = i + 1; j < groups.length; j++) {
    const d = hamming(groups[i].occ, groups[j].occ), a = groups[i], b = groups[j];
    a.minAll = Math.min(a.minAll, d); b.minAll = Math.min(b.minAll, d);
    if (!b.unchanged) a.minMoves = Math.min(a.minMoves, d);
    if (!a.unchanged) b.minMoves = Math.min(b.minMoves, d);
  }
  return { base, groups, byKey };
}

// ---- Twin patterns -------------------------------------------------------------------------------
const sign = x => Math.sign(x);
function sameRay(from, a, b) {
  const f = [from.charCodeAt(0), Number(from[1])], va = [a.charCodeAt(0) - f[0], Number(a[1]) - f[1]], vb = [b.charCodeAt(0) - f[0], Number(b[1]) - f[1]];
  const line = v => v[0] === 0 || v[1] === 0 || Math.abs(v[0]) === Math.abs(v[1]);
  return line(va) && line(vb) && sign(va[0]) === sign(vb[0]) && sign(va[1]) === sign(vb[1]);
}
const isCapture = m => m.flags.includes('c') || m.flags.includes('e');
/** Pattern of a wrong hypothesis `w` (a group) relative to the true move `t`. */
export function twinPattern(t, w) {
  if (w.unchanged) return 'unchanged-twin';
  const m = w.moves[0];
  if (/[kq]/.test(t.flags) || /[kq]/.test(m.flags)) return 'castling-related';
  if (t.flags.includes('e') || m.flags.includes('e')) return 'en-passant-related';
  if (t.from === m.from && t.to !== m.to) {
    if (t.piece === 'p' && !isCapture(t) && !isCapture(m)) return 'pawn-single-vs-double-push';
    if (t.piece !== 'n' && sameRay(t.from, t.to, m.to)) return 'same-piece-shorter-or-longer-on-line';
    return 'same-piece-other-destination';
  }
  if (t.to === m.to && t.from !== m.from) return t.piece === m.piece ? 'same-type-other-origin-same-destination' : 'other-piece-type-same-destination';
  return 'other';
}
export function misreadType(trueCode, readCode) {
  if (trueCode === 'e') return 'empty-read-as-piece';
  if (readCode === 'e') return 'piece-read-as-empty';
  return 'colour-swap';
}

/**
 * Exhaustive twin analysis for one ply: every hypothesis group at Hamming distance 2 or 3 from the
 * true result, each CONFIRMED by feeding its occupancy (= the true reading with exactly d specific
 * squares misread) to inferMove and checking it returns that wrong hypothesis.
 */
export function analyseTwins(fen, truthUci, H = hypotheses(fen)) {
  const T = H.groups.find(g => g.moves.some(m => uciOf(m) === truthUci));
  if (!T) throw new Error(`truth ${truthUci} is not legal in ${fen}`);
  const t = T.moves.find(m => uciOf(m) === truthUci), twins = [];
  let distanceOne = 0;
  for (const g of H.groups) {
    if (g === T) continue;
    const d = hamming(g.occ, T.occ);
    if (d === 1) distanceOne++;
    if (d !== 2 && d !== 3) continue;
    const r = inferMove({ fen, occupancy: toArray(g.occ) });
    const wrongUci = g.unchanged ? null : uciOf(g.moves[0]);
    const confirmed = g.unchanged ? r.status === 'unchanged' : (r.status === 'move' && r.move.uci === wrongUci && wrongUci !== truthUci);
    const squares = [];
    for (let i = 0; i < 64; i++) if (g.occ[i] !== T.occ[i]) squares.push({ square: OCCUPANCY_SQUARES[i], truth: NAME[T.occ[i]], readAs: NAME[g.occ[i]], type: misreadType(T.occ[i], g.occ[i]) });
    twins.push({ d, wrong: wrongUci ?? 'unchanged', status: r.status, confirmed, pattern: twinPattern(t, g), captureMismatch: !g.unchanged && isCapture(t) !== isCapture(g.moves[0]), squares });
  }
  return { truth: t, truthGroup: T, twins, distanceOne };
}

// ---- Fast reading classifier (exact replica of inferMove's decision; cross-checked against it) ---
function classify(frame, H, truthUci) {
  if (!frame.includes('u')) {
    const g = H.byKey.get(frame);
    if (!g) return { status: 'no-legal-explanation' };
    if (g.unchanged) return { status: 'unchanged', group: g };
    if (g.moves.length > 1) return { status: 'ambiguous', group: g };
    const uci = uciOf(g.moves[0]);
    return { status: uci === truthUci ? 'correct' : 'wrong', uci, group: g };
  }
  for (const g of H.groups) {
    let ok = true;
    for (let i = 0; i < 64; i++) if (frame[i] !== 'u' && frame[i] !== g.occ[i]) { ok = false; break; }
    if (ok) return { status: 'uncertain' };
  }
  return { status: 'no-legal-explanation' };
}
function realStatus(fen, frame) {
  const r = inferMove({ fen, occupancy: toArray(frame) });
  return r.status === 'move' ? { status: 'move', uci: r.move.uci } : { status: r.status };
}
function agrees(fast, real, truthUci) {
  if (fast.status === 'correct' || fast.status === 'wrong') return real.status === 'move' && real.uci === fast.uci && (fast.status === 'correct') === (real.uci === truthUci);
  return real.status === fast.status;
}

// Independent per-square noise: wrong label with prob p (each wrong label p/2), unknown with prob q.
function drawFrame(truth, p, q, random) {
  const r = p + q; let i = -1, out = null;
  const logKeep = Math.log(1 - r);
  for (;;) {
    i += 1 + Math.floor(Math.log(1 - random()) / logKeep);
    if (i >= 64) return out ? out.join('') : truth;
    out ??= truth.split('');
    if (q > 0 && random() < q / r) out[i] = 'u';
    else { const others = 'ewb'.replace(truth[i], ''); out[i] = others[random() < 0.5 ? 0 : 1]; }
  }
}

// ---- Statistics ----------------------------------------------------------------------------------
export function wilson(k, n) {
  if (n === 0) return null;
  if (k === 0) return { k, n, rate: 0, low: 0, high: 3 / n, method: 'rule-of-three upper bound' };
  const z = 1.959964, ph = k / n, den = 1 + z * z / n, c = (ph + z * z / (2 * n)) / den, h = z * Math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / den;
  return { k, n, rate: ph, low: Math.max(0, c - h), high: Math.min(1, c + h), method: 'Wilson 95%' };
}
const median = a => { const s = Float64Array.from(a).sort(), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
const sig = x => (x === 0 ? 0 : Number(x.toPrecision(4)));
const roundObj = o => JSON.parse(JSON.stringify(o, (k, v) => (typeof v === 'number' && !Number.isInteger(v) ? sig(v) : v)));

const STATUS_KEYS = ['correct', 'wrong', 'unchanged', 'no-legal-explanation', 'uncertain', 'ambiguous'];
const FRAMES = { 'G0-none': 1, 'G1-two-frame': 2, 'G2-three-of-three': 3, 'G3-margin2-all-hypotheses': 1, 'G3m-margin2-move-hypotheses': 1, 'G4-margin-else-two-frame': 1 };
const GUARDS = ['G0-none', 'G1-two-frame', 'G2-three-of-three', 'G3-margin2-all-hypotheses', 'G3m-margin2-move-hypotheses', 'G4-margin-else-two-frame'];

export function runReport({ games = 500, plies = 80, seed = 20261115, trials = 20 } = {}) {
  if (![games, plies, seed, trials].every(Number.isSafeInteger) || games < 1 || plies < 1 || trials < 0) throw new Error('games, plies, trials and seed must be integers (games, plies >= 1).');
  const random = rng(seed), noise = rng((seed ^ 0x9E3779B9) >>> 0);
  const models = [];
  for (const kind of ['label-only', 'label-plus-unknown']) for (const p of P_VALUES) models.push({ kind, p, q: kind === 'label-only' ? 0 : 10 * p });
  const mc = models.map(() => ({ trials: 0, single: Object.fromEntries(STATUS_KEYS.map(k => [k, 0])), guards: Object.fromEntries(GUARDS.map(g => [g, { correct: 0, wrong: 0 }])) }));
  const exact = models.map(() => ({ single: { correct: 0, wrong: 0, unchanged: 0, ambiguous: 0 }, guards: Object.fromEntries(GUARDS.map(g => [g, { correct: 0, wrong: 0, prompt: 0, condWrong: 0, condPrompt: 0, condPlies: 0, frames: [] }])) }));
  const A = { plies: 0, pliesWithTwin: 0, pliesWithMoveTwin: 0, twins: 0, moveTwins: 0, unconfirmedTwins: 0, unconfirmedByStatus: {}, distanceOne: 0, patterns: {}, captureMismatch: 0, misreadPairs: {}, misreadPairsMoveTwins: {}, examples: {} };
  const B = { pliesWithTwin3: 0, pliesWithMoveTwin3: 0, twins3: 0, moveTwins3: 0, unconfirmed3: 0, patterns3: {} };
  const cost = { truthMarginAll2: 0, truthMarginMoves2: 0, truthMarginMoves3: 0 };
  const cross = { sampleTick: 0, checked: 0, mismatches: 0, mismatchExamples: [] };
  let gamesPlayed = 0;

  for (let gi = 0; gi < games; gi++) {
    const chess = new Chess(); gamesPlayed++;
    for (let ply = 0; ply < plies; ply++) {
      const truthMove = randomMove(chess, random);
      if (!truthMove) break;
      const fen = chess.fen({ forceEnpassantSquare: true }), truthUci = uciOf(truthMove);
      chess.move(truthMove);
      const H = hypotheses(fen), { truthGroup: T, twins, distanceOne } = analyseTwins(fen, truthUci, H);
      A.plies++; A.distanceOne += distanceOne;
      if (T.minAll <= 2) cost.truthMarginAll2++;
      if (T.minMoves <= 2) cost.truthMarginMoves2++;
      if (T.minMoves <= 3) cost.truthMarginMoves3++;
      let any2 = false, move2 = false, any3 = false, move3 = false;
      for (const tw of twins) {
        if (!tw.confirmed) {
          if (tw.d === 2) { A.unconfirmedTwins++; A.unconfirmedByStatus[tw.status] = (A.unconfirmedByStatus[tw.status] ?? 0) + 1; } else B.unconfirmed3++;
          continue;
        }
        const isMove = tw.wrong !== 'unchanged';
        if (tw.d === 2) {
          any2 = true; A.twins++; if (isMove) { move2 = true; A.moveTwins++; }
          A.patterns[tw.pattern] = (A.patterns[tw.pattern] ?? 0) + 1;
          if (tw.captureMismatch) A.captureMismatch++;
          const pair = tw.squares.map(s => s.type).sort().join(' + ');
          A.misreadPairs[pair] = (A.misreadPairs[pair] ?? 0) + 1;
          if (isMove) A.misreadPairsMoveTwins[pair] = (A.misreadPairsMoveTwins[pair] ?? 0) + 1;
          if ((A.examples[tw.pattern] ??= []).length < 2) A.examples[tw.pattern].push({ fen, truth: truthUci, acceptedInstead: tw.wrong, misreads: tw.squares.map(s => `${s.square} ${s.truth}->${s.readAs}`) });
        } else {
          any3 = true; B.twins3++; if (isMove) { move3 = true; B.moveTwins3++; }
          B.patterns3[tw.pattern] = (B.patterns3[tw.pattern] ?? 0) + 1;
        }
      }
      if (any2) A.pliesWithTwin++; if (move2) A.pliesWithMoveTwin++;
      if (any3) B.pliesWithTwin3++; if (move3) B.pliesWithMoveTwin3++;

      const tUnique = T.moves.length === 1, risky = g => g.minMoves <= 2;
      models.forEach((model, mi) => {
        // Exact expectation under the model for this position (probability the frame equals group g).
        const { p, q } = model, E = exact[mi], local = Object.fromEntries(GUARDS.map(g => [g, { correct: 0, wrong: 0, prompt: 0, frames: FRAMES[g] }]));
        for (const g of H.groups) {
          const d = hamming(g.occ, T.occ), pi = (p / 2) ** d * (1 - p - q) ** (64 - d);
          const key = g === T ? (tUnique ? 'correct' : 'ambiguous') : g.unchanged ? 'unchanged' : g.moves.length > 1 ? 'ambiguous' : 'wrong';
          E.single[key] += pi;
          if (key === 'unchanged') continue; // "unchanged" = keep waiting / re-read
          // Per attempt: accept (correct/wrong), prompt the human (promotion choice, margin veto) or re-read.
          const L = local, dec = key === 'ambiguous' ? 'prompt' : key;
          L['G0-none'][dec] += pi; L['G1-two-frame'][dec] += pi ** 2; L['G2-three-of-three'][dec] += pi ** 3;
          L['G3-margin2-all-hypotheses'][g.minAll <= 2 ? 'prompt' : dec] += pi;
          L['G3m-margin2-move-hypotheses'][g.minMoves <= 2 ? 'prompt' : dec] += pi;
          if (dec !== 'prompt' && risky(g)) { L['G4-margin-else-two-frame'][dec] += pi ** 2; L['G4-margin-else-two-frame'].frames += pi; }
          else L['G4-margin-else-two-frame'][dec] += pi;
        }
        // Per-ply totals. "Re-read until decided": the app keeps taking fresh frames until the guard
        // accepts a move or asks the human; per ply P(wrong) = w / (c + w + h).
        for (const name of GUARDS) {
          const l = local[name], t = E.guards[name], decided = l.correct + l.wrong + l.prompt;
          t.correct += l.correct; t.wrong += l.wrong; t.prompt += l.prompt;
          if (decided > 0) { t.condWrong += l.wrong / decided; t.condPrompt += l.prompt / decided; t.condPlies++; t.frames.push(l.frames / decided); }
        }
        // Monte Carlo: same model, independent frames.
        const M = mc[mi];
        const clean = classify(T.occ, H, truthUci);
        const read = () => {
          const frame = drawFrame(T.occ, p, q, noise);
          if (frame === T.occ) return clean;
          const fast = classify(frame, H, truthUci);
          if (fast.status !== 'no-legal-explanation' && fast.status !== 'uncertain' || ++cross.sampleTick % 250 === 0) {
            const real = realStatus(fen, frame); cross.checked++;
            if (!agrees(fast, real, truthUci)) { cross.mismatches++; if (cross.mismatchExamples.length < 5) cross.mismatchExamples.push({ fen, frame, fast: fast.status, real }); }
          }
          return fast;
        };
        for (let k = 0; k < trials; k++) {
          const f1 = read(), f2 = read(), f3 = read();
          M.trials++; M.single[f1.status]++;
          const moveOk = f => f.status === 'correct' || f.status === 'wrong';
          const tally = (name, accepted) => { if (accepted) M.guards[name][f1.status]++; };
          tally('G0-none', moveOk(f1));
          tally('G1-two-frame', moveOk(f1) && f2.uci === f1.uci);
          tally('G2-three-of-three', moveOk(f1) && f2.uci === f1.uci && f3.uci === f1.uci);
          tally('G3-margin2-all-hypotheses', moveOk(f1) && f1.group.minAll > 2);
          tally('G3m-margin2-move-hypotheses', moveOk(f1) && f1.group.minMoves > 2);
          tally('G4-margin-else-two-frame', moveOk(f1) && (!risky(f1.group) || f2.uci === f1.uci));
        }
      });
    }
  }

  const n = A.plies, share = k => k / n, perPlyGame = n / gamesPlayed;
  const sorted = o => Object.fromEntries(Object.entries(o).sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1)));
  const errorModels = models.map((model, mi) => {
    const M = mc[mi], E = exact[mi];
    const single = Object.fromEntries(STATUS_KEYS.map(k => [k === 'wrong' ? 'wrongAcceptedMove' : k === 'unchanged' ? 'wrongUnchanged' : k === 'correct' ? 'correctMove' : k, wilson(M.single[k], M.trials)]));
    const guards = Object.fromEntries(GUARDS.map(g => [g, {
      exactExpected: { perAttempt: { correctMove: E.guards[g].correct / n, wrongAcceptedMove: E.guards[g].wrong / n, promptHuman: E.guards[g].prompt / n, reRead: 1 - (E.guards[g].correct + E.guards[g].wrong + E.guards[g].prompt) / n },
        reReadUntilDecided: E.guards[g].condPlies ? { wrongShareOfMoves: E.guards[g].condWrong / E.guards[g].condPlies, promptHumanShareOfMoves: E.guards[g].condPrompt / E.guards[g].condPlies, wrongMovesPerGame: E.guards[g].condWrong / E.guards[g].condPlies * perPlyGame, medianFramesPerMove: median(E.guards[g].frames) } : null },
      monteCarlo: { correctMove: wilson(M.guards[g].correct, M.trials), wrongAcceptedMove: wilson(M.guards[g].wrong, M.trials) },
    }]));
    return { ...model, montecarloTrials: M.trials,
      singleFrame: { monteCarlo: single, exactExpected: { correctMove: E.single.correct / n, wrongAcceptedMove: E.single.wrong / n, wrongUnchanged: E.single.unchanged / n, ambiguous: E.single.ambiguous / n, noLegalExplanationOrUncertain: 1 - (E.single.correct + E.single.wrong + E.single.unchanged + E.single.ambiguous) / n } },
      guards };
  });
  const report = {
    description: 'Misread squares vs three-way occupancy move inference. Seeded random legal games, synthetic per-square error models. No images, no camera data.',
    parameters: { games, maxPlies: plies, seed, trialsPerPlyPerModel: trials, framesPerTrial: 3, prng: 'mulberry32 (games: seed; noise: seed xor 0x9E3779B9)', moveChoice: 'random own piece with a legal move, then a random legal move of it (same as occupancy-ambiguity-report.mjs)' },
    totalPlies: n, meanPliesPerGame: perPlyGame,
    A_twoMisreadTwins: {
      definition: 'Wrong hypothesis (other legal move or "unchanged") whose occupancy differs from the true result on exactly 2 squares; counted only if inferMove, given that corrupted reading, returns it.',
      distanceOneHypothesesFound: A.distanceOne,
      pliesWithAnyTwin: { count: A.pliesWithTwin, share: share(A.pliesWithTwin) },
      pliesWithWrongMoveTwin: { count: A.pliesWithMoveTwin, share: share(A.pliesWithMoveTwin) },
      meanTwinsPerPly: A.twins / n, meanWrongMoveTwinsPerPly: A.moveTwins / n,
      notConfirmed: { count: A.unconfirmedTwins, byStatus: A.unconfirmedByStatus, note: 'promotion groups: inferMove returns ambiguous, not a wrong move' },
      byPattern: sorted(A.patterns), captureVsNonCaptureMismatch: A.captureMismatch,
      examples: A.examples,
    },
    B_threeMisreadTwins: { pliesWithAnyTwin: { count: B.pliesWithTwin3, share: share(B.pliesWithTwin3) }, pliesWithWrongMoveTwin: { count: B.pliesWithMoveTwin3, share: share(B.pliesWithMoveTwin3) }, twins: B.twins3, wrongMoveTwins: B.moveTwins3, meanTwinsPerPly: B.twins3 / n, notConfirmed: B.unconfirmed3, byPattern: sorted(B.patterns3) },
    D_misreadTypesOfTwoSquareTwins: { allTwins: sorted(A.misreadPairs), wrongMoveTwinsOnly: sorted(A.misreadPairsMoveTwins) },
    C_randomErrorModels: errorModels,
    guardCostOnPerfectReadings: {
      'G1-two-frame': { abstainShare: 0, note: 'perfect frames always agree; cost is one extra frame (latency) per move' },
      'G2-three-of-three': { abstainShare: 0, note: 'two extra frames per move' },
      'G3-margin2-all-hypotheses': { abstainShare: share(cost.truthMarginAll2), note: 'literal rule incl. "unchanged": a normal move is always 2 squares from "unchanged", so it abstains on almost every move' },
      'G3m-margin2-move-hypotheses': { abstainShare: share(cost.truthMarginMoves2) },
      'G3m-margin3-move-hypotheses': { abstainShare: share(cost.truthMarginMoves3), note: 'radius 3 would also cover three-misread twins' },
      'G4-margin-else-two-frame': { abstainShare: 0, secondFrameNeededShare: share(cost.truthMarginMoves2) },
    },
    fastClassifierCrossCheck: { ...cross, note: 'Monte Carlo readings are classified by an exact replica of inferMove; every wrong/unchanged/ambiguous verdict and a deterministic 1-in-250 sample of the rest is re-run through inferMove itself.' },
  };
  return roundObj(report);
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const args = Object.fromEntries(process.argv.slice(2).reduce((pairs, arg, i, all) => (arg.startsWith('--') ? [...pairs, [arg.slice(2), all[i + 1]]] : pairs), []));
  const opts = { games: Number(args.games ?? 500), plies: Number(args.plies ?? 80), seed: Number(args.seed ?? 20261115), trials: Number(args.trials ?? 20) };
  const out = resolve(args.out ?? DEFAULT_OUT), started = Date.now();
  const report = runReport(opts);
  mkdirSync(dirname(out), { recursive: true });
  writeFileSync(out, JSON.stringify(report, null, 2) + '\n');
  const A = report.A_twoMisreadTwins;
  console.log(JSON.stringify({ out, seconds: (Date.now() - started) / 1000, plies: report.totalPlies, pliesWithWrongMoveTwin: A.pliesWithWrongMoveTwin.share, crossCheck: { checked: report.fastClassifierCrossCheck.checked, mismatches: report.fastClassifierCrossCheck.mismatches }, distanceOne: A.distanceOneHypothesesFound }));
  if (report.fastClassifierCrossCheck.mismatches || A.distanceOneHypothesesFound) process.exitCode = 1;
}
