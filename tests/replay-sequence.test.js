import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {join} from 'node:path';
import {DeviceGameSession} from '../src/core/device-game-session.js';
import {SQUARES} from '../src/core/observation.js';
import {recognizeSimulation} from '../src/core/photo-recognizer.js';

// Opt-in: REPLAY_SEQUENCE_DIR points at the output of
// scripts/simulation/select-replay-sequence.mjs (kept outside the repository).
// Recognized boards come from the real local Python synthetic recognizer.
// evaluatorTruth is used only for the one automated starting-state review
// fixture and for scoring; it never reaches recognition or tracking input.
const directory = process.env.REPLAY_SEQUENCE_DIR;
const skip = directory ? false : 'REPLAY_SEQUENCE_DIR not set; replay sequence output not available.';
const reviewed = {pieces: true, turn: true, castling: true, enPassant: true, counters: true};
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
const FEN_LIKE = /[pnbrqkPNBRQK1-8]+\/[pnbrqkPNBRQK1-8]+\//;

/** PNG chunk types other than the minimal image chunks could carry hidden text. */
function pngChunkTypes(bytes) {
  assert.equal(bytes.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
  const types = [];
  for (let offset = 8; offset < bytes.length;) {
    const length = bytes.readUInt32BE(offset);
    types.push(bytes.subarray(offset + 4, offset + 8).toString('latin1'));
    offset += 12 + length;
  }
  return types;
}

async function loadSequence() {
  const manifest = JSON.parse(await readFile(join(directory, 'replay-manifest.json'), 'utf8'));
  const load = async entry => {
    const bytes = await readFile(join(directory, 'pixels', entry.file));
    assert.equal(sha256(bytes), entry.sha256, `${entry.file} hash`);
    return bytes;
  };
  const frames = [];
  for (const entry of manifest.frames) frames.push({...entry, bytes: await load(entry)});
  return {manifest, frames, interruption: {...manifest.interruption, bytes: await load(manifest.interruption)}};
}

const observedSquares = prediction => Object.fromEntries(SQUARES.map(square =>
  [square, {label: prediction.squares[square].label, confidence: prediction.squares[square].confidence}]));

test('replay manifest keeps position information inside evaluatorTruth only', {skip}, async () => {
  const {manifest, frames, interruption} = await loadSequence();
  assert.ok(frames.length >= 8 && frames.length <= 20);
  const {evaluatorTruth, ...visible} = manifest;
  assert.doesNotMatch(JSON.stringify(visible), FEN_LIKE);
  for (const entry of manifest.frames) assert.deepEqual(Object.keys(entry).sort(), ['file', 'index', 'sha256', 'timestampMs']);
  assert.equal(evaluatorTruth.frames.length, frames.length);
  for (const {bytes} of [...frames, interruption]) {
    assert.deepEqual([...new Set(pngChunkTypes(bytes))].filter(type => !['IHDR', 'IDAT', 'IEND'].includes(type)), []);
  }
});

test('recognized replay frames track to every expected FEN; interruption revokes; no output permission', {skip, timeout: 120_000}, async () => {
  const {manifest, frames, interruption} = await loadSequence();
  const truth = manifest.evaluatorTruth;
  const clockDomain = 'replay-sequence-test';
  const identity = {sessionId: 'replay-sequence', epoch: 1};
  let now = 10_000, requestNumber = 0, sequence = 0;
  const bridge = new DeviceGameSession({replayClock: {clockDomain, now: () => now}});
  const handle = (kind, payload) => {
    const reply = bridge.handle(JSON.stringify({schemaVersion: 1, requestId: `replay-${++requestNumber}`, kind,
      mode: 'trusted-replay', clockDomain, ...payload}));
    assert.equal(reply.guidanceAllowed, false); assert.equal(reply.liveGuidanceAllowed, false);
    assert.equal(reply.mode, 'replay-only'); assert.equal(reply.state.historyComplete, false);
    return reply;
  };
  const observe = async (bytes, sha) => {
    const prediction = await recognizeSimulation(bytes);
    assert.equal(prediction.sourceSha256, sha); assert.equal(prediction.fen, null); assert.equal(prediction.guidanceAllowed, false);
    return {prediction, reply: handle('observe', {frame: {identity: {...identity, sequence: sequence++, frameSha256: sha},
      capturedAtMs: now, squares: observedSquares(prediction)}})};
  };

  // One complete starting-state review (automated fixture standing in for the human review).
  const start = now;
  assert.equal(handle('initialize', {session: identity, fen: truth.startingFen, reviewed}).trackingReady, false);
  let stableChecks = 0;
  for (const [i, frame] of frames.entries()) {
    now = start + 1 + frame.timestampMs;
    const expected = truth.frames[i];
    const {prediction, reply} = await observe(frame.bytes, frame.sha256);
    assert.equal(prediction.unknownSquares, 0, `frame ${i} recognized with unknown squares`);
    const stable = i > 0 && truth.frames[i - 1].expectedFen === expected.expectedFen;
    if (stable) {
      assert.equal(reply.trackingReady, true, `frame ${i} should be tracking-ready`);
      assert.equal(reply.state.fen, expected.expectedFen, `frame ${i} FEN`);
      if (expected.moveSan) assert.equal(reply.state.lastMove.san, expected.moveSan);
      stableChecks++;
    } else assert.equal(reply.trackingReady, false, `frame ${i} is the first sighting of its position`);
  }
  assert.equal(stableChecks, new Set(truth.frames.map(frame => frame.expectedFen)).size);

  // The occluded/challenge frame must withhold and revoke tracking.
  now += 100;
  const {prediction, reply} = await observe(interruption.bytes, interruption.sha256);
  assert.ok(prediction.unknownSquares > 0);
  assert.equal(reply.trackingReady, false);
  assert.equal(reply.state.reason, 'uncertain-squares');
  // A good frame afterward does not silently restore tracking; renewed review is needed.
  const last = frames.at(-1), finalFen = truth.frames.at(-1).expectedFen;
  for (let k = 0; k < 2; k++) { now += 100; assert.equal((await observe(last.bytes, last.sha256)).reply.trackingReady, false); }
  handle('initialize', {session: identity, fen: finalFen, reviewed});
  let ready;
  for (let k = 0; k < 2; k++) { now += 100; ready = (await observe(last.bytes, last.sha256)).reply; }
  assert.equal(ready.trackingReady, true); assert.equal(ready.state.fen, finalFen);
});
