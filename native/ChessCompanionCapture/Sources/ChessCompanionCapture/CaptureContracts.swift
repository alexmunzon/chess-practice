import Foundation
import CryptoKit

public enum CaptureFailure: Error, Equatable {
    case disconnected, invalidFrame, invalidClock, staleIdentity, unknownCaptureAge
    case uncertainProposal, incompleteReview, invalidPosition, terminalPosition
    case cameraNotStopped, speechExperimentDisabled, noRecommendation, invalidEngineResult
}

public struct FrameIdentity: Hashable, Sendable {
    public let sessionID: UUID
    public let epoch: UInt64
    public let sequence: UInt64
    public let sha256: String
}

/// Media PTS remains in the media clock domain. It is never a host-clock timestamp.
public struct MediaTimestamp: Sendable, Equatable {
    public let value: Int64
    public let timescale: Int32
    public init(value: Int64, timescale: Int32) { self.value = value; self.timescale = timescale }
}

public enum CaptureTime: Sendable, Equatable {
    case unknownDAT(mediaPTS: MediaTimestamp?)
    /// Only prerecorded tests may use this case. No DAT-to-host mapping is implemented.
    case trustedReplay(hostSeconds: Double, clockDomain: UUID)
}

public struct CapturedFrame: Sendable {
    public let identity: FrameIdentity
    public let bytes: Data
    public let receivedAtHostSeconds: Double
    public let captureTime: CaptureTime
    init(sessionID: UUID, epoch: UInt64, sequence: UInt64, bytes: Data, receivedAt: Double, captureTime: CaptureTime) {
        self.bytes = Data(bytes)
        self.identity = FrameIdentity(sessionID: sessionID, epoch: epoch, sequence: sequence,
                                      sha256: SHA256.hash(data: self.bytes).map { String(format: "%02x", $0) }.joined())
        self.receivedAtHostSeconds = receivedAt
        self.captureTime = captureTime
    }
}

public struct SquarePrediction: Sendable {
    public let label: String
    public let confidence: Double
    public init(label: String, confidence: Double) { self.label = label; self.confidence = confidence }
}

/// Untrusted piece observations contain neither FEN nor historical state/review flags.
public struct BoardProposal: Sendable {
    public let frame: FrameIdentity
    public let squares: [String: SquarePrediction]
    public init(frame: FrameIdentity, squares: [String: SquarePrediction]) { self.frame = frame; self.squares = squares }
    var isComplete: Bool {
        let keys = Set((1...8).flatMap { rank in "abcdefgh".map { "\($0)\(rank)" } })
        let labels = Set(["empty"] + "PNBRQKpnbrqk".map(String.init))
        return Set(squares.keys) == keys && squares.values.allSatisfy {
            labels.contains($0.label) && $0.confidence.isFinite && $0.confidence >= 0.95 && $0.confidence <= 1
        }
    }
}

public struct FullStateReview: Sendable {
    public let pieces, turn, castling, enPassant, counters: Bool
    public init(pieces: Bool, turn: Bool, castling: Bool, enPassant: Bool, counters: Bool) {
        self.pieces = pieces; self.turn = turn; self.castling = castling; self.enPassant = enPassant; self.counters = counters
    }
    var complete: Bool { pieces && turn && castling && enPassant && counters }
}

public struct ValidatedPosition: Sendable {
    public let fen: String
    public let terminal: Bool
    public init(fen: String, terminal: Bool) { self.fen = fen; self.terminal = terminal }
}

public struct AnalysisRequest: Sendable, Equatable {
    public let id: UUID
    public let frame: FrameIdentity
    public let revision: UInt64
    public let fen: String
    public let movetimeMilliseconds: Int
    public init(id: UUID, frame: FrameIdentity, revision: UInt64, fen: String, movetimeMilliseconds: Int) {
        self.id = id; self.frame = frame; self.revision = revision; self.fen = fen; self.movetimeMilliseconds = movetimeMilliseconds
    }
}

public struct NativeEngineResult: Sendable {
    public let request: AnalysisRequest
    public let moveUCI: String
    public init(request: AnalysisRequest, moveUCI: String) { self.request = request; self.moveUCI = moveUCI }
}

public struct SpeechPermit: Sendable, Equatable {
    public let id: UUID
    public let request: AnalysisRequest
    public let expiresAtHostSeconds: Double
}

public struct Recommendation: Sendable {
    public let permit: SpeechPermit
    public let text: String
}

public protocol FrameRecognizer: Sendable {
    func recognize(_ frame: CapturedFrame) async throws -> BoardProposal
}
public protocol NativeChessEngine: Sendable {
    func analyze(_ request: AnalysisRequest) async throws -> NativeEngineResult
}

/// Implement with actual on-phone chess rules; there is no default permissive implementation.
@MainActor public protocol LocalChessRules: AnyObject {
    func validatePosition(_ fullFEN: String) async throws -> ValidatedPosition
    /// Must verify legality and derive speech from that legal move, never trust engine text.
    func speechForLegalMove(fen: String, moveUCI: String) async throws -> String
}

/// cancel() must synchronously stop queued and playing output. speak may return after enqueueing.
@MainActor public protocol CancellableSpeechOutput: AnyObject {
    func cancel()
    func speak(_ text: String, permit: SpeechPermit, isCurrent: @escaping @MainActor () -> Bool) async throws
}
