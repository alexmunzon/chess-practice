import {createDraft,emptyDraft,setDraftPiece,draftFen} from './position-draft.js';
import {createReviewState} from './review-state.js';
const $=s=>document.querySelector(s), review=createReviewState();
const START='rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
const symbols={K:'♔',Q:'♕',R:'♖',B:'♗',N:'♘',P:'♙',k:'♚',q:'♛',r:'♜',b:'♝',n:'♞',p:'♟'};
const names={k:'king',q:'queen',r:'rook',b:'bishop',n:'knight',p:'pawn'};
let draft=null,position=null, selected=null, flipped=false, dirty=false, controller=null, positionRequest=0, history=[], imageURL=null;
const status=text=>{$('#status').textContent=text;};
async function api(path,body,signal){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal});const d=await r.json();if(!r.ok)throw new Error(d.error?.message??d.error??`Request failed (${r.status})`);return d;}
function cancel(){controller?.abort();controller=null;review.invalidate();$('#confirmed').checked=false;renderAnalysis();renderBoard();}
function legalMoves(){return position?.legalMoves??[];}
function renderBoard(){
 const board=$('#board');board.replaceChildren();
 const ranks=flipped?[1,2,3,4,5,6,7,8]:[8,7,6,5,4,3,2,1],files=flipped?'hgfedcba':'abcdefgh';
 for(const rank of ranks)for(const file of files){const square=file+rank,row=8-rank,col='abcdefgh'.indexOf(file);let piece=(draft?.board??position?.board)?.[row]?.[col]??null;if(typeof piece==='object'&&piece)piece=piece.color==='w'?piece.type.toUpperCase():piece.type;
  const button=document.createElement('button');button.className='square '+((row+col)%2?'dark':'light');button.dataset.square=square;button.setAttribute('role','gridcell');button.setAttribute('aria-label',`${square}${piece?`, ${piece===piece.toUpperCase()?'white':'black'} ${names[piece.toLowerCase()]}`:', empty'}`);button.setAttribute('aria-selected',String(selected===square));
  if(selected===square)button.classList.add('selected');if(!draft&&selected&&legalMoves().some(m=>m.from===selected&&m.to===square))button.classList.add('legal');
  const move=review.get().analysis?.bestMove;if(move&&(square===move.from||square===move.to))button.classList.add('suggestion');
  if(piece){const span=document.createElement('span');span.className='piece '+(piece===piece.toUpperCase()?'white-piece':'black-piece');span.textContent=symbols[piece];button.append(span);}
  const label=document.createElement('span');label.className='coordinate';label.textContent=square;button.append(label);button.addEventListener('click',()=>choose(square));board.append(button);
 }
 $('#board-help').textContent=draft?'Manual setup: choose a piece, then click a square. Validate before analysis.':'Select a piece, then a highlighted destination. Every move clears old analysis.';
 $('#turn-status').textContent=draft?'Unvalidated board draft':position?`${position.turn==='w'?'White':'Black'} to move${position.status&&position.status!=='playing'?' · '+position.status:''}`:'No position';
 $('#undo').disabled=history.length===0;
}
function renderAnalysis(){const state=review.get(),result=$('#analysis');$('#analyze').disabled=!position||dirty||!state.confirmed||state.pending||position.gameOver||legalMoves().length===0;$('#cancel').hidden=!state.pending;$('#confirmed').disabled=!position||dirty;result.replaceChildren();result.classList.toggle('empty',!state.analysis);
 if(state.pending){result.textContent='Searching locally…';return;}if(!state.analysis){result.textContent=position?.gameOver?'Position is terminal: '+position.status+'.':state.confirmed?'Ready for local analysis.':'Confirm the position to begin.';return;}
 const d=state.analysis,a=d.analysis??{},headline=document.createElement('strong');headline.className='best-move';headline.textContent=d.bestMove?.san??'No move';result.append(headline);
 const detail=document.createElement('p');detail.textContent=d.bestMove?`${d.bestMove.from} → ${d.bestMove.to}${d.bestMove.promotion?' · promote to '+names[d.bestMove.promotion]:''}`:d.status;result.append(detail);
 const meta=document.createElement('p');meta.className='fine';meta.textContent=`Depth ${a.depth??'—'} · ${a.elapsedMs??'—'} ms${a.mate!=null?' · mate score '+a.mate:a.scoreCp!=null?' · evaluation '+(a.scoreCp/100).toFixed(2)+' for '+(position.turn==='w'?'White':'Black'):''}`;result.append(meta);
 const pv=document.createElement('p');pv.className='variation';pv.textContent='Engine line: '+(Array.isArray(a.pv)?a.pv.map(m=>typeof m==='string'?m:m.san??m.uci).join(' '):a.pv??'Not provided');result.append(pv);
}
async function load(fen,{remember=false}={}){dirty=true;cancel();selected=null;const id=++positionRequest;try{const next=await api('/api/position',{fen});if(id!==positionRequest)return;if(remember&&position)history.push(position.fen);position=next;draft=null;$('#position-editor').hidden=true;dirty=false;review.setPosition(next.fen);$('#fen').value=next.fen;renderBoard();renderAnalysis();status('Position loaded. Review it before requesting a move.');return true;}catch(e){if(id!==positionRequest)return;dirty=true;renderAnalysis();status('Position not loaded: '+e.message);return false;}}
async function choose(square){if(draft){setDraftPiece(draft,square,$('#editor-piece').value||null);updateDraft();return;}if(!position||dirty||position.gameOver)return;const options=legalMoves().filter(m=>m.from===selected&&m.to===square);if(options.length){const from=selected,fen=position.fen;dirty=true;cancel();status('Applying practice move…');const id=++positionRequest;try{const next=await api('/api/move',{fen,from,to:square,promotion:$('#promotion').value});if(id!==positionRequest)return;history.push(fen);position=next;dirty=false;selected=null;review.setPosition(next.fen);$('#fen').value=next.fen;renderBoard();renderAnalysis();status('Move played in practice. Check the new position.');}catch(e){if(id===positionRequest){dirty=false;renderAnalysis();renderBoard();status('Move not applied: '+e.message);}}return;}selected=selected===square?null:square;renderBoard();}
$('#confirmed').addEventListener('change',()=>{controller?.abort();controller=null;review.confirm($('#confirmed').checked);renderAnalysis();renderBoard();});
$('#analyze').addEventListener('click',async()=>{if($('#analyze').disabled)return;let token;try{token=review.begin();}catch(e){status(e.message);return;}controller=new AbortController();renderAnalysis();try{const result=await api('/api/analyze',{fen:token.fen,requestId:String(token.id),confirmation:true,movetimeMs:Number($('#budget').value)},controller.signal);if(review.accept(token,result)){renderAnalysis();renderBoard();status('Analysis ready for the confirmed position.');}}catch(e){if(review.fail(token)){renderAnalysis();status(e.name==='AbortError'?'Analysis cancelled.':'Analysis unavailable: '+e.message);}}});
$('#cancel').addEventListener('click',()=>{cancel();status('Analysis cancelled. Confirm again to restart.');});
$('#fen').addEventListener('input',()=>{draft=null;$('#position-editor').hidden=true;positionRequest++;dirty=true;cancel();renderBoard();status('Draft changed. Load the FEN before confirming.');});
$('#load').addEventListener('click',()=>load($('#fen').value.trim(),{remember:true}));
$('#reset').addEventListener('click',()=>load(START,{remember:true}));
$('#undo').addEventListener('click',async()=>{const previous=history.at(-1);if(previous&&await load(previous)){history.pop();renderBoard();}});
$('#flip').addEventListener('click',()=>{flipped=!flipped;renderBoard();});
$('#board').addEventListener('keydown',e=>{if(!['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.key))return;const buttons=[...$('#board').children],i=buttons.indexOf(document.activeElement),delta={ArrowUp:-8,ArrowDown:8,ArrowLeft:-1,ArrowRight:1}[e.key];if(i>=0){e.preventDefault();buttons[Math.max(0,Math.min(63,i+delta))].focus();}});
$('#image-file').addEventListener('change',()=>{const file=$('#image-file').files[0];if(!file)return;cancel();if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>20*1024*1024){status('Choose a PNG, JPEG or WebP image under 20 MB.');return;}if(imageURL)URL.revokeObjectURL(imageURL);imageURL=URL.createObjectURL(file);$('#reference-image').src=imageURL;$('#image-preview').hidden=false;status('Local reference loaded. Match its pieces to the FEN manually, including historical rights.');});
$('#clear-image').addEventListener('click',()=>{cancel();if(imageURL)URL.revokeObjectURL(imageURL);imageURL=null;$('#reference-image').removeAttribute('src');$('#image-preview').hidden=true;$('#image-file').value='';});
$('#reference-image').addEventListener('error',()=>{if(imageURL)URL.revokeObjectURL(imageURL);imageURL=null;$('#reference-image').removeAttribute('src');$('#image-preview').hidden=true;$('#image-file').value='';status('This image could not be decoded. Choose another local reference.');});
document.addEventListener('visibilitychange',()=>{if(document.hidden){cancel();status('Review interrupted. Confirm the position again.');}});
fetch('/api/health').then(r=>r.json()).then(d=>{$('#engine-status').textContent=(typeof d.engine==='string'?d.engine:d.engine?.name)??d.engineName??'Local engine available';}).catch(()=>{$('#engine-status').textContent='Local engine unavailable';});
load(START);

function showDraft(){
 $('#position-editor').hidden=false;$('#editor-turn').value=draft.turn;$('#editor-ep').value=draft.ep;$('#editor-halfmove').value=draft.halfmove;$('#editor-fullmove').value=draft.fullmove;document.querySelectorAll('.editor-right').forEach(el=>el.checked=draft.castling.includes(el.value));updateDraft();
}
function updateDraft(){positionRequest++;dirty=true;selected=null;cancel();try{$('#fen').value=draftFen(draft);status('Board setup changed. Validate it, then confirm all game state.');}catch(e){status(e.message);}renderBoard();renderAnalysis();}
$('#edit-position').addEventListener('click',()=>{if(!position)return;draft=createDraft(position.fen);showDraft();});
$('#clear-board').addEventListener('click',()=>{draft=emptyDraft();showDraft();});
$('#discard-editor').addEventListener('click',()=>{if(position)load(position.fen);});
$('#apply-editor').addEventListener('click',()=>{try{load(draftFen(draft),{remember:true});}catch(e){status(e.message);}});
for(const id of ['editor-turn','editor-ep','editor-halfmove','editor-fullmove'])$('#'+id).addEventListener('input',()=>{if(!draft)return;draft.turn=$('#editor-turn').value;draft.ep=$('#editor-ep').value;draft.halfmove=$('#editor-halfmove').value===''?NaN:Number($('#editor-halfmove').value);draft.fullmove=$('#editor-fullmove').value===''?NaN:Number($('#editor-fullmove').value);updateDraft();});
document.querySelectorAll('.editor-right').forEach(el=>el.addEventListener('change',()=>{if(draft){draft.castling=[...document.querySelectorAll('.editor-right:checked')].map(el=>el.value).join('')||'-';updateDraft();}}));
