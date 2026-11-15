import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import { mkdtemp, readdir, rm, readFile, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { createHash } from 'node:crypto';
import { createPhotoRecognizer, MAX_PHOTO_BYTES } from '../src/core/photo-recognizer.js';

const png = Buffer.from([137,80,78,71,13,10,26,10]); // Magic-only mock, not a real decoded image.
function proposal(bytes = png) {
  return {schemaVersion:1, source:'real-image-inference', sourceSha256:createHash('sha256').update(bytes).digest('hex'),
    status:'needs-human-review', fen:null, guidanceAllowed:false, model:'joelseytre/chessq-lite',
    modelRevision:'7b33e1d47be02ce67b8e30ff7f09418166037d99', numericalValidationStatus:'failed-one-logit-tolerance-on-evaluation-mac',
    threshold:0.95, imageSize:[640,480], rawPlacement:'8/8/8/8/8/8/8/8',
    squares:Object.fromEntries(Array.from({length:64}, (_,i) => ['abcdefgh'[i%8]+(8-Math.floor(i/8)), {rawLabel:'.',label:'empty',confidence:0.99}])),
    provenance:{numericalValidationPassed:false,computeUnits:'CPU_AND_GPU'},
    timing:{verificationMs:1,preprocessMs:1,compileAndLoadMs:1,inferenceMs:[1,1,1],totalMs:5}};
}
async function harness(t, behavior, options = {}) {
  const root = await mkdtemp(join(tmpdir(), 'photo-test-'));
  t.after(() => rm(root, {recursive:true,force:true}));
  const calls = [];
  const recognize = createPhotoRecognizer({tempRoot:root, timeoutMs:1000, ...options, spawnProcess(command,args,opts) {
    const child = new EventEmitter(); child.stdout = new PassThrough(); child.stderr = new PassThrough();
    let closed = false;
    child.close = code => { if (!closed) { closed = true; child.emit('close', code); } };
    child.kill = () => { child.killed = true; setImmediate(() => child.close(null)); return true; };
    calls.push({command,args,opts,child});
    setImmediate(() => behavior(child,args,opts));
    return child;
  }});
  return {recognize,calls,root,clean:async () => assert.deepEqual(await readdir(root), [])};
}
const code = expected => error => error.code === expected;

test('mock proposal preserves hard review gates and cleans private image on success', async t => {
  let input, dir;
  const h = await harness(t, (child,args) => { [,,input] = args; dir = dirname(input); child.stdout.write(JSON.stringify(proposal())); child.close(0); });
  const p = await h.recognize(png);
  assert.equal(p.guidanceAllowed,false); assert.equal(p.fen,null); assert.equal(p.status,'needs-human-review');
  assert.equal(h.calls[0].opts.env.TMPDIR,dir); assert.equal(h.calls[0].opts.detached,true); assert.equal(h.calls[0].opts.stdio[0],'ignore');
  assert.match(input,/photo\.png$/); await assert.rejects(stat(dir)); await h.clean();
});

test('invalid bytes, formats and oversize input never spawn', async t => {
  const h = await harness(t, () => assert.fail('must not spawn'));
  for (const bytes of [null,Buffer.alloc(0),Buffer.from('<svg/>'),Buffer.alloc(MAX_PHOTO_BYTES+1)]) await assert.rejects(h.recognize(bytes),code('INVALID_IMAGE'));
  assert.equal(h.calls.length,0); await h.clean();
});

test('pre-aborted requests never create work', async t => {
  const h = await harness(t, () => assert.fail('must not spawn'));
  await assert.rejects(h.recognize(png,{signal:AbortSignal.abort()}),code('ABORTED')); await h.clean();
});

test('one active job; cancellation kills child, waits for close and cleans', async t => {
  let started; const ready = new Promise(r => { started = r; });
  const h = await harness(t, () => started()); const controller = new AbortController();
  const job = h.recognize(png,{signal:controller.signal}); const rejected = assert.rejects(job,code('ABORTED'));
  await ready; await assert.rejects(h.recognize(png),code('BUSY'));
  controller.abort(); await rejected; assert.equal(h.calls[0].child.killed,true); await h.clean();
});

test('deadline and stderr/stdout limits kill and clean', async t => {
  for (const behavior of [() => {}, child => child.stderr.write(Buffer.alloc(128*1024+1)), child => child.stdout.write(Buffer.alloc(128*1024+1))]) {
    const h = await harness(t,behavior,{timeoutMs:20});
    await assert.rejects(h.recognize(png),error => ['TIMEOUT','OUTPUT_LIMIT'].includes(error.code));
    assert.equal(h.calls[0].child.killed,true); await h.clean();
  }
});

test('exit failure, spawn error and malformed output clean and unlock', async t => {
  for (const behavior of [child => child.close(1),child => { child.emit('error',new Error('ENOENT')); child.close(-2); },child => { child.stdout.write('invalid'); child.close(0); }]) {
    const h = await harness(t,behavior);
    await assert.rejects(h.recognize(png)); await h.clean();
    await assert.rejects(h.recognize(png)); assert.equal(h.calls.length,2); await h.clean();
  }
});

test('unsafe or incomplete model outputs cannot become review drafts', async t => {
  for (const mutate of [p => { p.guidanceAllowed = true; },p => { p.fen = '8/8/8/8/8/8/8/8 w - - 0 1'; },
    p => { p.sourceSha256 = 'wrong'; },p => { delete p.squares.a8; },p => { p.squares.a8.confidence = 1.1; },
    p => { p.squares.a8.label = 'K'; },p => { p.imageSize = [8193,1]; },p => { p.imageSize = [8000,8000]; },
    p => { p.rawPlacement = 'K7/8/8/8/8/8/8/8'; },p => { p.provenance.numericalValidationPassed = true; },
    p => { p.timing.inferenceMs = []; }]) {
    const h = await harness(t,child => { const p = proposal(); mutate(p); child.stdout.write(JSON.stringify(p)); child.close(0); });
    await assert.rejects(h.recognize(png),code('INVALID_RESULT')); await h.clean();
  }
});

test('input is snapshotted, path private, file permissions restricted', async t => {
  const input = Buffer.from(png); let inspect;
  const checked = new Promise((resolve,reject) => { inspect = async (child,args) => { try {
    assert.deepEqual(await readFile(args[2]),png);
    assert.equal((await stat(args[2])).mode & 0o777,0o600);
    assert.equal((await stat(dirname(args[2]))).mode & 0o777,0o700);
    child.stdout.write(JSON.stringify(proposal())); child.close(0); resolve();
  } catch(e) { reject(e); child.close(1); } }; });
  const h = await harness(t,(...args) => inspect(...args));
  const result = h.recognize(input); input.fill(0); await result; await checked; await h.clean();
});
