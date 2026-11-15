import Foundation
#if !STANDALONE_CONTRACT_TESTS
import ChessCompanionCapture
#endif

private struct CheckFailure: Error { let message: String }
private func require(_ condition: Bool, _ message: String = "Contract check failed", line: Int = #line) throws {
    if !condition { throw CheckFailure(message: "\(message) at line \(line)") }
}
private func requireValue<T>(_ value: T?, line: Int = #line) throws -> T {
    guard let value else { throw CheckFailure(message: "Missing value at line \(line)") }; return value
}
@MainActor private func expectFailure<T>(_ expected: CaptureFailure, _ body: () throws -> T) throws {
    do { _ = try body(); throw CheckFailure(message: "Expected \(expected)") }
    catch let error as CaptureFailure { try require(error == expected, "Expected \(expected), got \(error)") }
}
@MainActor private func expectAsyncFailure<T>(_ expected: CaptureFailure, _ body: () async throws -> T) async throws {
    do { _ = try await body(); throw CheckFailure(message: "Expected \(expected)") }
    catch let error as CaptureFailure { try require(error == expected, "Expected \(expected), got \(error)") }
}

private let fixtureFEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
private let fixtureReview = FullStateReview(pieces: true, turn: true, castling: true, enPassant: true, counters: true)

private actor ControlledRecognizer: FrameRecognizer {
    var frames: [CapturedFrame] = []
    var pending: [FrameIdentity: CheckedContinuation<BoardProposal, Error>] = [:]
    func recognize(_ frame: CapturedFrame) async throws -> BoardProposal {
        frames.append(frame)
        // Deliberately ignores Task cancellation to test retained active slots and late callbacks.
        return try await withCheckedThrowingContinuation { pending[frame.identity] = $0 }
    }
    func identities() -> [FrameIdentity] { frames.map(\.identity) }
    func complete(_ identity: FrameIdentity, uncertain: Bool = false) {
        let squares = Dictionary(uniqueKeysWithValues: (1...8).flatMap { rank in "abcdefgh".map { file in
            ("\(file)\(rank)", SquarePrediction(label: uncertain ? "unknown" : "empty", confidence: uncertain ? 0 : 1))
        } })
        pending.removeValue(forKey: identity)?.resume(returning: BoardProposal(frame: identity, squares: squares))
    }
}
private actor ControlledEngine: NativeChessEngine {
    var requests: [AnalysisRequest] = []
    var pending: [UUID: CheckedContinuation<NativeEngineResult, Error>] = [:]
    func analyze(_ request: AnalysisRequest) async throws -> NativeEngineResult {
        requests.append(request)
        return try await withCheckedThrowingContinuation { pending[request.id] = $0 }
    }
    func count() -> Int { requests.count }
    func complete(_ request: AnalysisRequest, move: String = "e2e4", wrongIdentity: Bool = false) {
        let echo = wrongIdentity ? AnalysisRequest(id: UUID(), frame: request.frame, revision: request.revision, fen: request.fen, movetimeMilliseconds: request.movetimeMilliseconds) : request
        pending.removeValue(forKey: request.id)?.resume(returning: NativeEngineResult(request: echo, moveUCI: move))
    }
}
@MainActor private final class FixtureRules: LocalChessRules {
    var terminal = false
    func validatePosition(_ fullFEN: String) async throws -> ValidatedPosition {
        guard fullFEN == fixtureFEN else { throw CaptureFailure.invalidPosition }
        return ValidatedPosition(fen: fullFEN, terminal: terminal)
    }
    func speechForLegalMove(fen: String, moveUCI: String) async throws -> String {
        guard fen == fixtureFEN, moveUCI == "e2e4" else { throw CaptureFailure.invalidEngineResult }
        return "pawn from e2 to e4."
    }
}
@MainActor private final class FixtureSpeech: CancellableSpeechOutput {
    var messages: [String] = [], cancellations = 0
    var queued = false
    var delayCompletion = false
    var pending: [UUID: CheckedContinuation<Void, Error>] = [:]
    func cancel() { cancellations += 1; queued = false }
    func speak(_ text: String, permit: SpeechPermit, isCurrent: @escaping @MainActor () -> Bool) async throws {
        guard isCurrent() else { throw CaptureFailure.staleIdentity }
        messages.append(text); queued = true // Returns before simulated playback finishes.
        if delayCompletion { try await withCheckedThrowingContinuation { pending[permit.id] = $0 } }
    }
    func complete(_ permit: SpeechPermit, fail: Bool = false) {
        if fail { pending.removeValue(forKey: permit.id)?.resume(throwing: CaptureFailure.invalidEngineResult) }
        else { pending.removeValue(forKey: permit.id)?.resume() }
    }
}
@MainActor private final class FixtureClock { var time = 0.0 }
@MainActor private struct Rig {
    let recognizer = ControlledRecognizer(), engine = ControlledEngine(), rules = FixtureRules(), speech = FixtureSpeech(), clock = FixtureClock()
    let coordinator: CaptureCoordinator
    init() throws {
        coordinator = try CaptureCoordinator(recognizer: recognizer, engine: engine, rules: rules, speech: speech, clock: { [clock] in clock.time })
        coordinator.setSpeechExperimentEnabled(true)
        let epoch = try coordinator.connect(); try coordinator.cameraStarted(epoch: epoch)
    }
    func frame(_ text: String = "replay-pixels") throws -> FrameIdentity {
        try coordinator.submitReplay(bytes: Data(text.utf8), capturedAtHostSeconds: clock.time, clockDomain: coordinator.clockDomain, epoch: coordinator.epoch)
    }
    func settle() async { for _ in 0..<40 { await Task.yield() } }
    func recognized() async throws -> FrameIdentity {
        let identity = try frame(); await settle(); await recognizer.complete(identity); await settle(); return identity
    }
    func stopped() throws { let request = try coordinator.requestCameraStop(); try coordinator.acknowledgeCameraStopped(epoch: coordinator.epoch, requestID: request) }
    func reviewed() async throws { _ = try await recognized(); try stopped(); try await coordinator.confirm(fullFEN: fixtureFEN, review: fixtureReview) }
    func recommended() async throws -> AnalysisRequest {
        try await reviewed(); let request = try coordinator.analyzeReviewedPosition()
        await settle(); await engine.complete(request); await settle(); return request
    }
}

@MainActor struct CaptureCoordinatorTests {
    func immutableIdentityAndOneActiveLatestPending() async throws {
        let rig = try Rig(); defer { rig.coordinator.disconnect() }
        let first = try rig.frame("one"); await rig.settle()
        rig.clock.time = 0.1; let second = try rig.frame("two")
        rig.clock.time = 0.2; let third = try rig.frame("three")
        try require(first.sha256 == "7692c3ad3540bb803c020b3aee66cd8887123234ea0c6e7143c0add73ff431ed")
        try require(first.sequence < second.sequence && second.sequence < third.sequence)
        try require(rig.coordinator.activeRecognitionCount == 1 && rig.coordinator.pendingRecognitionCount == 1)
        try require(await rig.recognizer.identities() == [first])
        await rig.recognizer.complete(first); await rig.settle()
        try require(await rig.recognizer.identities() == [first, third])
        await rig.recognizer.complete(third); await rig.settle()
        try require(rig.coordinator.proposal?.frame == third)
        try require(rig.coordinator.recommendation == nil)
    }
    func reconnectKeepsCancelledSlotUntilSettlement() async throws {
        let rig = try Rig(); defer { rig.coordinator.disconnect() }
        let first = try rig.frame(); await rig.settle(); let oldEpoch = rig.coordinator.epoch
        rig.coordinator.reset(); let newEpoch = try rig.coordinator.connect(); try rig.coordinator.cameraStarted(epoch: newEpoch)
        rig.clock.time = 0.1; let next = try rig.frame("next-session")
        try require(newEpoch != oldEpoch); try require(rig.coordinator.activeRecognitionCount == 1)
        try require(await rig.recognizer.identities() == [first])
        await rig.recognizer.complete(first); await rig.settle()
        try require(rig.coordinator.proposal == nil)
        try require(await rig.recognizer.identities() == [first, next])
        await rig.recognizer.complete(next); await rig.settle()
        try require(rig.coordinator.proposal?.frame == next)
        try expectFailure(.staleIdentity) { try rig.coordinator.submitDAT(bytes: Data([1]), receivedAtHostSeconds: 0.2, mediaPTS: nil, epoch: oldEpoch) }
    }
    func datReceiptAndPTSDoNotAuthorizeCaptureAge() async throws {
        let rig = try Rig(); defer { rig.coordinator.disconnect() }
        let identity = try rig.coordinator.submitDAT(bytes: Data([1, 2]), receivedAtHostSeconds: 0, mediaPTS: MediaTimestamp(value: 0, timescale: 600), epoch: rig.coordinator.epoch)
        await rig.settle(); await rig.recognizer.complete(identity); await rig.settle(); try rig.stopped()
        try await rig.coordinator.confirm(fullFEN: fixtureFEN, review: fixtureReview)
        try expectFailure(.unknownCaptureAge) { try rig.coordinator.analyzeReviewedPosition() }
        try require(await rig.engine.count() == 0); try require(rig.speech.messages.isEmpty)
    }
    func explicitReviewLegalityAndMatchingStopAreRequired() async throws {
        let rig = try Rig(); defer { rig.coordinator.disconnect() }
        _ = try await rig.recognized()
        try await expectAsyncFailure(.incompleteReview) {
            try await rig.coordinator.confirm(fullFEN: fixtureFEN, review: FullStateReview(pieces: true, turn: true, castling: true, enPassant: true, counters: false))
        }
        try await rig.coordinator.confirm(fullFEN: fixtureFEN, review: fixtureReview)
        try expectFailure(.cameraNotStopped) { try rig.coordinator.analyzeReviewedPosition() }
        let stopID = try rig.coordinator.requestCameraStop()
        try expectFailure(.staleIdentity) { try rig.coordinator.acknowledgeCameraStopped(epoch: rig.coordinator.epoch, requestID: UUID()) }
        try rig.coordinator.acknowledgeCameraStopped(epoch: rig.coordinator.epoch, requestID: stopID)
        try await rig.coordinator.confirm(fullFEN: fixtureFEN, review: fixtureReview)
        rig.rules.terminal = true; try await rig.coordinator.confirm(fullFEN: fixtureFEN, review: fixtureReview)
        try expectFailure(.terminalPosition) { try rig.coordinator.analyzeReviewedPosition() }
    }
    func newUnrecognizedFrameCancelsQueuedSpeechAndReview() async throws {
        let rig = try Rig(); defer { rig.coordinator.disconnect() }
        _ = try await rig.recommended(); let permit = try requireValue(rig.coordinator.recommendation?.permit)
        try await rig.coordinator.speakRecommendation(); try require(rig.speech.queued)
        rig.clock.time = 0.1; let next = try rig.frame("new-pixels")
        try require(!rig.speech.queued && rig.coordinator.recommendation == nil)
        try require(!rig.coordinator.isCurrent(permit)); try require(rig.coordinator.cameraState == .active)
        await rig.settle(); await rig.recognizer.complete(next, uncertain: true); await rig.settle()
        try await expectAsyncFailure(.uncertainProposal) { try await rig.coordinator.confirm(fullFEN: fixtureFEN, review: fixtureReview) }
    }
    func lateEngineAndInvalidMoveNeverRestoreRecommendation() async throws {
        for mode in ["new-frame", "wrong-identity", "illegal-move"] {
            let rig = try Rig(); try await rig.reviewed()
            let request = try rig.coordinator.analyzeReviewedPosition(); await rig.settle()
            var next: FrameIdentity?
            if mode == "new-frame" { rig.clock.time = 0.1; next = try rig.frame("changed") }
            await rig.engine.complete(request, move: mode == "illegal-move" ? "e2e5" : "e2e4", wrongIdentity: mode == "wrong-identity")
            await rig.settle(); try require(rig.coordinator.recommendation == nil); try require(rig.speech.messages.isEmpty)
            if let next { await rig.recognizer.complete(next) }
            rig.coordinator.disconnect()
        }
    }
    func expiryRevokesQueuedSpeechAndLateEngineResult() async throws {
        let rig = try Rig(); defer { rig.coordinator.disconnect() }
        _ = try await rig.recommended(); try await rig.coordinator.speakRecommendation()
        let permit = try requireValue(rig.coordinator.recommendation?.permit)
        rig.clock.time = 1.01; rig.coordinator.tick()
        try require(!rig.speech.queued); try require(!rig.coordinator.isCurrent(permit)); try require(rig.coordinator.recommendation == nil)
        let other = try Rig(); defer { other.coordinator.disconnect() }; try await other.reviewed()
        let request = try other.coordinator.analyzeReviewedPosition(); await other.settle(); other.clock.time = 1.1
        await other.engine.complete(request); await other.settle(); try require(other.coordinator.recommendation == nil)
    }
    func clocksAndResetFailClosed() async throws {
        let rig = try Rig(); defer { rig.coordinator.disconnect() }
        try expectFailure(.invalidClock) {
            try rig.coordinator.submitReplay(bytes: Data([1]), capturedAtHostSeconds: 1, clockDomain: rig.coordinator.clockDomain, epoch: rig.coordinator.epoch)
        }
        try expectFailure(.invalidClock) {
            try rig.coordinator.submitReplay(bytes: Data([1]), capturedAtHostSeconds: 0, clockDomain: UUID(), epoch: rig.coordinator.epoch)
        }
        rig.clock.time = 1; rig.coordinator.tick(); rig.clock.time = 0.5; rig.coordinator.tick()
        try require(rig.coordinator.reason == "invalid-clock")
        try expectFailure(.invalidClock) { try rig.frame() }
        rig.coordinator.reset(); try require(rig.coordinator.latestFrame == nil && rig.coordinator.recommendation == nil)
        try require(!rig.coordinator.historyComplete)
    }
    func incomingInvalidFrameCannotRepublishOldProposal() async throws {
        for malformed in [false, true] {
            let rig = try Rig(); let first = try rig.frame(); await rig.settle()
            if malformed {
                rig.clock.time = 0.1
                try expectFailure(.invalidFrame) { try rig.coordinator.submitDAT(bytes: Data(), receivedAtHostSeconds: 0.1, mediaPTS: nil, epoch: rig.coordinator.epoch) }
            } else { rig.coordinator.noteIncomingFrame(epoch: rig.coordinator.epoch) }
            await rig.recognizer.complete(first); await rig.settle()
            try require(rig.coordinator.latestFrame == nil && rig.coordinator.proposal == nil)
            try require(rig.coordinator.recommendation == nil); rig.coordinator.disconnect()
        }
    }
    func lateSpeechCompletionCannotCancelNewOutput() async throws {
        let rig = try Rig(); defer { rig.coordinator.disconnect() }
        _ = try await rig.recommended(); rig.speech.delayCompletion = true
        let oldPermit = try requireValue(rig.coordinator.recommendation?.permit)
        let oldSpeech = Task { @MainActor in try await rig.coordinator.speakRecommendation() }; await rig.settle()
        let next = try rig.coordinator.analyzeReviewedPosition(); await rig.settle(); await rig.engine.complete(next); await rig.settle()
        let newPermit = try requireValue(rig.coordinator.recommendation?.permit)
        let newSpeech = Task { @MainActor in try await rig.coordinator.speakRecommendation() }; await rig.settle()
        try require(rig.speech.queued)
        let count = rig.speech.cancellations
        rig.speech.complete(oldPermit)
        try await expectAsyncFailure(.staleIdentity) { try await oldSpeech.value }
        try require(rig.speech.queued && rig.speech.cancellations == count)
        rig.speech.complete(newPermit, fail: true)
        try await expectAsyncFailure(.invalidEngineResult) { try await newSpeech.value }
        try require(!rig.speech.queued && rig.coordinator.recommendation == nil)
    }
}


@main @MainActor struct CaptureContractRunner {
    static func main() async {
        let suite = CaptureCoordinatorTests()
        let tests: [(String, @MainActor () async throws -> Void)] = [
            ("immutable identity and bounded latest queue", suite.immutableIdentityAndOneActiveLatestPending),
            ("reconnect cancellation retains active slot", suite.reconnectKeepsCancelledSlotUntilSettlement),
            ("DAT capture age stays unknown", suite.datReceiptAndPTSDoNotAuthorizeCaptureAge),
            ("full review, legality and stop acknowledgement", suite.explicitReviewLegalityAndMatchingStopAreRequired),
            ("new frame revokes queued speech", suite.newUnrecognizedFrameCancelsQueuedSpeechAndReview),
            ("late and invalid engine results", suite.lateEngineAndInvalidMoveNeverRestoreRecommendation),
            ("expiry cancels queued speech and engine", suite.expiryRevokesQueuedSpeechAndLateEngineResult),
            ("clock and reset invalidation", suite.clocksAndResetFailClosed),
            ("incoming invalid frame rejects old proposal", suite.incomingInvalidFrameCannotRepublishOldProposal),
            ("late speech completion preserves newer output", suite.lateSpeechCompletionCannotCancelNewOutput)
        ]
        var failures = 0
        for (name, test) in tests {
            do { try await test(); print("PASS: \(name)") }
            catch { failures += 1; print("FAIL: \(name): \(error)") }
        }
        print("\(tests.count - failures)/\(tests.count) native contract tests passed; mocked inputs/rules/engine, no device or audio.")
        if failures > 0 { exit(1) }
    }
}
