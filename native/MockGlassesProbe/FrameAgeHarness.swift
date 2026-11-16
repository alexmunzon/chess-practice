// Phase 5 frame-age harness (docs/MOCK_GLASSES_FRAME_AGE.md). A separate Simulator-only app (bundle
// local.chesscompanion.mockglasses.frameage), built only by build_frame_age_harness.py. It streams the pinned test
// video through Meta's Mock Device Kit, injects stale frames in its own code and counts how often each candidate
// frame-age rule (FrameAgeRules.swift) accepts or rejects them. It does NOT change or use the live trust decision.
// It runs only when launched with `--frame-age`. It never uses the phone camera feed, microphone, audio session or
// speech, never registers and never requests a permission. The mock has no radio, so no real latency is measured.
//
// Also compiled into this app, unchanged: native/ChessCompanionApp/MockGlassesSource.swift (for its frame-index
// code reader `MockGlassesNonce` and pinned video hash) with the capture sources it needs. Its runner is never
// started here; the three stub classes below only satisfy the names its `SelfTestHook` mentions.
#if COMPANION_FRAME_AGE_HARNESS && !targetEnvironment(simulator)
#error("COMPANION_FRAME_AGE_HARNESS is Simulator-only")
#endif
#if COMPANION_FRAME_AGE_HARNESS && os(iOS) && targetEnvironment(simulator)
import CoreMedia
import CoreVideo
import CryptoKit
import Foundation
import SwiftUI
import MWDATCore
import MWDATCamera
import MWDATMockDevice

@MainActor final class OfflineStudyModel {}
@MainActor final class ReplayGameModel {}
@MainActor final class AppModeState {}

@main struct FrameAgeHarnessApp: App {
    var body: some Scene {
        WindowGroup {
            Text("Frame-age harness: Meta mock glasses only. No real latency is measured.")
                .padding()
                .task { await FrameAgeRunner.launchIfRequested() }
        }
    }
}

func frameAgeLog(_ text: String) { NSLog("FRAMEAGE %@", text as NSString) }
private var uptimeNow: Double { ProcessInfo.processInfo.systemUptime }

/// Thresholds. Defaults are written into the report; none of them is a measured hardware value.
struct FrameAgeConfig {
    var nonceMaxAge = 3.0          // method 1: code slot is 2 s in the test video, plus 1 s
    var nonceMargin = 0.05         // method 1: display refresh margin (no display in the mock)
    var offsetMaxExcess = 0.25     // method 2
    var offsetWindow = 10.0        // method 2 (a second gate keeps the minimum for the whole stream)
    var offsetWarmupFrames = 30
    var offsetWarmupSeconds = 1.0
    var budget = 0.5               // method 3: PLACEHOLDER, never measured on hardware
    var limit = 1.0                // method 3
    var maxGap = 0.3               // method 3 watchdog
    var agreeingFrames = 2         // method 3
    var slotSeconds = 2.0          // test video: each code held 2 s
    var codes = 15                 // test video: 15 codes, file loops every 30 s
    var delays: [Double] = [0.1, 0.2, 0.3, 0.45, 0.55, 0.95, 1.05, 2.0, 2.9, 3.1, 5.0, 10.0]
    var json: [String: Any] {
        ["nonceMaxAge": nonceMaxAge, "nonceMargin": nonceMargin, "offsetMaxExcess": offsetMaxExcess, "offsetWindow": offsetWindow,
         "offsetWarmupFrames": offsetWarmupFrames, "offsetWarmupSeconds": offsetWarmupSeconds, "budgetPlaceholder": budget,
         "limit": limit, "maxGap": maxGap, "agreeingFrames": agreeingFrames, "slotSeconds": slotSeconds, "codes": codes, "delays": delays]
    }
}

/// How the harness treats frames that arrive while a scenario is active.
enum FrameAgeScenario: Sendable {
    case fresh
    case isolated(every: Int)              // every Nth frame held by the next delay in the list; mode alternates per cycle
    case sustained(Double)                 // every frame held (queue before the phone)
    case burst(releaseAt: Double)          // every frame held until one release time, then delivered together
    case drop                              // frames discarded: a gap
    case crossStream(every: Int, delay: Double)
}

private struct ArrivedFrame: Sendable {
    let id: Int
    let epoch: UInt64
    let sdkTime: Double     // uptime at the SDK callback (ground truth for the injected hold)
    let pts: Double?
    let code: Int?
    let codeReason: String
}

/// All mutable state lives on `queue`.
final class FrameAgeEngine: @unchecked Sendable {
    let queue = DispatchQueue(label: "frame-age", qos: .userInitiated)
    let config: FrameAgeConfig
    private var nonce: NonceAgeGate
    private var offsetWindowed: OffsetMonitorGate
    private var offsetWhole: OffsetMonitorGate
    private var liveness: LivenessBudgetGate
    private var epoch: UInt64 = 0
    private var anchor: [UInt64: Double] = [:]
    private var nextSlot = 0
    private var scenario: FrameAgeScenario = .fresh
    private var label = "none"
    private var nextID = 0, isolatedCount = 0, delayIndex = 0, crossCount = 0
    private var frames: [[String: Any]] = []
    private var polls: [[String: Any]] = []
    private var events: [[String: Any]] = []
    private var latest: (frame: ArrivedFrame, receipt: Double)?
    private var framesPerEpoch: [UInt64: Int] = [:]
    private var timer: DispatchSourceTimer?
    // Corruption readback samples are taken on the SDK thread.
    private let corruptionLock = NSLock()
    private var corruptionCounter = 0
    private var corruption: [[String: Any]] = []

    init(config: FrameAgeConfig) {
        self.config = config
        nonce = NonceAgeGate(maxAge: config.nonceMaxAge, displayMargin: config.nonceMargin)
        offsetWindowed = OffsetMonitorGate(maxExcess: config.offsetMaxExcess, window: config.offsetWindow,
                                           warmupFrames: config.offsetWarmupFrames, warmupSeconds: config.offsetWarmupSeconds)
        offsetWhole = OffsetMonitorGate(maxExcess: config.offsetMaxExcess, window: nil,
                                        warmupFrames: config.offsetWarmupFrames, warmupSeconds: config.offsetWarmupSeconds)
        liveness = LivenessBudgetGate(budget: config.budget, limit: config.limit, maxGap: config.maxGap, agreeingFrames: config.agreeingFrames)
    }

    // MARK: control (called from the runner)

    func beginEpoch() -> UInt64 {
        queue.sync {
            epoch += 1; nextSlot = 0
            nonce.startEpoch(epoch)
            events.append(["uptime": uptimeNow, "kind": "epoch", "value": "\(epoch)"])
            return epoch
        }
    }
    func set(_ newLabel: String, _ newScenario: FrameAgeScenario) {
        queue.sync {
            label = newLabel; scenario = newScenario
            events.append(["uptime": uptimeNow, "kind": "scenario", "value": newLabel])
        }
    }
    func event(_ kind: String, _ value: String) {
        let t = uptimeNow
        queue.async { self.events.append(["uptime": t, "kind": kind, "value": value]) }
    }
    func frameCount(epoch e: UInt64) -> Int { queue.sync { framesPerEpoch[e, default: 0] } }
    func startPolling() {
        queue.sync {
            let source = DispatchSource.makeTimerSource(queue: queue)
            source.schedule(deadline: .now() + 0.1, repeating: 0.1, leeway: .milliseconds(5))
            source.setEventHandler { [weak self] in self?.poll() }
            source.resume(); timer = source
        }
    }
    func stopPolling() { queue.sync { timer?.cancel(); timer = nil } }
    func snapshot() -> [String: Any] {
        let c = corruptionLock.withLock { corruption }
        return queue.sync { ["frames": frames, "polls": polls, "events": events, "corruption": c] }
    }

    // MARK: SDK callback (SDK thread)

    func sdkFrame(_ frame: VideoFrame, epoch frameEpoch: UInt64) {
        let t = uptimeNow
        let cm = CMSampleBufferGetPresentationTimeStamp(frame.sampleBuffer)
        let pts: Double? = cm.isValid && cm.isNumeric ? cm.seconds : nil
        var code: Int?, reason = "no-image-buffer"
        if let image = CMSampleBufferGetImageBuffer(frame.sampleBuffer) {
            (code, reason) = MockGlassesNonce.read(image)
            let sample: Int? = corruptionLock.withLock { corruptionCounter += 1; return corruptionCounter % 5 == 0 ? corruptionCounter : nil }
            if let seed = sample, let code {
                let results = Self.corruptedReads(image, seed: seed, truth: code)
                corruptionLock.withLock { corruption.append(["seed": seed, "truth": code, "results": results]) }
            }
        }
        let arrived = (t, pts, code, reason)
        queue.async { self.arrive(sdkTime: arrived.0, pts: arrived.1, code: arrived.2, reason: arrived.3, epoch: frameEpoch) }
    }

    /// Reads the frame-index code again with deliberately corrupted block values, through the project's own
    /// decoder (`MockGlassesNonce.read(width:height:mean:)`). Each result is correct, abstained or MISREAD.
    static func corruptedReads(_ buffer: CVPixelBuffer, seed: Int, truth: Int) -> [String: String] {
        CVPixelBufferLockBaseAddress(buffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        let format = CVPixelBufferGetPixelFormatType(buffer)
        guard CVPixelBufferIsPlanar(buffer), format == kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange
                || format == kCVPixelFormatType_420YpCbCr8BiPlanarFullRange,
              let base = CVPixelBufferGetBaseAddressOfPlane(buffer, 0) else { return ["unsupported": MockGlassesNonce.fourCC(format)] }
        let width = CVPixelBufferGetWidth(buffer), height = CVPixelBufferGetHeight(buffer)
        let row = CVPixelBufferGetBytesPerRowOfPlane(buffer, 0)
        let pixels = base.assumingMemoryBound(to: UInt8.self)
        let videoRange = format == kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange
        func mean(_ x1: Int, _ y1: Int, _ x2: Int, _ y2: Int) -> Double {
            var sum = 0, count = 0
            for y in y1..<min(y2, height) { for x in x1..<min(x2, width) { sum += Int(pixels[y * row + x]); count += 1 } }
            let y = count == 0 ? 128.0 : Double(sum) / Double(count)
            return videoRange ? (y - 16) * 255 / 219 : y
        }
        // Call order of the reader: copy (top, bottom) x row 0..3 x column 0..15 = 128 calls.
        // Data bit j is the Manchester pair of blocks 2j, 2j+1 in rows 1-2.
        func pairCalls(_ j: Int) -> Set<Int> {
            var calls = Set<Int>()
            for copy in 0..<2 { for b in [2 * j, 2 * j + 1] { calls.insert(copy * 64 + (1 + b / 16) * 16 + b % 16) } }
            return calls
        }
        func read(_ transform: (Int, Double) -> Double) -> String {
            var call = 0
            let (index, why) = MockGlassesNonce.read(width: width, height: height) { x1, y1, x2, y2 in
                defer { call += 1 }
                return transform(call, mean(x1, y1, x2, y2))
            }
            guard let index else { return "abstained:" + why }
            return index == truth ? "correct" : "MISREAD:\(index)"
        }
        let k = seed % 128, j = seed % 16
        let flipBit = pairCalls(j), flipTwo = pairCalls(j).union(pairCalls((j + 5) % 16))
        let flipThree = flipTwo.union(pairCalls((j + 11) % 16))
        var noise = UInt64(truncatingIfNeeded: seed) &* 6364136223846793005 &+ 1442695040888963407
        return [
            "control-unmodified": read { _, v in v },
            "flip-one-block-one-copy": read { c, v in c == k ? 255 - v : v },
            "gray-one-block": read { c, v in c == k ? 128 : v },
            "flip-1-bit-both-copies": read { c, v in flipBit.contains(c) ? 255 - v : v },
            "flip-2-bits-both-copies": read { c, v in flipTwo.contains(c) ? 255 - v : v },
            "flip-3-bits-both-copies": read { c, v in flipThree.contains(c) ? 255 - v : v },
            "heavy-noise": read { _, v in
                noise = noise &* 6364136223846793005 &+ 1442695040888963407
                return v + Double(Int((noise >> 33) % 221) - 110)
            },
            "blank-gray": read { _, _ in 128 },
        ]
    }

    // MARK: queue-only

    private func advanceDisplays(_ now: Double) {
        guard let a = anchor[epoch] else { return }
        while a + Double(nextSlot) * config.slotSeconds <= now {
            nonce.recordDisplay(code: nextSlot % config.codes, at: a + Double(nextSlot) * config.slotSeconds)
            nextSlot += 1
        }
    }

    private func arrive(sdkTime t: Double, pts: Double?, code: Int?, reason: String, epoch e: UInt64) {
        // The modelled display log of method 1 is anchored on the first SDK callback of the stream (stream clock
        // 0 = callback time - PTS). It stands in for a display that logs its own times; it is never delayed.
        if e == epoch, anchor[e] == nil, let pts { anchor[e] = t - pts }
        advanceDisplays(t)
        framesPerEpoch[e, default: 0] += 1
        let f = ArrivedFrame(id: nextID, epoch: e, sdkTime: t, pts: pts, code: code, codeReason: reason)
        nextID += 1
        var mode = "fresh", nominal = 0.0
        switch scenario {
        case .fresh: break
        case .isolated(let every):
            isolatedCount += 1
            if isolatedCount % every == 0 {
                nominal = config.delays[delayIndex % config.delays.count]
                mode = (delayIndex / config.delays.count) % 2 == 0 ? "upstream" : "downstream"
                delayIndex += 1
            }
        case .sustained(let d): mode = "upstream"; nominal = d
        case .burst(let release): mode = "burst"; nominal = max(0, release - t)
        case .drop: mode = "drop"
        case .crossStream(let every, let d):
            crossCount += 1
            if crossCount % every == 0 { mode = "upstream"; nominal = d }
        }
        // Only ever touched on `queue` (the delayed closures run there too).
        nonisolated(unsafe) let base: [String: Any] = ["id": f.id, "epoch": Int(e), "sdkTime": t, "pts": pts ?? NSNull(), "code": code ?? NSNull(),
                                   "codeReason": reason, "scenario": label, "mode": mode, "nominalDelay": nominal]
        switch mode {
        case "fresh": deliver(f, base: base, receiptAtSDK: true)
        case "downstream": queue.asyncAfter(deadline: .now() + nominal) { self.deliver(f, base: base, receiptAtSDK: true) }
        case "upstream", "burst": queue.asyncAfter(deadline: .now() + nominal) { self.deliver(f, base: base, receiptAtSDK: false) }
        default: var r = base; r["delivered"] = false; frames.append(r)
        }
    }

    private func deliver(_ f: ArrivedFrame, base: [String: Any], receiptAtSDK: Bool) {
        let now = uptimeNow
        let receipt = receiptAtSDK ? f.sdkTime : now
        advanceDisplays(now)
        let v1 = nonce.evaluate(code: f.code, frameEpoch: f.epoch, now: now)
        let v2 = offsetWindowed.observe(pts: f.pts, receipt: receipt, now: now, frameEpoch: f.epoch)
        let v2w = offsetWhole.observe(pts: f.pts, receipt: receipt, now: now, frameEpoch: f.epoch)
        let v3 = liveness.observe(key: f.code.map { "code-\($0)" }, receipt: receipt, now: now, frameEpoch: f.epoch)
        var r = base
        r["delivered"] = true; r["evalTime"] = now; r["receipt"] = receipt; r["hold"] = now - f.sdkTime
        r["currentEpoch"] = Int(epoch)
        r["m1"] = Self.json(v1); r["m2"] = Self.json(v2); r["m2whole"] = Self.json(v2w); r["m3"] = Self.json(v3)
        frames.append(r)
        latest = (f, receipt)
    }

    private func poll() {
        guard let latest else { return }
        let now = uptimeNow
        advanceDisplays(now)
        let f = latest.frame
        polls.append(["t": now, "scenario": label, "frameID": f.id, "age": now - f.sdkTime, "epoch": Int(f.epoch), "currentEpoch": Int(epoch),
                      "m1": Self.json(nonce.evaluate(code: f.code, frameEpoch: f.epoch, now: now)),
                      "m2": Self.json(offsetWindowed.evaluate(pts: f.pts, frameEpoch: f.epoch, now: now)),
                      "m2whole": Self.json(offsetWhole.evaluate(pts: f.pts, frameEpoch: f.epoch, now: now)),
                      "m3": Self.json(liveness.evaluate(receipt: latest.receipt, frameEpoch: f.epoch, now: now))])
    }

    static func json(_ v: FrameAgeVerdict) -> [String: Any] {
        ["accept": v.accept, "reason": v.reason, "value": v.value ?? NSNull()]
    }
}

@MainActor final class FrameAgeRunner {
    private static var started = false
    private let engine = FrameAgeEngine(config: FrameAgeConfig())
    private var report: [String: Any] = [:]
    private var steps: [[String: Any]] = []
    private var tokens: [any AnyListenerToken] = []
    private var glasses: (any MockGlasses)?
    private let videoURL = Bundle.main.bundleURL.appendingPathComponent("FrameAge/replay-14.mp4")
    private static var documents: URL { FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0] }

    static func launchIfRequested() async {
        guard ProcessInfo.processInfo.arguments.contains("--frame-age") else {
            frameAgeLog("launch argument --frame-age absent: no Meta SDK call made")
            try? "argument absent; no Meta SDK call made\n".write(to: documents.appendingPathComponent("frame-age-absent.txt"), atomically: true, encoding: .utf8)
            return
        }
        guard !started else { return }
        started = true
        await FrameAgeRunner().run()
    }

    private func pause(_ seconds: Double) async { try? await Task.sleep(for: .milliseconds(Int(seconds * 1000))) }

    @discardableResult private func step(_ name: String, _ body: () throws -> Void) -> Bool {
        do { try body(); steps.append(["name": name, "uptime": uptimeNow, "ok": true]); frameAgeLog("step \(name) ok"); return true }
        catch { steps.append(["name": name, "uptime": uptimeNow, "ok": false, "error": String(describing: error)]); frameAgeLog("step \(name) FAILED \(error)"); return false }
    }

    func run() async {
        report = ["schemaVersion": 1, "launchUptime": uptimeNow, "bundleIdentifier": Bundle.main.bundleIdentifier ?? "",
                  "config": engine.config.json, "noRealLatencyMeasured": true]
        frameAgeLog("runner start")
        defer { write(complete: true); frameAgeLog("runner done") }
        guard step("verify-video", {
            let data = try Data(contentsOf: videoURL)
            let hash = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
            guard hash == MockGlassesLaunch.videoSHA256 else { throw CaptureFailure.invalidFrame }
        }) else { return }
        guard step("configure", { try Wearables.configure() }) else { return }
        let kit = MockDeviceKit.shared
        guard step("enable-mock", { kit.enable(config: MockDeviceKitConfig(initiallyRegistered: true, initialPermissionsGranted: true)) }) else { return }
        await pause(1)
        report["registrationState"] = String(describing: Wearables.shared.registrationState)
        guard step("pair", { glasses = try kit.pairGlasses(model: .rayBanMeta) }), let glasses else { return }
        glasses.powerOn(); glasses.unfold(); glasses.don()
        guard step("set-file-feed", { glasses.services.camera.setCameraFeed(fileURL: videoURL) }) else { return }
        await pause(1)
        engine.startPolling()
        defer { engine.stopPolling() }

        // Stream 1: warm-up, isolated delays (all within the first 28 s, before the 30 s code wrap), sustained queues,
        // bursts, drops, then doff, and frames held across a fold.
        engine.set("warmup", .fresh)
        guard var current = await startStream(label: "s1") else { return }
        await pause(4)
        engine.set("isolated", .isolated(every: 3)); await pause(22)
        engine.set("fresh-a", .fresh); await pause(3)
        engine.set("sustained-0.5", .sustained(0.5)); await pause(6)
        engine.set("fresh-b", .fresh); await pause(3)
        engine.set("sustained-1.2", .sustained(1.2)); await pause(14)
        engine.set("fresh-c", .fresh); await pause(3)
        // In-order queues just under and just over method 2's threshold (isolated delays arrive out of order).
        engine.set("sustained-0.2", .sustained(0.2)); await pause(5)
        engine.set("fresh-d", .fresh); await pause(2)
        engine.set("sustained-0.3", .sustained(0.3)); await pause(5)
        engine.set("fresh-e", .fresh); await pause(2)
        for g in [0.2, 0.4, 1.0, 3.0] {
            engine.set("burst-\(g)", .burst(releaseAt: uptimeNow + g)); await pause(g)
            engine.set("fresh-after-burst-\(g)", .fresh); await pause(3)
        }
        for g in [0.2, 0.4, 1.0, 3.0] {
            engine.set("drop-\(g)", .drop); await pause(g)
            engine.set("fresh-after-drop-\(g)", .fresh); await pause(3)
        }
        engine.set("doff", .fresh); engine.event("action", "doff"); glasses.doff(); await pause(6)
        engine.event("action", "don"); glasses.don(); engine.set("after-don", .fresh); await pause(3)
        engine.set("cross-stream-held", .crossStream(every: 3, delay: 16)); await pause(2)
        engine.set("fold", .fresh); engine.event("action", "fold"); glasses.fold(); await pause(6)
        engine.event("action", "unfold"); glasses.unfold(); engine.set("after-unfold", .fresh); await pause(3)
        report["framesAfterUnfoldSameStream"] = engine.frameCount(epoch: current.epoch)
        // Stream 2: a new stream (the mock does not resume after fold), delayed from its very first frame.
        current = await restart(current, glasses: glasses, label: "s2", scenario: ("delayed-at-start-1.0", .sustained(1.0)))
        await pause(4)
        engine.set("fresh-s2", .fresh); await pause(8)
        engine.set("power-off", .fresh); engine.event("action", "powerOff"); glasses.powerOff(); await pause(6)
        engine.event("action", "powerOn"); glasses.powerOn(); engine.set("after-power-on", .fresh); await pause(3)
        // Stream 3: plain fresh frames after power cycling.
        current = await restart(current, glasses: glasses, label: "s3", scenario: ("fresh-s3", .fresh))
        await pause(8)
        engine.set("end", .fresh)
        current.camera.stream.stop(); await pause(1); current.session.stop(); await pause(1)
    }

    private struct Running { let session: DeviceSession; let camera: Camera; let epoch: UInt64 }

    private func restart(_ old: Running, glasses: any MockGlasses, label: String, scenario: (String, FrameAgeScenario)) async -> Running {
        old.camera.stream.stop(); old.session.stop(); await pause(1)
        glasses.powerOn(); glasses.unfold(); glasses.don(); await pause(1)
        engine.set(scenario.0, scenario.1)
        guard let next = await startStream(label: label) else { return old }
        return next
    }

    private func startStream(label: String) async -> Running? {
        guard let glasses else { return nil }
        var session: DeviceSession?
        guard step("session-\(label)", {
            let s = try Wearables.shared.createSession(deviceSelector: SpecificDeviceSelector(device: glasses.deviceIdentifier))
            try s.start(); session = s
        }), let session else { return nil }
        for _ in 0..<100 where session.state != .started { await pause(0.1) }
        guard session.state == .started else { steps.append(["name": "session-\(label)-started", "ok": false, "error": String(describing: session.state)]); session.stop(); return nil }
        let epoch = engine.beginEpoch()
        var camera: Camera?
        let engine = self.engine
        guard step("stream-\(label)", {
            guard let added = try session.addCamera(config: StreamConfiguration(videoCodec: .raw, resolution: .high, frameRate: 30)) else { throw CaptureFailure.disconnected }
            camera = added
            tokens.append(added.stream.videoFramePublisher.listen { frame in engine.sdkFrame(frame, epoch: epoch) })
            tokens.append(added.stream.statePublisher.listen { state in engine.event("stream-\(label)", String(describing: state)) })
            added.stream.start()
        }), let camera else { session.stop(); return nil }
        for _ in 0..<100 where engine.frameCount(epoch: epoch) == 0 { await pause(0.1) }
        engine.event("first-frame-\(label)", "\(engine.frameCount(epoch: epoch))")
        return Running(session: session, camera: camera, epoch: epoch)
    }

    private func write(complete: Bool) {
        var out = report
        for (k, v) in engine.snapshot() { out[k] = v }
        out["steps"] = steps; out["complete"] = complete; out["writtenUptime"] = uptimeNow
        guard JSONSerialization.isValidJSONObject(out), let data = try? JSONSerialization.data(withJSONObject: out, options: [.sortedKeys]) else {
            frameAgeLog("report not serializable"); return
        }
        try? data.write(to: Self.documents.appendingPathComponent("frame-age-report.json"), options: .atomic)
    }
}
#endif
