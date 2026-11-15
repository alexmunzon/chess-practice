// Test-only Node worker bridge. Uses the installed pinned engine and its WASM;
// no browser, iOS, package/resource delivery or physical-device evidence.
const {parentPort} = require('node:worker_threads');
const createEngine = require('../../node_modules/stockfish/bin/stockfish-19-single.js');
const engine = createEngine();
engine.listener = line => parentPort.postMessage(line);
parentPort.on('message', command => engine.processCommand(command));
