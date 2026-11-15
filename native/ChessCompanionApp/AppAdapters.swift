import Foundation
import CryptoKit

struct StudyResources: Sendable {
    struct Asset: Decodable { let byteLength: Int; let sha256: String }
    struct Manifest: Decodable { let schemaVersion: Int; let mode: String; let assets: [String: Asset] }
    let root: URL
    private func read(_ path: String, maximum: Int) throws -> Data {
        let file = root.appendingPathComponent(path).standardizedFileURL.resolvingSymlinksInPath()
        guard file.path.hasPrefix(root.standardizedFileURL.resolvingSymlinksInPath().path + "/") else { throw OfflineStudyError.missingResource }
        let attributes = try FileManager.default.attributesOfItem(atPath: file.path)
        guard attributes[.type] as? FileAttributeType == .typeRegular, let count = (attributes[.size] as? NSNumber)?.intValue,
              count > 0, count <= maximum else { throw OfflineStudyError.missingResource }
        let data = try Data(contentsOf: file)
        guard data.count == count else { throw OfflineStudyError.missingResource }
        return data
    }
    private static let baseLimits = ["synthetic-fixture.png": 8 * 1024 * 1024,
                                     "classic-templates-v1.json": 512 * 1024,
                                     "Runtime/runtime-manifest.json": 32 * 1024]
    private static let fixtureLimits = Dictionary(uniqueKeysWithValues: StudyFixture.allCases
        .filter { $0 != .starting }.map { ($0.asset, 8 * 1024 * 1024) })
    /// Replay-game frames: per bundled game all frames or none, each also pinned by SHA-256 in ReplayFrames.
    private static let replayLimits = Dictionary(uniqueKeysWithValues: ReplayFrames.allAssetNames.map { ($0, ReplayGameModel.maximumFrameBytes) })

    private func manifest() throws -> Manifest {
        let manifest = try JSONDecoder().decode(Manifest.self, from: read("app-assets.json", maximum: 16 * 1024))
        let assets = Set(manifest.assets.keys)
        let base = Set(Self.baseLimits.keys)
        // Optional groups: the study fixtures and each replay game, each present completely or not at all.
        let groups = [Set(Self.fixtureLimits.keys)] + ReplaySequences.all.map { Set($0.allAssets.map(\.asset)) }
        let extra = assets.subtracting(base)
        let covered = groups.filter { !$0.isDisjoint(with: extra) }.reduce(Set<String>()) { $0.union($1) }
        guard manifest.schemaVersion == 1, manifest.mode == "private-unsigned-offline-synthetic-study",
              assets.isSuperset(of: base), covered == extra else { throw OfflineStudyError.missingResource }
        return manifest
    }
    /// The bundled replay games whose every frame is listed with a hash equal to its source pin.
    func replaySequences() throws -> [ReplaySequence] {
        let assets = try manifest().assets
        return ReplaySequences.all.filter { sequence in sequence.allAssets.allSatisfy { assets[$0.asset]?.sha256 == $0.sha256 } }
    }
    /// True when at least one replay game is completely bundled and pinned.
    func replayAvailable() throws -> Bool { try !replaySequences().isEmpty }
    func availableFixtures() throws -> [StudyFixture] {
        let assets = try manifest().assets
        return StudyFixture.allCases.filter { assets[$0.asset] != nil }
    }
    func checked(_ path: String) throws -> Data {
        guard let maximum = Self.baseLimits[path] ?? Self.fixtureLimits[path] ?? Self.replayLimits[path],
              let asset = try manifest().assets[path], asset.byteLength > 0,
              asset.byteLength <= maximum else { throw OfflineStudyError.missingResource }
        let data = try read(path, maximum: maximum)
        guard data.count == asset.byteLength, NativeSyntheticRecognizer.sha256(data) == asset.sha256 else { throw OfflineStudyError.missingResource }
        return data
    }
    func runtimeDirectory() throws -> URL { _ = try checked("Runtime/runtime-manifest.json"); return root.appendingPathComponent("Runtime", isDirectory: true) }
}

actor OfflinePixelRecognizer: OfflineImageRecognizer {
    private let resources: StudyResources
    /// Verified, prepared template features: built on the first successful call, then reused.
    /// Actor isolation serializes access, so no lock is needed. A failed preparation is not
    /// cached; the next call verifies the bundled asset again.
    private var prepared: NativeSyntheticRecognizer?
    init(resources: StudyResources) { self.resources = resources }
    private func recognizer() throws -> NativeSyntheticRecognizer {
        if let prepared { return prepared }
        let recognizer = try NativeSyntheticRecognizer(templateData: resources.checked("classic-templates-v1.json"))
        prepared = recognizer
        return recognizer
    }
    func recognize(_ bytes: Data) async throws -> OfflineBoard {
        try Task.checkCancellation()
        let result = try recognizer().recognize(imageData: bytes)
        try Task.checkCancellation()
        let digest = NativeSyntheticRecognizer.sha256(bytes)
        guard result["source"] as? String == "synthetic-pixel-inference", result["status"] as? String == "needs-human-review",
              result["sourceSha256"] as? String == digest,
              result["guidanceAllowed"] as? Bool == false, result["fen"] is NSNull,
              let cells = result["squares"] as? [String:[String:Any]] else { throw OfflineStudyError.invalidImage }
        var squares: [String:String] = [:]
        for (square, value) in cells {
            // This is the recognizer's native Swift dictionary, not decoded JSON.
            // Its fixed-template acceptance indicator is exactly Int(0) or Int(1).
            guard let label = value["label"] as? String, let confidence = value["confidence"] as? Int,
                  confidence == 0 || confidence == 1 else { throw OfflineStudyError.invalidImage }
            squares[square] = confidence == 1 ? label : "unknown"
        }
        return OfflineBoard(sha256: digest, squares: squares)
    }
}

@MainActor final class LocalOfflineBackend: ReplayEngineBackend {
    private let runtime: NativeEngineRuntime
    private let chess: LocalChessAdapters
    init(resources: StudyResources) throws {
        runtime = try NativeEngineRuntime(resourceDirectory: resources.runtimeDirectory())
        chess = LocalChessAdapters(transport: NativeRuntimeTransport(runtime: runtime))
        // Immediate closed signal: the runtime calls this once when it stops (explicit close included;
        // close() clears the handler first, so only a self-stop reaches the model).
        runtime.onClose = { [weak self] in self?.runtimeStopped() }
    }
    private var started = false
    private var closureHandler: (@MainActor () -> Void)?
    func start() async throws {
        try await runtime.start(); started = true
        // A runtime that died during start (before `started` was set) is reported now, not ignored.
        if !runtime.isReady { runtimeStopped() }
    }
    func validate(_ fen: String) async throws -> ValidatedPosition { try await reporting { try await chess.validatePosition(fen) } }
    func analyze(_ request: AnalysisRequest) async throws -> NativeEngineResult { try await reporting { try await chess.analyze(request) } }
    func speech(fen: String, move: String) async throws -> String { try await reporting { try await chess.speechForLegalMove(fen: fen, moveUCI: move) } }
    func cancel() { chess.cancel() }
    func close() { closureHandler = nil; chess.cancel(); runtime.close() }
    func observeClosure(_ handler: @escaping @MainActor () -> Void) { closureHandler = handler }
    /// Replay tracker requests travel through the same single-pending runtime as engine commands.
    func makeTrackerTransport() -> any ReplayTrackerTransport { ReplayTrackerRuntimeTransport(runtime: runtime) }
    // Reached from runtime.onClose (immediate notice) and, as a fallback, when a request fails
    // and the runtime reports it is no longer ready. The handler fires at most once.
    private func runtimeStopped() { guard started, !runtime.isReady, let handler = closureHandler else { return }; closureHandler = nil; handler() }
    private func reporting<T>(_ body: () async throws -> T) async throws -> T {
        do { return try await body() } catch { runtimeStopped(); throw error }
    }
}

#if os(iOS)
import AVFoundation

/// Offline study output only. No live permit is manufactured, audio route changed,
/// or hardware audibility inferred. The app explicitly calls speak after review.
@MainActor final class OfflineNativeSpeech: OfflineSpeech {
    private var synthesizer: AVSpeechSynthesizer?
    func cancel() { synthesizer?.stopSpeaking(at: .immediate) }
    func speak(_ text: String) throws {
        cancel()
        guard !text.isEmpty, text.utf8.count <= 512,
              let voice = AVSpeechSynthesisVoice.speechVoices().first(where: { $0.language.hasPrefix("en") }) else { throw OfflineStudyError.unavailableVoice }
        let output = synthesizer ?? AVSpeechSynthesizer(); synthesizer = output
        let utterance = AVSpeechUtterance(string: text); utterance.voice = voice; output.speak(utterance)
    }
}
#endif
