import Foundation

/// Evaluation-only observations. These records neither authorize output nor
/// identify a JavaScript/Worker cause from a native error message.
@MainActor final class ComposedStudyDiagnostics {
    enum Stage: String {
        case inputs, initialStart, occludedRecognition, unknownReview, positiveRecognition
        case incompleteReview, mismatchedReview, firstValidation, firstAnalysis, edit
        case secondValidation, secondAnalysis, reset, restart, recognitionAfterReset
        case thirdValidation, lateAnalysis, background, complete
    }
    enum Operation: String, CaseIterable { case start, validate, analyze, legalText }
    enum Assertion: String, CaseIterable {
        case pinnedInputs, runtimeManifest, positiveFixture, localReady, completeReview
        case unknownsPreserved, unknownReviewBlocked, exact64Cells, noInferredReview
        case incompleteReviewBlocked, mismatchedReviewBlocked, checkedOutputAvailable
        case requestIdentity, regeneratedText, noAutomaticOutput, explicitTextSink
        case analysisRequestPresent, editRevokedOutput, editBlockedOldText
        case resetRevokedOutput, resetBlockedOldText, heldReplyUnpublished, backgroundRevokedOutput
    }
    struct OperationToken {
        let operation: Operation
        let stage: Stage
        let ordinal: Int
        let startedMs: Double
    }
    private enum Event: String { case stage, backendStart, backendComplete, backendError, assertionPassed, textSinkCall, textSinkCleared }
    static let maximumEvents = 128
    static let maximumErrorBytes = 512
    private let clock = ContinuousClock()
    private let started = ContinuousClock().now
    private var stage: Stage = .inputs
    private var events: [[String: Any]] = []
    private var droppedEvents = 0
    private var starts: [Operation: Int] = [:], completions: [Operation: Int] = [:], errors: [Operation: Int] = [:]
    private var assertions: [Assertion: Int] = [:]
    private var lastBackendError: [String: Any]?
    private var sinkCalls = 0, sinkCancels = 0
    private var sinkPending = false
    private var frozen: [String: Any]?

    private func elapsed() -> Double {
        let parts = started.duration(to: clock.now).components
        return Double(parts.seconds) * 1000 + Double(parts.attoseconds) / 1e15
    }
    private func record(_ event: Event, at stage: Stage? = nil, fields: [String: Any] = [:]) {
        guard events.count < Self.maximumEvents else { droppedEvents += 1; return }
        var value = fields
        value["event"] = event.rawValue
        value["stage"] = (stage ?? self.stage).rawValue
        value["elapsedMs"] = elapsed()
        events.append(value)
    }
    func enter(_ value: Stage) { stage = value; record(.stage) }
    func passed(_ assertion: Assertion) {
        assertions[assertion, default: 0] += 1
        record(.assertionPassed, fields: ["assertion": assertion.rawValue])
    }
    func began(_ operation: Operation) -> OperationToken {
        starts[operation, default: 0] += 1
        let token = OperationToken(operation: operation, stage: stage, ordinal: starts[operation]!, startedMs: elapsed())
        record(.backendStart, at: token.stage, fields: ["operation": operation.rawValue, "ordinal": token.ordinal])
        return token
    }
    private func fields(_ token: OperationToken) -> [String: Any] {
        ["operation": token.operation.rawValue, "ordinal": token.ordinal,
         "operationElapsedMs": elapsed() - token.startedMs]
    }
    func completed(_ token: OperationToken) {
        completions[token.operation, default: 0] += 1
        record(.backendComplete, at: token.stage, fields: fields(token))
    }
    func failed(_ token: OperationToken, error: String) {
        errors[token.operation, default: 0] += 1
        var value = fields(token)
        var bounded = "", count = 0
        for scalar in error.unicodeScalars {
            let part = String(scalar), length = part.utf8.count
            if count + length > Self.maximumErrorBytes { break }
            bounded += part; count += length
        }
        value["error"] = bounded
        record(.backendError, at: token.stage, fields: value)
        value["stage"] = token.stage.rawValue
        value["elapsedMs"] = elapsed()
        lastBackendError = value
    }
    func textCalled() { sinkCalls += 1; sinkPending = true; record(.textSinkCall) }
    func textCancelled() {
        sinkCancels += 1
        let hadPending = sinkPending; sinkPending = false
        if hadPending { record(.textSinkCleared) }
    }
    /// Keep the observation at return/throw, before the harness's defer resets
    /// the model and clears pending text. Cleanup must not erase failure evidence.
    func freezeBeforeCleanup() { if frozen == nil { frozen = makeSnapshot(capture: "before-harness-cleanup") } }
    private func makeSnapshot(capture: String) -> [String: Any] {
        let operations = Dictionary(uniqueKeysWithValues: Operation.allCases.map {
            ($0.rawValue, ["started": starts[$0, default: 0], "completed": completions[$0, default: 0], "errors": errors[$0, default: 0]])
        })
        return ["schemaVersion": 1, "capture": capture, "stage": stage.rawValue, "elapsedMs": elapsed(),
                "operations": operations, "completedAssertions": Dictionary(uniqueKeysWithValues: assertions.map { ($0.key.rawValue, $0.value) }),
                "textSink": ["calls": sinkCalls, "cancelCalls": sinkCancels, "pending": sinkPending],
                "lastBackendError": lastBackendError as Any? ?? NSNull(),
                "events": events, "eventLimit": Self.maximumEvents, "droppedEvents": droppedEvents]
    }
    func snapshot() -> [String: Any] { frozen ?? makeSnapshot(capture: "at-final-report") }
}
