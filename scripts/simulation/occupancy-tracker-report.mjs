#!/usr/bin/env node
// Seeded, deterministic simulation of the occupancy tracker (src/core/occupancy-tracker.js) over random legal
// games. Pure logic: SYNTHETIC occupancy pictures, no images, no classifier.
// Usage: node scripts/simulation/occupancy-tracker-report.mjs [--games 100] [--plies 80] [--seed 20261116] [--cross-check-plies 1000] [--promotion-games 40] [--out file.json]
// Exits 1 when any agreeFrames >= 2 row has a wrong accepted move or a stale-ready picture, a perfect row revokes, or the cross-check differs.
// Error model and PRNG are those of occupancy-misread-report.mjs: each square independently is read as one of the two
// wrong labels with probability p (p/2 each) or as "unknown" with probability q.
// Human model: a revoke is followed at once by a re-review that confirms the TRUE current position; a promotion
// question is answered by an oracle with the true piece. Pictures 150 ms apart; per position 3, or enough to span the
// tracker's readyDwellMs (8 at the 1000 ms default, round 5): the opponent is modelled as waiting that long.
import { writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { Chess } from 'chess.js';
import { OCCUPANCY_SQUARES } from '../../src/core/occupancy-move-inference.js';
import { OccupancyTracker, isGameOver } from '../../src/core/occupancy-tracker.js';
import { SingleFrameSimulationTracker } from './occupancy-tracker-single-frame.mjs';
import { ObservationTracker, SQUARES } from '../../src/core/observation.js';
import { rng } from './occupancy-misread-report.mjs';

export { rng };
export const DEFAULT_OUT = '/Users/alexmunzon/chess-builds/occupancy-tracker-2026-11-16/report.json';
const REVIEWED = { pieces: true, turn: true, castling: true, enPassant: true, counters: true };
const NAME = { e: 'empty', w: 'white', b: 'black', u: 'unknown' };
const hash = n => n.toString(16).padStart(64, '0');

// Same move choice as occupancy-ambiguity-report.mjs / occupancy-misread-report.mjs (copied: not exported there).
export function randomMove(chess, random) {
  const squares = OCCUPANCY_SQUARES.filter(sq => chess.get(sq)?.color === chess.turn());
  while (squares.length) {
    const k = Math.floor(random() * squares.length), moves = chess.moves({ square: squares[k], verbose: true });
    if (moves.length) return moves[Math.floor(random() * moves.length)];
    squares.splice(k, 1);
  }
  return null;
}
const occString = chess => OCCUPANCY_SQUARES.map(sq => { const p = chess.get(sq); return p ? p.color : 'e'; }).join('');
// Copied from occupancy-misread-report.mjs drawFrame (not exported there), plus the p + q = 0 case.
function drawFrame(truth, p, q, random) {
  const r = p + q; if (r === 0) return truth;
  let i = -1, out = null;
  const logKeep = Math.log(1 - r);
  for (;;) {
    i += 1 + Math.floor(Math.log(1 - random()) / logKeep);
    if (i >= 64) return out ? out.join('') : truth;
    out ??= truth.split('');
    if (q > 0 && random() < q / r) out[i] = 'u';
    else { const others = 'ewb'.replace(truth[i], ''); out[i] = others[random() < 0.5 ? 0 : 1]; }
  }
}
const squaresOf = s => Object.fromEntries(OCCUPANCY_SQUARES.map((sq, i) => [sq, { label: NAME[s[i]], confidence: 1 }]));

export const PROMOTION_RICH_FEN = '7k/PPPP4/8/8/8/8/pppp4/7K w - - 0 1';
export const SPACING_MS = 150;
let trackerSerial = 0;
export function trackerFor(agreeFrames, options = {}) {
  const instanceId = `sim-${++trackerSerial}`;
  return agreeFrames === 1 ? new SingleFrameSimulationTracker({ instanceId, ...options }) : new OccupancyTracker({ instanceId, agreeFrames, ...options });
}

/** Seeded games: each is a list of positions {fen, occ, moveIn} (moveIn = move that produced it). Stops at game over. */
export function makeGames({ games, plies, seed, startFen = new Chess().fen() }) {
  const random = rng(seed), out = [];
  for (let g = 0; g < games; g++) {
    const chess = new Chess(startFen), positions = [{ fen: chess.fen({ forceEnpassantSquare: true }), occ: occString(chess), moveIn: null }];
    for (let ply = 0; ply < plies && !isGameOver(chess); ply++) {
      const move = randomMove(chess, random); if (!move) break;
      chess.move(move);
      positions.push({ fen: chess.fen({ forceEnpassantSquare: true }), occ: occString(chess),
        moveIn: { from: move.from, to: move.to, promotion: move.promotion ?? null, flags: move.flags, piece: move.piece, color: move.color } });
    }
    out.push(positions);
  }
  return out;
}

const idx = sq => (Number(sq[1]) - 1) * 8 + 'abcdefgh'.indexOf(sq[0]);
const CASTLING_ROOK = { h1f1: 'K', a1d1: 'Q', h8f8: 'k', a8d8: 'q' };
const isCastlingRookHalf = (fen, m) => m.piece === 'r' && Boolean(CASTLING_ROOK[m.from + m.to]) && fen.split(' ')[2].includes(CASTLING_ROOK[m.from + m.to]);
const setAt = (occ, pairs) => { const o = occ.split(''); for (const [sq, v] of pairs) o[idx(sq)] = v; return o.join(''); };
/**
 * Middle-of-move pictures shown before the regular pictures of a position (each applicable move, probability 0.5):
 * hand: true board, 3x3 unknown block on the destination. lifted: previous board, origin emptied.
 * capture-off: a capture with both pieces off the board. en-passant: capturing pawn landed, captured pawn still there.
 * king-first: king on its castling square, rook still home (after one "king lifted" picture). rook-first: rook already
 * on its castling square, king home, 1 picture; rook-first-paused: same, 4 pictures (600 ms).
 * touch / touch-settle0: a sliding piece set down for 2 pictures (150 ms) on the first square of its path; touch-300 /
 * touch-600 / touch-900: the same rest held for 3 / 5 / 7 pictures (300 / 600 / 900 ms).
 */
const TOUCH_PICTURES = { touch: 2, 'touch-settle0': 2, 'touch-300': 3, 'touch-600': 5, 'touch-900': 7 };
function middleFrames(mode, prev, truth) {
  const m = truth.moveIn, c = m.color, rank = m.from[1];
  if (mode === 'hand') {
    const o = truth.occ.split(''), f = 'abcdefgh'.indexOf(m.to[0]), r = Number(m.to[1]) - 1;
    for (let df = -1; df <= 1; df++) for (let dr = -1; dr <= 1; dr++) if (f + df >= 0 && f + df < 8 && r + dr >= 0 && r + dr < 8) o[(r + dr) * 8 + f + df] = 'u';
    return [o.join('')];
  }
  if (mode === 'lifted') return [setAt(prev.occ, [[m.from, 'e']])];
  if (mode === 'capture-off') return m.flags.includes('c') ? [setAt(prev.occ, [[m.from, 'e'], [m.to, 'e']])] : [];
  if (mode === 'en-passant') return m.flags.includes('e') ? [setAt(prev.occ, [[m.from, 'e'], [m.to, c]])] : [];
  const castle = m.flags.includes('k') ? ['h', 'f', 'g'] : m.flags.includes('q') ? ['a', 'd', 'c'] : null;
  if (mode === 'king-first') return castle ? [setAt(prev.occ, [[m.from, 'e']]), setAt(prev.occ, [[m.from, 'e'], [castle[2] + rank, c]])] : [];
  if (mode === 'rook-first' || mode === 'rook-first-paused') {
    if (!castle) return [];
    const f = setAt(prev.occ, [[castle[0] + rank, 'e'], [castle[1] + rank, c]]);
    return mode === 'rook-first' ? [f] : [f, f, f, f];
  }
  if (TOUCH_PICTURES[mode]) {
    if (!'rbq'.includes(m.piece)) return [];
    const df = Math.sign(m.to.charCodeAt(0) - m.from.charCodeAt(0)), dr = Math.sign(Number(m.to[1]) - Number(m.from[1]));
    const via = String.fromCharCode(m.from.charCodeAt(0) + df) + (Number(m.from[1]) + dr);
    if (via === m.to) return [];
    const f = setAt(prev.occ, [[m.from, 'e'], [via, c]]);
    return Array(TOUCH_PICTURES[mode]).fill(f);
  }
  return [];
}
// Swap episodes (end of each game, if a pair exists): two pieces of the side to move (not king or pawn, different types)
// exchange squares. seen: both lifts visible; fast: only the first lift visible; hidden: both squares unknown.
function swapEpisode(mode, final, random) {
  const chess = new Chess(final.fen), side = chess.turn();
  const own = OCCUPANCY_SQUARES.filter(sq => { const p = chess.get(sq); return p && p.color === side && p.type !== 'k' && p.type !== 'p'; });
  const pairs = [];
  for (let i = 0; i < own.length; i++) for (let j = i + 1; j < own.length; j++) if (chess.get(own[i]).type !== chess.get(own[j]).type) pairs.push([own[i], own[j]]);
  if (!pairs.length) return null;
  const [a, b] = pairs[Math.floor(random() * pairs.length)];
  const pa = chess.get(a), pb = chess.get(b); chess.remove(a); chess.remove(b); chess.put(pb, a); chess.put(pa, b);
  const swapped = final.occ; // occupancy is identical after the swap
  const lead = mode === 'swap-seen' ? [setAt(final.occ, [[a, 'e']]), setAt(final.occ, [[b, 'e']])]
    : mode === 'swap-fast' ? [setAt(final.occ, [[a, 'e']])] : [setAt(final.occ, [[a, 'u'], [b, 'u']])];
  return { frames: [...lead, swapped, swapped, swapped], firstSwapped: lead.length, truthPlacement: chess.fen().split(' ')[0] };
}

/**
 * One row. 3 pictures per position, SPACING_MS apart. A promotion position gets agreeFrames + answerDelay extra pictures
 * when the opponent waits (probability `patience`). The oracle answers `answerDelay` pictures after the question.
 * `wrongTrusted` counts every picture after which the tracker is ready on a FEN that is not the board (stale or wrong).
 */
export function simulate(games, { agreeFrames, p, q, noiseSeed, answerDelay = 0, patience = 1, inBetween = null, gameSet = 'standard', trackerOptions = {} }) {
  const tracker = trackerFor(agreeFrames, trackerOptions), noise = rng(noiseSeed), events = rng((noiseSeed ^ 0x27d4eb2f) >>> 0);
  const s = { agreeFrames, p, q, gameSet, answerDelay, patience, inBetween, inTransitTolerance: tracker.options.inTransitTolerance, minSettleMs: tracker.options.minSettleMs,
    games: games.length, positions: 0, pictures: 0, middlePictures: 0, swapEpisodes: 0, swapEpisodesTrustedWrong: 0,
    acceptedMoves: 0, wrongAcceptedMoves: 0, wrongTrusted: 0, revokes: 0, revokesByReason: {}, promotionPositions: 0, promotionPrompts: 0,
    wrongPromotionQuestions: 0, promotionAnswersAccepted: 0, promotionsVerified: 0, gamesTrackedToFinalFen: 0, gamesWithoutReReview: 0 };
  const placement = fen => fen.split(' ')[0];
  let time = 0, seq = 0;
  games.forEach((positions, g) => {
    const session = { sessionId: 'sim', epoch: g + 1 };
    tracker.confirm({ session, fen: positions[0].fen, reviewed: REVIEWED, atMs: time });
    let reReviews = 0, pendingAnswer = null;
    const send = frame => { time += SPACING_MS; seq++; s.pictures++; return tracker.ingest({ identity: { ...session, sequence: seq, frameSha256: hash(seq) }, capturedAtMs: time, squares: squaresOf(frame) }); };
    positions.forEach((truth, i) => {
      s.positions++;
      const promotion = Boolean(truth.moveIn?.promotion);
      if (promotion) s.promotionPositions++;
      const frames = [];
      if (inBetween && !inBetween.startsWith('swap') && i > 0 && events() < 0.5) { const extra = middleFrames(inBetween, positions[i - 1], truth); s.middlePictures += extra.length; frames.push(...extra); }
      const middleCount = frames.length;
      const waits = promotion && events() < patience;
      // A rook move that is also half of an allowed castling needs castlingRookSettleMs: the opponent is modelled as waiting.
      const rookHalf = truth.moveIn && isCastlingRookHalf(positions[i - 1].fen, truth.moveIn);
      const o = tracker.options, dwell = o.readyDwellMs ?? 0;
      const regular = rookHalf ? Math.ceil(Math.max(o.castlingRookSettleMs, dwell) / SPACING_MS) + 1 : Math.max(3, Math.ceil(Math.max(o.minSettleMs, dwell) / SPACING_MS) + 1);
      for (let k = 0; k < regular + (waits ? agreeFrames + answerDelay : 0); k++) frames.push(drawFrame(truth.occ, p, q, noise));
      for (const [k, frame] of frames.entries()) {
        let r = send(frame);
        if (pendingAnswer && r.status !== 'awaiting-promotion-choice') pendingAnswer = null;
        else if (pendingAnswer) pendingAnswer.remaining--;
        if (r.event === 'promotion-question') {
          s.promotionPrompts++;
          const m = truth.moveIn, right = m?.promotion && m.from === r.pendingQuestion.from && m.to === r.pendingQuestion.to;
          if (!right) s.wrongPromotionQuestions++;
          pendingAnswer = { questionId: r.pendingQuestion.questionId, piece: right ? m.promotion : 'q', remaining: answerDelay };
        }
        if (pendingAnswer && pendingAnswer.remaining <= 0) {
          r = tracker.answerPromotion({ session, questionId: pendingAnswer.questionId, piece: pendingAnswer.piece, atMs: time });
          if (r.accepted) s.promotionAnswersAccepted++;
          pendingAnswer = null;
        }
        const accepted = r.event === 'move-accepted' || (r.event === 'position-seen' && r.reason === 'promotion-position-seen');
        if (accepted) { s.acceptedMoves++; if (r.reason === 'promotion-position-seen') s.promotionsVerified++; if (r.fen !== truth.fen) s.wrongAcceptedMoves++; }
        // A middle picture is a board in mid-move: being ready on any FEN then is trusting a position that is not on the board.
        if (r.trackingReady && (k < middleCount || r.fen !== truth.fen)) s.wrongTrusted++;
        if (r.event === 'revoked') {
          s.revokes++; s.revokesByReason[r.reason] = (s.revokesByReason[r.reason] ?? 0) + 1; reReviews++; pendingAnswer = null;
          tracker.confirm({ session, fen: truth.fen, reviewed: REVIEWED, atMs: time }); // human re-review of the true position
        }
      }
    });
    const end = tracker.snapshot();
    if (end.trackingReady && end.fen === positions.at(-1).fen) s.gamesTrackedToFinalFen++;
    if (reReviews === 0) s.gamesWithoutReReview++;
    if (inBetween?.startsWith('swap') && end.trackingReady) {
      const episode = swapEpisode(inBetween, positions.at(-1), events);
      if (episode) {
        s.swapEpisodes++; let wrong = false;
        for (const [k, frame] of episode.frames.entries()) {
          const r = send(frame); s.middlePictures++;
          if (r.event === 'revoked') { s.revokes++; s.revokesByReason[r.reason] = (s.revokesByReason[r.reason] ?? 0) + 1; break; }
          if (k >= episode.firstSwapped && r.trackingReady && placement(r.fen) !== episode.truthPlacement) { s.wrongTrusted++; wrong = true; }
        }
        if (wrong) s.swapEpisodesTrustedWrong++;
      }
    }
  });
  s.reReviewsPer100Positions = Number((100 * s.revokes / s.positions).toFixed(3));
  s.revokesByReason = Object.fromEntries(Object.entries(s.revokesByReason).sort(([a], [b]) => (a < b ? -1 : 1)));
  return s;
}

/**
 * Cross-check with the existing 13-label ObservationTracker on PERFECT readings. Both trackers see the same
 * pictures (13 labels for the old one, the same board as occupancy for the new one), 60 ms apart. After every picture of a
 * non-promotion position: same readiness, same trusted FEN, same last SAN. A promotion position gets 2 extra pictures (the
 * occupancy tracker asks, then verifies after the answer) and is compared at its last picture only.
 */
export function crossCheck({ minNonPromotionPlies = 210, plies = 80, seed = 77, startFens = [new Chess().fen()] } = {}) {
  const random = rng(seed), out = { games: 0, pictures: 0, nonPromotionPlies: 0, promotions: 0, questions: 0, acceptedMovesOld: 0, acceptedMovesNew: 0, mismatches: 0, examples: [] };
  while (out.nonPromotionPlies < minNonPromotionPlies) {
    const startFen = startFens[out.games % startFens.length];
    let time = 0, seq = 0, last = null, oldFen = new Chess(startFen).fen({ forceEnpassantSquare: true });
    const old = new ObservationTracker({ clock: () => time }); old.connect('x'); old.confirm({ fen: startFen, reviewed: REVIEWED });
    // minSettleMs / readyDwellMs 0: the old tracker has no settle time (2 frames, 50 ms), so this compares the logic, not the timing.
    const occ = new OccupancyTracker({ instanceId: `cross-${++trackerSerial}`, minSettleMs: 0, castlingRookSettleMs: 0, readyDwellMs: 0 }), session = { sessionId: 'x', epoch: 1 };
    occ.confirm({ session, fen: startFen, reviewed: REVIEWED });
    const chess = new Chess(startFen); out.games++;
    const look = ply => {
      const n = 3 + (last?.promotion ? 2 : 0);
      for (let k = 0; k < n; k++) {
        time += 60; seq++; out.pictures++;
        const labels = Object.fromEntries(SQUARES.map(sq => { const pc = chess.get(sq); return [sq, { label: pc ? (pc.color === 'w' ? pc.type.toUpperCase() : pc.type) : 'empty', confidence: 1 }]; }));
        const a = old.ingest({ sourceId: 'x', epoch: old.snapshot().epoch, sequence: seq, capturedAt: time, squares: labels });
        let b = occ.ingest({ identity: { ...session, sequence: seq, frameSha256: hash(seq) }, capturedAtMs: time, squares: squaresOf(occString(chess)) });
        if (b.event === 'promotion-question') { out.questions++; b = occ.answerPromotion({ session, questionId: b.pendingQuestion.questionId, piece: last.promotion, atMs: time }); }
        if (b.event === 'move-accepted' || b.reason === 'promotion-position-seen' && b.event === 'position-seen') out.acceptedMovesNew++;
        if (a.fen !== oldFen) { out.acceptedMovesOld++; oldFen = a.fen; } // the old tracker's FEN changes only when it accepts a move
        if (last?.promotion && k < n - 1) continue;
        const same = b.trackingReady === a.guidanceAllowed && b.fen === (a.guidanceAllowed ? a.fen : null) && (b.lastMove?.san ?? null) === (a.guidanceAllowed ? a.lastMove?.san ?? null : null);
        if (!same) { out.mismatches++; if (out.examples.length < 5) out.examples.push({ game: out.games, ply, picture: k, old: { ready: a.guidanceAllowed, reason: a.reason, fen: a.fen }, occupancy: { ready: b.trackingReady, reason: b.reason, fen: b.fen } }); }
      }
    };
    for (let ply = 0; ply < plies; ply++) {
      look(ply);
      if (isGameOver(chess)) break;
      last = randomMove(chess, random); if (!last) break;
      chess.move(last); if (last.promotion) out.promotions++; else out.nonPromotionPlies++;
    }
    look(plies);
  }
  return out;
}

export const MIDDLE_MODELS = Object.freeze(['hand', 'lifted', 'capture-off', 'en-passant', 'king-first', 'rook-first', 'rook-first-paused', 'touch', 'touch-300', 'touch-600', 'touch-900', 'touch-settle0', 'swap-seen', 'swap-fast', 'swap-hidden']);
export const DEFAULT_EXTRA_ROWS = Object.freeze([
  ...[0, 2, 5].map(answerDelay => ({ agreeFrames: 2, p: 0, q: 0, answerDelay, patience: 0.5, games: 'promotion-rich' })),
  ...MIDDLE_MODELS.flatMap(inBetween => [false, true].map(inTransitTolerance => ({ agreeFrames: 2, p: 0, q: 0, inBetween,
    trackerOptions: { inTransitTolerance, ...(inBetween === 'touch-settle0' ? { minSettleMs: 0, readyDwellMs: 0 } : {}) } }))),
]);
// Exempt from the exit check, reported instead: touch-settle0 (a deliberate comparison row with settle and dwell switched off).
// swap-hidden was exempt until round 4; since round 5 the tracker refuses it (both squares were disturbed), so it is checked.
const OCCUPANCY_BLIND = new Set(['touch-settle0']);

export function runReport({ games = 100, plies = 80, seed = 20261116, agree = [1, 2, 3], p = [0, 0.003, 0.01], q = [0, 0.03], crossCheckPlies = 1000,
  extraRows = DEFAULT_EXTRA_ROWS, promotionGames = 40 } = {}) {
  if (![games, plies, seed, promotionGames].every(Number.isSafeInteger) || games < 1 || plies < 1) throw new Error('games, plies and seed must be integers >= 1.');
  const sets = { standard: makeGames({ games, plies, seed }), 'promotion-rich': makeGames({ games: promotionGames, plies: 30, seed: seed + 1, startFen: PROMOTION_RICH_FEN }) };
  const rows = [];
  let index = 0;
  const run = (gameSet, opts) => { index++; rows.push(simulate(sets[gameSet], { ...opts, gameSet, noiseSeed: (seed ^ 0x9E3779B9 ^ Math.imul(index, 0x85EBCA6B)) >>> 0 })); };
  for (const agreeFrames of agree) for (const pv of p) for (const qv of q) run('standard', { agreeFrames, p: pv, q: qv });
  for (const { games: gameSet = 'standard', ...opts } of extraRows) run(gameSet, opts);
  return {
    description: 'Occupancy tracker over seeded random legal games. SYNTHETIC occupancy pictures (no images), independent per-square errors.',
    parameters: { games, maxPlies: plies, seed, promotionRichGames: { games: promotionGames, maxPlies: 30, startFen: PROMOTION_RICH_FEN, seed: seed + 1 },
      picturesPerPosition: '3, plus agreeFrames + answerDelay at a promotion when the opponent waits (probability patience)', pictureSpacingMs: SPACING_MS,
      trackerDefaults: (({ instanceId, ...rest }) => rest)(new OccupancyTracker({ instanceId: `defaults-${++trackerSerial}` }).options),
      errorModel: 'per square: wrong label with prob p (each of the two wrong labels p/2), unknown with prob q (occupancy-misread-report.mjs drawFrame)',
      inBetween: 'middle-of-move pictures before the position (prob 0.5 per applicable move); swap models: one episode at the end of each game; see middleFrames/swapEpisode',
      human: 'revoke -> immediate re-review confirming the true position; promotion question -> oracle answer after answerDelay pictures',
      agreeFrames1: 'emulated by scripts/simulation/occupancy-tracker-single-frame.mjs (each picture counted twice); the module refuses 1',
      prng: 'mulberry32; games: seed (promotion-rich: seed+1); noise per row: seed ^ 0x9E3779B9 ^ imul(rowIndex, 0x85EBCA6B); events: noise seed ^ 0x27d4eb2f' },
    rows,
    crossCheckWithObservationTracker: crossCheckPlies > 0 ? crossCheck({ minNonPromotionPlies: crossCheckPlies, seed }) : null,
  };
}

export function failures(report) {
  const bad = [];
  for (const r of report.rows) {
    // (Perfect rows include rook moves that are half of an allowed castling: shown for castlingRookSettleMs, see simulate.)
    if (r.agreeFrames >= 2 && !OCCUPANCY_BLIND.has(r.inBetween) && (r.wrongTrusted || r.wrongAcceptedMoves)) bad.push(`agree ${r.agreeFrames} ${r.inBetween ?? ''} transit ${r.inTransitTolerance}: wrong or stale trusted`);
    if (r.p === 0 && r.q === 0 && !r.inBetween && !r.answerDelay && r.patience === 1 && (r.revokes || r.gamesTrackedToFinalFen !== r.games)) bad.push('perfect row revoked');
  }
  const cc = report.crossCheckWithObservationTracker;
  if (cc && (cc.mismatches || cc.questions !== cc.promotions || cc.acceptedMovesNew !== cc.acceptedMovesOld)) bad.push('cross-check mismatch');
  return bad;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const args = Object.fromEntries(process.argv.slice(2).reduce((pairs, arg, i, all) => (arg.startsWith('--') ? [...pairs, [arg.slice(2), all[i + 1]]] : pairs), []));
  const out = resolve(args.out ?? DEFAULT_OUT), started = Date.now();
  const report = runReport({ games: Number(args.games ?? 100), plies: Number(args.plies ?? 80), seed: Number(args.seed ?? 20261116), crossCheckPlies: Number(args['cross-check-plies'] ?? 1000), promotionGames: Number(args['promotion-games'] ?? 40) });
  mkdirSync(dirname(out), { recursive: true });
  writeFileSync(out, JSON.stringify(report, null, 2) + '\n');
  const cols = ['agree', 'p', 'q', 'games', 'delay', 'between', 'transit', 'positions', 'middle', 'wrong', 'wrongTr', 'swapWr', 'revokes', 'reRev/100', 'prompts', 'wrongQ', 'verified', 'tracked'];
  console.log(cols.map(c => c.padEnd(9)).join(' '));
  for (const r of report.rows) console.log([r.agreeFrames, r.p, r.q, r.gameSet === 'standard' ? 'std' : 'promo', r.answerDelay, r.inBetween ?? '-', r.inTransitTolerance ? 'on' : 'off', r.positions, r.middlePictures, r.wrongAcceptedMoves, r.wrongTrusted, `${r.swapEpisodesTrustedWrong}/${r.swapEpisodes}`, r.revokes, r.reReviewsPer100Positions, `${r.promotionPrompts}/${r.promotionPositions}`, r.wrongPromotionQuestions, r.promotionsVerified, `${r.gamesTrackedToFinalFen}/${r.games}`].map(String).map(v => v.padEnd(9)).join(' '));
  const cc = report.crossCheckWithObservationTracker;
  if (cc) console.log('cross-check vs ObservationTracker:', JSON.stringify({ games: cc.games, pictures: cc.pictures, nonPromotionPlies: cc.nonPromotionPlies, promotions: cc.promotions, questions: cc.questions, acceptedMovesOld: cc.acceptedMovesOld, acceptedMovesNew: cc.acceptedMovesNew, mismatches: cc.mismatches }));
  const bad = failures(report);
  console.log(JSON.stringify({ out, seconds: (Date.now() - started) / 1000, failures: bad }));
  if (bad.length) process.exitCode = 1;
}
