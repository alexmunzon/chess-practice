import test from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {PassThrough} from 'node:stream';
import {analyze} from '../src/core/engine.js';
import {START_FEN,loadPosition} from '../src/core/position.js';
const input={fen:START_FEN,confirmation:true,movetimeMs:100,requestId:'test'};
test('real Stockfish UCI startup and legal best move',async()=>{const r=await analyze(input); assert.ok(r.analysis.depth>0);assert.ok(loadPosition(r.fen).move(r.bestMove));assert.equal(r.requestId,'test');});
test('real Stockfish identifies mate in one',async()=>{const r=await analyze({...input,fen:'7k/5Q2/6K1/8/8/8/8/8 w - - 0 1',movetimeMs:300});const c=loadPosition(r.fen);c.move(r.bestMove);assert.ok(c.isCheckmate());assert.equal(r.analysis.mate,1);});
test('terminal position gives no move and confirmation is mandatory',async()=>{const r=await analyze({...input,fen:'7k/6Q1/5K2/8/8/8/8/8 b - - 0 1'});assert.equal(r.bestMove,null); await assert.rejects(analyze({...input,confirmation:false}),{code:'CONFIRMATION_REQUIRED'});await assert.rejects(analyze({...input,movetimeMs:3001}),{code:'INVALID_TIME'});});
function fake({ready=false,best=null}={}) {const child=new EventEmitter(); child.stdin=new PassThrough();child.stdout=new PassThrough();child.stderr=new PassThrough(); child.commands='';child.killed=false;child.kill=()=>{child.killed=true;};child.stdin.on('data',d=>{child.commands+=d; if(ready && String(d).startsWith('uci\n'))queueMicrotask(()=>child.stdout.write('uciok\n'));if(ready && String(d).startsWith('isready'))queueMicrotask(()=>child.stdout.write('readyok\n')); if(best && String(d).startsWith('go '))queueMicrotask(()=>child.stdout.write(`bestmove ${best}\n`));});return child;}
test('startup timeout, search timeout, cancellation stop and kill',async()=>{
 for(const ready of [false,true]){const child=fake({ready});await assert.rejects(analyze(input,{spawnEngine:()=>child,startupTimeoutMs:30,graceMs:10}),{code:'TIMEOUT'}); assert.ok(child.killed);assert.match(child.commands,/stop\nquit/);}
 const child=fake({ready:true}),controller=new AbortController();const p=analyze(input,{spawnEngine:()=>child,signal:controller.signal});controller.abort();await assert.rejects(p,{code:'ABORTED'});assert.ok(child.killed);
});
test('illegal engine output rejected',async()=>{await assert.rejects(analyze(input,{spawnEngine:()=>fake({ready:true,best:'e2e5'})}),{code:'INVALID_ENGINE_MOVE'});});
test('real Stockfish process cancellation rejects promptly',async()=>{const controller=new AbortController();const started=Date.now();const pending=analyze({...input,movetimeMs:3000},{signal:controller.signal});setTimeout(()=>controller.abort(),100);await assert.rejects(pending,{code:'ABORTED'});assert.ok(Date.now()-started<1500);});
