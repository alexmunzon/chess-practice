#!/usr/bin/env node
import { createReadStream } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { Chess } from 'chess.js';
import { ObservationTracker, SQUARES } from '../src/core/observation.js';

const MAX_BYTES = 2 * 1024 * 1024;
const MAX_EVENTS = 2000;
const object = value => value && typeof value === 'object' && !Array.isArray(value);
const keys = (value, required) => object(value) && Object.keys(value).length === required.length && required.every(key => Object.hasOwn(value, key));

export function replayObservations(document) {
  if (!keys(document, ['version', 'kind', 'events']) || document.version !== 1 || !['synthetic-observations', 'recognizer-observations'].includes(document.kind) || !Array.isArray(document.events) || document.events.length > MAX_EVENTS) throw new Error('Expected version 1 replay with kind and at most 2000 events.');
  let now = 0;
  const tracker = new ObservationTracker({ clock: () => now });
  const output = [];
  for (const [index, event] of document.events.entries()) {
    if (!object(event) || typeof event.at !== 'number' || !Number.isFinite(event.at) || event.at < now) throw new Error(`Event ${index}: at must be nonnegative monotonic milliseconds.`);
    now = event.at;
    let state;
    const shape = {
      connect: ['type', 'at', 'sourceId'], confirm: ['type', 'at', 'fen', 'reviewed'],
      observation: ['type', 'at', 'frame'], tick: ['type', 'at'], edit: ['type', 'at'], disconnect: ['type', 'at'],
    }[event.type];
    if (!shape || !keys(event, shape)) throw new Error(`Event ${index}: invalid event type or fields.`);
    switch (event.type) {
      case 'connect': state = tracker.connect(event.sourceId); break;
      case 'confirm': state = tracker.confirm({ fen: event.fen, reviewed: event.reviewed }); break;
      case 'observation': state = tracker.ingest(event.frame); break;
      case 'tick': state = tracker.tick(); break;
      case 'edit': state = tracker.edit(); break;
      case 'disconnect': state = tracker.disconnect(); break;
    }
    output.push({ index, at: now, type: event.type, ...state });
  }
  return { version: 1, kind: document.kind, classifierImplemented: false, hardwareVerified: false, states: output };
}

export function syntheticDemo() {
  const chess = new Chess();
  const frame = (sequence, at) => ({ type: 'observation', at, frame: {
    sourceId: 'synthetic-demo', epoch: 1, sequence, capturedAt: at,
    squares: Object.fromEntries(SQUARES.map(square => {
      const piece = chess.get(square);
      return [square, { label: piece ? (piece.color === 'w' ? piece.type.toUpperCase() : piece.type) : 'empty', confidence: 1 }];
    })),
  } });
  const events = [
    { type: 'connect', at: 0, sourceId: 'synthetic-demo' },
    { type: 'confirm', at: 0, fen: chess.fen(), reviewed: { pieces: true, turn: true, castling: true, enPassant: true, counters: true } },
    frame(0, 10), frame(1, 70),
  ];
  chess.move('e4'); events.push(frame(2, 100), frame(3, 160), { type: 'tick', at: 1161 });
  return { version: 1, kind: 'synthetic-observations', events };
}

async function readBounded(source) {
  const chunks = []; let size = 0;
  for await (const chunk of source) {
    size += chunk.length;
    if (size > MAX_BYTES) { source.destroy(); throw new Error('Replay exceeds 2 MiB limit.'); }
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const args = process.argv.slice(2);
    if (args.length !== 1) throw new Error('Usage: node scripts/replay-observations.js <replay.json | - | --synthetic-demo | --emit-synthetic-demo>');
    const arg = args[0];
    const document = arg === '--synthetic-demo' || arg === '--emit-synthetic-demo' ? syntheticDemo() : await readBounded(arg === '-' ? process.stdin : createReadStream(arg));
    console.log(JSON.stringify(arg === '--emit-synthetic-demo' ? document : replayObservations(document), null, 2));
  } catch (error) {
    console.error(`Replay failed: ${error.message}`); process.exitCode = 1;
  }
}
