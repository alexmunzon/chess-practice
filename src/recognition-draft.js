/** Untrusted local vision proposals are drafts, never confirmed game state. */
import {createPlacementDraft} from './position-draft.js';
export function parseRecognitionDraft(text,referenceHash){
 if(typeof text!=='string'||text.length>512*1024)throw new Error('Recognition JSON must be under 512 KB.');
 const p=JSON.parse(text);
 if(!p||p.schemaVersion!==1||!['real-image-inference','synthetic-pixel-inference'].includes(p.source)||p.status!=='needs-human-review'||p.fen!==null||p.guidanceAllowed!==false)throw new Error('Expected an unconfirmed image-recognition proposal.');
 if(!/^[a-f0-9]{64}$/.test(p.sourceSha256)||p.sourceSha256!==referenceHash)throw new Error('Load the same source photo before importing its recognition proposal.');
 if(!Array.isArray(p.imageSize)||p.imageSize.length!==2||p.imageSize.some(n=>!Number.isSafeInteger(n)||n<=0||n>20000))throw new Error('Invalid image dimensions.');
 if(typeof p.rawPlacement!=='string'||p.rawPlacement.length>80)throw new Error('Placement-only proposal required.');
 const draft=createPlacementDraft(p.rawPlacement);
 if(!p.squares||Object.keys(p.squares).length!==64)throw new Error('Exactly 64 square observations required.');
 const uncertain=[];
 for(let i=0;i<64;i++){
  const square='abcdefgh'[i%8]+(8-Math.floor(i/8)),cell=p.squares[square],raw=draft.board[Math.floor(i/8)][i%8]??'.';
  if(!cell||cell.rawLabel!==raw||typeof cell.confidence!=='number'||!Number.isFinite(cell.confidence)||cell.confidence<0||cell.confidence>1||!['unknown',raw==='.'?'empty':raw].includes(cell.label))throw new Error('Inconsistent or invalid square observation: '+square);
  if(cell.label==='unknown')uncertain.push(square);
 }
 // Placement never supplies the turn, castling, en passant or move counters.
 return {draft,uncertain,sourceSha256:p.sourceSha256,notice:`${p.source==='synthetic-pixel-inference'?'Synthetic screen-board pixel proposal (no physical-board validation)':'Vision proposal'}: ${uncertain.length} uncertain squares. Every piece and all game history need review, even high-scoring squares.`};
}
