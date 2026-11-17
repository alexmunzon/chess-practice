# Chess Companion

Offline chess study with local Stockfish analysis and explicit human review of the board.

Chess Companion combines an iPhone app, a browser development interface, and a research pipeline for reading chessboard images. The working iPhone flows are **Study** (review a saved position, then analyze it) and **Replay** (step through bundled synthetic games). The project is for personal study and consensual practice—not undisclosed assistance in competitive games.

**Status:** working offline prototype; experimental recognition and tracking. Live camera, physical-board recognition, and glasses integration are not ready for use. This repository contains source code, not a packaged app release.

## Start locally

The browser interface requires **Node.js 22 or newer** and npm. The test suite also invokes **Python 3.11 or newer with NumPy and Pillow**, pinned in [`requirements-test.txt`](requirements-test.txt). From the repository root:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --only-binary=:all: -r requirements-test.txt
npm ci --ignore-scripts
npm test
npm start
```

The environment-activation command above is for macOS/Linux; on Windows use `.venv\Scripts\Activate.ps1` in PowerShell.

Open [localhost:4174](http://127.0.0.1:4174). Stop the server with **Ctrl+C**.

Dependency installation uses the committed npm lockfile and Python version pins, and accesses the npm and PyPI registries. Normal chess analysis runs locally; the server binds to the loopback interface, so it is accessible only from the same computer. No account or hosted backend is required for the browser interface.

1. Load the starting position, enter a complete FEN, or use the piece-and-state editor.
2. Review the pieces, side to move, castling rights, en passant, and move counters.
3. Validate and confirm the position, then request analysis.
4. Editing the position or interrupting analysis clears the previous recommendation.

FEN describes a position and its current state; it cannot establish the full history of a game. Imported positions are validated, not proven historically reachable. Full-game repetition adjudication is not implemented.

## What works—and what is experimental

| Area | Current capability | Limit |
| --- | --- | --- |
| Browser study | Board editor, legal moves, promotion, local analysis, image reference, cancellation | Saved-photo recognition requires a separately prepared local evaluator |
| iPhone Study | Bundled-image recognition, full position review, on-device rules and Stockfish, text advice | Uses synthetic fixtures; not a live camera workflow |
| iPhone Replay | Bundled games, including special moves, reviewed starting state and tracked progression | Scripted test evidence does not substitute for a human usability study |
| Screen-board recognition | Corner detection, square reading, move inference and uncertainty checks | Development research on simulated pictures; physical-board accuracy is not established |
| Additional occupancy tracker and piece guard | Experimental safety modules with dedicated tests | Occupancy tracker is off by default; piece guard is not connected to the app |
| Glasses and audio | Adapter source and isolated mock experiments | No end-to-end real-glasses or audible-output validation |

The core rule is simple: **a recommendation belongs to one reviewed position**. Uncertain observations, position changes, reset, and interruptions must withdraw it. Late engine replies must not restore withdrawn advice. Recognition produces a proposal for review, not permission to analyze an unconfirmed board.

## Architecture

```text
Saved board image / manual position
                |
        Recognition proposal
                |
   Human review + rules validation
                |
       Local Stockfish analysis
                |
      Position-bound text advice
```

| Location | Responsibility |
| --- | --- |
| [`src/core/`](src/core/) | Chess rules, engine lifecycle, reviewed sessions and tracking contracts |
| [`src/server.js`](src/server.js), [`src/app.js`](src/app.js) | Loopback service and browser development interface |
| [`native/ChessCompanionApp/`](native/ChessCompanionApp/) | SwiftUI Study and Replay app |
| [`native/ChessCompanionRuntime/`](native/ChessCompanionRuntime/) | Local WebKit bridge to rules and Stockfish |
| [`scripts/recognition/`](scripts/recognition/) | Python recognition and evaluation experiments |
| [`scripts/simulation/`](scripts/simulation/) | Synthetic image/video generation and evaluation |
| [`tests/`](tests/) | Regression, safety, engine and recognition tests |

Rules use **chess.js 1.4.0**. Analysis uses **Stockfish.js 19.0.1**, with a single-threaded WebAssembly engine. Dependencies are pinned in [`package-lock.json`](package-lock.json).

## Checks

```sh
# JavaScript regression suite, including real local engine checks
npm test

# JavaScript plus Python recognition suites
scripts/check-all.sh
```

The JavaScript suite also runs Python-backed synthetic-image checks, so Node alone is insufficient. It needs Python 3 with NumPy/Pillow and permission to open local loopback listeners. Some tests are opt-in or depend on external fixtures; skipped checks are reported separately.

The full recognition suite is currently a **maintainer-environment check**, not a clean-clone guarantee. It needs Python 3, NumPy, Pillow, FFmpeg for video checks, and, for some cases, macOS tools or generated evidence outside the repository. Some research paths still refer to the original Mac workspace. Do not interpret missing fixtures or skipped tests as successful validation.

The [source-check workflow](.github/workflows/checks.yml) runs the main suite on Linux with the pinned dependencies. See [GitHub Actions](https://github.com/alexmunzon/chess-practice/actions) for current run status. It does not run the Mac, Simulator, or phone checks.

See the dated [verification record](docs/VERIFICATION.md) for results, commands, and evidence limits. The updated November 17 phone build passed **34 of 34 checks** after the runtime safety fix; the combined Mac check passed **12 of 12 suites**. Phone checks used scripted review and bundled synthetic pictures, and do not validate live glasses. Earlier interrupted attempts and test limitations remain in the verification record.

## Build the iPhone app

The native app needs macOS, Xcode, the installed iOS SDK, and the frozen synthetic fixture corpus described in the [native app guide](native/ChessCompanionApp/README.md). Engine assets and generated app bundles stay outside this repository. Use a local build folder outside cloud-synced Documents/Desktop for signing; Finder metadata added by sync can make code signing reject an otherwise valid generated bundle. There is no one-command clean-clone iPhone installation yet.

After installing the locked Node dependencies, prepare runtime assets in a **new empty directory outside the repository**:

```sh
node scripts/build-device-runtime.mjs --out /absolute/path/to/empty-runtime-assets
```

Use [`prepare_app.py`](native/ChessCompanionApp/prepare_app.py) with the prepared assets and verified fixture paths to compile a Simulator or device bundle. Its `--help` lists the inputs. Device signing and installation are separate steps documented in the [signing guide](native/ChessCompanionApp/signing/README.md); they require your own configured signing identity. Do not copy another developer's provisioning files.

The iOS Simulator has a known intermittent engine freeze that is not reproduced by the recorded phone searches. Its cause is unresolved. See [engine behavior and limits](docs/PREWARMED_ENGINE.md).

## Development and evidence

- [Plan](docs/PLAN.md): current priorities and historical decisions.
- [Verification](docs/VERIFICATION.md): dated results, evidence types, and open checks.
- [Synthetic simulation](docs/SIMULATION_PLAN.md): generation, evaluation and dataset limits.
- [Screen pipeline](docs/SCREEN_PIPELINE.md): recognition policy and failure cases.
- [Development workflow](docs/WORKFLOW.md): bounded changes, independent review and checkpoints.

Synthetic pictures, Mac execution, Simulator runs, and physical-phone tests are distinct evidence. None establishes physical-board or glasses accuracy. The existing held-out picture sets have already been used; new generalization claims require genuinely unseen data.

## License and distribution

Source is licensed under **GPL-3.0-or-later**; see [LICENSE](LICENSE). Preserve the [third-party notices](THIRD_PARTY_NOTICES.md) and dependency license texts in [`licenses/`](licenses/).

A source repository is not a prepared binary distribution. Before redistributing Stockfish binaries, WebAssembly, `node_modules`, or an app bundling the engine, verify the applicable GPL corresponding-source delivery requirements. Do not commit signing identities, provisioning profiles, credentials, or generated engine assets.
