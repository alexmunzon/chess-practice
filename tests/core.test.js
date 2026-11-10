import test from 'node:test';
import assert from 'node:assert/strict';
import {loadPosition,positionPayload,movePosition,START_FEN} from '../src/core/position.js';
function perft(c,d) { if(!d)return 1; let n=0; for(const m of c.moves({verbose:true})){c.move(m);n+=perft(c,d-1);c.undo();} return n; }
test('starting position perft reference 20, 400, 8902',()=>{const c=loadPosition(START_FEN); for(const [d,n]of [[1,20],[2,400],[3,8902]])assert.equal(perft(c,d),n);});
test('Kiwipete castling perft reference 48, 2039',()=>{const c=loadPosition('r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1');assert.equal(perft(c,1),48);assert.equal(perft(c,2),2039);});
test('castling, en passant, and promotion',()=>{
 assert.ok(positionPayload(loadPosition('r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1')).legalMoves.some(m=>m.san==='O-O'));
 assert.ok(movePosition({fen:'4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2',from:'e5',to:'d6'}).board[3][3]===null);
 const p=positionPayload(loadPosition('7k/P7/8/8/8/8/8/7K w - - 0 1')); assert.equal(p.legalMoves.filter(m=>m.from==='a7').length,4);
 assert.equal(movePosition({fen:p.fen,from:'a7',to:'a8',promotion:'n'}).board[0][0],'N');
});
test('mate, stalemate, insufficient material, fifty move',()=>{
 assert.equal(positionPayload(loadPosition('7k/6Q1/5K2/8/8/8/8/8 b - - 0 1')).status,'checkmate');
 assert.equal(positionPayload(loadPosition('7k/5K2/6Q1/8/8/8/8/8 b - - 0 1')).status,'stalemate');
 assert.equal(positionPayload(loadPosition('7k/8/8/8/8/8/8/K7 w - - 0 1')).status,'insufficient-material');
 assert.equal(positionPayload(loadPosition('7k/8/8/8/8/8/8/KR6 w - - 100 51')).status,'fifty-move-claim-available');
});
test('reject incomplete FEN, invalid kings, impossible rights and illegal moves',()=>{
 for(const fen of ['8/8/8/8/8/8/8/8 w - - 0 1','8/8/8/8/8/8/k7/K7 w - - 0 1','7k/8/8/8/8/8/8/K7 w K - 0 1','7k/8/8/8/8/8/8/K7 w - d6 0 1',START_FEN.split(' ').slice(0,4).join(' ')])assert.throws(()=>loadPosition(fen));
 assert.throws(()=>movePosition({fen:START_FEN,from:'e2',to:'e5'}));
});

test('claimable fifty-move draw permits play; automatic 75-move draw stops, mate takes precedence',()=>{
 const fen='7k/8/8/8/8/8/8/KR6 w - - 100 51';
 const p=positionPayload(loadPosition(fen));assert.equal(p.gameOver,false);assert.equal(p.drawClaimAvailable,true);assert.equal(movePosition({fen,from:'b1',to:'b2'}).gameOver,false);
 const automatic=positionPayload(loadPosition(fen.replace('100 51','150 76')));assert.equal(automatic.gameOver,true);assert.equal(automatic.status,'seventy-five-move-draw');assert.throws(()=>movePosition({fen:automatic.fen,from:'b1',to:'b2'}));
 assert.equal(positionPayload(loadPosition('7k/6Q1/5K2/8/8/8/8/8 b - - 150 76')).status,'checkmate');
});
test('provably impossible promotion inventory rejected, legal promoted material allowed',()=>{
 for(const fen of ['7k/8/8/8/8/8/PPPPPPPP/KQQ5 w - - 0 1','7k/8/8/8/8/8/PPPPPPPP/K1B1B3 w - - 0 1','7k/8/8/8/8/8/PPPPPPP1/KQQQ4 w - - 0 1'])assert.throws(()=>loadPosition(fen),/promoted pawns/);
 assert.ok(loadPosition('7k/8/8/8/8/8/PPPPPPP1/KQQ5 w - - 0 1'));
});
