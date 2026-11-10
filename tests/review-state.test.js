import test from 'node:test';import assert from 'node:assert/strict';import {createReviewState} from '../src/review-state.js';
const prepared=()=>{const s=createReviewState();s.setPosition('fen-A');s.confirm(true);return s;};
test('analysis requires a confirmed position',()=>{const s=createReviewState();assert.throws(()=>s.begin());s.setPosition('fen-A');assert.throws(()=>s.begin());s.confirm(true);assert.equal(s.begin().fen,'fen-A');});
test('edited positions reject stale analysis',()=>{const s=prepared(),t=s.begin();s.setPosition('fen-B');assert.equal(s.accept(t,{fen:'fen-A'}),false);assert.equal(s.get().analysis,null);});
test('revocation and repeated request discard old callbacks',()=>{const s=prepared(),a=s.begin(),b=s.begin();assert.equal(s.accept(a,{fen:'fen-A'}),false);assert.equal(s.accept(b,{fen:'fen-A'}),true);s.confirm(false);assert.equal(s.get().analysis,null);assert.throws(()=>s.begin());});
test('foreign identity and mismatched FEN are rejected',()=>{const s=prepared(),t=s.begin();assert.equal(s.accept({...t},{fen:'fen-A'}),false);assert.equal(s.accept(t,{fen:'fen-B'}),false);assert.equal(s.accept(t,{fen:'fen-A'}),true);});
test('interruption clears output without reviving confirmation',()=>{const s=prepared(),t=s.begin();s.invalidate();assert.equal(s.fail(t),false);assert.equal(s.accept(t,{fen:'fen-A'}),false);assert.equal(s.get().confirmed,false);});
