import test from 'node:test';
import assert from 'node:assert/strict';
import {DeviceBackend} from '../src/core/device-backend.js';
import {START_FEN} from '../src/core/position.js';
import {analyze} from '../src/core/engine.js';
const identity={sessionId:'phone-replay',epoch:1,sequence:2,frameSha256:'a'.repeat(64),revision:1};
const request=(kind,extra={})=>JSON.stringify({schemaVersion:1,requestId:'request-1',kind,...extra});
const analysis=()=>({fen:START_FEN,confirmation:true,movetimeMs:50,identity:{...identity}});
const good=input=>({...input,bestMove:{from:'e2',to:'e4'},speechText:'untrusted engine text'});

test('portable native contract validates full state and legal special moves without claiming history review',async()=>{
 let calls=0;const backend=new DeviceBackend({analyzer:async input=>{calls++;return good(input);}});
 const start=await backend.handle(request('position',{fen:START_FEN}));assert.equal(start.position.legalMoves.length,20);assert.equal(start.position.historyAvailable,false);assert.equal(calls,0);
 await assert.rejects(backend.handle(request('position',{fen:START_FEN.split(' ')[0]})));
 const castle=await backend.handle(request('move',{fen:'r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1',move:{from:'e1',to:'g1'}}));assert.match(castle.position.fen,/R4RK1 b kq/);assert.match(castle.speechText,/Castle/);
 assert.equal(castle.fen,'r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1');assert.deepEqual(castle.move,{from:'e1',to:'g1'});
 const promotion=await backend.handle(request('move',{fen:'7k/P7/8/8/8/8/8/7K w - - 0 1',move:{from:'a7',to:'a8',promotion:'n'}}));assert.deepEqual(promotion.move,{from:'a7',to:'a8',promotion:'n'});
 await assert.rejects(backend.handle(request('move',{fen:START_FEN,move:{from:'e2',to:'e5'}})));
 await assert.rejects(backend.handle(request('move',{fen:START_FEN,move:{from:'e2',to:'e4',promotion:'q'}})));
 backend.close();await assert.rejects(backend.handle(request('position',{fen:START_FEN})),e=>e.code==='CLOSED');
});

test('analysis requires explicit confirmation, bounded time and complete immutable frame identity',async()=>{
 let calls=0;const backend=new DeviceBackend({analyzer:async input=>{calls++;return good(input);}});
 for(const patch of [{confirmation:false},{identity:{...identity,frameSha256:'wrong'}},{identity:{...identity,revision:0}},{movetimeMs:3001},{rawLabels:[]},{fen:'bad'}])await assert.rejects(backend.handle(request('analyze',{...analysis(),...patch})));
 for(const text of ['null','[]','{',request('__proto__'),request('constructor'),'x'.repeat(16385)])await assert.rejects(backend.handle(text));
 assert.equal(calls,0);
 const result=await backend.handle(request('analyze',analysis()));assert.equal(calls,1);assert.deepEqual(result.identity,identity);assert.equal(result.fen,START_FEN);assert.equal(result.speechText,'pawn from e2 to e4.');assert.equal(result.runtime,'on-device-local');backend.close();
});

test('new frames/reviews/cancel/invalid commands cannot allow a noncooperative engine reply to escape',async()=>{
 for(const next of [request('cancel'),request('position',{fen:START_FEN}),'{']){
  let finish,signal;const backend=new DeviceBackend({analyzer:(input,options)=>{signal=options.signal;return new Promise(r=>finish=()=>r(good(input)));}});
  const pending=backend.handle(request('analyze',analysis()));const rejected=assert.rejects(pending,e=>e.code==='ABORTED');
  await backend.handle(next).catch(()=>{});assert.equal(signal.aborted,true);finish();await rejected;backend.close();
 }
});

test('foreign, missing, terminal and illegal engine results never produce speech',async()=>{
 for(const override of [{requestId:'foreign'},{fen:START_FEN.replace(' w ',' b ')},{bestMove:{from:'e2',to:'e5'}},{bestMove:null},{bestMove:{from:'e2',to:'e4',promotion:'q'}}]){
  const backend=new DeviceBackend({analyzer:async input=>({...good(input),...override})});await assert.rejects(backend.handle(request('analyze',analysis())),e=>e.code==='INVALID_RESULT');backend.close();
 }
 const terminal=new DeviceBackend({analyzer:async input=>good(input)});await assert.rejects(terminal.handle(request('analyze',{...analysis(),fen:'7k/6Q1/6K1/8/8/8/8/8 b - - 0 1'})),e=>e.code==='INVALID_RESULT');terminal.close();
});

test('reentrant result access revokes publication and real local engine obeys the portable command',async()=>{
 let backend;backend=new DeviceBackend({analyzer:async input=>({...input,get bestMove(){backend.cancel();return {from:'e2',to:'e4'};}})});
 await assert.rejects(backend.handle(request('analyze',analysis())),e=>e.code==='ABORTED');backend.close();
 const actual=new DeviceBackend({analyzer:analyze});const result=await actual.handle(request('analyze',analysis()));assert.equal(result.fen,START_FEN);assert.deepEqual(result.identity,identity);assert.ok(result.bestMove.san);assert.ok(result.speechText);actual.close();
});

test('abort-listener reentry cannot publish old-position speech after a newer position reply',async()=>{
 let finish,nested,calls=0;
 const backend=new DeviceBackend({analyzer:(input,{signal})=>{
  calls++;
  signal.addEventListener('abort',()=>{nested=backend.handle(request('analyze',{...analysis(),requestId:'nested-old'})).catch(e=>e);},{once:true});
  return new Promise(r=>finish=()=>r(good(input)));
 }});
 const old=backend.handle(request('analyze',analysis()));const oldRejected=assert.rejects(old,e=>e.code==='ABORTED');
 const after='rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1';
 const latest=await backend.handle(request('position',{fen:after,requestId:'new-position'}));
 assert.equal(latest.position.turn,'b');assert.equal((await nested).code,'ABORTED');assert.equal(calls,1);
 finish();await oldRejected;backend.close();
});
