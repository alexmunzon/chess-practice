// Simulator-only mock-glasses source (docs/MOCK_GLASSES_RUN.md; Phases 3-4 of docs/MOCK_DEVICE_KIT_PLAN.md).
// Compiled only by `prepare_app.py --simulator --mock-glasses <frameworks>` (-D COMPANION_MOCK_GLASSES), and it
// runs only when the app is launched with `--mock-glasses`. It drives Meta's Mock Device Kit with the bundled,
// SHA-256-pinned test video, measures the delivered frames and proves that every frame stays `.unknownDAT`
// (no engine or speech permit). It never uses the phone camera feed, microphone, audio session or speech,
// never registers, and never requests a Meta or iOS permission. Proving plumbing only: no advice from glasses.
#if COMPANION_MOCK_GLASSES && !targetEnvironment(simulator)
#error("COMPANION_MOCK_GLASSES is Simulator-only")
#endif
#if COMPANION_MOCK_GLASSES && os(iOS) && targetEnvironment(simulator)
import CoreMedia
import CoreVideo
import CryptoKit
import Foundation
import SwiftUI
import UIKit
import MWDATCore
import MWDATCamera
import MWDATMockDevice

func mockGlassesLog(_ text: String) {
    NSLog("MOCKGLASSES %@", text as NSString)
    MockGlassesRecorder.shared.appendLog(text)
}

enum MockGlassesLaunch {
    static let argument = "--mock-glasses"
    static let videoSHA256 = "cf99c6661507c5de71fb931e2abfff1d2c4109a5520cd8e9202604bf2f3b8e87"
    static var requested: Bool { ProcessInfo.processInfo.arguments.contains(argument) }
    static var stage: MockGlassesRunner.Stage {
        let args = ProcessInfo.processInfo.arguments
        if let at = args.firstIndex(of: "--mock-glasses-stage"), at + 1 < args.count,
           let stage = MockGlassesRunner.Stage(rawValue: args[at + 1]) { return stage }
        return .full
    }
    static var documents: URL { FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0] }
}

/// Entry hook. ChessCompanionApp.swift attaches `SelfTestHook(...)` under `#if COMPANION_SELFTEST ||
/// COMPANION_MOCK_GLASSES` (a same-line edit, so normal builds keep identical line numbers and bytes). SelfTest.swift
/// is never compiled into the mock copy, so this file provides that name here: it only starts the mock-glasses
/// runner. Without the launch argument `--mock-glasses` it only logs one line and writes
/// Documents/mock-glasses-absent.txt; it makes no Meta SDK call. No self-test runs.
struct SelfTestHook: ViewModifier {
    let model: OfflineStudyModel
    let replay: ReplayGameModel
    let modeState: AppModeState
    func body(content: Content) -> some View {
        content.task { await MockGlassesRunner.launchIfRequested() }
    }
}

// MARK: - Frame-index code reader (port of scripts/simulation/verify-mock-glasses-video.py read_nonce)

enum MockGlassesNonce {
    static let cols = 16, rows = 4
    static let blackMax = 80.0, whiteMin = 175.0

    static func crc8(_ byte: Int) -> Int {
        var crc = 0xFF ^ byte
        for _ in 0..<8 { crc = crc & 0x80 != 0 ? ((crc << 1) ^ 0x07) & 0xFF : (crc << 1) & 0xFF }
        return crc
    }

    /// Returns (index, reason). `luma(x, y0, x1, y1)` gives the mean full-range luma of a pixel rectangle.
    static func read(width: Int, height: Int, mean: (Int, Int, Int, Int) -> Double) -> (Int?, String) {
        let w = Double(width), h = Double(height)
        guard abs(h / w - 1280.0 / 720.0) <= 1e-6 else { return (nil, "not-9x16") }
        let s = w / 720.0, block = 40 * s, gridX = 40 * s
        var results: [(Int?, String)] = []
        for y0 in [60 * s, 1060 * s] {
            var grid = [[Int]](repeating: [Int](repeating: -1, count: cols), count: rows)
            for r in 0..<rows {
                for c in 0..<cols {
                    let x1 = Int((gridX + (Double(c) + 0.25) * block).rounded(.toNearestOrEven))
                    let x2 = Int((gridX + (Double(c) + 0.75) * block).rounded(.toNearestOrEven))
                    let y1 = Int((y0 + (Double(r) + 0.25) * block).rounded(.toNearestOrEven))
                    let y2 = Int((y0 + (Double(r) + 0.75) * block).rounded(.toNearestOrEven))
                    let v = mean(x1, y1, max(x2, x1 + 1), max(y2, y1 + 1))
                    grid[r][c] = v <= blackMax ? 0 : v >= whiteMin ? 1 : -1
                }
            }
            results.append(decode(grid))
        }
        guard let a = results[0].0, let b = results[1].0 else { return (nil, "top:\(results[0].1),bottom:\(results[1].1)") }
        return a == b ? (a, "ok") : (nil, "copies-disagree")
    }

    static func decode(_ grid: [[Int]]) -> (Int?, String) {
        if grid.joined().contains(-1) { return (nil, "ambiguous-block") }
        let start = (0..<cols).map { $0 % 2 }, stop = (0..<cols).map { 1 - $0 % 2 }
        guard grid[0] == start, grid[3] == stop else { return (nil, "bad-start-stop") }
        let blocks = grid[1] + grid[2]
        var value = 0
        for i in stride(from: 0, to: 32, by: 2) {
            switch (blocks[i], blocks[i + 1]) {
            case (0, 1): value = (value << 1) | 1
            case (1, 0): value = value << 1
            default: return (nil, "bad-manchester-pair")
            }
        }
        let index = value >> 8, check = value & 0xFF
        return crc8(index) == check ? (index, "ok") : (nil, "bad-crc")
    }

    static func read(_ buffer: CVPixelBuffer) -> (Int?, String) {
        CVPixelBufferLockBaseAddress(buffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(buffer, .readOnly) }
        let format = CVPixelBufferGetPixelFormatType(buffer)
        let width = CVPixelBufferGetWidth(buffer), height = CVPixelBufferGetHeight(buffer)
        if CVPixelBufferIsPlanar(buffer) {
            guard let base = CVPixelBufferGetBaseAddressOfPlane(buffer, 0) else { return (nil, "no-luma-plane") }
            let row = CVPixelBufferGetBytesPerRowOfPlane(buffer, 0)
            let pixels = base.assumingMemoryBound(to: UInt8.self)
            let videoRange = format == kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange
                || format == kCVPixelFormatType_420YpCbCr10BiPlanarVideoRange
            guard format == kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange
                    || format == kCVPixelFormatType_420YpCbCr8BiPlanarFullRange else { return (nil, "unsupported-planar-\(fourCC(format))") }
            return read(width: width, height: height) { x1, y1, x2, y2 in
                var sum = 0, count = 0
                for y in y1..<min(y2, height) { for x in x1..<min(x2, width) { sum += Int(pixels[y * row + x]); count += 1 } }
                let y = count == 0 ? 128.0 : Double(sum) / Double(count)
                return videoRange ? (y - 16) * 255 / 219 : y
            }
        }
        guard format == kCVPixelFormatType_32BGRA, let base = CVPixelBufferGetBaseAddress(buffer) else { return (nil, "unsupported-\(fourCC(format))") }
        let row = CVPixelBufferGetBytesPerRow(buffer)
        let pixels = base.assumingMemoryBound(to: UInt8.self)
        return read(width: width, height: height) { x1, y1, x2, y2 in
            var sum = 0.0, count = 0
            for y in y1..<min(y2, height) {
                for x in x1..<min(x2, width) {
                    let p = y * row + x * 4
                    sum += 0.0722 * Double(pixels[p]) + 0.7152 * Double(pixels[p + 1]) + 0.2126 * Double(pixels[p + 2]); count += 1
                }
            }
            return count == 0 ? 128 : sum / Double(count)
        }
    }

    static func fourCC(_ code: FourCharCode) -> String {
        let bytes = [24, 16, 8, 0].map { UInt8((code >> $0) & 0xFF) }
        return bytes.allSatisfy({ $0 >= 32 && $0 < 127 }) ? String(decoding: bytes, as: UTF8.self) : String(code)
    }
}

// MARK: - Thread-safe recorder (SDK callbacks arrive on SDK queues)

final class MockGlassesRecorder: @unchecked Sendable {
    static let shared = MockGlassesRecorder()
    private let lock = NSLock()
    private var frames: [[String: Any]] = []
    private var transitions: [[String: Any]] = []
    private var logLines: [String] = []
    private var phaseName = "none"
    private var pngWritten = 0
    private let pngQueue = DispatchQueue(label: "mock-glasses-png", qos: .utility)
    static let pngLimit = 60, pngEvery = 10

    var phase: String {
        get { lock.withLock { phaseName } }
        set { lock.withLock { phaseName = newValue }; transition("phase", newValue) }
    }
    func appendLog(_ line: String) {
        let stamped = String(format: "%.3f ", ProcessInfo.processInfo.systemUptime) + line
        lock.withLock { logLines.append(stamped) }
    }
    func transition(_ kind: String, _ value: String) {
        let entry: [String: Any] = ["uptime": ProcessInfo.processInfo.systemUptime, "kind": kind, "value": value]
        lock.withLock { transitions.append(entry) }
    }
    func frameCount(phasePrefix: String? = nil) -> Int {
        lock.withLock { phasePrefix.map { p in frames.filter { ($0["phase"] as? String)?.hasPrefix(p) == true }.count } ?? frames.count }
    }
    func snapshot() -> (frames: [[String: Any]], transitions: [[String: Any]], log: [String]) {
        lock.withLock { (frames, transitions, logLines) }
    }

    /// Called from the SDK's frame listener. Receipt uptime is read first.
    func record(_ frame: VideoFrame) {
        let uptime = ProcessInfo.processInfo.systemUptime
        let buffer = frame.sampleBuffer
        let pts = CMSampleBufferGetPresentationTimeStamp(buffer)
        let duration = CMSampleBufferGetDuration(buffer)
        let description = CMSampleBufferGetFormatDescription(buffer)
        let dims = description.map { CMVideoFormatDescriptionGetDimensions($0) }
        let subtype = description.map { CMFormatDescriptionGetMediaSubType($0) }
        var entry: [String: Any] = [
            "uptime": uptime, "ptsValue": pts.value, "ptsTimescale": pts.timescale,
            "ptsValid": pts.isValid && pts.isNumeric, "durationValue": duration.value, "durationTimescale": duration.timescale,
            "formatSubtype": subtype.map(MockGlassesNonce.fourCC) ?? "none",
            "width": Int(dims?.width ?? 0), "height": Int(dims?.height ?? 0)]
        if let image = CMSampleBufferGetImageBuffer(buffer) {
            entry["pixelFormat"] = MockGlassesNonce.fourCC(CVPixelBufferGetPixelFormatType(image))
            entry["bufferWidth"] = CVPixelBufferGetWidth(image); entry["bufferHeight"] = CVPixelBufferGetHeight(image)
            let (index, reason) = MockGlassesNonce.read(image)
            entry["nonceIndex"] = index ?? NSNull(); entry["nonceReason"] = reason
        } else {
            entry["pixelFormat"] = "no-image-buffer"; entry["nonceIndex"] = NSNull(); entry["nonceReason"] = "no-image-buffer"
        }
        let arrival: Int = lock.withLock {
            entry["arrival"] = frames.count; entry["phase"] = phaseName
            frames.append(entry); return frames.count - 1
        }
        let dump: Bool = lock.withLock {
            guard arrival % Self.pngEvery == 0, pngWritten < Self.pngLimit else { return false }
            pngWritten += 1; return true
        }
        if dump {
            pngQueue.async {
                let url = MockGlassesLaunch.documents.appendingPathComponent("mock-frames/frame-\(String(format: "%05d", arrival)).png")
                try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
                try? frame.makeUIImage()?.pngData()?.write(to: url)
            }
        }
    }
}

// MARK: - Mock collaborators for the real CaptureCoordinator (counting only; never advice)

final class MockGlassesCounters: @unchecked Sendable {
    private let lock = NSLock()
    private var values: [String: Int] = [:]
    private var captureKinds: [String] = []
    func bump(_ key: String) { lock.withLock { values[key, default: 0] += 1 } }
    func value(_ key: String) -> Int { lock.withLock { values[key, default: 0] } }
    func noteCapture(_ time: CaptureTime) {
        let kind: String
        switch time { case .unknownDAT: kind = "unknownDAT"; case .trustedReplay: kind = "trustedReplay" }
        lock.withLock { captureKinds.append(kind) }
    }
    var kinds: [String] { lock.withLock { captureKinds } }
    var all: [String: Int] { lock.withLock { values } }
}

/// Returns a COMPLETE proposal on purpose: everything except frame age is satisfied, so the run shows that
/// the unknown capture age alone keeps the gate shut. It is a test stub, not recognition.
final class MockGlassesRecognizer: FrameRecognizer, @unchecked Sendable {
    let counters: MockGlassesCounters
    init(counters: MockGlassesCounters) { self.counters = counters }
    func recognize(_ frame: CapturedFrame) async throws -> BoardProposal {
        counters.bump("recognizeCalls"); counters.noteCapture(frame.captureTime)
        let ranks = ["rnbqkbnr", "pppppppp", "8", "8", "8", "8", "PPPPPPPP", "RNBQKBNR"]
        var squares: [String: SquarePrediction] = [:]
        for (row, text) in ranks.enumerated() {
            let cells: [String] = text == "8" ? Array(repeating: "empty", count: 8) : text.map(String.init)
            for (file, label) in zip("abcdefgh", cells) { squares["\(file)\(8 - row)"] = SquarePrediction(label: label, confidence: 1) }
        }
        return BoardProposal(frame: frame.identity, squares: squares)
    }
}
final class MockGlassesEngine: NativeChessEngine, @unchecked Sendable {
    let counters: MockGlassesCounters
    init(counters: MockGlassesCounters) { self.counters = counters }
    func analyze(_ request: AnalysisRequest) async throws -> NativeEngineResult {
        counters.bump("engineAnalyzeCalls"); throw CaptureFailure.invalidEngineResult
    }
}
@MainActor final class MockGlassesRules: LocalChessRules {
    let counters: MockGlassesCounters
    init(counters: MockGlassesCounters) { self.counters = counters }
    func validatePosition(_ fullFEN: String) async throws -> ValidatedPosition {
        counters.bump("rulesValidateCalls"); return ValidatedPosition(fen: fullFEN, terminal: false)
    }
    func speechForLegalMove(fen: String, moveUCI: String) async throws -> String {
        counters.bump("rulesSpeechTextCalls"); throw CaptureFailure.noRecommendation
    }
}
@MainActor final class MockGlassesSpeechSink: CancellableSpeechOutput {
    let counters: MockGlassesCounters
    init(counters: MockGlassesCounters) { self.counters = counters }
    func cancel() { counters.bump("speechCancelCalls") }
    func speak(_ text: String, permit: SpeechPermit, isCurrent: @escaping @MainActor () -> Bool) async throws {
        counters.bump("speechSpeakCalls"); throw CaptureFailure.speechExperimentDisabled
    }
}

final class MockGlassesFlag: @unchecked Sendable {
    private let lock = NSLock()
    private var flag = true
    var value: Bool { get { lock.withLock { flag } } set { lock.withLock { flag = newValue } } }
}

// MARK: - Safety evaluation (pure; also run on a mutated copy as the deliberate negative control)

struct MockGlassesSafetyInput {
    var captureKinds: [String]          // capture-time label of every frame that reached the stub recognizer
    var latestFrameKinds: [String]      // label of the coordinator's latest frame, sampled every 50 ms
    var recommendationsObserved: Int    // samples (50 ms poll) in which coordinator.recommendation was non-nil
    var engineAnalyzeCalls: Int
    var rulesSpeechTextCalls: Int
    var speechSpeakCalls: Int
    var gateProbeError: String?
}
enum MockGlassesSafety {
    static func evaluate(_ input: MockGlassesSafetyInput) -> [String: Bool] {
        let seen = input.captureKinds + input.latestFrameKinds
        return [
            "everyFrameUnknownDAT": !seen.isEmpty && seen.allSatisfy { $0 == "unknownDAT" },
            // The coordinator exposes no permit counter. A SpeechPermit is only created in finishEngine, after an
            // engine result AND rules.speechForLegalMove; both stubs count calls, so 0 + 0 means no permit was possible.
            "noPermitPossibleEngineAndSpeechTextCallsZero": input.engineAnalyzeCalls == 0 && input.rulesSpeechTextCalls == 0,
            "noRecommendationSeenIn50msPoll": input.recommendationsObserved == 0,
            "speechRequestsZero": input.speechSpeakCalls == 0,
            "noAnalysisStarted": input.engineAnalyzeCalls == 0,
            "gateRefusedForUnknownCaptureAge": input.gateProbeError == "unknownCaptureAge",
        ]
    }
}

// MARK: - Runner

@MainActor final class MockGlassesRunner {
    enum Stage: String, CaseIterable { case app, configure, enable, pair, power, don, feed, session, stream, full }
    private static var started = false
    private let stage: Stage
    private let recorder = MockGlassesRecorder.shared
    private var report: [String: Any] = [:]
    private var steps: [[String: Any]] = []
    private var glasses: (any MockGlasses)?
    private var listenerTokens: [any AnyListenerToken] = []
    private let videoURL = Bundle.main.bundleURL.appendingPathComponent("MockGlasses/replay-14.mp4")

    init(stage: Stage) { self.stage = stage }

    static func launchIfRequested() async {
        guard MockGlassesLaunch.requested else {
            mockGlassesLog("launch argument --mock-glasses absent: no Meta SDK call made; normal app only")
            try? "argument absent; no Meta SDK call made\n".write(to: MockGlassesLaunch.documents.appendingPathComponent("mock-glasses-absent.txt"), atomically: true, encoding: .utf8)
            return
        }
        guard !started else { return }
        started = true
        await MockGlassesRunner(stage: MockGlassesLaunch.stage).run()
    }

    private var uptime: Double { ProcessInfo.processInfo.systemUptime }
    private func pause(_ seconds: Double) async { try? await Task.sleep(for: .milliseconds(Int(seconds * 1000))) }

    @discardableResult private func step(_ name: String, _ body: () throws -> Void) -> Bool {
        let start = uptime
        do {
            try body()
            steps.append(["name": name, "uptime": start, "ok": true]); recorder.transition("step", name + ":ok")
            mockGlassesLog("step \(name) ok"); writeReport(complete: false); return true
        } catch {
            steps.append(["name": name, "uptime": start, "ok": false, "error": String(describing: error)])
            recorder.transition("step", name + ":error:" + String(describing: error))
            mockGlassesLog("step \(name) FAILED \(error)"); writeReport(complete: false); return false
        }
    }
    private func reached(_ s: Stage) -> Bool {
        Stage.allCases.firstIndex(of: stage)! >= Stage.allCases.firstIndex(of: s)!
    }

    func run() async {
        report = ["schemaVersion": 1, "stageRequested": stage.rawValue, "launchUptime": uptime,
                  "bundleIdentifier": Bundle.main.bundleIdentifier ?? "", "arguments": ProcessInfo.processInfo.arguments]
        mockGlassesLog("runner start stage=\(stage.rawValue)")
        defer { writeReport(complete: true); mockGlassesLog("runner done") }
        // Pinned video first: refuse to feed anything else.
        guard step("verify-video", {
            let data = try Data(contentsOf: videoURL)
            let hash = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
            guard hash == MockGlassesLaunch.videoSHA256 else { throw CaptureFailure.invalidFrame }
            report["videoSha256"] = hash; report["videoBytes"] = data.count
        }) else { return }
        guard reached(.configure), step("configure", { try Wearables.configure() }) else { return }
        report["registrationStateAfterConfigure"] = String(describing: Wearables.shared.registrationState)
        let kit = MockDeviceKit.shared
        guard reached(.enable), step("enable-mock", {
            kit.enable(config: MockDeviceKitConfig(initiallyRegistered: true, initialPermissionsGranted: true))
            report["mockEnabled"] = kit.isEnabled
        }) else { return }
        await pause(1)
        report["registrationStateAfterEnable"] = String(describing: Wearables.shared.registrationState)
        guard reached(.pair), step("pair-rayBanMeta", {
            let pairedGlasses = try kit.pairGlasses(model: .rayBanMeta)
            glasses = pairedGlasses; report["deviceIdentifier"] = pairedGlasses.deviceIdentifier
        }), let glasses else { return }
        listenerTokens.append(Wearables.shared.addDevicesListener { ids in MockGlassesRecorder.shared.transition("devices", ids.joined(separator: ",")) })
        guard reached(.power), step("power-on", { glasses.powerOn() }) else { return }
        guard reached(.don), step("unfold-and-don", { glasses.unfold(); glasses.don() }) else { return }
        guard reached(.feed), step("set-file-feed", { glasses.services.camera.setCameraFeed(fileURL: videoURL) }) else { return }
        // What the app itself can see of wear / hinge / link state (read-only listener).
        if let device = Wearables.shared.deviceForIdentifier(glasses.deviceIdentifier) {
            listenerTokens.append(device.addDeviceStateListener { state in
                MockGlassesRecorder.shared.transition("deviceState", "link=\(state.linkState) don=\(state.donState) hinge=\(state.hingeState)")
            })
        }
        await pause(1)
        guard reached(.session) else { return }
        report["measureStreamConfig"] = ["videoCodec": "raw", "resolution": "high", "frameRate": 30,
                                         "expectedFrameSize": "\(StreamingResolution.high.videoFrameSize.width)x\(StreamingResolution.high.videoFrameSize.height)"]
        guard var measure = await startMeasureStream(label: "measure", phase: "steady") else { return }
        if stage == .stream {
            await pause(10); measure.1.stream.stop(); await pause(1); measure.0.stop(); return
        }
        // Full: 40 s steady (the 30 s file must loop), then doff / fold / power cycles.
        await pause(40)
        report["steadyFrames"] = recorder.frameCount(phasePrefix: "steady")
        for (name, off, on) in [("doff", { glasses.doff() }, { glasses.don() }),
                                ("fold", { glasses.fold() }, { glasses.unfold() }),
                                ("powerOff", { glasses.powerOff() }, { glasses.powerOn() })] as [(String, () -> Void, () -> Void)] {
            recorder.phase = "\(name)-off"; recorder.transition("action", name); off()
            await pause(4)
            recorder.phase = "\(name)-restored"; recorder.transition("action", name + "-inverse"); on()
            await pause(6)
            if recorder.frameCount(phasePrefix: "\(name)-restored") == 0 {
                // Inverse alone did not resume: redo the full sequence (power, unfold, don, new session, camera, stream).
                recorder.transition("action", name + "-full-resequence")
                measure.1.stream.stop(); measure.0.stop(); await pause(1)
                glasses.powerOn(); glasses.unfold(); glasses.don(); await pause(1)
                guard let next = await startMeasureStream(label: "measure-after-\(name)", phase: "\(name)-resequence") else { break }
                measure = next
                await pause(6)
            }
        }
        recorder.phase = "measure-stop"
        measure.1.stream.stop(); await pause(1); measure.0.stop(); await pause(1)
        report["measureSessionFinalState"] = String(describing: measure.0.state)
        await adapterPhase(kit: kit, glasses: glasses)
    }

    /// Own measurement stream (raw, high, 30 fps): every frame is logged by the recorder; nothing enters the coordinator.
    private func startMeasureStream(label: String, phase: String) async -> (DeviceSession, Camera)? {
        guard let session = await openSession(label: label) else { return nil }
        guard reached(.stream) else { session.stop(); return nil }
        var camera: Camera?
        guard step("add-camera-and-start-stream-\(label)", {
            guard let added = try session.addCamera(config: StreamConfiguration(videoCodec: .raw, resolution: .high, frameRate: 30)) else { throw CaptureFailure.disconnected }
            camera = added
            listenerTokens.append(added.stream.videoFramePublisher.listen { frame in MockGlassesRecorder.shared.record(frame) })
            listenerTokens.append(added.stream.statePublisher.listen { state in MockGlassesRecorder.shared.transition("stream-\(label)", String(describing: state)) })
            listenerTokens.append(added.stream.errorPublisher.listen { error in MockGlassesRecorder.shared.transition("streamError-\(label)", String(describing: error)) })
            recorder.phase = phase
            added.stream.start()
        }), let camera else { session.stop(); return nil }
        return (session, camera)
    }

    private func openSession(label: String) async -> DeviceSession? {
        var created: DeviceSession?
        guard step("create-and-start-session-\(label)", {
            guard let glasses else { throw CaptureFailure.disconnected }
            let session = try Wearables.shared.createSession(deviceSelector: SpecificDeviceSelector(device: glasses.deviceIdentifier))
            listenerTokens.append(session.statePublisher.listen { state in MockGlassesRecorder.shared.transition("session-\(label)", String(describing: state)) })
            try session.start(); created = session
        }), let session = created else { return nil }
        for _ in 0..<100 where session.state != .started { await pause(0.1) }
        recorder.transition("session-\(label)-wait", String(describing: session.state))
        guard session.state == .started else {
            steps.append(["name": "session-\(label)-started", "uptime": uptime, "ok": false, "error": String(describing: session.state)])
            session.stop(); return nil
        }
        return session
    }

    // MARK: Existing capture path: DATCaptureAdapter -> CaptureCoordinator, with revoke cycles

    private func adapterPhase(kit: any MockDeviceKitInterface, glasses: any MockGlasses) async {
        let counters = MockGlassesCounters()
        guard let coordinator = try? CaptureCoordinator(
            recognizer: MockGlassesRecognizer(counters: counters), engine: MockGlassesEngine(counters: counters),
            rules: MockGlassesRules(counters: counters), speech: MockGlassesSpeechSink(counters: counters),
            maxCaptureAgeSeconds: 10) else { return }
        // Everything except frame age is made as permissive as possible, so only the age gate can refuse.
        coordinator.setSpeechExperimentEnabled(true)
        var latestKinds: [String] = []
        var coordinatorFrameIDs = Set<String>()
        var recommendationsObserved = 0
        let watcher = Task { @MainActor in
            while !Task.isCancelled {
                if coordinator.recommendation != nil { recommendationsObserved += 1 }
                if let frame = coordinator.latestFrame {
                    switch frame.captureTime { case .unknownDAT: latestKinds.append("unknownDAT"); case .trustedReplay: latestKinds.append("trustedReplay") }
                    coordinatorFrameIDs.insert("\(frame.identity.sessionID)-\(frame.identity.sequence)")
                }
                try? await Task.sleep(for: .milliseconds(50))
            }
        }
        func state() -> [String: Any] {
            ["uptime": uptime, "cameraState": String(describing: coordinator.cameraState), "reason": coordinator.reason,
             "latestFrame": coordinator.latestFrame != nil, "proposal": coordinator.proposal != nil,
             "recommendation": coordinator.recommendation != nil, "epoch": coordinator.epoch,
             "recognizeCalls": counters.value("recognizeCalls")]
        }
        func analyzeError() -> String {
            do { try coordinator.analyzeReviewedPosition(); return "NO-ERROR" } catch { return String(describing: error) }
        }
        func baseline() { kit.permissions.set(.camera, .granted); glasses.powerOn(); glasses.unfold(); glasses.don() }
        func arm(_ label: String) async -> (DeviceSession, DATCaptureAdapter)? {
            baseline(); await pause(1)
            guard let session = await openSession(label: label) else { return nil }
            let adapter = DATCaptureAdapter(coordinator: coordinator)
            guard step("adapter-start-\(label)", { try adapter.start(in: session) }) else { session.stop(); return nil }
            let before = counters.value("recognizeCalls")
            for _ in 0..<100 where counters.value("recognizeCalls") - before < 3 { await pause(0.1) }
            return (session, adapter)
        }
        recorder.phase = "adapter"
        var cycles: [[String: Any]] = []
        // 1. Gate probe: stop acknowledged, complete proposal, full five-part review, speech experiment on.
        var gateProbe: [String: Any] = ["name": "gate-probe"]
        if let armed = await arm("gate-probe") {
            let (session, adapter) = armed
            gateProbe["armed"] = state()
            do { try adapter.requestStop() } catch { gateProbe["requestStopError"] = String(describing: error) }
            for _ in 0..<50 { if case .stoppedAcknowledged = coordinator.cameraState { break }; await pause(0.1) }
            for _ in 0..<30 where coordinator.proposal == nil { await pause(0.1) }
            gateProbe["afterStop"] = state()
            do {
                try await coordinator.confirm(fullFEN: "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                                              review: FullStateReview(pieces: true, turn: true, castling: true, enPassant: true, counters: true))
                gateProbe["confirm"] = "reviewed"
            } catch { gateProbe["confirm"] = String(describing: error) }
            gateProbe["analyzeError"] = analyzeError()
            do { try await coordinator.speakRecommendation(); gateProbe["speakError"] = "NO-ERROR" } catch { gateProbe["speakError"] = String(describing: error) }
            gateProbe["final"] = state()
            await adapter.disconnect(); session.stop(); await pause(1)
        }
        cycles.append(gateProbe)
        // 1b. Direct gate probe: the same CaptureCoordinator fed exactly as DATCaptureAdapter does (JPEG bytes,
        // receipt uptime, media PTS via submitDAT), but stopped in a strict order (stream stopped and drained,
        // then stop request + acknowledgement), so every gate condition except frame age is met.
        var direct: [String: Any] = ["name": "gate-probe-direct"]
        baseline(); await pause(1)
        if let session = await openSession(label: "gate-direct") {
            let forwarding = MockGlassesFlag()
            var camera: Camera?
            var epoch: UInt64 = 0
            let (deliveries, continuation) = AsyncStream<(VideoFrame, Double, MediaTimestamp?)>.makeStream(bufferingPolicy: .bufferingNewest(1))
            let pump = Task { @MainActor in
                for await (frame, receivedAt, pts) in deliveries {
                    guard forwarding.value else { continue }
                    coordinator.noteIncomingFrame(epoch: epoch)
                    guard let bytes = frame.makeUIImage()?.jpegData(compressionQuality: 0.9) else { continue }
                    _ = try? coordinator.submitDAT(bytes: bytes, receivedAtHostSeconds: receivedAt, mediaPTS: pts, epoch: epoch)
                }
            }
            if step("direct-gate-start", {
                epoch = try coordinator.connect()
                guard let added = try session.addCamera(config: StreamConfiguration(videoCodec: .raw, resolution: .medium, frameRate: 2)) else { throw CaptureFailure.disconnected }
                camera = added
                listenerTokens.append(added.stream.videoFramePublisher.listen { frame in
                    let receivedAt = ProcessInfo.processInfo.systemUptime
                    let pts = CMSampleBufferGetPresentationTimeStamp(frame.sampleBuffer)
                    continuation.yield((frame, receivedAt, pts.isValid && pts.isNumeric ? MediaTimestamp(value: pts.value, timescale: pts.timescale) : nil))
                })
                listenerTokens.append(added.stream.statePublisher.listen { state in MockGlassesRecorder.shared.transition("stream-gate-direct", String(describing: state)) })
                try coordinator.cameraStarted(epoch: epoch)
                added.stream.start()
            }), let camera {
                let before = counters.value("recognizeCalls")
                for _ in 0..<100 where counters.value("recognizeCalls") - before < 3 { await pause(0.1) }
                direct["armed"] = state()
                forwarding.value = false
                camera.stream.stop()
                for _ in 0..<50 where camera.stream.state != .stopped { await pause(0.1) }
                await pause(0.5)
                direct["streamStateAfterStop"] = String(describing: camera.stream.state)
                do {
                    let request = try coordinator.requestCameraStop()
                    try coordinator.acknowledgeCameraStopped(epoch: epoch, requestID: request)
                } catch { direct["stopAckError"] = String(describing: error) }
                for _ in 0..<30 where coordinator.proposal == nil { await pause(0.1) }
                direct["afterStop"] = state()
                do {
                    try await coordinator.confirm(fullFEN: "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                                                  review: FullStateReview(pieces: true, turn: true, castling: true, enPassant: true, counters: true))
                    direct["confirm"] = "reviewed"
                } catch { direct["confirm"] = String(describing: error) }
                direct["analyzeError"] = analyzeError()
                do { try await coordinator.speakRecommendation(); direct["speakError"] = "NO-ERROR" } catch { direct["speakError"] = String(describing: error) }
                direct["final"] = state()
                // From the completed review: resume the stream. New frames must revoke the review, so the refusal
                // reason becomes "incompleteReview". (A review cannot persist while frames arrive, so revoke cycles on a
                // running stream can never be refused for "unknown frame age"; only a stopped stream reaches that check.)
                // No manual revoke call here: only the arriving frames (submitDAT) act on the coordinator.
                direct["analyzeBeforeResume"] = analyzeError()
                forwarding.value = true
                camera.stream.start()
                await pause(3)
                direct["afterResume"] = state(); direct["analyzeAfterResume"] = analyzeError()
                forwarding.value = false; camera.stream.stop(); await pause(0.5)
            }
            continuation.finish(); pump.cancel()
            coordinator.disconnect(); session.stop(); await pause(1)
        }
        cycles.append(direct)
        // 2. Revoke cycles.
        let events: [(String, () -> Void, () -> Void)] = [
            ("doff", { glasses.doff() }, { glasses.don() }),
            ("fold", { glasses.fold() }, { glasses.unfold() }),
            ("powerOff", { glasses.powerOff() }, { glasses.powerOn() }),
            ("permissionDenied", { kit.permissions.set(.camera, .denied) }, { kit.permissions.set(.camera, .granted) }),
        ]
        for (name, event, inverse) in events {
            var cycle: [String: Any] = ["name": name]
            guard let armed = await arm(name) else { cycle["armed"] = false; cycles.append(cycle); continue }
            let (session, adapter) = armed
            cycle["armed"] = state()
            recorder.transition("adapter-event", name); event()
            await pause(1); cycle["after1s"] = state(); cycle["analyzeAfter1s"] = analyzeError()
            let held = counters.value("recognizeCalls")
            await pause(3); cycle["after4s"] = state(); cycle["analyzeAfter4s"] = analyzeError()
            cycle["framesIntoCoordinatorWhileRevoked"] = counters.value("recognizeCalls") - held
            // Only the inverse action (not the full sequence): record whether frames come back by themselves.
            recorder.transition("adapter-event", name + "-inverse-only"); inverse()
            await pause(4); cycle["afterInverseOnly4s"] = state(); cycle["analyzeAfterInverseOnly"] = analyzeError()
            await adapter.disconnect(); session.stop(); await pause(1)
            cycle["afterDisconnect"] = state()
            cycles.append(cycle)
        }
        // 3. Denied before start: does a stream start at all?
        var deniedStart: [String: Any] = ["name": "permissionDeniedBeforeStart"]
        baseline(); kit.permissions.set(.camera, .denied); await pause(1)
        if let session = await openSession(label: "denied-before-start") {
            let adapter = DATCaptureAdapter(coordinator: coordinator)
            let before = counters.value("recognizeCalls")
            deniedStart["startError"] = step("adapter-start-denied-before-start", { try adapter.start(in: session) }) ? "none" : "threw"
            await pause(4)
            deniedStart["framesIntoCoordinator"] = counters.value("recognizeCalls") - before
            deniedStart["state"] = state(); deniedStart["analyzeError"] = analyzeError()
            await adapter.disconnect(); session.stop(); await pause(1)
        }
        kit.permissions.set(.camera, .granted)
        cycles.append(deniedStart)
        watcher.cancel(); await pause(0.2)
        report["adapterCycles"] = cycles
        // Per event: revoked 1 s and 4 s after it, no frame entered meanwhile, still revoked after the inverse
        // action alone, and the gate refused analysis at every sample.
        var revoke: [String: Any] = [:]
        for cycle in cycles {
            guard let name = cycle["name"] as? String, ["doff", "fold", "powerOff", "permissionDenied"].contains(name) else { continue }
            func revoked(_ key: String) -> Bool {
                guard let s = cycle[key] as? [String: Any] else { return false }
                return (s["cameraState"] as? String) == "inactive" && (s["latestFrame"] as? Bool) == false && (s["recommendation"] as? Bool) == false
            }
            let refusals = ["analyzeAfter1s", "analyzeAfter4s", "analyzeAfterInverseOnly"].map { cycle[$0] as? String ?? "missing" }
            revoke[name] = ["revokedAfter1s": revoked("after1s"), "revokedAfter4s": revoked("after4s"),
                            "noFramesWhileRevoked": (cycle["framesIntoCoordinatorWhileRevoked"] as? Int) == 0,
                            "staysRevokedAfterInverseOnly": revoked("afterInverseOnly4s"),
                            "gateRefusedAtEverySample": refusals.allSatisfy { $0 != "NO-ERROR" && $0 != "missing" },
                            "pass": revoked("after1s") && revoked("after4s") && (cycle["framesIntoCoordinatorWhileRevoked"] as? Int) == 0 && revoked("afterInverseOnly4s")]
        }
        report["revokeAssertions"] = revoke
        report["counters"] = counters.all
        let input = MockGlassesSafetyInput(captureKinds: counters.kinds, latestFrameKinds: latestKinds,
                                           recommendationsObserved: recommendationsObserved,
                                           engineAnalyzeCalls: counters.value("engineAnalyzeCalls"),
                                           rulesSpeechTextCalls: counters.value("rulesSpeechTextCalls"),
                                           speechSpeakCalls: counters.value("speechSpeakCalls"),
                                           gateProbeError: direct["analyzeError"] as? String)
        report["safety"] = MockGlassesSafety.evaluate(input)
        report["safetyInputs"] = ["framesReachedCoordinatorRecognizer": input.captureKinds.count,
                                  "distinctCoordinatorFramesSeenByPoll": coordinatorFrameIDs.count,
                                  "latestFrameSamples": input.latestFrameKinds.count,
                                  "measurementOnlyFramesNeverInCoordinator": recorder.frameCount(),
                                  "scope": "everyFrameUnknownDAT covers frames that reached the coordinator; measurement-stream frames are logged only",
                                  "recommendationsObserved": recommendationsObserved,
                                  "trustedReplaySeen": (input.captureKinds + input.latestFrameKinds).filter { $0 != "unknownDAT" }.count]
        // Deliberate negative controls: each assertion re-run on a mutated COPY of the inputs must turn false.
        var mutations: [(String, String, MockGlassesSafetyInput)] = []
        var m = input
        m = input; m.captureKinds.append("trustedReplay"); mutations.append(("everyFrameUnknownDAT", "one frame relabelled trustedReplay", m))
        m = input; m.engineAnalyzeCalls += 1; m.rulesSpeechTextCalls += 1; mutations.append(("noPermitPossibleEngineAndSpeechTextCallsZero", "one engine result and one speech text", m))
        m = input; m.recommendationsObserved += 1; mutations.append(("noRecommendationSeenIn50msPoll", "one recommendation sample", m))
        m = input; m.speechSpeakCalls += 1; mutations.append(("speechRequestsZero", "one speak call", m))
        m = input; m.engineAnalyzeCalls += 1; mutations.append(("noAnalysisStarted", "one analyze call", m))
        m = input; m.gateProbeError = "NO-ERROR"; mutations.append(("gateRefusedForUnknownCaptureAge", "gate probe accepted", m))
        var controls: [String: Any] = [:]
        for (name, mutation, mutated) in mutations {
            controls[name] = ["mutation": mutation, "resultOnMutatedCopy": MockGlassesSafety.evaluate(mutated)[name] ?? true]
        }
        report["negativeControl"] = controls
        report["negativeControlAllTurnFalse"] = mutations.allSatisfy { MockGlassesSafety.evaluate($0.2)[$0.0] == false }
            && Set(mutations.map(\.0)) == Set(MockGlassesSafety.evaluate(input).keys)
    }

    private func writeReport(complete: Bool) {
        let snap = recorder.snapshot()
        var out = report
        out["complete"] = complete; out["steps"] = steps; out["frames"] = snap.frames
        out["transitions"] = snap.transitions; out["log"] = snap.log; out["writtenUptime"] = uptime
        out["totalFrames"] = snap.frames.count
        let steady = snap.frames.filter { ($0["phase"] as? String) == "steady" }
        if steady.count > 1, let first = steady.first?["uptime"] as? Double, let last = steady.last?["uptime"] as? Double, last > first {
            out["measuredSteadyFps"] = Double(steady.count - 1) / (last - first)
        }
        guard JSONSerialization.isValidJSONObject(out),
              let data = try? JSONSerialization.data(withJSONObject: out, options: [.prettyPrinted, .sortedKeys]) else {
            NSLog("MOCKGLASSES report not serializable"); return
        }
        try? data.write(to: MockGlassesLaunch.documents.appendingPathComponent("mock-glasses-report.json"), options: .atomic)
    }
}
#endif
