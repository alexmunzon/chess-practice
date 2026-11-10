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
