// Standalone mocked checks for the Replay game model (ReplayGame.swift). The real ReplayTracker
// client talks to a mocked tracker transport that emulates the JS tracker contract; recognizer and
// engine backend are mocks with holdable replies. Never constructs WebKit, audio or speech output.
import Foundation

// MARK: - Fixture game (1.e4 e5 2.Nf3)

private let startFEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
private let e4FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
private let e5FEN = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"
private let nf3FEN = "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2"

private func placementSquares(_ fen: String) -> [String: String] {
    var squares: [String: String] = [:]
    let ranks = fen.split(separator: " ")[0].split(separator: "/")
    for (row, rank) in ranks.enumerated() {
        var column = 0
        for piece in rank {
            if let n = piece.wholeNumberValue { for _ in 0..<n { squares["\(Array("abcdefgh")[column])\(8 - row)"] = "empty"; column += 1 } }
            else { squares["\(Array("abcdefgh")[column])\(8 - row)"] = String(piece); column += 1 }
        }
    }
    return squares
}

private struct MockFrame {
    let bytes: Data, fen: String, parent: String?, move: [String: String]?, unknown: Bool
    var sha: String { NativeSyntheticRecognizer.sha256(bytes) }
    var asset: ReplayFrameAsset { ReplayFrameAsset(asset: "mock/\(sha.prefix(12))", sha256: sha) }
    var board: OfflineBoard {
        var squares = placementSquares(fen)
        if unknown { for square in ["d4", "d5", "e4", "e5"] { squares[square] = "unknown" } }
        return OfflineBoard(sha256: sha, squares: squares)
    }
}
@MainActor private var frameCounter = 0
@MainActor private func frame(_ fen: String, parent: String? = nil, move: [String: String]? = nil, unknown: Bool = false) -> MockFrame {
    frameCounter += 1
    return MockFrame(bytes: Data("mock-replay-frame-\(frameCounter)-\(fen)".utf8), fen: fen, parent: parent, move: move, unknown: unknown)
}
@MainActor private func gameFrames() -> [MockFrame] {
    [frame(startFEN), frame(startFEN),
     frame(e4FEN, parent: startFEN, move: ["from": "e2", "to": "e4", "san": "e4"]),
     frame(e4FEN, parent: startFEN, move: ["from": "e2", "to": "e4", "san": "e4"]),
     frame(e5FEN, parent: e4FEN, move: ["from": "e7", "to": "e5", "san": "e5"]),
     frame(e5FEN, parent: e4FEN, move: ["from": "e7", "to": "e5", "san": "e5"]),
     frame(nf3FEN, parent: e5FEN, move: ["from": "g1", "to": "f3", "san": "Nf3"])]
}

// MARK: - Shared in-flight ledger (asserts tracker and engine are never in flight together)

@MainActor private final class Ledger {
    var engine = 0, tracker = 0, overlaps = 0
    func enterEngine() { if tracker > 0 { overlaps += 1 }; engine += 1 }
    func leaveEngine() { engine -= 1 }
    func enterTracker() { if engine > 0 { overlaps += 1 }; tracker += 1 }
    func leaveTracker() { tracker -= 1 }
}

// MARK: - Mock tracker transport emulating the frozen JS contract (docs/REPLAY_GAME.md)

private struct TransportDown: Error {}

@MainActor private final class MockTrackerTransport: ReplayTrackerTransport {
    let ledger: Ledger
    var table: [String: MockFrame] = [:]
    // Emulated tracker state.
    var session: Any = NSNull(), lastFrame: Any = NSNull(), lastMove: Any = NSNull()
    var fen: String?, status = "disconnected", reason = "not-connected", revision: UInt64 = 0
    var pendingFEN: String?, pendingCount = 0
    // Controls.
    var hold = false
    var held: CheckedContinuation<String, Error>?
    private var heldReply = ""
    /// Return a custom reply for a request (or nil to emulate); throw to simulate a transport failure.
    var override: ((_ request: [String: Any]) throws -> String?)?
    var kinds: [String] = []
    var capturedAtMs: [UInt64] = []
    init(ledger: Ledger) { self.ledger = ledger }

    func submit(requestJSON: String, timeoutMilliseconds: Int) async throws -> String {
        ledger.enterTracker(); defer { ledger.leaveTracker() }
        guard let request = try JSONSerialization.jsonObject(with: Data(requestJSON.utf8)) as? [String: Any],
              let kind = request["kind"] as? String else { throw TransportDown() }
        kinds.append(kind)
        if kind == "observe", let f = request["frame"] as? [String: Any], let t = (f["capturedAtMs"] as? NSNumber)?.uint64Value { capturedAtMs.append(t) }
        let reply: String
        if let override, let custom = try override(request) { reply = custom } else { reply = emulate(request) }
        if hold { heldReply = reply; return try await withCheckedThrowingContinuation { held = $0 } }
        return reply
    }
    func release() { let c = held; held = nil; c?.resume(returning: heldReply) }

    private func invalidate(_ why: String) { status = "needs-confirmation"; reason = why; revision += 1; pendingFEN = nil; pendingCount = 0 }
    private func emulate(_ request: [String: Any]) -> String {
        switch request["kind"] as? String {
        case "initialize":
            session = request["session"] ?? NSNull(); lastFrame = NSNull(); lastMove = NSNull()
            fen = request["fen"] as? String; revision += 1; status = "stabilizing"; reason = "waiting-for-observations"
            pendingFEN = nil; pendingCount = 0
        case "observe":
            let f = request["frame"] as! [String: Any], identity = f["identity"] as! [String: Any]
            lastFrame = ["sessionId": identity["sessionId"]!, "epoch": identity["epoch"]!, "sequence": identity["sequence"]!,
                         "frameSha256": identity["frameSha256"]!, "capturedAtMs": f["capturedAtMs"]!]
            let squares = f["squares"] as! [String: [String: Any]]
            if squares.values.contains(where: { ($0["label"] as? String) == "unknown" || (($0["confidence"] as? Double) ?? 0) < 0.95 }) {
                invalidate("uncertain-squares"); break
            }
            guard let entry = table[identity["frameSha256"] as! String] else { invalidate("not-zero-or-one-legal-move"); break }
            if status == "ready" && entry.fen == fen { break }
            let same = entry.fen == fen, oneMove = entry.parent != nil && entry.parent == fen
            revision += 1; status = "stabilizing"; reason = "waiting-for-stability"
            guard same || oneMove else { invalidate("not-zero-or-one-legal-move"); break }
            if pendingFEN == entry.fen { pendingCount += 1 } else { pendingFEN = entry.fen; pendingCount = 1 }
            if pendingCount >= 2 {
                if oneMove { fen = entry.fen; lastMove = entry.move ?? NSNull() }
                status = "ready"; reason = "stable-legal-position"
            }
        default: break
        }
        return success(request)
    }
    func success(_ request: [String: Any], ignored: String? = nil) -> String {
        var reply: [String: Any] = ["schemaVersion": 1, "requestId": request["requestId"]!, "kind": request["kind"]!,
                                    "runtime": "on-device-local", "mode": "replay-only", "session": session, "lastFrame": lastFrame,
                                    "trackingReady": status == "ready", "guidanceAllowed": false, "liveGuidanceAllowed": false,
                                    "state": ["status": status, "reason": reason, "revision": revision, "fen": fen ?? NSNull(),
                                              "lastMove": lastMove, "historyComplete": false] as [String: Any]]
        if let ignored { reply["ignored"] = ignored }
        return String(data: try! JSONSerialization.data(withJSONObject: reply), encoding: .utf8)!
    }
    func errorReply(_ request: [String: Any], code: String) -> String {
        let reply: [String: Any] = ["schemaVersion": 1, "requestId": request["requestId"]!, "kind": request["kind"]!,
                                    "runtime": "on-device-local", "mode": "replay-only", "guidanceAllowed": false, "liveGuidanceAllowed": false,
                                    "error": ["code": code, "message": "mock rejection", "trackerRevoked": true]]
        return String(data: try! JSONSerialization.data(withJSONObject: reply), encoding: .utf8)!
    }
}

// MARK: - Mock recognizer and engine

private actor MockPixels: OfflineImageRecognizer {
    var boards: [String: OfflineBoard] = [:]
    var hold = false
    var pending: CheckedContinuation<OfflineBoard, Error>?
    var pendingBoard: OfflineBoard?
    func set(_ frames: [MockFrame]) { for f in frames { boards[f.sha] = f.board } }
    func setHold(_ value: Bool) { hold = value }
    func recognize(_ bytes: Data) async throws -> OfflineBoard {
        guard let board = boards[NativeSyntheticRecognizer.sha256(bytes)] else { throw OfflineStudyError.invalidImage }
        if hold { pendingBoard = board; return try await withCheckedThrowingContinuation { pending = $0 } }
        return board
    }
    func waiting() -> Bool { pending != nil }
    func resume() { let c = pending; pending = nil; c?.resume(returning: pendingBoard!) }
}

@MainActor private final class MockEngine: ReplayEngineBackend {
    let ledger: Ledger, transport: MockTrackerTransport
    var starts = 0, validations = 0, analyses = 0, legalTexts = 0, cancels = 0, closes = 0, analysisReturns = 0
    var holdAnalysis = false, cancelFailsHeld = true, foreignRequest = false, foreignRevision = false
    var analyzing: CheckedContinuation<NativeEngineResult, Error>?
    var request: AnalysisRequest?
    var closure: (@MainActor () -> Void)?
    init(ledger: Ledger, transport: MockTrackerTransport) { self.ledger = ledger; self.transport = transport }
    func start() async throws { starts += 1 }
    func validate(_ fen: String) async throws -> ValidatedPosition {
        ledger.enterEngine(); defer { ledger.leaveEngine() }
        validations += 1; await Task.yield()
        return ValidatedPosition(fen: fen, terminal: false)
    }
    func analyze(_ request: AnalysisRequest) async throws -> NativeEngineResult {
        ledger.enterEngine(); defer { ledger.leaveEngine(); analysisReturns += 1 }
        analyses += 1; self.request = request
        if holdAnalysis { return try await withCheckedThrowingContinuation { analyzing = $0 } }
        await Task.yield()
        return reply()
    }
    func reply() -> NativeEngineResult {
        let input = request!
        let bound = AnalysisRequest(id: foreignRequest ? UUID() : input.id, frame: input.frame,
                                    revision: foreignRevision ? input.revision + 1 : input.revision, fen: input.fen,
                                    movetimeMilliseconds: input.movetimeMilliseconds)
        return NativeEngineResult(request: bound, moveUCI: "g1f3")
    }
    /// The app's rules check: returns legal-move text only.
    func speech(fen: String, move: String) async throws -> String {
        ledger.enterEngine(); defer { ledger.leaveEngine() }
        legalTexts += 1; await Task.yield()
        return "text for \(move) at \(fen.prefix(20))"
    }
    func cancel() {
        cancels += 1
        if cancelFailsHeld, let held = analyzing { analyzing = nil; held.resume(throwing: CancellationError()) }
    }
    func close() { closes += 1 }
    func observeClosure(_ handler: @escaping @MainActor () -> Void) { closure = handler }
    func die() { closure?() }
    func makeTrackerTransport() -> any ReplayTrackerTransport { transport }
}

// MARK: - Rig and helpers

@MainActor private final class Rig {
    let ledger = Ledger()
    let transport: MockTrackerTransport
    let engine: MockEngine
    let pixels = MockPixels()
    let frames: [MockFrame], interruption: MockFrame
    let model: ReplayGameModel
    init(frames: [MockFrame] = gameFrames(), extraBytes: [String: Data] = [:]) {
        self.frames = frames
        interruption = frame(startFEN, unknown: true)
        transport = MockTrackerTransport(ledger: ledger)
        engine = MockEngine(ledger: ledger, transport: transport)
        for f in frames { transport.table[f.sha] = f }
        var bytes: [String: Data] = [:]
        for f in frames + [interruption] { bytes[f.asset.asset] = f.bytes }
        for (k, v) in extraBytes { bytes[k] = v }
        let engine = engine, pixels = pixels
        model = ReplayGameModel(makeBackend: { engine }, recognizer: pixels,
                                loadFrame: { asset in guard let data = bytes[asset.asset] else { throw OfflineStudyError.missingResource }; return data },
                                frames: frames.map(\.asset), interruption: interruption.asset)
    }
    func setup() async { await pixels.set(frames + [interruption]) }
    func started() async throws { await setup(); model.start(); try await idle(model); model.step(); try await idle(model) }
    func review(_ fen: String) async throws {
        model.editFEN(fen)
        for field in ReviewField.allCases { model.setReview(field, checked: true) }
        model.confirmReview(); try await idle(model)
    }
    func tracking() async throws { try await started(); try await review(startFEN) }
    func analyzed() async throws { model.analyze(); try await idle(model) }
}

private struct CheckFailed: Error, CustomStringConvertible { let description: String }
private func check(_ value: @autoclosure () -> Bool, _ message: String) throws { if !value() { throw CheckFailed(description: message) } }
@MainActor private func idle(_ model: ReplayGameModel) async throws {
    for _ in 0..<5000 { if !model.busy { return }; await Task.yield() }
    throw CheckFailed(description: "Replay model did not finish a bounded mock operation")
}
@MainActor private func until(_ message: String, _ condition: () -> Bool) async throws {
    for _ in 0..<5000 { if condition() { return }; await Task.yield() }
    throw CheckFailed(description: "Mock continuation was not reached: \(message)")
}
@MainActor private func settle() async { for _ in 0..<200 { await Task.yield() } }

/// Everything a person can see or act on (busy excluded: a held call keeps the model honestly busy).
@MainActor private struct Snapshot: Equatable {
    let status: String, ready: Bool, phase: ReplayPhase, frameIndex: Int?, interruption: Bool, boardHash: String?
    let fen: String, checks: Set<ReviewField>, trackedFEN: String?, revision: UInt64?, san: String?, epoch: UInt64
    let recommendation: String?, move: String?, canAnalyze: Bool, canConfirm: Bool, identity: ReplayRecommendationIdentity?
    init(_ m: ReplayGameModel) {
        status = m.status; ready = m.ready; phase = m.phase; frameIndex = m.frameIndex; interruption = m.showingInterruption
        boardHash = m.board?.sha256; fen = m.fen; checks = m.checks; trackedFEN = m.trackedFEN; revision = m.trackedRevision
        san = m.lastMoveSAN; epoch = m.reviewEpoch; recommendation = m.recommendation; move = m.move
        canAnalyze = m.canAnalyze; canConfirm = m.canConfirmReview; identity = m.currentIdentity
    }
}
@MainActor private func frozen(_ model: ReplayGameModel, _ message: String, release: () async throws -> Void) async throws {
    let before = Snapshot(model)
    try await release(); await settle(); try await idle(model)
    try check(Snapshot(model) == before, "\(message): visible state changed after the late reply")
    try check(model.recommendation == nil && model.move == nil && !model.canAnalyze, "\(message): late reply produced output")
}
@MainActor private func noAudio(_ model: ReplayGameModel) throws {
    // No speech dependency of any kind: no stored property is an OfflineSpeech.
    let speechProperties = Mirror(reflecting: model).children.filter { $0.value is any OfflineSpeech }
    try check(speechProperties.isEmpty, "The replay model must not hold any speech output")
}

// MARK: - Checks

@main private struct ReplayGameChecks {
    @MainActor static func main() async {
        var names: [String] = []
        var overlaps = 0
        func pass(_ name: String, _ rig: Rig) { names.append(name); overlaps += rig.ledger.overlaps }
        do {
            // 1. No analysis (or tracker contact) before one complete review.
            do {
                let rig = Rig(); try await rig.started()
                try check(rig.model.phase == .needsReview && rig.model.frameIndex == 0 && !rig.model.canAnalyze, "First frame needs review")
                rig.model.analyze(); try await idle(rig.model)
                rig.model.editFEN(startFEN)
                for field in ReviewField.allCases.dropLast() { rig.model.setReview(field, checked: true) }
                try check(!rig.model.canConfirmReview, "Four of five confirmations cannot start tracking")
                rig.model.confirmReview(); try await idle(rig.model)
                rig.model.analyze(); try await idle(rig.model)
                try check(rig.engine.analyses == 0 && rig.engine.validations == 0 && rig.transport.kinds.isEmpty && rig.model.recommendation == nil,
                          "No engine or tracker call before a complete review")
                rig.model.setReview(.counters, checked: true); rig.model.confirmReview(); try await idle(rig.model)
                try check(rig.model.phase == .tracking && rig.transport.kinds == ["initialize", "observe", "observe"] && rig.model.reviewEpoch == 1,
                          "Five confirmations start tracking with initialize and two observations")
                try check(rig.transport.capturedAtMs == [100, 200], "Virtual replay time is a +100 ms step counter from 0")
                try await rig.analyzed()
                try check(rig.model.recommendation != nil && rig.model.result?.identity == rig.model.currentIdentity &&
                          rig.model.result?.identity.reviewEpoch == 1 && rig.model.result?.identity.run == rig.model.runID,
                          "Reviewed start position yields a bound recommendation")
                try noAudio(rig.model)
                pass("no-analysis-before-review", rig)
            }

            // 2-3. Clean legal advance keeps review, allows analysis of the new position; advance revokes.
            do {
                let rig = Rig(); try await rig.tracking(); try await rig.analyzed()
                let first = rig.model.result!.identity
                rig.model.step()
                try check(rig.model.recommendation == nil && rig.model.result == nil && !rig.model.canAnalyze, "Advance revokes the recommendation synchronously")
                pass("recommendation-revoked-on-advance", rig)
                try await idle(rig.model)
                try check(rig.model.phase == .tracking && rig.model.checks.count == 5 && rig.model.trackedFEN == startFEN &&
                          rig.model.trackedRevision == first.trackerRevision && rig.model.canAnalyze, "Same-position frame keeps tracking")
                rig.model.step(); try await idle(rig.model)
                try check(rig.model.phase == .tracking && rig.model.trackedFEN == e4FEN && rig.model.lastMoveSAN == "e4" &&
                          rig.model.checks.count == 5 && rig.model.canAnalyze && rig.model.reviewEpoch == 1, "Legal advance keeps the review")
                try await rig.analyzed()
                let second = rig.model.result!.identity
                try check(rig.model.recommendation != nil && second.fen == e4FEN && second.trackerRevision > first.trackerRevision &&
                          second.reviewEpoch == first.reviewEpoch && rig.engine.request?.fen == e4FEN, "New position analyzed with a new identity")
                try check(rig.transport.capturedAtMs == [100, 200, 300, 400, 500, 600], "Two observations per frame, +100 ms each")
                pass("clean-advance-keeps-review-and-allows-analysis", rig)
            }

            // 4. Late analysis reply after advance is dropped; the tracker waits for the engine to end.
            do {
                let rig = Rig(); try await rig.tracking()
                rig.engine.holdAnalysis = true; rig.engine.cancelFailsHeld = false
                rig.model.analyze(); try await until("held analysis") { rig.engine.analyzing != nil }
                let kindsBefore = rig.transport.kinds.count
                rig.model.step()
                try check(rig.model.recommendation == nil && rig.engine.cancels >= 1, "Stepping cancels in-flight analysis")
                await settle()
                try check(rig.transport.kinds.count == kindsBefore, "No tracker request while the engine is still in flight")
                rig.engine.analyzing?.resume(returning: rig.engine.reply()); rig.engine.analyzing = nil
                try await idle(rig.model)
                try check(rig.model.recommendation == nil && rig.model.result == nil && rig.engine.legalTexts == 0,
                          "Late analysis reply after advance must not restore output or request legal text")
                try check(rig.model.frameIndex == 1 && rig.model.phase == .tracking && rig.transport.kinds.count == kindsBefore + 2,
                          "The step completes after the engine ended")
                pass("late-analysis-after-advance-dropped", rig)
            }

            // 5. Late tracker reply after reset (and after edit) is dropped.
            let lateRevokers: [(String, @MainActor (ReplayGameModel) -> Void)] = [("reset", { $0.reset() }), ("edit", { $0.editFEN(e4FEN) })]
            for (name, revoke) in lateRevokers {
                let rig = Rig(); try await rig.tracking(); try await rig.analyzed()
                rig.transport.hold = true
                rig.model.step(); try await until("held tracker") { rig.transport.held != nil }
                revoke(rig.model)
                try check(rig.model.recommendation == nil && rig.model.phase != .tracking, "\(name) revokes at once")
                try await frozen(rig.model, "Late tracker reply after \(name)") { rig.transport.release() }
                try check(rig.model.trackedFEN == nil && !rig.model.trackingReady, "Late tracker reply after \(name) cannot restore tracking")
                pass("late-tracker-reply-after-\(name)-dropped", rig)
            }

            // 6. Unknown squares revoke; tracking stays blocked until a renewed full review.
            do {
                let rig = Rig(); try await rig.tracking()
                rig.model.step(); try await idle(rig.model)
                rig.model.step(); try await idle(rig.model) // e4
                try await rig.analyzed()
                rig.model.queueInterruption(); rig.model.step(); try await idle(rig.model)
                try check(rig.model.showingInterruption && rig.model.phase == .needsReview && rig.model.recommendation == nil &&
                          !rig.model.canAnalyze && !rig.model.canConfirmReview && rig.model.checks.isEmpty && rig.model.trackedFEN == nil,
                          "Obstructed frame revokes and cannot be reviewed")
                try check(rig.model.status.contains("Unknown"), "Status names the unknown squares")
                let sent = rig.transport.kinds.count, analyses = rig.engine.analyses
                rig.model.step(); try await idle(rig.model) // frame 3 (e4 again), not tracked
                rig.model.analyze(); try await idle(rig.model)
                try check(rig.model.frameIndex == 3 && !rig.model.showingInterruption && rig.model.phase == .needsReview &&
                          rig.transport.kinds.count == sent && rig.engine.analyses == analyses && !rig.model.canAnalyze,
                          "Later good frames stay blocked without review and never reach the tracker")
                try await rig.review(e4FEN)
                try check(rig.model.phase == .tracking && rig.model.reviewEpoch == 2 && rig.model.trackedFEN == e4FEN,
                          "Renewed review restarts tracking with a new epoch")
                try await rig.analyzed()
                try check(rig.model.recommendation != nil && rig.model.result?.identity.reviewEpoch == 2, "Analysis after renewed review")
                pass("unknown-squares-revoke-until-renewed-review", rig)
            }

            // 7. Skipped ply revokes.
            do {
                let skip = frame(nf3FEN, parent: e5FEN, move: ["from": "g1", "to": "f3", "san": "Nf3"])
                let frames = gameFrames()
                let rig = Rig(frames: [frames[0], frames[2], skip]); try await rig.tracking()
                rig.model.step(); try await idle(rig.model)
                try await rig.analyzed()
                try check(rig.model.trackedFEN == e4FEN && rig.model.recommendation != nil, "e4 tracked")
                rig.model.step(); try await idle(rig.model)
                try check(rig.model.phase == .needsReview && rig.model.recommendation == nil && rig.model.trackedFEN == nil &&
                          !rig.model.canAnalyze && rig.model.status.contains("other than one legal move"), "Skipped ply revokes")
                pass("skipped-ply-revokes", rig)
            }

            // 8. Reordered frames revoke: an ignored reply, and a frame from earlier in the game.
            do {
                let rig = Rig(); try await rig.tracking(); try await rig.analyzed()
                rig.transport.override = { [unowned transport = rig.transport] request in
                    request["kind"] as? String == "observe" ? transport.success(request, ignored: "repeated-or-reordered-frame") : nil
                }
                rig.model.step(); try await idle(rig.model)
                try check(rig.model.phase == .needsReview && rig.model.recommendation == nil && !rig.model.canAnalyze &&
                          rig.model.status.contains("reordered"), "Ignored (reordered) frame revokes")
                let frames = gameFrames()
                let back = Rig(frames: [frames[0], frames[2], frames[0]]); try await back.tracking()
                back.model.step(); try await idle(back.model)
                try check(back.model.trackedFEN == e4FEN, "e4 tracked")
                try await back.analyzed()
                back.model.step(); try await idle(back.model)
                try check(back.model.phase == .needsReview && back.model.recommendation == nil && !back.model.canAnalyze, "Earlier frame replayed out of order revokes")
                pass("reordered-frame-revokes", rig); overlaps += back.ledger.overlaps
            }

            // 9. Tracker error reply revokes. 10. Transport failure revokes.
            for failure in ["error-reply", "transport-failure"] {
                let rig = Rig(); try await rig.tracking(); try await rig.analyzed()
                rig.transport.override = { [unowned transport = rig.transport] request in
                    guard request["kind"] as? String == "observe" else { return nil }
                    if failure == "transport-failure" { throw TransportDown() }
                    return transport.errorReply(request, code: "INVALID_REQUEST")
                }
                rig.model.step(); try await idle(rig.model)
                try check(rig.model.phase == .needsReview && rig.model.recommendation == nil && rig.model.trackedFEN == nil &&
                          !rig.model.canAnalyze && rig.model.checks.isEmpty, "\(failure) revokes and requires renewed review")
                // The client latches revoked: nothing more is sent until a renewed review.
                rig.transport.override = nil
                let sent = rig.transport.kinds.count
                rig.model.step(); try await idle(rig.model)
                try check(rig.transport.kinds.count == sent && rig.model.phase == .needsReview, "\(failure): no tracking without renewed review")
                pass("tracker-\(failure)-revokes", rig)
            }

            // 11-14. Edit, reset, background and leave-mode each revoke; a held analysis released afterwards changes nothing.
            let revokers: [(String, @MainActor (ReplayGameModel) -> Void)] = [
                ("edit", { $0.editFEN(e4FEN) }),
                ("review-untick", { $0.setReview(.castling, checked: false) }),
                ("reset", { $0.reset() }),
                ("background", { $0.setActive(false) }),
                ("leave-mode", { $0.leave() }),
            ]
            for (name, revoke) in revokers {
                let rig = Rig(); try await rig.tracking(); try await rig.analyzed()
                try check(rig.model.recommendation != nil, "\(name): recommendation present first")
                revoke(rig.model)
                try check(rig.model.recommendation == nil && rig.model.phase != .tracking && !rig.model.canAnalyze, "\(name) revokes at once")
                if name == "edit" || name == "review-untick" {
                    try check(rig.model.phase == .needsReview && rig.model.checks.isEmpty && rig.model.ready, "\(name) requires renewed review")
                } else {
                    try check(rig.model.phase == .engineStopped && !rig.model.ready && rig.engine.closes == 1, "\(name) closes the engine")
                }
                // Held-reply variant.
                let held = Rig(); try await held.tracking()
                held.engine.holdAnalysis = true; held.engine.cancelFailsHeld = false
                held.model.analyze(); try await until("held analysis") { held.engine.analyzing != nil }
                revoke(held.model)
                try await frozen(held.model, "Late analysis after \(name)") {
                    held.engine.analyzing?.resume(returning: held.engine.reply()); held.engine.analyzing = nil
                }
                try check(held.engine.legalTexts == 0, "Late analysis after \(name) must not request legal text")
                if name == "leave-mode" {
                    held.model.start(); await settle()
                    try check(!held.model.ready && held.engine.starts == 1, "Leaving the mode keeps the replay inactive")
                }
                pass("\(name)-revokes", rig); overlaps += held.ledger.overlaps
            }

            // 15. Never concurrent: analysis blocked while a tracker request is in flight, and vice versa.
            do {
                let rig = Rig(); try await rig.tracking()
                rig.transport.hold = true
                rig.model.step(); try await until("held tracker") { rig.transport.held != nil }
                rig.model.analyze(); rig.model.step(); rig.model.confirmReview()
                try check(rig.engine.analyses == 0 && rig.ledger.engine == 0, "No engine call while the tracker is in flight")
                rig.transport.hold = false; rig.transport.release(); try await idle(rig.model)
                rig.engine.holdAnalysis = true
                rig.model.analyze(); try await until("held analysis") { rig.engine.analyzing != nil }
                rig.model.step() // cancel resumes the held analysis with a cancellation error, like the runtime
                try await idle(rig.model)
                try check(rig.ledger.overlaps == 0 && rig.model.frameIndex == 2 && rig.model.recommendation == nil, "Stepping during analysis stays sequential")
                pass("tracker-and-engine-never-concurrent", rig)
            }

            // 16. Analysis identity mismatch rejected (request ID, and revision).
            let mismatches: [(String, @MainActor (MockEngine) -> Void)] = [("request-id", { $0.foreignRequest = true }),
                                                                            ("revision", { $0.foreignRevision = true })]
            for (name, configure) in mismatches {
                let rig = Rig(); try await rig.tracking()
                configure(rig.engine)
                try await rig.analyzed()
                try check(rig.model.recommendation == nil && rig.model.result == nil && rig.engine.legalTexts == 0 &&
                          rig.model.status.hasPrefix("Analysis failed"), "Analysis reply with foreign \(name) is rejected")
                pass("analysis-identity-mismatch-\(name)-rejected", rig)
            }

            // 17. Virtual time ignores the wall clock; pinned frame hash mismatch is rejected; runtime death revokes.
            do {
                let rig = Rig(); try await rig.started()
                try await Task.sleep(for: .milliseconds(300)) // wall-clock time passes during review
                try await rig.review(startFEN)
                rig.model.step(); try await idle(rig.model)
                try check(rig.transport.capturedAtMs == [100, 200, 300, 400], "Virtual time does not follow the wall clock")
                rig.engine.die()
                try check(!rig.model.ready && rig.model.phase == .engineStopped && rig.model.recommendation == nil &&
                          rig.model.status.contains("stopped"), "Runtime stop revokes")
                rig.model.start(); try await idle(rig.model); try await rig.review(startFEN)
                try check(rig.model.phase == .tracking && rig.transport.capturedAtMs.suffix(2) == [100, 200] && rig.model.reviewEpoch == 2,
                          "A new runtime restarts virtual time at 0 with a new review epoch")
                let frames = gameFrames()
                let tampered = Rig(frames: [frames[0]], extraBytes: [frames[0].asset.asset: Data("tampered".utf8)])
                await tampered.setup(); tampered.model.start(); try await idle(tampered.model)
                tampered.model.step(); try await idle(tampered.model)
                try check(tampered.model.board == nil && tampered.model.phase != .tracking && tampered.model.status.contains("failed"),
                          "Frame bytes that do not match the pin are rejected")
                pass("virtual-time-pins-and-runtime-stop", rig); overlaps += tampered.ledger.overlaps
            }

            // 18. Late recognition after reset cannot repopulate.
            do {
                let rig = Rig(); await rig.setup(); rig.model.start(); try await idle(rig.model)
                await rig.pixels.setHold(true)
                rig.model.step()
                for _ in 0..<2000 { if await rig.pixels.waiting() { break }; await Task.yield() }
                rig.model.reset()
                try await frozen(rig.model, "Late recognition after reset") { await rig.pixels.resume() }
                try check(rig.model.board == nil && rig.model.frameIndex == nil, "Late recognition after reset shows nothing")
                pass("late-recognition-after-reset-dropped", rig)
            }

            try check(overlaps == 0, "Tracker and engine requests overlapped \(overlaps) times")
            print("Replay game mock checks: \(names.count)/\(names.count) passed; tracker/engine overlaps: 0; no WebKit, recognition inference, device, speech or audio.")
            for name in names { print("  pass  \(name)") }
        } catch {
            print("FAILED after \(names.count) passing checks: \(error)")
            exit(1)
        }
    }
}
