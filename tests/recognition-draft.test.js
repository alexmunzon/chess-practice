import test from 'node:test';import assert from 'node:assert/strict';import {parseRecognitionDraft} from '../src/recognition-draft.js';
import {draftFen} from '../src/position-draft.js';
const hash='a'.repeat(64);
function proposal(){return {schemaVersion:1,source:'real-image-inference',status:'needs-human-review',fen:null,guidanceAllowed:false,sourceSha256:hash,imageSize:[800,600],rawPlacement:'8/8/8/8/8/8/8/8',squares:Object.fromEntries(Array.from({length:64},(_,i)=>['abcdefgh'[i%8]+(8-Math.floor(i/8)),{rawLabel:'.',label:'unknown',confidence:.4}]))};}
test('image proposal leaves every nonvisual field unknown until explicitly supplied',()=>{
 const {draft,uncertain}=parseRecognitionDraft(JSON.stringify(proposal()),hash);
 assert.equal(uncertain.length,64);
 const unknown={turn:'',castling:'',ep:'',halfmove:null,fullmove:null};
 const known={turn:'b',castling:'-',ep:'-',halfmove:12,fullmove:34};
 for(const [key,value] of Object.entries(unknown)){
  assert.equal(draft[key],value,key);
  assert.throws(()=>draftFen({...draft,...known,[key]:value}),undefined,key);
 }
 assert.equal(draftFen({...draft,...known}),'8/8/8/8/8/8/8/8 b - - 12 34');
});
test('proposal rejects changed images, synthetic observations and claimed confirmation',()=>{for(const patch of [{sourceSha256:'b'.repeat(64)},{source:'synthetic-observations'},{guidanceAllowed:true},{fen:'8/8/8/8/8/8/8/8 w - - 0 1'},{status:'ready'},{imageSize:[Infinity,100]}])assert.throws(()=>parseRecognitionDraft(JSON.stringify({...proposal(),...patch}),hash));});
test('all 64 labels and scores must match placement and be finite',()=>{for(const mutate of [p=>delete p.squares.a8,p=>p.squares.a8.rawLabel='K',p=>p.squares.a8.confidence=2,p=>p.squares.a8.label='k',p=>p.rawPlacement='8/8']){const p=proposal();mutate(p);assert.throws(()=>parseRecognitionDraft(JSON.stringify(p),hash));}});
test('oversized and malformed proposals fail closed',()=>{assert.throws(()=>parseRecognitionDraft(' '.repeat(512*1024+1),hash));assert.throws(()=>parseRecognitionDraft('{',hash));});

test('synthetic pixel draft is labeled and leaves history unknown even with perfect match scores',()=>{
 const p={...proposal(),source:'synthetic-pixel-inference'};
 for(const cell of Object.values(p.squares)){cell.label='empty';cell.confidence=1;}
 const result=parseRecognitionDraft(JSON.stringify(p),hash);
 assert.match(result.notice,/Synthetic screen-board/);assert.match(result.notice,/no physical-board validation/);
 assert.equal(result.draft.turn,'');assert.equal(result.draft.castling,'');assert.equal(result.draft.ep,'');assert.throws(()=>draftFen(result.draft));
});
