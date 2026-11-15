import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import {Chess} from 'chess.js';
import {buildDefinition,generate,squaresFromFen} from '../scripts/simulation/generate.mjs';

const ROOT=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');

test('frozen synthetic corpus uses legal sequences, repeated states and explicit split limits',()=>{
  const definition=buildDefinition();
  assert.deepEqual(definition,buildDefinition());
  assert.equal(definition.frames.length,78);
  assert.equal(definition.protocol.frozenBeforeScoring,true);
  assert.deepEqual(definition.protocol.seeds,{dev:101729,heldout:408923,challenge:900617});
  for(const session of definition.sessions){
    const chess=new Chess(session.initialFen),frames=definition.frames.filter(frame=>frame.session===session.id);
    assert.equal(frames.length,(session.moves.length+1)*2);
    for(let ply=0;ply<=session.moves.length;ply++){
      if(ply)chess.move(session.moves[ply-1]);
      const [first,second]=frames.slice(ply*2,ply*2+2);
      assert.equal(first.fen,chess.fen());assert.equal(second.fen,chess.fen());
      assert.deepEqual(first.squares,squaresFromFen(chess.fen()));
      assert.deepEqual(first.scene,second.scene);
      assert.equal(first.threefoldRepetition,chess.isThreefoldRepetition());
    }
  }
  definition.frames.forEach((frame,index)=>{
    assert.equal(frame.id,String(index).padStart(6,'0'));
    assert.equal(frame.file,`${frame.id}.png`);
    assert.equal(frame.timestampMs,index*100);
    assert.equal(frame.expectedAbstention,frame.split==='challenge');
  });
  const dev=definition.sessions.find(x=>x.id==='dev-opening'),held=definition.sessions.find(x=>x.id==='heldout-opening');
  assert.notDeepEqual(dev.moves,held.moves);
  assert.equal(dev.initialFen,held.initialFen); // Deliberately not position-disjoint.
  assert.ok(definition.frames.filter(x=>x.split==='heldout').every(x=>x.scene.style==='classic'));
});

test('special fixtures exercise castling, en passant, promotion and repetition history',()=>{
  const {frames,sessions}=buildDefinition();
  const changed=id=>frames.filter(frame=>frame.session===id&&frame.repeat===0&&frame.move);
  assert.deepEqual(changed('fixture-castling').map(x=>x.move.san),['O-O','O-O-O']);
  assert.ok(changed('fixture-en-passant')[0].move.flags.includes('e'));
  assert.equal(changed('fixture-promotion')[0].move.promotion,'q');
  assert.equal(changed('fixture-repetition').at(-1).threefoldRepetition,true);
  assert.equal(sessions.find(x=>x.id==='fixture-repetition').historyKnownFromInitial,true);
  for(const [one,two] of [['metadata-castling-rights','metadata-no-castling-rights'],['metadata-en-passant','metadata-no-en-passant']]){
    const a=frames.find(x=>x.session===one),b=frames.find(x=>x.session===two);
    assert.equal(a.fen.split(' ')[0],b.fen.split(' ')[0]);
    assert.notEqual(a.fen,b.fen);
    assert.deepEqual(a.scene,b.scene);
    assert.deepEqual(a.squares,b.squares);
  }
});

test('renderer emits deterministic RGB pixels without hidden FEN or text metadata',async()=>{
  const directory=await mkdtemp(path.join(tmpdir(),'chess-simulation-render-test-'));
  try{
    const definition=buildDefinition(),first=definition.frames[0],changed=definition.frames[2];
    const outputs=['one.png','same.png','changed.png'].map(file=>path.join(directory,file));
    const request={renders:[{fen:first.fen,scene:{},output:outputs[0]},
      {fen:first.fen,scene:{},output:outputs[1]},{fen:changed.fen,scene:{},output:outputs[2]}]};
    const run=spawnSync('python3',['-B',path.join(ROOT,'scripts/simulation/render.py')],{input:JSON.stringify(request),encoding:'utf8',timeout:20_000});
    assert.equal(run.status,0,run.stderr);
    const [one,same,different]=await Promise.all(outputs.map(file=>readFile(file)));
    assert.deepEqual(one,same);assert.notDeepEqual(one,different);
    const chunks=[];let offset=8;
    while(offset<one.length){const size=one.readUInt32BE(offset);chunks.push(one.toString('ascii',offset+4,offset+8));offset+=12+size;}
    assert.deepEqual([...new Set(chunks)].sort(),['IDAT','IEND','IHDR']);
    assert.equal(one.readUInt32BE(16),768);assert.equal(one.readUInt32BE(20),768);
    assert.equal(one[25],2); // RGB, not indexed colors with embedded labels.
    assert.equal(JSON.parse(run.stdout).length,3);
  }finally{await rm(directory,{recursive:true,force:true});}
});

test('generator rejects repository media output without creating files',async()=>{
  await assert.rejects(generate(path.join(ROOT,'simulation-test-output')),/outside the source repository/);
});
