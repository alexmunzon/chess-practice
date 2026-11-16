#!/usr/bin/env node
/** Legal game lines for the simulated screen-game scene generator (make_screen_game_scenes.py).
 *
 * Mode "lines" (default): JSON on stdin {games:[{id, seed, hiddenPrefix:[san], prefix:[san], plies}]}.
 *   hiddenPrefix is played silently to reach a mid-game start FEN; prefix is a scripted SAN line;
 *   the rest is seeded random legal play that always takes castling / en passant / promotion when
 *   available and prefers captures. Output: {games:[{id, startFen, moves:[{uci, san, flags, fen}]}]}.
 * Mode "verify" (argv[2] === 'verify'): stdin {checks:[{before, uci, after}]}; prints
 *   {ok, failures:[{index, reason}]}; each uci must be legal from `before` and give exactly `after`.
 * Deterministic: own seeded PRNG, no clocks.
 */
import {Chess} from 'chess.js';

const FLAG_NAMES = {c: 'capture', e: 'enpassant', k: 'castle-k', q: 'castle-q', p: 'promotion'};

function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const uciOf = m => m.from + m.to + (m.promotion ?? '');

function flagsOf(move, chess) {
  const out = [];
  for (const f of ['c', 'e', 'k', 'q', 'p']) if (move.flags.includes(f)) out.push(FLAG_NAMES[f]);
  if (move.flags.includes('e') && !out.includes('capture')) out.unshift('capture');
  if (chess.inCheck()) out.push('check');
  return out;
}

function pick(rng, list) { return list[Math.floor(rng() * list.length)]; }

function chooseMove(rng, chess) {
  const moves = chess.moves({verbose: true});
  const special = moves.filter(m => /[kqe]/.test(m.flags));
  if (special.length) return pick(rng, special);
  const promos = moves.filter(m => m.flags.includes('p'));
  if (promos.length) {
    // pick a promoting pawn move, then a piece: queen 60 %, else an under-promotion
    const base = pick(rng, promos);
    const same = promos.filter(m => m.from === base.from && m.to === base.to);
    const r = rng();
    const piece = r < 0.6 ? 'q' : r < 0.75 ? 'n' : r < 0.9 ? 'r' : 'b';
    return same.find(m => m.promotion === piece) ?? base;
  }
  // avoid moves that end the game (mate/stalemate/insufficient) when something else exists
  const safe = moves.filter(m => { chess.move(m); const over = chess.isGameOver(); chess.undo(); return !over; });
  const pool = safe.length ? safe : moves;
  const captures = pool.filter(m => m.flags.includes('c'));
  if (captures.length && rng() < 0.45) return pick(rng, captures);
  const pawnPushes = pool.filter(m => m.piece === 'p' && !m.flags.includes('c'));
  if (pawnPushes.length && rng() < 0.3) return pick(rng, pawnPushes);
  return pick(rng, pool);
}

function playGame(spec) {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    const rng = mulberry32((spec.seed * 7919 + attempt * 104729) >>> 0);
    const chess = new Chess();
    for (const san of spec.hiddenPrefix ?? []) chess.move(san);
    const startFen = chess.fen();
    const moves = [];
    const push = move => moves.push({uci: uciOf(move), san: move.san, flags: flagsOf(move, chess), fen: chess.fen()});
    for (const san of spec.prefix ?? []) {
      const move = chess.move(san); // throws on an illegal scripted move
      if (move.san.replace(/[+#]/g, '') !== san.replace(/[+#]/g, '')) throw new Error(`Non-canonical SAN ${san}`);
      push(move);
    }
    while (moves.length < spec.plies && !chess.isGameOver()) push(chess.move(chooseMove(rng, chess)));
    if (moves.length >= spec.plies) return {id: spec.id, startFen, moves};
  }
  throw new Error(`Could not play ${spec.plies} plies for ${spec.id}`);
}

function verify(checks) {
  const failures = [];
  checks.forEach((c, index) => {
    let chess;
    try { chess = new Chess(c.before); } catch (e) { failures.push({index, reason: `bad before FEN: ${e.message}`}); return; }
    const legal = chess.moves({verbose: true}).find(m => uciOf(m) === c.uci);
    if (!legal) { failures.push({index, reason: `illegal ${c.uci}`}); return; }
    chess.move(legal);
    if (chess.fen() !== c.after) failures.push({index, reason: `fen mismatch: got ${chess.fen()}`});
    if (c.san !== undefined && c.san !== legal.san) failures.push({index, reason: `san mismatch: got ${legal.san}`});
  });
  return {ok: failures.length === 0, checked: checks.length, failures};
}

let input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', d => { input += d; });
process.stdin.on('end', () => {
  const req = JSON.parse(input);
  if (process.argv[2] === 'verify') process.stdout.write(JSON.stringify(verify(req.checks)));
  else process.stdout.write(JSON.stringify({games: req.games.map(playGame)}));
});
