// Standalone Foundation-only checks. Do not compile with the WebKit harness.
import Foundation

@main private struct ComposedStudyDiagnosticsChecks {
    @MainActor static func main() throws {
        var checks = 0
        func check(_ value: @autoclosure () -> Bool) { precondition(value()); checks += 1 }
        for (stage, operation) in [(ComposedStudyDiagnostics.Stage.firstAnalysis, ComposedStudyDiagnostics.Operation.analyze),
                                   (.firstAnalysis, .legalText), (.secondAnalysis, .analyze)] {
            let log = ComposedStudyDiagnostics()
            log.enter(stage)
            let token = log.began(operation)
            log.failed(token, error: "Local engine deadline exceeded.")
            let snapshot = log.snapshot(), failure = snapshot["lastBackendError"] as! [String: Any]
            check(failure["stage"] as? String == stage.rawValue && failure["operation"] as? String == operation.rawValue)
            let counts = snapshot["operations"] as! [String: [String: Int]]
            check(counts[operation.rawValue] == ["started": 1, "completed": 0, "errors": 1])
        }
        let log = ComposedStudyDiagnostics()
        log.enter(.firstValidation)
        log.completed(log.began(.validate)); log.passed(.completeReview)
        log.enter(.secondValidation)
        log.completed(log.began(.validate)); log.passed(.completeReview)
        log.textCalled()
        log.freezeBeforeCleanup()
        log.textCancelled()
        let snapshot = log.snapshot()
        let counts = snapshot["operations"] as! [String: [String: Int]]
        check(counts["validate"] == ["started": 2, "completed": 2, "errors": 0])
        check((snapshot["completedAssertions"] as! [String: Int])["completeReview"] == 2)
        let sink = snapshot["textSink"] as! [String: Any]
        check(sink["calls"] as? Int == 1 && sink["pending"] as? Bool == true && sink["cancelCalls"] as? Int == 0)
        check(snapshot["capture"] as? String == "before-harness-cleanup")
        let events = snapshot["events"] as! [[String: Any]]
        let times = events.map { $0["elapsedMs"] as! Double }
        check(times.allSatisfy { $0.isFinite && $0 >= 0 } && zip(times, times.dropFirst()).allSatisfy { $0 <= $1 })

        let bounded = ComposedStudyDiagnostics()
        for _ in 0..<200 { bounded.enter(.firstAnalysis) }
        let token = bounded.began(.analyze)
        bounded.failed(token, error: String(repeating: "🔥", count: 1000))
        let overflow = bounded.snapshot(), failure = overflow["lastBackendError"] as! [String: Any]
        check((overflow["events"] as! [[String: Any]]).count == ComposedStudyDiagnostics.maximumEvents)
        check(overflow["droppedEvents"] as? Int == 74)
        check((failure["error"] as! String).utf8.count <= 512 && failure["operation"] as? String == "analyze")
        check((overflow["operations"] as! [String: [String: Int]])["analyze"]?["errors"] == 1)
        let encoded = try JSONSerialization.data(withJSONObject: overflow)
        check(encoded.count < 64 * 1024)
        let unicode = ComposedStudyDiagnostics()
        unicode.failed(unicode.began(.legalText), error: "a" + String(repeating: "\u{301}", count: 1000))
        let unicodeFailure = unicode.snapshot()["lastBackendError"] as! [String: Any]
        check((unicodeFailure["error"] as! String).utf8.count <= ComposedStudyDiagnostics.maximumErrorBytes)
        print("{\"passed\":true,\"checks\":\(checks),\"scope\":\"Foundation-only composed-harness diagnostics; no WebKit, AppKit, engine or audio\"}")
    }
}
