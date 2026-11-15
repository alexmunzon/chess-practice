// The BUILT phone runtime bundle routes replay-tracker and engine requests through
// runtime.js's own router. Node only: no WebKit, Worker, WASM engine or network.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,rm} from 'node:fs/promises';
import {join,resolve,dirname} from 'node:path';
import {tmpdir} from 'node:os';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {buildDeviceRuntime} from '../scripts/build-device-runtime.mjs';

const ROOT=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const START='rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
const transcript=JSON.parse(await readFile(join(ROOT,'tests/fixtures/replay-runtime/transcript.json'),'utf8'));

// Build once into a temporary directory and import the built modules, not src/.
const dir=await mkdtemp(join(tmpdir(),'replay-runtime-bundle-test-'));
const built=await buildDeviceRuntime(join(dir,'bundle'));
const modules=name=>import(pathToFileURL(join(built.outputDirectory,name)));
// Minimal stand-ins for the WebKit page globals runtime.js touches at load time.
const posted=[];
globalThis.webkit={messageHandlers:{chessRuntime:{postMessage:text=>posted.push(JSON.parse(text))}}};
if (typeof globalThis.addEventListener!=='function') globalThis.addEventListener=()=>{};
const runtime=await modules('runtime.js');
const {ReplayRuntime}=await modules('core/replay-runtime.js');
const {DeviceBackend}=await modules('core/device-backend.js');
test.after(()=>rm(dir,{recursive:true,force:true}));

const identity={sessionId:'bundle-check',epoch:1,sequence:1,frameSha256:'a'.repeat(64),revision:1};
const engineCommand=(kind,extra={})=>JSON.stringify({schemaVersion:1,requestId:'engine-'+kind,kind,...extra});
function spy(target){
 const calls=[];
 return {calls,handle:text=>{let kind='unparsed';try{kind=JSON.parse(text).kind;}catch{}calls.push(kind);return target.handle(text);},cancel:()=>{calls.push('cancel()');target.cancel?.();}};
}

test('built runtime.js refuses to start outside the chess-local bundle scheme',async()=>{
 assert.equal(posted.length,1);
 assert.equal(posted[0].kind,'fatal');assert.match(posted[0].error,/Local engine resource required/);
 // After a fatal start every request (tracker or engine) is refused, as before.
 await globalThis.chessDeviceRuntime.submit(JSON.stringify(transcript[0].request),'transport-1');
 assert.deepEqual(posted[1],{protocolVersion:1,kind:'reply',transportId:'transport-1',ok:false,error:{code:'RUNTIME_ERROR',message:'Local runtime is not ready.'}});
});

test('golden replay transcript through the built router equals the frozen replies',async()=>{
 const engine=spy(new DeviceBackend({analyzer:()=>assert.fail('tracker traffic must never reach the engine')}));
 const tracker=new ReplayRuntime(),trackerKinds=[];
 const route=runtime.createRequestRouter({engine,tracker:{handle:text=>{trackerKinds.push(JSON.parse(text).kind);return tracker.handle(text);}}});
 assert.equal(transcript.length,28);
 for(const [index,step] of transcript.entries()){
  const reply=await route(JSON.stringify(step.request));
  assert.deepEqual(reply,step.reply,'step '+(index+1));
  assert.equal(JSON.stringify(reply),JSON.stringify(step.reply),'byte-identical reply at step '+(index+1));
 }
 assert.deepEqual(trackerKinds,transcript.map(step=>step.request.kind));
 // Every tracker request cancelled engine work first; the engine never handled one.
 assert.deepEqual(engine.calls,transcript.map(()=>'cancel()'));
});

test('engine requests still reach only the engine backend, unchanged',async()=>{
 const backend=new DeviceBackend({analyzer:async input=>({requestId:input.requestId,fen:input.fen,bestMove:{from:'e2',to:'e4'}})});
 const engine=spy(backend),trackerCalls=[];
 const route=runtime.createRequestRouter({engine,tracker:{handle:text=>{trackerCalls.push(text);return '{}';}}});
 const position=await route(engineCommand('position',{fen:START}));
 assert.equal(position.position.legalMoves.length,20);assert.equal(position.runtime,'on-device-local');
 const move=await route(engineCommand('move',{fen:START,move:{from:'e2',to:'e4'}}));
 assert.equal(move.speechText,'pawn from e2 to e4.');
 const analysis=await route(engineCommand('analyze',{fen:START,confirmation:true,movetimeMs:100,identity}));
 assert.equal(analysis.bestMove.san,'e4');assert.deepEqual(analysis.identity,identity);
 assert.deepEqual(await route(engineCommand('cancel')),{schemaVersion:1,requestId:'engine-cancel',kind:'cancel',runtime:'on-device-local',cancelled:true});
 // Malformed or unknown engine traffic is rejected by the engine backend exactly as before.
 await assert.rejects(route('{not json'),/Malformed command JSON/);
 await assert.rejects(route(engineCommand('validate',{fen:START})),/Unsupported command/);
 assert.deepEqual(engine.calls,['position','move','analyze','cancel','unparsed','validate']);
 assert.deepEqual(trackerCalls,[]);
 backend.close();
});

test('a tracker request cancels in-flight analysis and the two never overlap',async()=>{
 let started,aborted=false;const analyzing=new Promise(resolve=>{started=resolve;});
 const backend=new DeviceBackend({analyzer:(input,{signal})=>new Promise((_,reject)=>{
  started();signal.addEventListener('abort',()=>{aborted=true;reject(new Error('aborted'));});
 })});
 const tracker=new ReplayRuntime();
 const route=runtime.createRequestRouter({engine:backend,tracker:{handle:text=>{
  assert.ok(aborted,'analysis is aborted before the tracker runs');return tracker.handle(text);
 }}});
 const pending=route(engineCommand('analyze',{fen:START,confirmation:true,movetimeMs:3000,identity}));
 const settled=pending.then(()=>assert.fail('superseded analysis must not resolve'),error=>error);
 await analyzing;assert.equal(aborted,false);
 const reply=await route(JSON.stringify(transcript[0].request));
 assert.deepEqual(reply,transcript[0].reply);
 assert.match((await settled).message,/aborted/,'superseded analysis rejects instead of replying');
 backend.close();
});

test('tracker-shaped traffic never reaches the engine, even when malformed',async()=>{
 const engine=spy(new DeviceBackend({analyzer:()=>assert.fail('no analysis')})),tracker=new ReplayRuntime();
 const route=runtime.createRequestRouter({engine,tracker});
 for(const request of [
  {...transcript[0].request,mode:'engine'},             // tracker kind, wrong mode
  {...transcript[25].request,extra:true},               // tracker kind, extra key
  {schemaVersion:1,requestId:'r',kind:'position',mode:'trusted-replay',fen:START}, // engine kind claiming replay mode
 ]){
  const reply=await route(JSON.stringify(request));
  assert.equal(reply.error.trackerRevoked,true);assert.equal(reply.guidanceAllowed,false);assert.equal(reply.mode,'replay-only');
 }
 assert.ok(engine.calls.every(call=>call==='cancel()'));
 assert.equal(runtime.isTrackerCommand('x'.repeat(16385)),false);
 assert.throws(()=>runtime.createRequestRouter({engine:{handle(){}},tracker}),/required/);
});
