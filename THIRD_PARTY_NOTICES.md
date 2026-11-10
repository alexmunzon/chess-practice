# Third-party software

This local development project installs exact versions from the official npm registry using package-lock.json. No dependency install scripts are required (`npm ci --ignore-scripts`). Runtime chess analysis stays on this computer; there is no remote analysis service.

## chess.js 1.4.0
- Rules, FEN parsing and legal move generation.
- License: BSD-2-Clause. Copyright and full license: `licenses/chess.js-BSD-2-Clause.txt`.
- Source: https://github.com/jhlywa/chess.js
- Version source: https://github.com/jhlywa/chess.js/tree/v1.4.0
- Package: https://www.npmjs.com/package/chess.js/v/1.4.0

## Stockfish.js 19.0.1 / Stockfish 19
- Full, single-threaded WebAssembly NNUE engine (`stockfish-19-single.js` and matching `.wasm`), run as an isolated local Node child process.
- License: GPL-3.0, as declared by the package. Full license: `licenses/stockfish-GPL-3.0.txt`.
- Port and build source: https://github.com/nmrugg/stockfish.js
- Upstream Stockfish: https://github.com/official-stockfish/Stockfish
- Package: https://www.npmjs.com/package/stockfish/v/19.0.1
- Preserve upstream copyright, license notices, corresponding source and build instructions when redistributing engine binaries. A source link alone is not a substitute for satisfying applicable GPL source-delivery obligations. This project is a local development prototype, not a prepared binary distribution. Do not ship node_modules or packaged engine binaries until corresponding-source delivery is verified.

The project manifest declares GPL-3.0-or-later for this prototype. Chess.js remains under its BSD license. The engine is unmodified. Bounded engine search is strong analysis, not a mathematical proof of the best move in every position.
