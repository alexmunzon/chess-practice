import { loadPosition } from './position.js';

/**
 * Move-level inference from three-way occupancy (prototype, pure logic, no images).
 *
 * Square order is a1, b1, ..., h1, a2, ..., h8 (index = (rank - 1) * 8 + file).
 * NOTE: this differs from observation.js SQUARES, which starts at a8.
 * Each entry is "empty" | "white" | "black" | "unknown".
 *
 * Hypotheses are exactly: "nothing moved" plus every legal move from `fen`.
 * The function never guesses: ambiguous, no-legal-explanation and uncertain all
 * mean "withhold and ask for human review".
 */
export const OCCUPANCY_SQUARES = Object.freeze(Array.from({ length: 64 }, (_, i) => 'abcdefgh'[i % 8] + (Math.floor(i / 8) + 1)));
const STATES = new Set(['empty', 'white', 'black', 'unknown']);
const indexOf = square => (Number(square[1]) - 1) * 8 + 'abcdefgh'.indexOf(square[0]);

function boardOccupancy(chess) {
  return OCCUPANCY_SQUARES.map(square => {
    const piece = chess.get(square);
    return piece ? (piece.color === 'w' ? 'white' : 'black') : 'empty';
  });
}

/** Occupancy of a FEN in a1..h8 order (testing and simulation helper). */
export function occupancyFromFen(fen) { return boardOccupancy(loadPosition(fen)); }

// Occupancy after a verbose chess.js move, derived from its flags without replaying it.
// The property test cross-checks this against chess.js actually playing the move.
function occupancyAfter(base, move) {
  const next = base.slice(), colour = move.color === 'w' ? 'white' : 'black';
  next[indexOf(move.from)] = 'empty';
  next[indexOf(move.to)] = colour;
  if (move.flags.includes('e')) next[indexOf(move.to[0] + move.from[1])] = 'empty';
  for (const [flag, rookFrom, rookTo] of [['k', 'h', 'f'], ['q', 'a', 'd']]) {
    if (move.flags.includes(flag)) { next[indexOf(rookFrom + move.from[1])] = 'empty'; next[indexOf(rookTo + move.from[1])] = colour; }
  }
  return next;
}

function describe({ move, fenAfter }) {
  return { uci: move.from + move.to + (move.promotion ?? ''), san: move.san, from: move.from, to: move.to, ...(move.promotion ? { promotion: move.promotion } : {}), fenAfter };
}

// Legal moves that could explain the reading. Every move empties its origin (an own square) and
// leaves its own colour on its destination (a square that was not own). So only (origin, destination)
// pairs where the origin now reads empty/unknown and the destination own/unknown can match; trying
// just those through chess.js is exact and avoids chess.js generating SAN for every legal move
// (about 1 ms per position). Illegal pairs are rejected by chess.js itself.
function candidateMoves(chess, base, observed, own) {
  const origins = [], destinations = [], found = new Map();
  base.forEach((value, i) => {
    if (value === own && (observed[i] === 'empty' || observed[i] === 'unknown')) origins.push(OCCUPANCY_SQUARES[i]);
    if (value !== own && (observed[i] === own || observed[i] === 'unknown')) destinations.push(OCCUPANCY_SQUARES[i]);
  });
  for (const from of origins) for (const to of destinations) {
    const promotes = chess.get(from).type === 'p' && (to[1] === '8' || to[1] === '1');
    for (const promotion of promotes ? ['q', 'r', 'b', 'n'] : [undefined]) {
      let move;
      try { move = chess.move(promotion ? { from, to, promotion } : { from, to }); } catch { continue; }
      const fenAfter = chess.fen({ forceEnpassantSquare: true });
      chess.undo();
      found.set(move.from + move.to + (move.promotion ?? ''), { move, fenAfter });
    }
  }
  return [...found.values()];
}

function validate(input) {
  if (input === null || typeof input !== 'object' || Array.isArray(input)) throw new TypeError('Input must be an object { fen, occupancy }.');
  if (typeof input.fen !== 'string') throw new TypeError('fen must be a string.');
  const { occupancy } = input;
  if (!Array.isArray(occupancy) || occupancy.length !== 64) throw new TypeError('occupancy must be an array of exactly 64 entries in a1..h8 order.');
  occupancy.forEach((value, i) => { if (!STATES.has(value)) throw new TypeError(`occupancy[${i}] (${OCCUPANCY_SQUARES[i]}) must be empty, white, black or unknown.`); });
}

/**
 * @param {{fen: string, occupancy: string[]}} input
 * @param {{assumeUntouchedUnknowns?: boolean}} [options]
 *   Default (strict): any "unknown" square yields "uncertain", unless no hypothesis can match
 *   the known squares at all (then "no-legal-explanation", which no reading could change).
 *   assumeUntouchedUnknowns: an unknown square is ignored only if NO legal move from `fen`
 *   could change it. That cannot change which legal move is chosen, but it can hide an
 *   unexplained change on that square, so it is an explicit assumption, reported back.
 * Throws TypeError/Error on malformed input (including an invalid FEN).
 */
export function inferMove(input, options = {}) {
  validate(input);
  const chess = loadPosition(input.fen);
  const observed = input.occupancy;
  const base = boardOccupancy(chess);
  const own = chess.turn() === 'w' ? 'white' : 'black';
  const hypotheses = [{ move: null, occ: base }, ...candidateMoves(chess, base, observed, own).map(c => ({ ...c, occ: occupancyAfter(base, c.move) }))];
  const unknown = [];
  observed.forEach((value, i) => { if (value === 'unknown') unknown.push(i); });
  const matches = hypotheses.filter(h => h.occ.every((value, i) => observed[i] === 'unknown' || observed[i] === value));

  if (matches.length === 0) return { status: 'no-legal-explanation' };
  let assumedSquares;
  if (unknown.length) {
    const unknownSquares = unknown.map(i => OCCUPANCY_SQUARES[i]);
    if (!options.assumeUntouchedUnknowns) return { status: 'uncertain', unknownSquares };
    const everyMove = chess.moves({ verbose: true }).map(move => occupancyAfter(base, move));
    const relevant = unknown.filter(i => everyMove.some(occ => occ[i] !== base[i])).map(i => OCCUPANCY_SQUARES[i]);
    if (relevant.length) return { status: 'uncertain', unknownSquares, relevantUnknownSquares: relevant };
    assumedSquares = unknownSquares;
  }
  const extra = assumedSquares ? { assumedUnchangedSquares: assumedSquares } : {};
  if (matches.length === 1) {
    const [only] = matches;
    if (!only.move) return { status: 'unchanged', ...extra };
    const { fenAfter, ...move } = describe(only);
    return { status: 'move', move, fenAfter, ...extra };
  }
  // "Unchanged" can never share an occupancy with a move (a move always empties its origin).
  if (matches.some(h => !h.move)) throw new Error('Internal invariant broken: a move matched the unchanged board.');
  const candidates = matches.map(describe);
  const sameSquares = candidates.every(c => c.from === candidates[0].from && c.to === candidates[0].to);
  const cause = sameSquares && candidates.every(c => c.promotion) ? 'promotion-piece-choice' : 'other';
  return { status: 'ambiguous', cause, candidates, ...extra };
}
