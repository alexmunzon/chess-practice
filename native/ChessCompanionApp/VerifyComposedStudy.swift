// Compile-only preparation is not permission to execute this Mac WebKit harness.
#if os(macOS)
import AppKit
import CryptoKit
import Foundation

private let fixtureHash = "ed30d4974c39e73d64c5450a1bc1ea66359e7241e28cc5f88d6bd0299207926a"
private let challengeHash = "c02544067d3aba32b660e1093df77b0c7eac6076984c003bd2454f8c0c192f2b"
private let manifestHash = "f6584f4e1b001e2f9f76e3e505c122cb72a371f515216711a6390449bf9e2563"
private let runtimeHash = "471e56746249cb421a59c2466d2febf2ff1791af16b6391efb79aafb44fc47d5"
private let startingFEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
private let mismatchFEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
// Independently expanded reference rows from the frozen corpus truth for 000000.
// This is checked after recognition and never passed to the recognizer.
private let reviewedRows = ["rnbqkbnr", "pppppppp", "........", "........",
                            "........", "........", "PPPPPPPP", "RNBQKBNR"]

private struct CheckFailure: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}
private func check(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    if !condition() { throw CheckFailure(message: message) }
}
private func pinned(_ path: URL, _ hash: String, maximum: Int) throws -> Data {
    let metadata = try path.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
    try check(metadata.isRegularFile == true && metadata.isSymbolicLink == false &&
              (1...maximum).contains(metadata.fileSize ?? 0), "Invalid bounded input: \(path.lastPathComponent)")
    let bytes = try Data(contentsOf: path)
    try check(bytes.count == metadata.fileSize && NativeSyntheticRecognizer.sha256(bytes) == hash,
              "Unexpected input hash: \(path.lastPathComponent)")
    return bytes
}

@MainActor private final class TextSink: OfflineSpeech {
    var calls: [String] = []
    var pending: String?
    let diagnostics: ComposedStudyDiagnostics
    init(_ diagnostics: ComposedStudyDiagnostics) { self.diagnostics = diagnostics }
    func speak(_ text: String) { calls.append(text); pending = text; diagnostics.textCalled() }
    func cancel() { pending = nil; diagnostics.textCancelled() }
}

@MainActor private final class FixtureInput {
    var useChallenge = true
    let resources: StudyResources
    let occluded: Data
    init(resources: StudyResources, occluded: Data) {
        self.resources = resources; self.occluded = occluded
    }
    func read() throws -> Data {
        if useChallenge { return occluded }
        return try resources.checked("synthetic-fixture.png")
    }
}

/// All answers come from the app backend. The final case holds one already
/// rules-checked reply across a background transition, ignoring cancellation
/// at the injection boundary on purpose. It does not manufacture a move.
@MainActor private final class ObservedBackend: OfflineBackend {
    let backend: LocalOfflineBackend
    let diagnostics: ComposedStudyDiagnostics
    var validations = 0, analyses = 0, speechChecks = 0
    var lastRequest: AnalysisRequest?
    var lastError: String?
    var holdSpeech = false
    private var held: CheckedContinuation<Void, Never>?
    private(set) var deliveredLateReply = false
    private(set) var returnedText: String?
    var waiting: Bool { held != nil }
    init(_ resources: StudyResources, diagnostics: ComposedStudyDiagnostics) throws {
        backend = try LocalOfflineBackend(resources: resources); self.diagnostics = diagnostics
    }
    private func observe<T>(_ operation: ComposedStudyDiagnostics.Operation, _ body: () async throws -> T) async throws -> T {
        let token = diagnostics.began(operation)
        do { let result = try await body(); diagnostics.completed(token); return result }
        catch { lastError = error.localizedDescription; diagnostics.failed(token, error: error.localizedDescription); throw error }
    }
    func start() async throws { try await observe(.start) { try await backend.start() } }
    func validate(_ fen: String) async throws -> ValidatedPosition {
        validations += 1
        return try await observe(.validate) { try await backend.validate(fen) }
    }
    func analyze(_ request: AnalysisRequest) async throws -> NativeEngineResult {
        analyses += 1; lastRequest = request
        return try await observe(.analyze) { try await backend.analyze(request) }
    }
    func speech(fen: String, move: String) async throws -> String {
        speechChecks += 1
        let checked = try await observe(.legalText) { try await backend.speech(fen: fen, move: move) }
        if holdSpeech {
            await withCheckedContinuation { held = $0 }
            deliveredLateReply = true
        }
        returnedText = checked
        return checked
    }
    func release() { let continuation = held; held = nil; continuation?.resume() }
    func cancel() { backend.cancel() }
    func close() { backend.close() }
}

@MainActor private func wait(_ description: String, seconds: Int = 25, until: () -> Bool) async throws {
    let clock = ContinuousClock()
    let deadline = clock.now.advanced(by: .seconds(seconds))
    while !until() {
        if clock.now >= deadline { throw CheckFailure(message: "Timed out: \(description)") }
        try await Task.sleep(for: .milliseconds(10))
    }
}

@MainActor private func run(root: URL, challenge: URL, diagnostics: ComposedStudyDiagnostics) async throws -> [String: Any] {
    func checked(_ condition: @autoclosure () -> Bool, _ assertion: ComposedStudyDiagnostics.Assertion, _ message: String) throws {
        try check(condition(), message); diagnostics.passed(assertion)
    }
    diagnostics.enter(.inputs)
    _ = try pinned(root.appendingPathComponent("app-assets.json"), manifestHash, maximum: 16 * 1024)
    let resources = StudyResources(root: root)
    let runtime = try resources.checked("Runtime/runtime-manifest.json")
    try checked(NativeSyntheticRecognizer.sha256(runtime) == runtimeHash, .runtimeManifest, "Unexpected runtime manifest")
    let bytes = try resources.checked("synthetic-fixture.png")
    try checked(NativeSyntheticRecognizer.sha256(bytes) == fixtureHash, .positiveFixture, "Unexpected bundled positive fixture")
    let occluded = try pinned(challenge, challengeHash, maximum: 8 * 1024 * 1024)
    diagnostics.passed(.pinnedInputs)
    let sink = TextSink(diagnostics)
    var current: ObservedBackend?
    let input = FixtureInput(resources: resources, occluded: occluded)
    let model = OfflineStudyModel(makeBackend: {
        let observed = try ObservedBackend(resources, diagnostics: diagnostics); current = observed; return observed
    }, recognizer: OfflinePixelRecognizer(resources: resources), loadFixture: { _ in try input.read() }, speech: sink)
    defer { diagnostics.freezeBeforeCleanup(); model.reset(); current?.release() }
    func idle(_ phase: String, seconds: Int = 25) async throws {
        try await wait(phase, seconds: seconds) { !model.busy }
    }
    func start() async throws -> ObservedBackend {
        model.start(); try await idle("engine startup", seconds: 32)
        guard model.ready, let current else {
            throw CheckFailure(message: "Local start failed: \(current?.lastError ?? model.status)")
        }
        diagnostics.passed(.localReady)
        return current
    }
    func review(_ fen: String) {
        model.editFEN(fen)
        for field in ReviewField.allCases { model.setReview(field, checked: true) }
    }
    func validate() async throws {
        review(startingFEN); model.validate(); try await idle("complete position validation")
        try checked(model.reviewed && model.canAnalyze, .completeReview, "Explicit review did not validate: \(current?.lastError ?? model.status)")
    }
    func blocked(_ backend: ObservedBackend, _ phase: String, _ assertion: ComposedStudyDiagnostics.Assertion) async throws {
        model.analyze(); model.speak()
        try await idle(phase)
        try checked(!model.reviewed && !model.canAnalyze && !model.canSpeak &&
                  model.recommendation == nil && sink.calls.isEmpty &&
                  backend.validations == 0 && backend.analyses == 0 && backend.speechChecks == 0,
                  assertion, "\(phase) reached rules, engine, or output")
    }
    func analyzeAndEmit(_ backend: ObservedBackend, expectedCalls: Int) async throws -> (String, String) {
        model.analyze(); try await idle("Stockfish and separate legal move check")
        guard let move = model.move, move.utf8.count == 4, let text = model.recommendation,
              let request = backend.lastRequest else {
            throw CheckFailure(message: "Expected checked Stockfish output: \(backend.lastError ?? model.status)")
        }
        diagnostics.passed(.checkedOutputAvailable)
        try checked(request.fen == startingFEN && request.frame.sha256 == fixtureHash &&
                  request.frame.sequence == request.revision && request.movetimeMilliseconds == 1000,
                  .requestIdentity, "Stockfish request not bound to the reviewed image and FEN")
        let from = String(move.prefix(2)), to = String(move.suffix(2))
        let piece = ["P": "pawn", "N": "knight"][model.board?.squares[from] ?? ""]
        try checked(piece != nil && text == "\(piece ?? "") from \(from) to \(to)." && text == backend.returnedText,
                  .regeneratedText, "Regenerated rules text did not match the checked starting-position move")
        try checked(sink.calls.count == expectedCalls - 1 && sink.pending == nil, .noAutomaticOutput, "Unexpected automatic output")
        model.speak()
        try checked(sink.calls.count == expectedCalls && sink.pending == text, .explicitTextSink, "Explicit action did not reach text-only sink")
        return (move, text)
    }

    diagnostics.enter(.initialStart)
    let backend = try await start()
    diagnostics.enter(.occludedRecognition)
    model.recognizeFixture(); try await idle("occluded PNG recognition")
    guard let abstention = model.board else { throw CheckFailure(message: model.status) }
    let unknown = abstention.squares.filter { $0.value == "unknown" }.keys.sorted()
    try checked(abstention.sha256 == challengeHash && abstention.squares.count == 64 &&
              unknown.count == 16 && !abstention.complete, .unknownsPreserved, "Occluded fixture did not preserve the expected unknowns")
    diagnostics.enter(.unknownReview)
    review(startingFEN); model.validate(); try await blocked(backend, "unknown pieces", .unknownReviewBlocked)

    diagnostics.enter(.positiveRecognition)
    input.useChallenge = false
    model.recognizeFixture(); try await idle("bundled PNG recognition")
    guard let recognized = model.board else { throw CheckFailure(message: model.status) }
    let reference = Dictionary(uniqueKeysWithValues: reviewedRows.enumerated().flatMap { row, labels in
        zip("abcdefgh", labels).map { file, piece in ("\(file)\(8 - row)", piece == "." ? "empty" : String(piece)) }
    })
    try checked(model.imageBytes == bytes && recognized.sha256 == fixtureHash &&
              recognized.squares == reference && recognized.matchesPlacement(startingFEN),
              .exact64Cells, "Not all 64 pixel-derived labels match the independently expanded reference and supplied FEN")
    try checked(model.fen.isEmpty && model.checks.isEmpty, .noInferredReview, "Recognition supplied review state")
    diagnostics.enter(.incompleteReview)
    model.editFEN(startingFEN)
    for field in ReviewField.allCases where field != .counters { model.setReview(field, checked: true) }
    model.validate(); try await blocked(backend, "incomplete review", .incompleteReviewBlocked)
    diagnostics.enter(.mismatchedReview)
    review(mismatchFEN); model.validate(); try await blocked(backend, "mismatched pieces", .mismatchedReviewBlocked)

    diagnostics.enter(.firstValidation)
    try await validate()
    diagnostics.enter(.firstAnalysis)
    let (move, spokenText) = try await analyzeAndEmit(backend, expectedCalls: 1)
    guard let request = backend.lastRequest else { throw CheckFailure(message: "Missing analysis request identity") }
    diagnostics.passed(.analysisRequestPresent)
    diagnostics.enter(.edit)
    model.editFEN(mismatchFEN)
    try checked(!model.reviewed && model.checks.isEmpty && model.recommendation == nil &&
              !model.canSpeak && sink.calls.count == 1 && sink.pending == nil, .editRevokedOutput, "Edit did not revoke output")
    model.speak()
    try checked(sink.calls.count == 1, .editBlockedOldText, "Edited position emitted old text")

    diagnostics.enter(.secondValidation)
    try await validate()
    diagnostics.enter(.secondAnalysis)
    _ = try await analyzeAndEmit(backend, expectedCalls: 2)
    diagnostics.enter(.reset)
    model.reset()
    try checked(!model.ready && !model.reviewed && model.board == nil && model.fen.isEmpty &&
              !model.canSpeak && model.recommendation == nil && sink.calls.count == 2 &&
              sink.pending == nil, .resetRevokedOutput, "Reset did not revoke output")
    model.speak()
    try checked(sink.calls.count == 2, .resetBlockedOldText, "Reset position emitted old text")

    diagnostics.enter(.restart)
    let afterReset = try await start()
    diagnostics.enter(.recognitionAfterReset)
    model.recognizeFixture(); try await idle("recognition after reset")
    diagnostics.enter(.thirdValidation)
    try await validate()
    diagnostics.enter(.lateAnalysis)
    afterReset.holdSpeech = true
    model.analyze()
    try await wait("arrival of real rules-checked reply", seconds: 22) { afterReset.waiting }
    try checked(model.busy && model.recommendation == nil && sink.pending == nil, .heldReplyUnpublished, "Text published before rules check returned")
    diagnostics.enter(.background)
    model.setActive(false); afterReset.release()
    try await wait("return of deliberately late reply") { afterReset.deliveredLateReply }
    model.speak()
    try checked(!model.ready && !model.busy && !model.reviewed && !model.canSpeak &&
              model.recommendation == nil && sink.calls.count == 2 && sink.pending == nil,
              .backgroundRevokedOutput, "Late reply restored output after backgrounding")

    diagnostics.enter(.complete)
    return [
        "checks": ["occluded-pixels", "incomplete-review", "mismatched-placement", "exact-64-cell-review",
                   "stockfish", "separate-legal-text", "explicit-text-sink", "edit", "reset", "late-reply-after-background"],
        "recognition": ["sha256": fixtureHash, "squares": recognized.squares, "matched": 64],
        "unknownChallenge": ["sha256": challengeHash, "unknownSquares": unknown],
        "appManifestSha256": manifestHash, "runtimeManifestSha256": runtimeHash,
        "review": ["source": "scripted known-new-game fixture; no live human interaction", "fen": request.fen,
                   "fields": ReviewField.allCases.map(\.rawValue), "repetitionHistoryAvailable": false],
        "analysis": ["moveUCI": move, "text": spokenText, "requestId": request.id.uuidString,
                     "sessionId": request.frame.sessionID.uuidString, "epoch": request.frame.epoch,
                     "sequence": request.frame.sequence, "revision": request.revision,
                     "frameSha256": request.frame.sha256, "requestedMilliseconds": request.movetimeMilliseconds],
        "lateTextReturned": afterReset.returnedText ?? "",
    ]
}

@main private struct VerifyComposedStudy {
    @MainActor static func main() {
        guard CommandLine.arguments.count == 3 else {
            print("Usage: VerifyComposedStudy APP_RESOURCE_DIRECTORY OCCLUDED_FIXTURE_PNG"); exit(2)
        }
        let root = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
        let challenge = URL(fileURLWithPath: CommandLine.arguments[2])
        let app = NSApplication.shared
        app.setActivationPolicy(.prohibited)
        let start = ProcessInfo.processInfo.systemUptime
        let diagnostics = ComposedStudyDiagnostics()
        func finish(_ success: Bool, _ result: [String: Any]) -> Never {
            var report = result
            report["passed"] = success
            report["mode"] = "macOS-composed-offline-synthetic-study"
            report["elapsedMs"] = (ProcessInfo.processInfo.systemUptime - start) * 1000
            report["iOSExecuted"] = false
            report["audibleSpeechExecuted"] = false
            report["diagnostics"] = diagnostics.snapshot()
            let data = try! JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
            print(String(decoding: data, as: UTF8.self)); exit(success ? 0 : 1)
        }
        Task { @MainActor in
            try? await Task.sleep(for: .seconds(90))
            finish(false, ["error": "Whole Mac harness exceeded 90 seconds."])
        }
        Task { @MainActor in
            do { finish(true, try await run(root: root, challenge: challenge, diagnostics: diagnostics)) }
            catch { finish(false, ["error": error.localizedDescription]) }
        }
        app.run()
    }
}
#endif
