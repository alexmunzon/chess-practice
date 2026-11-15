# Licence audit: what is inside the iPhone app, and what each licence asks of you

Audited 2026-11-15 against the built bundle `~/chess-builds/integration-2026-11-15/device-normal/ChessCompanion.app` (read-only), `package-lock.json`, `node_modules`, `scripts/build-device-runtime.mjs` and `native/ChessCompanionApp/prepare_app.py`. **I am not a lawyer.** This reads the licence texts; it is not legal advice.

**Terms.** *Convey* = give a copy to someone else (GPLv3 s.0). *Object code* = the compiled form (the `.wasm`, the app binary). *Corresponding Source* = all source needed to rebuild that exact object code, plus build scripts (GPLv3 s.1). *Notice* = the copyright line and licence text a licence says must travel with copies.

## 1. Everything that ends up inside the .app

| Component | Version | Comes from | Licence (text location) | Notice inside the built .app? | Source for this exact version |
|---|---|---|---|---|---|
| Stockfish engine, WebAssembly build (`Runtime/engine/stockfish.wasm`, 99 MB) | Stockfish.js 19.0.1 (Stockfish 19) | npm `stockfish` 19.0.1, `node_modules/stockfish/bin/stockfish-19-single.wasm` | GPL-3.0 (`node_modules/stockfish/Copying.txt`; same text as `licenses/stockfish-GPL-3.0.txt`, checked byte-identical) | Yes: `Runtime/licenses/Stockfish-Copying.txt` | Tag `v19.0.1` (commit 0d5dd79) at github.com/nmrugg/stockfish.js; README says it builds with emscripten 6.0.9 via `build.js`. Not tested that it rebuilds the identical bytes. |
| Neural network embedded in that wasm (`nn-1a298aa575a0.nnue`, found by scanning the file) | as embedded | Stockfish's network files | Not stated in the npm package. Stockfish README: nets trained on Leela Chess Zero data under ODbL. | Not separately | Not checked whether the `v19.0.1` tag contains or fetches this file. See Unknowns. |
| Engine loader glue (`Runtime/engine/stockfish.js`) | 19.0.1 | `node_modules/stockfish/bin/stockfish-19-single.js` | Header says "License: GPLv3"; README: the package is GPL-3.0, non-engine code MIT | Yes: copyright header kept in the file | Same tag as above |
| chess.js rules library (`Runtime/vendor/chess.js`) | 1.4.0 | npm `chess.js` 1.4.0, `dist/esm/chess.js` | BSD-2-Clause (`node_modules/chess.js/LICENSE`; copy `licenses/chess.js-BSD-2-Clause.txt`) | Yes: `Runtime/licenses/chess.js-LICENSE` | github.com/jhlywa/chess.js tag v1.4.0; npm tarball |
| Project's own JavaScript (`Runtime/runtime.js`, `index.html`, `core/*.js`) | working tree | `native/ChessCompanionRuntime/`, `src/core/` | Project declares GPL-3.0-or-later (`package.json`, root `LICENSE`) | No: no project copyright or licence file in the bundle | Only this private repo; most of these files are **uncommitted** (`git status`: untracked) |
| Project's own Swift app binary (`ChessCompanion`, 1.2 MB) | working tree | `native/ChessCompanionApp`, `-Runtime`, `-Vision`, `-Integration` | Same as above (no per-file headers) | No | Private repo plus a source snapshot in the build folder `device-normal/sources/`; app folder is uncommitted |
| Synthetic board images (`synthetic-fixture.png`, `Study/*.png`) and piece templates (`classic-templates-v1.json`) | 2026-11-11 | `scripts/simulation/render.py`, `appearance.py` | Project's own. `appearance.py` says "Original simple vector silhouettes"; `OFFLINE-STUDY-NOTICE.txt` says "Owned synthetic images" | Yes, the origin note is in `OFFLINE-STUDY-NOTICE.txt` | In repo |
| `THIRD_PARTY_NOTICES.md`, `runtime-manifest.json`, `app-assets.json`, `Info.plist` | n/a | repo | Notices only | Yes | In repo |

Not inside: no fonts (SwiftUI uses Apple system fonts; the web page uses system fonts and Unicode chess symbols), no Meta SDK (`otool -L` lists only Apple system libraries; no `MWDAT` text in the binary), no Swift packages from outside the project (all four `Package.swift` files depend only on each other), no ML models, no photos.

## 2. Licence-relevant things in the repo that are NOT bundled

- **ChessQ-lite model** (joelseytre/chessq-lite, rev 7b33e1d): PolyForm Noncommercial 1.0.0 with DINOv2 Apache notices, stored outside the repo. Rule recorded: "Do not redistribute weights" (`native/PhotoRecognition/README.md`). Must never go into a shared or sold app.
- **cstr ONNX classifier**: "MIT on card; no LICENSE file found" (`docs/RECOGNITION_RESEARCH.md`). Licence is unconfirmed.
- **Datasets considered, none downloaded**: ChessReD / ChessReD2K are CC BY-NC-SA 4.0 (non-commercial); chesscog renders and Fenit are CC BY 4.0; ChessRender360 has "Licence not found"; Ultralytics YOLO models are AGPL-3.0 (`docs/RECOGNITION_RESEARCH.md`).
- **Test media**: Pexels video 6599638 under the Pexels License, not CC0 (`docs/VIDEO_EVALUATION.md`); Wikimedia photo by Staxringold, CC BY-SA 3.0 (`native/BoardVision/README.md`); two failed candidates (`docs/PUBLIC_VIDEO_SOURCES.md`). No media is stored in the repo. Only metadata JSON is kept.
- **Meta Wearables DAT SDK** pinned at exactly 1.0.1, rev 0bd3692 (`docs/HARDWARE_COMPATIBILITY.md`). Only compiled in a probe. `IOSAdapters.swift` imports it only `#if canImport(MWDATCore)`. The repo's LICENSE (read on the main branch, not the 1.0.1 tag) points to the "Meta Wearables Developer Terms": proprietary terms, not open source. Its licence is not recorded anywhere in this repo.
- **Piece artwork**: original to this project (`scripts/simulation/appearance.py` docstring). Who drew it beyond "this project" is not documented.
- **`evidence/*.jpg`**: screenshots of this project's own UI (`AGENTS.md` permits this).

## 3. What each situation requires

**Key texts.** GPLv3 s.2: you may "make, run and propagate" works you do not convey, without conditions. s.0 leaves running a program and "modifying a private copy" outside "propagate". s.4 and s.6: conveying object code requires the licence text, intact notices, and Corresponding Source by one of the methods in s.6a–e. For downloads, s.6d means equivalent access to the source "through the same place" at no extra charge, and you stay responsible for keeping it available. s.6c (passing on someone else's written offer) does not apply, because the engine came from npm without one. s.10: "You may not impose any further restrictions". BSD-2-Clause asks only that binary copies reproduce the copyright notice, conditions and disclaimer. The Stockfish README says that whenever you distribute it you "MUST always include the license and the full source code" or a pointer to it, for "the exact binary". (Re-fetched 2026-11-15 from github.com/official-stockfish/Stockfish README "Terms of use".)

### (1) Private use on your own phone (today)
- [x] Nothing is conveyed, so GPL s.2 places no conditions. BSD conditions apply only to redistribution.
- [x] Notices are kept anyway (`Runtime/licenses/`, `THIRD_PARTY_NOTICES.md`).
- [x] Non-commercial models and media stay out of the app.
- Nothing needed today.

### (2) A few friends (ad hoc or direct install, or TestFlight)
Giving a friend a copy is conveying, even if it's free and only to a few people. Stockfish's README explicitly allows sharing "among your friends", but only on the conditions above.
- [x] GPL text and chess.js BSD notice are inside the .app.
- [ ] **Corresponding Source for the engine** goes with every copy, or sits next to it with clear directions. That means the `v19.0.1` source, the exact `.nnue` file, and build steps. A bare link is weaker: `THIRD_PARTY_NOTICES.md` itself says a link "alone is not a substitute". Keep it available as long as you distribute.
- [ ] **Your own app code.** Whether a separate engine running in a web view makes the whole app a "work based on" Stockfish is unsettled. Two programs that only exchange messages are often treated as separate. The project already declares GPL-3.0-or-later, so the simplest safe route is to also give friends the app's source. Heads-up: scrub personal details first (device and purchase notes in `docs/HARDWARE_COMPATIBILITY.md`, local paths, `HANDOFF.md`), and commit that source first. Today it is uncommitted.
- [ ] Notices friends can actually see: there is no in-app licence screen, and files inside an iOS bundle are invisible to users. Add your own copyright and GPL statement and the no-warranty text (GPL s.15).
- [ ] Fix `THIRD_PARTY_NOTICES.md`: it describes the engine as "an isolated local Node child process", which is true on the Mac but not on the phone.
- [ ] Installation Information (s.6, the keys or methods needed to install modified versions) is tied to conveying "in, or with, or specifically for use in" a User Product (a consumer device) as part of handing over that device. A friend's own phone is not transferred, so this probably does not bite. That is a reading, not settled.
- [ ] **TestFlight** sends copies through Apple under Apple's terms, which raises the App Store question in (3). I did not read TestFlight's own terms. Installing directly yourself avoids that question.

### (3) Public App Store distribution
- Everything in (2), plus a permanent public source download (s.6d).
- **Unsettled conflict.** Apple's Standard EULA says users "may not distribute or make the Licensed Application available over a network" and may not "modify" it. That clashes with GPL s.10's ban on further restrictions. The EULA does exempt terms "permitted by the licensing terms governing use of any open-sourced components", and developers may supply a custom EULA. (Source: apple.com/legal/internet-services/itunes/dev/stdeula/, read 2026-11-15.)
- The FSF's 2010 position, from its GNU Go and VLC enforcement, was that App Store terms breach the GPL, and VLC was pulled after a contributor objected. gnu.org and fsf.org refused connections during this audit, so this is from secondhand reports only (e.g. engadget.com 2011 "The GPL, the App Store, and you"; vlc-devel list Nov 2010). Many Stockfish-based apps are reportedly on the App Store. Stockfish's README allows selling but says nothing about app stores. **Sources disagree, and only Stockfish's copyright holders could settle it.**
- Commercial use would also be ruled out for anything under a non-commercial licence (ChessQ-lite, ChessReD) if it were ever added.

## 4. Split

**Nothing needed today:** private use on your phone; non-bundled models, datasets and media; the Meta SDK (not in the app).
**Must fix before sharing with anyone:** engine Corresponding Source handed over with the app (including the `.nnue` file and build recipe); a decision on, and delivery of, your app's own source (committed and scrubbed); visible notices plus your own copyright, GPL statement and no-warranty text.

**Three cheapest actions to make sharing with friends compliant:**
1. Make one "source pack" folder you share together with the app: the `stockfish.js` `v19.0.1` source archive, the npm `stockfish-19.0.1.tgz`, the `nn-1a298aa575a0.nnue` file, a 5-line build note (emscripten 6.0.9, single-threaded flavour), `chess.js` 1.4.0 source, and both licences.
2. Commit the app's own code, strip personal details, and put that snapshot (`device-normal/sources/` plus `src/core`, `native/ChessCompanionRuntime`) in the same pack under GPL-3.0-or-later.
3. Install directly (Xcode or ad hoc), not through TestFlight. Send a short README with the app saying what it contains, the licences, where the source pack is, and that it comes with no warranty. Later, add an in-app "Licences" screen.

## 5. Unknowns
- The licence of the embedded Stockfish network `nn-1a298aa575a0.nnue`, and whether the `v19.0.1` tag includes it or downloads it at build time.
- Whether building the `v19.0.1` tag reproduces the npm `.wasm` byte for byte. I did no builds.
- Whether the Leela training data's ODbL licence carries any condition onto the trained network.
- Exact wording of the GPL FAQ and of the FSF App Store statement: gnu.org and fsf.org were unreachable, so I cite them secondhand.
- TestFlight tester terms, which I did not read.
- The Meta DAT SDK's terms at the 1.0.1 tag (I read only the main-branch pointer); the cstr model's actual licence file; the ChessRender360 licence.
- Whether the app's own code counts legally as a "work based on" Stockfish.
