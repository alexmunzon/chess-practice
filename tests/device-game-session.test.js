import test from 'node:test';
import assert from 'node:assert/strict';
import {Chess} from 'chess.js';
import {DeviceGameSession} from '../src/core/device-game-session.js';
import {SQUARES} from '../src/core/observation.js';
import {START_FEN} from '../src/core/position.js';

// Explicit review fixtures and labeled observations test the real rules tracker.
// These tests do not simulate a human action, run vision or authorize device output.
const reviewed = {pieces:true,turn:true,castling:true,enPassant:true,counters:true};
const squares = fen => {
  const chess = new Chess(fen);
  return Object.fromEntries(SQUARES.map(square => {
    const piece = chess.get(square);
    return [square, {label:piece ? (piece.color === 'w' ? piece.type.toUpperCase() : piece.type) : 'empty', confidence:1}];
  }));
};
const fullFen = chess => chess.fen({forceEnpassantSquare:true});

function rig() {
  const clockDomain = 'replay-clock-test';
  let now = 100, requestNumber = 0, sequence = 0;
  const identity = {sessionId:'recorded-test',epoch:1};
  const bridge = new DeviceGameSession({replayClock:{clockDomain,now:()=>now}});
  const command = (kind, payload = {}, patch = {}) => JSON.stringify({schemaVersion:1,
    requestId:`request-${++requestNumber}`,kind,mode:'trusted-replay',clockDomain,...payload,...patch});
  const handle = (kind, payload = {}, patch = {}) => bridge.handle(command(kind,payload,patch));
  const initialize = (fen = START_FEN) => handle('initialize',{session:{...identity},fen,reviewed:{...reviewed}});
  const snapshot = () => handle('snapshot',{session:{...identity}});
  const frame = (fen = START_FEN, patch = {}) => ({identity:{...identity,sequence:sequence++,frameSha256:sequence.toString(16).padStart(64,'0')},
    capturedAtMs:now,squares:squares(fen),...patch});
  const observe = (fen = START_FEN) => handle('observe',{frame:frame(fen)});
  const stable = (fen = START_FEN) => {const first=observe(fen);now+=60;return {first,second:observe(fen)};};
  return {bridge,clockDomain,identity,command,handle,initialize,snapshot,frame,observe,stable,
    advance:delta=>{now+=delta;},setTime:value=>{now=value;},getTime:()=>now};
}

test('complete initial review and two actual observations establish replay tracking, never output permission',()=>{
  const r=rig();
  assert.throws(()=>r.observe(),{code:'INITIALIZATION_REQUIRED'});
  const initialized=r.initialize();assert.equal(initialized.trackingReady,false);
  const {first,second}=r.stable();
  assert.equal(first.trackingReady,false);assert.equal(second.trackingReady,true);
  assert.equal(second.mode,'replay-only');assert.equal(second.guidanceAllowed,false);assert.equal(second.liveGuidanceAllowed,false);
  assert.equal(second.state.fen,START_FEN);assert.equal(second.state.historyComplete,false);
  assert.equal(second.lastFrame.sequence,2);assert.equal(second.lastFrame.frameSha256.length,64);
  second.lastFrame.frameSha256='modified';second.session.epoch=999;
  assert.notEqual(r.snapshot().lastFrame.frameSha256,'modified');assert.equal(r.snapshot().session.epoch,1);
});

test('same-board freshness and unique legal transitions preserve supplied history and require stability',()=>{
  const r=rig(),chess=new Chess();r.initialize();r.stable();
  const readyRevision=r.snapshot().state.revision;
  r.advance(800);const same=r.observe();assert.equal(same.trackingReady,true);assert.equal(same.state.revision,readyRevision);
  r.advance(500);assert.equal(r.snapshot().trackingReady,true);
  chess.move('e4');r.advance(1);let pair=r.stable(fullFen(chess));
  assert.equal(pair.first.trackingReady,false);assert.equal(pair.second.trackingReady,true);
  assert.equal(pair.second.state.fen,fullFen(chess));assert.equal(pair.second.state.lastMove.san,'e4');
  chess.move('c5');r.advance(1);pair=r.stable(fullFen(chess));
  assert.equal(pair.second.state.fen,fullFen(chess));assert.equal(pair.second.state.lastMove.san,'c5');
  r.advance(1001);assert.equal(r.snapshot().trackingReady,false);
  assert.equal(r.snapshot().state.reason,'observation-timeout');assert.equal(r.observe(fullFen(chess)).trackingReady,false);
});

test('real rules track castling, en passant, promotion, counters and repetition without claiming prior history',()=>{
  const fixtures=[
    ['r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 7 12',['O-O','O-O-O']],
    ['4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2',['exd6']],
    ['7k/P7/8/8/8/8/8/7K w - - 0 1',[{from:'a7',to:'a8',promotion:'n'}]],
    [START_FEN,['Nf3','Nf6','Ng1','Ng8','Nf3','Nf6','Ng1','Ng8']]
  ];
  for(const [initial,moves] of fixtures){
    const r=rig(),chess=new Chess(initial);r.initialize(initial);r.stable(initial);
    for(const move of moves){chess.move(move);r.advance(60);const result=r.stable(fullFen(chess)).second;
      assert.equal(result.trackingReady,true);assert.equal(result.state.fen,fullFen(chess));
      assert.equal(result.state.historyComplete,false);assert.equal(result.guidanceAllowed,false);
    }
  }
});

test('unknown cells and skipped plies require a new independent full-state review',()=>{
  for(const mode of ['unknown','skipped']){
    const r=rig();r.initialize();r.stable();r.advance(60);
    const chess=new Chess();chess.move('e4');chess.move('e5');
    let input=r.frame(mode==='skipped'?fullFen(chess):START_FEN);
    if(mode==='unknown')input.squares.a8={label:'unknown',confidence:0};
    const blocked=r.handle('observe',{frame:input});assert.equal(blocked.trackingReady,false);
    assert.equal(blocked.state.reason,mode==='unknown'?'uncertain-squares':'not-zero-or-one-legal-move');
    r.advance(60);assert.equal(r.stable().second.trackingReady,false);
    r.initialize();r.advance(60);assert.equal(r.stable().second.trackingReady,true);
  }
});

test('session epochs, old callbacks and immutable sequence/hash/time identities fail closed',()=>{
  const r=rig();r.initialize();r.stable();
  r.identity.epoch=2;r.identity.sessionId='replacement';r.initialize();r.advance(60);r.stable();
  const ready=r.snapshot();const old=r.frame();old.identity={sessionId:'recorded-test',epoch:1,sequence:999,frameSha256:'a'.repeat(64)};
  const ignored=r.handle('observe',{frame:old});assert.equal(ignored.ignored,'stale-session');
  assert.equal(ignored.trackingReady,true);assert.deepEqual(ignored.lastFrame,ready.lastFrame);
  assert.throws(()=>r.handle('initialize',{session:{sessionId:'recorded-test',epoch:1},fen:START_FEN,reviewed}),{code:'STALE_IDENTITY'});
  assert.equal(r.snapshot().trackingReady,false);
  r.initialize();r.advance(60);const input=r.frame();r.handle('observe',{frame:input});
  const duplicate=r.handle('observe',{frame:input});assert.equal(duplicate.ignored,'repeated-or-reordered-frame');
  for(const patch of [{frameSha256:'b'.repeat(64)},{capturedAtMs:input.capturedAtMs+1}]){
    const altered=structuredClone(input);
    if(patch.frameSha256)altered.identity.frameSha256=patch.frameSha256;else altered.capturedAtMs=patch.capturedAtMs;
    assert.throws(()=>r.handle('observe',{frame:altered}),{code:'FRAME_IDENTITY_CONFLICT'});
    assert.equal(r.snapshot().trackingReady,false);
  }
});

test('all explicit invalidation reasons require review; snapshots and reordered frames cannot renew freshness',()=>{
  for(const reason of ['manual-edit','interrupted','background','reset','disconnect']){
    const r=rig();r.initialize();const old=r.frame();r.handle('observe',{frame:old});r.advance(60);r.observe();
    r.advance(900);assert.equal(r.handle('observe',{frame:old}).ignored,'repeated-or-reordered-frame');
    r.advance(101);assert.equal(r.snapshot().trackingReady,false);
    r.initialize();r.advance(1);r.stable();
    const result=r.handle('invalidate',{session:{...r.identity},reason});assert.equal(result.invalidationReason,reason);
    assert.equal(result.trackingReady,false);r.advance(60);assert.equal(r.observe().trackingReady,false);
  }
});

test('review time starts freshness; drafts need no clock lease, and observations from before review do not stabilize',()=>{
  const r=rig();r.setTime(60_000);r.initialize();
  const preReview=r.frame(START_FEN,{capturedAtMs:59_950});
  assert.equal(r.handle('observe',{frame:preReview}).ignored,'before-confirmation');
  assert.equal(r.stable().second.trackingReady,true);
  r.advance(1001);r.snapshot();
  assert.throws(()=>r.handle('initialize',{session:{...r.identity},fen:START_FEN,reviewed:{...reviewed,counters:false}}),{code:'CONFIRMATION_REQUIRED'});
  r.advance(30_000);r.initialize();assert.equal(r.stable().second.trackingReady,true);
});

test('exact JSON rejects missing history, weak review, extra fields and DAT/receipt-clock shortcuts',()=>{
  const r=rig();r.initialize();r.stable();
  const invalid=[
    'null','[]','{','x'.repeat(16385),r.command('__proto__'),r.command('constructor'),
    r.command('initialize',{session:r.identity,fen:START_FEN.split(' ')[0],reviewed}),
    r.command('initialize',{session:r.identity,fen:START_FEN,reviewed:{...reviewed,pieces:false}}),
    r.command('initialize',{session:r.identity,fen:START_FEN,reviewed:{...reviewed,automatic:true}}),
    r.command('observe',{frame:r.frame()},{mode:'DAT'}),
    r.command('observe',{frame:r.frame()},{clockDomain:'media-PTS'}),
    r.command('observe',{frame:{...r.frame(),receivedAtHostSeconds:100}}),
    r.command('observe',{frame:{...r.frame(),mediaPTS:{value:100,timescale:1000}}}),
    r.command('observe',{frame:{...r.frame(),capturedAtMs:'100'}}),
    r.command('snapshot',{session:r.identity,fen:START_FEN})
  ];
  for(const value of invalid){assert.throws(()=>r.bridge.handle(value));assert.equal(r.snapshot().trackingReady,false);}
  for(const patch of [{sequence:-1},{sequence:1.5},{epoch:0},{frameSha256:'wrong'},{sessionId:''}]){
    const frame=r.frame();Object.assign(frame.identity,patch);assert.throws(()=>r.handle('observe',{frame}));
  }
  const frame=r.frame();delete frame.squares.a8;assert.throws(()=>r.handle('observe',{frame}));
});

test('future, stale or invalid replay clocks cannot preserve readiness',()=>{
  for(const kind of ['future','stale','backwards','nan','string']){
    const r=rig();r.initialize();r.stable();
    if(kind==='future'||kind==='stale'){
      const frame=r.frame(START_FEN,{capturedAtMs:kind==='future'?r.getTime()+1:0});
      if(kind==='stale')r.advance(1001);
      assert.equal(r.handle('observe',{frame}).trackingReady,false);
    }else{
      r.setTime(kind==='backwards'?0:kind==='nan'?NaN:'200');
      assert.throws(()=>r.snapshot(),{code:'INVALID_CLOCK'});
      r.setTime(1000);assert.equal(r.snapshot().trackingReady,false);
    }
  }
  assert.throws(()=>new DeviceGameSession());
  assert.throws(()=>new DeviceGameSession({replayClock:{clockDomain:'x'}}));
});

test('clock-provider reentry revokes the outer operation even if the provider catches the nested error',()=>{
  let bridge,reenter=false,nestedError;
  const envelope={schemaVersion:1,requestId:'reentry',mode:'trusted-replay',clockDomain:'test-clock'};
  const session={sessionId:'test-session',epoch:1};
  const provider={clockDomain:'test-clock',now(){
    if(reenter){reenter=false;try{bridge.handle(JSON.stringify({...envelope,kind:'snapshot',session}));}catch(error){nestedError=error;}}
    return 100;
  }};
  bridge=new DeviceGameSession({replayClock:provider});
  const initialize=JSON.stringify({...envelope,kind:'initialize',session,fen:START_FEN,reviewed});
  bridge.handle(initialize);reenter=true;
  assert.throws(()=>bridge.handle(initialize),{code:'ABORTED'});assert.equal(nestedError.code,'ABORTED');
  const snapshot=bridge.handle(JSON.stringify({...envelope,kind:'snapshot',session}));
  assert.equal(snapshot.trackingReady,false);assert.equal(snapshot.state.reason,'manual-edit');
});
