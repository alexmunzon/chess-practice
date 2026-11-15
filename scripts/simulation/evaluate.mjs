#!/usr/bin/env node
/** Offline synthetic-pixel evaluation. Truth never crosses the recognition boundary.
 * Tracker initialization below is an AUTOMATED REVIEW FIXTURE, not human review.
 * This deliberately does not use LiveSession or produce device/browser audio. */
import { readFile, realpath, stat, mkdir, writeFile, mkdtemp, readdir, rm } from 'node:fs/promises';
import { resolve, dirname, relative, isAbsolute } from 'node:path';
import { tmpdir } from 'node:os';
import { spawn } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
import { recognizeSimulation } from '../../src/core/photo-recognizer.js';
import { ObservationTracker, SQUARES } from '../../src/core/observation.js';
import { loadPosition } from '../../src/core/position.js';
import { analyze } from '../../src/core/engine.js';
import { spokenMove, TextSpeechSink } from '../../src/core/live-session.js';

const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const exactKeys = (value, keys) => record(value) && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
const identity = value => typeof value === 'string' && /^[a-zA-Z0-9_.-]{1,96}$/.test(value);
const fullFen = fen => loadPosition(fen).fen({ forceEnpassantSquare: true });
const reviewFixture = Object.freeze({ pieces: true, turn: true, castling: true, enPassant: true, counters: true });
const label = value => value === 'empty' ? '.' : value;

async function readBounded(file, limit) {
  if (!(await stat(file)).isFile()) throw new Error('Expected regular evaluation file.');
  if ((await stat(file)).size > limit) throw new Error('Evaluation file exceeds size limit.');
  const bytes = await readFile(file);
  if (bytes.length > limit) throw new Error('Evaluation file exceeds size limit.');
  return bytes;
}

function truthSquares(fen) {
  const chess = loadPosition(fen);
  return Object.fromEntries(SQUARES.map(square => {
    const piece = chess.get(square);
    return [square, piece ? (piece.color === 'w' ? piece.type.toUpperCase() : piece.type) : '.'];
  }));
}

/** Scores all cells; unknowns and wrong accepted cells remain in denominators. */
export function scorePrediction(prediction, expected, digest = prediction?.sourceSha256) {
  if (!record(prediction) || prediction.schemaVersion !== 1 || prediction.source !== 'synthetic-pixel-inference' ||
      prediction.sourceSha256 !== digest || !/^[0-9a-f]{64}$/.test(digest) || prediction.status !== 'needs-human-review' ||
      prediction.fen !== null || prediction.guidanceAllowed !== false || prediction.threshold !== 0.95 ||
      !exactKeys(prediction.squares, SQUARES) || !exactKeys(expected, SQUARES)) throw new Error('Invalid synthetic prediction boundary.');
  let rawAvailableSquares = 0, rawCorrectSquares = 0, acceptedSquares = 0, acceptedWrongSquares = 0, unknownSquares = 0;
  for (const square of SQUARES) {
    const cell = prediction.squares[square], actual = label(expected[square]);
    if (!/^[.PNBRQKpnbrqk]$/.test(actual) || !record(cell) || typeof cell.rawLabel !== 'string' ||
        !/^[.PNBRQKpnbrqk]$/.test(cell.rawLabel) || !Number.isFinite(cell.confidence) || cell.confidence < 0 || cell.confidence > 1 ||
        cell.label !== (cell.confidence >= 0.95 ? (cell.rawLabel === '.' ? 'empty' : cell.rawLabel) : 'unknown') ||
        (cell.rawLabelAvailable !== undefined && typeof cell.rawLabelAvailable !== 'boolean') ||
        (cell.rawLabelAvailable === false && cell.label !== 'unknown')) throw new Error('Invalid synthetic prediction cell.');
    if (cell.rawLabelAvailable !== false) { rawAvailableSquares++; if (cell.rawLabel === actual) rawCorrectSquares++; }
    if (cell.label === 'unknown') unknownSquares++;
    else { acceptedSquares++; if (label(cell.label) !== actual) acceptedWrongSquares++; }
  }
  return { totalSquares: 64, rawAvailableSquares, rawCorrectSquares, acceptedSquares, acceptedWrongSquares, unknownSquares,
    rawExactBoard: rawAvailableSquares === 64 && rawCorrectSquares === 64, acceptedBoard: unknownSquares === 0,
    acceptedExactBoard: unknownSquares === 0 && acceptedWrongSquares === 0,
    acceptedWrongBoard: unknownSquares === 0 && acceptedWrongSquares > 0 };
}

const newTotals = () => ({ frames: 0, recognitionErrors: 0, totalSquares: 0, rawAvailableSquares: 0, rawCorrectSquares: 0, acceptedSquares: 0,
  acceptedWrongSquares: 0, unknownSquares: 0, rawExactBoards: 0, acceptedBoards: 0, acceptedExactBoards: 0,
  acceptedWrongBoards: 0, readyStates: 0, readyExactStates: 0, readyWrongStates: 0, expectedAbstentions: 0,
  abstentionViolations: 0, requiredReadyStates: 0, missedReadyStates: 0, engineCalls: 0, speechMessages: 0 });

function addScore(totals, frame) {
  totals.frames++; totals.totalSquares += 64;
  if (frame.error) { totals.recognitionErrors++; totals.unknownSquares += 64; }
  else {
    for (const key of ['rawAvailableSquares', 'rawCorrectSquares', 'acceptedSquares', 'acceptedWrongSquares', 'unknownSquares']) totals[key] += frame.score[key];
    for (const [name, key] of [['rawExactBoards', 'rawExactBoard'], ['acceptedBoards', 'acceptedBoard'], ['acceptedExactBoards', 'acceptedExactBoard'], ['acceptedWrongBoards', 'acceptedWrongBoard']]) totals[name] += Number(frame.score[key]);
  }
  if (frame.tracker.guidanceAllowed) {
    totals.readyStates++;
    totals[frame.tracker.fenMatchesTruth ? 'readyExactStates' : 'readyWrongStates']++;
  }
  if (frame.expectedAbstention) { totals.expectedAbstentions++; totals.abstentionViolations += Number(frame.tracker.guidanceAllowed || frame.score?.acceptedBoard === true); }
  if (frame.expectedReadyFromFixture) { totals.requiredReadyStates++; totals.missedReadyStates += Number(!frame.tracker.guidanceAllowed || !frame.tracker.fenMatchesTruth); }
  totals.engineCalls += Number(Boolean(frame.engine));
  totals.speechMessages += Number(Boolean(frame.engine?.speechText));
}

async function loadDataset(input) {
  const root = await realpath(resolve(input)), pixelRoot = await realpath(resolve(root, 'pixels'));
  const indexBytes = await readBounded(resolve(pixelRoot, 'index.json'), 1024 * 1024);
  const truthBytes = await readBounded(resolve(root, 'evaluator/truth.json'), 8 * 1024 * 1024);
  const index = JSON.parse(indexBytes), truth = JSON.parse(truthBytes);
  if (!exactKeys(index, Object.hasOwn(index, 'video') ? ['schemaVersion', 'mode', 'frames', 'video'] : ['schemaVersion', 'mode', 'frames']) || index.schemaVersion !== 1 || index.mode !== 'synthetic-pixels' ||
      !Array.isArray(index.frames) || !index.frames.length || index.frames.length > 2000 ||
      !Array.isArray(truth?.frames) || !Array.isArray(truth.sessions) || truth.frames.length !== index.frames.length) throw new Error('Invalid synthetic dataset manifest.');
  const truths = new Map(), sessions = new Map();
  for (const session of truth.sessions) {
    if (!record(session) || !identity(session.id) || sessions.has(session.id) || typeof session.historyDescription !== 'string') throw new Error('Invalid synthetic session fixture.');
    sessions.set(session.id, { ...session, initialFen: fullFen(session.initialFen) });
  }
  for (const frame of truth.frames) {
    if (!record(frame) || !identity(frame.id) || truths.has(frame.id) || !sessions.has(frame.session) ||
        !['dev', 'heldout', 'challenge'].includes(frame.split) || typeof frame.expectedAbstention !== 'boolean' ||
        !/^[0-9a-f]{64}$/.test(frame.sourceSha256) || !exactKeys(frame.squares, SQUARES)) throw new Error('Invalid evaluator truth frame.');
    const expected = truthSquares(frame.fen);
    if (SQUARES.some(square => label(frame.squares[square]) !== expected[square])) throw new Error('Truth FEN and square labels disagree.');
    truths.set(frame.id, { ...frame, fen: fullFen(frame.fen) });
  }
  let previous = -1, activeSession = null;
  const ids = new Set(), closedSessions = new Set(), frames = [];
  for (const frame of index.frames) {
    if (!exactKeys(frame, ['id', 'file', 'timestampMs']) || !identity(frame.id) || ids.has(frame.id) ||
        typeof frame.file !== 'string' || !/^[a-zA-Z0-9_.-]+\.(png|jpe?g|webp)$/i.test(frame.file) ||
        !Number.isFinite(frame.timestampMs) || frame.timestampMs <= previous || !truths.has(frame.id)) throw new Error('Invalid pixel-only frame index.');
    const expected = truths.get(frame.id);
    if (expected.timestampMs !== undefined && expected.timestampMs !== frame.timestampMs) throw new Error('Frame timestamps disagree.');
    if (activeSession !== expected.session) {
      if (activeSession) closedSessions.add(activeSession);
      if (closedSessions.has(expected.session)) throw new Error('Session frames must be contiguous.');
      activeSession = expected.session;
      if (sessions.get(activeSession).initialFen !== expected.fen) throw new Error('Initial fixture FEN must match first frame of its session.');
    }
    const file = await realpath(resolve(pixelRoot, frame.file)), rel = relative(pixelRoot, file);
    if (rel.startsWith('..') || isAbsolute(rel)) throw new Error('Pixel path escapes its dataset.');
    const sourceSha256 = hash(await readBounded(file, 12 * 1024 * 1024));
    if (sourceSha256 !== expected.sourceSha256) throw new Error('Source pixel bytes do not match frozen truth hash.');
    ids.add(frame.id); previous = frame.timestampMs;
    frames.push({ ...frame, path: file, truth: expected, originalSourceSha256: sourceSha256 });
  }
  return { frames, sessions, pixelRoot, video: index.video, indexSha256: hash(indexBytes), truthSha256: hash(truthBytes) };
}

async function decodeDatasetVideo(dataset, requestedPath) {
  const metadata = dataset.video;
  if (!exactKeys(metadata, ['file', 'fps', 'frameCount', 'sourceSha256']) ||
      typeof metadata.file !== 'string' || !/^[a-zA-Z0-9_.-]+\.mp4$/.test(metadata.file) ||
      !Number.isFinite(metadata.fps) || metadata.fps <= 0 || metadata.fps > 60 ||
      metadata.frameCount !== dataset.frames.length || !/^[0-9a-f]{64}$/.test(metadata.sourceSha256)) throw new Error('Invalid generated-video index.');
  const videoPath = await realpath(resolve(requestedPath));
  if (videoPath !== await realpath(resolve(dataset.pixelRoot, metadata.file)) || relative(dataset.pixelRoot, videoPath).startsWith('..')) throw new Error('--video must name this dataset\'s indexed generated video.');
  const sourceSha256 = hash(await readBounded(videoPath, 256 * 1024 * 1024));
  if (sourceSha256 !== metadata.sourceSha256) throw new Error('Generated video hash does not match index.');
  const directory = await mkdtemp(resolve(tmpdir(), 'chess-synthetic-video-'));
  const started = performance.now();
  try {
    await new Promise((resolveRun, reject) => {
      const child = spawn('/usr/local/bin/ffmpeg', ['-nostdin', '-hide_banner', '-loglevel', 'error', '-i', videoPath,
        '-map', '0:v:0', '-vsync', '0', '-frames:v', String(metadata.frameCount + 1), '-start_number', '0', resolve(directory, '%06d.png')],
      { stdio: ['ignore', 'ignore', 'pipe'], detached: true });
      let error, output = 0;
      const stop = message => { error ??= new Error(message); try { process.kill(-child.pid, 'SIGKILL'); } catch {} };
      const interrupt = () => stop('Generated-video decoding interrupted.');
      const timer = setTimeout(() => stop('Generated-video decoding exceeded 60 seconds.'), 60_000);
      process.once('SIGINT', interrupt); process.once('SIGTERM', interrupt);
      child.on('error', problem => { error ??= problem; });
      child.stderr.on('data', chunk => { output += chunk.length; if (output > 64 * 1024) stop('Generated-video decoder exceeded diagnostic limit.'); });
      child.on('close', code => {
        clearTimeout(timer); process.removeListener('SIGINT', interrupt); process.removeListener('SIGTERM', interrupt);
        if (error) reject(error); else if (code !== 0) reject(new Error('Generated-video decoding failed.')); else resolveRun();
      });
    });
    const files = (await readdir(directory)).sort();
    if (files.length !== metadata.frameCount || files.some((file, i) => file !== `${String(i).padStart(6, '0')}.png`)) throw new Error('Decoded video frame count differs from source index.');
    return { directory, paths: files.map(file => resolve(directory, file)), sourceSha256, fps: metadata.fps,
      frameCount: files.length, decodeMs: performance.now() - started };
  } catch (error) { await rm(directory, { recursive: true, force: true }); throw error; }
}

/** Dependency injection is for evaluator tests only; CLI always uses real adapters. */
export async function evaluateDataset({ input, video, recognizer = recognizeSimulation, engine = analyze, movetimeMs = 100 } = {}) {
  if (!Number.isInteger(movetimeMs) || movetimeMs < 50 || movetimeMs > 3000) throw new Error('Invalid bounded engine time.');
  const dataset = await loadDataset(input);
  const decoded = video ? await decodeDatasetVideo(dataset, video) : null;
  try {
  const report = { schemaVersion: 1, mode: 'synthetic-pixel-evaluation', hardwareVerified: false, realWorldAccuracyClaim: false,
    recognitionAdapter: recognizer === recognizeSimulation ? 'actual-local-synthetic-pixel-recognizer' : 'test-injected',
    engineAdapter: engine === analyze ? 'actual-local-stockfish' : 'test-injected',
    speechMode: 'TextSpeechSink-text-only-no-audio', historyComplete: false,
    review: 'AUTOMATED REVIEW FIXTURE: explicit initial full FEN supplied by evaluator truth; no human review occurred.',
    dataset: { indexSha256: dataset.indexSha256, truthSha256: dataset.truthSha256,
      inputKind: decoded ? 'decoded-generated-video' : 'generated-png-frames',
      ...(decoded ? { video: { sourceSha256: decoded.sourceSha256, fps: decoded.fps, frameCount: decoded.frameCount, decodeMs: decoded.decodeMs } } : {}) },
    limitations: ['Synthetic screen-like pieces and visible calibration markers are not physical-board validation.',
      'Splits separate generated sessions/scenes, not necessarily chess positions or piece artwork.',
      'Tracker time uses deterministic capture timestamps; processing latency is measured separately and is not a live deadline test.',
      'Imported full FEN supplies metadata as an automated fixture; pre-fixture repetition history is unknown.'],
    splits: { dev: newTotals(), heldout: newTotals(), challenge: newTotals() }, frames: [], sessions: [],
    engine: { attempted: 0, completed: 0, speechMessages: [] }, staleProbes: [] };
  let tracker, currentSession, now = 0, sequence = 0, sourceId, sessionLastSplit, speech, devAttempted = false, truthRun;
  async function runGuidance(id) {
    const state = tracker.snapshot();
    if (!state.guidanceAllowed) return null;
    report.engine.attempted++;
    const requestId = `synthetic-evaluation:${id}`, controller = new AbortController();
    const isCurrent = () => { const current = tracker.snapshot(); return current.guidanceAllowed && current.revision === state.revision && current.fen === state.fen; };
    const activity = { inputFen: state.fen, movetimeMs, requestId, review: 'AUTOMATED REVIEW FIXTURE', speechText: null };
    try {
      const result = await engine({ fen: state.fen, confirmation: true, movetimeMs, requestId }, { signal: controller.signal });
      if (!isCurrent() || result.requestId !== requestId || result.fen !== state.fen) throw new Error('Engine result is stale or belongs to another position.');
      activity.result = result;
      if (result.bestMove) {
        const text = spokenMove(state.fen, result.bestMove);
        await speech.speak(text, { signal: controller.signal, isCurrent });
        if (!isCurrent()) throw new Error('Text speech became stale.');
        activity.speechText = text;
        report.engine.speechMessages.push({ frameId: id, text, fen: state.fen, mode: 'text-only' });
      }
      report.engine.completed++;
    } catch (error) { activity.error = String(error.message ?? error); }
    finally { controller.abort(); }
    return activity;
  }
  async function closeSession() {
    if (!tracker) return;
    now += 1001;
    const state = tracker.tick();
    const priorMessages = speech.messages.length, priorCalls = report.engine.attempted;
    const activity = await runGuidance(`stale:${currentSession}`);
    report.staleProbes.push({ session: currentSession, split: sessionLastSplit, at: now, state,
      engineCalls: report.engine.attempted - priorCalls, additionalSpeechMessages: speech.messages.length - priorMessages,
      passed: !state.guidanceAllowed && activity === null && report.engine.attempted === priorCalls && speech.messages.length === priorMessages });
    tracker.disconnect(); speech.cancel();
  }
  for (const [frameIndex, item] of dataset.frames.entries()) {
    const expected = item.truth;
    if (currentSession !== expected.session) {
      await closeSession();
      currentSession = expected.session; now = item.timestampMs; sequence = 0; sourceId = `simulation:${currentSession}`; truthRun = null;
      tracker = new ObservationTracker({ clock: () => now }); speech = new TextSpeechSink();
      tracker.connect(sourceId);
      const fixture = dataset.sessions.get(currentSession);
      tracker.confirm({ fen: fixture.initialFen, reviewed: reviewFixture });
      report.sessions.push({ id: currentSession, initialFen: fixture.initialFen, initialization: 'AUTOMATED REVIEW FIXTURE',
        historyDescription: fixture.historyDescription, historyComplete: false });
    }
    now = item.timestampMs; sessionLastSplit = expected.split;
    // This expectation is exclusively a scoring target, never an observation or tracker input.
    if (truthRun?.fen === expected.fen) truthRun.count++;
    else truthRun = { fen: expected.fen, count: 1, firstAt: item.timestampMs };
    const started = performance.now();
    const frame = { id: item.id, split: expected.split, session: currentSession, timestampMs: item.timestampMs,
      expectedAbstention: expected.expectedAbstention, truthFen: expected.fen, originalSourceSha256: item.originalSourceSha256,
      expectedReadyFromFixture: expected.split !== 'challenge' && !expected.expectedAbstention && truthRun.count >= 2 && item.timestampMs - truthRun.firstAt >= 50,
      prediction: null, score: null, error: null };
    let state;
    try {
      const bytes = await readBounded(decoded ? decoded.paths[frameIndex] : item.path, 12 * 1024 * 1024);
      frame.sourceSha256 = hash(bytes);
      if (!decoded && frame.sourceSha256 !== expected.sourceSha256) throw new Error('Pixel bytes do not match frozen truth hash.');
      // EXACTLY ONE ARGUMENT. No path, FEN, truth, labels, session, or scene is passed.
      const prediction = await recognizer(bytes);
      frame.score = scorePrediction(prediction, expected.squares, frame.sourceSha256);
      frame.prediction = prediction;
      state = tracker.ingest({ sourceId, epoch: tracker.snapshot().epoch, sequence: sequence++, capturedAt: item.timestampMs,
        squares: Object.fromEntries(SQUARES.map(square => [square, { label: prediction.squares[square].label, confidence: prediction.squares[square].confidence }])) });
    } catch (error) {
      frame.error = { code: error.code ?? 'EVALUATION_FRAME_ERROR', message: String(error.message ?? error) };
      state = tracker.edit(); // Never retain ready state across a failed or malformed result.
    }
    frame.processingMs = performance.now() - started;
    frame.tracker = { ...state, fenMatchesTruth: state.fen === expected.fen };
    // Select from recognized/tracked state, never from truth correctness. Wrong ready states count below.
    if ((expected.split === 'dev' && state.guidanceAllowed && !devAttempted) || expected.split === 'challenge') {
      if (expected.split === 'dev') devAttempted = true;
      frame.engine = await runGuidance(item.id);
    }
    addScore(report.splits[expected.split], frame); report.frames.push(frame);
  }
  await closeSession();
  report.safetyPassed = Object.values(report.splits).every(split => split.recognitionErrors === 0 && split.acceptedWrongBoards === 0 && split.acceptedWrongSquares === 0 && split.readyWrongStates === 0 && split.abstentionViolations === 0) && report.staleProbes.every(probe => probe.passed);
  report.positiveCoveragePassed = ['dev', 'heldout'].every(name => report.splits[name].frames > 0 && report.splits[name].acceptedExactBoards === report.splits[name].frames);
  report.trackingCoveragePassed = ['dev', 'heldout'].every(name => report.splits[name].requiredReadyStates > 0 && report.splits[name].missedReadyStates === 0) &&
    report.sessions.filter(session => report.frames.some(frame => frame.session === session.id && frame.split !== 'challenge')).every(session => report.frames.some(frame => frame.session === session.id && frame.expectedReadyFromFixture));
  report.engineTextPassed = report.splits.dev.engineCalls === 1 && report.splits.dev.speechMessages === 1 && report.engine.completed === 1 && report.engine.speechMessages.length === 1;
  report.passed = report.safetyPassed && report.positiveCoveragePassed && report.trackingCoveragePassed && report.engineTextPassed;
  return report;
  } finally { if (decoded) await rm(decoded.directory, { recursive: true, force: true }); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const args = process.argv.slice(2);
    if (![4, 6].includes(args.length) || args[0] !== '--input' || args[2] !== '--out' || (args.length === 6 && args[4] !== '--video')) throw new Error('Usage: node scripts/simulation/evaluate.mjs --input DATASET_DIR --out REPORT.json [--video GENERATED.mp4]');
    const report = await evaluateDataset({ input: args[1], video: args[5] });
    const output = resolve(args[3]); await mkdir(dirname(output), { recursive: true });
    await writeFile(output, JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify({ report: output, passed: report.passed, splits: report.splits, engine: report.engine }));
    if (!report.passed) process.exitCode = 1;
  } catch (error) { console.error(`Synthetic evaluation failed: ${error.message}`); process.exitCode = 1; }
}
