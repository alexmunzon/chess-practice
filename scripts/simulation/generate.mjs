#!/usr/bin/env node
/** Generate separate synthetic pixels and evaluator truth, never recognizer labels. */
import {Chess} from 'chess.js';
import {mkdir, readdir, readFile, writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const HERE=path.dirname(fileURLToPath(import.meta.url));
const ROOT=path.resolve(HERE,'../..');
export const FROZEN_PROTOCOL=Object.freeze({version:'synthetic-board-v1',frozenBeforeScoring:true,
  seeds:{dev:101729,heldout:408923,challenge:900617},
  limits:['Synthetic vector pieces and colored board markers; not a physical-board or glasses test.',
    'Held-out sequences and scenes use the same known classic template style as development.',
    'Opening sessions share their initial position; this is not a position-disjoint split.',
    'Perspective changes occur between positions: stepped camera motion, not continuous real head motion.',
    'Metadata fixtures explicitly supply synthetic history; pixels do not establish turn, rights, counters or repetition.']});

function random(seed) {let value=seed>>>0;return()=>{value=(1664525*value+1013904223)>>>0;return value/4294967296;};}
function sceneStream(seed,heldout=false) {
  const next=random(seed);
  return()=>({style:'classic',quad:[[50+Math.round(next()*35),55+Math.round(next()*30)],
    [687+Math.round(next()*30),45+Math.round(next()*35)],[687+Math.round(next()*30),689+Math.round(next()*29)],
    [45+Math.round(next()*35),681+Math.round(next()*36)]],
    brightness:Number((heldout?.88+next()*.20:.96+next()*.08).toFixed(4)),
    blur:heldout?.35:.1,boardVariation:heldout});
}
export function squaresFromFen(fen) {
  const chess=new Chess(fen), squares={};
  for (let rank=8;rank>=1;rank--) for (const file of 'abcdefgh') {
    const square=file+rank,piece=chess.get(square);
    squares[square]=piece?(piece.color==='w'?piece.type.toUpperCase():piece.type):'.';
  }
  return squares;
}

export function buildDefinition() {
  const sessions=[],frames=[];
  const devScene=sceneStream(FROZEN_PROTOCOL.seeds.dev),heldScene=sceneStream(FROZEN_PROTOCOL.seeds.heldout,true);
  function session(id,split,initialFen,moves,sceneForState,expectedAbstention=false) {
    const chess=new Chess(initialFen),states=[{fen:chess.fen(),move:null,threefoldRepetition:false}];
    for(const san of moves){const move=chess.move(san);states.push({fen:chess.fen(),threefoldRepetition:chess.isThreefoldRepetition(),move:{san:move.san,from:move.from,to:move.to,promotion:move.promotion??null,flags:move.flags}});}
    const historyKnownFromInitial=states[0].fen===new Chess().fen();
    sessions.push({id,split,initialFen:states[0].fen,moves:[...moves],
      historyDescription:historyKnownFromInitial?'Synthetic new game; every move from the initial position is listed.':'Explicit synthetic fixture at session start; prior repetition history is unknown. Subsequent listed moves are legal chess.js moves.',
      historyKnownFromInitial,
      initialStateSource:'synthetic-test-fixture',humanReviewed:false});
    states.forEach((state,ply)=>{
      const scene=sceneForState(ply);
      for(let repeat=0;repeat<2;repeat++){
        const number=frames.length;
        frames.push({id:String(number).padStart(6,'0'),file:`${String(number).padStart(6,'0')}.png`,
          timestampMs:number*100,split,session:id,ply,repeat,fen:state.fen,
          squares:squaresFromFen(state.fen),move:state.move,threefoldRepetition:state.threefoldRepetition,scene,expectedAbstention});
      }
    });
  }
  const initial=new Chess().fen();
  session('dev-opening','dev',initial,['e4','e5','Nf3','Nc6','Bc4','Nf6'],devScene);
  session('heldout-opening','heldout',initial,['d4','d5','c4','e6','Nc3','Nf6'],heldScene);
  const castle='r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1';
  const ep='4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2';
  session('fixture-castling','dev',castle,['O-O','O-O-O'],devScene);
  session('fixture-en-passant','dev',ep,['exd6'],devScene);
  session('fixture-promotion','dev','4k3/P7/8/8/8/8/8/4K3 w - - 0 1',['a8=Q+'],devScene);
  session('fixture-repetition','dev',initial,['Nf3','Nf6','Ng1','Ng8','Nf3','Nf6','Ng1','Ng8'],devScene);
  const identicalCastleScene=devScene(),identicalEpScene=devScene();
  session('metadata-castling-rights','dev',castle,[],()=>identicalCastleScene);
  session('metadata-no-castling-rights','dev','r3k2r/8/8/8/8/8/8/R3K2R w - - 17 25',[],()=>identicalCastleScene);
  session('metadata-en-passant','dev',ep,[],()=>identicalEpScene);
  session('metadata-no-en-passant','dev','4k3/8/8/3pP3/8/8/8/4K3 w - - 8 14',[],()=>identicalEpScene);
  const challengeScene=sceneStream(FROZEN_PROTOCOL.seeds.challenge);
  session('challenge-occlusion','challenge',initial,[],()=>({...challengeScene(),occlusions:[{box:[210,90,390,300],color:[149,111,88]}]}),true);
  session('challenge-missing-marker','challenge',initial,[],()=>({...challengeScene(),occlusions:[{box:[10,10,54,54],color:[184,190,193]}]}),true);
  session('challenge-unfamiliar','challenge',initial,[],()=>({...challengeScene(),style:'unfamiliar'}),true);
  session('challenge-glare','challenge',initial,[],()=>({...challengeScene(),occlusions:[{box:[120,80,350,190],color:[255,255,255]}]}),true);
  session('challenge-severe-blur','challenge',initial,[],()=>({...challengeScene(),blur:6}),true);
  return {schemaVersion:1,mode:'synthetic-evaluator-truth',protocol:FROZEN_PROTOCOL,sessions,frames};
}

export async function generate(out,{video=false}={}) {
  out=path.resolve(out);
  if(out===ROOT||out.startsWith(ROOT+path.sep))throw new Error('Generated media must stay outside the source repository.');
  await mkdir(out,{recursive:true});
  if((await readdir(out)).length)throw new Error('Output directory must be empty; existing artifacts are preserved.');
  const pixels=path.join(out,'pixels'),evaluator=path.join(out,'evaluator');
  await mkdir(pixels);await mkdir(evaluator);
  const definition=buildDefinition();
  const job={renders:definition.frames.map(frame=>({fen:frame.fen,scene:frame.scene,output:path.join(pixels,frame.file)}))};
  const run=spawnSync('python3',['-B',path.join(HERE,'render.py')],{input:JSON.stringify(job),encoding:'utf8',maxBuffer:16*1024*1024,timeout:60_000});
  if(run.error||run.status!==0)throw new Error(`Synthetic renderer failed: ${run.error?.message??run.stderr}`);
  const rendered=JSON.parse(run.stdout);
  if(rendered.length!==definition.frames.length)throw new Error('Renderer frame count mismatch.');
  definition.frames.forEach((frame,index)=>Object.assign(frame,rendered[index]));
  const index={schemaVersion:1,mode:'synthetic-pixels',frames:definition.frames.map(({id,file,timestampMs})=>({id,file,timestampMs}))};
  if(video){
    const videoPath=path.join(pixels,'sequence.mp4');
    const result=spawnSync('/usr/local/bin/ffmpeg',['-hide_banner','-loglevel','error','-nostdin','-framerate','10','-start_number','0',
      '-i',path.join(pixels,'%06d.png'),'-frames:v',String(definition.frames.length),'-c:v','libx264','-pix_fmt','yuv420p',
      '-map_metadata','-1',videoPath],{encoding:'utf8',timeout:120_000});
    if(result.error||result.status!==0)throw new Error(`Optional video encoding failed: ${result.error?.message??result.stderr}`);
    index.video={file:'sequence.mp4',fps:10,frameCount:definition.frames.length,
      sourceSha256:createHash('sha256').update(await readFile(videoPath)).digest('hex')};
  }
  await writeFile(path.join(pixels,'index.json'),JSON.stringify(index,null,2)+'\n',{flag:'wx'});
  await writeFile(path.join(evaluator,'truth.json'),JSON.stringify(definition,null,2)+'\n',{flag:'wx'});
  return {mode:'synthetic-pixels',frames:definition.frames.length,index:path.join(pixels,'index.json'),truth:path.join(evaluator,'truth.json'),video};
}

if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  const args=process.argv.slice(2),position=args.indexOf('--out');
  if(position<0||!args[position+1]||args.some((value,index)=>value!=='--out'&&value!=='--video'&&index!==position+1)){
    console.error('Usage: node scripts/simulation/generate.mjs --out PATH [--video]');process.exitCode=1;
  } else {
    try{console.log(JSON.stringify(await generate(args[position+1],{video:args.includes('--video')})));}
    catch(error){console.error(error.message);process.exitCode=1;}
  }
}
