import Foundation
import CoreFoundation
#if !COMPANION_MONOLITHIC_BUILD
import ChessCompanionCapture
import ChessCompanionVision
#endif

public enum IntegrationFailure: Error, Equatable {
    case malformedJSON, invalidIdentity, unsafeInteger, invalidFEN, invalidMove, invalidReply
    case cancelled, syntheticReplayOnly, invalidSyntheticProposal
}

/// One local runtime, with cancellation scoped to a unique operation rather than caller text IDs.
@MainActor public protocol LocalJSONTransport: AnyObject {
    func submit(commandJSON: String, operation: UUID, timeoutMilliseconds: Int) async throws -> String
    func cancel(operation: UUID)
}

enum JSONContract {
    static let maximumSafeInteger: UInt64 = 9_007_199_254_740_991
    static func object(_ text: String) throws -> [String: Any] {
        guard text.utf8.count <= 128 * 1024, let data = text.data(using: .utf8),
              let value = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { throw IntegrationFailure.malformedJSON }
        return value
    }
    static func keys(_ value: [String: Any], _ expected: Set<String>) -> Bool { Set(value.keys) == expected }
    static func bool(_ value: Any?) -> Bool? {
        guard let number = value as? NSNumber, CFGetTypeID(number) == CFBooleanGetTypeID() else { return nil }
        return number.boolValue
    }
    static func number(_ value: Any?) -> Double? {
        guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(), number.doubleValue.isFinite else { return nil }
        return number.doubleValue
    }
    static func unsigned(_ value: Any?) -> UInt64? {
        guard let n = number(value), n >= 0, n <= Double(maximumSafeInteger), n.rounded(.towardZero) == n else { return nil }
        return UInt64(n)
    }
    static func safe(_ value: UInt64, minimum: UInt64 = 0) throws -> UInt64 {
        guard value >= minimum, value <= maximumSafeInteger else { throw IntegrationFailure.unsafeInteger }; return value
    }
    static func matches(_ value: String, _ expression: String) -> Bool {
        value.range(of: expression, options: .regularExpression) == value.startIndex..<value.endIndex
    }
    static func fullFEN(_ source: String) throws -> String {
        guard source.utf8.count <= 200 else { throw IntegrationFailure.invalidFEN }
        let parts = source.split(whereSeparator: \.isWhitespace).map(String.init)
        guard parts.count == 6, ["w", "b"].contains(parts[1]),
              matches(parts[2], "^(?:K?Q?k?q?|-)$"), !parts[2].isEmpty,
              parts[3] == "-" || matches(parts[3], parts[1] == "w" ? "^[a-h]6$" : "^[a-h]3$"),
              matches(parts[4], "^(?:0|[1-9][0-9]*)$"), matches(parts[5], "^[1-9][0-9]*$"),
              let half = UInt64(parts[4]), let full = UInt64(parts[5]), half <= maximumSafeInteger, full <= maximumSafeInteger else { throw IntegrationFailure.invalidFEN }
        let ranks = parts[0].split(separator: "/", omittingEmptySubsequences: false)
        guard ranks.count == 8 else { throw IntegrationFailure.invalidFEN }
        for rank in ranks {
            var width = 0
            for piece in rank {
                if let digit = piece.wholeNumberValue, (1...8).contains(digit), piece.isASCII { width += digit }
                else if "PNBRQKpnbrqk".contains(piece) { width += 1 }
                else { throw IntegrationFailure.invalidFEN }
            }
            guard width == 8 else { throw IntegrationFailure.invalidFEN }
        }
        guard parts[0].filter({ $0 == "K" }).count == 1, parts[0].filter({ $0 == "k" }).count == 1 else { throw IntegrationFailure.invalidFEN }
        return parts.joined(separator: " ")
    }
    static func uci(_ source: String) throws -> [String: Any] {
        guard matches(source, "^[a-h][1-8][a-h][1-8][qrbn]?$") else { throw IntegrationFailure.invalidMove }
        let letters = Array(source), from = String(letters[0...1]), to = String(letters[2...3])
        guard from != to else { throw IntegrationFailure.invalidMove }
        var value: [String: Any] = ["from": from, "to": to]
        if letters.count == 5 { value["promotion"] = String(letters[4]) }; return value
    }
    static func move(_ value: Any?, includesSAN: Bool) throws -> String {
        guard let object = value as? [String: Any], let from = object["from"] as? String, let to = object["to"] as? String,
              matches(from, "^[a-h][1-8]$"), matches(to, "^[a-h][1-8]$") else { throw IntegrationFailure.invalidMove }
        var fields: Set<String> = ["from", "to"]
        if includesSAN {
            fields.insert("san")
            guard let san = object["san"] as? String, !san.isEmpty, san.utf8.count <= 32 else { throw IntegrationFailure.invalidMove }
        }
        var suffix = ""
        if let promotion = object["promotion"] { fields.insert("promotion"); guard let text = promotion as? String, matches(text, "^[qrbn]$") else { throw IntegrationFailure.invalidMove }; suffix = text }
        guard keys(object, fields) else { throw IntegrationFailure.invalidMove }
        let result = from + to + suffix; _ = try uci(result); return result
    }
    static func identity(_ request: AnalysisRequest) throws -> [String: Any] {
        guard matches(request.frame.sha256, "^[a-f0-9]{64}$") else { throw IntegrationFailure.invalidIdentity }
        return ["sessionId": request.frame.sessionID.uuidString, "epoch": try safe(request.frame.epoch, minimum: 1),
                "sequence": try safe(request.frame.sequence), "frameSha256": request.frame.sha256, "revision": try safe(request.revision, minimum: 1)]
    }
    static func checkIdentity(_ value: Any?, request: AnalysisRequest) throws {
        guard let value = value as? [String: Any], keys(value, ["sessionId", "epoch", "sequence", "frameSha256", "revision"]),
              value["sessionId"] as? String == request.frame.sessionID.uuidString, value["frameSha256"] as? String == request.frame.sha256,
              unsigned(value["epoch"]) == request.frame.epoch, unsigned(value["sequence"]) == request.frame.sequence,
              unsigned(value["revision"]) == request.revision else { throw IntegrationFailure.invalidIdentity }
    }
    static func position(_ value: Any?, matching fen: String? = nil) throws -> ValidatedPosition {
        guard let object = value as? [String: Any], let source = object["fen"] as? String,
              let terminal = bool(object["gameOver"]), bool(object["historyAvailable"]) == false else { throw IntegrationFailure.invalidReply }
        let normalized = try fullFEN(source)
        guard normalized == source, fen == nil || normalized == fen else { throw IntegrationFailure.invalidReply }
        return ValidatedPosition(fen: normalized, terminal: terminal)
    }
    static func speech(_ value: Any?) throws -> String {
        guard let text = value as? String, !text.isEmpty, text.utf8.count <= 512,
              text.unicodeScalars.allSatisfy({ !CharacterSet.controlCharacters.contains($0) }) else { throw IntegrationFailure.invalidReply }
        return text
    }
}

/// The search limit sent with an analysis: wall-clock time (50-3000 ms) or a node budget (1,000-2,000,000).
public enum SearchBudget: Equatable, Sendable {
    case movetime(milliseconds: Int)
    case nodes(Int)
    var valid: Bool {
        switch self {
        case .movetime(let milliseconds): return (50...3000).contains(milliseconds)
        case .nodes(let count): return (1_000...2_000_000).contains(count)
        }
    }
}

/// Diagnostic facts about one search, reported by the local runtime with an analysis reply. They are
/// never used to decide advice; the reply's move is checked exactly as before.
public struct SearchReport: Equatable, Sendable {
    public let nodes: UInt64?
    public let nodesPerSecond: UInt64?
    public let elapsedMilliseconds: Double?
    public let spareUsed: Bool
    /// "fresh", "spare" or "fallback" (spare unusable, fresh engine started instead).
    public let startup: String?
    public let startupMilliseconds: Double?
    public let fallbackReason: String?
    static let keys: Set<String> = ["nodes", "nps", "elapsedMs", "spareUsed", "startup", "startupMs", "fallbackReason"]
    static func parse(_ value: Any?) throws -> SearchReport {
        guard let object = value as? [String: Any], JSONContract.keys(object, keys),
              let spareUsed = JSONContract.bool(object["spareUsed"]) else { throw IntegrationFailure.invalidReply }
        func count(_ key: String) throws -> UInt64? {
            if object[key] is NSNull { return nil }
            guard let value = JSONContract.unsigned(object[key]) else { throw IntegrationFailure.invalidReply }; return value
        }
        func milliseconds(_ key: String) throws -> Double? {
            if object[key] is NSNull { return nil }
            guard let value = JSONContract.number(object[key]), value >= 0, value <= 600_000 else { throw IntegrationFailure.invalidReply }; return value
        }
        func text(_ key: String, _ pattern: String) throws -> String? {
            if object[key] is NSNull { return nil }
            guard let value = object[key] as? String, JSONContract.matches(value, pattern) else { throw IntegrationFailure.invalidReply }; return value
        }
        let startup = try text("startup", "^(fresh|spare|fallback)$")
        guard !spareUsed || startup == "spare" else { throw IntegrationFailure.invalidReply }
        return SearchReport(nodes: try count("nodes"), nodesPerSecond: try count("nps"), elapsedMilliseconds: try milliseconds("elapsedMs"),
                            spareUsed: spareUsed, startup: startup, startupMilliseconds: try milliseconds("startupMs"),
                            fallbackReason: try text("fallbackReason", "^[a-z-]{1,40}$"))
    }
}

/// Shared phone-local rules/engine adapter. Construction does not start any runtime.
@MainActor public final class LocalChessAdapters: LocalChessRules, NativeChessEngine {
    private let transport: any LocalJSONTransport
    private var current: UUID?
    /// Search facts of the most recent successful analysis, keyed by its request ID (nil if the runtime sent none).
    public private(set) var lastSearch: (request: UUID, report: SearchReport?)?
    public init(transport: any LocalJSONTransport) { self.transport = transport }
    public func cancel() {
        let previous = current; current = nil
        if let previous { transport.cancel(operation: previous) }
    }
    private func revokeBeforeValidation() throws {
        // An already-cancelled old Task must not revoke a newer request.
        try Task.checkCancellation(); cancel()
    }
    private func send(kind: String, fields: [String: Any], timeout: Int, requestID: String? = nil) async throws -> [String: Any] {
        try Task.checkCancellation()
        let operation = UUID(), previous = current
        current = operation
        if let previous { transport.cancel(operation: previous) }
        let requestedID = requestID ?? operation.uuidString
        var command = fields
        command["schemaVersion"] = 1; command["requestId"] = requestedID; command["kind"] = kind
        guard JSONSerialization.isValidJSONObject(command), let text = String(data: try JSONSerialization.data(withJSONObject: command, options: [.sortedKeys]), encoding: .utf8), text.utf8.count <= 16_384 else { throw IntegrationFailure.malformedJSON }
        return try await withTaskCancellationHandler {
            defer { if current == operation { current = nil } }
            try Task.checkCancellation()
            guard current == operation else { throw IntegrationFailure.cancelled }
            let reply = try await transport.submit(commandJSON: text, operation: operation, timeoutMilliseconds: timeout)
            try Task.checkCancellation()
            guard current == operation else { throw IntegrationFailure.cancelled }
            let result = try JSONContract.object(reply)
            var extra: Set<String>
            switch kind {
            case "position": extra = ["position"]
            case "move": extra = ["fen", "move", "position", "speechText"]
            // `search` (diagnostic facts) is sent by the current runtime; recorded older backends omit it.
            case "analyze": extra = ["identity", "fen", "bestMove", "speechText", "status"]; if result["search"] != nil { extra.insert("search") }
            case "prewarm": extra = ["spare"]
            case "cancelPrewarm": extra = ["cancelled"]
            default: throw IntegrationFailure.invalidReply
            }
            guard JSONContract.keys(result, extra.union(["schemaVersion", "requestId", "kind", "runtime"])),
                  JSONContract.unsigned(result["schemaVersion"]) == 1, result["requestId"] as? String == requestedID,
                  result["kind"] as? String == kind, result["runtime"] as? String == "on-device-local" else { throw IntegrationFailure.invalidReply }
            return result
        } onCancel: {
            Task { @MainActor [weak self] in
                guard let self, self.current == operation else { return }
                self.current = nil; self.transport.cancel(operation: operation)
            }
        }
    }
    public func validatePosition(_ fullFEN: String) async throws -> ValidatedPosition {
        try revokeBeforeValidation()
        let fen = try JSONContract.fullFEN(fullFEN)
        let reply = try await send(kind: "position", fields: ["fen": fen], timeout: 5_000)
        return try JSONContract.position(reply["position"], matching: fen)
    }
    public func speechForLegalMove(fen source: String, moveUCI: String) async throws -> String {
        try revokeBeforeValidation()
        let fen = try JSONContract.fullFEN(source), move = try JSONContract.uci(moveUCI)
        let reply = try await send(kind: "move", fields: ["fen": fen, "move": move], timeout: 5_000)
        guard reply["fen"] as? String == fen, try JSONContract.move(reply["move"], includesSAN: false) == moveUCI else { throw IntegrationFailure.invalidReply }
        _ = try JSONContract.position(reply["position"])
        return try JSONContract.speech(reply["speechText"])
    }
    /// Searches for the request's own time limit (unchanged behaviour).
    public func analyze(_ request: AnalysisRequest) async throws -> NativeEngineResult {
        try await analyze(request, budget: .movetime(milliseconds: request.movetimeMilliseconds))
    }
    /// Searches with an explicit limit. With a node budget the request's movetimeMilliseconds is not sent;
    /// the runtime then bounds the search by its own wall-clock deadline.
    public func analyze(_ request: AnalysisRequest, budget: SearchBudget) async throws -> NativeEngineResult {
        try revokeBeforeValidation()
        let fen = try JSONContract.fullFEN(request.fen)
        guard fen == request.fen, budget.valid else { throw IntegrationFailure.invalidFEN }
        let identity = try JSONContract.identity(request)
        var fields: [String: Any] = ["fen": fen, "confirmation": true, "identity": identity]
        switch budget {
        case .movetime(let milliseconds): fields["movetimeMs"] = milliseconds
        case .nodes(let count): fields["nodes"] = count
        }
        let reply = try await send(kind: "analyze", fields: fields, timeout: 15_000, requestID: request.id.uuidString)
        try JSONContract.checkIdentity(reply["identity"], request: request)
        guard reply["fen"] as? String == fen, let status = reply["status"] as? String,
              ["playing", "check", "fifty-move-claim-available"].contains(status) else { throw IntegrationFailure.invalidReply }
        let move = try JSONContract.move(reply["bestMove"], includesSAN: true)
        _ = try JSONContract.speech(reply["speechText"])
        let report = reply["search"] == nil ? nil : try SearchReport.parse(reply["search"])
        lastSearch = (request.id, report)
        // Coordinator separately asks the rules adapter to verify this UCI and regenerate speech.
        return NativeEngineResult(request: request, moveUCI: move)
    }
    /// Asks the runtime to start (or keep) its one spare engine. Returns its state ("starting", "ready",
    /// "none"), or nil without sending anything while another request of this adapter is in flight: a
    /// prewarm never supersedes a real request. Any later request supersedes the prewarm. The reply
    /// carries no position, move or text and is never turned into a result.
    public func prewarm() async throws -> String? {
        guard current == nil else { return nil }
        let reply = try await send(kind: "prewarm", fields: [:], timeout: 5_000)
        guard let spare = reply["spare"] as? String, ["starting", "ready", "none"].contains(spare) else { throw IntegrationFailure.invalidReply }
        return spare
    }
    /// Discards a spare engine that no analysis has taken. Like prewarm, it never supersedes a real request.
    @discardableResult public func cancelPrewarm() async throws -> Bool {
        guard current == nil else { return false }
        let reply = try await send(kind: "cancelPrewarm", fields: [:], timeout: 5_000)
        guard JSONContract.bool(reply["cancelled"]) == true else { throw IntegrationFailure.invalidReply }
        return true
    }
}

/// Explicitly synthetic: never attach this adapter to physical DAT capture.
public actor SyntheticFrameRecognizer: FrameRecognizer {
    public static let evidenceScope = "synthetic-marker-equipped-replay-only"
    private let recognizer: NativeSyntheticRecognizer
    public init(templateData: Data) throws { recognizer = try NativeSyntheticRecognizer(templateData: templateData) }
    public func recognize(_ frame: CapturedFrame) async throws -> BoardProposal {
        try Task.checkCancellation()
        guard case .trustedReplay = frame.captureTime else { throw IntegrationFailure.syntheticReplayOnly }
        guard NativeSyntheticRecognizer.sha256(frame.bytes) == frame.identity.sha256 else { throw IntegrationFailure.invalidIdentity }
        // Only image bytes enter the model. Frame identity and timing are not model inputs.
        let result = try recognizer.recognize(imageData: frame.bytes)
        try Task.checkCancellation()
        return try Self.proposal(result, frame: frame)
    }
    static func proposal(_ result: [String: Any], frame: CapturedFrame) throws -> BoardProposal {
        guard JSONContract.unsigned(result["schemaVersion"]) == 1,
              result["source"] as? String == "synthetic-pixel-inference", result["model"] as? String == "synthetic-screen-template-v1",
              result["pipelineVersion"] as? String == "native-visible-markers-v1",
              result["nativeImplementationVersion"] as? String == NativeSyntheticRecognizer.implementationVersion,
              result["templateFeaturesSha256"] as? String == NativeSyntheticRecognizer.expectedFeatureHash,
              result["sourceSha256"] as? String == frame.identity.sha256, result["status"] as? String == "needs-human-review",
              result["fen"] is NSNull, JSONContract.bool(result["guidanceAllowed"]) == false, JSONContract.number(result["threshold"]) == 0.95,
              let raw = result["squares"] as? [String: [String: Any]] else { throw IntegrationFailure.invalidSyntheticProposal }
        let expected = Set((1...8).flatMap { rank in "abcdefgh".map { "\($0)\(rank)" } })
        guard Set(raw.keys) == expected else { throw IntegrationFailure.invalidSyntheticProposal }
        var squares: [String: SquarePrediction] = [:]
        for (square, cell) in raw {
            guard let label = cell["label"] as? String, let rawLabel = cell["rawLabel"] as? String,
                  JSONContract.matches(rawLabel, "^[.PNBRQKpnbrqk]$"), let confidence = JSONContract.number(cell["confidence"]),
                  confidence == 0 || confidence == 1, let available = JSONContract.bool(cell["rawLabelAvailable"]),
                  label == (confidence == 1 ? (rawLabel == "." ? "empty" : rawLabel) : "unknown"), available || confidence == 0 else { throw IntegrationFailure.invalidSyntheticProposal }
            squares[square] = SquarePrediction(label: label, confidence: confidence)
        }
        return BoardProposal(frame: frame.identity, squares: squares)
    }
}

/// Merely creates adapters. The host still explicitly owns runtime start, review, capture and speech.
@MainActor public struct SyntheticPhoneServices {
    public let recognizer: SyntheticFrameRecognizer
    public let chess: LocalChessAdapters
    public init(templateData: Data, transport: any LocalJSONTransport) throws {
        recognizer = try SyntheticFrameRecognizer(templateData: templateData)
        chess = LocalChessAdapters(transport: transport)
    }
}
