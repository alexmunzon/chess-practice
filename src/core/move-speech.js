import { loadPosition } from './position.js';

export function spokenMove(fen, move) {
  const m = loadPosition(fen).move(move);
  const names = {p:'pawn',n:'knight',b:'bishop',r:'rook',q:'queen',k:'king'};
  let text = m.flags.includes('k') ? 'Castle kingside' : m.flags.includes('q') ? 'Castle queenside' : `${names[m.piece]} from ${m.from} ${m.captured ? 'captures on' : 'to'} ${m.to}`;
  if (m.promotion) text += `, promote to ${names[m.promotion]}`;
  if (m.san.endsWith('#')) text += ', checkmate';
  else if (m.san.endsWith('+')) text += ', check';
  return text + '.';
}

