import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { RecordedFrameQueue, MAX_RECORDED_FRAME_BYTES } from '../src/core/recorded-frame-queue.js';

const source = {sourceId:'saved-fixture', mode:'synthetic', sourceSha256:'a'.repeat(64)};
const flush = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve, reject; const promise = new Promise((a,b) => {resolve=a; reject=b;}); return {promise,resolve,reject}; };
const proposal = identity => ({status:'needs-human-review',fen:null,guidanceAllowed:false,sourceSha256:identity.frameSha256,squares:{a1:'unknown'}});

function setup(options={}) {
  let now=0; const calls=[];
  const queue = new RecordedFrameQueue({clock:()=>now, processor:(bytes,context)=>{
    const pending=deferred(); calls.push({bytes,context,...pending}); return pending.promise;
  },...options});
  let epoch=queue.connect(source).epoch;
  return {queue,calls,setTime:value=>{now=value;}, frame:(sequence,bytes=Buffer.from([sequence%256]))=>({sourceId:source.sourceId,epoch,sequence,capturedAt:now,bytes}), reconnect:descriptor=>{epoch=queue.connect(descriptor??source).epoch;return epoch;}};
}

test('offline queue keeps only one processor and one latest pending frame',async()=>{
  const x=setup();
  try {
    x.queue.offer(x.frame(0));
    for(let sequence=1;sequence<=100;sequence++){x.setTime(sequence);x.queue.offer(x.frame(sequence));}
    assert.equal(x.calls.length,1);assert.equal(x.queue.snapshot().pending.sequence,100);
    assert.equal(x.queue.snapshot().bufferedBytes,2);
    x.calls[0].resolve(proposal(x.calls[0].context.identity));await flush();
    assert.equal(x.queue.snapshot().proposal,null);assert.equal(x.calls.length,2);
    assert.equal(x.calls[1].context.identity.sequence,100);
    x.calls[1].resolve(proposal(x.calls[1].context.identity));await flush();
    const state=x.queue.snapshot();assert.equal(state.proposal.identity.sequence,100);
    assert.equal(state.proposal.identity.mode,'synthetic');assert.equal(state.proposal.identity.sourceSha256,source.sourceSha256);
    assert.equal(state.guidanceAllowed,false);assert.equal(state.reviewed,false);assert.equal(state.proposal.reviewed,false);
  } finally{x.queue.stop();}
});

test('new frames revoke old proposals and caller mutation cannot change queued bytes or snapshots',async()=>{
  const x=setup();
  try {
    const bytes=Buffer.from([1,2,3]);const digest=createHash('sha256').update(bytes).digest('hex');
    x.queue.offer(x.frame(0,bytes));bytes.fill(0);
    assert.deepEqual(x.calls[0].bytes,Buffer.from([1,2,3]));assert.equal(x.calls[0].context.identity.frameSha256,digest);
    assert.ok(Object.isFrozen(x.calls[0].context.identity));
    const result=proposal(x.calls[0].context.identity);x.calls[0].resolve(result);await flush();
    result.status='ready';const view=x.queue.snapshot();view.proposal.result.status='ready';view.source.mode='live';
    assert.equal(x.queue.snapshot().proposal.result.status,'needs-human-review');assert.equal(x.queue.snapshot().source.mode,'synthetic');
    x.setTime(10);x.queue.offer(x.frame(1));assert.equal(x.queue.snapshot().proposal,null);
  } finally{x.queue.stop();}
});

test('reconnect aborts but retains a noncooperative processor slot and ignores malformed old callbacks',async()=>{
  const x=setup();
  try {
    const old=x.frame(0);x.queue.offer(old);x.setTime(10);x.reconnect();
    assert.equal(x.calls[0].context.signal.aborted,true);x.queue.offer(x.frame(0));
    for(let sequence=1;sequence<=20;sequence++){x.setTime(10+sequence);x.queue.offer(x.frame(sequence));}
    const before=x.queue.snapshot();const ignored=x.queue.offer({epoch:old.epoch,bytes:null});
    assert.equal(ignored.ignored,'stale-session');assert.deepEqual(x.queue.snapshot(),before);
    assert.equal(x.calls.length,1);assert.equal(before.pending.sequence,20);assert.equal(before.status,'waiting-for-processor');
    x.calls[0].resolve(proposal(x.calls[0].context.identity));await flush();
    assert.equal(x.calls.length,2);assert.equal(x.queue.snapshot().proposal,null);
    x.calls[1].resolve(proposal(x.calls[1].context.identity));await flush();
    assert.equal(x.queue.snapshot().proposal.identity.epoch,before.epoch);
  } finally{x.queue.stop();}
});

test('stop clears pending input and late results; restarting never overlaps active work',async()=>{
  const x=setup();
  try {
    x.queue.offer(x.frame(0));x.setTime(10);x.queue.offer(x.frame(1));
    x.queue.stop();assert.equal(x.queue.snapshot().pending,null);assert.equal(x.calls[0].context.signal.aborted,true);
    x.reconnect();x.setTime(20);x.queue.offer(x.frame(0));assert.equal(x.calls.length,1);
    x.calls[0].reject(new Error('Old source failed'));await flush();assert.equal(x.calls.length,2);
    assert.equal(x.queue.snapshot().lastError,null);assert.equal(x.queue.snapshot().proposal,null);
    x.queue.stop();x.calls[1].resolve(proposal(x.calls[1].context.identity));await flush();
    assert.equal(x.queue.snapshot().proposal,null);assert.equal(x.queue.snapshot().status,'disconnected');
  } finally{x.queue.stop();}
});

test('synchronous abort callbacks cannot repopulate a stopped or reconnected queue',async()=>{
  for(const action of ['stop','reconnect']) {
    const x=setup();
    try {
      x.queue.offer(x.frame(0));x.setTime(10);const stale=x.frame(1);let callback;
      x.calls[0].context.signal.addEventListener('abort',()=>{callback=x.queue.offer(stale);},{once:true});
      if(action==='stop')x.queue.stop();else x.reconnect();
      assert.equal(callback.accepted,false);assert.equal(callback.ignored,'stale-session');
      assert.equal(x.queue.snapshot().pending,null);
      x.calls[0].resolve(proposal(x.calls[0].context.identity));await flush();
      assert.equal(x.calls.length,1);assert.equal(x.queue.snapshot().proposal,null);
    } finally{x.queue.stop();}
  }
});

test('freshness expires active and pending frames without starting stale work',async()=>{
  const x=setup({maxAgeMs:100});
  try {
    x.queue.offer(x.frame(0));x.setTime(10);x.queue.offer(x.frame(1));x.setTime(111);x.queue.tick();
    assert.equal(x.calls[0].context.signal.aborted,true);assert.equal(x.queue.snapshot().pending,null);
    x.calls[0].resolve(proposal(x.calls[0].context.identity));await flush();assert.equal(x.calls.length,1);assert.equal(x.queue.snapshot().proposal,null);
    x.queue.offer(x.frame(2));x.calls[1].resolve(proposal(x.calls[1].context.identity));await flush();
    assert.ok(x.queue.snapshot().proposal);x.setTime(212);assert.equal(x.queue.snapshot().proposal,null);
  } finally{x.queue.stop();}
});

test('watchdog aborts overdue processing without requiring a caller tick',async()=>{
  const x=setup({maxAgeMs:10,watchdogMs:1});
  try {x.queue.offer(x.frame(0));x.setTime(20);await new Promise(resolve=>setTimeout(resolve,15));assert.equal(x.calls[0].context.signal.aborted,true);assert.equal(x.calls.length,1);} finally{x.queue.stop();}
});

test('review-only result boundary rejects foreign bytes, confirmed state and oversized proposals',async()=>{
  for(const change of [p=>p.sourceSha256='b'.repeat(64),p=>p.fen='complete fen',p=>p.guidanceAllowed=true,p=>p.status='ready',p=>p.reviewed=true,p=>p.reviewed={pieces:true},p=>p.confirmation=true,p=>p.humanConfirmed=true,p=>p.extra='x'.repeat(256*1024),p=>p.toJSON=()=>({...p,status:'ready',toJSON:undefined})]) {
    const x=setup();
    try {x.queue.offer(x.frame(0));const p=proposal(x.calls[0].context.identity);change(p);x.calls[0].resolve(p);await flush();assert.equal(x.queue.snapshot().proposal,null);assert.equal(x.queue.snapshot().reason,'processor-error');} finally{x.queue.stop();}
  }
});

test('result serialization cannot publish after synchronous stop, reconnect or timeout',async()=>{
  for(const action of ['stop','reconnect','timeout']) {
    const x=setup();
    try {
      x.queue.offer(x.frame(0));const result=proposal(x.calls[0].context.identity);
      result.toJSON=()=>{
        if(action==='stop')x.queue.stop();
        else if(action==='reconnect')x.reconnect();
        else x.setTime(2000);
        return {...result,toJSON:undefined};
      };
      x.calls[0].resolve(result);await flush();
      assert.equal(x.queue.snapshot().proposal,null,action);
      assert.equal(x.queue.snapshot().guidanceAllowed,false,action);
    } finally{x.queue.stop();}
  }
});

test('a throwing clock revokes a published proposal and normalizes watchdog errors',async()=>{
  let clockThrows=false;
  const x=setup({clock:()=>{if(clockThrows)throw undefined;return 0;},watchdogMs:1});
  try {
    x.queue.offer(x.frame(0));x.calls[0].resolve(proposal(x.calls[0].context.identity));await flush();
    assert.ok(x.queue.snapshot().proposal);
    clockThrows=true;await new Promise(resolve=>setTimeout(resolve,15));
    assert.equal(x.queue.lastError,'Recorded frame clock failed.');
    clockThrows=false;const state=x.queue.snapshot();assert.equal(state.proposal,null);assert.equal(state.reason,'invalid-clock');
  } finally{x.queue.stop();}
});

test('a throwing clock aborts active work and its late result cannot publish',async()=>{
  let clockThrows=false;
  const x=setup({clock:()=>{if(clockThrows)throw null;return 0;}});
  try {
    x.queue.offer(x.frame(0));clockThrows=true;
    assert.throws(()=>x.queue.tick(),/clock failed/);assert.equal(x.calls[0].context.signal.aborted,true);
    clockThrows=false;x.calls[0].resolve(proposal(x.calls[0].context.identity));await flush();
    assert.equal(x.queue.snapshot().proposal,null);
  } finally{x.queue.stop();}
});

test('invalid current frames revoke proposals and reject unbounded bytes, future times and review flags',async()=>{
  for(const change of [f=>f.bytes=Buffer.alloc(MAX_RECORDED_FRAME_BYTES+1),f=>f.bytes=Buffer.alloc(0),f=>f.capturedAt=11,f=>f.capturedAt=NaN,f=>f.sourceId='different',f=>f.sequence=.5,f=>f.reviewed=true]) {
    const x=setup();
    try {x.queue.offer(x.frame(0));x.calls[0].resolve(proposal(x.calls[0].context.identity));await flush();x.setTime(10);const bad=x.frame(1);change(bad);assert.equal(x.queue.offer(bad).accepted,false);assert.equal(x.queue.snapshot().proposal,null);assert.equal(x.calls.length,1);} finally{x.queue.stop();}
  }
});

test('duplicates cannot establish freshness; backward clocks fail closed',async()=>{
  const x=setup({maxAgeMs:100});
  try {
    const initial=x.frame(0);x.queue.offer(initial);x.calls[0].resolve(proposal(x.calls[0].context.identity));await flush();
    x.setTime(90);assert.equal(x.queue.offer(initial).ignored,'repeated-or-reordered-frame');
    x.setTime(101);assert.equal(x.queue.snapshot().proposal,null);
    x.setTime(100);assert.throws(()=>x.queue.snapshot(),/monotonic/);
  } finally{x.queue.stop();}
});

test('offline source descriptors and configuration are explicit',()=>{
  const processor=async()=>null;
  for(const options of [{processor:null},{processor,maxAgeMs:0},{processor,watchdogMs:0}])assert.throws(()=>new RecordedFrameQueue(options));
  const queue=new RecordedFrameQueue({processor});
  try {
    for(const descriptor of [{sourceId:'x',mode:'live',sourceSha256:'a'.repeat(64)},{sourceId:'x',mode:'prerecorded'},{...source,sourceId:''}])assert.throws(()=>queue.connect(descriptor));
    const descriptor={...source,mode:'prerecorded'};queue.connect(descriptor);descriptor.mode='live';assert.equal(queue.snapshot().source.mode,'prerecorded');
  } finally{queue.stop();}
});

test('source descriptor getters are captured once before validation',()=>{
  const x=setup();let reads=0;
  try {
    x.queue.connect({sourceId:source.sourceId,sourceSha256:source.sourceSha256,get mode(){return ++reads===1?'prerecorded':'live';}});
    assert.equal(reads,1);assert.equal(x.queue.snapshot().source.mode,'prerecorded');
    assert.throws(()=>x.queue.connect({sourceId:source.sourceId,sourceSha256:source.sourceSha256,get mode(){x.queue.stop();return 'prerecorded';}}),/changed/);
    assert.equal(x.queue.snapshot().source,null);
  } finally{x.queue.stop();}
});

test('frame byte getter is captured once, so later values cannot bypass the byte limit',()=>{
  const x=setup();let reads=0;
  try {
    const small=Buffer.from([7]),large=Buffer.alloc(MAX_RECORDED_FRAME_BYTES+1);
    const frame=x.frame(0);Object.defineProperty(frame,'bytes',{enumerable:true,get(){return ++reads===1?small:large;}});
    assert.equal(x.queue.offer(frame).accepted,true);assert.equal(reads,1);
    assert.equal(x.calls[0].bytes.length,1);assert.equal(x.queue.snapshot().bufferedBytes,1);
  } finally{x.queue.stop();}
});

test('frame getters that stop or reconnect cannot enqueue after the source changes',()=>{
  for(const action of ['stop','reconnect','reconnect-then-throw']) {
    const x=setup();
    try {
      const frame=x.frame(0);
      Object.defineProperty(frame,'bytes',{enumerable:true,get(){
        if(action==='stop')x.queue.stop();else x.reconnect();
        if(action==='reconnect-then-throw')throw new Error('Old source getter');
        return Buffer.from([1]);
      }});
      const result=x.queue.offer(frame);
      assert.equal(result.accepted,false,action);assert.equal(result.ignored,'stale-session',action);
      assert.equal(x.calls.length,0);assert.equal(x.queue.snapshot().pending,null);
      assert.equal(x.queue.snapshot().bufferedBytes,0);assert.equal(x.queue.snapshot().lastError,null);
    } finally{x.queue.stop();}
  }
});

test('own byteLength cannot disguise an oversized typed array',()=>{
  const x=setup();
  try {
    const bytes=new Uint8Array(MAX_RECORDED_FRAME_BYTES+1);
    Object.defineProperty(bytes,'byteLength',{value:1});
    assert.equal(x.queue.offer(x.frame(0,bytes)).accepted,false);
    assert.equal(x.calls.length,0);assert.equal(x.queue.snapshot().bufferedBytes,0);
  } finally{x.queue.stop();}
});

test('typed-array copying never invokes an own length getter that could reorder frames',()=>{
  const x=setup();let lengthReads=0;
  try {
    x.queue.offer(x.frame(0));x.setTime(1);
    const bytes=new Uint8Array([1,2,3]);
    Object.defineProperty(bytes,'length',{get(){lengthReads++;x.setTime(2);x.queue.offer(x.frame(2));return 3;}});
    assert.equal(x.queue.offer(x.frame(1,bytes)).accepted,true);
    assert.equal(lengthReads,0);assert.equal(x.queue.snapshot().latestSequence,1);
    assert.equal(x.queue.snapshot().pending.sequence,1);assert.equal(x.queue.snapshot().bufferedBytes,4);
    x.setTime(2);assert.equal(x.queue.offer(x.frame(2)).accepted,true);
    assert.equal(x.queue.snapshot().latestSequence,2);assert.equal(x.queue.snapshot().pending.sequence,2);
  } finally{x.queue.stop();}
});
