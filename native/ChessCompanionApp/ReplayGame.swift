import Foundation
import Combine

// Offline "Replay game" mode (2026-11-15). Steps through bundled synthetic board images, reads each
// with native recognition, and keeps the game state with the bundled legal-move tracker inside the
// local WebKit runtime (ReplayTracker + ReplayTrackerRuntimeTransport). Text recommendations only.
//
// State machine (phase), with the events that move between states:
//
//   engineStopped --start ok--> awaitingFirstFrame --step (frame 0 read)--> needsReview
//   needsReview --confirmReview: 5 ticks + pieces match + rules ok + tracker initialize + 2 clean
//                 observations of the shown frame--> tracking
//   tracking --step, tracker reports a clean legal advance (same position, or exactly one new legal
//              ply, ready after 2 observations)--> tracking (review kept; analysis allowed again)
//   tracking --step with unknown squares / skipped ply / illegal / repeated or reordered frame /
//              tracker error / transport failure / anything not a clean advance--> needsReview
//   tracking|needsReview --edit FEN, review box change--> needsReview (renewed review required)
//   any --reset, choose another game (selectSequence), leave mode, background, runtime stopped--> engineStopped
//
// Bundled games (ReplaySequences): the 14-frame opening and the 26-frame special-move game (en
// passant, captures, promotion, both castlings), each with its own interruption frames.
//
// Recommendation rules: analysis only in `tracking` after a clean advance and only between tracker
// requests; it is bound to (run id, review epoch, tracker revision, FEN) and shown only while all
// four are unchanged. Every event above, and every step, revokes it first (generation bump).
// Stepping cancels in-flight analysis and waits for it to end before any tracker request, so tracker
// and engine are never in flight together. Late replies are dropped by generation + identity checks.
// Virtual replay time is a step counter (+100 ms per observation, reset with each new runtime),
// never wall-clock time, and the UI never presents it as a capture age. No audio or speech output.

/// One bundled replay image with its pinned SHA-256 (also pinned by prepare_app.py).
struct ReplayFrameAsset: Sendable, Equatable {
    let asset: String
    let sha256: String
}

/// A frame the person can insert once between two normal frames (obstruction, missing piece).
struct ReplayInterruption: Sendable, Equatable {
    let asset: ReplayFrameAsset
    let title: String          // frame label while it is shown
    let buttonTitle: String    // "Show ... next"
}

/// One selectable bundled game: ordered frames plus optional interruption frames. Only pixels and
/// their pins are bundled; no expected position of any frame is part of the app.
struct ReplaySequence: Sendable, Equatable, Identifiable {
    let id: String
    let title: String
    let frames: [ReplayFrameAsset]
    let interruptions: [ReplayInterruption]
    var allAssets: [ReplayFrameAsset] { frames + interruptions.map(\.asset) }
}

enum ReplayFrames {
    private static let pins = [
        "ed30d4974c39e73d64c5450a1bc1ea66359e7241e28cc5f88d6bd0299207926a",
        "ed30d4974c39e73d64c5450a1bc1ea66359e7241e28cc5f88d6bd0299207926a",
        "4f40873feb7b4f023592669302d393f9b3cbc716aee37616ff258f942e1cf825",
        "4f40873feb7b4f023592669302d393f9b3cbc716aee37616ff258f942e1cf825",
        "b2c518e33713679be97a7cd74d690b98c15977ab2990813442f66b57d3167db9",
        "b2c518e33713679be97a7cd74d690b98c15977ab2990813442f66b57d3167db9",
        "7e74cd459577938cc6bad8ecb2a33530b00b1ad101ea89b35243eeeb6b12005d",
        "7e74cd459577938cc6bad8ecb2a33530b00b1ad101ea89b35243eeeb6b12005d",
        "096c62ca48e04d8b8b841fd110ee21b4bc8eca57f6b9bb25e352eca10ba03b30",
        "096c62ca48e04d8b8b841fd110ee21b4bc8eca57f6b9bb25e352eca10ba03b30",
        "983b9caa9157e97877192ec5f8bf21cc783b38c689bede6c23b246a1a466b21e",
        "983b9caa9157e97877192ec5f8bf21cc783b38c689bede6c23b246a1a466b21e",
        "e7f93fb7b5b31d9ac5b662052c42c5d312eee2b8a51b4e4f57e77d09dfc3077d",
        "e7f93fb7b5b31d9ac5b662052c42c5d312eee2b8a51b4e4f57e77d09dfc3077d",
    ]
    static let main: [ReplayFrameAsset] = pins.enumerated().map { index, sha in
        ReplayFrameAsset(asset: String(format: "Replay/frame-%03d.png", index), sha256: sha)
    }
    static let interruption = ReplayFrameAsset(asset: "Replay/interruption.png",
                                               sha256: "c02544067d3aba32b660e1093df77b0c7eac6076984c003bd2454f8c0c192f2b")

    /// Special-move game (scripts/simulation/generate-special-game.mjs, 2026-11-15): one frame per
    /// position, 25 plies with en passant, captures, a promotion and both castlings.
    private static let specialPins = [
        "725b4ef13d9a5c7b9319c5e6c90cd0a49b08e118e54261a2575104b1e35d46cb",
        "7428476f6c3d7e9f0fceda395fa5058283f8057563e193b07da1917e954e49fd",
        "d86a2b19dd44a6f69d23c98f3e9ecefc7860ad1c63a2deb028e1e487f2d48aab",
        "2ef9072cc001d98f6e526db8fcdb6ee2bba296f01efeb69db1d3933d2aa66ef3",
        "6af693ddcb578db2bf8c30f2c3ad62f27ef1d1ea3b3a58dfe7ee7635ee79fd92",
        "72c9d86d4b1cf4110ccd7bb02ed325305cd38bed1acf0a357cd98320418e2353",
        "3524a487900def0d01354c3a958de604817d83facbac30485c3f61ed22a6def5",
        "2a5b2a3d481f6b1f7cc7089365fbe3c2605dbcb58a3f685fddbcf083e36f0e21",
        "8332f6c64ece084f00787d8146c366482455acf8d9818971c5306456698711f9",
        "810a5c513bbe8157fb722c8b06d9c26fef4758674f2e04e02affe04072eb53a7",
        "b3aa16a094673e8cd52bf43ae704725b724b292d58b73421d1fe56e416f43a7b",
        "a3cbc56210a8ba480ab048aefdd8f1d75d1fa3d2a9bbd2142198377c64713d6b",
        "010511f431e43644909e6232854224084b61d2ce515de588cea9a03294d55983",
        "aaead77d0d3aa1e7492e60ad4ad4bc7779c15fc38ae330b466618c73bb265db3",
        "a9d27fab4b056200ccddcbf6b6600636bd8617dc88cce97149cae7e3f11f43cb",
        "e3f2ce69f029f5bc103200cc4e80862b25d914521645b56bcd5dbe57379dba2e",
        "f6a5baee7e025c48113a4473e9a3c67f4f59018a0add2e6e4816c2be340f5eb0",
        "10a24a4d6b96fca5d2255a7f53b8c10ce91ec520c85ff271612b1ef7eee70e85",
        "a4bc11dd13665dd13ca2d836f460ba9636363a89b44dbee7e51a29d746796560",
        "8c99079d5ed9456befdadc6d3a9a11e6ebdd7265af3ed835a2efa4089a38480b",
        "61c6aaf68e69971904d11c625a9e8cbb846a6a0df916e5e5bf3b083f7853e40a",
        "b36bbc7d516e0b1a0cc3a41f0f31f823e266959728be3239c494bd09030471d5",
        "92436aea38886a45b392692ac847fa152cac958734159a0c34f79994a8fefe0b",
        "ba7e0923174b5559bea3bf1896f6049ecff9d2d71dabb32f9001076eaf328488",
        "1214c3a1006dc919c02aaa76a4eed861bd8e27edc4f33295f107e6d14c0dc9a3",
        "3a20461a21011b00a5bc67b1969810afd11241ec99958bca7780a1bad495a3cf",
    ]
    static let special: [ReplayFrameAsset] = specialPins.enumerated().map { index, sha in
        ReplayFrameAsset(asset: String(format: "ReplaySpecial/frame-%03d.png", index), sha256: sha)
    }
    static let specialOcclusion = ReplayFrameAsset(asset: "ReplaySpecial/occlusion.png",
                                                   sha256: "76e6b1c0f1a1564e58c15afc9969e4f7fd324814528a243fc45edc7389c7219c")
    static let specialMissingPiece = ReplayFrameAsset(asset: "ReplaySpecial/missing-piece.png",
                                                      sha256: "9c0c9f6c0e11714d262657919c180d4937864f2666d459aed4df25e712a3e22d")

    static var allAssetNames: [String] { ReplaySequences.all.flatMap { $0.allAssets.map(\.asset) } }
}

enum ReplaySequences {
    static let opening = ReplaySequence(
        id: "opening", title: "Opening (14 frames)", frames: ReplayFrames.main,
        interruptions: [ReplayInterruption(asset: ReplayFrames.interruption, title: "Inserted obstructed frame (interruption)",
                                           buttonTitle: "Show obstructed frame next")])
    static let special = ReplaySequence(
        id: "special", title: "Special moves (26 frames)", frames: ReplayFrames.special,
        interruptions: [ReplayInterruption(asset: ReplayFrames.specialOcclusion, title: "Inserted obstructed frame (interruption)",
                                           buttonTitle: "Show obstructed frame next"),
                        ReplayInterruption(asset: ReplayFrames.specialMissingPiece, title: "Inserted frame with a piece missing (interruption)",
                                           buttonTitle: "Show frame with a missing piece next")])
    static let all = [opening, special]
}

/// The local engine backend plus a tracker transport into the same single-pending local runtime.
@MainActor protocol ReplayEngineBackend: OfflineBackend {
    func makeTrackerTransport() -> any ReplayTrackerTransport
}

enum ReplayPhase: Equatable { case engineStopped, awaitingFirstFrame, needsReview, tracking }

struct ReplayRecommendationIdentity: Equatable, Sendable {
    let run: UUID
    let reviewEpoch: UInt64
    let trackerRevision: UInt64
    let fen: String
}

struct ReplayRecommendation: Equatable, Sendable {
    let identity: ReplayRecommendationIdentity
    let text: String
    let move: String
}

@MainActor final class ReplayGameModel: ObservableObject {
    nonisolated static let maximumFrameBytes = 8 * 1024 * 1024
    /// Virtual replay milliseconds added per tracker observation (step counter, not a clock).
    static let virtualStepMilliseconds: UInt64 = 100
    /// The tracker needs two matching observations at least 50 virtual ms apart.
    static let observationsPerFrame = 2

    @Published private(set) var status = "Replay game. Start the local engine when ready."
    @Published private(set) var ready = false
    @Published private(set) var phase: ReplayPhase = .engineStopped
    @Published private(set) var frameIndex: Int?
    /// Index (into the selected sequence's interruptions) of the frame queued next / shown now.
    @Published private(set) var queuedInterruption: Int?
    @Published private(set) var shownInterruption: Int?
    @Published private(set) var selectedSequence: ReplaySequence
    @Published private(set) var board: OfflineBoard?
    @Published private(set) var imageBytes: Data?
    @Published private(set) var fen = ""
    @Published private(set) var checks: Set<ReviewField> = []
    @Published private(set) var trackedFEN: String?
    @Published private(set) var trackedRevision: UInt64?
    @Published private(set) var lastMoveSAN: String?
    @Published private(set) var reviewEpoch: UInt64 = 0
    @Published private(set) var trackingReady = false
    @Published private(set) var cleanAdvance = false
    @Published private(set) var starting = false
    @Published private(set) var stepping = false
    @Published private(set) var analyzing = false
    @Published private(set) var result: ReplayRecommendation?
    @Published private(set) var runID = UUID()
    @Published private(set) var active = true

    let sequences: [ReplaySequence]
    var frames: [ReplayFrameAsset] { selectedSequence.frames }
    var showingInterruption: Bool { shownInterruption != nil }
    var interruptionQueued: Bool { queuedInterruption != nil }
    private let makeBackend: @MainActor () throws -> any ReplayEngineBackend
    private let recognizer: any OfflineImageRecognizer
    private let loadFrame: @MainActor (ReplayFrameAsset) throws -> Data
    private var backend: (any ReplayEngineBackend)?
    private var tracker: ReplayTracker?
    private var session: ReplaySession?
    private var generation: UInt64 = 0
    private var nextEpoch: UInt64 = 0
    private var virtualMilliseconds: UInt64 = 0
    private var frameSequence: UInt64 = 0
    private var startTask: Task<Void, Never>?, stepTask: Task<Void, Never>?, analysisTask: Task<Void, Never>?
    private var startToken: UUID?, stepToken: UUID?, analysisToken: UUID?

    init(makeBackend: @escaping @MainActor () throws -> any ReplayEngineBackend,
         recognizer: any OfflineImageRecognizer,
         loadFrame: @escaping @MainActor (ReplayFrameAsset) throws -> Data,
         sequences: [ReplaySequence]) {
        self.makeBackend = makeBackend; self.recognizer = recognizer; self.loadFrame = loadFrame
        let usable = sequences.filter { !$0.frames.isEmpty }
        self.sequences = usable.isEmpty ? [ReplaySequences.opening] : usable
        self.selectedSequence = self.sequences[0]
    }
    /// One sequence made of the given frames and a single obstructed interruption frame.
    convenience init(makeBackend: @escaping @MainActor () throws -> any ReplayEngineBackend,
                     recognizer: any OfflineImageRecognizer,
                     loadFrame: @escaping @MainActor (ReplayFrameAsset) throws -> Data,
                     frames: [ReplayFrameAsset] = ReplayFrames.main, interruption: ReplayFrameAsset = ReplayFrames.interruption) {
        self.init(makeBackend: makeBackend, recognizer: recognizer, loadFrame: loadFrame, sequences: [ReplaySequence(
            id: "opening", title: ReplaySequences.opening.title, frames: frames,
            interruptions: [ReplayInterruption(asset: interruption, title: "Inserted obstructed frame (interruption)",
                                               buttonTitle: "Show obstructed frame next")])])
    }

    // MARK: - Derived gates

    var busy: Bool { starting || stepping || analyzing }
    var hasNextFrame: Bool { queuedInterruption != nil || (frameIndex.map { $0 + 1 } ?? 0) < frames.count }
    var canStep: Bool { active && ready && !starting && !stepping && hasNextFrame }
    var canQueueInterruption: Bool {
        active && ready && !stepping && frameIndex != nil && queuedInterruption == nil && shownInterruption == nil
            && !selectedSequence.interruptions.isEmpty
    }
    var canConfirmReview: Bool {
        active && ready && !busy && phase == .needsReview && board?.complete == true && checks.count == ReviewField.allCases.count && !fen.isEmpty
    }
    /// The identity a recommendation must carry to be shown right now; nil whenever none may be shown.
    var currentIdentity: ReplayRecommendationIdentity? {
        guard active, ready, phase == .tracking, trackingReady, cleanAdvance, board?.complete == true,
              let fen = trackedFEN, let revision = trackedRevision else { return nil }
        return ReplayRecommendationIdentity(run: runID, reviewEpoch: reviewEpoch, trackerRevision: revision, fen: fen)
    }
    var canAnalyze: Bool { !busy && currentIdentity != nil && recommendation == nil }
    var recommendation: String? { visibleResult?.text }
    var move: String? { visibleResult?.move }
    private var visibleResult: ReplayRecommendation? {
        guard let result, let identity = currentIdentity, result.identity == identity else { return nil }
        return result
    }
    var frameLabel: String {
        if let shown = shownInterruption, selectedSequence.interruptions.indices.contains(shown) {
            return selectedSequence.interruptions[shown].title
        }
        guard let frameIndex else { return "No frame read yet" }
        return "Frame \(frameIndex + 1) of \(frames.count)"
    }

    // MARK: - Internal helpers

    private func current(_ expected: UInt64) -> Bool { active && generation == expected && !Task.isCancelled }
    private func live(_ expected: UInt64, _ identity: ReplayRecommendationIdentity) -> Bool {
        current(expected) && currentIdentity == identity
    }
    /// Revokes any recommendation and invalidates every pending reply.
    private func bump() { generation &+= 1; result = nil }
    /// Cancels in-flight work. Tasks stay recorded (and the model stays busy) until they really end,
    /// so a new tracker or engine request can never overlap an old one.
    private func cancelInFlight() { stepTask?.cancel(); analysisTask?.cancel(); backend?.cancel() }
    private func clearTracking() {
        result = nil; trackingReady = false; cleanAdvance = false; session = nil
        trackedFEN = nil; trackedRevision = nil; lastMoveSAN = nil
        phase = !ready ? .engineStopped : (frameIndex == nil && !showingInterruption ? .awaitingFirstFrame : .needsReview)
    }
    /// Tracking is revoked; a renewed full review of the shown frame is required.
    private func revokeTracking(_ message: String, clearDraft: Bool) {
        bump(); clearTracking(); checks = []
        if clearDraft { fen = "" }
        status = message
    }
    private func closeBackend() { let old = backend; backend = nil; tracker = nil; ready = false; old?.close() }
    private func backendClosed(_ closed: any ReplayEngineBackend) {
        guard let backend, backend === closed else { return }
        bump(); cancelInFlight(); closeBackend(); clearTracking(); checks = []
        status = "The local engine stopped. Start it again and review the shown frame again."
    }
    private func finishStart(_ token: UUID) { if startToken == token { startToken = nil; startTask = nil; starting = false } }
    private func finishStep(_ token: UUID) { if stepToken == token { stepToken = nil; stepTask = nil; stepping = false } }
    private func finishAnalysis(_ token: UUID) { if analysisToken == token { analysisToken = nil; analysisTask = nil; analyzing = false } }
    private func normalized(_ text: String) -> String { text.split(whereSeparator: \.isWhitespace).joined(separator: " ") }

    private func message(for cause: ReplayRevocationCause) -> String {
        let tail = " Tracking and any recommendation are revoked. Review a complete frame again."
        switch cause {
        case .trackerNeedsConfirmation(let reason):
            switch reason {
            case "uncertain-squares": return "Unknown or uncertain squares on this frame." + tail
            case "not-zero-or-one-legal-move": return "The board changed by something other than one legal move (skipped or illegal)." + tail
            case "ambiguous-observation": return "The change matches more than one legal move." + tail
            case "observation-timeout": return "Too much replay time passed without a usable frame." + tail
            default: return "The tracker stopped tracking (\(reason))." + tail
            }
        case .errorReply(let code): return "The tracker rejected the frame (\(code ?? "error"))." + tail
        case .transportFailure: return "The local tracker did not answer." + tail
        case .malformedReply: return "The tracker reply did not match the contract." + tail
        case .requestRejected: return "The frame could not be sent to the tracker." + tail
        case .concurrentRequest: return "A tracker request overlapped another." + tail
        case .invalidated, .notInitialized: return "Tracking is not active." + tail
        }
    }

    // MARK: - Actions (the same methods the buttons call)

    func start() {
        guard active, !busy, !ready else { return }
        closeBackend(); bump(); clearTracking(); checks = []
        let token = UUID(), expected = generation
        startToken = token; starting = true
        status = "Starting the bundled local engine…"
        startTask = Task { @MainActor [weak self] in
            guard let self else { return }
            defer { self.finishStart(token) }
            var candidate: (any ReplayEngineBackend)?
            do {
                let created = try self.makeBackend(); candidate = created
                created.observeClosure { [weak self, weak created] in
                    guard let self, let created else { return }
                    self.backendClosed(created)
                }
                try await created.start()
                guard self.current(expected) else { created.close(); return }
                self.backend = created
                self.tracker = ReplayTracker(transport: created.makeTrackerTransport(), requestIdPrefix: "replay-")
                // A new runtime has a new tracker whose virtual clock starts at 0.
                self.virtualMilliseconds = 0; self.frameSequence = 0
                self.ready = true; self.clearTracking()
                self.status = self.board == nil ? "Local engine ready. Read the first frame."
                                                : "Local engine ready. Review the shown frame to start tracking."
            } catch {
                candidate?.close()
                if self.current(expected) { self.status = "Local engine failed to start. Reset and try again." }
            }
        }
    }

    /// Moves to the next bundled frame (or the queued obstructed frame). Revokes any recommendation
    /// first, cancels and awaits in-flight analysis, then reads the frame and, while tracking, asks
    /// the tracker. Anything except a clean legal advance requires a renewed review.
    func step() {
        guard canStep else { return }
        let wasTracking = phase == .tracking
        bump(); cleanAdvance = false
        if !wasTracking { checks = []; fen = "" } // a review belongs to the frame it was made on
        let interrupt = queuedInterruption
        let asset = interrupt.map { selectedSequence.interruptions[$0].asset } ?? frames[(frameIndex ?? -1) + 1]
        let nextIndex = interrupt != nil ? frameIndex : (frameIndex ?? -1) + 1
        let previousFEN = trackedFEN, previousRevision = trackedRevision
        let prior = analysisTask
        if prior != nil { analysisTask?.cancel(); backend?.cancel() }
        let token = UUID(), expected = generation
        stepToken = token; stepping = true
        status = "Reading the next replay frame…"
        stepTask = Task { @MainActor [weak self] in
            guard let self else { return }
            defer { self.finishStep(token) }
            if let prior { await prior.value } // engine fully ended before any tracker request
            guard self.current(expected) else { return }
            guard let proposal = await self.read(asset, expected) else { return }
            self.board = proposal.board; self.imageBytes = proposal.bytes
            self.frameIndex = nextIndex; self.shownInterruption = interrupt
            if interrupt != nil { self.queuedInterruption = nil }
            guard wasTracking, self.phase == .tracking else {
                self.phase = .needsReview
                self.status = proposal.board.complete
                    ? "Tracking is not active. Review this frame (all five confirmations) to start tracking."
                    : "Unknown squares on this frame. Tracking and analysis are blocked."
                return
            }
            self.status = "Asking the legal-move tracker about this frame…"
            if await self.observePair(proposal.board, expected, reviewedFEN: nil, previousFEN: previousFEN, previousRevision: previousRevision) {
                self.status = self.trackedFEN == previousFEN
                    ? "Same position as before. Tracking continues; you can analyze it."
                    : "Legal move tracked\(self.lastMoveSAN.map { ": \($0)" } ?? ""). Tracking continues; you can analyze the new position."
            }
        }
    }

    /// Queues interruption `index` of the selected sequence to be shown by the next step.
    func queueInterruption(_ index: Int = 0) {
        guard canQueueInterruption, selectedSequence.interruptions.indices.contains(index) else { return }
        queuedInterruption = index
        status = index == 0 ? "The obstructed frame will be shown next." : "The frame with a missing piece will be shown next."
    }

    /// Chooses another bundled game. Like reset: revokes tracking and any recommendation at once,
    /// cancels in-flight work, stops the engine and clears the frame, draft and review.
    func selectSequence(_ id: String) {
        guard let next = sequences.first(where: { $0.id == id }), next.id != selectedSequence.id else { return }
        reset()
        selectedSequence = next
        status = "Switched to \(next.title). Start the local engine and review the first frame to start tracking."
    }

    private func read(_ asset: ReplayFrameAsset, _ expected: UInt64) async -> (bytes: Data, board: OfflineBoard)? {
        do {
            let bytes = try loadFrame(asset)
            guard !bytes.isEmpty, bytes.count <= Self.maximumFrameBytes,
                  NativeSyntheticRecognizer.sha256(bytes) == asset.sha256 else { throw OfflineStudyError.invalidImage }
            let proposal = try await recognizer.recognize(bytes)
            guard current(expected) else { return nil }
            guard proposal.sha256 == asset.sha256 else { throw OfflineStudyError.invalidImage }
            return (bytes, proposal)
        } catch {
            if current(expected) {
                revokeTracking("Reading this frame failed. Tracking is revoked and analysis is blocked.", clearDraft: true)
            }
            return nil
        }
    }

    /// Sends the shown frame to the tracker twice (virtual time +100 ms each) and accepts only a
    /// clean result. `reviewedFEN` set: first pair after a review (no move allowed). Otherwise the
    /// position must be unchanged or exactly one tracked legal ply after `previousFEN`.
    private func observePair(_ board: OfflineBoard, _ expected: UInt64, reviewedFEN: String?,
                             previousFEN: String?, previousRevision: UInt64?) async -> Bool {
        guard let tracker, let session else {
            revokeTracking("Tracking is not active. Review a complete frame again.", clearDraft: true); return false
        }
        var squares: [String: ReplaySquare] = [:]
        for (square, label) in board.squares {
            // Recognition never fills in anything: an unknown square stays unknown with zero confidence.
            squares[square] = label == "unknown" ? ReplaySquare(label: "unknown", confidence: 0) : ReplaySquare(label: label, confidence: 1)
        }
        var last: ReplayTrackingState?
        for _ in 0..<Self.observationsPerFrame {
            frameSequence += 1; virtualMilliseconds += Self.virtualStepMilliseconds
            let frame = ReplayFrame(session: session, sequence: frameSequence, frameSha256: board.sha256,
                                    capturedAtMs: virtualMilliseconds, squares: squares)
            let outcome = await tracker.observe(frame)
            guard current(expected) else { return false }
            switch outcome {
            case .revokedRenewedReviewRequired(let cause):
                revokeTracking(message(for: cause), clearDraft: true); return false
            case .tracking(let state):
                if let ignored = state.ignored {
                    revokeTracking("The tracker ignored a repeated or reordered frame (\(ignored)). Tracking is revoked. Review a complete frame again.", clearDraft: true)
                    return false
                }
                last = state
            }
        }
        let clean: Bool
        if let state = last, state.trackingReady, board.complete, let fen = state.fen, board.matchesPlacement(fen) {
            if reviewedFEN != nil {
                clean = state.lastMove == nil
            } else {
                let unchanged = fen == previousFEN && state.revision == previousRevision
                let oneMove = fen != previousFEN && state.lastMove != nil && previousRevision.map { state.revision > $0 } == true
                clean = unchanged || oneMove
            }
        } else { clean = false }
        guard clean, let state = last else {
            revokeTracking(board.complete ? "This frame was not a clean legal advance. Tracking and any recommendation are revoked. Review a complete frame again."
                                          : "Unknown squares on this frame. Tracking and any recommendation are revoked. Review a complete frame again.",
                           clearDraft: true)
            return false
        }
        trackedFEN = state.fen; trackedRevision = state.revision; lastMoveSAN = state.lastMove?.san
        trackingReady = true; cleanAdvance = true; phase = .tracking
        return true
    }

    func editFEN(_ text: String) {
        guard text != fen else { return }
        let wasTracking = phase == .tracking
        bump(); cancelInFlight(); clearTracking(); checks = []
        fen = String(text.prefix(200))
        status = wasTracking ? "Position edited. Tracking and any recommendation are revoked. Review this frame again."
                             : "Position changed. Review every state group again."
    }

    func setReview(_ field: ReviewField, checked: Bool) {
        let wasTracking = phase == .tracking
        bump(); cancelInFlight(); clearTracking()
        if wasTracking { checks = [] } // renewed review means five explicit confirmations again
        if checked { checks.insert(field) } else { checks.remove(field) }
        status = wasTracking ? "Review changed. Tracking and any recommendation are revoked. Review this frame again."
                             : "Review the supplied full position before starting tracking."
    }

    /// One complete human review of the shown frame starts (or restarts) tracking.
    func confirmReview() {
        guard canConfirmReview, let board, let backend, let tracker else { return }
        let source = normalized(fen)
        guard board.matchesPlacement(source) else {
            bump(); checks = []
            status = "FEN pieces do not match all recognized squares. Correct the FEN and review again."
            return
        }
        let review = ReplayHumanReview(pieces: checks.contains(.pieces), turn: checks.contains(.turn), castling: checks.contains(.castling),
                                       enPassant: checks.contains(.enPassant), counters: checks.contains(.counters))
        bump()
        let prior = analysisTask
        let token = UUID(), expected = generation
        stepToken = token; stepping = true
        status = "Checking the reviewed position with local chess rules…"
        stepTask = Task { @MainActor [weak self] in
            guard let self else { return }
            defer { self.finishStep(token) }
            if let prior { await prior.value }
            guard self.current(expected) else { return }
            do {
                let position = try await backend.validate(source)
                guard self.current(expected) else { return }
                guard position.fen == source, self.board?.sha256 == board.sha256 else { throw IntegrationFailure.invalidReply }
                guard !position.terminal else { self.status = "The reviewed position is terminal. No move advice."; return }
                self.nextEpoch += 1
                let session = ReplaySession(sessionId: "run-" + self.runID.uuidString.lowercased(), epoch: self.nextEpoch)
                self.status = "Starting the legal-move tracker from your reviewed position…"
                let outcome = await tracker.initialize(session: session, fen: source, review: review)
                guard self.current(expected) else { return }
                guard case .tracking(let state) = outcome, state.fen != nil, !state.trackingReady else {
                    self.revokeTracking("The tracker did not accept the reviewed position. Review again.", clearDraft: false); return
                }
                self.session = session; self.reviewEpoch = session.epoch
                if await self.observePair(board, expected, reviewedFEN: source, previousFEN: nil, previousRevision: nil) {
                    self.status = "Tracking from your reviewed position. Earlier repetition history is unknown."
                }
            } catch {
                if self.current(expected) { self.checks = []; self.status = "Position validation failed. Check all six FEN fields and review again." }
            }
        }
    }

    /// Text-only recommendation for the current tracked position. Never runs during a tracker request.
    func analyze() {
        guard canAnalyze, let identity = currentIdentity, let backend, let board else { return }
        let token = UUID(), expected = generation
        analysisToken = token; analyzing = true
        status = "Analyzing the tracked position (text only)…"
        let request = AnalysisRequest(id: UUID(), frame: FrameIdentity(sessionID: identity.run, epoch: identity.reviewEpoch,
                                                                       sequence: identity.trackerRevision, sha256: board.sha256),
                                      revision: identity.trackerRevision, fen: identity.fen, movetimeMilliseconds: 1000)
        analysisTask = Task { @MainActor [weak self] in
            guard let self else { return }
            defer { self.finishAnalysis(token) }
            do {
                let position = try await backend.validate(identity.fen)
                guard self.live(expected, identity) else { return }
                guard position.fen == identity.fen else { throw IntegrationFailure.invalidReply }
                if position.terminal { self.status = "The tracked position is terminal. No move advice."; return }
                let reply = try await backend.analyze(request)
                guard self.live(expected, identity) else { return }
                guard reply.request == request else { throw IntegrationFailure.invalidReply }
                // Rules check of the engine move; returns text only (no audio is produced anywhere).
                let text = try await backend.speech(fen: identity.fen, move: reply.moveUCI)
                guard self.live(expected, identity) else { return }
                self.result = ReplayRecommendation(identity: identity, text: text, move: reply.moveUCI)
                self.status = "Text recommendation for the tracked position. Replayed saved frames, not live play."
            } catch {
                if self.live(expected, identity) { self.status = "Analysis failed or was cancelled. No recommendation is available." }
            }
        }
    }

    func setActive(_ isActive: Bool) {
        active = isActive
        guard !isActive else { return }
        bump(); cancelInFlight(); closeBackend(); clearTracking(); checks = []
        status = "Paused. Start the local engine and review the shown frame again after returning."
    }

    /// Leaving the mode clears everything, like reset, and keeps the model inactive.
    func leave() { reset(); active = false }

    func reset() {
        bump(); cancelInFlight(); closeBackend()
        board = nil; imageBytes = nil; frameIndex = nil; shownInterruption = nil; queuedInterruption = nil
        fen = ""; checks = []; runID = UUID()
        clearTracking()
        status = "Replay reset. No camera or glasses session is active."
    }
}

#if os(iOS)
import SwiftUI
import UIKit

struct ReplayGameView: View {
    @ObservedObject var model: ReplayGameModel
    var body: some View {
        NavigationStack {
            Form {
                Section("Replay game") {
                    Text("Saved synthetic frames are replayed in order. This is not a live camera, and no capture time is shown.")
                        .font(.footnote)
                    if model.sequences.count > 1 {
                        Picker("Game", selection: Binding(get: { model.selectedSequence.id }, set: { model.selectSequence($0) })) {
                            ForEach(model.sequences) { sequence in Text(sequence.title).tag(sequence.id) }
                        }.accessibilityIdentifier("replay-sequence")
                        Text("Choosing another game stops tracking and the engine.").font(.footnote)
                    }
                    Text(model.status).accessibilityIdentifier("replay-status")
                    Text(model.frameLabel).font(.subheadline).accessibilityIdentifier("replay-frame")
                    if model.ready {
                        Button(model.frameIndex == nil && !model.showingInterruption ? "Read first frame" : "Next frame") { model.step() }
                            .disabled(!model.canStep)
                        ForEach(Array(model.selectedSequence.interruptions.enumerated()), id: \.offset) { index, interruption in
                            Button(interruption.buttonTitle) { model.queueInterruption(index) }.disabled(!model.canQueueInterruption)
                        }
                    } else {
                        Button("Start local engine") { model.start() }.disabled(model.busy || !model.active)
                    }
                    if model.busy { ProgressView() }
                }
                if let bytes = model.imageBytes, let image = UIImage(data: bytes) {
                    Section("Frame and unreviewed recognition") {
                        Image(uiImage: image).resizable().scaledToFit().accessibilityLabel("Bundled synthetic replay frame")
                        if let board = model.board {
                            Text(board.complete ? "All 64 squares have a proposal." : "Unknown squares block tracking and analysis.")
                            ReplayBoardGrid(board: board)
                        }
                    }
                }
                if model.phase == .tracking, let fen = model.trackedFEN {
                    Section("Tracked position (legal-move tracker)") {
                        Text(fen).font(.system(.footnote, design: .monospaced)).accessibilityIdentifier("replay-tracked-fen")
                        if let san = model.lastMoveSAN { Text("Last tracked move: \(san)") }
                        Text("Earlier repetition history is unknown; no repetition claims are made.").font(.footnote)
                        Button("Analyze tracked position") { model.analyze() }.disabled(!model.canAnalyze)
                    }
                }
                if (model.phase == .needsReview || model.phase == .tracking), model.board?.complete == true {
                    Section(model.phase == .tracking ? "Your review (changing it stops tracking)" : "Review this frame to start tracking") {
                        Text("Supply all six FEN fields for the shown frame and check each group. Earlier repetition history is unknown.")
                        if model.frameIndex == 0 && !model.showingInterruption && model.phase == .needsReview,
                           let sample = StudyFixture.starting.referenceFEN {
                            Button("Use sample FEN (standard starting position)") { model.editFEN(sample) }
                        }
                        TextField("Complete six-field FEN", text: Binding(get: { model.fen }, set: { model.editFEN($0) }), axis: .vertical)
                            .textInputAutocapitalization(.never).autocorrectionDisabled().font(.system(.body, design: .monospaced))
                        ForEach(ReviewField.allCases) { field in
                            Toggle(field.title, isOn: Binding(get: { model.checks.contains(field) }, set: { model.setReview(field, checked: $0) }))
                        }
                        if model.phase == .needsReview {
                            Button("Confirm review and start tracking") { model.confirmReview() }.disabled(!model.canConfirmReview)
                        }
                    }
                }
                if let text = model.recommendation {
                    Section("Text recommendation") {
                        Text(text).font(.headline).accessibilityIdentifier("replay-recommendation")
                    }
                }
                Section { Button("Reset replay", role: .destructive) { model.reset() } }
            }.navigationTitle("Replay game")
        }
    }
}

private struct ReplayBoardGrid: View {
    let board: OfflineBoard
    var body: some View {
        LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 1), count: 8), spacing: 1) {
            ForEach(0..<64, id: \.self) { index in
                let square = "\(Array("abcdefgh")[index % 8])\(8 - index / 8)"
                let label = board.squares[square] ?? "unknown"
                Text(label == "empty" ? "·" : label == "unknown" ? "?" : label).font(.system(.body, design: .monospaced))
                    .frame(maxWidth: .infinity).padding(.vertical, 4)
                    .background((index / 8 + index % 8).isMultiple(of: 2) ? Color.secondary.opacity(0.1) : Color.secondary.opacity(0.25))
                    .accessibilityElement(children: .ignore)
                    .accessibilityLabel("\(square), \(label)")
            }
        }
    }
}
#endif
