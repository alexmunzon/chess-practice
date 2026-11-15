import test from 'node:test';
import assert from 'node:assert/strict';
import { Chess } from 'chess.js';
import { SQUARES } from '../src/core/observation.js';
import { LiveSession, TextSpeechSink, spokenMove } from '../src/core/live-session.js';
const fen = new Chess().fen();
const reviewed = {pieces:true,turn:true,castling:true,enPassant:true,counters:true};
function setup(engine, color='w', speech=new TextSpeechSink()) {
 let now=0;
 const session=new LiveSession({engine,speech,color,trackerOptions:{clock:()=>now}});
 const {epoch}=session.connect('rehearsal');session.confirm({fen,reviewed});
 const frame=(sequence)=>({sourceId:'rehearsal',epoch,sequence,capturedAt:now,squares:Object.fromEntries(SQUARES.map(s=>{const p=new Chess(fen).get(s);return [s,{label:p?(p.color==='w'?p.type.toUpperCase():p.type):'empty',confidence:1}]}))});
 session.ingestReviewed(frame(0),{humanReviewed:true});now=60; session.ingestReviewed(frame(1),{humanReviewed:true});
 return {session,speech,frame,setTime:t=>now=t};
}
const engine=async q=>({...q,bestMove:{from:'e2',to:'e4'}});
test('stable reviewed position speaks once and only on own turn', async()=>{
 const {session,speech}=setup(engine); try {assert.ok(await session.guide());assert.equal(await session.guide(),null);assert.deepEqual(speech.messages,['pawn from e2 to e4.']);} finally {session.stop();}
 const other=setup(engine,'b');try {assert.equal(await other.session.guide(),null);} finally{other.session.stop();}
});
test('late engine result is dropped after uncertainty, timeout, stop or reconnect',async()=>{
 for(const change of ['uncertain','timeout','stop','connect']) {
 let resolve;const x=setup(q=>new Promise(r=>{resolve=()=>r({...q,bestMove:{from:'e2',to:'e4'}})}));
 const pending=x.session.guide();
 if(change==='uncertain'){x.setTime(70);const f=x.frame(2);f.squares.a1.label='unknown';x.session.ingestReviewed(f,{humanReviewed:true});}
 if(change==='timeout'){x.setTime(2000);x.session.tick();}
 if(change==='stop')x.session.stop();
 if(change==='connect')x.session.connect('new');
 resolve();assert.equal(await pending,null);assert.equal(x.speech.messages.length,0);x.session.stop();
 }
});
test('review draft and wrong engine identity cannot speak',async()=>{
 const x=setup(async q=>({...await engine(q),requestId:'wrong'}));assert.equal(await x.session.guide(),null);
 assert.throws(()=>x.session.ingestReviewed(x.frame(3)),/human review/);assert.equal(x.speech.messages.length,0);x.session.stop();
});
test('spoken move names castling and promotion check',()=>{
 assert.equal(spokenMove('r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1',{from:'e1',to:'g1'}),'Castle kingside.');
 assert.match(spokenMove('7k/P7/8/8/8/8/8/7K w - - 0 1',{from:'a7',to:'a8',promotion:'q'}),/promote to queen, check/);
});
test('fresh identical frames preserve a slow search and configured analysis budget',async()=>{
 let resolve, request;
 const x=setup(q=>{request=q;return new Promise(r=>{resolve=()=>r({...q,bestMove:{from:'e2',to:'e4'}});});});
 try {
  const pending=x.session.guide();
  for(let sequence=2;sequence<=8;sequence++) {x.setTime(sequence*500);x.session.ingestReviewed(x.frame(sequence),{humanReviewed:true});}
  assert.equal(request.movetimeMs,1000);resolve();assert.ok(await pending);assert.equal(x.speech.messages.length,1);
 } finally {x.session.stop();}
});
test('analysis budget validates supported bounds',()=>{
 for(const movetimeMs of [49,3001,NaN,50.5]) assert.throws(()=>new LiveSession({engine,color:'w',movetimeMs}),/analysis time/);
 for(const movetimeMs of [50,1500,3000]) {const s=new LiveSession({engine,color:'w',movetimeMs});s.stop();}
});

test('queued speech remains cancellable after the adapter acknowledges it',async()=>{
 for(const change of ['uncertain','timeout','changed-board','stop','connect']) {
  let output, playing=false, cancellations=0;
  const speech={
   cancel(){cancellations++;playing=false;},
   async speak(text,options){output=options;if(!options.signal.aborted&&options.isCurrent())playing=true;}
  };
  const x=setup(engine,'w',speech);
  try {
   assert.ok(await x.session.guide());assert.equal(playing,true);
   const before=cancellations;
   if(change==='uncertain'||change==='changed-board') {
    x.setTime(70);const f=x.frame(2);
    if(change==='uncertain')f.squares.a1.label='unknown';
    else {f.squares.e2.label='empty';f.squares.e4.label='P';}
    assert.equal(x.session.ingestReviewed(f,{humanReviewed:true}).guidanceAllowed,false);
   }
   if(change==='timeout'){x.setTime(2000);x.session.tick();}
   if(change==='stop')x.session.stop();
   if(change==='connect')x.session.connect('new');
   assert.equal(playing,false,change);
   assert.equal(output.signal.aborted,true,change);
   assert.equal(output.isCurrent(),false,change);
   assert.ok(cancellations>before,change);
  } finally{x.session.stop();}
 }
});

test('identical fresh observations preserve queued speech without repeating it',async()=>{
 let output,calls=0;
 const speech={cancel(){},async speak(text,options){calls++;output=options;}};
 const x=setup(engine,'w',speech);
 try {
  assert.ok(await x.session.guide());x.setTime(500);
  assert.equal(x.session.ingestReviewed(x.frame(2),{humanReviewed:true}).guidanceAllowed,true);
  assert.equal(output.signal.aborted,false);assert.equal(output.isCurrent(),true);
  assert.equal(await x.session.guide(),null);assert.equal(calls,1);
 } finally{x.session.stop();}
});

test('speech failure cancels partial output and permits a fresh retry',async()=>{
 let calls=0,playing=false,firstSignal;
 const speech={
  cancel(){playing=false;},
  async speak(text,{signal}){playing=true;if(++calls===1){firstSignal=signal;throw new Error('Audio unavailable');}}
 };
 const x=setup(engine,'w',speech);
 try {
  assert.equal(await x.session.guide(),null);assert.equal(playing,false);
  assert.equal(firstSignal.aborted,true);assert.equal(x.session.lastError,'Audio unavailable');
  assert.ok(await x.session.guide());assert.equal(calls,2);assert.equal(playing,true);
  assert.equal(x.session.lastError,null);assert.equal(await x.session.guide(),null);
 } finally{x.session.stop();}
});

test('late completion of cancelled speech cannot disturb replacement output',async()=>{
 let rejectFirst,calls=0,secondSignal;
 const speech={
  cancel(){},
  speak(text,{signal}){if(++calls===1)return new Promise((_,reject)=>{rejectFirst=reject;});secondSignal=signal;return Promise.resolve();}
 };
 const x=setup(engine,'w',speech);
 try {
  const first=x.session.guide();await new Promise(resolve=>setImmediate(resolve));
  x.session.confirm({fen,reviewed});x.setTime(70);x.session.ingestReviewed(x.frame(2),{humanReviewed:true});
  x.setTime(130);x.session.ingestReviewed(x.frame(3),{humanReviewed:true});
  assert.ok(await x.session.guide());rejectFirst(new Error('Old playback failed'));
  assert.equal(await first,null);assert.equal(secondSignal.aborted,false);
  assert.equal(x.session.lastError,null);assert.equal(await x.session.guide(),null);
 } finally{x.session.stop();}
});

test('non-Error speech rejection still cancels output and permits retry',async()=>{
 for(const rejection of [undefined,null,'Audio unavailable']) {
  let calls=0,playing=false,firstSignal;
  const speech={
   cancel(){playing=false;},
   async speak(text,{signal}){playing=true;if(++calls===1){firstSignal=signal;throw rejection;}}
  };
  const x=setup(engine,'w',speech);
  try {
   assert.equal(await x.session.guide(),null);assert.equal(playing,false);
   assert.equal(firstSignal.aborted,true);assert.equal(x.session.lastError,'Live guidance failed.');
   assert.ok(await x.session.guide());assert.equal(calls,2);
   assert.equal(x.session.lastError,null);
  } finally{x.session.stop();}
 }
});
