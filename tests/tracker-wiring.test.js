// Wiring of the occupancy tracker (src/core/occupancy-tracker.js) into the phone runtime (runtime.js):
// the off-by-default gate, the four request kinds, the boundary guards, and engine independence.
// Node only: the built bundle's own runtime.js exports, a fake engine, SYNTHETIC occupancy readings. No WebKit or device.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, rm, writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {pathToFileURL} from 'node:url';
import {Chess} from 'chess.js';
import {DeviceBackend} from '../src/core/device-backend.js';
import {OCCUPANCY_SQUARES} from '../src/core/occupancy-move-inference.js';
import {buildDeviceRuntime} from '../scripts/build-device-runtime.mjs';

const START = new Chess().fen();
const reviewed = {pieces: true, turn: true, castling: true, enPassant: true, counters: true};
const SESSION = {sessionId: 'wiring', epoch: 1};
const identity = {sessionId: 'wiring-engine', epoch: 1, sequence: 1, frameSha256: 'a'.repeat(64), revision: 1};
const ON = {occupancyTracker: true};
let ids = 0;
const command = (kind, extra = {}) => JSON.stringify({schemaVersion: 1, requestId: `${kind}-${++ids}`, kind, ...extra});
const start = (atMs = 0, session = SESSION, fen = START) => command('trackerStart', {session, fen, reviewed, atMs});
const snapshot = atMs => command('trackerSnapshot', {atMs});
const analyze = requestId => JSON.stringify({schemaVersion: 1, requestId, kind: 'analyze', fen: START, confirmation: true, nodes: 100000, identity});

const bundleDir = await mkdtemp(join(tmpdir(), 'tracker-wiring-test-'));
const built = await buildDeviceRuntime(join(bundleDir, 'bundle'));
globalThis.webkit = {messageHandlers: {chessRuntime: {postMessage: () => {}}}};
if (typeof globalThis.addEventListener !== 'function') globalThis.addEventListener = () => {};
// The built runtime's top-level start fails here (not chess-local); only its exports are used.
const runtime = await import(pathToFileURL(join(built.outputDirectory, 'runtime.js')));
test.after(() => rm(bundleDir, {recursive: true, force: true}));

/** A fake engine backend with one held analysis at a time; records cancels. */
function heldEngine() {
  const calls = {cancel: 0, handle: 0};
  let release = null;
  const backend = new DeviceBackend({analyzer: async (input, {signal}) => {
    await new Promise((resolve, reject) => { release = resolve; signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), {code: 'ABORTED'}))); });
    return {...input, bestMove: {from: 'e2', to: 'e4'}};
  }});
  const engine = {handle: text => { calls.handle++; return backend.handle(text); }, cancel: () => { calls.cancel++; backend.cancel(); }};
  return {engine, calls, release: () => release?.(), close: () => backend.close()};
}
const replayStub = {handle: () => assert.fail('the replay tracker is not used here')};
function router({occupancy = runtime.createOccupancyHandler(), engine = heldEngine().engine} = {}) {
  return runtime.createRequestRouter({engine, tracker: replayStub, occupancy});
}

/** Scripted camera: one reading every 100 ms, consecutive sequence numbers, a new image hash per reading. */
function camera(route, {session = SESSION, t0 = 0, fen} = {}) {
  const chess = new Chess(fen);
  let seq = 0, time = t0;
  const reading = (overrides = {}, {dt = 100, sequence, at} = {}) => {
    time = at ?? time + dt; seq = sequence ?? seq + 1;
    const squares = Object.fromEntries(OCCUPANCY_SQUARES.map(sq => {
      const piece = chess.get(sq);
      return [sq, overrides[sq] ?? {label: piece ? (piece.color === 'w' ? 'white' : 'black') : 'empty', confidence: 1}];
    }));
    return {identity: {...session, sequence: seq, frameSha256: (session.sessionId + ':' + seq).split('').map(c => c.charCodeAt(0).toString(16)).join('').padStart(64, '0').slice(-64)}, capturedAtMs: time, squares};
  };
  const send = (overrides, opts) => route(command('trackerIngest', {reading: reading(overrides, opts)}), ON);
  const hold = async (n, overrides) => { let last; for (let i = 0; i < n; i++) last = await send(overrides); return last; };
  return {chess, reading, send, hold, now: () => time, play: san => chess.move(san)};
}
async function readyAtStart(route) {
  await route(start(0), ON);
  const cam = camera(route);
  const last = await cam.hold(2);
  assert.equal(last.trackingReady, true, 'two agreeing readings of the reviewed position make it ready');
  return cam;
}
const refusedWith = code => error => { assert.equal(error.code, code, error.message); return true; };
const hidden = (...squares) => Object.fromEntries(squares.map(sq => [sq, {label: 'unknown', confidence: 1}]));

test('setting off (the default): every tracker request is refused and nothing reaches the tracker or the engine', async () => {
  let reached = 0;
  const {engine, calls} = heldEngine();
  const route = runtime.createRequestRouter({engine, tracker: replayStub, occupancy: {handle: () => { reached++; return {}; }}});
  const requests = [start(0), command('trackerIngest', {reading: {}}), snapshot(10), command('trackerStop'), command('trackerSnapshot')];
  for (const options of [undefined, {}, {occupancyTracker: false}, {occupancyTracker: 'true'}, {occupancyTracker: 1}]) {
    for (const text of requests) await assert.rejects(route(text, options), error => error.code === 'TRACKER_DISABLED' && error.message === 'Occupancy tracker disabled.');
  }
  assert.equal(reached, 0); assert.deepEqual(calls, {cancel: 0, handle: 0});
  // A router built without any occupancy handler refuses the same way even if asked to enable it.
  const bare = runtime.createRequestRouter({engine, tracker: replayStub});
  await assert.rejects(bare(start(0), ON), refusedWith('TRACKER_DISABLED'));
});

test('setting off: engine requests are answered exactly as before (same replies with the setting off, on, or no tracker)', async () => {
  const position = JSON.stringify({schemaVersion: 1, requestId: 'p', kind: 'position', fen: START});
  const move = JSON.stringify({schemaVersion: 1, requestId: 'm', kind: 'move', fen: START, move: {from: 'e2', to: 'e4'}});
  const replies = [];
  for (const [occupancy, options] of [[null, undefined], [runtime.createOccupancyHandler(), undefined], [runtime.createOccupancyHandler(), ON]]) {
    const engine = new DeviceBackend({analyzer: async input => ({...input, bestMove: {from: 'g1', to: 'f3'}})});
    const route = runtime.createRequestRouter({engine, tracker: replayStub, occupancy});
    replies.push([await route(position, options), await route(move, options), await route(analyze('a'), options)]);
    engine.close();
  }
  assert.deepEqual(replies[1], replies[0]); assert.deepEqual(replies[2], replies[0]);
  assert.equal(replies[0][2].bestMove.san, 'Nf3');
});

test('setting on: a scripted honest game is tracked and trusted (1.e4 e5 2.Nf3), replies never carry advice', async () => {
  const route = router();
  const started = await route(start(0), ON);
  assert.deepEqual(Object.keys(started).sort(), ['guidanceAllowed', 'kind', 'mode', 'requestId', 'runtime', 'schemaVersion', 'state', 'trackingReady']);
  assert.equal(started.mode, 'occupancy-tracking'); assert.equal(started.guidanceAllowed, false); assert.equal(started.trackingReady, false);
  const cam = camera(route);
  assert.equal((await cam.hold(2)).trackingReady, true);
  for (const san of ['e4', 'e5', 'Nf3']) {
    cam.play(san);
    const pending = await cam.send();
    assert.equal(pending.trackingReady, false, 'a changed board is not trusted on one reading');
    assert.equal(pending.state.fen, null);
    const accepted = await cam.hold(10); // 1,000 ms in view (readyDwellMs)
    assert.equal(accepted.trackingReady, true, san);
    assert.equal(accepted.state.lastMove.san, san);
    assert.equal(accepted.guidanceAllowed, false);
  }
  const snap = await route(snapshot(cam.now() + 100), ON);
  assert.equal(snap.trackingReady, true);
  assert.equal(snap.state.fen, cam.chess.fen());
  assert.equal(snap.state.movesAccepted, 3);
});

test('setting on: a swap behind a hidden square revokes, and later readings never restore trust', async () => {
  const route = router();
  const cam = await readyAtStart(route);
  // A hand covers b1 and g1 (read unknown); the knights could be exchanged; then White plays e4.
  assert.equal((await cam.send(hidden('b1', 'g1'))).trackingReady, false);
  cam.play('e4');
  const after = await cam.hold(11); // 1,000 ms in view: the move would be accepted here without the hidden squares
  assert.equal(after.trackingReady, false);
  assert.equal(after.state.reason, 'pieces-may-have-swapped');
  const later = await cam.hold(5);
  assert.equal(later.trackingReady, false); assert.equal(later.state.status, 'needs-confirmation');
  assert.equal((await route(snapshot(cam.now() + 10), ON)).trackingReady, false);
});

test('setting on: a stopped feed revokes 250 ms after the last reading (snapshot with time); a late reading never restores', async () => {
  const route = router();
  const cam = await readyAtStart(route);
  const last = cam.now();
  assert.equal((await route(snapshot(last + 100), ON)).trackingReady, true);
  assert.equal((await route(snapshot(last + 250), ON)).trackingReady, true, 'exactly 250 ms is still within the gap rule');
  const stale = await route(snapshot(last + 251), ON);
  assert.equal(stale.trackingReady, false); assert.equal(stale.state.reason, 'picture-gap');
  const late = await cam.send(undefined, {dt: 1});
  assert.equal(late.trackingReady, false);
  assert.equal((await cam.hold(3)).trackingReady, false);
});

test('setting on: a snapshot without a time (or with a malformed time) is refused and revokes', async () => {
  for (const bad of [{}, {atMs: null}, {atMs: '400'}, {atMs: -1}, {atMs: 1.5}]) {
    const route = router();
    const cam = await readyAtStart(route);
    await assert.rejects(route(command('trackerSnapshot', bad), ON), refusedWith('TIME_REQUIRED'), JSON.stringify(bad));
    const after = await route(snapshot(cam.now() + 10), ON);
    assert.equal(after.trackingReady, false, JSON.stringify(bad));
    assert.match(after.state.reason, /^invalidated:/);
  }
});

test('setting on: a repeated or earlier reading is passed to the tracker as a revoke, never reordered or dropped silently', async () => {
  for (const scenario of ['repeat', 'earlier-sequence', 'earlier-time']) {
    const route = router();
    const cam = await readyAtStart(route);
    const again = scenario === 'repeat' ? cam.reading({}, {sequence: 2, at: 200})
      : scenario === 'earlier-sequence' ? cam.reading({}, {sequence: 1, at: 300}) : cam.reading({}, {sequence: 3, at: 150});
    await assert.rejects(route(command('trackerIngest', {reading: again}), ON), refusedWith('OUT_OF_ORDER'), scenario);
    const after = await route(snapshot(cam.now()), ON);
    assert.equal(after.trackingReady, false, scenario); assert.equal(after.state.reason, 'invalidated:reading-out-of-order', scenario);
  }
  // A dropped reading keeps its number: the gap reaches the tracker, which revokes.
  const route = router();
  const cam = await readyAtStart(route);
  const gap = await route(command('trackerIngest', {reading: cam.reading({}, {sequence: 4})}), ON);
  assert.equal(gap.trackingReady, false); assert.equal(gap.state.reason, 'missing-picture');
});

test('setting on: a malformed reading or request is refused and revokes', async () => {
  const cases = {
    '63 squares': cam => { const r = cam.reading(); delete r.squares.h8; return {reading: r}; },
    'bad label': cam => cam.reading({e4: {label: 'queen', confidence: 1}}),
    'no capture time': cam => { const r = cam.reading(); delete r.capturedAtMs; return {reading: r}; },
    'extra field': cam => ({reading: cam.reading(), note: 'x'}),
    'no reading': () => ({}),
  };
  for (const [name, make] of Object.entries(cases)) {
    const route = router();
    const cam = await readyAtStart(route);
    let extra = make(cam);
    if (!Object.hasOwn(extra, 'reading') && extra.identity) extra = {reading: extra};
    await assert.rejects(route(command('trackerIngest', extra), ON), refusedWith('INVALID_REQUEST'), name);
    assert.equal((await route(snapshot(cam.now()), ON)).trackingReady, false, name);
  }
  const route = router();
  await readyAtStart(route);
  await assert.rejects(route('{"kind":"trackerStop"', ON), error => error.code !== 'TRACKER_DISABLED' || assert.fail('broken JSON is not a tracker command'));
  await assert.rejects(route(JSON.stringify({schemaVersion: 1, requestId: 'x', kind: 'trackerStop', mode: 'trusted-replay'}), ON), refusedWith('INVALID_REQUEST'));
  assert.equal((await route(snapshot(250), ON)).trackingReady, false);
});

test('setting on: a tracker request while an analysis is pending neither cancels nor delays it', async () => {
  const held = heldEngine();
  const route = router({engine: held.engine});
  const pending = route(analyze('held'));
  await new Promise(resolve => setImmediate(resolve));
  const cam = camera(route);
  await route(start(0), ON);
  await cam.hold(3);
  await route(snapshot(cam.now() + 10), ON);
  await route(command('trackerStop'), ON);
  assert.equal(held.calls.cancel, 0, 'no tracker request cancelled the engine');
  held.release();
  const reply = await pending;
  assert.equal(reply.requestId, 'held'); assert.equal(reply.bestMove.san, 'e4');
  held.close();
});

test('setting on: trackerStop revokes, and later honest readings and snapshots never restore trust', async () => {
  const route = router();
  const cam = await readyAtStart(route);
  const stopped = await route(command('trackerStop'), ON);
  assert.equal(stopped.trackingReady, false); assert.equal(stopped.state.reason, 'invalidated:stopped');
  assert.equal((await cam.hold(3)).trackingReady, false);
  assert.equal((await route(snapshot(cam.now() + 10), ON)).trackingReady, false);
});

test('setting on: a refused start (bad FEN, a missing tick, a retired epoch) leaves a tracker that never becomes ready', async () => {
  const bad = {
    'bad FEN': () => command('trackerStart', {session: SESSION, fen: 'not a fen', reviewed, atMs: 0}),
    'four ticks': () => command('trackerStart', {session: SESSION, fen: START, reviewed: {...reviewed, counters: false}, atMs: 0}),
    'no time': () => command('trackerStart', {session: SESSION, fen: START, reviewed}),
  };
  for (const [name, make] of Object.entries(bad)) {
    const route = router();
    const cam = await readyAtStart(route);
    await assert.rejects(route(make(), ON), error => typeof error.code === 'string' && error.code !== 'TRACKER_DISABLED', name);
    assert.equal((await cam.hold(4)).trackingReady, false, name);
  }
  const route = router();
  await route(start(0, {sessionId: 'wiring', epoch: 2}), ON);
  await assert.rejects(route(start(0, SESSION), ON), refusedWith('STALE_IDENTITY'));
  const cam = camera(route, {session: {sessionId: 'wiring', epoch: 2}});
  assert.equal((await cam.hold(4)).trackingReady, false, 'the retired-epoch start revoked the newer one too');
});

test('native revoke path: revoke() removes trust and never creates or restores a tracker', async () => {
  const occupancy = runtime.createOccupancyHandler();
  occupancy.revoke('native-request-failed'); // before any request: nothing to revoke, nothing created
  const route = router({occupancy});
  const cam = await readyAtStart(route);
  occupancy.revoke('native-request-failed');
  const after = await route(snapshot(cam.now() + 10), ON);
  assert.equal(after.trackingReady, false); assert.equal(after.state.reason, 'invalidated:native-request-failed');
  assert.equal((await cam.hold(3)).trackingReady, false);
  occupancy.revoke('Not A Valid Reason!');
  assert.equal((await route(snapshot(cam.now() + 10), ON)).state.reason, 'invalidated:native-revoke');
});

test('built runtime.js: the default submit refuses tracker requests; true enables them', async () => {
  const child = join(bundleDir, 'tracker-runtime-child.mjs'), hooks = join(bundleDir, 'tracker-hooks.mjs');
  const bundle = pathToFileURL(built.outputDirectory + '/').href;
  await writeFile(hooks, `
const BUNDLE=${JSON.stringify(bundle)};
export async function resolve(specifier,context,next){
 const parent=context.parentURL??'';
 if(specifier.startsWith('chess-local:')) return {url:specifier,shortCircuit:true,format:'module'};
 if(parent.startsWith('chess-local:')&&(specifier.startsWith('./')||specifier.startsWith('../'))) return {url:new URL(specifier,parent).href,shortCircuit:true,format:'module'};
 return next(specifier,context);
}
export async function load(url,context,next){
 if(!url.startsWith('chess-local:')) return next(url,context);
 const {readFile}=await import('node:fs/promises');
 return {format:'module',shortCircuit:true,source:await readFile(new URL(url.slice('chess-local://bundle/'.length),BUNDLE))};
}`);
  await writeFile(child, `
import {register} from 'node:module';
import {readFile} from 'node:fs/promises';
register(${JSON.stringify(pathToFileURL(hooks).href)});
const BUNDLE=${JSON.stringify(bundle)};
const posted=[];
globalThis.webkit={messageHandlers:{chessRuntime:{postMessage:text=>posted.push(JSON.parse(text))}}};
globalThis.addEventListener??=()=>{};
globalThis.fetch=async url=>{const u=new URL(url);return new Response(await readFile(new URL(u.pathname.slice(1),BUNDLE)),{headers:{'content-type':u.pathname.endsWith('.wasm')?'application/wasm':'text/javascript'}});};
URL.createObjectURL=()=>'blob:stand-in'; URL.revokeObjectURL=()=>{};
globalThis.Worker=class{addEventListener(){} removeEventListener(){} postMessage(){} terminate(){}};
await import('chess-local://bundle/runtime.js');
const stop=JSON.stringify({schemaVersion:1,requestId:'s',kind:'trackerStop'});
await globalThis.chessDeviceRuntime.submit(stop,'t1');
await globalThis.chessDeviceRuntime.submit(stop,'t2',false);
await globalThis.chessDeviceRuntime.submit(stop,'t3','true');
await globalThis.chessDeviceRuntime.submit(stop,'t4',true);
await globalThis.chessDeviceRuntime.submit(JSON.stringify({schemaVersion:1,requestId:'p',kind:'position',fen:${JSON.stringify(START)}}),'t5');
process.stdout.write(JSON.stringify(posted));
`);
  const {stdout} = await promisify(execFile)(process.execPath, [child], {cwd: bundleDir, timeout: 30_000});
  const posted = JSON.parse(stdout);
  assert.deepEqual(posted[0], {protocolVersion: 1, kind: 'ready'});
  for (const i of [1, 2, 3]) assert.deepEqual(posted[i].error, {code: 'TRACKER_DISABLED', message: 'Occupancy tracker disabled.'}, `t${i}`);
  assert.equal(posted[4].ok, true); assert.equal(posted[4].result.mode, 'occupancy-tracking'); assert.equal(posted[4].result.trackingReady, false);
  assert.equal(posted[5].ok, true); assert.equal(posted[5].result.position.legalMoves.length, 20);
});

/** Runs `body` in a child process that loads the built bundle's real runtime.js entry (chess-local:// hooks, stand-in fetch/Worker). */
async function inRuntime(name, body, {fixedRandom = false} = {}) {
  const hooks = join(bundleDir, `${name}-hooks.mjs`), child = join(bundleDir, `${name}-child.mjs`);
  const bundle = pathToFileURL(built.outputDirectory + '/').href;
  await writeFile(hooks, `
const BUNDLE=${JSON.stringify(bundle)};
export async function resolve(specifier,context,next){
 const parent=context.parentURL??'';
 if(specifier.startsWith('chess-local:')) return {url:specifier,shortCircuit:true,format:'module'};
 if(parent.startsWith('chess-local:')&&(specifier.startsWith('./')||specifier.startsWith('../'))) return {url:new URL(specifier,parent).href,shortCircuit:true,format:'module'};
 return next(specifier,context);
}
export async function load(url,context,next){
 if(!url.startsWith('chess-local:')) return next(url,context);
 const {readFile}=await import('node:fs/promises');
 return {format:'module',shortCircuit:true,source:await readFile(new URL(url.slice('chess-local://bundle/'.length),BUNDLE))};
}`);
  await writeFile(child, `
import {register} from 'node:module';
import {readFile} from 'node:fs/promises';
register(${JSON.stringify(pathToFileURL(hooks).href)});
const BUNDLE=${JSON.stringify(bundle)};
const posted=[];
globalThis.webkit={messageHandlers:{chessRuntime:{postMessage:text=>posted.push(JSON.parse(text))}}};
globalThis.addEventListener??=()=>{};
globalThis.fetch=async url=>{const u=new URL(url);return new Response(await readFile(new URL(u.pathname.slice(1),BUNDLE)),{headers:{'content-type':u.pathname.endsWith('.wasm')?'application/wasm':'text/javascript'}});};
URL.createObjectURL=()=>'blob:stand-in'; URL.revokeObjectURL=()=>{};
globalThis.Worker=class{addEventListener(){} removeEventListener(){} postMessage(){} terminate(){}};
// fixedRandom: the page's random source returns 0x5a bytes and counts its calls, so the tracker id is known (test only;
// all zeros would be refused as a broken source).
const randomCalls={n:0};
if (${fixedRandom}) globalThis.crypto.getRandomValues=a=>{randomCalls.n++; return a.fill(0x5a);};
await import('chess-local://bundle/runtime.js');
const rt=globalThis.chessDeviceRuntime, out={};
${body}
process.stdout.write(JSON.stringify({posted,out}));
`);
  const {stdout} = await promisify(execFile)(process.execPath, [child], {cwd: bundleDir, timeout: 30_000});
  return JSON.parse(stdout);
}

test('built runtime.js, setting off: refused requests and native revokes never create a tracker object', async () => {
  const {posted, out} = await inRuntime('off-lazy', `
const stop=JSON.stringify({schemaVersion:1,requestId:'s',kind:'trackerStop'});
await rt.submit(stop,'t1'); await rt.submit(stop,'t2',false); rt.revokeOccupancy('native-request-failed');
const {OccupancyTracker}=await import('chess-local://bundle/core/occupancy-tracker.js');
out.randomCalls=randomCalls.n;
try { new OccupancyTracker({instanceId:'device-occupancy-1-'+'5a'.repeat(16)}); out.instanceIdFree=true; } catch (e) { out.instanceIdFree=false; out.error=e.message; }`, {fixedRandom: true});
  assert.equal(posted[1].error.code, 'TRACKER_DISABLED'); assert.equal(posted[2].error.code, 'TRACKER_DISABLED');
  assert.equal(out.instanceIdFree, true, 'no OccupancyTracker was constructed while the setting was off: ' + (out.error ?? ''));
  assert.equal(out.randomCalls, 0, 'no tracker id was drawn while the setting was off');
});

test('built runtime.js, setting on: the native revoke entry revokes a ready tracker; later readings never restore it', async () => {
  const reading = (seq, t) => {
    const chess = new Chess();
    const squares = Object.fromEntries(OCCUPANCY_SQUARES.map(sq => { const p = chess.get(sq); return [sq, {label: p ? (p.color === 'w' ? 'white' : 'black') : 'empty', confidence: 1}]; }));
    return {identity: {...SESSION, sequence: seq, frameSha256: seq.toString(16).padStart(64, '0')}, capturedAtMs: t, squares};
  };
  const cmds = [start(0), command('trackerIngest', {reading: reading(1, 100)}), command('trackerIngest', {reading: reading(2, 200)}), 'REVOKE',
    command('trackerIngest', {reading: reading(3, 300)}), command('trackerIngest', {reading: reading(4, 400)}), snapshot(410)];
  const {posted} = await inRuntime('on-revoke', `
const cmds=${JSON.stringify(cmds)};
let i=0; for (const c of cmds) { if (c==='REVOKE') rt.revokeOccupancy('native-request-failed'); else await rt.submit(c,'t'+(++i),true); }`);
  const replies = posted.slice(1).map(p => p.result);
  assert.equal(replies[2].trackingReady, true, 'ready before the revoke');
  assert.deepEqual(replies.slice(3).map(r => r.trackingReady), [false, false, false]);
  assert.equal(replies[5].state.reason, 'invalidated:native-request-failed');
});

// ---- Promotion answer (trackerAnswerPromotion), 2026-11-17 ----
// White pawn a7, kings a1 / h8: a7-a8 is a promotion whose piece occupancy cannot see.
const PROMO_FEN = '7k/P7/8/8/8/8/8/K7 w - - 0 1';
const promoted = piece => { const c = new Chess(PROMO_FEN); c.move({from: 'a7', to: 'a8', promotion: piece}); return c.fen(); };
const answer = (question, {piece = 'q', atMs, session = SESSION, questionId = question?.questionId ?? 'promotion:none'} = {}) =>
  command('trackerAnswerPromotion', {session, questionId, piece, atMs});
/** Start on PROMO_FEN, become ready, push a7-a8 and read until the tracker asks which piece. */
async function atQuestion(route, {session = SESSION, t0 = 0} = {}) {
  await route(start(t0, session, PROMO_FEN), ON);
  const cam = camera(route, {session, t0, fen: PROMO_FEN});
  assert.equal((await cam.hold(2)).trackingReady, true, 'ready on the promotion position');
  cam.play({from: 'a7', to: 'a8', promotion: 'q'});
  let reply;
  for (let i = 0; i < 6 && reply?.state.status !== 'awaiting-promotion-choice'; i++) reply = await cam.send();
  assert.equal(reply.state.status, 'awaiting-promotion-choice'); assert.equal(reply.trackingReady, false);
  return {cam, question: reply.state.pendingQuestion, revision: reply.state.revision};
}
const kept = (reply, revision) => { assert.equal(reply.state.accepted, false); assert.equal(reply.state.revision, revision, 'nothing changed'); };

test('promotion, setting off: trackerAnswerPromotion is refused at the page gate and nothing reaches the tracker', async () => {
  let reached = 0;
  const {engine, calls} = heldEngine();
  const route = runtime.createRequestRouter({engine, tracker: replayStub, occupancy: {handle: () => { reached++; return {}; }}});
  for (const options of [undefined, {}, {occupancyTracker: false}, {occupancyTracker: 'true'}, {occupancyTracker: 1}]) {
    await assert.rejects(route(answer(null, {atMs: 0}), options), error => error.code === 'TRACKER_DISABLED' && error.message === 'Occupancy tracker disabled.');
  }
  assert.equal(reached, 0); assert.deepEqual(calls, {cancel: 0, handle: 0});
});

test('promotion, built runtime.js, setting off: an answer is refused and no tracker object exists', async () => {
  const text = answer(null, {atMs: 0});
  const {posted, out} = await inRuntime('off-answer', `
const a=${JSON.stringify(text)};
await rt.submit(a,'t1'); await rt.submit(a,'t2',false); await rt.submit(a,'t3','true');
const {OccupancyTracker}=await import('chess-local://bundle/core/occupancy-tracker.js');
out.randomCalls=randomCalls.n;
try { new OccupancyTracker({instanceId:'device-occupancy-1-'+'5a'.repeat(16)}); out.instanceIdFree=true; } catch (e) { out.instanceIdFree=false; out.error=e.message; }`, {fixedRandom: true});
  for (const i of [1, 2, 3]) assert.deepEqual(posted[i].error, {code: 'TRACKER_DISABLED', message: 'Occupancy tracker disabled.'}, `t${i}`);
  assert.equal(out.instanceIdFree, true, 'no OccupancyTracker was constructed while the setting was off: ' + (out.error ?? ''));
  assert.equal(out.randomCalls, 0, 'no tracker id was drawn while the setting was off');
});

test('promotion, setting on: an honest promotion answered by the person is tracked and stays trusted', async () => {
  const route = router();
  const {cam, question} = await atQuestion(route);
  assert.deepEqual(question.options, ['q', 'r', 'b', 'n']); assert.equal(question.from, 'a7'); assert.equal(question.to, 'a8');
  const answered = await route(answer(question, {piece: 'n', atMs: cam.now()}), ON);
  assert.equal(answered.kind, 'trackerAnswerPromotion'); assert.equal(answered.guidanceAllowed, false);
  assert.equal(answered.state.accepted, true); assert.equal(answered.trackingReady, false, 'an answer alone never makes the tracker ready');
  assert.equal(answered.state.status, 'verifying');
  const seen = await cam.hold(2);
  assert.equal(seen.trackingReady, true); assert.equal(seen.state.fen, promoted('n'));
  assert.equal(seen.state.lastMove.promotion, 'n'); assert.equal(seen.state.movesAccepted, 1);
  assert.equal((await cam.hold(5)).trackingReady, true, 'stays trusted on later readings');
  const snap = await route(snapshot(cam.now() + 100), ON);
  assert.equal(snap.trackingReady, true); assert.equal(snap.state.fen, promoted('n'));
});

test('promotion, setting on: a malformed or unknown-piece answer is refused and revokes; a correct answer afterwards cannot restore', async () => {
  const cases = {
    'piece k': (q, t) => answer(q, {piece: 'k', atMs: t}), 'piece Q': (q, t) => answer(q, {piece: 'Q', atMs: t}),
    'piece p': (q, t) => answer(q, {piece: 'p', atMs: t}), 'piece null': (q, t) => answer(q, {piece: null, atMs: t}),
    'no atMs': q => command('trackerAnswerPromotion', {session: SESSION, questionId: q.questionId, piece: 'q'}),
    'negative atMs': q => answer(q, {atMs: -1}), 'fractional atMs': (q, t) => answer(q, {atMs: t + 0.5}),
    'extra field': (q, t) => command('trackerAnswerPromotion', {session: SESSION, questionId: q.questionId, piece: 'q', atMs: t, note: 'x'}),
    'session without epoch': (q, t) => answer(q, {atMs: t, session: {sessionId: 'wiring'}}),
    'session epoch 0': (q, t) => answer(q, {atMs: t, session: {sessionId: 'wiring', epoch: 0}}),
    'numeric questionId': (q, t) => answer(q, {atMs: t, questionId: 7}),
    'with mode': (q, t) => JSON.stringify({schemaVersion: 1, requestId: 'm1', kind: 'trackerAnswerPromotion', mode: 'trusted-replay', session: SESSION, questionId: q.questionId, piece: 'q', atMs: t}),
  };
  for (const [name, make] of Object.entries(cases)) {
    const route = router();
    const {cam, question} = await atQuestion(route);
    await assert.rejects(route(make(question, cam.now()), ON), refusedWith('INVALID_REQUEST'), name);
    const after = await route(snapshot(cam.now()), ON);
    assert.equal(after.trackingReady, false, name); assert.equal(after.state.status, 'needs-confirmation', name);
    const retry = await route(answer(question, {atMs: cam.now()}), ON);
    assert.equal(retry.state.accepted, false, name); assert.equal(retry.state.rejected, 'no-pending-question', name);
    assert.equal((await cam.hold(3)).trackingReady, false, name);
  }
  // An unknown piece revokes a ready tracker too (no question needed to be a caller bug).
  const route = router();
  const cam = await readyAtStart(route);
  await assert.rejects(route(answer(null, {piece: 'x', atMs: cam.now()}), ON), refusedWith('INVALID_REQUEST'));
  assert.equal((await route(snapshot(cam.now()), ON)).trackingReady, false);
  // An oversized answer is not a tracker request at the page (the native side refuses it before sending and revokes).
  let reached = 0;
  const big = JSON.stringify({schemaVersion: 1, requestId: 'big', kind: 'trackerAnswerPromotion', session: SESSION, questionId: 'q'.repeat(17000), piece: 'q', atMs: 0});
  const guarded = runtime.createRequestRouter({engine: heldEngine().engine, tracker: replayStub, occupancy: {handle: () => { reached++; return {}; }}});
  await assert.rejects(guarded(big, ON)); assert.equal(reached, 0);
});

test('promotion, setting on: an answer when no promotion is waiting is rejected and changes nothing (as the tracker does)', async () => {
  const route = router();
  const cam = await readyAtStart(route);
  const before = await route(snapshot(cam.now()), ON);
  const reply = await route(answer(null, {questionId: 'promotion:wiring:1:device-occupancy-1:1', atMs: cam.now()}), ON);
  kept(reply, before.state.revision); assert.equal(reply.state.rejected, 'no-pending-question');
  assert.equal(reply.trackingReady, true, 'trust is neither added nor removed');
  assert.equal((await cam.hold(2)).trackingReady, true);
});

test('promotion, setting on: an answer never restores advice that was already revoked (native revoke, stop, picture gap, misread)', async () => {
  for (const how of ['native-revoke', 'stop', 'picture-gap', 'changed-board']) {
    const occupancy = runtime.createOccupancyHandler();
    const route = router({occupancy});
    const {cam, question} = await atQuestion(route);
    if (how === 'native-revoke') occupancy.revoke('native-request-failed');
    if (how === 'stop') await route(command('trackerStop'), ON);
    if (how === 'picture-gap') assert.equal((await route(snapshot(cam.now() + 251), ON)).state.status, 'needs-confirmation');
    if (how === 'changed-board') assert.equal((await cam.send({a8: {label: 'empty', confidence: 1}, a7: {label: 'white', confidence: 1}, h1: {label: 'white', confidence: 1}})).state.status, 'needs-confirmation');
    const revoked = await route(snapshot(cam.now()), ON);
    const reply = await route(answer(question, {atMs: how === 'changed-board' ? cam.now() : question.askedAtMs}), ON);
    kept(reply, revoked.state.revision); assert.equal(reply.trackingReady, false, how); assert.equal(reply.state.rejected, 'no-pending-question', how);
    assert.equal((await cam.hold(4)).trackingReady, false, how);
  }
});

test('promotion, setting on: a late answer (after a stop, a new start, or a newer reading) has no effect', async () => {
  { // After a stop: the stop's revoke stands unchanged.
    const route = router();
    const {cam, question} = await atQuestion(route);
    const stopped = await route(command('trackerStop'), ON);
    const late = await route(answer(question, {atMs: cam.now()}), ON);
    kept(late, stopped.state.revision); assert.equal(late.state.reason, 'invalidated:stopped');
  }
  { // After a new start (a new review of the promoted board) that became ready: the old answer leaves it ready.
    const route = router();
    const {cam, question} = await atQuestion(route);
    const askedAt = cam.now();
    await route(start(cam.now(), SESSION, cam.chess.fen()), ON);
    const ready = await cam.hold(2);
    assert.equal(ready.trackingReady, true);
    const late = await route(answer(question, {atMs: askedAt}), ON);
    kept(late, ready.state.revision); assert.equal(late.trackingReady, true); assert.equal(late.state.rejected, 'no-pending-question');
    assert.equal((await cam.hold(2)).trackingReady, true);
  }
  { // After a newer reading: rejected without using up the question; an answer stamped with the newest reading then works.
    const route = router();
    const {cam, question} = await atQuestion(route);
    const askedAt = cam.now();
    const newer = await cam.send();
    assert.equal(newer.state.status, 'awaiting-promotion-choice');
    for (const atMs of [askedAt, cam.now() + 50, cam.now() - 1]) {
      const late = await route(answer(question, {atMs}), ON);
      kept(late, newer.state.revision); assert.equal(late.state.rejected, 'late-answer', String(atMs));
      assert.equal(late.state.status, 'awaiting-promotion-choice'); assert.equal(late.state.pendingQuestion.questionId, question.questionId);
    }
    const foreign = await route(answer(question, {atMs: cam.now(), session: {sessionId: 'wiring', epoch: 2}}), ON);
    kept(foreign, newer.state.revision); assert.equal(foreign.state.rejected, 'foreign-session');
    const stale = await route(answer(question, {atMs: cam.now(), questionId: question.questionId + '0'}), ON);
    kept(stale, newer.state.revision); assert.equal(stale.state.rejected, 'stale-question');
    const current = await route(answer(question, {piece: 'r', atMs: cam.now()}), ON);
    assert.equal(current.state.accepted, true);
    const seen = await cam.hold(2);
    assert.equal(seen.trackingReady, true); assert.equal(seen.state.fen, promoted('r'));
    // The identical answer again changes nothing; a DIFFERENT piece for the same question is doubt and revokes (review
    // 2026-11-17 finding 1: this line used to assert that a different piece changed nothing, which kept advice on).
    const again = await route(answer(question, {piece: 'r', atMs: cam.now()}), ON);
    kept(again, seen.state.revision); assert.equal(again.trackingReady, true); assert.equal(again.state.fen, promoted('r'));
    await assert.rejects(route(answer(question, {piece: 'q', atMs: cam.now()}), ON), refusedWith('ANSWER_CONFLICT'));
    const after = await route(snapshot(cam.now()), ON);
    assert.equal(after.trackingReady, false); assert.equal(after.state.reason, 'invalidated:conflicting-promotion-answer');
  }
});

// ---- Review 2026-11-17 (review-promotion-wiring): conflicting answers, question ids across page reloads ----
test('promotion, review finding 1: a different piece for an answered question revokes before verification', async () => {
  const route = router();
  const {cam, question} = await atQuestion(route);
  assert.equal((await route(answer(question, {piece: 'q', atMs: cam.now()}), ON)).state.accepted, true);
  await assert.rejects(route(answer(question, {piece: 'n', atMs: cam.now()}), ON), refusedWith('ANSWER_CONFLICT'));
  const after = await route(snapshot(cam.now()), ON);
  assert.equal(after.trackingReady, false); assert.equal(after.state.reason, 'invalidated:conflicting-promotion-answer');
  assert.equal((await cam.hold(4)).trackingReady, false, 'never ready with either piece');
});

test('promotion, review finding 1: a different piece for an answered question revokes after verification (advice was on)', async () => {
  const route = router();
  const {cam, question} = await atQuestion(route);
  assert.equal((await route(answer(question, {piece: 'q', atMs: cam.now()}), ON)).state.accepted, true);
  const ready = await cam.hold(2);
  assert.equal(ready.trackingReady, true); assert.equal(ready.state.fen, promoted('q'));
  await assert.rejects(route(answer(question, {piece: 'n', atMs: cam.now()}), ON), refusedWith('ANSWER_CONFLICT'));
  assert.equal((await route(snapshot(cam.now()), ON)).trackingReady, false);
  assert.equal((await cam.hold(4)).trackingReady, false);
});

test('promotion, review finding 1: the identical answer repeated is a no-op, before and after verification', async () => {
  const route = router();
  const {cam, question} = await atQuestion(route);
  const first = await route(answer(question, {piece: 'b', atMs: cam.now()}), ON);
  assert.equal(first.state.accepted, true);
  const repeat = await route(answer(question, {piece: 'b', atMs: cam.now()}), ON);
  kept(repeat, first.state.revision); assert.equal(repeat.state.rejected, 'no-pending-question'); assert.equal(repeat.state.status, 'verifying');
  const ready = await cam.hold(2);
  assert.equal(ready.trackingReady, true); assert.equal(ready.state.fen, promoted('b'));
  const later = await route(answer(question, {piece: 'b', atMs: cam.now()}), ON);
  kept(later, ready.state.revision); assert.equal(later.trackingReady, true);
});

test('promotion: an answer for another session with no question open is rejected as foreign-session, nothing changed', async () => {
  const route = router();
  const cam = await readyAtStart(route);
  const before = await route(snapshot(cam.now()), ON);
  const reply = await route(answer(null, {atMs: cam.now(), session: {sessionId: 'wiring', epoch: 9}}), ON);
  kept(reply, before.state.revision); assert.equal(reply.state.rejected, 'foreign-session'); assert.equal(reply.trackingReady, true);
});

/** Commands for one page: start on PROMO_FEN, two readings, then four readings of a7-a8 (camera clock from 0). */
function promotionPageCommands() {
  const square = fen => { const c = new Chess(fen); return Object.fromEntries(OCCUPANCY_SQUARES.map(sq => { const p = c.get(sq); return [sq, {label: p ? (p.color === 'w' ? 'white' : 'black') : 'empty', confidence: 1}]; })); };
  const reading = (seq, fen) => command('trackerIngest', {reading: {identity: {...SESSION, sequence: seq, frameSha256: seq.toString(16).padStart(64, '0')}, capturedAtMs: seq * 100, squares: square(fen)}});
  return [start(0, SESSION, PROMO_FEN), reading(1, PROMO_FEN), reading(2, PROMO_FEN), ...[3, 4, 5, 6].map(n => reading(n, promoted('q')))];
}

test('promotion, review finding 2: after a page reload (same session and epoch, camera clock restarted) an old answer is rejected and changes nothing', async () => {
  const cmds = promotionPageCommands();
  const page = body => inRuntime('reload-' + (++ids), `
const cmds=${JSON.stringify(cmds)};
let i=0; for (const c of cmds) await rt.submit(c,'t'+(++i),true);
out.question=posted.at(-1).result.state.pendingQuestion; out.atMs=posted.at(-1).result.state.lastFrame.capturedAtMs;
${body}`);
  const a = (await page('')).out;
  assert.ok(a.question?.questionId, 'page A asked a question');
  const old = answer(a.question, {piece: 'n', atMs: a.atMs});
  const after = [7, 8, 9].map(seq => command('trackerIngest', {reading: {identity: {...SESSION, sequence: seq, frameSha256: seq.toString(16).padStart(64, '0')}, capturedAtMs: seq * 100,
    squares: Object.fromEntries(OCCUPANCY_SQUARES.map(sq => [sq, {label: sq === 'a8' ? 'white' : sq === 'h8' ? 'black' : sq === 'a1' ? 'white' : 'empty', confidence: 1}]))}}));
  const {out: b} = await page(`
const before=posted.at(-1).result.state.revision;
await rt.submit(${JSON.stringify(old)},'old',true); out.old=posted.at(-1).result; out.before=before;
for (const c of ${JSON.stringify(after)}) await rt.submit(c,'r'+(++i),true); out.later=posted.at(-1).result;`);
  assert.equal(b.atMs, a.atMs, 'the old answer carries the right time for the new page (the reviewer\'s condition)');
  assert.match(a.question.questionId, /^promotion:wiring:1:device-occupancy-1-[0-9a-f]{32}:1$/);
  assert.notEqual(b.question.questionId, a.question.questionId, 'question ids differ across page loads');
  assert.equal(b.old.state.accepted, false); assert.equal(b.old.state.rejected, 'stale-question');
  assert.equal(b.old.state.revision, b.before, 'nothing changed'); assert.equal(b.old.state.status, 'awaiting-promotion-choice');
  assert.equal(b.later.trackingReady, false, 'the new question is still unanswered: never ready');
});

test('promotion: with the setting on, the tracker id is drawn from the page random source (control for the setting-off checks)', async () => {
  const {out} = await inRuntime('on-random', `
await rt.submit(${JSON.stringify(start(0))},'t1',true);
out.randomCalls=randomCalls.n;
const {OccupancyTracker}=await import('chess-local://bundle/core/occupancy-tracker.js');
try { new OccupancyTracker({instanceId:'device-occupancy-1-'+'5a'.repeat(16)}); out.instanceIdFree=true; } catch (e) { out.instanceIdFree=false; }`, {fixedRandom: true});
  assert.equal(out.randomCalls, 1); assert.equal(out.instanceIdFree, false, 'the created tracker holds exactly that id');
});

test('promotion: an answer to another question is named stale-question whatever its time, and changes nothing', async () => {
  const route = router();
  const {cam, question, revision} = await atQuestion(route);
  for (const atMs of [cam.now(), cam.now() - 100]) {
    const reply = await route(answer(question, {atMs, questionId: question.questionId + '0'}), ON);
    kept(reply, revision); assert.equal(reply.state.rejected, 'stale-question', String(atMs)); assert.equal(reply.state.status, 'awaiting-promotion-choice');
  }
});

// ---- Review round 2 of 2026-11-17: random-source failures, answers across a game, a full answer memory ----
/** Runs `body` with globalThis.crypto replaced by `value` (undefined = no crypto at all), then restores the real one. */
async function withCrypto(value, body) {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'crypto');
  Object.defineProperty(globalThis, 'crypto', {value, configurable: true, writable: true});
  try { return await body(); } finally { Object.defineProperty(globalThis, 'crypto', original); }
}

test('random source: missing crypto, missing getRandomValues, a throwing or an all-zero source leave no tracker and refuse every tracker request; the engine still answers', async () => {
  const sources = {
    'missing crypto': [undefined, /unavailable/],
    'missing getRandomValues': [{}, /unavailable/],
    'throwing getRandomValues': [{getRandomValues() { throw new Error('QuotaExceededError'); }}, /unavailable/],
    'all-zero getRandomValues': [{getRandomValues: a => a.fill(0)}, /all zeros/],
  };
  const position = JSON.stringify({schemaVersion: 1, requestId: 'p', kind: 'position', fen: START});
  for (const [name, [source, message]] of Object.entries(sources)) {
    const occupancy = runtime.createOccupancyHandler();
    const engine = new DeviceBackend({analyzer: async input => ({...input, bestMove: {from: 'g1', to: 'f3'}})});
    const route = runtime.createRequestRouter({engine, tracker: replayStub, occupancy});
    const cam = camera(route);
    await withCrypto(source, async () => {
      const requests = [start(0), command('trackerIngest', {reading: cam.reading()}), snapshot(10), command('trackerStop'),
        answer(null, {atMs: 0}), command('trackerIngest', {reading: {}})];
      for (const text of requests) {
        await assert.rejects(route(text, ON), error => error.code === 'RANDOM_UNAVAILABLE' && message.test(error.message), `${name}: ${text.slice(0, 60)}`);
      }
      occupancy.revoke('native-request-failed'); // the native revoke path neither throws nor creates a tracker
      assert.equal((await route(position, ON)).position.legalMoves.length, 20, `${name}: engine still answers`);
    });
    // No tracker was created while the source failed: the first request after it works draws the id exactly once.
    let draws = 0;
    await withCrypto({getRandomValues: a => { draws++; return a.fill(0x5a); }}, async () => {
      assert.equal((await route(start(0), ON)).state.status, 'verifying', name);
    });
    assert.equal(draws, 1, `${name}: the tracker was created only after the source worked`);
    engine.close();
  }
});

test('promotion: two promotions in one game are each answerable; a conflicting late answer to the FIRST question revokes', async () => {
  const FEN2 = '8/PP5k/8/8/8/8/8/K7 w - - 0 1';
  const route = router();
  await route(start(0, SESSION, FEN2), ON);
  const cam = camera(route, {fen: FEN2});
  assert.equal((await cam.hold(2)).trackingReady, true);
  const ask = async move => { cam.play(move); let r; for (let i = 0; i < 6 && r?.state.status !== 'awaiting-promotion-choice'; i++) r = await cam.send();
    assert.equal(r.state.status, 'awaiting-promotion-choice'); return r.state.pendingQuestion; };
  const q1 = await ask({from: 'a7', to: 'a8', promotion: 'q'});
  assert.equal((await route(answer(q1, {piece: 'q', atMs: cam.now()}), ON)).state.accepted, true);
  assert.equal((await cam.hold(2)).trackingReady, true);
  cam.play('Kh6');
  assert.equal((await cam.hold(11)).state.lastMove?.san, 'Kh6');
  const q2 = await ask({from: 'b7', to: 'b8', promotion: 'n'});
  assert.notEqual(q2.questionId, q1.questionId);
  assert.equal((await route(answer(q2, {piece: 'n', atMs: cam.now()}), ON)).state.accepted, true, 'the second promotion is answerable');
  const ready = await cam.hold(2);
  assert.equal(ready.trackingReady, true); assert.equal(ready.state.fen, cam.chess.fen()); assert.equal(ready.state.movesAccepted, 3);
  const repeat = await route(answer(q1, {piece: 'q', atMs: cam.now()}), ON);
  kept(repeat, ready.state.revision); assert.equal(repeat.trackingReady, true, 'the identical first answer again changes nothing');
  await assert.rejects(route(answer(q1, {piece: 'n', atMs: cam.now()}), ON), refusedWith('ANSWER_CONFLICT'));
  const after = await route(snapshot(cam.now()), ON);
  assert.equal(after.trackingReady, false); assert.equal(after.state.reason, 'invalidated:conflicting-promotion-answer');
});

test('promotion: the answer memory is never evicted; when it is full (1,024 answers on one page) the next answer is refused and revokes', async () => {
  const route = router();
  let first = null, last = null;
  for (let i = 0; i <= 1024; i++) {
    const session = {sessionId: 'wiring', epoch: i + 1};
    const {cam, question} = await atQuestion(route, {session, t0: i * 10_000});
    first ??= {question, session};
    last = {cam, question, session};
    if (i === 1024) break;
    assert.equal((await route(answer(question, {piece: 'q', atMs: cam.now(), session}), ON)).state.accepted, true, `answer ${i + 1}`);
  }
  await assert.rejects(route(answer(last.question, {piece: 'q', atMs: last.cam.now(), session: last.session}), ON), refusedWith('ANSWER_MEMORY_FULL'));
  const after = await route(snapshot(last.cam.now()), ON);
  assert.equal(after.trackingReady, false); assert.equal(after.state.reason, 'invalidated:promotion-memory-full');
  assert.equal((await last.cam.hold(3)).trackingReady, false);
  // The first answer is still remembered: a conflicting answer to it is still caught.
  await assert.rejects(route(answer(first.question, {piece: 'n', atMs: last.cam.now(), session: first.session}), ON), refusedWith('ANSWER_CONFLICT'));
});

test('promotion: answers are remembered across a stop and a new review: a conflicting old answer still revokes the new, ready game', async () => {
  const route = router();
  const {cam, question} = await atQuestion(route);
  assert.equal((await route(answer(question, {piece: 'q', atMs: cam.now()}), ON)).state.accepted, true);
  assert.equal((await cam.hold(2)).trackingReady, true);
  await route(command('trackerStop'), ON);
  await route(start(cam.now(), SESSION, cam.chess.fen()), ON); // a new human review of the promoted board
  assert.equal((await cam.hold(2)).trackingReady, true);
  await assert.rejects(route(answer(question, {piece: 'n', atMs: cam.now()}), ON), refusedWith('ANSWER_CONFLICT'));
  assert.equal((await route(snapshot(cam.now()), ON)).trackingReady, false);
});
