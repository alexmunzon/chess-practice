# Local iPhone engine runtime

Source for the phone-only backend. `NativeEngineRuntime` owns a nonpersistent WKWebView and serves a fixed, hashed resource allowlist from the app's local bundle through `chess-local://bundle`. It does not open a Mac server or an existing browser profile, request a device permission, access a camera, register with Meta, or speak audio.

The native caller explicitly invokes `start()`, then `submit(commandJSON:timeoutMilliseconds:)`, `cancel()` and `close()`. JSON commands are validated by the shared `DeviceBackend`; every native transport has its own UUID even when a caller reuses a command ID. A task cancelled before entering `submit` is rejected before it can cancel a newer pending request. Absolute monotonic deadlines are checked at publication as well as by timers. Cancellation, a later request, invalid replies, navigation failure or WebKit termination revoke pending replies. Human review, capture age, legal tracking and permission to speak remain the capture coordinator's responsibility; a backend response cannot grant them.

Only the local entry page can navigate. Its CSP excludes remote schemes and permits the local resource scheme and blob workers. Local JS/WASM are loaded into blob URLs before starting the unchanged Stockfish worker. The pinned worker accepts its WASM blob URL through `location.hash`. Full Stockfish 19.0.1 remains selected; its WASM asset is 99,169,054 bytes. Startup time, peak memory and sustained use on the iPhone remain unmeasured. No smaller/weaker engine is substituted silently.

## Build private local assets

From the repository, choose a new empty directory outside the source checkout:

```sh
node scripts/build-device-runtime.mjs --out /tmp/chess-device-assets
node --test tests/device-runtime-assets.test.js
```

The builder uses only already-installed pinned `stockfish` 19.0.1 and `chess.js` 1.4.0. It copies four portable core modules, rewrites the one bare rules import to the copied local module, preserves license notices and emits `runtime-manifest.json` with source and output hashes. It performs no downloads and refuses existing nonempty outputs or any output resolving into the repository. Generated engine assets are private development artifacts. Do not distribute a bundled engine until GPL corresponding-source delivery obligations have been verified.

## Verification boundary

The host typechecks for arm64 iOS 17.2 with the installed iOS 26.2 SDK and Swift 6.2.4. The optional macOS harness also typechecks with the installed macOS 26.2 SDK. Packaging tests verify actual copied hashes, module imports, pinned dependencies, preservation of output files and path restrictions. Existing Worker tests run real pinned WASM under Node worker threads; those are not WebKit or iPhone tests.

**One authorized offline macOS WebKit fixture passed on 2026-11-11.** The initial authorized run in the restricted command sandbox exited 1 after WebKit/LaunchServices sandbox extensions could not be created; it did not establish engine compatibility. The user separately authorized one expanded command run of the same executable and local v2 asset bundle. That run exited 0 with empty stderr, validated the starting FEN, returned the legal Stockfish move `e4` and generated its speech text, and passed cancellation. The complete fixture took 1,482.826 ms; this is not an isolated engine latency measurement.

This verifies the custom-scheme modules/fetch and blob Worker/WASM path for the tested Mac fixture. It does not verify iPhone runtime behavior, resource use, physical recognition, DAT capture or audible speech. The harness used a nonpersistent, undisplayed WKWebView and the local-only CSP/hashed allowlist; no existing browser profile was opened. No packet-capture or network-monitoring result is claimed.

The executed host SHA256 was `52d82cc4b7d90318e011048324479d3d8ad968fcf8ede5c4130dbc20b9ff6713`; the v2 asset manifest was `471e56746249cb421a59c2466d2febf2ff1791af16b6391efb79aafb44fc47d5`. A subsequent one-line `Task.checkCancellation()` guard at `submit` entry produced host SHA256 `47564b0a3cc140f68c3cea12fc1ac8b4a0d4e7df58c6807b31018097bc73c8fe`. The guarded host and harness typecheck for macOS, and the guarded host passes the complete capture/vision/integration iOS typecheck. The earlier WebKit success applies to the preceding source hash; no post-guard WebKit rerun is claimed. Exact commands, logs and source boundaries are retained in the continuation session's `outputs/native-readiness-2026-11-11/runtime/` and adjacent `integration/` evidence.

`VerifyRuntime.swift` remains a bounded macOS verification harness with a 60-second exit deadline. It does not call speech, camera or Meta APIs. Its original unsigned compile-only artifact was never executed; the successful run used a normal local macOS development link, with no Apple account or iOS provisioning. The user authorized one expanded run, which is complete. Any additional WebKit execution needs separate approval under this session's no-browser-without-asking instruction.

The generated bundle and compiled harness are kept under the continuation session's `work/` directory. The app will eventually package the same assets locally on the iPhone. The Mac is only a development/test host, not a required runtime service.
