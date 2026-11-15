import test from 'node:test';import assert from 'node:assert/strict';
import {positionPayload,loadPosition,movePosition,START_FEN} from '../src/core/position.js';
// Minimal local DOM harness exercises real app event handlers. It is not browser or vision evidence.
class Element {
 constructor(){this.listeners=new Map();this.children=[];this.dataset={};this.attrs={};this.value='';this.disabled=false;this.checked=false;this.hidden=false;this.textContent='';this.classes=new Set();this.classList={add:x=>this.classes.add(x),toggle:(x,on)=>on?this.classes.add(x):this.classes.delete(x)};}
 addEventListener(name,fn){this.listeners.set(name,fn);}fire(name,event={}){return this.listeners.get(name)?.(event);}replaceChildren(...children){this.children=[...children];}append(...children){this.children.push(...children);}setAttribute(k,v){this.attrs[k]=v;}removeAttribute(k){delete this.attrs[k];}focus(){}
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
test('real app move handlers block old-position guidance and recover from stale/error responses',async()=>{
 const originalDocument=globalThis.document,originalFetch=globalThis.fetch;
 const els=new Map(),get=id=>{if(!els.has(id))els.set(id,new Element());return els.get(id);};
 get('#promotion').value='q';get('#budget').value='500';const rights=[...'KQkq'].map(value=>Object.assign(new Element(),{value}));
 globalThis.document={querySelector:get,createElement:()=>new Element(),querySelectorAll:selector=>selector.includes(':checked')?rights.filter(el=>el.checked):rights,addEventListener(){},hidden:false};
 let pendingMove,analysisCalls=0;
 globalThis.fetch=async(path,options)=>{
  if(path==='/api/health')return {ok:true,json:async()=>({engine:'Test transport'})};
  const body=JSON.parse(options.body);
  if(path==='/api/position')return {ok:true,json:async()=>positionPayload(loadPosition(body.fen))};
  if(path==='/api/move'){pendingMove={...deferred(),body};return pendingMove.promise;}
  if(path==='/api/analyze'){analysisCalls++;throw Error('Unexpected analysis');}
  throw Error('Unknown path');
 };
 const square=s=>get('#board').children.find(el=>el.dataset.square===s);
 const beginMove=async()=>{await square('e2').fire('click');const p=square('e4').fire('click');await flush();return {done:p};};
 const response=body=>({ok:true,json:async()=>movePosition(body)});
 try{
  await import('../src/app.js?mutation-test');await flush();
  let move=await beginMove();assert.equal(get('#confirmed').disabled,true);assert.equal(get('#analyze').disabled,true);assert.equal(analysisCalls,0);
  pendingMove.resolve(response(pendingMove.body));await move.done;assert.equal(get('#confirmed').disabled,false);assert.equal(get('#confirmed').checked,false);assert.equal(get('#analyze').disabled,true);assert.match(get('#fen').value,/ b /);
  await get('#reset').fire('click');move=await beginMove();pendingMove.reject(new Error('Offline'));await move.done;assert.equal(get('#confirmed').disabled,false);assert.equal(get('#confirmed').checked,false);assert.equal(get('#analyze').disabled,true);assert.match(get('#status').textContent,/Move not applied: Offline/);assert.equal(get('#fen').value,START_FEN);
  move=await beginMove();const old=pendingMove;get('#fen').value='7k/5Q2/6K1/8/8/8/8/8 w - - 0 1';get('#fen').fire('input');await get('#load').fire('click');old.resolve(response(old.body));await move.done;assert.equal(get('#fen').value,'7k/5Q2/6K1/8/8/8/8/8 w - - 0 1');assert.equal(get('#confirmed').checked,false);assert.equal(analysisCalls,0);
 }finally{globalThis.document=originalDocument;globalThis.fetch=originalFetch;}
});
for(const [button,route,source] of [['#recognize','/api/recognize','real-image-inference'],['#recognize-simulation','/api/recognize-simulation','synthetic-pixel-inference']])test(`${source} proposals cannot survive source changes or bypass explicit board review`,async()=>{
 const oldDoc=globalThis.document,oldFetch=globalThis.fetch;
 const els=new Map(),get=id=>{if(!els.has(id))els.set(id,new Element());return els.get(id);};
 get('#promotion').value='q';get('#budget').value='500';const rights=[...'KQkq'].map(value=>Object.assign(new Element(),{value}));
 globalThis.document={querySelector:get,createElement:()=>new Element(),querySelectorAll:selector=>selector.includes(':checked')?rights.filter(x=>x.checked):rights,addEventListener(){},hidden:false};
 let recognition,loads=0;
 globalThis.fetch=async(path,options)=>{
  if(path==='/api/health')return {ok:true,json:async()=>({engine:'Test transport'})};
  if(path===route){recognition=deferred();return recognition.promise;}
  if(path==='/api/position'){loads++;return {ok:true,json:async()=>positionPayload(loadPosition(JSON.parse(options.body).fen))};}
  throw Error('Unexpected API '+path);
 };
 const image=new Blob(['test image only'],{type:'image/png'}),hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',await image.arrayBuffer()))].map(x=>x.toString(16).padStart(2,'0')).join('');
 const board=positionPayload(loadPosition(START_FEN)).board,squares={};
 for(let i=0;i<64;i++){const raw=board[Math.floor(i/8)][i%8]??'.';squares['abcdefgh'[i%8]+(8-Math.floor(i/8))]={rawLabel:raw,label:raw==='.'?'empty':raw,confidence:1};}
 const proposal={schemaVersion:1,source,status:'needs-human-review',fen:null,guidanceAllowed:false,sourceSha256:hash,imageSize:[64,64],rawPlacement:START_FEN.split(' ')[0],squares};
 try{
  await import('../src/app.js?photo-test='+source);await flush();
  get('#image-file').files=[image];await get('#image-file').fire('change');assert.equal(get(button).disabled,false);
  const pending=get(button).fire('click');await flush();get('#clear-image').fire('click');recognition.resolve({ok:true,json:async()=>proposal});await pending;assert.equal(get('#position-editor').hidden,true);assert.equal(get(button).disabled,true);
  get('#image-file').files=[image];await get('#image-file').fire('change');get('#recognition-file').files=[{size:100,text:async()=>JSON.stringify(proposal)}];await get('#recognition-file').fire('change');
  assert.equal(get('#position-editor').hidden,false);assert.equal(get('#editor-turn').value,'');assert.equal(get('#apply-editor').disabled,true);const before=loads;get('#apply-editor').fire('click');assert.equal(loads,before);
  assert.equal(get('#editor-ep').value,'');assert.equal(get('#editor-halfmove').value,'');assert.equal(get('#editor-fullmove').value,'');assert.equal(get('#editor-castling-known').checked,false);assert.ok(rights.every(x=>x.disabled));assert.equal(get('#fen').value,'');
  get('#proposal-reviewed').checked=true;get('#proposal-reviewed').fire('change');assert.equal(get('#apply-editor').disabled,true);
  await get('#apply-editor').fire('click');assert.equal(loads,before);
  for(const [id,value] of [['editor-turn','w'],['editor-ep','-'],['editor-halfmove','0'],['editor-fullmove','1']]){
   get('#'+id).value=value;get('#'+id).fire('input');
   get('#proposal-reviewed').checked=true;get('#proposal-reviewed').fire('change');assert.equal(get('#apply-editor').disabled,true);
  }
  // None is an explicit history choice, separate from merely leaving rights clear.
  get('#editor-castling-known').checked=true;get('#editor-castling-known').fire('change');
  assert.equal(get('#proposal-reviewed').checked,false);assert.equal(get('#apply-editor').disabled,true);
  assert.equal(get('#fen').value,START_FEN.replace('KQkq','-'));assert.equal(get('#load').disabled,true);
  await get('#load').fire('click');assert.equal(loads,before);
  get('#proposal-reviewed').checked=true;get('#proposal-reviewed').fire('change');assert.equal(get('#apply-editor').disabled,false);
  await get('#apply-editor').fire('click');assert.equal(loads,before+1);assert.equal(get('#confirmed').checked,false);assert.equal(get('#analyze').disabled,true);
  // Slow JSON reads cannot replace a reset or a newer import from the same photo.
  let read=deferred();get('#recognition-file').files=[{size:100,text:()=>read.promise}];let pendingImport=get('#recognition-file').fire('change');
  await get('#reset').fire('click');read.resolve(JSON.stringify(proposal));await pendingImport;
  assert.equal(get('#position-editor').hidden,true);assert.equal(get('#fen').value,START_FEN);
  read=deferred();get('#recognition-file').files=[{size:100,text:()=>read.promise}];pendingImport=get('#recognition-file').fire('change');
  get('#confirmed').checked=true;get('#confirmed').fire('change');read.resolve(JSON.stringify(proposal));await pendingImport;
  assert.equal(get('#position-editor').hidden,true);assert.equal(get('#confirmed').checked,true);assert.equal(get('#analyze').disabled,false);
  read=deferred();get('#recognition-file').files=[{size:100,text:()=>read.promise}];pendingImport=get('#recognition-file').fire('change');
  get('#recognition-file').files=[{size:100,text:async()=>JSON.stringify(proposal)}];await get('#recognition-file').fire('change');
  get('#editor-turn').value='b';get('#editor-turn').fire('input');read.resolve(JSON.stringify(proposal));await pendingImport;
  assert.equal(get('#editor-turn').value,'b');assert.equal(get('#apply-editor').disabled,true);
  get('#clear-image').fire('click');assert.equal(get('#position-editor').hidden,true);assert.equal(get('#confirmed').disabled,true);assert.equal(get('#analyze').disabled,true);
 }finally{globalThis.document=oldDoc;globalThis.fetch=oldFetch;}
});

test('manual photo handlers bind grid review, reject late replies and keep every history field unknown',async()=>{
 const oldDoc=globalThis.document,oldFetch=globalThis.fetch;
 const els=new Map(),get=id=>{if(!els.has(id))els.set(id,new Element());return els.get(id);};
 get('#promotion').value='q';get('#budget').value='500';const rights=[...'KQkq'].map(value=>Object.assign(new Element(),{value}));
 globalThis.document={querySelector:get,createElement:()=>new Element(),createElementNS:()=>new Element(),querySelectorAll:selector=>selector.includes(':checked')?rights.filter(x=>x.checked):rights,addEventListener(){},hidden:false};
 const calibrations=[],recognitions=[];let analysisCalls=0;
 globalThis.fetch=async(path,options)=>{
  if(path==='/api/health')return {ok:true,json:async()=>({engine:'Test transport'})};
  if(path==='/api/position')return {ok:true,json:async()=>positionPayload(loadPosition(JSON.parse(options.body).fen))};
  if(path==='/api/calibrate'||path==='/api/recognize'){
   const call={...deferred(),metadata:options.headers['X-Chess-Calibration']?JSON.parse(options.headers['X-Chess-Calibration']):null,options};
   (path==='/api/calibrate'?calibrations:recognitions).push(call);return call.promise;
  }
  if(path==='/api/analyze')analysisCalls++;
  throw Error('Unexpected API '+path);
 };
 const image=new Blob(['manual fixture only'],{type:'image/png'}),hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',await image.arrayBuffer()))].map(x=>x.toString(16).padStart(2,'0')).join('');
 const geometry=metadata=>({...metadata,schemaVersion:1,source:'manual-image-calibration',status:'needs-geometry-review',calibrationId:'c'.repeat(64),fen:null,guidanceAllowed:false,
  squares:Array.from({length:64},(_,i)=>{const r=Math.floor(i/8),c=i%8,x=10+c*10,y=10+r*10;const square=metadata.topLeftSquare==='h8'?'abcdefgh'[7-r]+(8-c):'abcdefgh'[c]+(8-r);return {square,sourcePolygon:[[x,y],[x+10,y],[x+10,y+10],[x,y+10]]};})});
 const board=positionPayload(loadPosition(START_FEN)).board;
 const proposal=()=>({schemaVersion:1,source:'real-image-inference',sourceSha256:hash,imageSize:[100,100],calibrationId:'c'.repeat(64),status:'needs-human-review',fen:null,guidanceAllowed:false,rawPlacement:START_FEN.split(' ')[0],
  squares:Object.fromEntries(Array.from({length:64},(_,i)=>{const raw=board[Math.floor(i/8)][i%8]??'.';return ['abcdefgh'[i%8]+(8-Math.floor(i/8)),{rawLabel:raw,label:raw==='.'?'empty':raw,confidence:.99}];}))});
 const finish=async(call,pending,result)=>{call.resolve({ok:true,json:async()=>result});await pending;};
 const prepare=async()=>{const pending=get('#calibrate').fire('click');await flush();const call=calibrations.at(-1);await finish(call,pending,geometry(call.metadata));};
 const confirmGrid=()=>{get('#geometry-reviewed').checked=true;get('#geometry-reviewed').fire('change');};
 try{
  await import('../src/app.js?manual-calibration-test');await flush();
  get('#image-file').files=[image];await get('#image-file').fire('change');
  assert.equal(get('#pick-corners').disabled,true);
  const photo=get('#reference-image');photo.naturalWidth=100;photo.naturalHeight=100;photo.getBoundingClientRect=()=>({left:0,top:0,width:100,height:100});photo.fire('load');
  assert.equal(get('#pick-corners').disabled,false);get('#pick-corners').fire('click');
  for(const [clientX,clientY]of [[10,10],[90,10],[90,90],[10,90]])photo.fire('click',{clientX,clientY});
  assert.equal(get('#calibration-tl-x').value,'10');assert.equal(get('#calibration-br-y').value,'90');assert.equal(get('#calibrate').disabled,true);
  get('#calibration-top-left').value='h8';get('#calibration-top-left').fire('change');assert.equal(get('#calibrate').disabled,false);
  let pending=get('#calibrate').fire('click');await flush();let call=calibrations.at(-1);
  assert.deepEqual(call.metadata,{sourceSha256:hash,imageSize:[100,100],corners:[[10,10],[90,10],[90,90],[10,90]],topLeftSquare:'h8',geometryReviewed:false});
  get('#calibration-tl-x').value='11';get('#calibration-tl-x').fire('input');assert.equal(call.options.signal.aborted,true);
  await finish(call,pending,geometry(call.metadata));assert.equal(get('#geometry-reviewed').disabled,true);assert.equal(get('#recognize-calibrated').disabled,true);
  get('#calibration-tl-x').value='10';get('#calibration-tl-x').fire('input');await prepare();
  assert.equal(get('#geometry-reviewed').checked,false);assert.equal(get('#recognize-calibrated').disabled,true);
  assert.equal(get('#calibration-overlay').children.filter(el=>el.attrs.class==='calibration-cell').length,64);
  assert.equal(get('#calibration-overlay').children.find(el=>el.attrs.class==='calibration-square-label').textContent,'h8');
  confirmGrid();assert.equal(get('#recognize-calibrated').disabled,false);assert.equal(get('#confirmed').checked,false);
  pending=get('#recognize-calibrated').fire('click');await flush();call=recognitions.at(-1);
  assert.equal(call.metadata.geometryReviewed,true);assert.equal(call.metadata.calibrationId,'c'.repeat(64));assert.equal(call.metadata.topLeftSquare,'h8');
  assert.deepEqual(call.metadata.corners,[[10,10],[90,10],[90,90],[10,90]]);
  // Revoking the geometry review cancels pending inference and rejects its late result.
  get('#geometry-reviewed').checked=false;get('#geometry-reviewed').fire('change');assert.equal(call.options.signal.aborted,true);
  await finish(call,pending,proposal());assert.equal(get('#position-editor').hidden,true);
  confirmGrid();pending=get('#recognize-calibrated').fire('click');await flush();call=recognitions.at(-1);
  get('#calibration-top-left').value='a8';get('#calibration-top-left').fire('change');await finish(call,pending,proposal());
  assert.equal(get('#position-editor').hidden,true);assert.equal(get('#geometry-reviewed').disabled,true);
  await prepare();confirmGrid();pending=get('#recognize-calibrated').fire('click');await flush();call=recognitions.at(-1);await finish(call,pending,proposal());
  assert.equal(get('#position-editor').hidden,false);assert.equal(get('#editor-turn').value,'');assert.equal(get('#editor-ep').value,'');
  assert.equal(get('#editor-halfmove').value,'');assert.equal(get('#editor-fullmove').value,'');assert.equal(get('#editor-castling-known').checked,false);
  assert.equal(get('#apply-editor').disabled,true);assert.equal(get('#confirmed').checked,false);assert.equal(get('#analyze').disabled,true);assert.equal(analysisCalls,0);
  get('#calibration-tl-x').value='12';get('#calibration-tl-x').fire('input');assert.equal(get('#position-editor').hidden,true);assert.equal(get('#fen').value,'');assert.equal(get('#geometry-reviewed').checked,false);
  // A new source cannot receive an old grid preview, even if its request resolves successfully.
  pending=get('#calibrate').fire('click');await flush();call=calibrations.at(-1);get('#clear-image').fire('click');await finish(call,pending,geometry(call.metadata));
  assert.equal(get('#geometry-reviewed').disabled,true);assert.equal(get('#calibration-overlay').children.length,0);
  // Existing whole-photo recognition remains header-free.
  get('#image-file').files=[image];await get('#image-file').fire('change');pending=get('#recognize').fire('click');await flush();call=recognitions.at(-1);assert.equal(call.metadata,null);get('#clear-image').fire('click');await finish(call,pending,proposal());
 }finally{globalThis.document=oldDoc;globalThis.fetch=oldFetch;}
});

let lifecycleImports=0;
async function manualLifecycleHarness(t){
 const original={document:globalThis.document,fetch:globalThis.fetch,speechSynthesis:globalThis.speechSynthesis};
 t.after(()=>Object.assign(globalThis,original));
 const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
 const rights=[...'KQkq'].map(value=>Object.assign(new Element(),{value})),listeners=new Map();
 const doc={querySelector:get,createElement:()=>new Element(),createElementNS:()=>new Element(),querySelectorAll:selector=>selector.includes(':checked')?rights.filter(x=>x.checked):rights,
  addEventListener(name,listener){listeners.set(name,listener);},hidden:false};
 let speechCancels=0;globalThis.document=doc;globalThis.speechSynthesis={cancel(){speechCancels++;}};
 get('#promotion').value='q';get('#budget').value='500';
 const calls=[];
 globalThis.fetch=async(path,options)=>{
  if(path==='/api/health')return {ok:true,json:async()=>({engine:'Mock transport'})};
  if(path==='/api/position')return {ok:true,json:async()=>positionPayload(loadPosition(JSON.parse(options.body).fen))};
  if(path==='/api/analyze'){
   const request=JSON.parse(options.body);
   return {ok:true,json:async()=>({...request,bestMove:{from:'e2',to:'e4',san:'e4'},speechText:'pawn from e2 to e4.',analysis:{depth:1,elapsedMs:1,pv:[]}})};
  }
  if(path==='/api/calibrate'||path==='/api/recognize'){
   const call={...deferred(),path,options,metadata:JSON.parse(options.headers['X-Chess-Calibration'])};calls.push(call);return call.promise;
  }
  throw Error('Unexpected API '+path);
 };
 await import('../src/app.js?manual-lifecycle-'+(++lifecycleImports));await flush();
 assert.equal(typeof listeners.get('visibilitychange'),'function');
 const image=new Blob(['lifecycle fixture only'],{type:'image/png'});
 const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',await image.arrayBuffer()))].map(x=>x.toString(16).padStart(2,'0')).join('');
 get('#image-file').files=[image];await get('#image-file').fire('change');
 get('#reference-image').naturalWidth=100;get('#reference-image').naturalHeight=100;get('#reference-image').fire('load');
 for(const [corner,point]of Object.entries({tl:[10,10],tr:[90,10],br:[90,90],bl:[10,90]}))for(const [i,axis]of ['x','y'].entries()){
  get('#calibration-'+corner+'-'+axis).value=String(point[i]);get('#calibration-'+corner+'-'+axis).fire('input');
 }
 get('#calibration-top-left').value='a8';get('#calibration-top-left').fire('change');
 const geometry=(metadata,calibrationId='c'.repeat(64))=>({...metadata,schemaVersion:1,source:'manual-image-calibration',status:'needs-geometry-review',calibrationId,fen:null,guidanceAllowed:false,
  squares:Array.from({length:64},(_,i)=>{const x=10+i%8*10,y=10+Math.floor(i/8)*10;return {square:'abcdefgh'[i%8]+(8-Math.floor(i/8)),sourcePolygon:[[x,y],[x+10,y],[x+10,y+10],[x,y+10]]};})});
 const board=positionPayload(loadPosition(START_FEN)).board;
 const proposal=calibrationId=>({schemaVersion:1,source:'real-image-inference',sourceSha256:hash,imageSize:[100,100],calibrationId,status:'needs-human-review',fen:null,guidanceAllowed:false,rawPlacement:START_FEN.split(' ')[0],
  squares:Object.fromEntries(Array.from({length:64},(_,i)=>{const raw=board[Math.floor(i/8)][i%8]??'.';return ['abcdefgh'[i%8]+(8-Math.floor(i/8)),{rawLabel:raw,label:raw==='.'?'empty':raw,confidence:.99}];}))});
 const start=async id=>{const count=calls.length,promise=get(id).fire('click');await flush();assert.equal(calls.length,count+1);return {promise,call:calls.at(-1)};};
 const finish=async(job,result)=>{job.call.resolve({ok:true,json:async()=>result});await job.promise;};
 const prepare=async()=>{const job=await start('#calibrate');await finish(job,geometry(job.call.metadata));};
 const confirm=()=>{get('#geometry-reviewed').checked=true;get('#geometry-reviewed').fire('change');};
 const hide=()=>{doc.hidden=true;listeners.get('visibilitychange')();};
 const show=()=>{doc.hidden=false;listeners.get('visibilitychange')();};
 const revoked=()=>{assert.equal(get('#confirmed').checked,false);assert.equal(get('#analyze').disabled,true);assert.equal(get('#speak').disabled,true);assert.equal(get('#geometry-reviewed').checked,false);};
 return {get,geometry,proposal,start,finish,prepare,confirm,hide,show,revoked,speechCancels:()=>speechCancels};
}

test('visibility events revoke pending calibration, recognition, accepted proposals and analysis',async t=>{
 const h=await manualLifecycleHarness(t);
 let job=await h.start('#calibrate'),before=h.speechCancels();h.hide();
 assert.equal(job.call.options.signal.aborted,true);assert.ok(h.speechCancels()>before);h.revoked();
 await h.finish(job,h.geometry(job.call.metadata));assert.equal(h.get('#geometry-reviewed').disabled,true);assert.equal(h.get('#position-editor').hidden,true);
 h.show();await h.prepare();h.confirm();job=await h.start('#recognize-calibrated');h.hide();
 assert.equal(job.call.options.signal.aborted,true);h.revoked();
 await h.finish(job,h.proposal(job.call.metadata.calibrationId));assert.equal(h.get('#position-editor').hidden,true);
 h.show();h.confirm();job=await h.start('#recognize-calibrated');await h.finish(job,h.proposal(job.call.metadata.calibrationId));
 assert.equal(h.get('#position-editor').hidden,false);h.hide();h.revoked();assert.equal(h.get('#apply-editor').disabled,true);
 h.show();
 for(const [id,value]of [['editor-turn','w'],['editor-ep','-'],['editor-halfmove','0'],['editor-fullmove','1']]){h.get('#'+id).value=value;h.get('#'+id).fire('input');}
 h.get('#editor-castling-known').checked=true;h.get('#editor-castling-known').fire('change');
 h.get('#proposal-reviewed').checked=true;h.get('#proposal-reviewed').fire('change');await h.get('#apply-editor').fire('click');
 h.get('#confirmed').checked=true;h.get('#confirmed').fire('change');await h.get('#analyze').fire('click');
 assert.equal(h.get('#speak').disabled,false);assert.ok(h.get('#analysis').children.length>0);
 before=h.speechCancels();h.hide();h.revoked();assert.ok(h.speechCancels()>before);
 assert.equal(h.get('#analysis').children.length,0);assert.ok(h.get('#board').children.every(square=>!square.classes.has('suggestion')));
});

test('reset during pending manual calibration or recognition discards late replies',async t=>{
 const h=await manualLifecycleHarness(t);
 for(const phase of ['calibration','recognition']){
  if(phase==='recognition'){await h.prepare();h.confirm();}
  const job=await h.start(phase==='calibration'?'#calibrate':'#recognize-calibrated');
  await h.get('#reset').fire('click');assert.equal(job.call.options.signal.aborted,true);h.revoked();
  await h.finish(job,phase==='calibration'?h.geometry(job.call.metadata):h.proposal(job.call.metadata.calibrationId));
  assert.equal(h.get('#fen').value,START_FEN);assert.equal(h.get('#position-editor').hidden,true);h.revoked();
 }
});

test('a superseded preview cannot replace a newer grid or revoke its explicit review',async t=>{
 const h=await manualLifecycleHarness(t),old=await h.start('#calibrate');
 await h.get('#reset').fire('click');assert.equal(old.call.options.signal.aborted,true);
 const current=await h.start('#calibrate'),newId='d'.repeat(64);
 await h.finish(current,h.geometry(current.call.metadata,newId));h.confirm();
 const status=h.get('#status').textContent;
 await h.finish(old,h.geometry(old.call.metadata));
 assert.equal(h.get('#geometry-reviewed').checked,true);assert.equal(h.get('#recognize-calibrated').disabled,false);assert.equal(h.get('#status').textContent,status);
 const recognition=await h.start('#recognize-calibrated');assert.equal(recognition.call.metadata.calibrationId,newId);
 await h.get('#reset').fire('click');await h.finish(recognition,h.proposal(newId));h.revoked();
});
