import { Chess, validateFen } from 'chess.js';
export const START_FEN = new Chess().fen();
export function loadPosition(fen) {
  if (typeof fen !== 'string' || fen.length > 200 || fen.trim().split(/\s+/).length !== 6) throw new Error('Supply a complete six-field FEN, including historical castling and en passant rights.');
  const result = validateFen(fen);
  if (!result.ok) throw new Error(result.error);
  const chess = new Chess(fen);
  const parts = fen.trim().split(/\s+/);
  const board = chess.board().flat().filter(Boolean);
  for (const color of ['w', 'b']) {
    const own = board.filter(p => p.color === color), pawns = own.filter(p => p.type === 'p').length;
    if (own.length > 16 || pawns > 8) throw new Error('Too many pieces or pawns.');
    const count = type => own.filter(p => p.type === type).length;
    const bishops = [0, 0];
    for (const piece of own.filter(p => p.type === 'b')) bishops[('abcdefgh'.indexOf(piece.square[0]) + Number(piece.square[1])) % 2]++;
    const requiredPromotions = Math.max(0, count('q')-1) + Math.max(0, count('r')-2) + Math.max(0, count('n')-2) + bishops.reduce((n,c)=>n+Math.max(0,c-1),0);
    if (requiredPromotions > 8-pawns) throw new Error('Extra pieces require more promoted pawns than are missing.');
  }
  const king = board.find(p => p.type === 'k' && p.color !== chess.turn());
  if (chess.isAttacked(king.square, chess.turn())) throw new Error('The side that just moved cannot remain in check.');
  for (const [right,k,r,color] of [['K','e1','h1','w'],['Q','e1','a1','w'],['k','e8','h8','b'],['q','e8','a8','b']]) {
    if (parts[2].includes(right) && (chess.get(k)?.type !== 'k' || chess.get(k)?.color !== color || chess.get(r)?.type !== 'r' || chess.get(r)?.color !== color)) throw new Error('Castling rights do not match king and rook locations.');
  }
  if (parts[3] !== '-') {
    const file = parts[3][0], white = chess.turn() === 'w';
    const pawn = chess.get(file + (white ? '5' : '4'));
    if (chess.get(parts[3]) || chess.get(file + (white ? '7' : '2')) || pawn?.type !== 'p' || pawn?.color !== (white ? 'b' : 'w') || parts[4] !== '0') throw new Error('En passant state is inconsistent with the last double pawn move.');
  }
  return chess;
}
export function positionPayload(chess) {
  const checkmate = chess.isCheckmate(), stalemate = chess.isStalemate();
  const insufficientMaterial = chess.isInsufficientMaterial(), fiftyMove = chess.isDrawByFiftyMoves();
  const seventyFiveMove = Number(chess.fen().split(' ')[4]) >= 150;
  const gameOver = checkmate || stalemate || insufficientMaterial || seventyFiveMove;
  return { fen: chess.fen({forceEnpassantSquare:true}), turn: chess.turn(), board: chess.board().map(rank => rank.map(p => p ? (p.color === 'w' ? p.type.toUpperCase() : p.type) : null)), checked: chess.isCheck(), checkmate, stalemate, gameOver, insufficientMaterial, fiftyMove, seventyFiveMove, drawClaimAvailable: fiftyMove && !gameOver, status: checkmate ? 'checkmate' : stalemate ? 'stalemate' : insufficientMaterial ? 'insufficient-material' : seventyFiveMove ? 'seventy-five-move-draw' : fiftyMove ? 'fifty-move-claim-available' : chess.isCheck() ? 'check' : 'playing', legalMoves: chess.moves({verbose:true}).map(({from,to,san,promotion})=>({from,to,san,...(promotion?{promotion}:{})})), historyAvailable: false };
}
export function movePosition({fen,from,to,promotion}) {
  const chess = loadPosition(fen);
  if (positionPayload(chess).gameOver) throw new Error('The position is terminal.');
  if (promotion !== undefined && !['q','r','b','n'].includes(promotion)) throw new Error('Invalid promotion.');
  chess.move({from,to,...(promotion?{promotion}:{})});
  return positionPayload(chess);
}
