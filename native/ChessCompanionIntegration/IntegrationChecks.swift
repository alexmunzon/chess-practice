import Foundation

private struct CheckFailure: Error { let message: String }
private func require(_ condition: Bool, _ text: String = "Integration check failed", line: Int = #line) throws {
    if !condition { throw CheckFailure(message: "\(text) at line \(line)") }
}
private func rejects(_ body: () throws -> Void) throws {
    do { try body() } catch { return }; throw CheckFailure(message: "Expected rejection")
}
@MainActor private func rejectsAsync<T>(_ body: () async throws -> T) async throws {
    do { _ = try await body() } catch { return }; throw CheckFailure(message: "Expected async rejection")
}
private let fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
private let afterE4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
private func fixtureFrame(sequence: UInt64 = 1, epoch: UInt64 = 1, dat: Bool = false) -> CapturedFrame {
    CapturedFrame(sessionID: UUID(), epoch: epoch, sequence: sequence, bytes: Data("mock-image-bytes".utf8), receivedAt: 0,
                  captureTime: dat ? .unknownDAT(mediaPTS: nil) : .trustedReplay(hostSeconds: 0, clockDomain: UUID()))
}
private func fixtureRequest(sequence: UInt64 = 1, epoch: UInt64 = 1, revision: UInt64 = 1) -> AnalysisRequest {
    AnalysisRequest(id: UUID(), frame: fixtureFrame(sequence: sequence, epoch: epoch).identity, revision: revision, fen: fen, movetimeMilliseconds: 100)
}

#if INTEGRATION_TRANSPORT_STUB
/// Tests the concrete wrapper without importing/constructing WebKit.
@MainActor public final class NativeEngineRuntime {
    var operations: [UUID] = [], taskCancellations: [UUID] = []
    var globalCancelCalls = 0
    var pending: [UUID: CheckedContinuation<String, Error>] = [:]
    public func submit(commandJSON: String, timeoutMilliseconds: Int) async throws -> String {
        try Task.checkCancellation()
        let token = UUID(); operations.append(token)
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { pending[token] = $0 }
        } onCancel: { Task { @MainActor [weak self] in self?.taskCancellations.append(token) } }
    }
    public func cancel() { globalCancelCalls += 1 }
    func finish(_ token: UUID, text: String) { pending.removeValue(forKey: token)?.resume(returning: text) }
}
#endif

@MainActor private final class MockTransport: LocalJSONTransport {
    struct Call { let operation: UUID; let command: [String: Any]; let timeout: Int }
    var calls: [Call] = [], cancelled: [UUID] = []
    var pending: [UUID: CheckedContinuation<String, Error>] = [:]
    var automatic = true
    var mutation: ((inout [String: Any]) -> Void)?
    /// Kinds whose submission fails like a transport error (prewarm failure checks).
    var failingKinds: Set<String> = []
    func submit(commandJSON: String, operation: UUID, timeoutMilliseconds: Int) async throws -> String {
        let command = try JSONContract.object(commandJSON)
        calls.append(Call(operation: operation, command: command, timeout: timeoutMilliseconds))
        if let kind = command["kind"] as? String, failingKinds.contains(kind) { throw IntegrationFailure.cancelled }
        if automatic { return try reply(command) }
        // Deliberately ignores cancellation: an old callback may settle after a replacement.
        return try await withCheckedThrowingContinuation { pending[operation] = $0 }
    }
    func cancel(operation: UUID) { cancelled.append(operation) }
    func finish(_ operation: UUID) throws {
        guard let call = calls.first(where: { $0.operation == operation }) else { throw CheckFailure(message: "Missing mock call") }
        pending.removeValue(forKey: operation)?.resume(returning: try reply(call.command))
    }
    func reply(_ command: [String: Any]) throws -> String {
        let kind = command["kind"] as! String
        var reply: [String: Any] = ["schemaVersion": 1, "requestId": command["requestId"]!, "kind": kind, "runtime": "on-device-local"]
        switch kind {
        case "position": reply["position"] = ["fen": command["fen"]!, "gameOver": false, "historyAvailable": false]
        case "move":
            reply["fen"] = command["fen"]!; reply["move"] = command["move"]!
            reply["position"] = ["fen": afterE4, "gameOver": false, "historyAvailable": false]
            reply["speechText"] = "pawn from e2 to e4."
        case "analyze":
            reply["identity"] = command["identity"]!; reply["fen"] = command["fen"]!
            reply["bestMove"] = ["from": "e2", "to": "e4", "san": "e4"]
            reply["speechText"] = "pawn from e2 to e4."; reply["status"] = "playing"
        case "prewarm": reply["spare"] = "starting"
        case "cancelPrewarm": reply["cancelled"] = true
        default: throw CheckFailure(message: "Unexpected mock command")
        }
        mutation?(&reply)
        return String(data: try JSONSerialization.data(withJSONObject: reply), encoding: .utf8)!
    }
}

/// Replays actual Node DeviceBackend output without executing WebKit.
@MainActor private final class BackendFixtureTransport: LocalJSONTransport {
    let fixture: [String: Any]
    var kinds: [String] = []
    init(path: String) throws {
        fixture = try JSONContract.object(String(contentsOfFile: path, encoding: .utf8))
        guard fixture["kind"] as? String == "real-device-backend-contract-fixtures" else { throw CheckFailure(message: "Real backend fixture provenance required") }
    }
    func submit(commandJSON: String, operation: UUID, timeoutMilliseconds: Int) async throws -> String {
        let command = try JSONContract.object(commandJSON), kind = command["kind"] as! String
        let originals = fixture["commands"] as! [String: [String: Any]], responses = fixture["responses"] as! [String: [String: Any]]
        guard let original = originals[kind], var reply = responses[kind], command["fen"] as? String == original["fen"] as? String else { throw CheckFailure(message: "Fixture command FEN mismatch") }
        if kind == "move" { try require(try JSONContract.move(command["move"], includesSAN: false) == JSONContract.move(original["move"], includesSAN: false)) }
        // These are the only substitutions: no FEN, move, speech or status repair.
        reply["requestId"] = command["requestId"]!
        if kind == "analyze" { reply["identity"] = command["identity"]! }
        kinds.append(kind)
        return String(data: try JSONSerialization.data(withJSONObject: reply), encoding: .utf8)!
    }
    func cancel(operation: UUID) {}
}

/// Mock phone-local JSON transport answering replay-tracker requests (no WebKit, no JS).
@MainActor private final class TrackerMockTransport: LocalJSONTransport {
    enum Behaviour { case echo, foreign, errorReply, fail, hang }
    var behaviour: Behaviour = .echo
    var calls: [(operation: UUID, command: [String: Any], timeout: Int)] = [], cancelled: [UUID] = []
    var pending: [UUID: CheckedContinuation<String, Error>] = [:]
    func submit(commandJSON: String, operation: UUID, timeoutMilliseconds: Int) async throws -> String {
        let command = try JSONContract.object(commandJSON)
        calls.append((operation, command, timeoutMilliseconds))
        switch behaviour {
        case .fail: throw IntegrationFailure.cancelled
        case .hang: return try await withCheckedThrowingContinuation { pending[operation] = $0 }
        case .errorReply:
            return try Self.text(["schemaVersion": 1, "requestId": command["requestId"]!, "kind": command["kind"]!, "runtime": "on-device-local",
                                  "mode": "replay-only", "guidanceAllowed": false, "liveGuidanceAllowed": false,
                                  "error": ["code": "STALE_SESSION", "message": "foreign session", "trackerRevoked": false]])
        case .echo, .foreign:
            let revision = command["kind"] as? String == "initialize" ? 2 : 3
            return try Self.text(["schemaVersion": 1, "requestId": behaviour == .foreign ? "old-request" : command["requestId"]!,
                                  "kind": command["kind"]!, "runtime": "on-device-local", "mode": "replay-only",
                                  "session": command["session"]!, "lastFrame": NSNull(), "trackingReady": false,
                                  "guidanceAllowed": false, "liveGuidanceAllowed": false,
                                  "state": ["status": "stabilizing", "reason": "waiting-for-observations", "revision": revision,
                                            "fen": fen, "lastMove": NSNull(), "historyComplete": false] as [String: Any]])
        }
    }
    func cancel(operation: UUID) {
        cancelled.append(operation)
        pending.removeValue(forKey: operation)?.resume(throwing: IntegrationFailure.cancelled)
    }
    static func text(_ value: [String: Any]) throws -> String { String(data: try JSONSerialization.data(withJSONObject: value), encoding: .utf8)! }
}
private let replaySession = ReplaySession(sessionId: "integration-replay", epoch: 1)
private let fullReview = ReplayHumanReview(pieces: true, turn: true, castling: true, enPassant: true, counters: true)

@MainActor private struct Checks {
    func settle() async { for _ in 0..<50 { await Task.yield() } }
    func workingRulesAndEngineBindings() async throws {
        let transport = MockTransport(), adapters = LocalChessAdapters(transport: transport)
        try require(transport.calls.isEmpty, "Construction must stay dormant")
        let state = try await adapters.validatePosition(fen)
        try require(state.fen == fen && !state.terminal)
        let speech = try await adapters.speechForLegalMove(fen: fen, moveUCI: "e2e4")
        try require(speech == "pawn from e2 to e4.")
        let request = fixtureRequest(), result = try await adapters.analyze(request)
        try require(result.request == request && result.moveUCI == "e2e4")
        let command = transport.calls.last!.command
        try require(command["requestId"] as? String == request.id.uuidString)
        try JSONContract.checkIdentity(command["identity"], request: request)
        try require(transport.calls.map(\.timeout) == [5000, 5000, 15000])
    }
    func fullHistoryNeverInferred() async throws {
        let transport = MockTransport(), adapters = LocalChessAdapters(transport: transport)
        for invalid in [String(fen.split(separator: " ").prefix(4).joined(separator: " ")), fen.replacingOccurrences(of: " w ", with: " ? "), fen.replacingOccurrences(of: " - 0 1", with: " - - 1")] {
            try await rejectsAsync { try await adapters.validatePosition(invalid) }
        }
        try require(transport.calls.isEmpty)
        transport.mutation = { reply in reply["position"] = ["fen": afterE4, "gameOver": false, "historyAvailable": false] }
        try await rejectsAsync { try await adapters.validatePosition(fen) }
        transport.mutation = { reply in reply["position"] = ["fen": fen, "gameOver": 0, "historyAvailable": false] }
        try await rejectsAsync { try await adapters.validatePosition(fen) }
    }
    func numericIdentityBounds() async throws {
        let transport = MockTransport(), adapters = LocalChessAdapters(transport: transport)
        let safe = fixtureRequest(sequence: JSONContract.maximumSafeInteger, epoch: JSONContract.maximumSafeInteger, revision: JSONContract.maximumSafeInteger)
        _ = try await adapters.analyze(safe)
        for request in [fixtureRequest(sequence: JSONContract.maximumSafeInteger + 1), fixtureRequest(epoch: 0), fixtureRequest(revision: 0), fixtureRequest(revision: UInt64.max)] {
            let count = transport.calls.count
            try await rejectsAsync { try await adapters.analyze(request) }; try require(transport.calls.count == count)
        }
        for invalid: Any in [true, 1.5, 9_007_199_254_740_992.0, -1] {
            transport.mutation = { reply in var identity = reply["identity"] as! [String: Any]; identity["epoch"] = invalid; reply["identity"] = identity }
            try await rejectsAsync { try await adapters.analyze(fixtureRequest()) }
        }
    }
    func foreignOrMalformedRepliesFailClosed() async throws {
        let mutations: [(inout [String: Any]) -> Void] = [
            { $0["requestId"] = "old-request" }, { $0["kind"] = "position" }, { $0["runtime"] = "remote" },
            { $0["schemaVersion"] = true }, { $0["unexpected"] = true }, { $0["fen"] = afterE4 },
            { var id = $0["identity"] as! [String: Any]; id["frameSha256"] = String(repeating: "0", count: 64); $0["identity"] = id },
            { $0["bestMove"] = NSNull() }, { $0["bestMove"] = ["from": "e", "to": "2e4", "san": "e4"] },
            { $0["bestMove"] = ["from": "e2", "to": "e4\n", "san": "e4"] },
            { $0["bestMove"] = ["from": "e2", "to": "e4", "promotion": "", "san": "e4"] }
        ]
        for mutation in mutations {
            let transport = MockTransport(); transport.mutation = mutation
            try await rejectsAsync { try await LocalChessAdapters(transport: transport).analyze(fixtureRequest()) }
        }
    }
    func moveEchoAndCanonicalUCI() async throws {
        let transport = MockTransport(), adapters = LocalChessAdapters(transport: transport)
        for bad in ["e2e4\n", "e2e4q\n", "e2e2", "e2e4qq", "a7a8k", "E2E4"] {
            try await rejectsAsync { try await adapters.speechForLegalMove(fen: fen, moveUCI: bad) }
        }
        try require(transport.calls.isEmpty)
        try require(try JSONContract.move(["from": "a7", "to": "a8", "promotion": "n"], includesSAN: false) == "a7a8n")
        for mutation: (inout [String: Any]) -> Void in [
            { $0["fen"] = afterE4 }, { $0["move"] = ["from": "d2", "to": "d4"] }, { $0["speechText"] = "injected\ntext" }
        ] {
            transport.mutation = mutation
            try await rejectsAsync { try await adapters.speechForLegalMove(fen: fen, moveUCI: "e2e4") }
        }
    }
    func cancelledOldRequestDoesNotAbortNewer() async throws {
        let transport = MockTransport(); transport.automatic = false
        let adapters = LocalChessAdapters(transport: transport)
        let old = Task { @MainActor in try await adapters.analyze(fixtureRequest()) }; await settle()
        let oldID = transport.calls[0].operation
        let replacement = Task { @MainActor in try await adapters.validatePosition(fen) }; await settle()
        let replacementID = transport.calls[1].operation
        try require(transport.cancelled == [oldID])
        old.cancel(); await settle()
        try require(!transport.cancelled.contains(replacementID))
        try transport.finish(oldID); try await rejectsAsync { try await old.value }
        try transport.finish(replacementID); let result = try await replacement.value
        try require(result.fen == fen)
    }
    func currentCancellationAndLateReplies() async throws {
        let transport = MockTransport(); transport.automatic = false
        let adapters = LocalChessAdapters(transport: transport)
        let task = Task { @MainActor in try await adapters.analyze(fixtureRequest()) }; await settle()
        let operation = transport.calls[0].operation
        task.cancel(); await settle(); try require(transport.cancelled == [operation])
        try transport.finish(operation); try await rejectsAsync { try await task.value }
        let next = Task { @MainActor in try await adapters.validatePosition(fen) }; await settle()
        let nextID = transport.calls[1].operation
        let preCancelled = Task { @MainActor in try await adapters.validatePosition(fen) }; preCancelled.cancel(); await settle()
        try await rejectsAsync { try await preCancelled.value }
        try require(transport.calls.count == 2 && !transport.cancelled.contains(nextID))
        try transport.finish(nextID); _ = try await next.value
    }
    func invalidNewRequestRevokesOldAnalysis() async throws {
        let transport = MockTransport(); transport.automatic = false
        let adapters = LocalChessAdapters(transport: transport)
        let task = Task { @MainActor in try await adapters.analyze(fixtureRequest()) }; await settle()
        let operation = transport.calls[0].operation
        try await rejectsAsync { try await adapters.validatePosition("8/8/8/8/8/8/8/8 w - -") }
        try require(transport.cancelled == [operation] && transport.calls.count == 1)
        try transport.finish(operation); try await rejectsAsync { try await task.value }
    }
    func unknownSyntheticProposalStaysUntrusted() async throws {
        let frame = fixtureFrame()
        let cells = Dictionary(uniqueKeysWithValues: (1...8).flatMap { rank in "abcdefgh".map { file in
            ("\(file)\(rank)", ["label": "unknown", "rawLabel": ".", "confidence": 0, "rawLabelAvailable": false] as [String: Any])
        } })
        var result: [String: Any] = ["schemaVersion": 1, "source": "synthetic-pixel-inference", "model": "synthetic-screen-template-v1",
                                     "pipelineVersion": "native-visible-markers-v1", "nativeImplementationVersion": NativeSyntheticRecognizer.implementationVersion,
                                     "templateFeaturesSha256": NativeSyntheticRecognizer.expectedFeatureHash, "sourceSha256": frame.identity.sha256,
                                     "status": "needs-human-review", "fen": NSNull(), "guidanceAllowed": false, "threshold": 0.95, "squares": cells]
        let proposal = try SyntheticFrameRecognizer.proposal(result, frame: frame)
        try require(proposal.frame == frame.identity && proposal.squares.count == 64 && proposal.squares.values.allSatisfy { $0.label == "unknown" && $0.confidence == 0 })
        result["fen"] = fen; try rejects { _ = try SyntheticFrameRecognizer.proposal(result, frame: frame) }
        result["fen"] = NSNull(); result["guidanceAllowed"] = true; try rejects { _ = try SyntheticFrameRecognizer.proposal(result, frame: frame) }
        result["guidanceAllowed"] = false; result["sourceSha256"] = String(repeating: "0", count: 64); try rejects { _ = try SyntheticFrameRecognizer.proposal(result, frame: frame) }
    }
    func syntheticAdapterRejectsDATBeforeInference() async throws {
        let data = try Data(contentsOf: URL(fileURLWithPath: "native/ChessCompanionVision/Assets/classic-templates-v1.json"))
        let recognizer = try SyntheticFrameRecognizer(templateData: data)
        do { _ = try await recognizer.recognize(fixtureFrame(dat: true)); throw CheckFailure(message: "DAT unexpectedly accepted") }
        catch IntegrationFailure.syntheticReplayOnly { }
    }
    func actualBackendResponseSchemaAccepted() async throws {
        guard CommandLine.arguments.count == 2 else { throw CheckFailure(message: "Pass the frozen actual DeviceBackend fixture JSON path") }
        let transport = try BackendFixtureTransport(path: CommandLine.arguments[1]), adapters = LocalChessAdapters(transport: transport)
        let position = try await adapters.validatePosition(fen)
        let result = try await adapters.analyze(fixtureRequest())
        let text = try await adapters.speechForLegalMove(fen: position.fen, moveUCI: result.moveUCI)
        let responses = transport.fixture["responses"] as! [String: [String: Any]]
        try require(text == responses["move"]?["speechText"] as? String)
        try require(result.moveUCI == JSONContract.move(responses["analyze"]?["bestMove"], includesSAN: true))
        try require(transport.kinds == ["position", "analyze", "move"])
    }
    func concreteWrapperCancellationIsTaskScoped() async throws {
        let runtime = NativeEngineRuntime(), oldWrapper = NativeRuntimeTransport(runtime: runtime), newWrapper = NativeRuntimeTransport(runtime: runtime)
        let oldID = UUID(), newID = UUID()
        let old = Task { @MainActor in try await oldWrapper.submit(commandJSON: "{}", operation: oldID, timeoutMilliseconds: 100) }; await settle()
        let oldToken = runtime.operations[0]
        let next = Task { @MainActor in try await newWrapper.submit(commandJSON: "{}", operation: newID, timeoutMilliseconds: 100) }; await settle()
        let newToken = runtime.operations[1]
        oldWrapper.cancel(operation: oldID); await settle()
        try require(runtime.globalCancelCalls == 0 && runtime.taskCancellations.contains(oldToken) && !runtime.taskCancellations.contains(newToken))
        runtime.finish(oldToken, text: "old"); try await rejectsAsync { try await old.value }
        runtime.finish(newToken, text: "current"); try require(try await next.value == "current")
    }
    func preCancelledConcreteWrapperPreservesCurrent() async throws {
        let runtime = NativeEngineRuntime(), wrapper = NativeRuntimeTransport(runtime: runtime)
        let current = Task { @MainActor in try await wrapper.submit(commandJSON: "{}", operation: UUID(), timeoutMilliseconds: 100) }; await settle()
        let token = runtime.operations[0]
        let old = Task { @MainActor in try await wrapper.submit(commandJSON: "{}", operation: UUID(), timeoutMilliseconds: 100) }
        old.cancel(); await settle(); try await rejectsAsync { try await old.value }
        try require(runtime.operations.count == 1 && runtime.taskCancellations.isEmpty && runtime.globalCancelCalls == 0)
        runtime.finish(token, text: "current"); try require(try await current.value == "current")
    }
    func replayAdapterSuccess() async throws {
        let mock = TrackerMockTransport(), tracker = ReplayTracker(transport: ReplayTrackerRuntimeTransport(transport: mock))
        try require(mock.calls.isEmpty, "Construction must stay dormant")
        let initialized = await tracker.initialize(session: replaySession, fen: fen, review: fullReview)
        guard case .tracking(let state) = initialized else { throw CheckFailure(message: "initialize revoked: \(initialized)") }
        try require(state.fen == fen && state.status == "stabilizing" && !state.trackingReady && tracker.isTrackingUsable)
        let snapshot = await tracker.snapshot()
        try require(snapshot.trackingState?.revision == 3 && snapshot.trackingState?.kind == .snapshot)
        try require(mock.calls.map { $0.command["kind"] as? String } == ["initialize", "snapshot"])
        try require(mock.calls.allSatisfy { $0.command["mode"] as? String == "trusted-replay" && $0.timeout == 2_000 })
        try require(Set(mock.calls.map(\.operation)).count == 2 && mock.cancelled.isEmpty, "fresh operation per request")
    }
    func replayAdapterForeignReplyRevokes() async throws {
        for behaviour in [TrackerMockTransport.Behaviour.foreign, .errorReply] {
            let mock = TrackerMockTransport(), tracker = ReplayTracker(transport: ReplayTrackerRuntimeTransport(transport: mock))
            _ = await tracker.initialize(session: replaySession, fen: fen, review: fullReview)
            mock.behaviour = behaviour
            let outcome = await tracker.snapshot()
            switch (behaviour, outcome) {
            case (.foreign, .revokedRenewedReviewRequired(.malformedReply(let detail))): try require(detail == "requestId mismatch")
            case (.errorReply, .revokedRenewedReviewRequired(.errorReply(let code))): try require(code == "STALE_SESSION")
            default: throw CheckFailure(message: "Unexpected outcome \(outcome)")
            }
            try require(!tracker.isTrackingUsable)
            mock.behaviour = .echo; let count = mock.calls.count
            try require(await tracker.snapshot() == .revokedRenewedReviewRequired(.notInitialized) && mock.calls.count == count, "latched until a new review")
        }
    }
    func replayAdapterFailureRevokes() async throws {
        let mock = TrackerMockTransport(), tracker = ReplayTracker(transport: ReplayTrackerRuntimeTransport(transport: mock))
        _ = await tracker.initialize(session: replaySession, fen: fen, review: fullReview)
        mock.behaviour = .fail
        guard case .revokedRenewedReviewRequired(.transportFailure) = await tracker.snapshot() else { throw CheckFailure(message: "failure must revoke") }
        try require(!tracker.isTrackingUsable)
        let fresh = TrackerMockTransport(); fresh.behaviour = .fail
        let first = ReplayTracker(transport: ReplayTrackerRuntimeTransport(transport: fresh))
        guard case .revokedRenewedReviewRequired(.transportFailure) = await first.initialize(session: replaySession, fen: fen, review: fullReview) else {
            throw CheckFailure(message: "failed initialize must revoke")
        }
    }
    func replayAdapterCancellationIsOperationScoped() async throws {
        let mock = TrackerMockTransport(); mock.behaviour = .hang
        let adapter = ReplayTrackerRuntimeTransport(transport: mock)
        let task = Task { @MainActor in try await adapter.submit(requestJSON: "{}", timeoutMilliseconds: 100) }; await settle()
        let next = Task { @MainActor in try await adapter.submit(requestJSON: "{}", timeoutMilliseconds: 100) }; await settle()
        task.cancel(); await settle()
        try require(mock.cancelled == [mock.calls[0].operation], "only the cancelled task's operation")
        try await rejectsAsync { try await task.value }
        mock.pending.removeValue(forKey: mock.calls[1].operation)?.resume(returning: "current")
        try require(try await next.value == "current")
        let preCancelled = Task { @MainActor in try await adapter.submit(requestJSON: "{}", timeoutMilliseconds: 100) }; preCancelled.cancel()
        try await rejectsAsync { try await preCancelled.value }; try require(mock.calls.count == 2)
    }
    func replayAdapterOverConcreteWrapper() async throws {
        let runtime = NativeEngineRuntime(), adapter = ReplayTrackerRuntimeTransport(runtime: runtime)
        let task = Task { @MainActor in try await adapter.submit(requestJSON: "{}", timeoutMilliseconds: 100) }; await settle()
        try require(runtime.operations.count == 1)
        runtime.finish(runtime.operations[0], text: "tracker-reply"); try require(try await task.value == "tracker-reply")
        let cancelled = Task { @MainActor in try await adapter.submit(requestJSON: "{}", timeoutMilliseconds: 100) }; await settle()
        cancelled.cancel(); await settle()
        try require(runtime.globalCancelCalls == 0 && runtime.taskCancellations == [runtime.operations[1]])
        runtime.finish(runtime.operations[1], text: "late"); try await rejectsAsync { try await cancelled.value }
    }
}

// Pre-started engine wiring (2026-11-16): node budget, search facts, prewarm requests.
private var validSearch: [String: Any] { ["nodes": 100_412, "nps": 351_000, "elapsedMs": 286.0, "spareUsed": true,
                                          "startup": "spare", "startupMs": 12.4, "fallbackReason": NSNull()] }
extension Checks {
    func nodeBudgetSentAndRangeGuarded() async throws {
        let transport = MockTransport(), adapters = LocalChessAdapters(transport: transport), request = fixtureRequest()
        let result = try await adapters.analyze(request, budget: .nodes(100_000))
        try require(result.request == request && result.moveUCI == "e2e4")
        let command = transport.calls.last!.command
        try require(JSONContract.unsigned(command["nodes"]) == 100_000 && command["movetimeMs"] == nil &&
                    Set(command.keys) == ["schemaVersion", "requestId", "kind", "fen", "confirmation", "identity", "nodes"], "exactly one limit: nodes")
        _ = try await adapters.analyze(request) // the request's own movetime, unchanged
        try require(JSONContract.unsigned(transport.calls.last!.command["movetimeMs"]) == 100 && transport.calls.last!.command["nodes"] == nil)
        for budget in [SearchBudget.nodes(1_000), .nodes(2_000_000), .movetime(milliseconds: 50), .movetime(milliseconds: 3000)] {
            _ = try await adapters.analyze(request, budget: budget)
        }
        let sent = transport.calls.count
        for budget in [SearchBudget.nodes(999), .nodes(2_000_001), .nodes(0), .nodes(-1), .movetime(milliseconds: 49), .movetime(milliseconds: 3001)] {
            try await rejectsAsync { try await adapters.analyze(request, budget: budget) }
        }
        try require(transport.calls.count == sent, "out-of-range budgets never reach the runtime")
    }
    func searchReportExactAndOptional() async throws {
        let transport = MockTransport(), adapters = LocalChessAdapters(transport: transport), request = fixtureRequest()
        _ = try await adapters.analyze(request, budget: .nodes(100_000))
        try require(adapters.lastSearch?.request == request.id && adapters.lastSearch?.report == nil, "a recorded older reply without search facts is accepted")
        transport.mutation = { $0["search"] = validSearch }
        _ = try await adapters.analyze(request, budget: .nodes(100_000))
        let report = adapters.lastSearch?.report
        try require(adapters.lastSearch?.request == request.id && report?.nodes == 100_412 && report?.nodesPerSecond == 351_000 &&
                    report?.spareUsed == true && report?.startup == "spare" && report?.startupMilliseconds == 12.4 && report?.fallbackReason == nil)
        let broken: [(String, (inout [String: Any]) -> Void)] = [
            ("extra search key", { $0["bestMove"] = "e2e4" }), ("missing key", { $0.removeValue(forKey: "nps") }),
            ("text count", { $0["nodes"] = "100412" }), ("negative time", { $0["elapsedMs"] = -1 }),
            ("unknown startup", { $0["startup"] = "warm" }), ("spare claimed on a fresh start", { $0["startup"] = "fresh" }),
            ("non-boolean spare", { $0["spareUsed"] = 1 }), ("free-text reason", { $0["fallbackReason"] = "Spare failed!" }),
        ]
        for (name, edit) in broken {
            var search = validSearch; edit(&search)
            transport.mutation = { $0["search"] = search }
            do { _ = try await adapters.analyze(request, budget: .nodes(100_000)); throw CheckFailure(message: "accepted: \(name)") }
            catch is CheckFailure { throw CheckFailure(message: "accepted: \(name)") } catch {}
        }
        transport.mutation = { $0["search"] = validSearch; $0["warmup"] = ["bestMove": "d2d4"] }
        try await rejectsAsync { try await adapters.analyze(request, budget: .nodes(100_000)) }
    }
    func prewarmReplyNeverAdvice() async throws {
        let transport = MockTransport(), adapters = LocalChessAdapters(transport: transport), request = fixtureRequest()
        // A prewarm-shaped reply answering an analysis is rejected.
        transport.mutation = { reply in
            if reply["kind"] as? String == "analyze" {
                reply = ["schemaVersion": 1, "requestId": reply["requestId"]!, "kind": "prewarm", "runtime": "on-device-local", "spare": "ready"]
            }
        }
        try await rejectsAsync { try await adapters.analyze(request, budget: .nodes(100_000)) }
        // A prewarm reply carrying a position, move or text is rejected, never a result.
        for extra in [["bestMove": ["from": "e2", "to": "e4", "san": "e4"]], ["speechText": "pawn from e2 to e4."], ["fen": fen]] as [[String: Any]] {
            transport.mutation = { reply in for (key, value) in extra { reply[key] = value } }
            try await rejectsAsync { try await adapters.prewarm() }
        }
        transport.mutation = { $0["spare"] = "bestmove e2e4" }
        try await rejectsAsync { try await adapters.prewarm() }
        transport.mutation = nil
        let spare = try await adapters.prewarm(), cancelled = try await adapters.cancelPrewarm()
        try require(spare == "starting" && cancelled)
        // Held prewarm in flight when the user confirms: the analysis supersedes it; the late prewarm
        // reply settles nothing; the analysis reply binds to the analysis request only.
        transport.automatic = false
        let prewarm = Task { @MainActor in try await adapters.prewarm() }; await settle()
        let prewarmOperation = transport.calls.last!.operation
        let analysis = Task { @MainActor in try await adapters.analyze(request, budget: .nodes(100_000)) }; await settle()
        let analysisOperation = transport.calls.last!.operation
        try require(transport.cancelled.contains(prewarmOperation) && transport.calls.last!.command["kind"] as? String == "analyze")
        try transport.finish(prewarmOperation); await settle()
        try await rejectsAsync { try await prewarm.value }
        transport.mutation = { $0["search"] = validSearch }
        try transport.finish(analysisOperation)
        let result = try await analysis.value
        try require(result.request == request && result.moveUCI == "e2e4" && adapters.lastSearch?.request == request.id)
    }
    func prewarmNeverSupersedesARealRequest() async throws {
        let transport = MockTransport(), adapters = LocalChessAdapters(transport: transport)
        transport.automatic = false
        let validation = Task { @MainActor in try await adapters.validatePosition(fen) }; await settle()
        let spare = try await adapters.prewarm(), cancelled = try await adapters.cancelPrewarm()
        try require(spare == nil && !cancelled)
        try require(transport.calls.count == 1 && transport.cancelled.isEmpty, "nothing sent, nothing cancelled")
        try transport.finish(transport.calls[0].operation)
        try require(try await validation.value.fen == fen)
    }
    func prewarmFailureLeavesAnalysisWorking() async throws {
        let transport = MockTransport(), adapters = LocalChessAdapters(transport: transport), request = fixtureRequest()
        transport.failingKinds = ["prewarm", "cancelPrewarm"]
        try await rejectsAsync { try await adapters.prewarm() }
        try await rejectsAsync { try await adapters.cancelPrewarm() }
        let result = try await adapters.analyze(request, budget: .nodes(100_000))
        try require(result.request == request && result.moveUCI == "e2e4" && transport.calls.last!.command["kind"] as? String == "analyze")
    }
}

@main @MainActor struct IntegrationCheckRunner {
    static func main() async {
        let suite = Checks()
        let tests: [(String, @MainActor () async throws -> Void)] = [
            ("dormant construction and rules/engine bindings", suite.workingRulesAndEngineBindings),
            ("complete history and FEN binding", suite.fullHistoryNeverInferred),
            ("safe JS integer identity boundaries", suite.numericIdentityBounds),
            ("foreign and malformed replies rejected", suite.foreignOrMalformedRepliesFailClosed),
            ("move echo and canonical UCI", suite.moveEchoAndCanonicalUCI),
            ("old cancellation preserves newer operation", suite.cancelledOldRequestDoesNotAbortNewer),
            ("current/pre-cancelled tasks and late replies", suite.currentCancellationAndLateReplies),
            ("invalid new request revokes old analysis", suite.invalidNewRequestRevokesOldAnalysis),
            ("synthetic unknowns remain untrusted", suite.unknownSyntheticProposalStaysUntrusted),
            ("synthetic adapter rejects DAT before inference", suite.syntheticAdapterRejectsDATBeforeInference),
            ("actual DeviceBackend JSON schema accepted", suite.actualBackendResponseSchemaAccepted),
            ("concrete wrapper cancellation is task-scoped", suite.concreteWrapperCancellationIsTaskScoped),
            ("pre-cancelled concrete wrapper preserves current", suite.preCancelledConcreteWrapperPreservesCurrent),
            ("replay adapter: tracker requests succeed through the JSON transport", suite.replayAdapterSuccess),
            ("replay adapter: foreign or error reply revokes", suite.replayAdapterForeignReplyRevokes),
            ("replay adapter: transport failure revokes", suite.replayAdapterFailureRevokes),
            ("replay adapter: cancellation is operation-scoped", suite.replayAdapterCancellationIsOperationScoped),
            ("replay adapter over concrete runtime wrapper", suite.replayAdapterOverConcreteWrapper),
            ("prewarm: node budget sent, both limits range-guarded", suite.nodeBudgetSentAndRangeGuarded),
            ("prewarm: search facts exact when present, optional for older replies", suite.searchReportExactAndOptional),
            ("prewarm: a prewarm or warm-up reply never becomes advice; held prewarm superseded by the confirmed analysis", suite.prewarmReplyNeverAdvice),
            ("prewarm: never supersedes a real request in flight", suite.prewarmNeverSupersedesARealRequest),
            ("prewarm: failure leaves normal analysis working", suite.prewarmFailureLeavesAnalysisWorking)
        ]
        var failures = 0
        for (name, test) in tests {
            do { try await test(); print("PASS: \(name)") }
            catch { failures += 1; print("FAIL: \(name): \(error)") }
        }
        print("\(tests.count - failures)/\(tests.count) native integration checks passed; mock JSON transport, no WebKit/device/audio/model inference.")
        if failures > 0 { exit(1) }
    }
}
