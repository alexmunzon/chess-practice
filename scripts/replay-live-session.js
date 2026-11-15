// Human-reviewed synthetic labels only. This does not read video or use a camera.
import { Chess } from 'chess.js';
import { analyze } from '../src/core/engine.js';
import { SQUARES } from '../src/core/observation.js';
import { LiveSession, TextSpeechSink } from '../src/core/live-session.js';
const chess=new Chess(), speech=new TextSpeechSink();
const session=new LiveSession({engine:analyze,movetimeMs:50,speech,color:'w',trackerOptions:{timeoutMs:15000}});
try {
 const {epoch}=session.connect('synthetic-rehearsal');
 session.confirm({fen:chess.fen(),reviewed:{pieces:true,turn:true,castling:true,enPassant:true,counters:true}});
 for(let sequence=0;sequence<2;sequence++) {
  if(sequence) await new Promise(r=>setTimeout(r,60));
  session.ingestReviewed({sourceId:'synthetic-rehearsal',epoch,sequence,capturedAt:performance.now(),squares:Object.fromEntries(SQUARES.map(s=>{const p=chess.get(s);return [s,{label:p?(p.color==='w'?p.type.toUpperCase():p.type):'empty',confidence:1}]}))},{humanReviewed:true});
 }
 const result=await session.guide();if(!result) throw new Error(session.lastError || 'No guidance');
 console.log(JSON.stringify({mode:'synthetic labeled rehearsal, real Stockfish, text-only speech',text:result.text,depth:result.result.analysis.depth}));
} finally {session.stop();}
