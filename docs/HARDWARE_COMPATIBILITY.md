# Meta glasses compatibility research

## Private phone build preparation — November 13, 2026

Alex reconfirmed the reported phone as **iPhone 17 / iOS 27.2** on November 13. This remains user-reported, not physically queried. The unchanged Simulator-tested source compiled and linked successfully as a private unsigned arm64 iOS device app with all five study fixtures, using the installed iPhoneOS 26.2 SDK path supplied to Swift and deployment target 17.2. The Mach-O itself encodes minimum OS 17.2 and SDK 17.2; both observed facts are retained without assigning a cause. All 46 artifact checks passed. The unsigned executable SHA-256 is `43a02cdeed2143bec10fa06afd8d456efb76583ec6c806616a7a2f607edbbdb6`; bundle ID `local.chesscompanion.offlinestudy`. Actual iOS 27.2 compatibility and phone performance remain unverified.

Evidence and exact prepared artifact: `/Users/alexmunzon/Documents/Codex/2026-11-12/task/outputs/iphone-offline-preparation-2026-11-13/` (`Phone-build.md`, `build-report.json`, `verification.json`). Prepared unsigned app: `/private/var/folders/40/pkx1ymn10_s42501bl5799wh0000gn/T/chess-iphone-study-ruo4lyj9/build/ChessCompanion.app`. No app source changed. No signing identity, profile, account or physical-device inventory was queried; no signing, installation, launch, audio or glasses operation occurred.

Physical-phone approval is still required to inspect the actual connected target/existing signing setup, sign using an existing configured identity/profile if available, install, launch and exercise this private app with text-only output. Stop for new accounts, registration, credential entry, spending or permanent settings changes. Simulator approval does not cover physical-device actions. Do not invent a device ID, team, identity, profile or successful compatibility result. The separate actual-UI in-flight fixture-switch timing limit remains documented; its mock passed 10/10.


Reverified from official public sources on 2026-11-11, with authorized local SDK resolution and a successful minimal device-target import/link probe recorded below. No physical glasses compatibility test has been performed.

## Current project boundary

- The preserved blackjack hardware handoff identifies the glasses as receipt-verified **Ray-Ban Meta Wayfarer Gen1, Shiny Black/Clear, Large**, ordered May 16 and delivered May 21, 2025. The user confirmed on November 10 that these are the same glasses. Source: ../blackjack-practice/docs/HARDWARE-HANDOFF.md. No purchase/payment/address details are copied here.
- The user confirmed **iPhone 17 running iOS 27.2** on November 11. This is user-provided device information; no phone inspection or connection was performed. Glasses firmware and Meta AI app version remain unconfirmed.
- The user explicitly chose **the entire chess runtime on iPhone**. Recognition, legal state, engine coordination and speech must run there; the Mac is build/evaluation tooling, not a required runtime coordinator. This is the architecture requirement, not a claim that the native app is implemented or tested.
- The local tools are Xcode 26.3 (17C529), Swift 6.2.4 and macOS 15.7.4. Current official iOS samples request Xcode 26.4+, Swift 6.3+ and an iOS 17.2+ deployment target. A direct import/typealias-only probe nevertheless **typechecked and linked** DAT 1.0.1 with these installed tools. This establishes the limited probe's compatibility, not full sample or native application support.
- The user authorized isolated DAT 1.0.1 dependency resolution and signing-disabled compile checks. The SDK is now downloaded into the session-local probe checkout. No developer account, signing, SDK registration, camera/microphone permission, physical device connection, app installation or glasses operation was performed. Existing offline chess/replay tests do not prove camera or audio support.

## Actual local SDK probe: 2026-11-11

The probe is a dynamic Swift library containing only `MWDATCore`/`MWDATCamera` imports and public type aliases. It contains no SDK initialization or runtime calls. Its package pins **exactly 1.0.1**. Both `Package.resolved` and the downloaded checkout's Git HEAD identify revision `0bd369298eef6a980ad0bdb6c8a5502f2c02a08c`.

| Check | Observed result | What it establishes |
| --- | --- | --- |
| Dependency resolution | Succeeded; exact version and revision verified | The pinned public dependency was acquired locally |
| Generic iOS Simulator build | Exit 70 before Swift compilation; requested destination unavailable | No simulator import/link result |
| Generic iOS build | Exit 70 before Swift compilation; requested destination unavailable | No import/link result from that command; no phone operation |
| Direct Swift device-target typecheck | Exit 0, 8,204.77 ms | Existing Swift 6.2.4 imports the selected DAT Core/Camera interfaces for arm64 iOS 17.2 |
| Direct Swift device-target library link | Exit 0, 1,030.20 ms | Minimal library/module emitted with explicit signing suppression; no runtime execution |

The earlier generic-build logs reported **iOS 26.2 is not installed** at destination selection. Subsequent read-only inventory found both **iPhoneOS 26.2 and iPhoneSimulator 26.2 compile SDKs already present**, with valid paths, settings, headers/module maps and link stubs. Direct `swiftc` then imported and linked successfully using the existing iPhoneOS SDK and downloaded DAT device slices, without Xcode destination selection. The earlier inference that another platform installation was the next necessary build prerequisite is withdrawn. The destination-selection failure remains undiagnosed; no simulator runtime result is claimed. No component installation or toolchain upgrade was needed for this limited probe.

The tagged `Package.swift` uses Swift tools version 6.0. The downloaded Core and Camera public interfaces identify compiler Swift 6.3.3, iOS 17.2 targets and library evolution support. The successful probe source contains only imports and type aliases; it does not exercise SDK methods. It does not prove the full official sample, native app compilation, signing, registration, camera delivery, audio routing or operation on these Gen1 glasses.

Read-only `file`, `otool -l` and `vtool -show-build` inspection confirmed an **arm64 Mach-O dynamic library**, platform **IOS**, minimum OS **17.2**, both DAT framework load commands, and **no `LC_CODE_SIGNATURE`**. The emitted build-version SDK field is **17.2**, while the actual compiler command and SDKSettings identify the installed **26.2** SDK. These distinct metadata facts are preserved without changing the binary or claiming a cause. Library SHA-256: `3b077f70f3a94cfe4f2b742f0e8d59388cde9e204200c75287e31c87e1fa254f`.

Evidence: [successful direct probe](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/native-readiness-2026-11-11/direct-probe/summary.md), [installed SDK inventory](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/native-readiness-2026-11-11/inventory.md), and [earlier generic-build results](/Users/alexmunzon/Documents/Codex/2026-11-11/continue-my-chess-glasses-project-at/outputs/completion-build-2026-11-11/sdk-probe/summary.md). The direct record retains original commands/report, empty successful compiler logs, source/pin snapshots, targeted metadata hashes and binary inspection. Its caches, temporary files and outputs were scoped under `work/ios-sdk-probe/.local/direct-device`. The earlier Xcode commands also wrote error result bundles to the system temporary directory. No probe application or library was run or installed.

Sources:
- https://github.com/meta/meta-wearables-dat-ios/blob/1.0.1/Package.swift
- https://github.com/meta/meta-wearables-dat-ios/blob/1.0.1/MWDATCore.xcframework/ios-arm64/MWDATCore.framework/Modules/MWDATCore.swiftmodule/arm64-apple-ios.swiftinterface
- https://github.com/meta/meta-wearables-dat-ios/blob/1.0.1/MWDATCamera.xcframework/ios-arm64/MWDATCamera.framework/Modules/MWDATCamera.swiftmodule/arm64-apple-ios.swiftinterface
- https://developer.apple.com/xcode/system-requirements/

## Supported platform claims

The current official FAQ says DAT 1.0 became stable on September 30, 2026. Repository README text still describing developer preview is inconsistent with that newer FAQ. Pin a release before implementation rather than treating all repository-main features as stable.

The FAQ lists Ray-Ban Meta Gen 1 and Gen 2, Meta Ray-Ban Display, Oakley Meta HSTN and Oakley Meta Vanguard. Capabilities vary by device. The recovered Gen1 model is listed. It is displayless: spoken guidance, rather than a visual overlay, is the intended output. Listing support does not establish the installed firmware or actual operation of this pair.

Source: https://developers.meta.com/wearables/faq/

## iOS camera integration

Official sample prerequisites: Xcode 26.4+, Swift 6.3+, iOS 17.2+, installed Meta AI companion app, supported paired glasses and Developer Mode. Modules are MWDATCore and MWDATCamera through Swift Package Manager.

The documented sequence is configure, register, create DeviceSession, start it, wait for started state, obtain DAT camera permission, add Camera, observe its Stream frames, then start Stream. VideoFrame exposes CMSampleBuffer or UIImage. Raw decoded frames and compressed HEVC are separate configurations. Documented sizes are 360x640, 504x896 and 720x1280, with 2/7/15/24/30 FPS options. These are SDK options, not measured rates on this user's device.

Configuration includes Bluetooth usage descriptions/background modes, external-accessory protocol com.meta.ar.wearable, and local-network/Bonjour declarations. Developer Mode permits app ID 0; production requires Developer Center application values and Apple Team ID. Configuration declarations do not constitute user permission.

Sources:
- https://github.com/meta/meta-wearables-dat-ios/blob/main/plugins/mwdat-ios/skills/getting-started/SKILL.md
- https://github.com/meta/meta-wearables-dat-ios/blob/main/AGENTS.md

## Android camera integration

Official documentation specifies Android 10+ test device, Meta AI app and Developer Mode. DAT artifacts are on Maven Central under com.meta.wearable; no repository access token is required. Initialize and register, create a session, observe STARTED before attaching Camera, then collect camera.stream.videoStream. Default frame buffers are YUV; compressed HEVC is optional. Documented sizes/rates match the iOS list above. Bluetooth runtime permission, DAT CAMERA consent and handset-camera permission are distinct.

Source: https://github.com/meta/meta-wearables-dat-android/blob/main/AGENTS.md

## Audio and display boundaries

Camera streaming and display integration are documented parts of DAT 1.0. Display requires display-capable hardware; it is not an overlay available on ordinary displayless glasses.

Synchronized microphone PCM inside Camera Stream is explicitly experimental. iOS requires Camera and Audio Streaming approval in Developer Center plus camera and microphone runtime permissions; configure audioCodec and observe audioFramePublisher with timestamps. Documented rates are 16/44.1/48 kHz. It is available for development/beta, not production publishing. Android documents AudioCodec.PCM, audioStream and presentationTimeUs. MockDeviceKit does not guarantee deterministic PCM injection. Speech, motion, inputs and voice-invocation features are also marked experimental in current repository documentation.

Conventional Bluetooth speaker/microphone routing is a separate pathway. The detailed official microphones-and-speakers page was login-gated during research; its complete current recipe was not verified. Simultaneous camera capture, microphone input and spoken output must remain unverified until tested on actual hardware.

Sources:
- https://github.com/meta/meta-wearables-dat-ios/blob/main/plugins/mwdat-ios/skills/audio-streaming/SKILL.md
- https://github.com/meta/meta-wearables-dat-android/blob/main/AGENTS.md
- https://wearables.developer.meta.com/docs/develop/dat/microphones-and-speakers

## Terms, privacy and next gate

The official SDK README states use entails Meta Wearables Developer Terms and Acceptable Use Policy, and that Meta may collect information about device/app communications. Local chess inference must not be presented as proof that the whole glasses stack is offline. No agreement was accepted by reading these documents.

Sources:
- https://github.com/meta/meta-wearables-dat-ios
- https://github.com/meta/meta-wearables-dat-android

Immediate native work can proceed against the existing toolchain, with the complete runtime targeted to iPhone. The import/link probe removes the assumed compiler-installation prerequisite for this small dependency surface; a full application build remains separate. A future SDK mock adapter can test session transitions, permission-denied behavior, prerecorded camera feeds and stale-result invalidation after its own build and setup are verified. The package checkout includes mock-framework artifacts, but the probe declares only Core and Camera as dependencies; no SDK mock was initialized or run.

Actual hardware acceptance still requires a successful native application build, authorized signing/pairing and Meta AI/SDK permission setup, confirmed firmware/companion versions, and physical capture, reconnect, interruption, latency, battery and audio-route testing. Phone model/OS and the iPhone-only runtime requirement are user-confirmed. Check the version compatibility matrix at implementation time; do not fabricate minimum firmware or app versions from the available public pages.

## Camera and spoken output: unresolved integration blocker

The latest visible official iOS release tag during this research was [1.0.1](https://github.com/meta/meta-wearables-dat-ios/tags), October 9, 2026, commit `0bd369298eef6a980ad0bdb6c8a5502f2c02a08c`. This exact release resolved and passed the limited direct device-target import/link probe. Requirements quoted from current `main` documentation remain distinct from measured behavior of this pinned release; no SDK runtime behavior was exercised.

An October 22 response in [Meta iOS issue #358](https://github.com/meta/meta-wearables-dat-ios/issues/358#issuecomment-6350602851) states that active camera streaming pauses phone A2DP audio, including app TTS, even while the audio route still reports the glasses. It reports no SDK sound-playback API or app setting to keep that output audible. The issue reports Gen 2 / DAT 1.0.1; applicability to this Gen 1 pair is untested. Route selection is not proof of audible delivery.

[Issue #256](https://github.com/meta/meta-wearables-dat-ios/issues/256) separately reports a playback-resumption bug after stopping a stream. Capture → stop stream → speak is therefore a proposed hardware experiment, not a verified workaround. Test actual audibility, pause/resume recovery, new-frame freshness, interruption, reconnect and stale-speech cancellation on the confirmed paired phone before promising the full pipeline.

The exact [firmware/companion-app matrix](https://wearables.developer.meta.com/docs/version-dependencies) and [microphones/speakers guide](https://wearables.developer.meta.com/docs/develop/dat/microphones-and-speakers) remained login-gated through documentation tools. No browser fallback, account setup or device-permission change was used. The user-confirmed iPhone 17 / iOS 27.2 establishes the intended platform; the full adapter remains untested.
