import { spawn } from 'node:child_process';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import {validateCalibrationRequest, validateCalibrationPreview, validateManualProvenance} from './photo-calibration.js';

const script = fileURLToPath(new URL('../../scripts/recognition/run_whole_photo.py', import.meta.url));
const manualScript = fileURLToPath(new URL('../../scripts/recognition/manual_photo.py', import.meta.url));
const simulationScript = fileURLToPath(new URL('../../scripts/simulation/recognize.py', import.meta.url));
const python = '/Library/Frameworks/Python.framework/Versions/3.11/bin/python3';
export const MAX_PHOTO_BYTES = 12 * 1024 * 1024;
const OUTPUT_LIMIT = 128 * 1024;
export class PhotoRecognitionError extends Error {
  constructor(message, code) { super(message); this.name = 'PhotoRecognitionError'; this.code = code; }
}
const failure = (code, message) => new PhotoRecognitionError(message, code);

function imageType(bytes) {
  if (bytes.length >= 3 && bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255) return 'jpg';
  if (bytes.length >= 8 && bytes.subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10]))) return 'png';
  if (bytes.length >= 12 && bytes.toString('ascii', 0, 4) === 'RIFF' && bytes.toString('ascii', 8, 12) === 'WEBP') return 'webp';
  throw failure('INVALID_IMAGE', 'Choose a JPEG, PNG or WebP image.');
}

function validate(result, digest, calibration, synthetic = false) {
  const invalid = () => { throw failure('INVALID_RESULT', 'Local recognizer returned an invalid review draft.'); };
  if (!result || result.schemaVersion !== 1 || result.source !== (synthetic ? 'synthetic-pixel-inference' : 'real-image-inference') || result.sourceSha256 !== digest ||
      result.status !== 'needs-human-review' || result.fen !== null || result.guidanceAllowed !== false ||
      !Array.isArray(result.imageSize) || result.imageSize.length !== 2 || !result.imageSize.every(n => Number.isInteger(n) && n > 0 && n <= 8192) ||
      result.imageSize[0] * result.imageSize[1] > 25_000_000 || result.threshold !== 0.95 ||
      !result.squares || Object.keys(result.squares).length !== 64 ||
      ['humanReviewed','humanConfirmed','reviewed','confirmed','confirmation'].some(k=>Object.hasOwn(result,k)&&result[k]!==false)) invalid();
  const rows = [];
  for (let rank = 8; rank >= 1; rank--) {
    let row = '', empty = 0;
    for (const file of 'abcdefgh') {
      const s = result.squares[file + rank];
      if (!s || typeof s.rawLabel !== 'string' || !/^[.PNBRQKpnbrqk]$/.test(s.rawLabel) ||
          !Number.isFinite(s.confidence) || s.confidence < 0 || s.confidence > 1 ||
          s.label !== (s.confidence >= 0.95 ? (s.rawLabel === '.' ? 'empty' : s.rawLabel) : 'unknown')) invalid();
      if (s.rawLabel === '.') empty++;
      else { if (empty) row += empty; empty = 0; row += s.rawLabel; }
    }
    if (empty) row += empty;
    rows.push(row);
  }
  if (result.rawPlacement !== rows.join('/')) invalid();
  if (synthetic) {
    if (result.model !== 'synthetic-screen-template-v1' || result.pipelineVersion !== 'visible-markers-v1' ||
        !Number.isFinite(result.elapsedMs) || result.elapsedMs < 0 || !Array.isArray(result.limitations)) invalid();
    return result;
  }
  if (calibration) {
    try { validateManualProvenance(result,calibration); } catch { invalid(); }
    return result;
  }
  if (result.model !== 'joelseytre/chessq-lite' || result.modelRevision !== '7b33e1d47be02ce67b8e30ff7f09418166037d99' ||
      result.numericalValidationStatus !== 'failed-one-logit-tolerance-on-evaluation-mac' || result.provenance?.numericalValidationPassed !== false ||
      result.provenance?.computeUnits !== 'CPU_AND_GPU' || !result.timing ||
      !['verificationMs','preprocessMs','compileAndLoadMs','totalMs'].every(k => Number.isFinite(result.timing[k]) && result.timing[k] >= 0) ||
      !Array.isArray(result.timing.inferenceMs) || result.timing.inferenceMs.length !== 3 ||
      !result.timing.inferenceMs.every(n => Number.isFinite(n) && n >= 0)) invalid();
  return result;
}

/** Dependency injection is for deterministic lifecycle tests, never HTTP request options.
 * Local Mac evaluator only. No model downloads or silent installation. */
export function createPhotoRecognizer({spawnProcess = spawn, tempRoot = tmpdir(), timeoutMs = 120_000} = {}) {
  let active = false;
  if (!Number.isInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 120_000) throw new TypeError('Invalid recognition deadline');
  async function processPhoto(bytes, {signal, calibration, operation='recognize'} = {}) {
    if (!Buffer.isBuffer(bytes) || bytes.length === 0 || bytes.length > MAX_PHOTO_BYTES) throw failure('INVALID_IMAGE', 'Image must be at most 12 MiB.');
    const type = imageType(bytes);
    if (signal?.aborted) throw failure('ABORTED', 'Photo recognition cancelled.');
    if (active) throw failure('BUSY', 'Another photo is being reviewed. Cancel it or wait.');
    let directory;
    // Copy bytes before the first await; caller mutation cannot change checked input.
    bytes = Buffer.from(bytes);
    const digest = createHash('sha256').update(bytes).digest('hex');
    if (operation==='preview' && calibration===undefined) throw failure('INVALID_CALIBRATION','Choose four board corners and an explicit orientation.');
    if (calibration!==undefined) {
      if (bytes.length>8*1024*1024) throw failure('INVALID_IMAGE','Calibrated images must be at most 8 MiB.');
      calibration=validateCalibrationRequest(calibration,{digest,reviewed:operation!=='preview'});
    }
    active = true;
    try {
      directory = await mkdtemp(join(tempRoot, 'chess-photo-'));
      const input = join(directory, `photo.${type}`);
      await writeFile(input, bytes, {mode:0o600, flag:'wx'});
      // The synthetic recognizer receives only pixels in an opaque private file.
      // No evaluator truth, FEN, scene configuration or original filename crosses this boundary.
      const args=['-B',operation==='synthetic'?simulationScript:script,input];
      if (calibration) {
        const request=join(directory,'calibration-request.json');
        await writeFile(request,JSON.stringify(calibration),{mode:0o600,flag:'wx'});
        args.splice(1,args.length-1,manualScript,operation==='preview'?'preview':'recognize',input,request);
      }
      if (signal?.aborted) throw failure('ABORTED', 'Photo recognition cancelled.');
      const output = await new Promise((resolve, reject) => {
        let child, timer, terminalError, total = 0, chunks = [];
        const kill = () => {
          // Detached process group includes the Python child and Swift grandchild.
          if (spawnProcess === spawn && child?.pid) {
            try { process.kill(-child.pid, 'SIGKILL'); } catch {}
          } else { try { child?.kill('SIGKILL'); } catch {} }
        };
        const stop = error => { terminalError ??= error; kill(); };
        const abort = () => stop(failure('ABORTED', 'Photo recognition cancelled.'));
        const cleanup = () => { clearTimeout(timer); signal?.removeEventListener('abort', abort); };
        try {
          child = spawnProcess(python, args, {stdio:['ignore','pipe','pipe'], detached:true,
            env:{...process.env, TMPDIR:directory, PYTHONDONTWRITEBYTECODE:'1', CHESS_COREML_CPU_DIAGNOSTIC:'0'}});
        } catch { reject(failure('UNAVAILABLE', 'Local photo recognizer is unavailable.')); return; }
        child.on('error', () => { terminalError ??= failure('UNAVAILABLE', 'Local photo recognizer is unavailable.'); });
        child.on('close', code => {
          cleanup();
          if (terminalError) reject(terminalError);
          else if (code !== 0) reject(failure('RECOGNITION_FAILED', 'Local photo recognition failed. Check the local evaluation setup and image.'));
          else resolve(Buffer.concat(chunks).toString('utf8'));
        });
        const collect = (chunk, stdout) => {
          total += chunk.length;
          if (total > OUTPUT_LIMIT) { stop(failure('OUTPUT_LIMIT', 'Local recognition output exceeded its limit.')); return; }
          if (stdout && !terminalError) chunks.push(Buffer.from(chunk));
        };
        child.stdout.on('data', chunk => collect(chunk, true));
        child.stderr.on('data', chunk => collect(chunk, false));
        timer = setTimeout(() => stop(failure('TIMEOUT', 'Local photo recognition exceeded its deadline.')), timeoutMs);
        signal?.addEventListener('abort', abort, {once:true});
        if (signal?.aborted) abort();
      });
      let result;
      try { result = JSON.parse(output); } catch { throw failure('INVALID_RESULT', 'Local recognizer returned an invalid review draft.'); }
      if (signal?.aborted) throw failure('ABORTED', 'Photo recognition cancelled.');
      if (operation==='preview') {
        try { return validateCalibrationPreview(result,calibration); }
        catch { throw failure('INVALID_RESULT','Local calibration returned an invalid grid preview.'); }
      }
      return validate(result, digest, calibration, operation==='synthetic');
    } finally {
      try { if (directory) await rm(directory, {recursive:true, force:true}); }
      finally { active = false; }
    }
  }
  const recognize=(bytes,{signal,calibration}={})=>processPhoto(bytes,{signal,calibration});
  recognize.calibrate=(bytes,{signal,calibration}={})=>processPhoto(bytes,{signal,calibration,operation:'preview'});
  recognize.simulation=(bytes,{signal}={})=>processPhoto(bytes,{signal,operation:'synthetic'});
  return recognize;
}

export const recognizePhoto = createPhotoRecognizer();
export const calibratePhoto = recognizePhoto.calibrate;
export const recognizeSimulation = recognizePhoto.simulation;
