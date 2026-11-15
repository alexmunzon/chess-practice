import test from 'node:test';
import http from 'node:http';
import assert from 'node:assert/strict';
import {createServer} from '../src/server.js';
import {START_FEN} from '../src/core/position.js';
import {EngineError} from '../src/core/engine.js';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {mkdtemp,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {parseRecognitionDraft} from '../src/recognition-draft.js';
import {draftFen} from '../src/position-draft.js';
import {calibrationId} from '../src/core/photo-calibration.js';
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
test('HTTP real Stockfish result echoes identity and normalized position',async t=>{const {post}=await fixture(t);const res=await post('/api/analyze',{fen:START_FEN,confirmation:true,requestId:'live-api',movetimeMs:100});assert.equal(res.status,200);const result=await res.json();assert.equal(result.requestId,'live-api');assert.equal(result.fen,START_FEN);assert.ok(result.bestMove.san);assert.match(result.speechText, /[a-h][1-8]|Castle/);assert.ok(result.analysis.depth>0);assert.equal(result.analysis.scorePerspective,'side-to-move');});
test('image route limits types, sizes and requires review-only outputs',async t=>{
 let calls=0;const proposal={source:'real-image-inference',status:'needs-human-review',fen:null,guidanceAllowed:false};
 const {base}=await fixture(t,{recognizer:async bytes=>{calls++;assert.equal(bytes.toString(),'image-bytes');return proposal;}});
 const post=(body,type='image/jpeg')=>fetch(base+'/api/recognize',{method:'POST',headers:{'content-type':type},body});
 assert.equal((await post('image-bytes','text/plain')).status,415);assert.equal(calls,0);
 assert.equal((await post('')).status,400);assert.equal(calls,0);
 assert.equal((await post(Buffer.alloc(8*1024*1024+1))).status,413);assert.equal(calls,0);
 const valid=await post('image-bytes');assert.equal(valid.status,200);assert.deepEqual(await valid.json(),proposal);assert.equal(calls,1);
 assert.equal((await fetch(base+'/api/recognize',{method:'POST',headers:{'content-type':'image/jpeg',origin:'https://other.example'},body:'image-bytes'})).status,403);
 const other=await fixture(t,{recognizer:async()=>({...proposal,guidanceAllowed:true})});assert.equal((await fetch(other.base+'/api/recognize',{method:'POST',headers:{'content-type':'image/png'},body:'image-bytes'})).status,400);
});
test('recognition cancels on position change and rejects a stale noncooperative recognizer result',async t=>{
 let finish,start,signal;const started=new Promise(r=>start=r);
 const {base,post}=await fixture(t,{recognizer:(_,{signal:s})=>new Promise(r=>{finish=r;signal=s;start();})});
 const pending=fetch(base+'/api/recognize',{method:'POST',headers:{'content-type':'image/jpeg'},body:'image-bytes'});await started;await post('/api/position',{fen:START_FEN});assert.ok(signal.aborted);finish({source:'real-image-inference',status:'needs-human-review',fen:null,guidanceAllowed:false});assert.equal((await pending).status,409);
});

function calibrationRequest(){return {sourceSha256:createHash('sha256').update('image-bytes').digest('hex'),imageSize:[400,400],corners:[[0,0],[400,0],[400,400],[0,400]],topLeftSquare:'a8',geometryReviewed:false};}
function calibrationPreview(request){return {schemaVersion:1,source:'manual-image-calibration',sourceSha256:request.sourceSha256,imageSize:request.imageSize,corners:request.corners,topLeftSquare:request.topLeftSquare,calibrationId:calibrationId(request),status:'needs-geometry-review',fen:null,guidanceAllowed:false,squares:Array.from({length:64},(_,i)=>{const x=i%8*50,y=Math.floor(i/8)*50;return {square:'abcdefgh'[i%8]+(8-Math.floor(i/8)),sourcePolygon:[[x,y],[x+50,y],[x+50,y+50],[x,y+50]]};})};}
const photoPost=(base,path,metadata,body='image-bytes')=>fetch(base+path,{method:'POST',headers:{'content-type':'image/jpeg',...(metadata===undefined?{}:{'x-chess-calibration':JSON.stringify(metadata)})},body});

test('manual grid preview is bound to image bytes and explicit unreviewed geometry',async t=>{
 let calls=0;const {base}=await fixture(t,{calibrator:async(bytes,{calibration})=>{calls++;assert.equal(bytes.toString(),'image-bytes');return calibrationPreview(calibration);}});
 const request=calibrationRequest();const valid=await photoPost(base,'/api/calibrate',request);assert.equal(valid.status,200);assert.equal((await valid.json()).status,'needs-geometry-review');assert.equal(calls,1);
 for(const bad of [undefined,{...request,sourceSha256:'a'.repeat(64)},{...request,geometryReviewed:true},{...request,threshold:.5},{...request,corners:request.corners.slice(1).concat([request.corners[0]])}])assert.equal((await photoPost(base,'/api/calibrate',bad)).status,400);
 assert.equal((await photoPost(base,'/api/calibrate',request,'different-image')).status,400);assert.equal(calls,1);
 const unsafe=await fixture(t,{calibrator:async()=>({...calibrationPreview(request),guidanceAllowed:true})});assert.equal((await photoPost(unsafe.base,'/api/calibrate',request)).status,400);
});

test('manual recognition requires the exact reviewed geometry and remains a piece draft',async t=>{
 let calls=0;const {base}=await fixture(t,{recognizer:async(bytes,{calibration})=>{calls++;return {source:'real-image-inference',sourceSha256:calibration.sourceSha256,calibrationId:calibration.calibrationId,status:'needs-human-review',fen:null,guidanceAllowed:false};}});
 const request=calibrationRequest();assert.equal((await photoPost(base,'/api/recognize',request)).status,400);assert.equal(calls,0);
 const reviewed={...request,geometryReviewed:true,calibrationId:calibrationId(request)};
 assert.equal((await photoPost(base,'/api/recognize',{...reviewed,topLeftSquare:'h8'})).status,400);assert.equal(calls,0);
 const result=await photoPost(base,'/api/recognize',reviewed);assert.equal(result.status,200);assert.equal((await result.json()).fen,null);assert.equal(calls,1);
 const foreign=await fixture(t,{recognizer:async()=>({source:'real-image-inference',sourceSha256:request.sourceSha256,calibrationId:'a'.repeat(64),status:'needs-human-review',fen:null,guidanceAllowed:false})});assert.equal((await photoPost(foreign.base,'/api/recognize',reviewed)).status,400);
});

test('new position cancels a pending grid preview and suppresses late noncooperative output',async t=>{
 let release,start,signal;const ready=new Promise(r=>start=r);const request=calibrationRequest();
 const {base,post}=await fixture(t,{calibrator:(_,{signal:s})=>new Promise(r=>{release=r;signal=s;start();})});
 const pending=photoPost(base,'/api/calibrate',request);await ready;await post('/api/position',{fen:START_FEN});assert.equal(signal.aborted,true);
 release(calibrationPreview(request));const result=await pending;assert.equal(result.status,409);assert.equal((await result.json()).squares,undefined);
});

test('synthetic pixel route is separate, review-only, pixel-only and cancellable',async t=>{
 const proposal={source:'synthetic-pixel-inference',status:'needs-human-review',fen:null,guidanceAllowed:false};
 let calls=0,release,start,signal;const ready=new Promise(r=>start=r);
 const {base,post}=await fixture(t,{recognizer:()=>assert.fail('physical recognizer must not run'),simulationRecognizer:(bytes,{signal:s,...options})=>{
  calls++;assert.equal(bytes.toString(),'image-bytes');assert.deepEqual(options,{});signal=s;start();return new Promise(r=>release=r);
 }});
 assert.equal((await photoPost(base,'/api/recognize-simulation',{fen:START_FEN})).status,400);assert.equal(calls,0);
 const pending=photoPost(base,'/api/recognize-simulation');await ready;await post('/api/cancel',{});assert.equal(signal.aborted,true);release(proposal);assert.equal((await pending).status,409);
 const okay=await fixture(t,{simulationRecognizer:async()=>proposal});const response=await photoPost(okay.base,'/api/recognize-simulation');assert.equal(response.status,200);assert.deepEqual(await response.json(),proposal);
 for(const patch of [{source:'real-image-inference'},{guidanceAllowed:true},{fen:START_FEN}]){
  const unsafe=await fixture(t,{simulationRecognizer:async()=>({...proposal,...patch})});assert.equal((await photoPost(unsafe.base,'/api/recognize-simulation')).status,400);
 }
});

test('actual synthetic pixels through HTTP stay unreviewed before local Stockfish and speech text',async t=>{
 const directory=await mkdtemp(join(tmpdir(),'synthetic-http-'));t.after(()=>rm(directory,{recursive:true,force:true}));
 const file=join(directory,'pixels.png'),renderer=fileURLToPath(new URL('../scripts/simulation/render.py',import.meta.url));
 // Truth belongs only to this renderer/test fixture. The HTTP recognizer receives raw bytes.
 const render=spawnSync('python3',['-B',renderer],{input:JSON.stringify({fen:START_FEN,scene:{},output:file}),encoding:'utf8',timeout:30_000});
 assert.equal(render.status,0,render.stderr);
 const bytes=await readFile(file),hash=createHash('sha256').update(bytes).digest('hex');
 const {base,post}=await fixture(t);
 const response=await fetch(base+'/api/recognize-simulation',{method:'POST',headers:{'content-type':'image/png'},body:bytes});
 assert.equal(response.status,200);const proposal=await response.json();
 assert.equal(proposal.rawPlacement,START_FEN.split(' ')[0]);assert.equal(proposal.unknownSquares,0);
 const {draft,notice}=parseRecognitionDraft(JSON.stringify(proposal),hash);assert.match(notice,/Synthetic/);
 assert.throws(()=>draftFen(draft));assert.equal(draft.turn,'');assert.equal(draft.ep,'');assert.equal(draft.castling,'');
 assert.equal((await post('/api/analyze',{fen:START_FEN,requestId:'unreviewed-pixels',movetimeMs:50})).status,400);
 // Explicit automated reviewer fixture supplies history; this is not a human/device test.
 const reviewedFen=draftFen({...draft,turn:'w',castling:'KQkq',ep:'-',halfmove:0,fullmove:1});
 const position=await post('/api/position',{fen:reviewedFen});assert.equal(position.status,200);
 const analysis=await post('/api/analyze',{fen:reviewedFen,requestId:'reviewed-simulation-fixture',confirmation:true,movetimeMs:50});
 assert.equal(analysis.status,200);const result=await analysis.json();assert.equal(result.fen,reviewedFen);assert.ok(result.bestMove?.san);assert.ok(result.speechText);
});
