import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync, writeFileSync, mkdirSync} from 'node:fs';
import {Chess} from 'chess.js';
import {ReplayRuntime, REPLAY_CLOCK_DOMAIN, REPLAY_REPLY_KEYS, REPLAY_ERROR_KEYS} from '../src/core/replay-runtime.js';
import {SQUARES} from '../src/core/observation.js';
import {START_FEN} from '../src/core/position.js';

// SYNTHETIC OBSERVATIONS ONLY. Square labels are derived from FEN by the pinned chess.js,
// at confidence 1; no image, recognizer or human review is simulated or validated here.
// The `reviewed` flags below are a test fixture, not a human action.
const FIXTURE = new URL('./fixtures/replay-runtime/transcript.json', import.meta.url);
const reviewed = {pieces:true,turn:true,castling:true,enPassant:true,counters:true};
const fullFen = chess => chess.fen({forceEnpassantSquare:true});
function syntheticSquares(fen) {
  const chess = new Chess(fen);
  return Object.fromEntries(SQUARES.map(square => {
    const piece = chess.get(square);
    return [square, {label:piece ? (piece.color === 'w' ? piece.type.toUpperCase() : piece.type) : 'empty', confidence:1}];
  }));
}
// Deterministic synthetic frame hash: SHA-256 of the synthetic labels, not of any image.
const syntheticSha = squares => createHash('sha256').update(JSON.stringify(squares)).digest('hex');

function checkReply(text) {
  assert.equal(typeof text, 'string');
  const reply = JSON.parse(text);
  assert.equal(reply.guidanceAllowed, false); assert.equal(reply.liveGuidanceAllowed, false);
  assert.equal(reply.runtime, 'on-device-local'); assert.equal(reply.mode, 'replay-only');
  if (reply.error) {
    assert.deepEqual(Object.keys(reply), REPLAY_ERROR_KEYS);
    assert.deepEqual(Object.keys(reply.error), ['code','message','trackerRevoked']);
  } else {
    assert.deepEqual(Object.keys(reply), Object.hasOwn(reply,'ignored') ? [...REPLAY_REPLY_KEYS,'ignored'] : REPLAY_REPLY_KEYS);
    assert.deepEqual(Object.keys(reply.state), ['status','reason','revision','fen','lastMove','historyComplete']);
    assert.equal(reply.state.historyComplete, false);
  }
  return reply;
}

function rig({sessionId = 'replay-test', epoch = 1} = {}) {
  const runtime = new ReplayRuntime();
  const session = {sessionId, epoch};
  let requestNumber = 0, sequence = 0;
  const request = (kind, payload = {}, patch = {}) => ({schemaVersion:1, requestId:`req-${++requestNumber}`, kind,
    mode:'trusted-replay', clockDomain:REPLAY_CLOCK_DOMAIN, ...payload, ...patch});
  const send = value => checkReply(runtime.handle(typeof value === 'string' ? value : JSON.stringify(value)));
  const frame = (fen, capturedAtMs, identity = session) => {
    const squares = syntheticSquares(fen);
    return {identity:{sessionId:identity.sessionId, epoch:identity.epoch, sequence:sequence++, frameSha256:syntheticSha(squares)},
      capturedAtMs, squares};
  };
  return {runtime, session, request, send, frame,
    initialize: (fen = START_FEN, s = session) => send(request('initialize', {session:{...s}, fen, reviewed:{...reviewed}})),
    observe: (fen, at, identity) => send(request('observe', {frame:frame(fen, at, identity)})),
    snapshot: (s = session) => send(request('snapshot', {session:{...s}})),
    invalidate: reason => send(request('invalidate', {session:{...session}, reason})),
    setSession: s => Object.assign(session, s)};
}
const readyRig = () => { const r = rig(); r.initialize(); r.observe(START_FEN, 100); assert.equal(r.observe(START_FEN, 160).trackingReady, true); return r; };

// The replayed game: 1.e4 Nf6 2.e5 d5 3.exd6 e.p. exd6 (capture) 4.Nf3 Be7 5.Bc4 O-O 6.O-O
const GAME = ['e4','Nf6','e5','d5','exd6','exd6','Nf3','Be7','Bc4','O-O','O-O'];

function buildTranscript() {
  const r = rig({sessionId:'replay-golden'});
  const entries = [];
  const exchange = value => { const text = r.runtime.handle(JSON.stringify(value)); checkReply(text); entries.push({request:value, reply:JSON.parse(text)}); return {text, reply:JSON.parse(text)}; };
  exchange(r.request('initialize', {session:{...r.session}, fen:START_FEN, reviewed:{...reviewed}}));
  const chess = new Chess();
  let t = 100;
  const position = () => [exchange(r.request('observe', {frame:r.frame(fullFen(chess), t)})).reply,
    exchange(r.request('observe', {frame:r.frame(fullFen(chess), t + 60)})).reply];
  position();
  for (const san of GAME) { chess.move(san); t += 300; position(); }
  exchange(r.request('snapshot', {session:{...r.session}}));
  exchange(r.request('analyze', {fen:fullFen(chess)})); // engine kinds are never served here
  exchange(r.request('snapshot', {session:{...r.session}}));
  return {entries, finalFen:fullFen(chess)};
}
const serialize = entries => '[\n' + entries.map(entry => JSON.stringify(entry)).join(',\n') + '\n]\n';

test('envelope strictness: every malformed or foreign request gets a structured error and revokes as the tracker dictates', () => {
  const cases = [
    ['non-string', r => 42],
    ['malformed JSON', r => '{'],
    ['unknown kind', r => r.request('replay', {session:{...r.session}})],
    ...['validate','analyze','position','move','cancel','bestmove'].map(kind => [`engine kind ${kind}`, r => r.request(kind, {fen:START_FEN})]),
    ['extra top-level key', r => r.request('snapshot', {session:{...r.session}, debug:true})],
    ['missing top-level key', r => { const v = r.request('snapshot', {session:{...r.session}}); delete v.clockDomain; return v; }],
    ['extra frame key', r => r.request('observe', {frame:{...r.frame(START_FEN, 200), receivedAtHostMs:200}})],
    ['missing frame key', r => { const f = r.frame(START_FEN, 200); delete f.capturedAtMs; return r.request('observe', {frame:f}); }],
    ['missing square', r => { const f = r.frame(START_FEN, 200); delete f.squares.e4; return r.request('observe', {frame:f}); }],
    ['wrong mode', r => r.request('snapshot', {session:{...r.session}}, {mode:'live'})],
    ['wrong clockDomain', r => r.request('snapshot', {session:{...r.session}}, {clockDomain:'media-PTS'})],
    ['wrong schemaVersion', r => r.request('snapshot', {session:{...r.session}}, {schemaVersion:2})],
    ['incomplete FEN', r => r.request('initialize', {session:{...r.session}, fen:START_FEN.split(' ')[0], reviewed})],
    ['partial review', r => r.request('initialize', {session:{...r.session}, fen:START_FEN, reviewed:{...reviewed, enPassant:false}})],
    ['extra review flag', r => r.request('initialize', {session:{...r.session}, fen:START_FEN, reviewed:{...reviewed, auto:true}})],
    ['unsupported invalidation reason', r => r.request('invalidate', {session:{...r.session}, reason:'timeout'})],
    ['stale epoch initialize', r => r.request('initialize', {session:{...r.session, epoch:0}, fen:START_FEN, reviewed})],
  ];
  for (const [label, make] of cases) {
    const r = readyRig(); const value = make(r);
    const reply = r.send(value);
    assert.ok(reply.error, label); assert.equal(reply.error.trackerRevoked, true, label);
    assert.equal(r.snapshot().trackingReady, false, `${label} must revoke tracking`);
  }
  // Foreign session or retired epoch: tracker ignores and stays unchanged; wrapper reports an error.
  for (const foreign of [{sessionId:'someone-else', epoch:1}, {sessionId:'replay-test', epoch:2}]) {
    for (const kind of ['observe','snapshot','invalidate']) {
      const r = readyRig(); const before = r.snapshot();
      const payload = kind === 'observe' ? {frame:r.frame(START_FEN, 999, foreign)} :
        kind === 'invalidate' ? {session:foreign, reason:'reset'} : {session:foreign};
      const reply = r.send(r.request(kind, payload));
      assert.equal(reply.error.code, 'STALE_SESSION'); assert.equal(reply.error.trackerRevoked, false);
      assert.equal(r.runtime.virtualClockMs, 160, 'foreign frames never move virtual time');
      const after = r.snapshot(); assert.equal(after.trackingReady, true); assert.deepEqual(after.state, before.state);
    }
  }
  // Retired epoch after a newer session took over.
  const r = readyRig(); r.setSession({epoch:2}); r.initialize();
  const old = r.send(r.request('initialize', {session:{sessionId:'replay-test', epoch:1}, fen:START_FEN, reviewed}));
  assert.equal(old.error.code, 'STALE_IDENTITY'); assert.equal(old.requestId.startsWith('req-'), true); assert.equal(old.kind, 'initialize');
  const garbage = JSON.parse(new ReplayRuntime().handle('{'));
  assert.equal(garbage.requestId, null); assert.equal(garbage.kind, null);
});

test('virtual clock is max(previous, frame time), never reads host clocks', () => {
  const source = readFileSync(new URL('../src/core/replay-runtime.js', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /\bDate\b|\bperformance\b|hrtime|process\./);
  const r = rig();
  const RealDate = globalThis.Date, perf = Object.getOwnPropertyDescriptor(globalThis, 'performance');
  const trap = () => { throw new Error('host clock read'); };
  try {
    globalThis.Date = new Proxy(RealDate, {construct: trap, apply: trap, get: (target, key) => key === 'now' ? trap : target[key]});
    Object.defineProperty(globalThis, 'performance', {configurable:true, get: trap});
    assert.equal(r.runtime.virtualClockMs, 0);
    r.initialize(); assert.equal(r.runtime.virtualClockMs, 0);
    r.observe(START_FEN, 100); assert.equal(r.runtime.virtualClockMs, 100);
    assert.equal(r.observe(START_FEN, 400).trackingReady, true); assert.equal(r.runtime.virtualClockMs, 400);
    // A later sequence carrying an earlier timestamp cannot move the clock back.
    const back = r.observe(START_FEN, 300); assert.equal(back.ignored, 'repeated-or-reordered-frame');
    assert.equal(r.runtime.virtualClockMs, 400);
    r.snapshot(); r.invalidate('reset'); assert.equal(r.runtime.virtualClockMs, 400);
    // A rejected frame (bad envelope) never moves the clock either.
    assert.ok(r.send(r.request('observe', {frame:r.frame(START_FEN, 900)}, {mode:'x'})).error);
    assert.equal(r.runtime.virtualClockMs, 400);
  } finally {
    globalThis.Date = RealDate; Object.defineProperty(globalThis, 'performance', perf);
  }
});

test('huge, fractional or unsafe capturedAtMs is rejected and never moves the virtual clock', () => {
  for (const bad of [1e300, Number.MAX_SAFE_INTEGER + 2, 100.5, Number.MAX_VALUE]) {
    const r = readyRig();
    const before = r.runtime.virtualClockMs;
    const reply = r.observe(START_FEN, bad);
    assert.ok(reply.error, `capturedAtMs ${bad} must be rejected`);
    assert.equal(reply.error.trackerRevoked, true);
    assert.equal(r.runtime.virtualClockMs, before, `capturedAtMs ${bad} must not move the clock`);
    // After a renewed review the replay clock still works normally.
    r.setSession({epoch: 2}); assert.equal(r.initialize().state.status, 'stabilizing');
    r.observe(START_FEN, before + 100);
    assert.equal(r.observe(START_FEN, before + 200).trackingReady, true);
    assert.equal(r.runtime.virtualClockMs, before + 200);
  }
});

test('golden transcript: full legal game with en passant, capture and both castlings reproduces byte-for-byte', () => {
  const {entries, finalFen} = buildTranscript();
  if (process.env.UPDATE_REPLAY_FIXTURE === '1') {
    mkdirSync(new URL('./fixtures/replay-runtime/', import.meta.url), {recursive:true});
    writeFileSync(FIXTURE, serialize(entries));
  }
  const golden = readFileSync(FIXTURE, 'utf8');
  assert.equal(serialize(entries), golden);
  // Replaying the stored requests through a fresh runtime yields identical reply bytes.
  const runtime = new ReplayRuntime();
  for (const entry of JSON.parse(golden)) assert.equal(runtime.handle(JSON.stringify(entry.request)), JSON.stringify(entry.reply));
  // Game content checks.
  const observes = entries.filter(e => e.request.kind === 'observe');
  assert.equal(observes.length, 2 * (GAME.length + 1));
  const chess = new Chess();
  for (let i = 0; i <= GAME.length; i++) {
    if (i > 0) chess.move(GAME[i - 1]);
    const [first, second] = [observes[2 * i].reply, observes[2 * i + 1].reply];
    assert.equal(first.trackingReady, false, `position ${i} needs a second stable frame`);
    assert.equal(second.trackingReady, true, `position ${i} ready`);
    assert.equal(second.state.fen, fullFen(chess));
    assert.equal(second.state.lastMove?.san ?? null, i ? GAME[i - 1] : null);
  }
  assert.equal(chess.history({verbose:true}).some(m => m.isEnPassant()), true);
  assert.equal(chess.history({verbose:true}).filter(m => m.isKingsideCastle()).length, 2);
  assert.equal(chess.history({verbose:true}).filter(m => m.captured).length, 2);
  assert.equal(finalFen, fullFen(chess));
  const tail = entries.slice(-3).map(e => e.reply);
  assert.equal(tail[0].trackingReady, true); assert.equal(tail[1].error.trackerRevoked, true);
  assert.equal(tail[2].trackingReady, false); assert.equal(tail[2].state.reason, 'manual-edit');
});

test('stable-frame requirement: two matching frames at least 50 ms apart', () => {
  const r = rig(); r.initialize();
  assert.equal(r.observe(START_FEN, 100).trackingReady, false);
  assert.equal(r.observe(START_FEN, 149).trackingReady, false);
  assert.equal(r.observe(START_FEN, 150).trackingReady, true);
  const chess = new Chess(); chess.move('d4');
  assert.equal(r.observe(fullFen(chess), 300).trackingReady, false);
  const early = r.observe(fullFen(chess), 340); assert.equal(early.trackingReady, false); assert.equal(early.state.fen, START_FEN);
  const ready = r.observe(fullFen(chess), 350); assert.equal(ready.trackingReady, true); assert.equal(ready.state.lastMove.san, 'd4');
});

test('skipped ply, reordered sequence, >1 s gap and unknown squares revoke or withhold tracking', () => {
  const skip = readyRig(); const two = new Chess(); two.move('e4'); two.move('e5');
  const skipped = skip.observe(fullFen(two), 300);
  assert.equal(skipped.trackingReady, false); assert.equal(skipped.state.reason, 'not-zero-or-one-legal-move');
  skip.observe(fullFen(two), 400); assert.equal(skip.observe(fullFen(two), 500).trackingReady, false);
  skip.initialize(fullFen(two)); skip.observe(fullFen(two), 600);
  assert.equal(skip.observe(fullFen(two), 700).trackingReady, true, 'a fresh full review restores tracking');

  const order = readyRig(); const late = order.frame(START_FEN, 120);
  late.identity.sequence = 0; // sequence already consumed
  const reordered = order.send(order.request('observe', {frame:late}));
  assert.equal(reordered.ignored, 'repeated-or-reordered-frame'); assert.equal(reordered.trackingReady, true);
  assert.equal(reordered.lastFrame.sequence, 1, 'an ignored frame never becomes lastFrame');
  // Reusing the latest sequence with a different time is an identity conflict: revoked.
  const order2 = readyRig(); const lower = order2.frame(START_FEN, 150); lower.identity.sequence = 1;
  const conflict = order2.send(order2.request('observe', {frame:lower}));
  assert.equal(conflict.error.code, 'FRAME_IDENTITY_CONFLICT'); assert.equal(conflict.error.trackerRevoked, true);
  assert.equal(order2.snapshot().trackingReady, false);

  const gap = readyRig(); const stale = gap.observe(START_FEN, 1161);
  assert.equal(stale.trackingReady, false); assert.equal(stale.state.reason, 'observation-timeout');
  const edge = readyRig(); assert.equal(edge.observe(START_FEN, 1160).trackingReady, true, 'exactly 1000 ms is still fresh');

  for (const cell of [{label:'unknown', confidence:0}, {label:'P', confidence:0.94}]) {
    const u = readyRig(); const f = u.frame(START_FEN, 300); f.squares.e2 = cell;
    const blocked = u.send(u.request('observe', {frame:f}));
    assert.equal(blocked.trackingReady, false); assert.equal(blocked.state.reason, 'uncertain-squares');
    u.observe(START_FEN, 400); assert.equal(u.observe(START_FEN, 500).trackingReady, false);
  }
});

test('reordered frames are ignored without changing state', () => {
  const r = rig(); r.initialize();
  const a = r.frame(START_FEN, 100), b = r.frame(START_FEN, 200);
  r.send(r.request('observe', {frame:b}));
  const out = r.send(r.request('observe', {frame:a}));
  assert.equal(out.ignored, 'repeated-or-reordered-frame'); assert.equal(out.trackingReady, false);
  assert.equal(out.lastFrame.sequence, b.identity.sequence);
});

test('each invalidation reason and stale epoch revokes tracking until a new review', () => {
  for (const reason of ['manual-edit','interrupted','background','reset','disconnect']) {
    const r = readyRig(); const reply = r.invalidate(reason);
    assert.equal(reply.trackingReady, false); assert.equal(reply.state.reason, 'manual-edit');
    assert.equal(Object.hasOwn(reply, 'invalidationReason'), false);
    r.observe(START_FEN, 300); assert.equal(r.observe(START_FEN, 400).trackingReady, false);
  }
  const r = readyRig(); r.setSession({epoch:2}); const fresh = r.initialize();
  assert.equal(fresh.trackingReady, false); assert.equal(fresh.session.epoch, 2);
  const stale = r.observe(START_FEN, 300, {sessionId:'replay-test', epoch:1});
  assert.equal(stale.error.code, 'STALE_SESSION');
  r.observe(START_FEN, 300); assert.equal(r.observe(START_FEN, 400).trackingReady, true);
  const retired = r.send(r.request('initialize', {session:{sessionId:'replay-test', epoch:1}, fen:START_FEN, reviewed}));
  assert.equal(retired.error.code, 'STALE_IDENTITY'); assert.equal(r.snapshot().trackingReady, false);
});
