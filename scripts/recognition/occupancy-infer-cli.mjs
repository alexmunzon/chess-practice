#!/usr/bin/env node
// Thin long-lived wrapper around inferMove for the Python screen pipeline (experiment, not app code).
// Reads one JSON object per line on stdin: {"id": any, "fen": "<six-field FEN>",
//   "occupancy": [64 x "empty"|"white"|"black"|"unknown" in a1,b1,...,h8 order], "options": {...}?}
// Writes one JSON line per request on stdout: {"id", "result"} or {"id", "error"}.
// One process serves a whole game, so a game does not spawn hundreds of node processes.
import readline from 'node:readline';
import { inferMove } from '../../src/core/occupancy-move-inference.js';

const lines = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
lines.on('line', line => {
  if (!line.trim()) return;
  let id = null;
  try {
    const request = JSON.parse(line);
    id = request.id ?? null;
    const started = process.hrtime.bigint();
    const result = inferMove({ fen: request.fen, occupancy: request.occupancy }, request.options ?? {});
    const ms = Number(process.hrtime.bigint() - started) / 1e6;
    process.stdout.write(JSON.stringify({ id, result, ms }) + '\n');
  } catch (error) {
    process.stdout.write(JSON.stringify({ id, error: String(error?.message ?? error) }) + '\n');
  }
});
