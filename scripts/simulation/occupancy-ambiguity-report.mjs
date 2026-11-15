#!/usr/bin/env node
// Seeded, deterministic measurement of how often three-way occupancy (empty/white/black)
// pins down the move, starting from a known position. No images: occupancy is exact here.
// Usage: node scripts/simulation/occupancy-ambiguity-report.mjs [--games 2000] [--plies 80] [--seed 20261115] [--out file.json]
import { writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { Chess } from 'chess.js';
import { inferMove, OCCUPANCY_SQUARES } from '../../src/core/occupancy-move-inference.js';

const args = Object.fromEntries(process.argv.slice(2).reduce((pairs, arg, i, all) => (arg.startsWith('--') ? [...pairs, [arg.slice(2), all[i + 1]]] : pairs), []));
const games = Number(args.games ?? 2000), plies = Number(args.plies ?? 80), seed = Number(args.seed ?? 20261115);
const out = resolve(args.out ?? '/Users/alexmunzon/chess-builds/occupancy-2026-11-15/occupancy-ambiguity-report.json');
if (![games, plies, seed].every(Number.isSafeInteger) || games < 1 || plies < 1) throw new Error('games, plies and seed must be positive integers.');

function rng(s) { let a = s >>> 0; return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
const boardOcc = chess => OCCUPANCY_SQUARES.map(sq => { const p = chess.get(sq); return p ? (p.color === 'w' ? 'white' : 'black') : 'empty'; });
// Random own piece that has a legal move, then a random legal move of it.
function randomMove(chess, random) {
  const squares = OCCUPANCY_SQUARES.filter(sq => chess.get(sq)?.color === chess.turn());
  while (squares.length) {
    const k = Math.floor(random() * squares.length), moves = chess.moves({ square: squares[k], verbose: true });
    if (moves.length) return moves[Math.floor(random() * moves.length)];
    squares.splice(k, 1);
  }
  return null;
}

const random = rng(seed);
const counts = { plies: 0, unique: 0, ambiguous: { 'promotion-piece-choice': 0, other: 0 }, wrongUnique: 0, unexpected: 0 };
const examples = { 'promotion-piece-choice': [], other: [] };
// Second experiment: the same true reading with ONE square misread (random square, random wrong state).
const misread = { trials: 0, noLegalExplanation: 0, wrongUniqueMove: 0, correctUniqueMove: 0, ambiguous: 0, unchanged: 0, wrongUniqueExamples: [] };
const states = ['empty', 'white', 'black'];

for (let g = 0; g < games; g++) {
  const chess = new Chess();
  for (let ply = 0; ply < plies; ply++) {
    const truth = randomMove(chess, random);
    if (!truth) break;
    const fen = chess.fen({ forceEnpassantSquare: true });
    chess.move(truth);
    const uci = truth.from + truth.to + (truth.promotion ?? '');
    const occupancy = boardOcc(chess);
    const r = inferMove({ fen, occupancy });
    counts.plies++;
    if (r.status === 'move') { if (r.move.uci === uci) counts.unique++; else counts.wrongUnique++; }
    else if (r.status === 'ambiguous' && r.candidates.some(c => c.uci === uci)) {
      counts.ambiguous[r.cause]++;
      if (examples[r.cause].length < 5) examples[r.cause].push({ fen, truth: uci, candidates: r.candidates.map(c => ({ uci: c.uci, san: c.san })) });
    } else counts.unexpected++;

    const square = Math.floor(random() * 64), wrong = states.filter(s => s !== occupancy[square])[Math.floor(random() * 2)];
    const noisy = occupancy.slice(); noisy[square] = wrong;
    const m = inferMove({ fen, occupancy: noisy });
    misread.trials++;
    if (m.status === 'no-legal-explanation') misread.noLegalExplanation++;
    else if (m.status === 'ambiguous') misread.ambiguous++;
    else if (m.status === 'unchanged') misread.unchanged++;
    else if (m.status === 'move' && m.move.uci === uci) misread.correctUniqueMove++;
    else if (m.status === 'move') {
      misread.wrongUniqueMove++;
      if (misread.wrongUniqueExamples.length < 5) misread.wrongUniqueExamples.push({ fen, truth: uci, misreadSquare: OCCUPANCY_SQUARES[square], readAs: wrong, accepted: m.move.uci });
    }
  }
}

const pct = n => Number((100 * n / counts.plies).toFixed(4));
const report = {
  description: 'Three-way occupancy move inference on seeded random legal games; exact (noise-free) occupancy unless stated.',
  parameters: { games, maxPlies: plies, seed, prng: 'mulberry32', moveChoice: 'random own piece with a legal move, then a random legal move of it' },
  totalPlies: counts.plies,
  uniqueCorrect: { count: counts.unique, percent: pct(counts.unique) },
  ambiguous: { count: counts.ambiguous['promotion-piece-choice'] + counts.ambiguous.other, percent: pct(counts.ambiguous['promotion-piece-choice'] + counts.ambiguous.other),
    byCause: Object.fromEntries(Object.entries(counts.ambiguous).map(([k, v]) => [k, { count: v, percent: pct(v) }])) },
  wrongUniqueMove: counts.wrongUnique,
  unexpectedStatus: counts.unexpected,
  examples,
  singleSquareMisread: { ...misread, wrongUniqueMovePercent: Number((100 * misread.wrongUniqueMove / misread.trials).toFixed(4)) },
};
mkdirSync(dirname(out), { recursive: true });
writeFileSync(out, JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify({ out, totalPlies: report.totalPlies, unique: report.uniqueCorrect.percent, ambiguous: report.ambiguous, wrongUnique: counts.wrongUnique, misread: report.singleSquareMisread.wrongUniqueMovePercent }));
if (counts.wrongUnique || counts.unexpected) process.exitCode = 1;
