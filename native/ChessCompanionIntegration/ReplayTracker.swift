import Foundation

// Swift side of the frozen "Replay game" tracker contract (docs/REPLAY_GAME.md, schemaVersion 1).
// Foundation only. Builds requests for src/core/replay-runtime.js and strictly decodes its replies.
// Tracking state only: nothing here grants engine analysis, speech or guidance. Any error reply,
// malformed reply, transport failure or tracker revocation yields one outcome: revoked, and a new
// full human review (initialize) is required.

/// One synchronous-in-spirit local runtime: one request string in, one reply string out.
/// Mirrors LocalJSONTransport's style (MainActor, async, throwing) without depending on it.
@MainActor public protocol ReplayTrackerTransport: AnyObject {
    func submit(requestJSON: String, timeoutMilliseconds: Int) async throws -> String
}

public enum ReplayContractError: Error, Equatable, Sendable {
    case invalidRequest(String)
    case invalidReply(String)
}

public struct ReplaySession: Equatable, Sendable {
    public let sessionId: String
    public let epoch: UInt64
    public init(sessionId: String, epoch: UInt64) { self.sessionId = sessionId; self.epoch = epoch }
}

/// The five complete-state fields a human must have reviewed. All must be true to initialize.
public struct ReplayHumanReview: Equatable, Sendable {
    public var pieces, turn, castling, enPassant, counters: Bool
    public init(pieces: Bool, turn: Bool, castling: Bool, enPassant: Bool, counters: Bool) {
        self.pieces = pieces; self.turn = turn; self.castling = castling; self.enPassant = enPassant; self.counters = counters
    }
    var complete: Bool { pieces && turn && castling && enPassant && counters }
}

public struct ReplaySquare: Equatable, Sendable {
    public let label: String
    public let confidence: Double
    public init(label: String, confidence: Double) { self.label = label; self.confidence = confidence }
}

public struct ReplayFrame: Equatable, Sendable {
    public let session: ReplaySession
    public let sequence: UInt64
    public let frameSha256: String
    public let capturedAtMs: UInt64
    public let squares: [String: ReplaySquare]
    public init(session: ReplaySession, sequence: UInt64, frameSha256: String, capturedAtMs: UInt64, squares: [String: ReplaySquare]) {
        self.session = session; self.sequence = sequence; self.frameSha256 = frameSha256
        self.capturedAtMs = capturedAtMs; self.squares = squares
    }
}

public enum ReplayInvalidationReason: String, Sendable, CaseIterable {
    case manualEdit = "manual-edit", interrupted, background, reset, disconnect
}

public enum ReplayRequestKind: String, Sendable { case initialize, observe, invalidate, snapshot }

/// A validated request: its canonical JSON plus what the reply must echo.
public struct ReplayRequest: Sendable {
    public let requestId: String
    public let kind: ReplayRequestKind
    public let session: ReplaySession
    public let json: String
    /// For observe only: the frame a non-ignored reply must report as lastFrame.
    public let frame: ReplayLastFrame?
}

public struct ReplayLastFrame: Equatable, Sendable {
    public let session: ReplaySession
    public let sequence: UInt64
    public let frameSha256: String
    public let capturedAtMs: UInt64
}

public struct ReplayMove: Equatable, Sendable {
    public let from: String, to: String, san: String
    public let promotion: String?
}

/// Decoded, contract-checked tracker state. `trackingReady` means a stable legal position only;
/// it is never permission to advise, speak or analyze (guidance is always false by contract).
public struct ReplayTrackingState: Equatable, Sendable {
    public let requestId: String
    public let kind: ReplayRequestKind
    public let session: ReplaySession
    public let lastFrame: ReplayLastFrame?
    public let trackingReady: Bool
    public let status: String
    public let reason: String
    public let revision: UInt64
    public let fen: String?
    public let lastMove: ReplayMove?
    /// `repeated-or-reordered-frame` or `before-confirmation`: the tracker did not change.
    public let ignored: String?
}

public enum ReplayRevocationCause: Equatable, Sendable {
    case errorReply(code: String?)
    case malformedReply(String)
    case transportFailure(String)
    case requestRejected(String)
    case trackerNeedsConfirmation(reason: String)
    case invalidated(ReplayInvalidationReason)
    case concurrentRequest
    case notInitialized
}

public enum ReplayOutcome: Equatable, Sendable {
    case tracking(ReplayTrackingState)
    /// The single failure outcome: tracking revoked, renewed human review required.
    case revokedRenewedReviewRequired(ReplayRevocationCause)

    public var trackingState: ReplayTrackingState? {
        if case .tracking(let state) = self { return state }; return nil
    }
}

enum ReplayJSON {
    static let maximumSafeInteger: UInt64 = 9_007_199_254_740_991
    static let squares: [String] = (1...8).reversed().flatMap { rank in "abcdefgh".map { "\($0)\(rank)" } }
    static let labels: Set<String> = Set(["empty", "unknown"] + "PNBRQKpnbrqk".map(String.init))

    static func matches(_ value: String, _ expression: String) -> Bool {
        value.range(of: expression, options: .regularExpression) == value.startIndex..<value.endIndex
    }
    static func identifier(_ value: String) -> Bool { matches(value, "^[A-Za-z0-9_.:/-]{1,128}$") }
    static func object(_ text: String) throws -> [String: Any] {
        guard text.utf8.count <= 128 * 1024, let data = text.data(using: .utf8),
              let value = try? JSONSerialization.jsonObject(with: data), let object = value as? [String: Any] else {
            throw ReplayContractError.invalidReply("malformed JSON")
        }
        return object
    }
    static func isBool(_ value: Any?) -> Bool {
        guard let number = value as? NSNumber else { return false }
        return CFGetTypeID(number) == CFBooleanGetTypeID()
    }
    static func bool(_ value: Any?) -> Bool? { isBool(value) ? (value as? NSNumber)?.boolValue : nil }
    static func unsigned(_ value: Any?) -> UInt64? {
        guard let number = value as? NSNumber, !isBool(number) else { return nil }
        let n = number.doubleValue
        guard n.isFinite, n >= 0, n <= Double(maximumSafeInteger), n.rounded(.towardZero) == n else { return nil }
        return UInt64(n)
    }
    static func exact(_ value: [String: Any], _ keys: Set<String>) -> Bool { Set(value.keys) == keys }
    static func isNull(_ value: Any?) -> Bool { value is NSNull }
    static func fen(_ source: String) -> Bool {
        let parts = source.split(separator: " ", omittingEmptySubsequences: false).map(String.init)
        guard source.utf8.count <= 100, parts.count == 6, ["w", "b"].contains(parts[1]),
              parts[2] == "-" || matches(parts[2], "^K?Q?k?q?$") && !parts[2].isEmpty,
              parts[3] == "-" || matches(parts[3], parts[1] == "w" ? "^[a-h]6$" : "^[a-h]3$"),
              matches(parts[4], "^(0|[1-9][0-9]{0,8})$"), matches(parts[5], "^[1-9][0-9]{0,8}$") else { return false }
        let ranks = parts[0].split(separator: "/", omittingEmptySubsequences: false)
        guard ranks.count == 8 else { return false }
        for rank in ranks {
            var width = 0
            for piece in rank {
                if piece.isASCII, let digit = piece.wholeNumberValue, (1...8).contains(digit) { width += digit }
                else if "PNBRQKpnbrqk".contains(piece) { width += 1 } else { return false }
            }
            guard width == 8 else { return false }
        }
        return parts[0].filter { $0 == "K" }.count == 1 && parts[0].filter { $0 == "k" }.count == 1
    }
}

/// Builds requests the JS ReplayRuntime accepts. Throws before sending anything it would reject.
public enum ReplayRequestBuilder {
    public static let mode = "trusted-replay"
    public static let clockDomain = "replay-synthetic-v1"

    public static func initialize(requestId: String, session: ReplaySession, fen: String, review: ReplayHumanReview) throws -> ReplayRequest {
        guard review.complete else { throw ReplayContractError.invalidRequest("every complete-state field must be human-reviewed") }
        guard ReplayJSON.fen(fen) else { throw ReplayContractError.invalidRequest("complete six-field FEN required") }
        let reviewed: [String: Any] = ["pieces": true, "turn": true, "castling": true, "enPassant": true, "counters": true]
        return try make(requestId, .initialize, session, ["session": try sessionObject(session), "fen": fen, "reviewed": reviewed], frame: nil)
    }

    public static func observe(requestId: String, frame: ReplayFrame) throws -> ReplayRequest {
        guard frame.sequence <= ReplayJSON.maximumSafeInteger, frame.capturedAtMs <= ReplayJSON.maximumSafeInteger,
              ReplayJSON.matches(frame.frameSha256, "^[a-f0-9]{64}$") else { throw ReplayContractError.invalidRequest("invalid frame identity") }
        guard Set(frame.squares.keys) == Set(ReplayJSON.squares) else { throw ReplayContractError.invalidRequest("all 64 squares required") }
        var squares: [String: Any] = [:]
        for (name, square) in frame.squares {
            guard ReplayJSON.labels.contains(square.label), square.confidence.isFinite, (0...1).contains(square.confidence) else {
                throw ReplayContractError.invalidRequest("invalid square \(name)")
            }
            squares[name] = ["label": square.label, "confidence": square.confidence]
        }
        var identity = try sessionObject(frame.session)
        identity["sequence"] = NSNumber(value: frame.sequence); identity["frameSha256"] = frame.frameSha256
        let fields: [String: Any] = ["frame": ["identity": identity, "capturedAtMs": NSNumber(value: frame.capturedAtMs), "squares": squares]]
        let last = ReplayLastFrame(session: frame.session, sequence: frame.sequence, frameSha256: frame.frameSha256, capturedAtMs: frame.capturedAtMs)
        return try make(requestId, .observe, frame.session, fields, frame: last)
    }

    public static func invalidate(requestId: String, session: ReplaySession, reason: ReplayInvalidationReason) throws -> ReplayRequest {
        try make(requestId, .invalidate, session, ["session": try sessionObject(session), "reason": reason.rawValue], frame: nil)
    }

    public static func snapshot(requestId: String, session: ReplaySession) throws -> ReplayRequest {
        try make(requestId, .snapshot, session, ["session": try sessionObject(session)], frame: nil)
    }

    static func sessionObject(_ session: ReplaySession) throws -> [String: Any] {
        guard ReplayJSON.identifier(session.sessionId), session.epoch >= 1, session.epoch <= ReplayJSON.maximumSafeInteger else {
            throw ReplayContractError.invalidRequest("invalid session identity")
        }
        return ["sessionId": session.sessionId, "epoch": NSNumber(value: session.epoch)]
    }

    static func make(_ requestId: String, _ kind: ReplayRequestKind, _ session: ReplaySession, _ fields: [String: Any],
                     frame: ReplayLastFrame?) throws -> ReplayRequest {
        guard ReplayJSON.identifier(requestId) else { throw ReplayContractError.invalidRequest("invalid requestId") }
        var command = fields
        command["schemaVersion"] = 1; command["requestId"] = requestId; command["kind"] = kind.rawValue
        command["mode"] = mode; command["clockDomain"] = clockDomain
        guard JSONSerialization.isValidJSONObject(command),
              let data = try? JSONSerialization.data(withJSONObject: command, options: [.sortedKeys]),
              let text = String(data: data, encoding: .utf8), text.utf8.count <= 16_384 else {
            throw ReplayContractError.invalidRequest("request does not serialize within 16384 bytes")
        }
        return ReplayRequest(requestId: requestId, kind: kind, session: session, json: text, frame: frame)
    }
}

/// Strict reply decoder. Never returns a usable state for anything outside the success contract.
public enum ReplayReplyDecoder {
    static let successKeys: Set<String> = ["schemaVersion", "requestId", "kind", "runtime", "mode", "session", "lastFrame",
                                           "trackingReady", "guidanceAllowed", "liveGuidanceAllowed", "state"]
    static let stateKeys: Set<String> = ["status", "reason", "revision", "fen", "lastMove", "historyComplete"]
    static let statuses: Set<String> = ["disconnected", "needs-confirmation", "stabilizing", "ready"]
    static let ignoredValues: Set<String> = ["repeated-or-reordered-frame", "before-confirmation"]

    /// `activeSession` is the session the host last initialized (for initialize, the request's own).
    public static func decode(_ text: String, for request: ReplayRequest, activeSession: ReplaySession) -> ReplayOutcome {
        do {
            let state = try strictState(text, for: request, activeSession: activeSession)
            if !state.trackingReady && (state.status == "needs-confirmation" || state.status == "disconnected") {
                return .revokedRenewedReviewRequired(.trackerNeedsConfirmation(reason: state.reason))
            }
            return .tracking(state)
        } catch let ReplayContractError.invalidReply(detail) where detail.hasPrefix("error reply:") {
            return .revokedRenewedReviewRequired(.errorReply(code: String(detail.dropFirst("error reply:".count))))
        } catch let ReplayContractError.invalidReply(detail) {
            return .revokedRenewedReviewRequired(.malformedReply(detail))
        } catch {
            return .revokedRenewedReviewRequired(.malformedReply("\(error)"))
        }
    }

    static func fail(_ detail: String) -> ReplayContractError { .invalidReply(detail) }

    static func session(_ value: Any?) throws -> ReplaySession {
        guard let object = value as? [String: Any], ReplayJSON.exact(object, ["sessionId", "epoch"]),
              let id = object["sessionId"] as? String, ReplayJSON.identifier(id),
              let epoch = ReplayJSON.unsigned(object["epoch"]), epoch >= 1 else { throw fail("invalid session") }
        return ReplaySession(sessionId: id, epoch: epoch)
    }

    static func strictState(_ text: String, for request: ReplayRequest, activeSession: ReplaySession) throws -> ReplayTrackingState {
        let reply = try ReplayJSON.object(text)
        if reply["error"] != nil {
            let code = ((reply["error"] as? [String: Any])?["code"] as? String).map { String($0.prefix(64)) } ?? ""
            throw fail("error reply:\(code)")
        }
        var keys = successKeys
        if reply["ignored"] != nil { keys.insert("ignored") }
        guard ReplayJSON.exact(reply, keys) else { throw fail("unexpected or missing reply keys") }
        guard ReplayJSON.unsigned(reply["schemaVersion"]) == 1 else { throw fail("wrong schemaVersion") }
        guard reply["requestId"] as? String == request.requestId else { throw fail("requestId mismatch") }
        guard reply["kind"] as? String == request.kind.rawValue else { throw fail("kind mismatch") }
        guard reply["runtime"] as? String == "on-device-local" else { throw fail("wrong runtime") }
        guard reply["mode"] as? String == "replay-only" else { throw fail("wrong mode") }
        guard ReplayJSON.bool(reply["guidanceAllowed"]) == false, ReplayJSON.bool(reply["liveGuidanceAllowed"]) == false else {
            throw fail("guidance must be false")
        }
        let replySession = try session(reply["session"])
        guard replySession == activeSession, replySession == request.session else { throw fail("foreign session or epoch") }
        var lastFrame: ReplayLastFrame?
        if !ReplayJSON.isNull(reply["lastFrame"]) {
            guard let object = reply["lastFrame"] as? [String: Any],
                  ReplayJSON.exact(object, ["sessionId", "epoch", "sequence", "frameSha256", "capturedAtMs"]),
                  let id = object["sessionId"] as? String, let epoch = ReplayJSON.unsigned(object["epoch"]),
                  let sequence = ReplayJSON.unsigned(object["sequence"]), let sha = object["frameSha256"] as? String,
                  ReplayJSON.matches(sha, "^[a-f0-9]{64}$"), let captured = ReplayJSON.unsigned(object["capturedAtMs"]) else {
                throw fail("invalid lastFrame")
            }
            guard ReplaySession(sessionId: id, epoch: epoch) == activeSession else { throw fail("lastFrame from foreign session") }
            lastFrame = ReplayLastFrame(session: activeSession, sequence: sequence, frameSha256: sha, capturedAtMs: captured)
        }
        var ignored: String?
        if let value = reply["ignored"] {
            guard request.kind == .observe, let text = value as? String, ignoredValues.contains(text) else { throw fail("invalid ignored") }
            ignored = text
        }
        if request.kind == .observe, ignored == nil, lastFrame != request.frame { throw fail("accepted frame not echoed as lastFrame") }
        guard let trackingReady = ReplayJSON.bool(reply["trackingReady"]) else { throw fail("trackingReady must be boolean") }
        guard let state = reply["state"] as? [String: Any], ReplayJSON.exact(state, stateKeys) else { throw fail("invalid state keys") }
        guard ReplayJSON.bool(state["historyComplete"]) == false else { throw fail("historyComplete must be false") }
        guard let status = state["status"] as? String, statuses.contains(status),
              let reason = state["reason"] as? String, !reason.isEmpty, reason.utf8.count <= 64,
              let revision = ReplayJSON.unsigned(state["revision"]) else { throw fail("invalid state fields") }
        guard trackingReady == (status == "ready") else { throw fail("trackingReady disagrees with status") }
        var fen: String?
        if !ReplayJSON.isNull(state["fen"]) {
            guard let text = state["fen"] as? String, ReplayJSON.fen(text) else { throw fail("invalid fen") }
            fen = text
        }
        if trackingReady && fen == nil { throw fail("ready without a position") }
        var lastMove: ReplayMove?
        if !ReplayJSON.isNull(state["lastMove"]) {
            guard let move = state["lastMove"] as? [String: Any],
                  ReplayJSON.exact(move, ["from", "to", "san"]) || ReplayJSON.exact(move, ["from", "to", "san", "promotion"]),
                  let from = move["from"] as? String, let to = move["to"] as? String, from != to,
                  ReplayJSON.matches(from, "^[a-h][1-8]$"), ReplayJSON.matches(to, "^[a-h][1-8]$"),
                  let san = move["san"] as? String, !san.isEmpty, san.utf8.count <= 16 else { throw fail("invalid lastMove") }
            var promotion: String?
            if let value = move["promotion"] {
                guard let text = value as? String, ReplayJSON.matches(text, "^[qrbn]$") else { throw fail("invalid promotion") }
                promotion = text
            }
            lastMove = ReplayMove(from: from, to: to, san: san, promotion: promotion)
        }
        return ReplayTrackingState(requestId: request.requestId, kind: request.kind, session: replySession, lastFrame: lastFrame,
                                   trackingReady: trackingReady, status: status, reason: reason, revision: revision,
                                   fen: fen, lastMove: lastMove, ignored: ignored)
    }
}

/// Host-side tracker client. One request at a time; after any revocation it refuses everything
/// except a new human-reviewed initialize, without contacting the runtime.
@MainActor public final class ReplayTracker {
    private let transport: any ReplayTrackerTransport
    private let requestIdPrefix: String
    private let timeoutMilliseconds: Int
    private var counter: UInt64 = 0
    private var active: ReplaySession?
    private var usable = false
    private var inFlight = false
    private var generation: UInt64 = 0

    public init(transport: any ReplayTrackerTransport, requestIdPrefix: String = "replay-", timeoutMilliseconds: Int = 2_000) {
        self.transport = transport; self.requestIdPrefix = requestIdPrefix; self.timeoutMilliseconds = timeoutMilliseconds
    }

    public var activeSession: ReplaySession? { active }
    public var isTrackingUsable: Bool { usable }

    public func initialize(session: ReplaySession, fen: String, review: ReplayHumanReview) async -> ReplayOutcome {
        _ = revoke(.notInitialized)
        return await perform(activeSession: session) { try ReplayRequestBuilder.initialize(requestId: $0, session: session, fen: fen, review: review) }
    }

    public func observe(_ frame: ReplayFrame) async -> ReplayOutcome {
        guard usable, let active else { return .revokedRenewedReviewRequired(.notInitialized) }
        guard frame.session == active else { return revoke(.requestRejected("frame names a foreign session")) }
        return await perform(activeSession: active) { try ReplayRequestBuilder.observe(requestId: $0, frame: frame) }
    }

    public func snapshot() async -> ReplayOutcome {
        guard usable, let active else { return .revokedRenewedReviewRequired(.notInitialized) }
        return await perform(activeSession: active) { try ReplayRequestBuilder.snapshot(requestId: $0, session: active) }
    }

    /// Deliberate revocation. The tracker is told when possible; the outcome is always revoked.
    public func invalidate(reason: ReplayInvalidationReason) async -> ReplayOutcome {
        let wasUsable = usable
        _ = revoke(.invalidated(reason))
        if wasUsable, let active {
            _ = await perform(activeSession: active) { try ReplayRequestBuilder.invalidate(requestId: $0, session: active, reason: reason) }
            _ = revoke(.invalidated(reason))
        }
        return .revokedRenewedReviewRequired(.invalidated(reason))
    }

    private func revoke(_ cause: ReplayRevocationCause) -> ReplayOutcome {
        usable = false; generation &+= 1
        return .revokedRenewedReviewRequired(cause)
    }

    private func perform(activeSession: ReplaySession, _ build: (String) throws -> ReplayRequest) async -> ReplayOutcome {
        guard !inFlight else { return revoke(.concurrentRequest) }
        counter += 1
        let request: ReplayRequest
        do { request = try build(requestIdPrefix + String(counter)) } catch { return revoke(.requestRejected("\(error)")) }
        inFlight = true
        defer { inFlight = false }
        let started = generation
        let reply: String
        do { reply = try await transport.submit(requestJSON: request.json, timeoutMilliseconds: timeoutMilliseconds) }
        catch { return revoke(.transportFailure("\(type(of: error))")) }
        guard started == generation else { return revoke(.concurrentRequest) }
        let outcome = ReplayReplyDecoder.decode(reply, for: request, activeSession: activeSession)
        guard case .tracking = outcome else { return revoke(outcomeCause(outcome)) }
        if request.kind == .initialize { active = activeSession }
        usable = true
        return outcome
    }

    private func outcomeCause(_ outcome: ReplayOutcome) -> ReplayRevocationCause {
        if case .revokedRenewedReviewRequired(let cause) = outcome { return cause }
        return .malformedReply("unknown")
    }
}
