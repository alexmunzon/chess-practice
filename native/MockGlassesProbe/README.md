# MockGlassesProbe (Phase 1 of docs/MOCK_DEVICE_KIT_PLAN.md, 2026-11-15)

Compile-and-link probe for Meta's simulated-glasses SDK 1.0.1 (Simulator slices). **Nothing here was ever run**; never launch, install or execute these binaries (running Meta code is Phase 4).
Meta's frameworks are proprietary and stay outside the repo (`/Users/alexmunzon/chess-builds/mock-glasses-2026-11-15/phase1/`).

**Verdict: links on this Mac (Xcode 26.3, Swift 6.2.4, iPhoneSimulator SDK 26.2) with no workaround.** The frameworks ship only
textual `.swiftinterface` files (no binary `.swiftmodule`); Swift 6.2.4 rebuilt them from the 6.3.3 interfaces without warnings.
All 3,965 strong imports of the three binaries (built against SDK 26.5) exist in the 26.2 Simulator SDK `.tbd` stubs (`logs/sdk262-import-check.txt`).

## Run the check
`native/MockGlassesProbe/build_probe.sh <frameworks dir> <out dir>` (pass = exit 0, `BUILD OK`, three `@rpath/MWDAT*` lines per binary in `otool -L`).
Flags: `xcrun --sdk iphonesimulator swiftc -target arm64-apple-ios17.2-simulator -swift-version 6 -F <dir> -framework MWDATCore -framework MWDATCamera -framework MWDATMockDevice -Xlinker -rpath -Xlinker @executable_path/Frameworks`.
(Without `--sdk iphonesimulator`, `xcrun swiftc` also links but warns "using sysroot for 'MacOSX'".)

## Phase 3 call sequence (type-checked and linked in `CallSequenceProbe.swift`; quoted from the .swiftinterface)
1. `Wearables.configure() throws(MWDATCore.WearablesError)`; then `Wearables.shared: any WearablesInterface`.
2. `MockDeviceKit.shared: any MockDeviceKitInterface`; `func enable(config: MockDeviceKitConfig)` (sync, no throw);
   `MockDeviceKitConfig(initiallyRegistered: Bool = true, initialPermissionsGranted: Bool = true)`.
3. `func pairGlasses(model: GlassesModel) throws(MockDeviceKitError) -> any MockGlasses` (errors `.notEnabled`, `.testServerUnavailable`).
   `GlassesModel` has 6 cases: `rayBanMeta, oakleyMetaHSTN, oakleyMetaVanguard, rayBanMetaOptics, metaGlasses, metaRayBanDisplay` (no generation).
4. `MockDevice`: `powerOn()`, `powerOff()`, `don()`, `doff()`, `var deviceIdentifier: DeviceIdentifier` (= `String`); `MockGlasses` adds `fold()`, `unfold()`, `services`.
5. `glasses.services.camera.setCameraFeed(fileURL: Foundation.URL)` (sync). The same protocol also has the phone-camera variant: never use it.
6. `Wearables.shared.createSession(deviceSelector: any DeviceSelector) throws(DeviceSessionError) -> DeviceSession`, with
   `SpecificDeviceSelector(device: DeviceIdentifier)`; then `DeviceSession.start() throws(DeviceSessionError)` (sync; state via `statePublisher`/`stateStream()`).
7. `extension DeviceSession { func addCamera(config: StreamConfiguration = StreamConfiguration()) throws(DeviceSessionError) -> Camera? }` (in MWDATCamera).
   `StreamConfiguration(videoCodec: VideoCodec /* .raw | .hvc1 */, resolution: StreamingResolution /* .high | .medium | .low */, frameRate: UInt)`.
8. `camera.stream.start()`; frames: `stream.videoFramePublisher: any Announcer<VideoFrame>`, `listen(_: @escaping @Sendable (VideoFrame) -> Void) -> any AnyListenerToken`.
9. `public struct VideoFrame: Sendable { var sampleBuffer: CMSampleBuffer { get }; func makeUIImage() -> sending UIImage? }`.
   **No timestamp field**: use `CMSampleBufferGetPresentationTimeStamp/GetDuration(frame.sampleBuffer)`. (`AudioFrame` has `presentationTimeStamp: CMTime`.)

Differs from the plan's assumptions: no single "start camera stream session" call (it is session -> addCamera -> stream.start);
frames come via a listener token, not an async sequence; the mock has 6 models, not one; pairing throws.
Unconfirmed until Phase 4: whether `configure()` must precede `enable`, whether `unfold()`/session `.started` are needed before `addCamera`.

## Static inspection (otool/vtool/strings/interfaces only)
- All three: dynamic, IOSSIMULATOR, minos 17.2, sdk 26.5; SHA-256 pins in `phase1/hashes.txt`. MWDATCore links: Foundation, CoreFoundation, UIKit, CoreGraphics, CoreBluetooth, CryptoKit, DeviceCheck, Security, SystemConfiguration,
  ExternalAccessory, Network, NetworkExtension, Combine, AccessorySetupKit (weak), WiFiAware (weak), libz, libc++, libiconv.
- MWDATCamera: MWDATCore, AVFoundation, AVFAudio, CoreMedia, CoreVideo, CoreImage, ImageIO, VideoToolbox, UIKit, CoreGraphics.
- MWDATMockDevice: MWDATCore, AVFoundation, AVFAudio, CoreMedia, CoreVideo, CoreMotion, ImageIO, Network, **Speech**, **WebKit**, VideoToolbox, UIKit.
  Its strong imports include `AVCaptureSession`/`AVCaptureDevice` (the phone-camera feed path) and `SFSpeech*`: present but only reached via APIs we do not call.
- Info.plist checks (MWDATCore strings, "... must be present and non-empty" / "must contain"): `NSBluetoothAlwaysUsageDescription`,
  `NSLocalNetworkUsageDescription`, `NSBonjourServices` (service string `_meta-datax._tcp` found), `UIBackgroundModes` ∋ `bluetooth-central`, `external-accessory`,
  `UISupportedExternalAccessoryProtocols` ∋ `com.meta.ar.wearable`. Also read: `MWDAT` dict with `MetaAppID`, `ClientToken`, `TeamID`, `AppLinkURLScheme`,
  `Logging`, `Attestation`, `CFBundleURLTypes`/`CFBundleURLSchemes`.
- Opt-out keys (strings + checkout README): `MWDAT > Analytics > OptOut = true`, `MWDAT > CrashReporting > OptOut = true`. Both default ON.
  The crash reporter installs itself and chains to existing crash handlers unless opted out.
- Hard-coded hosts (only in MWDATCore): `https://api2.ar.meta.com/mwsdk/telemetry`, `https://api2.ar.meta.com/wearables/attestation/challenge`.
  Others are doc/protobuf strings (`developers.google.com`, `type.googleapis.com`, `fburl.com/xcode-arc-focus`), not endpoints.

Not verified: any runtime behaviour (nothing executed), whether opt-out actually stops network calls, permission prompts, frame format/rate.
