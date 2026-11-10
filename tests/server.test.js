import test from 'node:test';
import http from 'node:http';
import assert from 'node:assert/strict';
import {createServer} from '../src/server.js';
import {START_FEN} from '../src/core/position.js';
import {EngineError} from '../src/core/engine.js';
async function fixture(t, options){const server=createServer(options);await new Promise(r=>server.listen(0,'127.0.0.1',r));t.after(()=>new Promise(r=>{server.closeAllConnections();server.close(r);}));const base=`http://127.0.0.1:${server.address().port}`;return {base,post:(path,body,opts={})=>fetch(base+path,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body),...opts})};}
test('HTTP health, position, move, invalid and confirmation contracts',async t=>{
 const {base,post}=await fixture(t);
 assert.equal((await (await fetch(base+'/api/health')).json()).local,true);
 const p=await (await post('/api/position',{fen:START_FEN})).json();assert.equal(p.board[0][0],'r');assert.equal(p.legalMoves.length,20);
 const m=await (await post('/api/move',{fen:START_FEN,from:'e2',to:'e4'})).json();assert.equal(m.turn,'b');assert.equal(m.fen.split(' ')[3],'-');
 assert.equal((await post('/api/move',{fen:START_FEN,from:'e2',to:'e5'})).status,400);
 assert.equal((await post('/api/position',{fen:'bad'})).status,400);
 assert.equal((await post('/api/analyze',{fen:START_FEN,requestId:'one'})).status,400);
 assert.equal((await post('/api/analyze',{fen:START_FEN,confirmation:true})).status,400);
 assert.equal((await fetch(base+'/api/health',{headers:{origin:'https://example.com'}})).status,403);
 assert.equal(await new Promise((resolve,reject)=>{const req=http.get(base+'/api/health',{headers:{host:'evil.example'}},r=>{r.resume();resolve(r.statusCode);});req.on('error',reject);}),403);
 assert.equal((await fetch(base+'/package.json')).status,404);
 assert.equal((await fetch(base+'/src/review-state.js')).status,200);
 assert.equal((await fetch(base+'/src/position-draft.js')).status,200);
 const page=await fetch(base+'/');assert.match(page.headers.get('content-security-policy'),/img-src 'self' data: blob:/);assert.match(page.headers.get('content-security-policy'),/frame-ancestors 'none'/);
 assert.equal((await fetch(base+'/api/position',{method:'POST',body:'plain text'})).status,415);
 assert.equal((await post('/api/position',{fen:'x'.repeat(9000)})).status,413);
 assert.equal((await fetch(base+'/../package-lock.json')).status,404);
 assert.equal((await post('/api/cancel',{})).status,200);
});
test('new position cancels outstanding engine; stale result cannot publish',async t=>{
 let seenSignal,release; const started=new Promise(r=>release=r);
 const analyzer=(_,{signal})=>new Promise((resolve,reject)=>{seenSignal=signal;release();signal.addEventListener('abort',()=>reject(new EngineError('cancelled','ABORTED')),{once:true});});
 const {post}=await fixture(t,{analyzer});const pending=post('/api/analyze',{fen:START_FEN,requestId:'old',confirmation:true}); await started;
 await post('/api/position',{fen:START_FEN});assert.ok(seenSignal.aborted);assert.equal((await pending).status,409);
});
test('server rejects stale even when analyzer ignores abort',async t=>{
 let complete,release;const started=new Promise(r=>release=r);
 const {post}=await fixture(t,{analyzer:()=>new Promise(r=>{complete=r;release();})});
 const pending=post('/api/analyze',{fen:START_FEN,requestId:'old',confirmation:true});await started;await post('/api/cancel',{});complete({bestMove:'must not leak'});const res=await pending;assert.equal(res.status,409);assert.equal((await res.json()).bestMove,undefined);
});
test('client disconnect cancels live search',async t=>{
 let release,signal;const started=new Promise(r=>release=r);
 const {post}=await fixture(t,{analyzer:(_,{signal:s})=>new Promise((r,j)=>{signal=s;release();s.addEventListener('abort',()=>j(new EngineError('cancelled','ABORTED')));})});
 const c=new AbortController();const p=post('/api/analyze',{fen:START_FEN,requestId:'gone',confirmation:true},{signal:c.signal});await started;c.abort();await assert.rejects(p);await new Promise(r=>setTimeout(r,30));assert.ok(signal.aborted);
});
test('HTTP real Stockfish result echoes identity and normalized position',async t=>{const {post}=await fixture(t);const res=await post('/api/analyze',{fen:START_FEN,confirmation:true,requestId:'live-api',movetimeMs:100});assert.equal(res.status,200);const result=await res.json();assert.equal(result.requestId,'live-api');assert.equal(result.fen,START_FEN);assert.ok(result.bestMove.san);assert.ok(result.analysis.depth>0);assert.equal(result.analysis.scorePerspective,'side-to-move');});
