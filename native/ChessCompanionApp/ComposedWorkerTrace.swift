import Foundation
import WebKit

/// Included only in the generated Mac evaluation harness.
@MainActor final class ComposedWorkerTrace: NSObject, WKScriptMessageHandler {
    static let shared = ComposedWorkerTrace()
    private static let limit = 192
    private static let javaScriptEvents: Set<String> = [
        "jsSubmit", "analyzerEntered", "workerCreating", "workerCreated",
        "uciPostAttempt", "uciok", "isReadyPostAttempt", "readyok", "goPostAttempt",
        "goPostReturned", "goPostThrew", "firstWorkerMessageAfterGo",
        "workerMessageClassified", "workerMessageSampleLimitReached", "workerErrorAfterGo",
        "workerMessageErrorAfterGo", "searchTimerScheduled", "searchTimerFired",
        "pageTimerProbesScheduled", "pageTimer100msFired", "pageTimer1000msFired",
        "workerAbortSignal", "bestmove",
        "engineFinishEntered", "engineCompleted", "engineFailed", "jsReplyPostAttempt", "jsReplyPostReturned"
    ]
    private static let workerCategories: Set<String> = [
        "uciok", "readyok", "infoDepth", "infoString", "otherInfo", "bestmove",
        "id", "option", "empty", "otherText", "nonText"
    ]
    private static let replyErrorCodes: Set<String> = [
        "ABORTED", "TIMEOUT", "ENGINE_ERROR", "ENGINE_OUTPUT", "ENGINE_PROTOCOL",
        "INVALID_ENGINE_MOVE", "INVALID_REQUEST", "INVALID_RESULT", "INVALID_WORKER", "WORKER_REUSED",
        "INVALID_CLOCK", "INVALID_TIME", "INVALID_TIMEOUT", "CONFIRMATION_REQUIRED", "CLOSED", "RUNTIME_ERROR"
    ]
    private let started = ContinuousClock.now
    private var events: [[String: Any]] = []
    private var dropped = 0
    private var known = Set<String>()
    private var frozen: [String: Any]?

    func dispatch(_ id: String, kind: String) {
        if known.count < Self.limit { known.insert(id) }
        record("nativeDispatch", id, fields: ["requestKind": kind])
    }

    func record(_ name: String, _ id: String, fields: [String: Any] = [:]) {
        guard known.contains(id) else { return }
        guard events.count < Self.limit else { dropped += 1; return }
        let elapsed = started.duration(to: .now).components
        var event = fields
        event["event"] = name
        event["transportId"] = id
        event["nativeReceiptMs"] = Double(elapsed.seconds) * 1000 + Double(elapsed.attoseconds) / 1e15
        events.append(event)
    }

    func recordReply(_ id: String, envelope: [String: Any], matchedPending: Bool) {
        var fields: [String: Any] = ["matchedPending": matchedPending]
        if let ok = envelope["ok"] as? Bool {
            fields["ok"] = ok
            if !ok {
                let detail = envelope["error"] as? [String: Any]
                let code = detail?["code"] as? String
                fields["errorCode"] = code.map { Self.replyErrorCodes.contains($0) ? $0 : "OTHER" } ?? "MISSING"
            }
        }
        record("nativeReplyReceived", id, fields: fields)
    }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == "chessWorkerTrace", message.frameInfo.isMainFrame,
              message.frameInfo.securityOrigin.protocol == "chess-local",
              message.frameInfo.securityOrigin.host == "bundle",
              let text = message.body as? String, text.utf8.count <= 256,
              let fields = try? JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any],
              let id = fields["id"] as? String, let event = fields["event"] as? String,
              Self.javaScriptEvents.contains(event), let ms = fields["ms"] as? Double,
              ms.isFinite, ms >= 0 else { return }
        var observation: [String: Any] = ["javaScriptPerformanceMs": ms]
        if event == "workerMessageClassified" {
            guard let category = fields["category"] as? String, Self.workerCategories.contains(category) else { return }
            observation["category"] = category
        }
        record(event, id, fields: observation)
    }

    func freezeBeforeCleanup() {
        if frozen == nil { frozen = makeSnapshot(capture: "before-harness-cleanup") }
    }

    func snapshot() -> [String: Any] {
        frozen ?? makeSnapshot(capture: "at-final-report")
    }

    private func makeSnapshot(capture: String) -> [String: Any] {
        ["capture": capture, "events": events, "limit": Self.limit, "dropped": dropped]
    }
}
