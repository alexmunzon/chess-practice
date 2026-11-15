import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {join} from 'node:path';
import {ReplayRuntime, REPLAY_CLOCK_DOMAIN} from '../src/core/replay-runtime.js';
import {SQUARES} from '../src/core/observation.js';
import {recognizeSimulation} from '../src/core/photo-recognizer.js';

// Opt-in: SPECIAL_GAME_DIR points at the output of
// scripts/simulation/generate-special-game.mjs (kept outside the repository).
// Boards come from the real local Python synthetic recognizer and reach the tracker only
// through the ReplayRuntime JSON contract. evaluatorTruth supplies the one automated
// starting-state review fixture, the renewed reviews after interruptions, and scoring.
const directory = process.env.SPECIAL_GAME_DIR;
const skip = directory ? false : 'SPECIAL_GAME_DIR not set; special game output not available.';
const reviewed = {pieces: true, turn: true, castling: true, enPassant: true, counters: true};
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
const FEN_LIKE = /[pnbrqkPNBRQK1-8]+\/[pnbrqkPNBRQK1-8]+\//;
const REQUIRED_KINDS = ['capture', 'en-passant', 'kingside-castle', 'promotion', 'queenside-castle'];

async function loadGame() {
  const manifest = JSON.parse(await readFile(join(directory, 'replay-manifest.json'), 'utf8'));
  const load = async entry => {
    const bytes = await readFile(join(directory, 'pixels', entry.file));
    assert.equal(sha256(bytes), entry.sha256, `${entry.file} hash`);
    return {...entry, bytes};
  };
  const frames = [];
  for (const entry of manifest.frames) frames.push(await load(entry));
  const interruptions = [];
  for (const entry of manifest.interruptions) interruptions.push(await load(entry));
  return {manifest, frames, interruptions};
}

const observedSquares = prediction => Object.fromEntries(SQUARES.map(square =>
  [square, {label: prediction.squares[square].label, confidence: prediction.squares[square].confidence}]));

test('special game manifest: schema, special moves, truth only inside evaluatorTruth', {skip}, async () => {
  const {manifest, frames, interruptions} = await loadGame();
  const {evaluatorTruth: truth, ...visible} = manifest;
  assert.doesNotMatch(JSON.stringify(visible), FEN_LIKE);
  for (const entry of manifest.frames) assert.deepEqual(Object.keys(entry).sort(), ['file', 'index', 'sha256', 'timestampMs']);
  assert.ok(truth.moves.length >= 20 && truth.moves.length <= 40);
  assert.equal(frames.length, truth.moves.length + 1);
  assert.equal(interruptions.length, 2);
  assert.deepEqual(truth.specialMoveKinds, REQUIRED_KINDS);
  assert.equal(truth.startingFen, 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1');
});

test('recognized special game tracks every FEN; interruptions revoke until renewed review; no guidance', {skip, timeout: 300_000}, async () => {
  const {manifest, frames, interruptions} = await loadGame();
  const truth = manifest.evaluatorTruth;
  const runtime = new ReplayRuntime();
  const identity = {sessionId: 'special-game', epoch: 1};
  let now = 0, requestNumber = 0, sequence = 0;
  const handle = (kind, payload) => {
    const reply = JSON.parse(runtime.handle(JSON.stringify({schemaVersion: 1, requestId: `special-${++requestNumber}`, kind,
      mode: 'trusted-replay', clockDomain: REPLAY_CLOCK_DOMAIN, ...payload})));
    assert.equal(reply.error, undefined, `request ${requestNumber} error ${JSON.stringify(reply.error)}`);
    assert.equal(reply.guidanceAllowed, false); assert.equal(reply.liveGuidanceAllowed, false);
    assert.equal(reply.mode, 'replay-only'); assert.equal(reply.state.historyComplete, false);
    return reply;
  };
  const recognized = new Map();
  const recognize = async frame => {
    if (!recognized.has(frame.file)) {
      const prediction = await recognizeSimulation(frame.bytes);
      assert.equal(prediction.sourceSha256, frame.sha256); assert.equal(prediction.fen, null); assert.equal(prediction.guidanceAllowed, false);
      recognized.set(frame.file, prediction);
    }
    return recognized.get(frame.file);
  };
  // Each frame is submitted twice, 100 ms of virtual time apart, as the tracker requires.
  const submitTwice = async frame => {
    const prediction = await recognize(frame);
    const replies = [];
    for (let k = 0; k < 2; k++) {
      now += 100;
      replies.push(handle('observe', {frame: {identity: {...identity, sequence: sequence++, frameSha256: frame.sha256},
        capturedAtMs: now, squares: observedSquares(prediction)}}));
    }
    return {prediction, replies};
  };
  const review = fen => handle('initialize', {session: identity, fen, reviewed});

  const byAfter = new Map(truth.interruptions.map((meta, i) => [meta.playAfterFrameIndex, {meta, frame: interruptions[i]}]));
  assert.equal(review(truth.startingFen).trackingReady, false); // the one complete starting review
  const tracked = [], kindsTracked = new Set(), reasons = [];
  for (const [i, frame] of frames.entries()) {
    const expected = truth.frames[i];
    const {prediction, replies: [first, second]} = await submitTwice(frame);
    assert.equal(prediction.unknownSquares, 0, `frame ${i} recognized with unknown squares`);
    if (i > 0) assert.equal(first.trackingReady, false, `frame ${i} first sighting must not be ready`);
    assert.equal(second.trackingReady, true, `frame ${i} (${expected.moveSan ?? 'start'}) not tracking-ready: ${second.state.reason}`);
    assert.equal(second.state.fen, expected.expectedFen, `frame ${i} (${expected.moveSan ?? 'start'}) FEN`);
    if (expected.moveSan) assert.equal(second.state.lastMove.san, expected.moveSan, `frame ${i} move`);
    tracked.push(i); expected.moveKinds.forEach(kind => kindsTracked.add(kind));

    const interruption = byAfter.get(i);
    if (!interruption) continue;
    const bad = await submitTwice(interruption.frame);
    for (const reply of bad.replies) assert.equal(reply.trackingReady, false);
    assert.equal(bad.replies[0].state.reason, interruption.meta.expectedReason, `${interruption.meta.kind} reason`);
    if (interruption.meta.kind === 'occluded') assert.ok(bad.prediction.unknownSquares > 0);
    else assert.equal(bad.prediction.unknownSquares, 0);
    reasons.push(bad.replies[0].state.reason);
    // A good frame afterward does not silently restore tracking; renewed review is needed.
    const blocked = await submitTwice(frame);
    for (const reply of blocked.replies) assert.equal(reply.trackingReady, false, `good frame ${i} must stay blocked after ${interruption.meta.kind}`);
    review(interruption.meta.renewedReviewFen);
    const renewed = await submitTwice(frame);
    assert.equal(renewed.replies[1].trackingReady, true); assert.equal(renewed.replies[1].state.fen, expected.expectedFen);
  }
  assert.equal(tracked.length, frames.length);
  assert.deepEqual([...kindsTracked].sort(), REQUIRED_KINDS);
  assert.deepEqual(reasons, ['uncertain-squares', 'not-zero-or-one-legal-move']);
});
