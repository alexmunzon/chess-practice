// Standalone mocked lifecycle checks. Never constructs WebKit or audio output.
import Foundation

private let startingFEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
private let fixtureBytes = Data("offline-controller-mock-pixels".utf8)
private func fixtureBoard(unknown: Bool = false) -> OfflineBoard {
    let rows = ["rnbqkbnr", "pppppppp", "........", "........", "........", "........", "PPPPPPPP", "RNBQKBNR"]
    var squares: [String:String] = [:]
    for (row, pieces) in rows.enumerated() { for (column, piece) in pieces.enumerated() {
        squares["\(Array("abcdefgh")[column])\(8-row)"] = piece == "." ? "empty" : String(piece)
    } }
    if unknown { squares["a8"] = "unknown" }
    return OfflineBoard(sha256: NativeSyntheticRecognizer.sha256(fixtureBytes), squares: squares)
}
private actor MockPixels: OfflineImageRecognizer {
    var value = fixtureBoard()
    var hold = false
    var pending: CheckedContinuation<OfflineBoard, Error>?
    func configure(unknown: Bool = false, hold: Bool = false, foreignHash: Bool = false) {
        let board = fixtureBoard(unknown: unknown)
        value = foreignHash ? OfflineBoard(sha256: NativeSyntheticRecognizer.sha256(Data("other-pixels".utf8)), squares: board.squares) : board
        self.hold = hold
    }
    func recognize(_ bytes: Data) async throws -> OfflineBoard {
        if hold { return try await withCheckedThrowingContinuation { pending = $0 } }
        return value
    }
    func waiting() -> Bool { pending != nil }
    func resume() { let continuation = pending; pending = nil; continuation?.resume(returning: value) }
}
@MainActor private final class MockSpeech: OfflineSpeech {
    var queued: [String] = []
    var cancels = 0
    func speak(_ text: String) { queued.append(text) }
    func cancel() { cancels += 1; queued = [] }
}
@MainActor private final class MockBackend: OfflineBackend {
    var starts = 0, validations = 0, analyses = 0, cancellations = 0, closes = 0
    var analysisReturns = 0, speechChecks = 0
    var holdStart = false, holdValidation = false, holdAnalysis = false, holdSpeech = false, foreignFEN = false, foreignRequest = false
    var terminal = false, foreignFrame = false, foreignRevision = false
    var speaking: CheckedContinuation<String, Error>?
    var closureHandler: (@MainActor () -> Void)?
    func observeClosure(_ handler: @escaping @MainActor () -> Void) { closureHandler = handler }
    /// Simulates WebKit process death: the runtime stops by itself and reports it.
    func die() { closureHandler?() }
    var starting: CheckedContinuation<Void, Error>?
    var validating: CheckedContinuation<ValidatedPosition, Error>?
    var analyzing: CheckedContinuation<NativeEngineResult, Error>?
    var request: AnalysisRequest?
    func start() async throws { starts += 1; if holdStart { try await withCheckedThrowingContinuation { starting = $0 } } }
    func validate(_ fen: String) async throws -> ValidatedPosition {
        validations += 1
        if holdValidation { noteHold(); return try await withCheckedThrowingContinuation { validating = $0 } }
        return ValidatedPosition(fen: foreignFEN ? fen.replacingOccurrences(of: " w ", with: " b ") : fen, terminal: terminal)
    }
    func analyze(_ request: AnalysisRequest) async throws -> NativeEngineResult {
        analyses += 1; self.request = request
        defer { analysisReturns += 1 }
        if holdAnalysis { noteHold(); return try await withCheckedThrowingContinuation { analyzing = $0 } }
        return reply()
    }
    func reply() -> NativeEngineResult {
        let input = request!
        let frame = foreignFrame ? FrameIdentity(sessionID: UUID(), epoch: input.frame.epoch, sequence: input.frame.sequence, sha256: input.frame.sha256) : input.frame
        let bound = AnalysisRequest(id: foreignRequest ? UUID() : input.id, frame: frame,
                                    revision: foreignRevision ? input.revision + 1 : input.revision, fen: input.fen, movetimeMilliseconds: input.movetimeMilliseconds)
        return NativeEngineResult(request: bound, moveUCI: "e2e4")
    }
    func speech(fen: String, move: String) async throws -> String {
        speechChecks += 1
        if holdSpeech { noteHold(); return try await withCheckedThrowingContinuation { speaking = $0 } }
        return "pawn from e2 to e4."
    }
    func cancel() { cancellations += 1; cancelledSinceHold = true }
    func close() { closes += 1; calls.append("close") }
    // Pre-started engine stand-in (2026-11-16). A prewarm can be held; releasing it may "leak" a
    // warm-up result into a held analysis (a reply bound to another position), as a worst case.
    var prewarms = 0, prewarmCancels = 0, prewarmCallsWhileLive = 0
    var holdPrewarm = false, prewarmFails = false
    var heldPrewarms: [CheckedContinuation<Void, Error>] = []
    var calls: [String] = []
    /// A held validation/analysis/text request that the model has not cancelled since it started.
    private var cancelledSinceHold = true
    var live: Bool { (validating != nil || analyzing != nil || speaking != nil) && !cancelledSinceHold }
    func noteHold() { cancelledSinceHold = false }
    func prewarm() async throws {
        prewarms += 1; calls.append("prewarm"); if live { prewarmCallsWhileLive += 1 }
        if prewarmFails { throw OfflineStudyError.missingResource }
        if holdPrewarm { try await withCheckedThrowingContinuation { heldPrewarms.append($0) } }
    }
    func cancelPrewarm() async throws {
        prewarmCancels += 1; calls.append("cancelPrewarm"); if live { prewarmCallsWhileLive += 1 }
        if prewarmFails { throw OfflineStudyError.missingResource }
    }
    /// Completes every held prewarm. With `leak`, the held analysis is answered with a warm-up result:
    /// same request ID, but bound to another position (the warm-up FEN).
    func releasePrewarms(leak: Bool = false) {
        let held = heldPrewarms; heldPrewarms = []
        for continuation in held { continuation.resume() }
        if leak, let input = request, let pending = analyzing {
            analyzing = nil
            let warmup = AnalysisRequest(id: input.id, frame: input.frame, revision: input.revision,
                                         fen: "r1bq1rk1/pp3ppp/2np4/4N3/1PBQ4/P1P2RK1/8/8 w - - 0 1", movetimeMilliseconds: input.movetimeMilliseconds)
            pending.resume(returning: NativeEngineResult(request: warmup, moveUCI: "e2e4"))
        }
    }
}
@MainActor private struct Rig {
    let backend = MockBackend(), pixels = MockPixels(), speech = MockSpeech()
    let model: OfflineStudyModel
    init() {
        let backend = backend, pixels = pixels, speech = speech
        model = OfflineStudyModel(makeBackend: { backend }, recognizer: pixels, loadFixture: { _ in fixtureBytes }, speech: speech)
    }
    func prepared() async throws {
        model.start(); try await idle(model)
        model.recognizeFixture(); try await idle(model)
        model.editFEN(startingFEN)
        for field in ReviewField.allCases { model.setReview(field, checked: true) }
    }
    func reviewed() async throws { try await prepared(); model.validate(); try await idle(model) }
}
private struct CheckFailed: Error { let message: String }
private func check(_ value: @autoclosure () -> Bool, _ message: String) throws { if !value() { throw CheckFailed(message: message) } }
@MainActor private func idle(_ model: OfflineStudyModel) async throws {
    for _ in 0..<1000 { if !model.busy { return }; await Task.yield() }
    throw CheckFailed(message: "Controller did not finish bounded mock operation")
}
/// Everything a person can see or act on. A late reply must leave all of it unchanged.
@MainActor private struct Snapshot: Equatable {
    let status: String, ready: Bool, busy: Bool, fixture: StudyFixture, boardHash: String?, squares: [String: String]?
    let image: Data?, fen: String, checks: Set<ReviewField>, reviewed: Bool, recommendation: String?, move: String?
    let canValidate: Bool, canAnalyze: Bool, canSpeak: Bool
    init(_ m: OfflineStudyModel) {
        status = m.status; ready = m.ready; busy = m.busy; fixture = m.fixture; boardHash = m.board?.sha256; squares = m.board?.squares
        image = m.imageBytes; fen = m.fen; checks = m.checks; reviewed = m.reviewed; recommendation = m.recommendation; move = m.move
        canValidate = m.canValidate; canAnalyze = m.canAnalyze; canSpeak = m.canSpeak
    }
}
@MainActor private func settle() async { for _ in 0..<50 { await Task.yield() } }
/// Takes a snapshot after the revoking event, releases the held reply, and requires no visible change.
@MainActor private func frozen(_ model: OfflineStudyModel, _ message: String, release: () async throws -> Void) async throws {
    let before = Snapshot(model)
    try await release(); await settle()
    try check(Snapshot(model) == before, "\(message): visible state changed after the late reply")
    try check(model.recommendation == nil && model.move == nil && !model.canSpeak && !model.busy, "\(message): late reply produced output")
}
@MainActor private func waitForPixels(_ pixels: MockPixels) async throws {
    for _ in 0..<1000 { if await pixels.waiting() { return }; await Task.yield() }
    throw CheckFailed(message: "Recognizer continuation was not reached")
}
@MainActor private func until(_ condition: () -> Bool) async throws {
    for _ in 0..<1000 { if condition() { return }; await Task.yield() }
    throw CheckFailed(message: "Mock continuation was not reached")
}

@main private struct OfflineStudyChecks {
    @MainActor static func main() async {
        do {
            var passed = 0
            let first = Rig()
            try check(first.backend.starts == 0 && first.speech.queued.isEmpty && !first.model.ready, "Construction must be dormant")
            try await first.reviewed(); try check(first.model.reviewed && first.model.canAnalyze, "Explicit review should validate")
            first.model.analyze(); try await idle(first.model); first.model.speak()
            try check(first.speech.queued == ["pawn from e2 to e4."], "Only explicit speech action should queue")
            first.model.editFEN(startingFEN.replacingOccurrences(of: " w ", with: " b "))
            try check(first.speech.queued.isEmpty && first.model.recommendation == nil && first.model.checks.isEmpty, "FEN edit must revoke speech and review")
            passed += 1

            let mismatch = Rig(); try await mismatch.prepared()
            mismatch.model.editFEN("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1")
            for field in ReviewField.allCases { mismatch.model.setReview(field, checked: true) }
            mismatch.model.validate(); try check(mismatch.backend.validations == 0 && !mismatch.model.reviewed, "Mismatched pixels must block rules/engine")
            passed += 1

            let uncertain = Rig(); await uncertain.pixels.configure(unknown: true); try await uncertain.prepared()
            uncertain.model.validate(); uncertain.model.analyze()
            try check(!uncertain.model.canValidate && uncertain.backend.validations == 0 && uncertain.backend.analyses == 0, "Unknown pixels block output")
            passed += 1

            let latePixels = Rig(); latePixels.model.start(); try await idle(latePixels.model); await latePixels.pixels.configure(hold: true)
            latePixels.model.recognizeFixture()
            for _ in 0..<1000 { if await latePixels.pixels.waiting() { break }; await Task.yield() }
            let recognitionIsPending = await latePixels.pixels.waiting()
            try check(recognitionIsPending, "Late-recognition test must reach its suspended recognizer")
            latePixels.model.reset(); await latePixels.pixels.resume(); for _ in 0..<20 { await Task.yield() }
            try check(latePixels.model.board == nil && !latePixels.model.busy, "Late recognition cannot repopulate reset state")
            passed += 1

            let lateValidation = Rig(); try await lateValidation.prepared(); lateValidation.backend.holdValidation = true
            lateValidation.model.validate(); try await until { lateValidation.backend.validating != nil }
            lateValidation.model.setReview(.turn, checked: false)
            lateValidation.backend.validating?.resume(returning: ValidatedPosition(fen: startingFEN, terminal: false)); lateValidation.backend.validating = nil
            for _ in 0..<20 { await Task.yield() }
            try check(!lateValidation.model.reviewed && !lateValidation.model.canAnalyze, "Late validation cannot restore review")
            passed += 1

            let lateAnalysis = Rig(); try await lateAnalysis.reviewed(); lateAnalysis.backend.holdAnalysis = true
            lateAnalysis.model.analyze(); try await until { lateAnalysis.backend.analyzing != nil }
            lateAnalysis.model.setActive(false)
            lateAnalysis.backend.analyzing?.resume(returning: lateAnalysis.backend.reply()); lateAnalysis.backend.analyzing = nil
            for _ in 0..<20 { await Task.yield() }
            try check(lateAnalysis.model.recommendation == nil && !lateAnalysis.model.canSpeak && !lateAnalysis.model.ready, "Background must reject late analysis")
            passed += 1

            let switched = Rig(); try await switched.reviewed()
            switched.model.analyze(); try await idle(switched.model); switched.model.speak()
            try check(switched.model.canSpeak && !switched.speech.queued.isEmpty, "The first position should have output")
            switched.model.selectFixture(.afterE4)
            try check(switched.model.fixture == .afterE4 && switched.model.ready && switched.model.board == nil &&
                      switched.model.imageBytes == nil && switched.model.fen.isEmpty && switched.model.checks.isEmpty &&
                      !switched.model.reviewed && !switched.model.canAnalyze && !switched.model.canSpeak &&
                      switched.model.recommendation == nil && switched.speech.queued.isEmpty,
                      "Switching positions must discard the previous board, review and output")
            passed += 1

            let switchingAnalysis = Rig(); try await switchingAnalysis.reviewed()
            switchingAnalysis.backend.holdAnalysis = true
            switchingAnalysis.model.analyze(); try await until { switchingAnalysis.backend.analyzing != nil }
            switchingAnalysis.model.selectFixture(.enPassant)
            switchingAnalysis.model.recognizeFixture(); try await idle(switchingAnalysis.model)
            switchingAnalysis.backend.analyzing?.resume(returning: switchingAnalysis.backend.reply())
            switchingAnalysis.backend.analyzing = nil
            try await until { switchingAnalysis.backend.analysisReturns == 1 }
            try check(switchingAnalysis.model.fixture == .enPassant && switchingAnalysis.model.imageBytes == fixtureBytes &&
                      switchingAnalysis.model.fen.isEmpty && switchingAnalysis.model.checks.isEmpty &&
                      !switchingAnalysis.model.reviewed && !switchingAnalysis.model.canSpeak &&
                      switchingAnalysis.model.recommendation == nil && switchingAnalysis.backend.speechChecks == 0,
                      "A held analysis reply must not restore output or enter legal text after switching positions")
            passed += 1

            let bad = Rig(); try await bad.prepared(); bad.backend.foreignFEN = true; bad.model.validate(); try await idle(bad.model)
            try check(!bad.model.reviewed && !bad.model.busy, "Foreign FEN must finish with no review")
            bad.backend.foreignFEN = false; bad.model.validate(); try await idle(bad.model); bad.backend.foreignRequest = true
            bad.model.analyze(); try await idle(bad.model)
            try check(bad.model.recommendation == nil && !bad.model.busy, "Foreign analysis identity must finish with no recommendation")
            passed += 1

            let old = MockBackend(), replacement = MockBackend(), pixels = MockPixels(), speech = MockSpeech()
            old.holdStart = true; var factories = 0
            let model = OfflineStudyModel(makeBackend: { factories += 1; return factories == 1 ? old : replacement }, recognizer: pixels, loadFixture: { _ in fixtureBytes }, speech: speech)
            model.start(); try await until { old.starting != nil }; model.start(); try await idle(model)
            old.starting?.resume(); old.starting = nil; for _ in 0..<20 { await Task.yield() }
            try check(model.ready && replacement.closes == 0 && old.closes == 1, "Old start completion must not close replacement runtime")
            model.reset(); try check(!model.ready && replacement.closes == 1, "Reset closes owned runtime")
            passed += 1
            passed += try await newChecks()
            passed += try await prewarmChecks()
            print("Offline study mock lifecycle checks: \(passed)/\(passed) passed; no WebKit, recognition inference, device or audio execution.")
        } catch { print("FAILED: \(error)"); exit(1) }
    }
}

private let blackToMoveFEN = startingFEN.replacingOccurrences(of: " w ", with: " b ")

/// Held-reply and safety checks added 2026-11-15. Each returns only after its assertions pass.
@MainActor private func newChecks() async throws -> Int {
    var passed = 0
    // 1-3: a held analysis reply released after a revoking event changes nothing visible.
    let revokers: [(String, @MainActor (OfflineStudyModel) -> Void)] = [
        ("FEN edit", { $0.editFEN(blackToMoveFEN) }),
        ("review untick", { $0.setReview(.castling, checked: false) }),
        ("reset", { $0.reset() }),
    ]
    for (name, revoke) in revokers {
        let rig = Rig(); try await rig.reviewed(); rig.backend.holdAnalysis = true
        rig.model.analyze(); try await until { rig.backend.analyzing != nil }
        revoke(rig.model)
        try await frozen(rig.model, "Late analysis after \(name)") {
            rig.backend.analyzing?.resume(returning: rig.backend.reply()); rig.backend.analyzing = nil
        }
        try check(rig.backend.speechChecks == 0 && rig.speech.queued.isEmpty, "Late analysis after \(name) must not request legal text or speech")
        passed += 1
    }

    // 4: a held legal-text/speech-text reply released after a revoking event.
    let lateText = Rig(); try await lateText.reviewed(); lateText.backend.holdSpeech = true
    lateText.model.analyze(); try await until { lateText.backend.speaking != nil }
    lateText.model.setReview(.pieces, checked: false)
    try await frozen(lateText.model, "Late legal text after review untick") {
        lateText.backend.speaking?.resume(returning: "pawn from e2 to e4."); lateText.backend.speaking = nil
    }
    lateText.model.speak()
    try check(lateText.speech.queued.isEmpty, "Late legal text must not become speakable")
    passed += 1

    // 5-8: a held validation reply released after FEN edit, reset, background, fixture switch.
    let validationRevokers: [(String, @MainActor (OfflineStudyModel) -> Void)] = [
        ("FEN edit", { $0.editFEN(blackToMoveFEN) }),
        ("reset", { $0.reset() }),
        ("background and return", { $0.setActive(false); $0.setActive(true) }),
        ("fixture switch", { $0.selectFixture(.afterE4) }),
    ]
    for (name, revoke) in validationRevokers {
        let rig = Rig(); try await rig.prepared(); rig.backend.holdValidation = true
        rig.model.validate(); try await until { rig.backend.validating != nil }
        revoke(rig.model)
        try await frozen(rig.model, "Late validation after \(name)") {
            rig.backend.validating?.resume(returning: ValidatedPosition(fen: startingFEN, terminal: false)); rig.backend.validating = nil
        }
        try check(!rig.model.reviewed && !rig.model.canAnalyze, "Late validation after \(name) must not restore review")
        passed += 1
    }

    // 9-10: a held recognition reply released after background or fixture switch.
    let recognitionRevokers: [(String, @MainActor (OfflineStudyModel) -> Void)] = [
        ("background and return", { $0.setActive(false); $0.setActive(true) }),
        ("fixture switch", { $0.selectFixture(.promotion) }),
    ]
    for (name, revoke) in recognitionRevokers {
        let rig = Rig(); rig.model.start(); try await idle(rig.model); await rig.pixels.configure(hold: true)
        rig.model.recognizeFixture(); try await waitForPixels(rig.pixels)
        revoke(rig.model)
        try await frozen(rig.model, "Late recognition after \(name)") { await rig.pixels.resume() }
        try check(rig.model.board == nil && rig.model.imageBytes == nil, "Late recognition after \(name) must not show a board")
        passed += 1
    }

    // 11: an engine start that completes after backgrounding leaves the model not ready.
    let lateStart = Rig(); lateStart.backend.holdStart = true
    lateStart.model.start(); try await until { lateStart.backend.starting != nil }
    lateStart.model.setActive(false); lateStart.model.setActive(true)
    try await frozen(lateStart.model, "Late engine start after background") {
        lateStart.backend.starting?.resume(); lateStart.backend.starting = nil
    }
    try check(!lateStart.model.ready && lateStart.backend.closes == 1, "Late start must close the runtime and stay not ready")
    passed += 1

    // 12: a terminal position blocks analysis.
    let terminal = Rig(); try await terminal.prepared(); terminal.backend.terminal = true
    terminal.model.validate(); try await idle(terminal.model)
    terminal.model.analyze(); try await idle(terminal.model)
    try check(terminal.model.reviewed && !terminal.model.canAnalyze && terminal.backend.analyses == 0 &&
              terminal.model.recommendation == nil && terminal.model.status.contains("terminal"), "Terminal position must block analysis")
    passed += 1

    // 13: a recognition result whose image hash does not match is rejected.
    let foreignHash = Rig(); foreignHash.model.start(); try await idle(foreignHash.model)
    await foreignHash.pixels.configure(foreignHash: true)
    foreignHash.model.recognizeFixture(); try await idle(foreignHash.model)
    try check(foreignHash.model.board == nil && foreignHash.model.imageBytes == nil &&
              foreignHash.model.status.hasPrefix("Recognition failed"), "Mismatched image hash must be rejected")
    passed += 1

    // 14: an analysis reply with the right request ID but wrong frame or revision is rejected.
    for wrongFrame in [true, false] {
        let rig = Rig(); try await rig.reviewed()
        rig.backend.foreignFrame = wrongFrame; rig.backend.foreignRevision = !wrongFrame
        rig.model.analyze(); try await idle(rig.model)
        try check(rig.backend.request != nil && rig.backend.reply().request.id == rig.backend.request!.id, "Mock must keep the request ID")
        try check(rig.model.recommendation == nil && rig.model.move == nil && rig.backend.speechChecks == 0 &&
                  rig.model.status.hasPrefix("Analysis failed"), "Reply with the right ID but wrong \(wrongFrame ? "frame" : "revision") must be rejected")
    }
    passed += 1

    // 15: speech is cancelled on background after something was spoken.
    let spoken = Rig(); try await spoken.reviewed(); spoken.model.analyze(); try await idle(spoken.model); spoken.model.speak()
    try check(spoken.speech.queued == ["pawn from e2 to e4."], "Speech should be queued before backgrounding")
    let cancelsBefore = spoken.speech.cancels
    spoken.model.setActive(false)
    try check(spoken.speech.cancels > cancelsBefore && spoken.speech.queued.isEmpty && spoken.model.recommendation == nil,
              "Backgrounding must cancel speech that was already spoken")
    passed += 1

    // A: the runtime stopping by itself makes the model stop showing the engine as ready.
    let died = Rig(); try await died.reviewed(); died.model.analyze(); try await idle(died.model)
    try check(died.model.ready && died.model.recommendation != nil, "Engine should be ready with output before it dies")
    died.backend.die()
    try check(!died.model.ready && !died.model.reviewed && died.model.recommendation == nil && !died.model.canAnalyze &&
              !died.model.canSpeak && !died.model.canValidate && died.backend.closes == 1 && died.model.status.contains("stopped"),
              "Runtime death must revoke readiness, review and output")
    died.model.start(); try await idle(died.model)
    try check(died.model.ready, "Engine can be started again after it stopped")
    died.model.reset()
    try await frozen(died.model, "Closure signal after our own reset") { died.backend.die() }
    try check(!died.model.ready && died.model.status.hasPrefix("Offline study reset"), "Our own close must not be reported as a crash")
    passed += 1

    // A (held): runtime death while analysis is held; the late reply cannot restore output.
    let diedHeld = Rig(); try await diedHeld.reviewed(); diedHeld.backend.holdAnalysis = true
    diedHeld.model.analyze(); try await until { diedHeld.backend.analyzing != nil }
    diedHeld.backend.die()
    try await frozen(diedHeld.model, "Late analysis after runtime death") {
        diedHeld.backend.analyzing?.resume(returning: diedHeld.backend.reply()); diedHeld.backend.analyzing = nil
    }
    try check(!diedHeld.model.ready, "Runtime death during analysis leaves the engine not ready")
    passed += 1

    // B: five separate, truthful confirmations that start unticked; loading the sample clears ticks.
    let titles = ReviewField.allCases.map(\.title)
    try check(titles.count == 5 && Set(titles).count == 5 && titles.allSatisfy { $0.hasPrefix("I checked and confirm") } &&
              !titles.contains { $0.contains("supplied") }, "Review wording must be five distinct checked-and-confirm statements")
    let sample = Rig(); sample.model.start(); try await idle(sample.model)
    sample.model.recognizeFixture(); try await idle(sample.model)
    try check(sample.model.checks.isEmpty && sample.model.fen.isEmpty, "Review boxes start unticked")
    for field in ReviewField.allCases { sample.model.setReview(field, checked: true) }
    try check(sample.model.checks.count == 5, "Each box ticks separately")
    sample.model.editFEN(StudyFixture.starting.referenceFEN!) // "Use sample FEN"
    try check(sample.model.checks.isEmpty && sample.model.fen == startingFEN && !sample.model.canValidate,
              "Loading the sample FEN must clear existing ticks")
    passed += 1
    return passed
}

/// Pre-started engine cases added 2026-11-16 (held-back stand-in replies). Each returns only after its assertions pass.
@MainActor private func prewarmChecks() async throws -> Int {
    var passed = 0, whileLive = 0
    // P1: a prewarm is requested when the review screen opens (complete board, engine ready), when the
    // review becomes complete and after validation; never before the engine runs or for an uncertain board.
    do {
        let rig = Rig()
        rig.model.start(); try await idle(rig.model); await settle()
        try check(rig.backend.prewarms == 0, "P1: no prewarm before a board is read")
        rig.model.recognizeFixture(); try await idle(rig.model); await settle()
        try check(rig.backend.prewarms == 1, "P1: prewarm when the review screen opens")
        rig.model.editFEN(startingFEN)
        for field in ReviewField.allCases { rig.model.setReview(field, checked: true) }
        await settle()
        try check(rig.backend.prewarms == 2, "P1: prewarm again when all five boxes are ticked")
        rig.model.validate(); try await idle(rig.model); await settle()
        try check(rig.backend.prewarms == 3 && rig.model.reviewed, "P1: prewarm after a successful validation")
        let uncertain = Rig(); await uncertain.pixels.configure(unknown: true)
        for field in ReviewField.allCases { uncertain.model.setReview(field, checked: true) }
        uncertain.model.start(); try await idle(uncertain.model)
        uncertain.model.recognizeFixture(); try await idle(uncertain.model)
        uncertain.model.editFEN(startingFEN)
        for field in ReviewField.allCases { uncertain.model.setReview(field, checked: true) }
        await settle()
        try check(uncertain.backend.prewarms == 0, "P1: no prewarm for an uncertain board or before the engine runs")
        whileLive += rig.backend.prewarmCallsWhileLive + uncertain.backend.prewarmCallsWhileLive
        passed += 1
    }
    // P2: a prewarm still in flight when the user confirms and analyzes. Releasing it changes nothing;
    // advice comes only from the analysis of the confirmed position. A warm-up result leaking into the
    // analysis channel (bound to the warm-up position) is rejected: no recommendation, no legal-text request.
    do {
        let rig = Rig(); rig.backend.holdPrewarm = true
        try await rig.reviewed(); await settle()
        try check(!rig.backend.heldPrewarms.isEmpty, "P2: a prewarm is in flight at confirmation")
        rig.backend.holdAnalysis = true
        rig.model.analyze(); try await until { rig.backend.analyzing != nil }
        let before = Snapshot(rig.model)
        rig.backend.releasePrewarms(); await settle()
        try check(Snapshot(rig.model) == before && rig.model.recommendation == nil, "P2: a prewarm completing changes nothing visible")
        rig.backend.analyzing?.resume(returning: rig.backend.reply()); rig.backend.analyzing = nil
        try await idle(rig.model)
        try check(rig.model.recommendation == "pawn from e2 to e4." && rig.backend.request?.fen == startingFEN && rig.model.reviewed,
                  "P2: advice for the confirmed position only")

        let leak = Rig(); leak.backend.holdPrewarm = true
        try await leak.reviewed(); await settle()
        leak.backend.holdAnalysis = true
        leak.model.analyze(); try await until { leak.backend.analyzing != nil }
        leak.backend.releasePrewarms(leak: true); try await idle(leak.model); await settle()
        try check(leak.model.recommendation == nil && leak.model.move == nil && !leak.model.canSpeak && leak.backend.speechChecks == 0 &&
                  leak.model.status.hasPrefix("Analysis failed"), "P2: a warm-up result is never shown as a recommendation")
        whileLive += rig.backend.prewarmCallsWhileLive + leak.backend.prewarmCallsWhileLive
        passed += 1
    }
    // P3: un-ticking the review, switching position, reset and backgrounding each cancel the prewarm
    // (reset and background also close the runtime) and a held analysis reply released later shows nothing.
    let leavers: [(String, Bool, @MainActor (OfflineStudyModel) -> Void)] = [
        ("review untick", false, { $0.setReview(.turn, checked: false) }),
        ("position switch", false, { $0.selectFixture(.afterE4) }),
        ("reset", true, { $0.reset() }),
        ("background", true, { $0.setActive(false) }),
    ]
    for (name, closes, leave) in leavers {
        let rig = Rig(); rig.backend.holdPrewarm = true
        try await rig.reviewed(); await settle()
        rig.backend.holdAnalysis = true
        rig.model.analyze(); try await until { rig.backend.analyzing != nil }
        let cancelsBefore = rig.backend.prewarmCancels
        leave(rig.model); await settle()
        try check(rig.backend.prewarmCancels == cancelsBefore + 1, "P3: \(name) must cancel the prewarm")
        try check(rig.backend.closes == (closes ? 1 : 0), "P3: \(name) closes the runtime only for reset/background")
        try await frozen(rig.model, "P3: late replies after \(name)") {
            rig.backend.releasePrewarms()
            rig.backend.analyzing?.resume(returning: rig.backend.reply()); rig.backend.analyzing = nil
        }
        try check(rig.backend.speechChecks == 0 && rig.model.recommendation == nil, "P3: nothing shown after \(name)")
        whileLive += rig.backend.prewarmCallsWhileLive
    }
    passed += 1
    // P4: a failing prewarm is invisible: the same flow shows exactly what it shows without any prewarm failure.
    do {
        let failing = Rig(), normal = Rig(); failing.backend.prewarmFails = true
        for rig in [failing, normal] {
            try await rig.reviewed(); await settle(); rig.model.analyze(); try await idle(rig.model); await settle()
        }
        try check(failing.backend.prewarms > 0 && Snapshot(failing.model) == Snapshot(normal.model) &&
                  failing.model.recommendation == "pawn from e2 to e4.", "P4: prewarm failure falls back to normal analysis, invisibly")
        failing.model.setReview(.pieces, checked: false); normal.model.setReview(.pieces, checked: false); await settle()
        try check(Snapshot(failing.model) == Snapshot(normal.model), "P4: a failing cancel is invisible too")
        passed += 1
    }
    // P5: the model asks for (or cancels) a spare only when none of its own requests is live, so a
    // prewarm can never cancel the user's analysis (the runtime runs one request at a time) and never
    // makes a second engine run beside an analysis.
    do {
        let rig = Rig(); try await rig.reviewed(); await settle()
        rig.backend.holdAnalysis = true
        rig.model.analyze(); try await until { rig.backend.analyzing != nil }
        await settle()
        let duringAnalysis = rig.backend.prewarmCallsWhileLive
        rig.backend.analyzing?.resume(returning: rig.backend.reply()); rig.backend.analyzing = nil; try await idle(rig.model)
        rig.backend.holdValidation = true
        rig.model.setReview(.turn, checked: false); rig.model.setReview(.turn, checked: true)
        rig.model.validate(); try await until { rig.backend.validating != nil }; await settle()
        rig.backend.validating?.resume(returning: ValidatedPosition(fen: startingFEN, terminal: false)); rig.backend.validating = nil
        try await idle(rig.model); await settle()
        whileLive += rig.backend.prewarmCallsWhileLive
        try check(duringAnalysis == 0 && whileLive == 0, "P5: \(whileLive) prewarm requests were sent while a request was live")
        passed += 1
    }
    return passed
}
