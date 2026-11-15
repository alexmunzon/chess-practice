import Foundation

/// Phone-local orchestration only. The app must explicitly provide real recognition/rules/engine adapters.
@MainActor public final class CaptureCoordinator {
    public enum CameraState: Equatable { case inactive, active, stopRequested(UUID), stoppedAcknowledged(UUID) }
    public let clockDomain = UUID()
    public private(set) var epoch: UInt64 = 0
    public private(set) var sessionID = UUID()
    public private(set) var latestFrame: CapturedFrame?
    public private(set) var proposal: BoardProposal?
    public private(set) var recommendation: Recommendation?
    public private(set) var cameraState: CameraState = .inactive
    public private(set) var reason = "disconnected"
    public var historyComplete: Bool { false }
    public var activeRecognitionCount: Int { activeRecognition == nil ? 0 : 1 }
    public var pendingRecognitionCount: Int { pendingFrame == nil ? 0 : 1 }

    private let recognizer: any FrameRecognizer
    private let engine: any NativeChessEngine
    private let rules: any LocalChessRules
    private let speech: any CancellableSpeechOutput
    private let clock: @MainActor () -> Double
    private let maxAge: Double
    private var connected = false, speechExperiment = false
    private var sequence: UInt64 = 0, revision: UInt64 = 0
    private var lastNow = -Double.infinity, lastReceipt = -Double.infinity
    private var review: (frame: FrameIdentity, revision: UInt64, position: ValidatedPosition)?
    private var activeRecognition: (id: UUID, task: Task<Void, Never>)?
    private var pendingFrame: CapturedFrame?
    private var engineTask: Task<Void, Never>?
    private var activeAnalysis: AnalysisRequest?
    private var speechAttempt: UUID?
    private var watchdog: Task<Void, Never>?

    public init(recognizer: any FrameRecognizer, engine: any NativeChessEngine, rules: any LocalChessRules,
                speech: any CancellableSpeechOutput, maxCaptureAgeSeconds: Double = 1,
                clock: @escaping @MainActor () -> Double = { ProcessInfo.processInfo.systemUptime }) throws {
        guard maxCaptureAgeSeconds.isFinite, maxCaptureAgeSeconds > 0, maxCaptureAgeSeconds <= 10 else { throw CaptureFailure.invalidClock }
        self.recognizer = recognizer; self.engine = engine; self.rules = rules; self.speech = speech
        self.maxAge = maxCaptureAgeSeconds; self.clock = clock
    }

    private func now() throws -> Double {
        let value = clock()
        guard value.isFinite, value >= 0, value >= lastNow else {
            invalidate("invalid-clock"); connected = false; throw CaptureFailure.invalidClock
        }
        lastNow = value; return value
    }
    private func invalidate(_ reason: String, clearReview: Bool = true) {
        revision &+= 1; engineTask?.cancel(); engineTask = nil; activeAnalysis = nil
        recommendation = nil; speechAttempt = nil; speech.cancel()
        if clearReview { review = nil }
        self.reason = reason
    }
    private func cancelRecognition() {
        activeRecognition?.task.cancel(); pendingFrame = nil
        // Keep the active slot until the recognizer actually returns, even across reconnect.
    }

    @discardableResult public func connect() throws -> UInt64 {
        _ = try now(); invalidate("connected-needs-frame"); cancelRecognition()
        epoch &+= 1; sessionID = UUID(); sequence = 0; lastReceipt = -.infinity
        connected = true; cameraState = .inactive; latestFrame = nil; proposal = nil
        watchdog?.cancel()
        watchdog = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(50))
                if Task.isCancelled { break }; self?.tick()
            }
        }
        return epoch
    }
    public func disconnect() {
        invalidate("disconnected"); cancelRecognition(); epoch &+= 1; connected = false
        latestFrame = nil; proposal = nil; cameraState = .inactive; watchdog?.cancel(); watchdog = nil
    }
    public func reset() {
        disconnect(); reason = "reset-disconnected-needs-new-session"
    }
    public func setSpeechExperimentEnabled(_ enabled: Bool) {
        invalidate("speech-experiment-setting-changed"); speechExperiment = enabled
    }
    public func cameraStarted(epoch callbackEpoch: UInt64) throws {
        guard connected, callbackEpoch == epoch else { throw CaptureFailure.staleIdentity }
        invalidate("camera-active"); cameraState = .active
    }
    @discardableResult public func requestCameraStop() throws -> UUID {
        guard connected, cameraState == .active else { throw CaptureFailure.cameraNotStopped }
        invalidate("camera-stop-unacknowledged")
        let requestID = UUID(); cameraState = .stopRequested(requestID); return requestID
    }
    public func acknowledgeCameraStopped(epoch callbackEpoch: UInt64, requestID: UUID) throws {
        guard connected, callbackEpoch == epoch, cameraState == .stopRequested(requestID) else { throw CaptureFailure.staleIdentity }
        cameraState = .stoppedAcknowledged(requestID); reason = "camera-stopped-needs-review"
    }
    /// Paused/failed streams are not successful stop acknowledgements.
    public func captureInterrupted(epoch callbackEpoch: UInt64) {
        guard callbackEpoch == epoch else { return }
        invalidate("capture-interrupted"); cancelRecognition(); cameraState = .inactive
        latestFrame = nil; proposal = nil
    }
    public func noteIncomingFrame(epoch callbackEpoch: UInt64) {
        guard connected, callbackEpoch == epoch else { return }
        invalidate("unrecognized-new-frame"); proposal = nil; latestFrame = nil; cancelRecognition()
        // A frame after a stop acknowledgement disproves that acknowledgement's usefulness.
        if case .stoppedAcknowledged = cameraState { cameraState = .active }
    }

    @discardableResult public func submitDAT(bytes: Data, receivedAtHostSeconds: Double, mediaPTS: MediaTimestamp?, epoch callbackEpoch: UInt64) throws -> FrameIdentity {
        try submit(bytes: bytes, receivedAt: receivedAtHostSeconds, captureTime: .unknownDAT(mediaPTS: mediaPTS), callbackEpoch: callbackEpoch)
    }
    /// Test/replay-only entry point. Never call with DAT sample-buffer PTS or receipt time.
    @discardableResult public func submitReplay(bytes: Data, capturedAtHostSeconds: Double, clockDomain: UUID, epoch callbackEpoch: UInt64) throws -> FrameIdentity {
        try submit(bytes: bytes, receivedAt: now(), captureTime: .trustedReplay(hostSeconds: capturedAtHostSeconds, clockDomain: clockDomain), callbackEpoch: callbackEpoch)
    }
    private func submit(bytes: Data, receivedAt: Double, captureTime: CaptureTime, callbackEpoch: UInt64) throws -> FrameIdentity {
        guard connected, callbackEpoch == epoch else { throw CaptureFailure.staleIdentity }
        noteIncomingFrame(epoch: callbackEpoch)
        let time = try now()
        guard !bytes.isEmpty, bytes.count <= 8 * 1024 * 1024, receivedAt.isFinite,
              receivedAt >= 0, receivedAt <= time, receivedAt > lastReceipt else { throw CaptureFailure.invalidFrame }
        if case let .trustedReplay(capturedAt, domain) = captureTime {
            guard domain == clockDomain, capturedAt.isFinite, capturedAt >= 0, capturedAt <= receivedAt, time - capturedAt <= maxAge else { throw CaptureFailure.invalidClock }
        }
        lastReceipt = receivedAt; sequence &+= 1
        let frame = CapturedFrame(sessionID: sessionID, epoch: epoch, sequence: sequence, bytes: bytes, receivedAt: receivedAt, captureTime: captureTime)
        latestFrame = frame; proposal = nil
        activeRecognition?.task.cancel()
        if activeRecognition != nil { pendingFrame = frame } else { startRecognition(frame) }
        return frame.identity
    }
    private func startRecognition(_ frame: CapturedFrame) {
        let jobID = UUID(), recognizer = self.recognizer
        let task = Task { @MainActor [weak self] in
            let result: Result<BoardProposal, Error>
            do { result = .success(try await recognizer.recognize(frame)) } catch { result = .failure(error) }
            self?.finishRecognition(jobID: jobID, frame: frame, result: result, cancelled: Task.isCancelled)
        }
        activeRecognition = (jobID, task)
    }
    private func finishRecognition(jobID: UUID, frame: CapturedFrame, result: Result<BoardProposal, Error>, cancelled: Bool) {
        guard activeRecognition?.id == jobID else { return }
        activeRecognition = nil
        if !cancelled, connected, latestFrame?.identity == frame.identity {
            switch result {
            case .success(let value) where value.frame == frame.identity && value.isComplete:
                proposal = value; reason = "proposal-needs-independent-full-state-review"
            default: invalidate("uncertain-or-invalid-proposal"); proposal = nil
            }
        }
        if let pending = pendingFrame {
            pendingFrame = nil
            if connected, latestFrame?.identity == pending.identity { startRecognition(pending) }
        }
    }

    public func confirm(fullFEN: String, review checklist: FullStateReview) async throws {
        invalidate("full-state-review-pending")
        guard connected, let frame = latestFrame, proposal?.frame == frame.identity, proposal?.isComplete == true else { throw CaptureFailure.uncertainProposal }
        guard checklist.complete else { throw CaptureFailure.incompleteReview }
        guard fullFEN.utf8.count <= 200, fullFEN.split(whereSeparator: \.isWhitespace).count == 6 else { throw CaptureFailure.invalidPosition }
        let token = revision
        let position = try await rules.validatePosition(fullFEN)
        guard connected, latestFrame?.identity == frame.identity, revision == token else { throw CaptureFailure.staleIdentity }
        guard position.fen.split(whereSeparator: \.isWhitespace).count == 6 else { throw CaptureFailure.invalidPosition }
        self.review = (frame.identity, token, position); reason = position.terminal ? "terminal-position" : "reviewed"
    }
    private func capturedAt(_ frame: CapturedFrame, now time: Double) throws -> Double {
        guard case let .trustedReplay(capturedAt, domain) = frame.captureTime else { throw CaptureFailure.unknownCaptureAge }
        guard domain == clockDomain, capturedAt.isFinite, capturedAt >= 0, capturedAt <= time, time - capturedAt <= maxAge else { throw CaptureFailure.invalidClock }
        return capturedAt
    }
    private func requireGuidanceState() throws -> (CapturedFrame, ValidatedPosition, UInt64, Double) {
        let time = try now()
        guard connected, let frame = latestFrame, let review, review.frame == frame.identity else { throw CaptureFailure.incompleteReview }
        guard !review.position.terminal else { throw CaptureFailure.terminalPosition }
        guard case .stoppedAcknowledged = cameraState else { throw CaptureFailure.cameraNotStopped }
        guard speechExperiment else { throw CaptureFailure.speechExperimentDisabled }
        let capturedAt = try capturedAt(frame, now: time)
        return (frame, review.position, review.revision, capturedAt)
    }
    @discardableResult public func analyzeReviewedPosition(movetimeMilliseconds: Int = 100) throws -> AnalysisRequest {
        guard (50...3000).contains(movetimeMilliseconds) else { throw CaptureFailure.invalidEngineResult }
        let (frame, position, reviewRevision, _) = try requireGuidanceState()
        engineTask?.cancel(); recommendation = nil; speechAttempt = nil; speech.cancel()
        let request = AnalysisRequest(id: UUID(), frame: frame.identity, revision: reviewRevision, fen: position.fen, movetimeMilliseconds: movetimeMilliseconds)
        activeAnalysis = request
        let engine = self.engine
        engineTask = Task { @MainActor [weak self] in
            do {
                let result = try await engine.analyze(request)
                guard !Task.isCancelled else { return }
                try await self?.finishEngine(result, request: request)
            } catch {
                if self?.activeAnalysis == request { self?.invalidate("engine-failed-or-stale") }
            }
        }
        return request
    }
    private func finishEngine(_ result: NativeEngineResult, request: AnalysisRequest) async throws {
        guard activeAnalysis == request, result.request == request else { throw CaptureFailure.invalidEngineResult }
        let text = try await rules.speechForLegalMove(fen: request.fen, moveUCI: result.moveUCI)
        let (frame, position, reviewRevision, capturedAt) = try requireGuidanceState()
        guard !Task.isCancelled, activeAnalysis == request, frame.identity == request.frame,
              position.fen == request.fen, reviewRevision == request.revision,
              !text.isEmpty, text.utf8.count <= 512 else { throw CaptureFailure.staleIdentity }
        let permit = SpeechPermit(id: UUID(), request: request, expiresAtHostSeconds: capturedAt + maxAge)
        recommendation = Recommendation(permit: permit, text: text); reason = "reviewed-legal-result-text-ready"
        engineTask = nil
    }
    public func isCurrent(_ permit: SpeechPermit) -> Bool {
        guard recommendation?.permit == permit, activeAnalysis == permit.request else { return false }
        do {
            let (frame, position, reviewRevision, _) = try requireGuidanceState()
            return try now() <= permit.expiresAtHostSeconds && frame.identity == permit.request.frame &&
                position.fen == permit.request.fen && reviewRevision == permit.request.revision
        } catch { return false }
    }
    public func speakRecommendation() async throws {
        guard let recommendation, isCurrent(recommendation.permit) else { throw CaptureFailure.noRecommendation }
        let attempt = UUID(); speech.cancel(); speechAttempt = attempt
        do {
            try await speech.speak(recommendation.text, permit: recommendation.permit, isCurrent: { [weak self] in
                self?.speechAttempt == attempt && self?.isCurrent(recommendation.permit) == true
            })
            guard speechAttempt == attempt, isCurrent(recommendation.permit) else { throw CaptureFailure.staleIdentity }
        } catch {
            // A late completion from an old output must never cancel newer speech.
            if speechAttempt == attempt { invalidate("speech-failed-or-stale") }
            throw error
        }
        // Permit is retained while speech may remain queued/playing; watchdog/new frames revoke it.
    }
    public func tick() {
        do {
            let time = try now()
            if let frame = latestFrame {
                let expired: Bool
                switch frame.captureTime {
                case .trustedReplay(let capturedAt, _): expired = time - capturedAt > maxAge
                case .unknownDAT: expired = time - frame.receivedAtHostSeconds > maxAge
                }
                if expired, reason != "frame-expired" { invalidate("frame-expired"); cancelRecognition(); proposal = nil }
            }
        } catch { cancelRecognition() }
    }
    deinit { watchdog?.cancel(); activeRecognition?.task.cancel(); engineTask?.cancel() }
}
