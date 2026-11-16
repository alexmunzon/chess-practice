import Foundation
import Combine

/// Offline study has no capture timestamp or live output permit. The reviewed
/// image can be old; its exact bytes and every supplied FEN field stay visible.
struct OfflineBoard: Sendable {
    let sha256: String
    let squares: [String: String]
    var complete: Bool {
        let expected = Set((1...8).flatMap { r in "abcdefgh".map { "\($0)\(r)" } })
        let allowed = Set(["empty"] + "PNBRQKpnbrqk".map(String.init))
        return Set(squares.keys) == expected && squares.values.allSatisfy(allowed.contains)
    }
    func matchesPlacement(_ fullFEN: String) -> Bool {
        guard complete else { return false }
        let fields = fullFEN.split(whereSeparator: \.isWhitespace)
        guard fields.count == 6 else { return false }
        let ranks = fields[0].split(separator: "/", omittingEmptySubsequences: false)
        guard ranks.count == 8 else { return false }
        for (row, rank) in ranks.enumerated() {
            var cells: [String] = []
            for piece in rank {
                if let n = piece.wholeNumberValue, piece.isASCII, (1...8).contains(n) { cells += Array(repeating: "empty", count: n) }
                else if "PNBRQKpnbrqk".contains(piece) { cells.append(String(piece)) }
                else { return false }
            }
            guard cells.count == 8 else { return false }
            for (column, file) in "abcdefgh".enumerated() where squares["\(file)\(8-row)"] != cells[column] { return false }
        }
        return true
    }
}

enum StudyFixture: String, CaseIterable, Identifiable {
    case starting, afterE4, enPassant, promotion, occluded
    var id: Self { self }
    var asset: String {
        self == .starting ? "synthetic-fixture.png" : "Study/\(rawValue).png"
    }
    var title: String {
        switch self {
        case .starting: "Starting position"
        case .afterE4: "After 1. e4"
        case .enPassant: "En passant"
        case .promotion: "Promotion"
        case .occluded: "Obstructed board"
        }
    }
    // The corpus reference is separate from the pixels and enters the editable
    // FEN only on request. Every review checkbox still starts unchecked.
    var referenceFEN: String? {
        switch self {
        case .starting: "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        case .afterE4: "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
        case .enPassant: "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2"
        case .promotion: "4k3/P7/8/8/8/8/8/4K3 w - - 0 1"
        case .occluded: nil
        }
    }
}

enum OfflineStudyError: Error { case missingResource, invalidImage, incompleteReview, mismatchedPieces, terminal, unavailableVoice }
protocol OfflineImageRecognizer: Sendable { func recognize(_ bytes: Data) async throws -> OfflineBoard }
@MainActor protocol OfflineBackend: AnyObject {
    func start() async throws
    func validate(_ fen: String) async throws -> ValidatedPosition
    func analyze(_ request: AnalysisRequest) async throws -> NativeEngineResult
    func speech(fen: String, move: String) async throws -> String
    func cancel()
    func close()
    /// Called at most once when the runtime stops by itself (WebKit process death,
    /// startup failure, fatal reply). The model then stops showing the engine as ready.
    func observeClosure(_ handler: @escaping @MainActor () -> Void)
    /// Best effort: start one spare engine now so the next analysis need not start its own. Produces
    /// no result. The model ignores its outcome: a failure only means the next analysis starts a
    /// fresh engine, as before.
    func prewarm() async throws
    /// Best effort: discard a spare engine that no analysis has taken.
    func cancelPrewarm() async throws
}
extension OfflineBackend {
    /// Backends without a closure signal keep the previous behaviour.
    func observeClosure(_ handler: @escaping @MainActor () -> Void) {}
    /// Backends without a spare engine keep the previous behaviour.
    func prewarm() async throws {}
    func cancelPrewarm() async throws {}
}
@MainActor protocol OfflineSpeech: AnyObject { func speak(_ text: String) throws; func cancel() }

enum ReviewField: String, CaseIterable, Identifiable {
    case pieces, turn, castling, enPassant, counters
    var id: String { rawValue }
    var title: String {
        switch self {
        case .pieces: return "I checked and confirm every piece against the image"
        case .turn: return "I checked and confirm whose turn it is"
        case .castling: return "I checked and confirm the castling rights, including none"
        case .enPassant: return "I checked and confirm the en passant square, including none"
        case .counters: return "I checked and confirm both move counters"
        }
    }
}

@MainActor final class OfflineStudyModel: ObservableObject {
    @Published private(set) var status = "Offline synthetic study. Start the local engine when ready."
    @Published private(set) var ready = false
    @Published private(set) var busy = false
    @Published private(set) var fixture: StudyFixture = .starting
    @Published private(set) var board: OfflineBoard?
    @Published private(set) var imageBytes: Data?
    @Published private(set) var fen = ""
    @Published private(set) var checks: Set<ReviewField> = []
    @Published private(set) var reviewed = false
    @Published private(set) var recommendation: String?
    @Published private(set) var move: String?
    private struct Review { let revision: UInt64; let frame: FrameIdentity; let fen: String; let terminal: Bool }
    private struct ResultIdentity { let review: Review; let request: UUID; let text: String }
    private let makeBackend: @MainActor () throws -> any OfflineBackend
    private let recognizer: any OfflineImageRecognizer
    private let loadFixture: @MainActor (StudyFixture) throws -> Data
    private let speech: any OfflineSpeech
    private var backend: (any OfflineBackend)?
    private var review: Review?
    private var result: ResultIdentity?
    private var work: Task<Void, Never>?
    private var operation: UUID?
    private var revision: UInt64 = 1
    private var session = UUID()
    private var active = true
    private var prewarmTask: Task<Void, Never>?

    init(makeBackend: @escaping @MainActor () throws -> any OfflineBackend,
         recognizer: any OfflineImageRecognizer, loadFixture: @escaping @MainActor (StudyFixture) throws -> Data,
         speech: any OfflineSpeech) {
        self.makeBackend = makeBackend; self.recognizer = recognizer
        self.loadFixture = loadFixture; self.speech = speech
    }
    var canValidate: Bool { active && ready && !busy && board?.complete == true && checks.count == 5 && !fen.isEmpty }
    var canAnalyze: Bool { active && ready && !busy && review?.revision == revision && review?.terminal == false }
    var canSpeak: Bool { active && !busy && result?.review.revision == revision && result?.review.frame.sha256 == board?.sha256 }
    private func cancelWork() {
        operation = nil; work?.cancel(); work = nil; busy = false
        backend?.cancel(); speech.cancel(); result = nil; recommendation = nil; move = nil
    }
    private func invalidate(clearChecks: Bool) {
        cancelWork(); review = nil; reviewed = false
        if clearChecks { checks = [] }
        if revision >= 9_007_199_254_740_991 { session = UUID(); revision = 1 } else { revision += 1 }
    }
    private func begin() -> (UUID, UInt64) {
        cancelWork(); let token = UUID(); operation = token; busy = true; return (token, revision)
    }
    private func current(_ token: UUID, _ expected: UInt64) -> Bool { active && operation == token && revision == expected && !Task.isCancelled }
    private func finish(_ token: UUID) { if operation == token { busy = false; operation = nil; work = nil } }
    /// The review screen is open (or its review just completed): ask for a spare engine. Called only
    /// when no request of this model is in flight. Fire and forget; the outcome is ignored.
    private func requestPrewarm() {
        guard active, ready, board?.complete == true, let backend else { return }
        prewarmTask?.cancel()
        prewarmTask = Task { @MainActor in try? await backend.prewarm() }
    }
    /// Leaving review (un-tick, switch, reset, background): drop any spare. Closing the runtime also ends it.
    private func dropPrewarm() {
        prewarmTask?.cancel(); prewarmTask = nil
        guard let backend else { return }
        Task { @MainActor in try? await backend.cancelPrewarm() }
    }
    /// Detach before closing so our own close never looks like an unexpected runtime stop.
    private func closeBackend() { dropPrewarm(); let old = backend; backend = nil; ready = false; old?.close() }
    private func backendClosed(_ closed: any OfflineBackend) {
        guard let backend, backend === closed else { return }
        invalidate(clearChecks: false); closeBackend()
        status = "The local engine stopped. Start it again and validate the position again."
    }

    func start() {
        guard active else { return }
        invalidate(clearChecks: true); closeBackend()
        let (token, expected) = begin(); status = "Starting the bundled local engine…"
        work = Task { @MainActor [weak self] in
            guard let self else { return }
            defer { self.finish(token) }
            var candidate: (any OfflineBackend)?
            do {
                let created = try self.makeBackend(); candidate = created
                created.observeClosure { [weak self, weak created] in
                    guard let self, let created else { return }
                    self.backendClosed(created)
                }
                try await created.start()
                guard self.current(token, expected) else { created.close(); return }
                self.backend = created; self.ready = true; self.status = "Local engine ready. Read the selected board."
            } catch {
                candidate?.close()
                if self.current(token, expected) { self.status = "Local engine failed to start. Reset and try again." }
            }
        }
    }
    func selectFixture(_ selection: StudyFixture) {
        guard selection != fixture else { return }
        invalidate(clearChecks: true); dropPrewarm()
        board = nil; imageBytes = nil; fen = ""
        fixture = selection
        status = ready ? "Position selected. Read the board to begin review." : "Position selected. Start the local engine."
    }
    func recognizeFixture() {
        guard active && ready else { return }
        invalidate(clearChecks: true); board = nil; imageBytes = nil; fen = ""
        let selection = fixture
        let (token, expected) = begin(); status = "Reading the selected board…"
        work = Task { @MainActor [weak self] in
            guard let self else { return }
            defer { self.finish(token) }
            do {
                let bytes = try self.loadFixture(selection)
                guard !bytes.isEmpty, bytes.count <= 8 * 1024 * 1024 else { throw OfflineStudyError.invalidImage }
                let proposal = try await self.recognizer.recognize(bytes)
                guard self.current(token, expected) else { return }
                guard proposal.sha256 == NativeSyntheticRecognizer.sha256(bytes) else { throw OfflineStudyError.invalidImage }
                self.imageBytes = bytes; self.board = proposal
                self.status = proposal.complete ? "Unreviewed synthetic pieces. Enter all six FEN fields and review each group." : "Recognition is uncertain. Analysis is blocked."
                self.requestPrewarm() // the review screen opens (only for a complete board)
            } catch { if self.current(token, expected) { self.status = "Recognition failed. Analysis is blocked." } }
        }
    }
    func editFEN(_ text: String) {
        guard text != fen else { return }
        invalidate(clearChecks: true); fen = String(text.prefix(200)); status = "Position changed. Review every state group again."
    }
    func setReview(_ field: ReviewField, checked: Bool) {
        invalidate(clearChecks: false)
        if checked { checks.insert(field) } else { checks.remove(field) }
        status = "Review the supplied full position before validation."
        if !checked { dropPrewarm() } else if checks.count == ReviewField.allCases.count { requestPrewarm() }
    }
    func validate() {
        guard canValidate, let board, let backend else { return }
        let source = fen.split(whereSeparator: \.isWhitespace).joined(separator: " ")
        guard board.matchesPlacement(source) else {
            invalidate(clearChecks: true); status = "FEN pieces do not match all recognized squares. Correct the FEN and review again."; return
        }
        let (token, expected) = begin(); status = "Checking the complete position with local chess rules…"
        work = Task { @MainActor [weak self] in
            guard let self else { return }
            defer { self.finish(token) }
            do {
                let position = try await backend.validate(source)
                guard self.current(token, expected) else { return }
                guard position.fen == source, self.board?.sha256 == board.sha256 else { throw IntegrationFailure.invalidReply }
                let identity = FrameIdentity(sessionID: self.session, epoch: 1, sequence: expected, sha256: board.sha256)
                self.review = Review(revision: expected, frame: identity, fen: source, terminal: position.terminal)
                self.reviewed = true
                self.status = position.terminal ? "Reviewed terminal position. No move advice." : "Reviewed offline position. Prior repetition history remains unknown."
                if !position.terminal { self.requestPrewarm() }
            } catch { if self.current(token, expected) { self.review = nil; self.reviewed = false; self.status = "Position validation failed. Check all six FEN fields." } }
        }
    }
    func analyze() {
        guard canAnalyze, let review, let backend else { return }
        let (token, expected) = begin(); status = "Analyzing the reviewed offline position…"
        let request = AnalysisRequest(id: UUID(), frame: review.frame, revision: review.revision, fen: review.fen, movetimeMilliseconds: 1000)
        work = Task { @MainActor [weak self] in
            guard let self else { return }
            defer { self.finish(token) }
            do {
                let reply = try await backend.analyze(request)
                guard self.current(token, expected) else { return }
                guard reply.request == request else { throw IntegrationFailure.invalidReply }
                let text = try await backend.speech(fen: review.fen, move: reply.moveUCI)
                guard self.current(token, expected), self.review?.revision == review.revision, self.board?.sha256 == review.frame.sha256 else { return }
                self.result = ResultIdentity(review: review, request: request.id, text: text)
                self.recommendation = text; self.move = reply.moveUCI
                self.status = "Offline recommendation ready. This is analysis of the reviewed saved image."
            } catch { if self.current(token, expected) { self.status = "Analysis failed or was cancelled. No recommendation is available." } }
        }
    }
    func speak() {
        speech.cancel()
        guard canSpeak, let result, result.review.fen == review?.fen else { return }
        do { try speech.speak(result.text); status = "Offline speech requested. Audible delivery and glasses routing are unverified." }
        catch { status = "No installed English speech voice is available." }
    }
    func stopSpeech() { speech.cancel(); status = "Speech stopped." }
    func setActive(_ isActive: Bool) {
        active = isActive
        if !isActive {
            invalidate(clearChecks: true); closeBackend()
            status = "Paused. Start the local engine and review again after returning."
        }
    }
    func reset() {
        invalidate(clearChecks: true); closeBackend()
        board = nil; imageBytes = nil; fen = ""; fixture = .starting; session = UUID()
        status = "Offline study reset. No camera or glasses session is active."
    }
}
