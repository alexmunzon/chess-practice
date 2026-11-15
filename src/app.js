import {parseRecognitionDraft} from './recognition-draft.js';
import {createDraft,emptyDraft,setDraftPiece,draftFen} from './position-draft.js';
import {createReviewState} from './review-state.js';
import {calibrationRequest,calibrationHeader,parseCalibrationPreview,imagePoint} from './calibration-draft.js';
const $=s=>document.querySelector(s), review=createReviewState();
const START='rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
const symbols={K:'♔',Q:'♕',R:'♖',B:'♗',N:'♘',P:'♙',k:'♚',q:'♛',r:'♜',b:'♝',n:'♞',p:'♟'};
const names={k:'king',q:'queen',r:'rook',b:'bishop',n:'knight',p:'pawn'};
let referenceFile=null,recognitionPending=false,recognitionRequest=0,referenceHash=null,imageRequest=0,proposalDraft=false,uncertainSquares=new Set(),draft=null,position=null, selected=null, flipped=false, dirty=false, controller=null, positionRequest=0, history=[], imageURL=null;
const CORNERS=['tl','tr','br','bl'],CORNER_LABELS=['Top-left','Top-right','Bottom-right','Bottom-left'];
let referenceSize=null,calibrationCorners=Array.from({length:4},()=>[null,null]),calibrationPreview=null,calibrationPending=false,calibrationVersion=0,pickingCorners=false;
const status=text=>{$('#status').textContent=text;};
async function api(path,body,signal){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal});const d=await r.json();if(!r.ok)throw new Error(d.error?.message??d.error??`Request failed (${r.status})`);return d;}
function renderRecognition(){$('#recognize').disabled=!referenceFile||!referenceHash||recognitionPending||calibrationPending;$('#recognize-simulation').disabled=$('#recognize').disabled;$('#recognize').textContent=recognitionPending?'Reading image locally…':'Recognize saved photo';renderCalibrationActions();}
function cancel(){globalThis.speechSynthesis?.cancel();recognitionRequest++;recognitionPending=false;calibrationPending=false;$('#geometry-reviewed').checked=false;controller?.abort();controller=null;renderRecognition();review.invalidate();$('#confirmed').checked=false;renderAnalysis();renderBoard();}
function legalMoves(){return position?.legalMoves??[];}
function renderBoard(){
 const board=$('#board');board.replaceChildren();
 const ranks=flipped?[1,2,3,4,5,6,7,8]:[8,7,6,5,4,3,2,1],files=flipped?'hgfedcba':'abcdefgh';
 for(const rank of ranks)for(const file of files){const square=file+rank,row=8-rank,col='abcdefgh'.indexOf(file);let piece=(draft?.board??position?.board)?.[row]?.[col]??null;if(typeof piece==='object'&&piece)piece=piece.color==='w'?piece.type.toUpperCase():piece.type;
  const button=document.createElement('button');button.className='square '+((row+col)%2?'dark':'light');button.dataset.square=square;button.setAttribute('role','gridcell');button.setAttribute('aria-label',`${square}${piece?`, ${piece===piece.toUpperCase()?'white':'black'} ${names[piece.toLowerCase()]}`:', empty'}`);button.setAttribute('aria-selected',String(selected===square));
  if(draft&&uncertainSquares.has(square))button.classList.add('uncertain');
  if(selected===square)button.classList.add('selected');if(!draft&&selected&&legalMoves().some(m=>m.from===selected&&m.to===square))button.classList.add('legal');
  const move=review.get().analysis?.bestMove;if(move&&(square===move.from||square===move.to))button.classList.add('suggestion');
  if(piece){const span=document.createElement('span');span.className='piece '+(piece===piece.toUpperCase()?'white-piece':'black-piece');span.textContent=symbols[piece];button.append(span);}
  const label=document.createElement('span');label.className='coordinate';label.textContent=square;button.append(label);button.addEventListener('click',()=>choose(square));board.append(button);
 }
 $('#board-help').textContent=draft?'Manual setup: choose a piece, then click a square. Validate before analysis.':'Select a piece, then a highlighted destination. Every move clears old analysis.';
 $('#turn-status').textContent=draft?'Unvalidated board draft':position?`${position.turn==='w'?'White':'Black'} to move${position.status&&position.status!=='playing'?' · '+position.status:''}`:'No position';
 $('#undo').disabled=history.length===0;
}
function renderAnalysis(){const state=review.get(),result=$('#analysis');$('#load').disabled=!!draft;$('#speak').disabled=!state.confirmed||!state.analysis?.speechText||dirty;$('#analyze').disabled=!position||dirty||!state.confirmed||state.pending||position.gameOver||legalMoves().length===0;$('#cancel').hidden=!state.pending;$('#confirmed').disabled=!position||dirty;result.replaceChildren();result.classList.toggle('empty',!state.analysis);
 if(state.pending){result.textContent='Searching locally…';return;}if(!state.analysis){result.textContent=position?.gameOver?'Position is terminal: '+position.status+'.':state.confirmed?'Ready for local analysis.':'Confirm the position to begin.';return;}
 const d=state.analysis,a=d.analysis??{},headline=document.createElement('strong');headline.className='best-move';headline.textContent=d.bestMove?.san??'No move';result.append(headline);
 const detail=document.createElement('p');detail.textContent=d.bestMove?`${d.bestMove.from} → ${d.bestMove.to}${d.bestMove.promotion?' · promote to '+names[d.bestMove.promotion]:''}`:d.status;result.append(detail);
 const meta=document.createElement('p');meta.className='fine';meta.textContent=`Depth ${a.depth??'—'} · ${a.elapsedMs??'—'} ms${a.mate!=null?' · mate score '+a.mate:a.scoreCp!=null?' · evaluation '+(a.scoreCp/100).toFixed(2)+' for '+(position.turn==='w'?'White':'Black'):''}`;result.append(meta);
 const pv=document.createElement('p');pv.className='variation';pv.textContent='Engine line: '+(Array.isArray(a.pv)?a.pv.map(m=>typeof m==='string'?m:m.san??m.uci).join(' '):a.pv??'Not provided');result.append(pv);
}
async function load(fen,{remember=false}={}){dirty=true;cancel();selected=null;const id=++positionRequest;try{const next=await api('/api/position',{fen});if(id!==positionRequest)return;if(remember&&position)history.push(position.fen);position=next;draft=null;proposalDraft=false;uncertainSquares.clear();$('#position-editor').hidden=true;dirty=false;review.setPosition(next.fen);$('#fen').value=next.fen;renderBoard();renderAnalysis();status('Position loaded. Review it before requesting a move.');return true;}catch(e){if(id!==positionRequest)return;dirty=true;renderAnalysis();status('Position not loaded: '+e.message);return false;}}
async function choose(square){if(draft){setDraftPiece(draft,square,$('#editor-piece').value||null);updateDraft();return;}if(!position||dirty||position.gameOver)return;const options=legalMoves().filter(m=>m.from===selected&&m.to===square);if(options.length){const from=selected,fen=position.fen;dirty=true;cancel();status('Applying practice move…');const id=++positionRequest;try{const next=await api('/api/move',{fen,from,to:square,promotion:$('#promotion').value});if(id!==positionRequest)return;history.push(fen);position=next;dirty=false;selected=null;review.setPosition(next.fen);$('#fen').value=next.fen;renderBoard();renderAnalysis();status('Move played in practice. Check the new position.');}catch(e){if(id===positionRequest){dirty=false;renderAnalysis();renderBoard();status('Move not applied: '+e.message);}}return;}selected=selected===square?null:square;renderBoard();}
$('#confirmed').addEventListener('change',()=>{globalThis.speechSynthesis?.cancel();recognitionRequest++;recognitionPending=false;calibrationPending=false;$('#geometry-reviewed').checked=false;controller?.abort();controller=null;renderRecognition();review.confirm($('#confirmed').checked);renderAnalysis();renderBoard();});
$('#analyze').addEventListener('click',async()=>{if($('#analyze').disabled)return;let token;try{token=review.begin();}catch(e){status(e.message);return;}controller=new AbortController();renderAnalysis();try{const result=await api('/api/analyze',{fen:token.fen,requestId:String(token.id),confirmation:true,movetimeMs:Number($('#budget').value)},controller.signal);if(review.accept(token,result)){renderAnalysis();renderBoard();status('Analysis ready for the confirmed position.');}}catch(e){if(review.fail(token)){renderAnalysis();status(e.name==='AbortError'?'Analysis cancelled.':'Analysis unavailable: '+e.message);}}});
$('#speak').addEventListener('click',()=>{
 const state=review.get();if($('#speak').disabled||!state.confirmed||!state.analysis?.speechText)return;
 const synth=globalThis.speechSynthesis,Utterance=globalThis.SpeechSynthesisUtterance;
 if(!synth||!Utterance){status('Local speech is unavailable in this browser. The move remains visible.');return;}
 const voice=synth.getVoices().find(v=>v.localService&&/^en(?:-|$)/i.test(v.lang));
 if(!voice){status('No installed English voice is available. No online voice will be used.');return;}
 synth.cancel();const utterance=new Utterance(state.analysis.speechText);utterance.voice=voice;utterance.lang=voice.lang;utterance.rate=.9;
 const identity=state.analysis;utterance.onstart=()=>{if(review.get().analysis!==identity||!review.get().confirmed||document.hidden)synth.cancel();};
 utterance.onerror=()=>{if(review.get().analysis===identity)status('Local speech could not play. Read the displayed move.');};
 synth.speak(utterance);status('Speaking through this device’s selected output. Glasses audio routing has not been tested.');
});
$('#cancel').addEventListener('click',()=>{cancel();status('Analysis cancelled. Confirm again to restart.');});
$('#fen').addEventListener('input',()=>{draft=null;proposalDraft=false;uncertainSquares.clear();$('#position-editor').hidden=true;positionRequest++;dirty=true;cancel();renderBoard();status('Draft changed. Load the FEN before confirming.');});
$('#load').addEventListener('click',()=>{if(!draft)return load($('#fen').value.trim(),{remember:true});});
$('#reset').addEventListener('click',()=>load(START,{remember:true}));
$('#undo').addEventListener('click',async()=>{const previous=history.at(-1);if(previous&&await load(previous)){history.pop();renderBoard();}});
$('#flip').addEventListener('click',()=>{flipped=!flipped;renderBoard();});
$('#board').addEventListener('keydown',e=>{if(!['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.key))return;const buttons=[...$('#board').children],i=buttons.indexOf(document.activeElement),delta={ArrowUp:-8,ArrowDown:8,ArrowLeft:-1,ArrowRight:1}[e.key];if(i>=0){e.preventDefault();buttons[Math.max(0,Math.min(63,i+delta))].focus();}});
function invalidateImageProposal(){
 if(proposalDraft){draft=null;proposalDraft=false;uncertainSquares.clear();positionRequest++;dirty=true;$('#position-editor').hidden=true;}
 referenceHash=null;referenceFile=null;referenceSize=null;resetCalibrationFields();cancel();renderCalibrationOverlay();
}
$('#image-file').addEventListener('change',async()=>{const imageId=++imageRequest;invalidateImageProposal();const file=$('#image-file').files[0];if(!file)return;if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>8*1024*1024){status('Choose a PNG, JPEG or WebP image under 8 MB.');return;}if(imageURL)URL.revokeObjectURL(imageURL);imageURL=URL.createObjectURL(file);$('#reference-image').src=imageURL;$('#image-preview').hidden=false;status('Local reference loaded. Recognition produces a draft that must be checked.');try{const hash=await crypto.subtle.digest('SHA-256',await file.arrayBuffer());if(imageId===imageRequest){referenceHash=[...new Uint8Array(hash)].map(x=>x.toString(16).padStart(2,'0')).join('');referenceFile=file;renderRecognition();}}catch{if(imageId===imageRequest)status('Image preview works, but its identity could not be verified for recognition.');}});
$('#clear-image').addEventListener('click',()=>{imageRequest++;invalidateImageProposal();if(imageURL)URL.revokeObjectURL(imageURL);imageURL=null;$('#reference-image').removeAttribute('src');$('#image-preview').hidden=true;$('#image-file').value='';});
$('#reference-image').addEventListener('error',()=>{imageRequest++;invalidateImageProposal();if(imageURL)URL.revokeObjectURL(imageURL);imageURL=null;$('#reference-image').removeAttribute('src');$('#image-preview').hidden=true;$('#image-file').value='';status('This image could not be decoded. Choose another local reference.');});
$('#reference-image').addEventListener('load',()=>{
 const image=$('#reference-image');if(!imageURL||(image.currentSrc||image.src)!==imageURL)return;
 const size=[image.naturalWidth,image.naturalHeight];
 if(size.some(n=>!Number.isSafeInteger(n)||n<1)){referenceSize=null;renderCalibrationActions();return;}
 referenceSize=size;renderCalibrationActions();renderCalibrationOverlay();
});
function applyProposal(text){const result=parseRecognitionDraft(text,referenceHash);draft=result.draft;proposalDraft=true;uncertainSquares=new Set(result.uncertain);showDraft();$('#recognition-notice').textContent=result.notice;status(result.notice+' Enter all missing game-state fields before validation.');}
for(const [button,path,source] of [['#recognize','/api/recognize','real-image-inference'],['#recognize-simulation','/api/recognize-simulation','synthetic-pixel-inference']])$(button).addEventListener('click',async()=>{
 if($(button).disabled||!referenceFile||!referenceHash)return;
 cancel();const id=recognitionRequest,imageId=imageRequest;controller=new AbortController();recognitionPending=true;renderRecognition();status(source==='synthetic-pixel-inference'?'Reading synthetic screen-board pixels on this Mac. This tests the known rendered piece style only.':'Reading the saved photo on this Mac. This is not a live glasses feed.');
 try{const response=await fetch(path,{method:'POST',headers:{'Content-Type':referenceFile.type},body:referenceFile,signal:controller.signal});const result=await response.json();if(id!==recognitionRequest||imageId!==imageRequest)return;if(!response.ok)throw new Error(result.error??'Recognition failed.');if(result.source!==source)throw new Error('Recognizer returned a different input mode.');recognitionPending=false;controller=null;applyProposal(JSON.stringify(result));}
 catch(e){if(id===recognitionRequest){status(e.name==='AbortError'?'Recognition cancelled.':'Recognition unavailable: '+e.message);}}
 finally{if(id===recognitionRequest){recognitionPending=false;controller=null;renderRecognition();}}
});
document.addEventListener('visibilitychange',()=>{if(document.hidden){cancel();status('Review interrupted. Confirm the position again.');}});
fetch('/api/health').then(r=>r.json()).then(d=>{$('#engine-status').textContent=(typeof d.engine==='string'?d.engine:d.engine?.name)??d.engineName??'Local engine available';}).catch(()=>{$('#engine-status').textContent='Local engine unavailable';});
load(START);

function showDraft(){
 $('#position-editor').hidden=false;$('#proposal-review').hidden=!proposalDraft;$('#proposal-reviewed').checked=false;$('#editor-turn').value=draft.turn;$('#editor-ep').value=draft.ep;$('#editor-halfmove').value=draft.halfmove??'';$('#editor-fullmove').value=draft.fullmove??'';$('#editor-castling-known').checked=!!draft.castling;document.querySelectorAll('.editor-right').forEach(el=>{el.checked=draft.castling.includes(el.value);el.disabled=!draft.castling;});updateDraft();
}
function renderDraftActions(){let valid=false;try{draftFen(draft);valid=true;}catch{}$('#apply-editor').disabled=!valid||(proposalDraft&&!$('#proposal-reviewed').checked);}
function updateDraft(){if(proposalDraft)$('#proposal-reviewed').checked=false;renderDraftActions();positionRequest++;dirty=true;selected=null;cancel();try{$('#fen').value=draftFen(draft);status('Board setup changed. Validate it, then confirm all game state.');}catch(e){$('#fen').value='';status(e.message);}renderBoard();renderAnalysis();}
$('#edit-position').addEventListener('click',()=>{if(!position)return;proposalDraft=false;uncertainSquares.clear();draft=createDraft(position.fen);showDraft();});
$('#clear-board').addEventListener('click',()=>{proposalDraft=false;uncertainSquares.clear();draft=emptyDraft();showDraft();});
$('#discard-editor').addEventListener('click',()=>{if(position)load(position.fen);});
$('#apply-editor').addEventListener('click',()=>{if(proposalDraft&&!$('#proposal-reviewed').checked){status('Review every proposed piece and game state before validating.');return;}try{return load(draftFen(draft),{remember:true});}catch(e){status(e.message);}});
for(const id of ['editor-turn','editor-ep','editor-halfmove','editor-fullmove'])$('#'+id).addEventListener('input',()=>{if(!draft)return;draft.turn=$('#editor-turn').value;draft.ep=$('#editor-ep').value;draft.halfmove=$('#editor-halfmove').value===''?NaN:Number($('#editor-halfmove').value);draft.fullmove=$('#editor-fullmove').value===''?NaN:Number($('#editor-fullmove').value);updateDraft();});
function updateCastling(){if(!draft)return;const known=$('#editor-castling-known').checked;document.querySelectorAll('.editor-right').forEach(el=>el.disabled=!known);draft.castling=known?([...document.querySelectorAll('.editor-right:checked')].map(el=>el.value).join('')||'-'):'';updateDraft();}
$('#editor-castling-known').addEventListener('change',updateCastling);
document.querySelectorAll('.editor-right').forEach(el=>el.addEventListener('change',updateCastling));

$('#proposal-reviewed').addEventListener('change',renderDraftActions);
$('#recognition-file').addEventListener('change',async()=>{const file=$('#recognition-file').files[0],imageId=imageRequest;if(!file)return;cancel();const id=recognitionRequest;try{if(file.size>512*1024)throw new Error('Recognition JSON must be under 512 KB.');const text=await file.text();if(id!==recognitionRequest||imageId!==imageRequest)return;applyProposal(text);}catch(e){if(id===recognitionRequest&&imageId===imageRequest)status('Recognition proposal not loaded: '+e.message);}finally{if($('#recognition-file').files[0]===file)$('#recognition-file').value='';}});

function calibrationInput(){return calibrationRequest({sourceSha256:referenceHash,imageSize:referenceSize,corners:calibrationCorners,topLeftSquare:$('#calibration-top-left').value});}
function renderCalibrationActions(){
 const loaded=!!referenceFile&&!!referenceHash&&!!referenceSize,busy=recognitionPending||calibrationPending;
 let valid=false;try{calibrationInput();valid=true;}catch{}
 $('#calibration-controls').hidden=!referenceFile;
 $('#pick-corners').disabled=!loaded;$('#reset-corners').disabled=!loaded;$('#calibration-corner').disabled=!loaded;
 $('#calibrate').disabled=!loaded||!valid||busy;$('#calibrate').textContent=calibrationPending?'Preparing grid…':'Preview labeled grid';
 $('#geometry-reviewed').disabled=!calibrationPreview||calibrationPending;
 if(!calibrationPreview)$('#geometry-reviewed').checked=false;
 $('#recognize-calibrated').disabled=!calibrationPreview||!$('#geometry-reviewed').checked||busy;
 $('#calibration-help').textContent=!loaded?'Wait for the photo to finish loading.':pickingCorners?`Click the ${CORNER_LABELS[Number($('#calibration-corner').value)||0].toLowerCase()} board corner in the photo.`:calibrationPreview?'Check the labeled grid against the actual board before confirming its geometry.':'Select four board corners in image order, then choose the actual square at the top-left corner.';
 $('#reference-image').classList.toggle('selecting-corners',pickingCorners);
}
function renderCalibrationOverlay(){
 const overlay=$('#calibration-overlay');overlay.replaceChildren();if(!referenceSize)return;
 overlay.setAttribute('viewBox',`0 0 ${referenceSize[0]} ${referenceSize[1]}`);
 const node=(name,attrs,text)=>{const el=document.createElementNS('http://www.w3.org/2000/svg',name);for(const [key,value]of Object.entries(attrs))el.setAttribute(key,String(value));if(text!==undefined)el.textContent=text;overlay.append(el);};
 const font=Math.max(9,Math.min(...referenceSize)/45);
 if(calibrationPreview)for(const cell of calibrationPreview.squares){
  node('polygon',{points:cell.sourcePolygon.map(p=>p.join(',')).join(' '),class:'calibration-cell'});
  const center=cell.sourcePolygon.reduce((sum,p)=>[sum[0]+p[0]/4,sum[1]+p[1]/4],[0,0]);
  node('text',{x:center[0],y:center[1],'font-size':font*.7,class:'calibration-square-label'},cell.square);
 }
 const known=calibrationCorners.filter(p=>p.every(Number.isFinite));
 if(known.length===4&&!calibrationPreview)node('polygon',{points:known.map(p=>p.join(',')).join(' '),class:'calibration-outline'});
 calibrationCorners.forEach((point,i)=>{if(!point.every(Number.isFinite))return;node('circle',{cx:point[0],cy:point[1],r:font*.3,class:'calibration-point'});node('text',{x:point[0]+font*.45,y:point[1]+font,'font-size':font,class:'calibration-corner-label'},CORNERS[i].toUpperCase());});
}
function resetCalibrationFields(){
 calibrationVersion++;calibrationPreview=null;calibrationPending=false;pickingCorners=false;
 calibrationCorners=Array.from({length:4},()=>[null,null]);$('#calibration-top-left').value='';$('#calibration-corner').value='0';$('#geometry-reviewed').checked=false;
 for(const name of CORNERS)for(const axis of ['x','y'])$('#calibration-'+name+'-'+axis).value='';
}
function invalidateGeometry(){
 calibrationVersion++;calibrationPreview=null;$('#geometry-reviewed').checked=false;
 if(proposalDraft){draft=null;proposalDraft=false;uncertainSquares.clear();$('#position-editor').hidden=true;$('#fen').value='';}
 positionRequest++;dirty=true;cancel();renderCalibrationOverlay();
}
function readCornerFields(){return CORNERS.map(name=>['x','y'].map(axis=>{const value=$('#calibration-'+name+'-'+axis).value;return value===''?null:Number(value);}));}
for(const name of CORNERS)for(const axis of ['x','y'])$('#calibration-'+name+'-'+axis).addEventListener('input',()=>{calibrationCorners=readCornerFields();pickingCorners=false;invalidateGeometry();status('Board corners changed. Preview and review the grid again.');});
$('#calibration-top-left').addEventListener('change',()=>{invalidateGeometry();status('Board orientation changed. Preview and review the grid again.');});
$('#pick-corners').addEventListener('click',()=>{if($('#pick-corners').disabled)return;pickingCorners=true;const missing=calibrationCorners.findIndex(p=>!p.every(Number.isFinite));$('#calibration-corner').value=String(missing<0?0:missing);renderCalibrationActions();});
$('#calibration-corner').addEventListener('change',()=>{if($('#calibration-corner').disabled)return;pickingCorners=true;renderCalibrationActions();});
$('#reference-image').addEventListener('click',event=>{
 if(!pickingCorners||!referenceSize)return;
 try{const index=Number($('#calibration-corner').value);if(!Number.isInteger(index)||index<0||index>3)return;
  const point=imagePoint(event.clientX,event.clientY,$('#reference-image').getBoundingClientRect(),referenceSize);calibrationCorners[index]=point;
  ['x','y'].forEach((axis,i)=>$('#calibration-'+CORNERS[index]+'-'+axis).value=String(point[i]));
  if(index<3)$('#calibration-corner').value=String(index+1);else pickingCorners=false;
  invalidateGeometry();status('Corner selected. Check all four corners and choose the board orientation.');
 }catch(error){status(error.message);}
});
$('#reset-corners').addEventListener('click',()=>{resetCalibrationFields();invalidateGeometry();status('Board corners cleared. Select all four corners again.');});
$('#calibrate').addEventListener('click',async()=>{
 if($('#calibrate').disabled||!referenceFile)return;
 let metadata;try{metadata=calibrationInput();}catch(error){status(error.message);return;}
 cancel();calibrationPreview=null;renderCalibrationOverlay();const id=recognitionRequest,imageId=imageRequest,version=calibrationVersion,file=referenceFile;
 controller=new AbortController();calibrationPending=true;renderRecognition();status('Preparing the manual board grid on this Mac.');
 try{const response=await fetch('/api/calibrate',{method:'POST',headers:{'Content-Type':file.type,'X-Chess-Calibration':calibrationHeader(metadata)},body:file,signal:controller.signal});const result=await response.json();
  if(id!==recognitionRequest||imageId!==imageRequest||version!==calibrationVersion)return;
  if(!response.ok)throw new Error(result.error?.message??result.error??'Grid preparation failed.');
  calibrationPreview=parseCalibrationPreview(result,metadata);pickingCorners=false;$('#geometry-reviewed').checked=false;renderCalibrationOverlay();status('Review the grid and every coordinate label on the photo. Geometry review does not confirm pieces or game state.');
 }catch(error){if(id===recognitionRequest&&imageId===imageRequest&&version===calibrationVersion)status('Grid unavailable: '+error.message);}
 finally{if(id===recognitionRequest){calibrationPending=false;controller=null;renderRecognition();}}
});
$('#geometry-reviewed').addEventListener('change',()=>{
 const checked=$('#geometry-reviewed').checked,preview=calibrationPreview;
 cancel();$('#geometry-reviewed').checked=!!preview&&preview===calibrationPreview&&checked;renderCalibrationActions();
});
$('#recognize-calibrated').addEventListener('click',async()=>{
 if($('#recognize-calibrated').disabled||!referenceFile||!calibrationPreview||!$('#geometry-reviewed').checked)return;
 let header;const preview=calibrationPreview;try{header=calibrationHeader(calibrationInput(),preview.calibrationId);}catch(error){status(error.message);return;}
 cancel();$('#geometry-reviewed').checked=true;const id=recognitionRequest,imageId=imageRequest,version=calibrationVersion,file=referenceFile;
 controller=new AbortController();recognitionPending=true;renderRecognition();status('Reading pieces inside the reviewed board. Every result still needs piece and history review.');
 try{const response=await fetch('/api/recognize',{method:'POST',headers:{'Content-Type':file.type,'X-Chess-Calibration':header},body:file,signal:controller.signal});const result=await response.json();
  if(id!==recognitionRequest||imageId!==imageRequest||version!==calibrationVersion||preview!==calibrationPreview)return;
  if(!response.ok)throw new Error(result.error?.message??result.error??'Calibrated recognition failed.');
  if(result.calibrationId!==preview.calibrationId)throw new Error('Recognition does not match the reviewed grid.');
  recognitionPending=false;controller=null;applyProposal(JSON.stringify(result));
 }catch(error){if(id===recognitionRequest&&imageId===imageRequest&&version===calibrationVersion)status('Recognition unavailable: '+error.message);}
 finally{if(id===recognitionRequest){recognitionPending=false;controller=null;renderRecognition();}}
});
