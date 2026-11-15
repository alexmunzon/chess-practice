import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {EventEmitter} from 'node:events';
import {PassThrough} from 'node:stream';
import {mkdtemp,readdir,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createPhotoRecognizer} from '../src/core/photo-recognizer.js';
import {calibrationId,parseCalibrationHeader,validateCalibrationRequest,validateCalibrationPreview,MANUAL_MODEL_HASHES,MANUAL_MODEL_REVISION} from '../src/core/photo-calibration.js';

const png=Buffer.from([137,80,78,71,13,10,26,10]);
const request=()=>({sourceSha256:createHash('sha256').update(png).digest('hex'),imageSize:[640,480],corners:[[80,40],[560,40],[560,440],[80,440]],topLeftSquare:'a8',geometryReviewed:false});
const reviewed=()=>{const r=request();return {...r,geometryReviewed:true,calibrationId:calibrationId(r)};};
function preview(r=request()) {
  return {schemaVersion:1,source:'manual-image-calibration',sourceSha256:r.sourceSha256,imageSize:r.imageSize,corners:r.corners,topLeftSquare:r.topLeftSquare,
    calibrationId:calibrationId(r),status:'needs-geometry-review',fen:null,guidanceAllowed:false,
    squares:Array.from({length:64},(_,i)=>{const x=80+(i%8)*60,y=40+Math.floor(i/8)*50;return {square:'abcdefgh'[i%8]+(8-Math.floor(i/8)),sourcePolygon:[[x,y],[x+60,y],[x+60,y+50],[x,y+50]]};})};
}
function proposal(r=reviewed()) {
  return {schemaVersion:1,source:'real-image-inference',sourceSha256:r.sourceSha256,imageSize:r.imageSize,status:'needs-human-review',fen:null,guidanceAllowed:false,
    model:'cstr/chess-board-photo-onnx',modelRevision:MANUAL_MODEL_REVISION,pipelineVersion:'image-order-crops-v1',modelHashes:MANUAL_MODEL_HASHES,
    topLeftSquare:r.topLeftSquare,calibrationId:r.calibrationId,geometryHumanReviewed:true,elapsedMs:100,threshold:.95,rawPlacement:'8/8/8/8/8/8/8/8',
    squares:Object.fromEntries(Array.from({length:64},(_,i)=>['abcdefgh'[i%8]+(8-Math.floor(i/8)),{rawLabel:'.',label:'empty',confidence:.99}]))};
}
async function harness(t,behavior) {
  const root=await mkdtemp(join(tmpdir(),'manual-photo-test-'));t.after(()=>rm(root,{recursive:true,force:true}));const calls=[];
  const recognize=createPhotoRecognizer({tempRoot:root,timeoutMs:1000,spawnProcess(command,args,options){
    const child=new EventEmitter();child.stdout=new PassThrough();child.stderr=new PassThrough();let closed=false;
    child.close=code=>{if(!closed){closed=true;child.emit('close',code);}};
    child.kill=()=>{child.killed=true;setImmediate(()=>child.close(null));return true;};calls.push({command,args,options,child});
    setImmediate(()=>Promise.resolve(behavior(child,args,options)).catch(e=>{child.stderr.write(String(e));child.close(1);}));return child;
  }});return {recognize,calls,clean:async()=>assert.deepEqual(await readdir(root),[])};
}

test('calibration review binds exact bytes, corners, dimensions and orientation',()=>{
  const r=reviewed();assert.deepEqual(validateCalibrationRequest(r,{digest:r.sourceSha256,reviewed:true}),r);
  for(const change of [x=>x.sourceSha256='0'.repeat(64),x=>x.imageSize[0]++,x=>x.corners[0][0]++,x=>x.topLeftSquare='h8',x=>x.geometryReviewed=false]) {
    const x=structuredClone(r);change(x);assert.throws(()=>validateCalibrationRequest(x,{digest:r.sourceSha256,reviewed:true}));
  }
  const a=request();a.corners[0][0]=-0;const b=structuredClone(a);b.corners[0][0]=0;assert.equal(calibrationId(a),calibrationId(b));
});

test('header rejects ambiguous, oversized, rotated, invalid and unreviewed geometry',()=>{
  for(const header of ['', '[]','null','x'.repeat(4097)])assert.throws(()=>parseCalibrationHeader(header));
  for(const change of [x=>x.orientation='guessed',x=>delete x.topLeftSquare,x=>x.corners.push([1,1]),x=>x.corners[0][0]=NaN,
    x=>x.imageSize=[8000,8000],x=>x.corners=x.corners.slice(1).concat([x.corners[0]]),x=>x.corners[0]=[1000,0],x=>x.geometryReviewed=true]) {
    const r=request();change(r);assert.throws(()=>validateCalibrationRequest(r));
  }
  assert.throws(()=>parseCalibrationHeader(JSON.stringify(request()),{reviewed:true}));
  assert.throws(()=>parseCalibrationHeader(JSON.stringify({...request(),calibrationId:'a'.repeat(64)})));
});

test('preview response cannot substitute another grid or assert trusted game state',()=>{
  assert.equal(validateCalibrationPreview(preview(),request()).squares.length,64);
  for(const change of [x=>x.guidanceAllowed=true,x=>x.fen='anything',x=>x.humanReviewed=true,x=>x.calibrationId='a'.repeat(64),
    x=>x.corners[0][0]++,x=>x.squares.pop(),x=>x.squares[1].square='a8',x=>x.squares[0].sourcePolygon[0][0]=-1]) {
    const p=preview();change(p);assert.throws(()=>validateCalibrationPreview(p,request()));
  }
});

test('preview and manual recognition use fixed bridge commands and private captured metadata',async t=>{
  let expected=request();
  const h=await harness(t,async(child,args)=>{
    assert.match(args[1],/manual_photo\.py$/);assert.ok(['preview','recognize'].includes(args[2]));assert.deepEqual(await readFile(args[3]),png);
    const saved=JSON.parse(await readFile(args[4],'utf8'));assert.deepEqual(saved,expected);
    child.stdout.write(JSON.stringify(args[2]==='preview'?preview(saved):proposal(saved)));child.close(0);
  });
  const mutable=request(),job=h.recognize.calibrate(png,{calibration:mutable});mutable.corners[0][0]=999;
  const grid=await job;assert.equal(grid.guidanceAllowed,false);await h.clean();
  expected=reviewed();const p=await h.recognize(png,{calibration:expected});assert.equal(p.fen,null);assert.equal(p.status,'needs-human-review');assert.equal(p.geometryHumanReviewed,true);await h.clean();
});

test('both modes share active job exclusion and abort/cleanup lifecycle',async t=>{
  let start;const ready=new Promise(r=>start=r);const h=await harness(t,()=>start());const controller=new AbortController();
  const job=h.recognize.calibrate(png,{signal:controller.signal,calibration:request()});const rejected=assert.rejects(job,e=>e.code==='ABORTED');
  await ready;await assert.rejects(h.recognize(png),e=>e.code==='BUSY');await assert.rejects(h.recognize(png,{calibration:reviewed()}),e=>e.code==='BUSY');
  controller.abort();await rejected;assert.equal(h.calls[0].child.killed,true);await h.clean();
});

test('manual bridge rejects a stale calibration before spawn and invalid model claims after return',async t=>{
  const h=await harness(t,()=>assert.fail('must not spawn'));
  await assert.rejects(h.recognize(png,{calibration:request()}));await assert.rejects(h.recognize.calibrate(png,{calibration:reviewed()}));
  const mismatch=reviewed();mismatch.sourceSha256='0'.repeat(64);await assert.rejects(h.recognize(png,{calibration:mismatch}));assert.equal(h.calls.length,0);await h.clean();
  for(const change of [p=>p.calibrationId='0'.repeat(64),p=>p.modelHashes={},p=>p.model='different',p=>p.geometryHumanReviewed=false,p=>p.humanReviewed=true,p=>p.guidanceAllowed=true]) {
    const other=await harness(t,child=>{const p=proposal();change(p);child.stdout.write(JSON.stringify(p));child.close(0);});
    await assert.rejects(other.recognize(png,{calibration:reviewed()}),e=>e.code==='INVALID_RESULT');await other.clean();
  }
});

test('synthetic recognizer receives opaque pixels only, shares cancellation and cannot claim trusted state',async t=>{
  const synthetic=()=>({...proposal(),source:'synthetic-pixel-inference',model:'synthetic-screen-template-v1',pipelineVersion:'visible-markers-v1',limitations:['Synthetic template domain only.']});
  const h=await harness(t,async(child,args)=>{
    assert.equal(args.length,3);assert.match(args[1],/scripts\/simulation\/recognize\.py$/);assert.deepEqual(await readFile(args[2]),png);
    child.stdout.write(JSON.stringify(synthetic()));child.close(0);
  });
  const result=await h.recognize.simulation(png,{fen:'must never enter the child',scene:{seed:42}});
  assert.equal(result.fen,null);assert.equal(result.guidanceAllowed,false);await h.clean();
  for(const patch of [{source:'real-image-inference'},{humanReviewed:true},{guidanceAllowed:true},{model:'other'},{elapsedMs:-1}]) {
    const invalid=await harness(t,child=>{child.stdout.write(JSON.stringify({...synthetic(),...patch}));child.close(0);});
    await assert.rejects(invalid.recognize.simulation(png),e=>e.code==='INVALID_RESULT');await invalid.clean();
  }
  let start;const ready=new Promise(r=>start=r),controller=new AbortController();const pending=await harness(t,()=>start());
  const job=pending.recognize.simulation(png,{signal:controller.signal});const rejected=assert.rejects(job,e=>e.code==='ABORTED');await ready;
  await assert.rejects(pending.recognize(png),e=>e.code==='BUSY');controller.abort();await rejected;await pending.clean();
});
