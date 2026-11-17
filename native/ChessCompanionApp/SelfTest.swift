// Automated acceptance self-test. Compiled only when prepare_app.py is given
// --self-test (Swift flag COMPANION_SELFTEST), and run only when the process is
// launched with --chess-self-test. It drives the same OfflineStudyModel methods
// the UI buttons call. Review boxes are a scripted review fixture, not human
// review. Text only: no speech synthesizer or any audio API is ever used.
#if COMPANION_SELFTEST && os(iOS)
import SwiftUI
import UIKit

private func elapsedMilliseconds(_ start: ContinuousClock.Instant, _ end: ContinuousClock.Instant = .now) -> Double {
    let d = end - start
    return (Double(d.components.seconds) * 1000 + Double(d.components.attoseconds) / 1e15).rounded(toPlaces: 1)
}
private extension Double { func rounded(toPlaces p: Int) -> Double { let m = pow(10, Double(p)); return (self * m).rounded() / m } }
private func jsonValue(_ value: Any?) -> Any { value ?? NSNull() }
/// Search facts the runtime reported with one analysis reply (diagnostics only; never used for advice).
@MainActor private func searchFacts(_ report: SearchReport?) -> [String: Any] {
    guard let report else { return ["searchReported": false] }
    return ["searchReported": true, "nodes": jsonValue(report.nodes.map { Int(clamping: $0) }),
            "nodesPerSecond": jsonValue(report.nodesPerSecond.map { Int(clamping: $0) }), "searchMs": jsonValue(report.elapsedMilliseconds),
            "startup": jsonValue(report.startup), "startupMs": jsonValue(report.startupMilliseconds), "spareUsed": report.spareUsed,
            "fallbackReason": jsonValue(report.fallbackReason)]
}

/// Timestamped observation log shared by the probe backend and the runner.
@MainActor final class SelfTestLog {
    static let shared = SelfTestLog()
    let origin = ContinuousClock.now
    private(set) var events: [[String: Any]] = []
    /// One entry per analysis that returned a move: mode, FEN, move and the runtime's search facts.
    private(set) var searches: [[String: Any]] = []
    func recordSearch(_ info: [String: Any]) { searches.append(info) }
    func now() -> Double { elapsedMilliseconds(origin) }
    func record(_ name: String, _ info: [String: Any] = [:]) {
        var event = info; event["event"] = name; event["tMs"] = now(); events.append(event)
    }
    func events(since index: Int) -> [[String: Any]] { Array(events[min(index, events.count)...]) }
}

/// Pure pass-through around the real backend. It only records when calls start
/// and end; every argument, result and error is forwarded unchanged.
@MainActor final class SelfTestProbeBackend: OfflineBackend {
    private let inner: any OfflineBackend
    private let log: SelfTestLog
    private(set) var validateCalls = 0, analyzeCalls = 0, speechCalls = 0, prewarmCalls = 0, cancelPrewarmCalls = 0
    init(inner: any OfflineBackend, log: SelfTestLog) { self.inner = inner; self.log = log }
    func start() async throws {
        log.record("backend.start.begin")
        do { try await inner.start(); log.record("backend.start.end") } catch { log.record("backend.start.error", ["error": "\(error)"]); throw error }
    }
    func validate(_ fen: String) async throws -> ValidatedPosition {
        validateCalls += 1; log.record("backend.validate.begin", ["fen": fen])
        do { let p = try await inner.validate(fen); log.record("backend.validate.end", ["terminal": p.terminal]); return p }
        catch { log.record("backend.validate.error", ["error": "\(error)"]); throw error }
    }
    func analyze(_ request: AnalysisRequest) async throws -> NativeEngineResult {
        analyzeCalls += 1; log.record("backend.analyze.begin", ["fen": request.fen, "request": request.id.uuidString])
        do {
            let r = try await inner.analyze(request)
            var info = searchFacts((inner as? LocalOfflineBackend)?.searchReport(for: request.id))
            info["move"] = r.moveUCI; info["request"] = request.id.uuidString; info["fen"] = request.fen
            log.record("backend.analyze.reply", info)
            info["mode"] = "study"; log.recordSearch(info)
            return r
        }
        catch { log.record("backend.analyze.error", ["error": "\(error)", "request": request.id.uuidString]); throw error }
    }
    /// Forwarded unchanged (the model ignores the outcome); recorded so checks can see when the model asks.
    func prewarm() async throws {
        prewarmCalls += 1; log.record("backend.prewarm.begin")
        do { try await inner.prewarm(); log.record("backend.prewarm.end") } catch { log.record("backend.prewarm.error", ["error": "\(error)"]); throw error }
    }
    func cancelPrewarm() async throws {
        cancelPrewarmCalls += 1; log.record("backend.cancelPrewarm.begin")
        do { try await inner.cancelPrewarm(); log.record("backend.cancelPrewarm.end") } catch { log.record("backend.cancelPrewarm.error", ["error": "\(error)"]); throw error }
    }
    /// Self-test diagnostics only: the runtime's spare state. Asking keeps (or starts) its one shared spare.
    func spareStatus() async -> String? { await (inner as? LocalOfflineBackend)?.prewarmStatus() }
    func speech(fen: String, move: String) async throws -> String {
        speechCalls += 1; log.record("backend.legalText.begin", ["move": move])
        do { let t = try await inner.speech(fen: fen, move: move); log.record("backend.legalText.end", ["text": t]); return t }
        catch { log.record("backend.legalText.error", ["error": "\(error)"]); throw error }
    }
    func cancel() { log.record("backend.cancel"); inner.cancel() }
    func close() { log.record("backend.close"); inner.close() }
    func observeClosure(_ handler: @escaping @MainActor () -> Void) {
        inner.observeClosure { [log] in log.record("backend.closed"); handler() }
    }
}

/// Pass-through probe for the Replay game: records engine and tracker calls with timestamps and
/// counts any moment both are in flight (must stay 0). Arguments and results are forwarded unchanged.
@MainActor final class SelfTestReplayProbe: ReplayEngineBackend {
    private let inner: LocalOfflineBackend
    private let log: SelfTestLog
    private(set) var validateCalls = 0, analyzeCalls = 0, legalTextCalls = 0, trackerRequests = 0, overlaps = 0, prewarmCalls = 0, cancelPrewarmCalls = 0
    private var engineInFlight = 0, trackerInFlight = 0
    init(inner: LocalOfflineBackend, log: SelfTestLog) { self.inner = inner; self.log = log }
    private func enterEngine() { if trackerInFlight > 0 { overlaps += 1; log.record("replay.VIOLATION.overlap") }; engineInFlight += 1 }
    func enterTracker() { if engineInFlight > 0 { overlaps += 1; log.record("replay.VIOLATION.overlap") }; trackerInFlight += 1; trackerRequests += 1 }
    func leaveTracker() { trackerInFlight -= 1 }
    func start() async throws {
        log.record("replay.engine.start.begin")
        do { try await inner.start(); log.record("replay.engine.start.end") } catch { log.record("replay.engine.start.error", ["error": "\(error)"]); throw error }
    }
    func validate(_ fen: String) async throws -> ValidatedPosition {
        validateCalls += 1; enterEngine(); defer { engineInFlight -= 1 }
        log.record("replay.engine.validate.begin", ["fen": fen])
        do { let p = try await inner.validate(fen); log.record("replay.engine.validate.end", ["fen": p.fen, "terminal": p.terminal]); return p }
        catch { log.record("replay.engine.validate.error", ["error": "\(error)"]); throw error }
    }
    func analyze(_ request: AnalysisRequest) async throws -> NativeEngineResult {
        analyzeCalls += 1; enterEngine(); defer { engineInFlight -= 1 }
        log.record("replay.engine.analyze.begin", ["fen": request.fen, "request": request.id.uuidString, "revision": request.revision, "epoch": request.frame.epoch])
        do {
            let r = try await inner.analyze(request)
            var info = searchFacts(inner.searchReport(for: request.id))
            info["move"] = r.moveUCI; info["request"] = request.id.uuidString; info["fen"] = request.fen
            log.record("replay.engine.analyze.reply", info)
            info["mode"] = "replay"; log.recordSearch(info)
            return r
        }
        catch { log.record("replay.engine.analyze.error", ["error": "\(error)", "request": request.id.uuidString]); throw error }
    }
    /// Forwarded unchanged and recorded. Not counted as engine work for the tracker-overlap counters: a prewarm
    /// carries no position and only ever starts or drops the spare engine.
    func prewarm() async throws {
        prewarmCalls += 1; log.record("replay.engine.prewarm.begin")
        do { try await inner.prewarm(); log.record("replay.engine.prewarm.end") } catch { log.record("replay.engine.prewarm.error", ["error": "\(error)"]); throw error }
    }
    func cancelPrewarm() async throws {
        cancelPrewarmCalls += 1; log.record("replay.engine.cancelPrewarm.begin")
        do { try await inner.cancelPrewarm(); log.record("replay.engine.cancelPrewarm.end") } catch { log.record("replay.engine.cancelPrewarm.error", ["error": "\(error)"]); throw error }
    }
    /// Self-test diagnostics only: the runtime's spare state (asking keeps or starts its one shared spare).
    func spareStatus() async -> String? { await inner.prewarmStatus() }
    /// Self-test diagnostics only: true while this probe's local runtime is running.
    var runtimeRunning: Bool { inner.runtimeRunning }
    /// The app's own rules reply for (FEN, move): legal-move text only, never audio.
    func speech(fen: String, move: String) async throws -> String {
        legalTextCalls += 1; enterEngine(); defer { engineInFlight -= 1 }
        log.record("replay.engine.legalText.begin", ["fen": fen, "move": move])
        do { let t = try await inner.speech(fen: fen, move: move); log.record("replay.engine.legalText.end", ["fen": fen, "move": move, "text": t]); return t }
        catch { log.record("replay.engine.legalText.error", ["fen": fen, "move": move, "error": "\(error)"]); throw error }
    }
    func cancel() { log.record("replay.engine.cancel"); inner.cancel() }
    func close() { log.record("replay.engine.close"); inner.close() }
    func observeClosure(_ handler: @escaping @MainActor () -> Void) {
        inner.observeClosure { [log] in log.record("replay.engine.closed"); handler() }
    }
    func makeTrackerTransport() -> any ReplayTrackerTransport { SelfTestTrackerProbe(inner: inner.makeTrackerTransport(), owner: self, log: log) }
}

/// Records every tracker request and the decoded essentials of its reply (the real bundled tracker).
@MainActor final class SelfTestTrackerProbe: ReplayTrackerTransport {
    private let inner: any ReplayTrackerTransport
    private weak var owner: SelfTestReplayProbe?
    private let log: SelfTestLog
    init(inner: any ReplayTrackerTransport, owner: SelfTestReplayProbe, log: SelfTestLog) { self.inner = inner; self.owner = owner; self.log = log }
    func submit(requestJSON: String, timeoutMilliseconds: Int) async throws -> String {
        owner?.enterTracker(); defer { owner?.leaveTracker() }
        let request = (try? JSONSerialization.jsonObject(with: Data(requestJSON.utf8))) as? [String: Any] ?? [:]
        var info: [String: Any] = ["kind": request["kind"] ?? NSNull(), "requestId": request["requestId"] ?? NSNull()]
        if let frame = request["frame"] as? [String: Any], let identity = frame["identity"] as? [String: Any] {
            info["capturedAtMs"] = frame["capturedAtMs"] ?? NSNull(); info["sequence"] = identity["sequence"] ?? NSNull()
            info["frameSha256"] = identity["frameSha256"] ?? NSNull()
            info["unknownSquares"] = (frame["squares"] as? [String: [String: Any]])?.values.filter { $0["label"] as? String == "unknown" }.count ?? NSNull()
        }
        if let session = request["session"] as? [String: Any] { info["epoch"] = session["epoch"] ?? NSNull() }
        log.record("replay.tracker.begin", info)
        do {
            let reply = try await inner.submit(requestJSON: requestJSON, timeoutMilliseconds: timeoutMilliseconds)
            let object = (try? JSONSerialization.jsonObject(with: Data(reply.utf8))) as? [String: Any] ?? [:]
            var out: [String: Any] = ["requestId": request["requestId"] ?? NSNull()]
            if let state = object["state"] as? [String: Any] {
                out["status"] = state["status"] ?? NSNull(); out["reason"] = state["reason"] ?? NSNull()
                out["revision"] = state["revision"] ?? NSNull(); out["fen"] = state["fen"] ?? NSNull()
                out["lastMove"] = state["lastMove"] ?? NSNull(); out["historyComplete"] = state["historyComplete"] ?? NSNull()
            }
            out["trackingReady"] = object["trackingReady"] ?? NSNull(); out["guidanceAllowed"] = object["guidanceAllowed"] ?? NSNull()
            if let ignored = object["ignored"] { out["ignored"] = ignored }
            if let error = object["error"] { out["error"] = error }
            log.record("replay.tracker.end", out)
            return reply
        } catch { log.record("replay.tracker.error", ["error": "\(error)"]); throw error }
    }
}

/// Pass-through around the real recognizer: forwards bytes and results unchanged and records how
/// long each recognition took (milliseconds), so the report can show recognition time per frame.
actor SelfTestRecognizerProbe: OfflineImageRecognizer {
    private let inner: any OfflineImageRecognizer
    private var durations: [Double] = []
    init(inner: any OfflineImageRecognizer) { self.inner = inner }
    func recognize(_ bytes: Data) async throws -> OfflineBoard {
        let start = ContinuousClock.now
        defer { durations.append(elapsedMilliseconds(start)) }
        return try await inner.recognize(bytes)
    }
    /// Returns and clears the durations recorded since the last call.
    func take() -> [Double] { let out = durations; durations = []; return out }
}

/// Text-only stand-in for OfflineNativeSpeech: never touches AVFoundation.
@MainActor final class SelfTestSilentSpeech: OfflineSpeech {
    static let shared = SelfTestSilentSpeech()
    private(set) var speakRequests = 0
    func speak(_ text: String) throws { speakRequests += 1 }
    func cancel() {}
}

@MainActor final class SelfTestRunner: ObservableObject {
    static let launchArgument = "--chess-self-test"
    static var requested: Bool { ProcessInfo.processInfo.arguments.contains(launchArgument) }
    static let overallTimeoutSeconds = 120
    static let expectedEarlierSimulatorMoves: [StudyFixture: String] = [.starting: "e2e4", .afterE4: "c7c5", .enPassant: "e1d2", .promotion: "e1e2"]

    /// Same recognizer, resources and real local backend as the normal app; the
    /// backend is wrapped only by the recording probe, speech is text-only.
    static func makeModel(resources: StudyResources) -> OfflineStudyModel {
        studyResources = resources
        return OfflineStudyModel(
            makeBackend: {
                let backend = SelfTestProbeBackend(inner: try LocalOfflineBackend(resources: resources), log: .shared)
                SelfTestRunner.currentProbe = backend
                return backend
            },
            recognizer: OfflinePixelRecognizer(resources: resources),
            loadFixture: { try resources.checked($0.asset) }, speech: SelfTestSilentSpeech.shared)
    }
    static var currentProbe: SelfTestProbeBackend?
    /// The app's own bundle resources (for the runtime allowlist check).
    static var studyResources: StudyResources?
    /// The node budget the app sends with every analysis (LocalOfflineBackend.searchBudget).
    static var budgetNodes: Int? { if case .nodes(let count) = LocalOfflineBackend.searchBudget { return count }; return nil }
    /// A search honoured the budget: the engine reports at least the budget and stops within 10% above it.
    static func withinBudget(_ nodes: Int?) -> Bool {
        guard let nodes, let budget = budgetNodes else { return false }
        return nodes >= budget && nodes < budget + budget / 10
    }
    /// Replay model wired exactly like the normal app (real recognizer, real backend and real bundled
    /// tracker in WebKit), wrapped only by the recording probe. It has no speech dependency at all.
    static func makeReplayModel(resources: StudyResources, sequences: [ReplaySequence]) -> ReplayGameModel {
        let recognizer = SelfTestRecognizerProbe(inner: OfflinePixelRecognizer(resources: resources))
        currentRecognizerProbe = recognizer
        return ReplayGameModel(
            makeBackend: {
                let probe = SelfTestReplayProbe(inner: try LocalOfflineBackend(resources: resources), log: .shared)
                SelfTestRunner.currentReplayProbe = probe
                return probe
            },
            recognizer: recognizer,
            loadFrame: { try resources.checked($0.asset) }, sequences: sequences)
    }
    static var currentReplayProbe: SelfTestReplayProbe?
    static var currentRecognizerProbe: SelfTestRecognizerProbe?
    static let specialTimeoutSeconds = 360
    /// Special-move game (1.e4 Nf6 2.e5 d5 3.exd6 e.p. Bf5 4.dxc7 Nbd7 5.cxd8=Q+ Rxd8 6.d4 e6 7.Nc3 Be7
    /// 8.Be3 O-O 9.Qd2 Nb6 10.O-O-O Nbd5 11.Nxd5 Nxd5 12.Bd3 Bxd3 13.Qxd3). Scripted reviewer input for
    /// the review points (frames 0, 20, 21, 23) and the expected tracker FEN after each ply, used here
    /// only to compare. The app never reads these; it bundles no expected positions.
    static let specialFENs = [
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        "rnbqkb1r/pppppppp/5n2/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 1 2",
        "rnbqkb1r/pppppppp/5n2/4P3/8/8/PPPP1PPP/RNBQKBNR b KQkq - 0 2",
        "rnbqkb1r/ppp1pppp/5n2/3pP3/8/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 3",
        "rnbqkb1r/ppp1pppp/3P1n2/8/8/8/PPPP1PPP/RNBQKBNR b KQkq - 0 3",
        "rn1qkb1r/ppp1pppp/3P1n2/5b2/8/8/PPPP1PPP/RNBQKBNR w KQkq - 1 4",
        "rn1qkb1r/ppP1pppp/5n2/5b2/8/8/PPPP1PPP/RNBQKBNR b KQkq - 0 4",
        "r2qkb1r/ppPnpppp/5n2/5b2/8/8/PPPP1PPP/RNBQKBNR w KQkq - 1 5",
        "r2Qkb1r/pp1npppp/5n2/5b2/8/8/PPPP1PPP/RNBQKBNR b KQkq - 0 5",
        "3rkb1r/pp1npppp/5n2/5b2/8/8/PPPP1PPP/RNBQKBNR w KQk - 0 6",
        "3rkb1r/pp1npppp/5n2/5b2/3P4/8/PPP2PPP/RNBQKBNR b KQk - 0 6",
        "3rkb1r/pp1n1ppp/4pn2/5b2/3P4/8/PPP2PPP/RNBQKBNR w KQk - 0 7",
        "3rkb1r/pp1n1ppp/4pn2/5b2/3P4/2N5/PPP2PPP/R1BQKBNR b KQk - 1 7",
        "3rk2r/pp1nbppp/4pn2/5b2/3P4/2N5/PPP2PPP/R1BQKBNR w KQk - 2 8",
        "3rk2r/pp1nbppp/4pn2/5b2/3P4/2N1B3/PPP2PPP/R2QKBNR b KQk - 3 8",
        "3r1rk1/pp1nbppp/4pn2/5b2/3P4/2N1B3/PPP2PPP/R2QKBNR w KQ - 4 9",
        "3r1rk1/pp1nbppp/4pn2/5b2/3P4/2N1B3/PPPQ1PPP/R3KBNR b KQ - 5 9",
        "3r1rk1/pp2bppp/1n2pn2/5b2/3P4/2N1B3/PPPQ1PPP/R3KBNR w KQ - 6 10",
        "3r1rk1/pp2bppp/1n2pn2/5b2/3P4/2N1B3/PPPQ1PPP/2KR1BNR b - - 7 10",
        "3r1rk1/pp2bppp/4pn2/3n1b2/3P4/2N1B3/PPPQ1PPP/2KR1BNR w - - 8 11",
        "3r1rk1/pp2bppp/4pn2/3N1b2/3P4/4B3/PPPQ1PPP/2KR1BNR b - - 0 11",
        "3r1rk1/pp2bppp/4p3/3n1b2/3P4/4B3/PPPQ1PPP/2KR1BNR w - - 0 12",
        "3r1rk1/pp2bppp/4p3/3n1b2/3P4/3BB3/PPPQ1PPP/2KR2NR b - - 1 12",
        "3r1rk1/pp2bppp/4p3/3n4/3P4/3bB3/PPPQ1PPP/2KR2NR w - - 0 13",
        "3r1rk1/pp2bppp/4p3/3n4/3P4/3QB3/PPP2PPP/2KR2NR b - - 0 13",
    ]
    static let specialSAN = ["e4", "Nf6", "e5", "d5", "exd6", "Bf5", "dxc7", "Nbd7", "cxd8=Q+", "Rxd8", "d4", "e6", "Nc3",
                             "Be7", "Be3", "O-O", "Qd2", "Nb6", "O-O-O", "Nbd5", "Nxd5", "Nxd5", "Bd3", "Bxd3", "Qxd3"]
    /// Plies analyzed in the full special game: after en passant, promotion, recapture, both castlings, final.
    static let specialAnalyzedPlies: Set<Int> = [0, 5, 9, 10, 16, 19, 25]
    static let replayTimeoutSeconds = 240
    /// Scripted reviewer input (typed FENs for 1.e4 e5 2.Nf3 Nc6 3.Bc4 Nf6), written here as a
    /// reviewer would type them. The app never reads these; it bundles no expected positions.
    static let scriptedReplayFENs = [
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
        "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2",
        "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3",
        "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3",
        "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4",
    ]
    static let expectedReplaySAN = ["e4", "e5", "Nf3", "Nc6", "Bc4", "Nf6"]

    @Published private(set) var status = "Self-test: waiting to start"
    private var checks: [[String: Any]] = []
    private var started = false, finished = false
    private var startDate = Date()
    private let log = SelfTestLog.shared
    private let scriptedLabel = "scripted review fixture, not human review"

    func run(model: OfflineStudyModel, replay: ReplayGameModel, modeState: AppModeState) async {
        guard !started else { return }
        started = true; startDate = Date()
        status = "Self-test running…"
        log.record("selftest.begin")
        // Keep the screen awake for the duration of the run only; a real screen lock deactivates the app,
        // which (correctly) closes the engine and would end the remaining checks early.
        UIApplication.shared.isIdleTimerDisabled = true
        defer { UIApplication.shared.isIdleTimerDisabled = false }
        log.record("app.state", ["applicationState": UIApplication.shared.applicationState.rawValue])
        let center = NotificationCenter.default
        let observers = [(UIApplication.willResignActiveNotification, "app.willResignActive"),
                         (UIApplication.didEnterBackgroundNotification, "app.didEnterBackground"),
                         (UIApplication.didBecomeActiveNotification, "app.didBecomeActive")].map { name, label in
            center.addObserver(forName: name, object: nil, queue: .main) { _ in
                MainActor.assumeIsolated { SelfTestLog.shared.record(label) }
            }
        }
        defer { observers.forEach(center.removeObserver) }
        let work = Task { @MainActor in await self.runAll(model) }
        let watchdog = Task { @MainActor in
            try? await Task.sleep(for: .seconds(Self.overallTimeoutSeconds))
            guard !Task.isCancelled, !self.finished else { return }
            work.cancel()
            self.log.record("selftest.timeout")
            self.finish(incomplete: true, reason: "overall timeout of \(Self.overallTimeoutSeconds) s reached")
        }
        await work.value
        watchdog.cancel()
        // Replay game checks run after the study checks, under their own separate watchdog.
        if !finished && !Task.isCancelled {
            let replayWork = Task { @MainActor in await self.runReplay(replay, study: model, modeState: modeState) }
            let replayWatchdog = Task { @MainActor in
                try? await Task.sleep(for: .seconds(Self.replayTimeoutSeconds))
                guard !Task.isCancelled, !self.finished else { return }
                replayWork.cancel()
                self.log.record("selftest.replay.timeout")
                self.finish(incomplete: true, reason: "replay timeout of \(Self.replayTimeoutSeconds) s reached")
            }
            await replayWork.value
            replayWatchdog.cancel()
        }
        // Special-move replay game checks, after the first game, under their own watchdog.
        if !finished && !Task.isCancelled {
            let specialWork = Task { @MainActor in await self.runSpecialReplay(replay, modeState: modeState) }
            let specialWatchdog = Task { @MainActor in
                try? await Task.sleep(for: .seconds(Self.specialTimeoutSeconds))
                guard !Task.isCancelled, !self.finished else { return }
                specialWork.cancel()
                self.log.record("selftest.special.timeout")
                self.finish(incomplete: true, reason: "special replay timeout of \(Self.specialTimeoutSeconds) s reached")
            }
            await specialWork.value
            specialWatchdog.cancel()
        }
        // Occupancy-tracker wiring checks (setting off as launched; on via the test switch), own watchdog.
        if !finished && !Task.isCancelled {
            let occupancyWork = Task { @MainActor in await self.runOccupancyChecks() }
            let occupancyWatchdog = Task { @MainActor in
                try? await Task.sleep(for: .seconds(Self.occupancyTimeoutSeconds))
                guard !Task.isCancelled, !self.finished else { return }
                occupancyWork.cancel()
                self.log.record("selftest.occupancy.timeout")
                self.finish(incomplete: true, reason: "occupancy tracker timeout of \(Self.occupancyTimeoutSeconds) s reached")
            }
            await occupancyWork.value
            occupancyWatchdog.cancel()
        }
        if !finished && !Task.isCancelled { searchBudgetCheck() }
        if !finished { finish(incomplete: Task.isCancelled, reason: nil) }
    }

    // MARK: - Helpers driving the same model methods as the UI

    private func pause(_ ms: Int) async { try? await Task.sleep(for: .milliseconds(ms)) }
    /// Waits until this check's engine analysis request has left the app (its probe logged `event`), then
    /// `settleMs` more, so a switch lands while that search runs. A fixed pause does not work with a fast
    /// node-budget search on a pre-started engine, which can finish inside it. Returns ms since `start`, or nil
    /// if the request was not sent within `limitMs` (the caller then fails its precondition).
    private func waitForAnalysisSent(since index: Int, event: String, from start: ContinuousClock.Instant,
                                     limitMs: Double = 3000, settleMs: Int = 30) async -> Double? {
        while !log.events(since: index).contains(where: { $0["event"] as? String == event }) {
            if Task.isCancelled || elapsedMilliseconds(start) > limitMs { return nil }
            await pause(2)
        }
        await pause(settleMs)
        return elapsedMilliseconds(start)
    }
    /// Waits for an event logged since `index`; true if it came within `limitMs`.
    private func waitForEvent(since index: Int, _ event: String, limitMs: Double = 3000) async -> Bool {
        let start = ContinuousClock.now
        while !log.events(since: index).contains(where: { $0["event"] as? String == event }) {
            if Task.isCancelled || elapsedMilliseconds(start) > limitMs { return false }
            await pause(5)
        }
        return true
    }
    /// Polls the runtime's spare state until it is "ready" (at most `limitMs`). Returns the last state and the wait.
    private func waitSpareReady(limitMs: Double = 15_000, _ status: () async -> String?) async -> (String?, Double) {
        let start = ContinuousClock.now
        var last: String?
        while !Task.isCancelled && elapsedMilliseconds(start) <= limitMs {
            last = await status()
            if last == "ready" { break }
            await pause(100)
        }
        log.record("selftest.spare-status", ["spare": last ?? NSNull(), "waitedMs": elapsedMilliseconds(start)])
        return (last, elapsedMilliseconds(start))
    }
    /// Waits until the model is not busy; returns elapsed ms or nil on timeout.
    private func waitIdle(_ model: OfflineStudyModel, from start: ContinuousClock.Instant, timeout: Double = 20_000) async -> Double? {
        while model.busy {
            if Task.isCancelled || elapsedMilliseconds(start) > timeout { return nil }
            await pause(10)
        }
        return elapsedMilliseconds(start)
    }
    private func ensureEngine(_ model: OfflineStudyModel, _ details: inout [String: Any], _ timings: inout [String: Double]) async -> Bool {
        if model.ready { return true }
        let t = ContinuousClock.now
        model.start()                                   // "Start local engine"
        timings["engineStart"] = await waitIdle(model, from: t, timeout: 30_000) ?? -1
        details["engineStatus"] = model.status
        return model.ready
    }
    private struct Pipeline { var recognized = false; var complete = false; var unknown = 0; var validated = false; var move: String?; var text: String? }
    /// Select → read board → sample FEN → scripted review → validate → (analyze).
    private func pipeline(_ model: OfflineStudyModel, _ fixture: StudyFixture, fen: String?, review: Set<ReviewField> = Set(ReviewField.allCases),
                          analyze: Bool, _ details: inout [String: Any], _ timings: inout [String: Double]) async -> Pipeline {
        var out = Pipeline()
        model.selectFixture(fixture)                    // Position picker
        guard await ensureEngine(model, &details, &timings) else { details["failure"] = "engine not ready"; return out }
        var t = ContinuousClock.now
        model.recognizeFixture()                        // "Read board"
        timings["recognition"] = await waitIdle(model, from: t) ?? -1
        out.recognized = model.board != nil
        out.complete = model.board?.complete == true
        out.unknown = model.board?.squares.values.filter { $0 == "unknown" }.count ?? 64
        details["recognitionStatus"] = model.status
        details["unknownSquares"] = out.unknown
        guard out.recognized, let fen else { return out }
        model.editFEN(fen)                              // "Use sample FEN" / FEN field
        for field in ReviewField.allCases where review.contains(field) { model.setReview(field, checked: true) } // Toggles
        details["reviewBoxesTicked"] = review.count
        details["review"] = scriptedLabel
        details["canValidate"] = model.canValidate
        t = ContinuousClock.now
        model.validate()                                // "Validate reviewed position"
        timings["validation"] = await waitIdle(model, from: t) ?? -1
        out.validated = model.reviewed
        details["validationStatus"] = model.status
        guard analyze, out.validated else { return out }
        details["canAnalyze"] = model.canAnalyze
        t = ContinuousClock.now
        model.analyze()                                 // "Analyze offline position"
        timings["analysis"] = await waitIdle(model, from: t) ?? -1
        out.move = model.move; out.text = model.recommendation
        details["analysisStatus"] = model.status
        return out
    }
    private func record(_ name: String, pass: Bool, details: [String: Any], timings: [String: Double] = [:], label: String? = nil, events: [[String: Any]]? = nil) {
        var check: [String: Any] = ["name": name, "pass": pass, "details": details, "timingsMs": timings, "finishedAtMs": log.now()]
        if let label { check["label"] = label }
        if let events { check["events"] = events }
        checks.append(check)
        status = "Self-test running… \(checks.count) checks done (\(checks.filter { $0["pass"] as? Bool == true }.count) passed)"
        writeReport(incomplete: true, reason: "in progress")
    }

    // MARK: - Scenarios

    private func runAll(_ model: OfflineStudyModel) async {
        // 1–4. Playable fixtures end to end.
        for fixture in [StudyFixture.starting, .afterE4, .enPassant, .promotion] {
            if Task.isCancelled { return }
            var d: [String: Any] = ["fixture": fixture.title], t: [String: Double] = [:]
            let r = await pipeline(model, fixture, fen: fixture.referenceFEN, analyze: true, &d, &t)
            d["moveUCI"] = r.move ?? NSNull(); d["recommendationText"] = r.text ?? NSNull()
            let expected = Self.expectedEarlierSimulatorMoves[fixture] ?? ""
            d["earlierSimulatorMove"] = expected
            d["matchesEarlierSimulatorMove_informationOnly"] = r.move == expected
            record("fixture-\(fixture.rawValue)-end-to-end", pass: r.complete && r.validated && r.move != nil && r.text != nil,
                   details: d, timings: t, label: scriptedLabel)
        }
        if Task.isCancelled { return }

        // 5. Obstructed board blocks.
        do {
            var d: [String: Any] = ["fixture": StudyFixture.occluded.title], t: [String: Double] = [:]
            let probeBefore = (Self.currentProbe?.validateCalls ?? 0, Self.currentProbe?.analyzeCalls ?? 0)
            let r = await pipeline(model, .occluded, fen: nil, analyze: false, &d, &t)
            // Attempt the gated actions anyway, exactly as UI taps would.
            model.editFEN(StudyFixture.starting.referenceFEN!)
            for field in ReviewField.allCases { model.setReview(field, checked: true) }
            d["canValidateAfterFullScriptedReview"] = model.canValidate
            model.validate(); await pause(50)
            d["canAnalyze"] = model.canAnalyze
            model.analyze(); await pause(50)
            let probeAfter = (Self.currentProbe?.validateCalls ?? 0, Self.currentProbe?.analyzeCalls ?? 0)
            d["backendValidateCallsDuringCheck"] = probeAfter.0 - probeBefore.0
            d["backendAnalyzeCallsDuringCheck"] = probeAfter.1 - probeBefore.1
            d["recommendation"] = model.recommendation ?? NSNull()
            let pass = r.recognized && !r.complete && r.unknown == 16 && !model.canValidate && !model.reviewed
                && !model.canAnalyze && model.recommendation == nil && model.move == nil && probeAfter == probeBefore
            record("obstructed-board-blocks", pass: pass, details: d, timings: t)
        }
        if Task.isCancelled { return }

        // 6. Four of five review boxes → validation blocked.
        do {
            var d: [String: Any] = [:], t: [String: Double] = [:]
            let before = Self.currentProbe?.validateCalls ?? 0
            model.selectFixture(.afterE4) // force a fresh selection before returning to starting
            let r = await pipeline(model, .starting, fen: StudyFixture.starting.referenceFEN,
                                   review: Set(ReviewField.allCases).subtracting([.counters]), analyze: false, &d, &t)
            let calls = (Self.currentProbe?.validateCalls ?? 0) - before
            d["backendValidateCalls"] = calls
            let pass = r.complete && d["canValidate"] as? Bool == false && !r.validated && calls == 0 && !model.canAnalyze && model.recommendation == nil
            record("four-of-five-review-blocks-validation", pass: pass, details: d, timings: t, label: scriptedLabel)
        }
        if Task.isCancelled { return }

        // 7. Invalid FEN (side to move x, matching pieces) → rejected.
        do {
            var d: [String: Any] = [:], t: [String: Double] = [:]
            let invalid = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR x KQkq - 0 1"
            d["fen"] = invalid
            let r = await pipeline(model, .starting, fen: invalid, analyze: false, &d, &t)
            d["piecesMatchRecognition"] = model.board?.matchesPlacement(invalid) ?? false
            let pass = r.complete && !r.validated && !model.canAnalyze && model.recommendation == nil
                && model.status.contains("validation failed")
            record("invalid-fen-side-to-move-x-rejected", pass: pass, details: d, timings: t, label: scriptedLabel)
        }
        if Task.isCancelled { return }

        // 8. Untick one review box after a recommendation → revoked.
        do {
            var d: [String: Any] = [:], t: [String: Double] = [:]
            model.selectFixture(.afterE4)
            let r = await pipeline(model, .starting, fen: StudyFixture.starting.referenceFEN, analyze: true, &d, &t)
            d["recommendationBefore"] = r.text ?? NSNull()
            model.setReview(.counters, checked: false)  // Toggle off
            let immediately = model.recommendation == nil && model.move == nil
            await pause(1500) // any late reply must not restore it
            d["recommendationAfter1500ms"] = model.recommendation ?? NSNull()
            let pass = r.text != nil && immediately && model.recommendation == nil && model.move == nil && !model.reviewed && !model.canAnalyze
            record("untick-review-revokes-recommendation", pass: pass, details: d, timings: t, label: scriptedLabel)
        }
        if Task.isCancelled { return }

        // 9. In-flight switch.
        do {
            var d: [String: Any] = [:], t: [String: Double] = [:]
            model.selectFixture(.afterE4)
            let r = await pipeline(model, .starting, fen: StudyFixture.starting.referenceFEN, analyze: false, &d, &t)
            var timeline: [[String: Any]] = []
            var pass = false
            if r.validated && model.canAnalyze {
                let firstEvent = log.events.count
                let analysisStart = ContinuousClock.now
                model.analyze()
                log.record("selftest.analyze-called", ["fixture": "starting"])
                let sentMs = await waitForAnalysisSent(since: firstEvent, event: "backend.analyze.begin", from: analysisStart)
                let busyAtSwitch = model.busy
                let replyBeforeSwitch = log.events(since: firstEvent).contains { ($0["event"] as? String) == "backend.analyze.reply" || ($0["event"] as? String) == "backend.analyze.error" }
                log.record("selftest.switch", ["to": "afterE4", "busyAtSwitch": busyAtSwitch, "msAfterAnalyze": elapsedMilliseconds(analysisStart)])
                model.selectFixture(.afterE4)
                var everRecommendation = false, everMove = false, firstViolationMs: Double?
                let window = ContinuousClock.now
                while elapsedMilliseconds(window) < 3000 { // 1 s search + 2 s grace
                    if model.recommendation != nil || model.move != nil {
                        everRecommendation = everRecommendation || model.recommendation != nil
                        everMove = everMove || model.move != nil
                        if firstViolationMs == nil { firstViolationMs = log.now(); log.record("selftest.VIOLATION.recommendation-visible") }
                    }
                    await pause(10)
                }
                log.record("selftest.window-end", ["fixture": model.fixture.rawValue, "recommendationNil": model.recommendation == nil])
                timeline = log.events(since: firstEvent)
                let switchMs = timeline.first { ($0["event"] as? String) == "selftest.switch" }?["tMs"] as? Double ?? 0
                let late = timeline.filter { (($0["event"] as? String) ?? "").hasPrefix("backend.analyze.") && ($0["event"] as? String) != "backend.analyze.begin" }
                d["analysisOutcomeEvents"] = late
                d["lateReplyAfterSwitch"] = late.contains { ($0["tMs"] as? Double ?? 0) > switchMs }
                d["legalTextRequestsAfterSwitch"] = timeline.filter { ($0["event"] as? String) == "backend.legalText.begin" && ($0["tMs"] as? Double ?? 0) > switchMs }.count
                d["busyAtSwitch"] = busyAtSwitch
                d["engineReplyBeforeSwitch"] = replyBeforeSwitch
                d["preconditionSearchStillRunningAtSwitch"] = busyAtSwitch && !replyBeforeSwitch && sentMs != nil
                d["analysisRequestSentThenSettledMs"] = sentMs ?? NSNull()
                d["recommendationEverVisible"] = everRecommendation
                d["moveEverSet"] = everMove
                d["firstViolationMs"] = firstViolationMs ?? NSNull()
                d["fixtureAfter"] = model.fixture.rawValue
                d["observationWindowMs"] = 3000
                pass = sentMs != nil && busyAtSwitch && !replyBeforeSwitch && !everRecommendation && !everMove && model.recommendation == nil && model.fixture == .afterE4
            } else { d["failure"] = "could not reach a validated starting position" }
            record("in-flight-switch-no-stale-recommendation", pass: pass, details: d, timings: t, label: scriptedLabel, events: timeline)
        }
        if Task.isCancelled { return }

        // 10. Recovery: the interrupted engine still serves the newly selected position.
        do {
            var d: [String: Any] = [:], t: [String: Double] = [:]
            let r = await pipeline(model, .afterE4, fen: StudyFixture.afterE4.referenceFEN, analyze: true, &d, &t)
            d["moveUCI"] = r.move ?? NSNull(); d["recommendationText"] = r.text ?? NSNull()
            record("post-switch-recovery-after-e4", pass: r.validated && r.move != nil && r.text != nil, details: d, timings: t, label: scriptedLabel)
        }
        if Task.isCancelled { return }

        // 11. Background handler (same handler the scene-phase change calls).
        do {
            var d: [String: Any] = [:]
            let hadRecommendation = model.recommendation != nil
            d["recommendationBefore"] = model.recommendation ?? NSNull()
            model.setActive(false)
            let revoked = model.recommendation == nil && model.move == nil && model.checks.isEmpty && !model.reviewed && !model.ready
            await pause(1500)
            d["recommendationAfter1500ms"] = model.recommendation ?? NSNull()
            d["statusWhileInactive"] = model.status
            model.setActive(true)
            d["readyAfterReturn"] = model.ready
            d["canAnalyzeAfterReturn"] = model.canAnalyze
            let pass = hadRecommendation && revoked && model.recommendation == nil && !model.ready && !model.canAnalyze
            record("background-handler-revokes", pass: pass, details: d, label: "handler invoked in-process, not real backgrounding")
        }
        if Task.isCancelled { return }

        // 12. Reset clears everything.
        do {
            var d: [String: Any] = [:], t: [String: Double] = [:]
            let r = await pipeline(model, .enPassant, fen: StudyFixture.enPassant.referenceFEN, analyze: true, &d, &t)
            d["recommendationBefore"] = r.text ?? NSNull()
            model.reset()                               // "Reset study"
            await pause(1500)
            d["statusAfter"] = model.status
            let pass = r.text != nil && model.recommendation == nil && model.move == nil && model.board == nil && model.imageBytes == nil
                && model.fen.isEmpty && model.checks.isEmpty && !model.reviewed && !model.ready && model.fixture == .starting
            record("reset-clears", pass: pass, details: d, timings: t, label: scriptedLabel)
        }
        if Task.isCancelled { return }

        // 13. Pre-started engine: after a complete review the spare is ready, and the next analysis takes it
        // and advises the reviewed position only (reply FEN checked, text regenerated by the app's rules).
        do {
            var d: [String: Any] = [:], t: [String: Double] = [:]
            let fen = StudyFixture.afterE4.referenceFEN!
            let r = await pipeline(model, .afterE4, fen: fen, analyze: false, &d, &t)
            var spare: String?, reply: [String: Any]?
            if r.validated, let probe = Self.currentProbe {
                let (state, waited) = await waitSpareReady { await probe.spareStatus() }
                spare = state; t["spareReady"] = waited
                if spare == "ready" && model.canAnalyze {
                    let first = log.events.count, start = ContinuousClock.now
                    model.analyze()
                    t["analysis"] = await waitIdle(model, from: start) ?? -1
                    reply = log.events(since: first).first { $0["event"] as? String == "backend.analyze.reply" }
                }
            }
            d["spareBeforeAnalysis"] = spare ?? NSNull(); d["analysisReply"] = reply ?? NSNull()
            d["moveUCI"] = model.move ?? NSNull(); d["recommendationText"] = model.recommendation ?? NSNull()
            let pass = r.validated && spare == "ready" && reply?["fen"] as? String == fen && reply?["move"] as? String == model.move
                && reply?["startup"] as? String == "spare" && reply?["spareUsed"] as? Bool == true && Self.withinBudget(reply?["nodes"] as? Int)
                && model.recommendation != nil && model.fixture == .afterE4
            record("prewarm-spare-serves-reviewed-position", pass: pass, details: d, timings: t, label: scriptedLabel)
        }
        if Task.isCancelled { return }

        // 14. Un-ticking a review box discards the spare: asking afterwards has to start a NEW one ("starting"),
        // where a kept spare would answer "ready".
        do {
            var d: [String: Any] = [:], t: [String: Double] = [:]
            let r = await pipeline(model, .enPassant, fen: StudyFixture.enPassant.referenceFEN, analyze: false, &d, &t)
            var spare: String?, after: String?, cancelled = false
            if r.validated, let probe = Self.currentProbe {
                let (state, waited) = await waitSpareReady { await probe.spareStatus() }
                spare = state; t["spareReady"] = waited
                let first = log.events.count
                model.setReview(.counters, checked: false)       // Toggle off
                cancelled = await waitForEvent(since: first, "backend.cancelPrewarm.end")
                after = await probe.spareStatus()
                log.record("selftest.cleanup", ["discard": "diagnostic spare"])
                try? await probe.cancelPrewarm()                 // drop the spare this diagnostic query started
            }
            d["spareBeforeUntick"] = spare ?? NSNull(); d["modelCancelledPrewarm"] = cancelled; d["spareStateWhenAskedAfterUntick"] = after ?? NSNull()
            let pass = r.validated && spare == "ready" && cancelled && after == "starting"
                && model.recommendation == nil && model.move == nil && !model.reviewed && !model.canAnalyze
            record("untick-review-discards-spare", pass: pass, details: d, timings: t, label: scriptedLabel)
        }
        if Task.isCancelled { return }

        // 15. Runtime allowlist: exactly one asset and two command kinds were added; anything else is still refused.
        model.reset()                                       // close the study runtime first (one engine page at a time)
        await allowlistCheck()
    }

    /// The bundled runtime must refuse a manifest with an unknown (or missing) asset, and must refuse an unknown
    /// command kind, or a prewarm that claims the replay mode, before anything reaches the engine page.
    private func allowlistCheck() async {
        var d: [String: Any] = [:]
        guard let resources = Self.studyResources, let directory = try? resources.runtimeDirectory() else {
            record("runtime-allowlist-refuses-unknown-asset-and-kind", pass: false, details: ["failure": "no runtime directory"]); return
        }
        let manager = FileManager.default
        /// nil: the variant could not be written; true: construction refused it; false: accepted.
        func refused(_ edit: (inout [String: Any]) -> Void) -> Bool? {
            let temp = manager.temporaryDirectory.appendingPathComponent("selftest-allowlist-\(UUID().uuidString)", isDirectory: true)
            defer { try? manager.removeItem(at: temp) }
            do {
                try manager.createDirectory(at: temp, withIntermediateDirectories: true)
                guard var manifest = try JSONSerialization.jsonObject(with: Data(contentsOf: directory.appendingPathComponent("runtime-manifest.json"))) as? [String: Any],
                      var assets = manifest["assets"] as? [String: Any] else { return nil }
                edit(&assets); manifest["assets"] = assets
                try JSONSerialization.data(withJSONObject: manifest).write(to: temp.appendingPathComponent("runtime-manifest.json"))
            } catch { return nil }
            do { _ = try NativeEngineRuntime(resourceDirectory: temp); return false } catch { return true }
        }
        let unchanged = refused { _ in }
        let extraAsset = refused { $0["core/unknown.js"] = $0["runtime.js"] }
        let missingPrewarm = refused { $0.removeValue(forKey: "core/prewarmed-engine.js") }
        d["manifest"] = ["unchangedRefused": jsonValue(unchanged), "extraAssetRefused": jsonValue(extraAsset), "withoutPrewarmedEngineRefused": jsonValue(missingPrewarm)]
        // Live: the real bundle in its own engine page.
        var outcomes: [String: String] = [:]
        var live = false
        if let runtime = try? NativeEngineRuntime(resourceDirectory: directory) {
            do {
                try await runtime.start()
                live = runtime.isReady
                let swiftRefusal = "Runtime not ready or command invalid."
                let cases: [(String, [String: Any])] = [
                    ("prewarm", ["kind": "prewarm"]), ("cancelPrewarm", ["kind": "cancelPrewarm"]),
                    ("unknownKind", ["kind": "warmup"]), ("uciGo", ["kind": "go"]), ("caseVariant", ["kind": "Prewarm"]),
                    ("prewarmWithReplayMode", ["kind": "prewarm", "mode": "trusted-replay"]),
                ]
                for (label, fields) in cases {
                    var command = fields; command["schemaVersion"] = 1; command["requestId"] = "allowlist-\(label)"
                    let text = String(data: try JSONSerialization.data(withJSONObject: command, options: [.sortedKeys]), encoding: .utf8)!
                    do {
                        let reply = try JSONSerialization.jsonObject(with: Data(try await runtime.submit(commandJSON: text, timeoutMilliseconds: 5_000).utf8)) as? [String: Any] ?? [:]
                        let keys = Set(reply.keys)
                        outcomes[label] = keys == ["schemaVersion", "requestId", "kind", "runtime", "spare"] || keys == ["schemaVersion", "requestId", "kind", "runtime", "cancelled"]
                            ? "accepted" : "accepted-unexpected-keys"
                    } catch NativeEngineRuntimeError.unavailable(let message) where message == swiftRefusal {
                        outcomes[label] = "refused-before-send"
                    } catch { outcomes[label] = "error: \(error)" }
                }
                // A prewarm must never cancel a pending real request (it is refused instead). A 100,000-node analysis
                // stands in for any engine or tracker request: the runtime has one pending slot for all of them.
                let identity: [String: Any] = ["sessionId": "allowlist", "epoch": 1, "sequence": 1, "frameSha256": String(repeating: "a", count: 64), "revision": 1]
                let analyzeCommand: [String: Any] = ["schemaVersion": 1, "requestId": "allowlist-held-analysis", "kind": "analyze", "confirmation": true,
                                                     "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "nodes": 100_000, "identity": identity]
                let analyzeText = String(data: try JSONSerialization.data(withJSONObject: analyzeCommand, options: [.sortedKeys]), encoding: .utf8)!
                let held = Task { @MainActor () -> String in
                    do { _ = try await runtime.submit(commandJSON: analyzeText, timeoutMilliseconds: 30_000); return "reply" }
                    catch NativeEngineRuntimeError.cancelled { return "cancelled" }
                    catch NativeEngineRuntimeError.timedOut { return "timed-out" } catch { return "error: \(error)" }
                }
                await pause(20)                              // the analysis is now the runtime's pending request
                do { _ = try await runtime.submit(commandJSON: #"{"kind":"prewarm","requestId":"allowlist-prewarm-while-busy","schemaVersion":1}"#, timeoutMilliseconds: 5_000)
                     outcomes["prewarmWhileAnalysisPending"] = "accepted" }
                catch NativeEngineRuntimeError.unavailable(let message) where message == "Runtime busy; prewarm skipped." { outcomes["prewarmWhileAnalysisPending"] = "refused-busy" }
                catch { outcomes["prewarmWhileAnalysisPending"] = "error: \(error)" }
                outcomes["pendingAnalysisOutcome"] = await held.value
                // Only a real reply passes. A timeout is its own non-pass outcome (slow machine or a hang), never success.
                if outcomes["pendingAnalysisOutcome"] == "timed-out" {
                    d["pendingAnalysisTimedOut"] = "the held analysis did not reply within 30 s; counted as not passed (slow machine or engine hang)"
                }
                live = live && runtime.isReady
            } catch { outcomes["start"] = "error: \(error)" }
            runtime.close()
        }
        d["liveCommands"] = outcomes; d["runtimeStayedReady"] = live
        let pass = unchanged == false && extraAsset == true && missingPrewarm == true && live
            && outcomes["prewarm"] == "accepted" && outcomes["cancelPrewarm"] == "accepted"
            && ["unknownKind", "uciGo", "caseVariant", "prewarmWithReplayMode"].allSatisfy { outcomes[$0] == "refused-before-send" }
            && outcomes["prewarmWhileAnalysisPending"] == "refused-busy" && outcomes["pendingAnalysisOutcome"] == "reply"
        record("runtime-allowlist-refuses-unknown-asset-and-kind", pass: pass, details: d)
    }

    // MARK: - Replay game scenarios (real recognition, real bundled tracker in WebKit, real engine)

    private func waitReplayIdle(_ r: ReplayGameModel, from start: ContinuousClock.Instant, timeout: Double = 30_000) async -> Double? {
        while r.busy {
            if Task.isCancelled || elapsedMilliseconds(start) > timeout { return nil }
            await pause(10)
        }
        return elapsedMilliseconds(start)
    }
    private func trackerEvents(since index: Int) -> [[String: Any]] {
        log.events(since: index).filter { (($0["event"] as? String) ?? "").hasPrefix("replay.tracker.") }
    }
    /// One "Next frame" tap. Returns a summary including tracker request/reply pairs for this step.
    private func replayStep(_ r: ReplayGameModel) async -> [String: Any] {
        let first = log.events.count, t = ContinuousClock.now
        r.step()
        let clearedAtTap = r.recommendation == nil && r.move == nil && !r.canAnalyze
        let ms = await waitReplayIdle(r, from: t) ?? -1
        let tracker = trackerEvents(since: first)
        let recognition = await Self.currentRecognizerProbe?.take() ?? []
        return ["frame": r.frameLabel, "recommendationClearedAtTap": clearedAtTap, "recognitionMs": recognition,
                "trackerLastReason": tracker.last { $0["event"] as? String == "replay.tracker.end" }?["reason"] ?? NSNull(), "frameIndex": r.frameIndex ?? NSNull(), "interruption": r.showingInterruption,
                "phase": "\(r.phase)", "trackedFEN": r.trackedFEN ?? NSNull(), "lastMoveSAN": r.lastMoveSAN ?? NSNull(),
                "trackerRevision": r.trackedRevision ?? NSNull(), "status": r.status, "stepMs": ms,
                "unknownSquares": r.board?.squares.values.filter { $0 == "unknown" }.count ?? NSNull(),
                "trackerRequests": tracker.filter { $0["event"] as? String == "replay.tracker.begin" }.count, "trackerEvents": tracker]
    }
    /// Scripted review (labelled; not human review) of the shown frame, then "Confirm review".
    private func replayReview(_ r: ReplayGameModel, fen: String) async -> [String: Any] {
        let first = log.events.count
        r.editFEN(fen)
        for field in ReviewField.allCases { r.setReview(field, checked: true) }
        let canConfirm = r.canConfirmReview
        let t = ContinuousClock.now
        r.confirmReview()
        let ms = await waitReplayIdle(r, from: t) ?? -1
        return ["review": scriptedLabel, "fen": fen, "canConfirmBefore": canConfirm, "phase": "\(r.phase)", "reviewEpoch": r.reviewEpoch,
                "trackedFEN": r.trackedFEN ?? NSNull(), "status": r.status, "reviewToTrackingMs": ms, "trackerEvents": trackerEvents(since: first)]
    }
    /// "Analyze tracked position". Records FEN, move, text, timings and the app's own rules reply.
    private func replayAnalyze(_ r: ReplayGameModel, ply: Int) async -> [String: Any] {
        let first = log.events.count, identity = r.currentIdentity
        let t = ContinuousClock.now
        r.analyze()
        let ms = await waitReplayIdle(r, from: t) ?? -1
        let events = log.events(since: first)
        let rules = events.first { $0["event"] as? String == "replay.engine.legalText.end" }
        let move = r.move
        let legal = rules != nil && rules?["fen"] as? String == identity?.fen && rules?["move"] as? String == move
            && rules?["text"] as? String == r.recommendation
        let analyzeBegin = events.first { $0["event"] as? String == "replay.engine.analyze.begin" }?["tMs"] as? Double
        let analyzeEnd = events.first { $0["event"] as? String == "replay.engine.analyze.reply" }?["tMs"] as? Double
        return ["ply": ply, "fen": identity?.fen ?? NSNull(), "trackerRevision": identity?.trackerRevision ?? NSNull(),
                "reviewEpoch": identity?.reviewEpoch ?? NSNull(), "moveUCI": move ?? NSNull(), "recommendationText": r.recommendation ?? NSNull(),
                "legalPerAppRulesReply": legal, "rulesReply": rules ?? NSNull(), "analysisTotalMs": ms,
                "engineSearchMs": (analyzeBegin != nil && analyzeEnd != nil) ? analyzeEnd! - analyzeBegin! : NSNull(),
                "identityStillCurrent": r.result?.identity == r.currentIdentity && r.result != nil]
    }

    /// A normal step must leave the model tracking the expected position after exactly two observations.
    private static func tracked(_ s: [String: Any], fen: String) -> Bool {
        s["phase"] as? String == "tracking" && s["trackedFEN"] as? String == fen && s["trackerRequests"] as? Int == 2
    }

    private func runReplay(_ r: ReplayGameModel, study: OfflineStudyModel, modeState: AppModeState) async {
        log.record("selftest.replay.begin")
        modeState.mode = .replay // the app's onChange deactivates study and activates replay
        await pause(300)
        study.setActive(false); r.setActive(true) // same calls the mode switch makes, in case the scene is not active
        let replayStart = log.events.count
        var timings: [String: Double] = [:]
        let t = ContinuousClock.now
        r.start()
        timings["engineStart"] = await waitReplayIdle(r, from: t) ?? -1
        guard r.ready else {
            record("replay-engine-start", pass: false, details: ["status": r.status]); return
        }
        guard let probe = Self.currentReplayProbe else { return }

        // R1. No analysis and no tracker contact before one complete (scripted) review.
        do {
            var d: [String: Any] = [:]
            let first = await replayStep(r)
            d["firstFrame"] = first
            let before = (probe.analyzeCalls, probe.trackerRequests, probe.validateCalls)
            d["canAnalyzeBeforeReview"] = r.canAnalyze
            r.analyze(); await pause(50)
            r.editFEN(StudyFixture.starting.referenceFEN!)                     // "Use sample FEN"
            for field in ReviewField.allCases.dropLast() { r.setReview(field, checked: true) }
            d["canConfirmWithFourOfFive"] = r.canConfirmReview
            r.confirmReview(); await pause(50)
            let after = (probe.analyzeCalls, probe.trackerRequests, probe.validateCalls)
            d["engineAnalyzeCalls"] = after.0 - before.0; d["trackerRequests"] = after.1 - before.1; d["validateCalls"] = after.2 - before.2
            let pass = r.phase == .needsReview && r.board?.complete == true && d["canAnalyzeBeforeReview"] as? Bool == false
                && d["canConfirmWithFourOfFive"] as? Bool == false && after == before && r.recommendation == nil
            record("replay-no-analysis-before-review", pass: pass, details: d, label: scriptedLabel)
        }
        if Task.isCancelled { return }

        // R2-R4. Full 14-frame game: review once, track every frame, analyze several plies,
        // advance during analysis, obstructed frame mid-game, renewed review, continue.
        var steps: [[String: Any]] = [], recommendations: [[String: Any]] = [], reviews: [[String: Any]] = []
        var cleanSteps = true
        var advanceCheck: [String: Any] = [:], advancePass = false
        var occlusion: [String: Any] = [:], occlusionPass = false
        let fens = Self.scriptedReplayFENs
        reviews.append(await replayReview(r, fen: fens[0]))
        if r.phase == .tracking { recommendations.append(await replayAnalyze(r, ply: 0)) } else { cleanSteps = false }
        for index in 1...13 {
            if Task.isCancelled || !cleanSteps { break }
            let ply = index / 2
            if index == 4 {
                // R3. Advance while the analysis of frame 3 is still running.
                let first = log.events.count, s0 = ContinuousClock.now
                r.analyze(); log.record("selftest.replay.analyze-called", ["frame": 3])
                let sentMs = await waitForAnalysisSent(since: first, event: "replay.engine.analyze.begin", from: s0)
                let analyzingAtStep = r.analyzing
                let replied = log.events(since: first).contains { ["replay.engine.analyze.reply", "replay.engine.analyze.error"].contains($0["event"] as? String ?? "") }
                log.record("selftest.replay.step-during-analysis", ["msAfterAnalyze": elapsedMilliseconds(s0)])
                r.step()
                var everVisible = false
                let window = ContinuousClock.now
                while elapsedMilliseconds(window) < 3000 { if r.recommendation != nil || r.move != nil { everVisible = true }; await pause(10) }
                _ = await waitReplayIdle(r, from: ContinuousClock.now)
                let events = log.events(since: first)
                let ended = events.first { ["replay.engine.analyze.reply", "replay.engine.analyze.error"].contains($0["event"] as? String ?? "") }
                let firstTracker = events.first { $0["event"] as? String == "replay.tracker.begin" }
                let endedMs = ended?["tMs"] as? Double ?? .infinity, trackerMs = firstTracker?["tMs"] as? Double ?? -1
                advanceCheck = ["analysisRequestSentThenSettledMs": sentMs ?? NSNull(), "analyzingAtStep": analyzingAtStep, "engineReplyBeforeStep": replied, "recommendationEverVisible": everVisible,
                                "analysisOutcome": ended ?? NSNull(), "firstTrackerRequestAfterAnalysisEnded": trackerMs > endedMs,
                                "legalTextRequests": events.filter { $0["event"] as? String == "replay.engine.legalText.begin" }.count,
                                "trackedFEN": r.trackedFEN ?? NSNull(), "observationWindowMs": 3000, "events": events]
                advancePass = sentMs != nil && analyzingAtStep && !replied && !everVisible && trackerMs > endedMs && r.phase == .tracking
                    && r.trackedFEN == fens[2] && r.recommendation == nil && (advanceCheck["legalTextRequests"] as? Int) == 0
                steps.append(["frameIndex": 4, "trackedFEN": r.trackedFEN ?? NSNull(), "phase": "\(r.phase)", "note": "stepped during analysis"])
                if r.phase != .tracking { cleanSteps = false; break }
                recommendations.append(await replayAnalyze(r, ply: 2))
                continue
            }
            if index == 8 {
                // R4. Obstructed frame inserted mid-game: revokes, blocks until renewed review.
                r.queueInterruption()
                let o = await replayStep(r)
                let before = (probe.analyzeCalls, probe.trackerRequests)
                let blockedAnalyze = r.canAnalyze
                r.analyze(); await pause(50)
                let next = await replayStep(r) // frame 8 (after 2...Nc6) while not tracking
                r.analyze(); await pause(50)
                let after = (probe.analyzeCalls, probe.trackerRequests)
                occlusion = ["obstructedStep": o, "canAnalyzeAfterObstruction": blockedAnalyze, "nextFrameWhileRevoked": next,
                             "engineAnalyzeCallsWhileRevoked": after.0 - before.0, "trackerRequestsWhileRevoked": after.1 - before.1,
                             "canConfirmBeforeReview": r.canConfirmReview]
                let review = await replayReview(r, fen: fens[4])
                reviews.append(review)
                occlusion["renewedReview"] = review
                occlusionPass = o["interruption"] as? Bool == true && o["phase"] as? String == "needsReview" && (o["unknownSquares"] as? Int ?? 0) > 0
                    && !blockedAnalyze && next["phase"] as? String == "needsReview" && after == before
                    && review["phase"] as? String == "tracking" && r.reviewEpoch == 2 && r.trackedFEN == fens[4]
                steps.append(o); steps.append(next)
                if r.phase != .tracking { cleanSteps = false; break }
                recommendations.append(await replayAnalyze(r, ply: 4))
                continue
            }
            let s = await replayStep(r)
            steps.append(s)
            if !Self.tracked(s, fen: fens[ply]) { cleanSteps = false; break }
            if [2, 6, 10, 12].contains(index) { recommendations.append(await replayAnalyze(r, ply: ply)) }
        }
        let legalRecs = recommendations.filter { $0["legalPerAppRulesReply"] as? Bool == true && $0["moveUCI"] is String }
        let distinctPlies = Set(legalRecs.compactMap { $0["ply"] as? Int })
        record("replay-full-game-tracked-with-text-recommendations",
               pass: cleanSteps && r.frameIndex == 13 && !r.hasNextFrame && distinctPlies.count >= 3 && legalRecs.count == recommendations.count,
               details: ["steps": steps, "recommendations": recommendations, "reviews": reviews, "distinctPliesWithLegalRecommendation": distinctPlies.sorted(),
                         "finalTrackedFEN": r.trackedFEN ?? NSNull(), "finalFrame": r.frameLabel, "speakRequests": SelfTestSilentSpeech.shared.speakRequests],
               timings: timings, label: scriptedLabel)
        record("replay-advance-during-analysis-nothing-stale", pass: advancePass, details: advanceCheck, label: scriptedLabel)
        record("replay-obstruction-revokes-until-renewed-review", pass: occlusionPass, details: occlusion, label: scriptedLabel)
        if Task.isCancelled { return }

        // R5. Tracker and engine never in flight together during the whole replay (from the probe).
        let replayEvents = log.events(since: replayStart)
        var engineOpen = 0, trackerOpen = 0, intervalOverlaps = 0
        for e in replayEvents {
            switch e["event"] as? String ?? "" {
            case "replay.engine.validate.begin", "replay.engine.analyze.begin", "replay.engine.legalText.begin":
                if trackerOpen > 0 { intervalOverlaps += 1 }; engineOpen += 1
            case "replay.engine.validate.end", "replay.engine.validate.error", "replay.engine.analyze.reply", "replay.engine.analyze.error",
                 "replay.engine.legalText.end", "replay.engine.legalText.error": engineOpen -= 1
            case "replay.tracker.begin": if engineOpen > 0 { intervalOverlaps += 1 }; trackerOpen += 1
            case "replay.tracker.end", "replay.tracker.error": trackerOpen -= 1
            default: break
            }
        }
        record("replay-tracker-and-engine-never-concurrent", pass: probe.overlaps == 0 && intervalOverlaps == 0,
               details: ["probeOverlaps": probe.overlaps, "logIntervalOverlaps": intervalOverlaps, "trackerRequests": probe.trackerRequests,
                         "engineAnalyzeCalls": probe.analyzeCalls, "rulesCalls": probe.validateCalls + probe.legalTextCalls])

        // R6. Leaving the mode revokes the recommendation and stops the replay engine.
        do {
            // The final step revoked the last recommendation; analyze the final frame so there is one to revoke.
            let final = r.recommendation == nil && r.canAnalyze ? await replayAnalyze(r, ply: 6) : [:]
            var d: [String: Any] = ["finalFrameAnalysis": final, "recommendationBefore": r.recommendation ?? NSNull()]
            let had = r.recommendation != nil
            modeState.mode = .study // the app's onChange calls replay.leave()
            await pause(100)
            if r.ready || r.active { r.leave() } // same call, in case the scene did not deliver onChange
            let immediately = r.recommendation == nil
            await pause(1500)
            d["recommendationAfter1500ms"] = r.recommendation ?? NSNull(); d["ready"] = r.ready; d["phase"] = "\(r.phase)"
            record("replay-leave-mode-revokes", pass: had && immediately && r.recommendation == nil && !r.ready && r.phase == .engineStopped, details: d)
        }
    }

    // MARK: - Special-move replay game (real recognition, real bundled tracker, real engine)

    private var specialTimings: [String: Any] = [:]
    private func number(_ value: Any?) -> Double? { (value as? NSNumber)?.doubleValue }
    private func counts(_ p: SelfTestReplayProbe) -> [Int] { [p.analyzeCalls, p.trackerRequests, p.validateCalls, p.legalTextCalls] }

    private func runSpecialReplay(_ r: ReplayGameModel, modeState: AppModeState) async {
        log.record("selftest.special.begin")
        let fens = Self.specialFENs, sans = Self.specialSAN
        guard r.sequences.contains(where: { $0.id == "special" }) else {
            record("special-replay-game-bundled", pass: false, details: ["sequences": r.sequences.map(\.id)]); return
        }
        modeState.mode = .replay // the app's onChange re-activates the replay model
        await pause(300)
        r.setActive(true)
        r.selectSequence("special")                       // "Game" picker
        let specialStart = log.events.count
        _ = await Self.currentRecognizerProbe?.take()
        var engineStarts: [Double] = []
        func startEngine() async -> Bool {
            let t = ContinuousClock.now
            r.start()                                      // "Start local engine"
            engineStarts.append(await waitReplayIdle(r, from: t) ?? -1)
            return r.ready
        }
        guard r.selectedSequence.id == "special", r.frames.count == 26, await startEngine(), let firstProbe = Self.currentReplayProbe else {
            record("special-replay-engine-start", pass: false, details: ["status": r.status, "sequence": r.selectedSequence.id]); return
        }
        var probes = [firstProbe]
        var allSteps: [[String: Any]] = [], recommendations: [[String: Any]] = []

        // S1. One scripted review of frame 0, then every one of the 25 plies through the real tracker.
        var steps: [[String: Any]] = [], failures: [String] = []
        let firstFrame = await replayStep(r)
        allSteps.append(firstFrame)
        let review0 = await replayReview(r, fen: fens[0])
        var clean = r.phase == .tracking && r.trackedFEN == fens[0]
        if !clean { failures.append("review of frame 0 did not start tracking") }
        if clean { recommendations.append(await replayAnalyze(r, ply: 0)) }
        if clean {
            for ply in 1...25 {
                if Task.isCancelled { return }
                var s = await replayStep(r)
                let ok = s["phase"] as? String == "tracking" && s["trackedFEN"] as? String == fens[ply] && s["lastMoveSAN"] as? String == sans[ply - 1]
                    && s["trackerRequests"] as? Int == 2 && s["frameIndex"] as? Int == ply && s["recommendationClearedAtTap"] as? Bool == true
                s["expectedFEN"] = fens[ply]; s["expectedSAN"] = sans[ply - 1]; s["ply"] = ply; s["pass"] = ok
                steps.append(s); allSteps.append(s)
                if !ok { clean = false; failures.append("ply \(ply) (\(sans[ply - 1])) did not track as expected"); break }
                if Self.specialAnalyzedPlies.contains(ply) { recommendations.append(await replayAnalyze(r, ply: ply)) }
            }
        }
        record("special-full-game-every-ply-tracked",
               pass: clean && steps.count == 25 && r.frameIndex == 25 && !r.hasNextFrame && r.reviewEpoch > 0,
               details: ["review": review0, "steps": steps, "failures": failures, "finalTrackedFEN": r.trackedFEN ?? NSNull(),
                         "note": "every ply checked against the expected FEN (castling rights, en-passant square, counters) and SAN"],
               label: scriptedLabel)
        if Task.isCancelled { return }

        // S2. Switching game mid-game revokes at once and stops the engine; nothing comes back later.
        do {
            var d: [String: Any] = [:]
            if r.recommendation == nil && r.canAnalyze { recommendations.append(await replayAnalyze(r, ply: 25)) }
            let had = r.recommendation != nil
            d["recommendationBefore"] = r.recommendation ?? NSNull(); d["trackedFENBefore"] = r.trackedFEN ?? NSNull()
            r.selectSequence("opening")                    // "Game" picker
            let immediately = r.recommendation == nil && r.trackedFEN == nil && r.phase == .engineStopped && !r.ready
            await pause(1500)
            d["recommendationAfter1500ms"] = r.recommendation ?? NSNull(); d["phase"] = "\(r.phase)"; d["status"] = r.status
            d["sequenceAfter"] = r.selectedSequence.id; d["revokedImmediately"] = immediately
            let pass = had && immediately && r.recommendation == nil && r.phase == .engineStopped && r.board == nil && r.frameIndex == nil
                && r.fen.isEmpty && r.checks.isEmpty && r.selectedSequence.id == "opening"
            record("special-switch-game-mid-game-revokes", pass: pass, details: d)
        }
        if Task.isCancelled { return }

        // Back to the special game: read frames 0...20 without any review (no tracker or engine contact).
        r.selectSequence("special")
        guard await startEngine(), let secondProbe = Self.currentReplayProbe else {
            record("special-replay-engine-restart", pass: false, details: ["status": r.status]); return
        }
        probes.append(secondProbe)
        let unreviewedBefore = counts(secondProbe)
        for _ in 0...20 { if Task.isCancelled { return }; allSteps.append(await replayStep(r)) }
        let unreviewedAfter = counts(secondProbe)
        let review20 = await replayReview(r, fen: fens[20])

        // S3. Late engine reply: analysis of frame 20 is running when the obstructed frame is stepped in.
        var late: [String: Any] = [:], latePass = false
        let unreviewed: [String: Any] = ["frameIndex": r.frameIndex.map { $0 as Any } ?? NSNull(),
                                         "trackerOrEngineCallsBeforeReview": zip(unreviewedAfter, unreviewedBefore).map { $0 - $1 }]
        var occlusion: [String: Any] = ["unreviewedFrames0to20": unreviewed, "midGameReview": review20]
        if r.phase == .tracking && r.trackedFEN == fens[20] && r.canAnalyze {
            let first = log.events.count, s0 = ContinuousClock.now
            r.analyze(); log.record("selftest.special.analyze-called", ["frame": 20])
            let sentMs = await waitForAnalysisSent(since: first, event: "replay.engine.analyze.begin", from: s0)
            let analyzingAtStep = r.analyzing
            let replied = log.events(since: first).contains { ["replay.engine.analyze.reply", "replay.engine.analyze.error"].contains($0["event"] as? String ?? "") }
            log.record("selftest.special.occlusion-during-analysis", ["msAfterAnalyze": elapsedMilliseconds(s0)])
            let stepMs = log.now()
            r.queueInterruption(0)                         // "Show obstructed frame next"
            r.step()                                       // "Next frame"
            let clearedAtTap = r.recommendation == nil && r.move == nil
            var everVisible = false
            let window = ContinuousClock.now
            while elapsedMilliseconds(window) < 3000 { if r.recommendation != nil || r.move != nil { everVisible = true }; await pause(10) }
            _ = await waitReplayIdle(r, from: ContinuousClock.now)
            let events = log.events(since: first)
            let ended = events.first { ["replay.engine.analyze.reply", "replay.engine.analyze.error"].contains($0["event"] as? String ?? "") }
            let firstTracker = events.first { $0["event"] as? String == "replay.tracker.begin" }
            let endedMs = number(ended?["tMs"]) ?? .infinity, trackerMs = number(firstTracker?["tMs"]) ?? -1
            let legalText = events.filter { $0["event"] as? String == "replay.engine.legalText.begin" }.count
            let trackerEnd = events.last { $0["event"] as? String == "replay.tracker.end" }
            late = ["analysisRequestSentThenSettledMs": sentMs ?? NSNull(), "analyzingAtStep": analyzingAtStep, "engineReplyBeforeStep": replied, "recommendationClearedAtTap": clearedAtTap,
                    "recommendationEverVisible": everVisible, "analysisOutcome": ended ?? NSNull(), "engineEndedAfterStepTap": endedMs > stepMs,
                    "firstTrackerRequestAfterAnalysisEnded": trackerMs > endedMs, "legalTextRequests": legalText,
                    "observationWindowMs": 3000, "events": events]
            latePass = sentMs != nil && analyzingAtStep && !replied && clearedAtTap && !everVisible && trackerMs > endedMs && legalText == 0
                && r.showingInterruption && r.phase == .needsReview && r.recommendation == nil
            occlusion["obstructedStep"] = ["frame": r.frameLabel, "phase": "\(r.phase)", "interruption": r.showingInterruption,
                                           "unknownSquares": r.board?.squares.values.filter { $0 == "unknown" }.count ?? NSNull(),
                                           "trackerReason": trackerEnd?["reason"] ?? NSNull(), "trackerStatus": trackerEnd?["status"] ?? NSNull(),
                                           "status": r.status]
        } else { late["failure"] = "could not reach a tracked, analyzable frame 20" }
        record("special-late-engine-reply-after-occlusion-revoke-nothing-shown", pass: latePass, details: late, label: scriptedLabel)
        if Task.isCancelled { return }

        // S4. Occlusion revoked; frame 21 stays blocked until a renewed review; tracking resumes.
        do {
            let o = occlusion["obstructedStep"] as? [String: Any] ?? [:]
            let canConfirmOnObstructed = r.canConfirmReview, canAnalyzeOnObstructed = r.canAnalyze
            let before = counts(secondProbe)
            r.analyze(); await pause(50)
            let next = await replayStep(r)                // frame 21 while revoked
            allSteps.append(next)
            r.analyze(); await pause(50)
            let after = counts(secondProbe)
            let epochBefore = r.reviewEpoch
            let review = await replayReview(r, fen: fens[21])
            let s22 = await replayStep(r); allSteps.append(s22)
            occlusion["canConfirmOnObstructedFrame"] = canConfirmOnObstructed; occlusion["canAnalyzeOnObstructedFrame"] = canAnalyzeOnObstructed
            occlusion["nextFrameWhileRevoked"] = next; occlusion["callsWhileRevoked"] = zip(after, before).map { $0 - $1 }
            occlusion["renewedReview"] = review; occlusion["afterRenewedReview"] = s22
            let pass = (unreviewedAfter == unreviewedBefore) && review20["phase"] as? String == "tracking"
                && o["interruption"] as? Bool == true && o["phase"] as? String == "needsReview" && (o["unknownSquares"] as? Int ?? 0) > 0
                && o["trackerReason"] as? String == "uncertain-squares" && !canConfirmOnObstructed && !canAnalyzeOnObstructed
                && next["phase"] as? String == "needsReview" && next["frameIndex"] as? Int == 21 && after == before
                && review["phase"] as? String == "tracking" && r.reviewEpoch > epochBefore && review["trackedFEN"] as? String == fens[21]
                && s22["trackedFEN"] as? String == fens[22] && s22["lastMoveSAN"] as? String == sans[21] && s22["phase"] as? String == "tracking"
            record("special-occlusion-revokes-until-renewed-review", pass: pass, details: occlusion, label: scriptedLabel)
        }
        if Task.isCancelled { return }
        if r.phase == .tracking && r.canAnalyze { recommendations.append(await replayAnalyze(r, ply: 22)) }

        // S5. Missing piece (h2 pawn gone): no legal move explains it; revoked until a renewed review.
        do {
            var d: [String: Any] = [:]
            r.queueInterruption(1)                         // "Show frame with a missing piece next"
            let m = await replayStep(r); allSteps.append(m)
            let canConfirm = r.canConfirmReview, canAnalyze = r.canAnalyze, complete = r.board?.complete == true
            let before = counts(secondProbe)
            r.analyze(); await pause(50)
            let next = await replayStep(r); allSteps.append(next) // frame 23 while revoked
            r.analyze(); await pause(50)
            let after = counts(secondProbe)
            let epochBefore = r.reviewEpoch
            let review = await replayReview(r, fen: fens[23])
            var resumed: [[String: Any]] = []
            for _ in 24...25 { let s = await replayStep(r); resumed.append(s); allSteps.append(s) }
            if r.phase == .tracking && r.canAnalyze { recommendations.append(await replayAnalyze(r, ply: 25)) }
            d = ["missingPieceStep": m, "boardComplete": complete, "canConfirmOnMissingPieceFrame": canConfirm, "canAnalyzeOnMissingPieceFrame": canAnalyze,
                 "nextFrameWhileRevoked": next, "callsWhileRevoked": zip(after, before).map { $0 - $1 }, "renewedReview": review, "resumed": resumed]
            let pass = m["interruption"] as? Bool == true && m["phase"] as? String == "needsReview" && complete
                && m["trackerLastReason"] as? String == "not-zero-or-one-legal-move" && !canConfirm && !canAnalyze
                && next["phase"] as? String == "needsReview" && next["frameIndex"] as? Int == 23 && after == before
                && review["phase"] as? String == "tracking" && r.reviewEpoch > epochBefore
                && resumed.count == 2 && resumed[0]["trackedFEN"] as? String == fens[24] && resumed[0]["lastMoveSAN"] as? String == sans[23]
                && resumed[1]["trackedFEN"] as? String == fens[25] && resumed[1]["lastMoveSAN"] as? String == sans[24]
                && resumed.allSatisfy { $0["phase"] as? String == "tracking" && $0["trackerRequests"] as? Int == 2 }
            record("special-missing-piece-revokes-until-renewed-review", pass: pass, details: d, label: scriptedLabel)
        }
        if Task.isCancelled { return }

        // S6. Text advice only at reviewed-and-tracked positions, each legal per the app's own rules reply.
        do {
            let plyOK: ([String: Any]) -> Bool = { rec in
                guard let ply = rec["ply"] as? Int, fens.indices.contains(ply) else { return false }
                return rec["fen"] as? String == fens[ply] && rec["legalPerAppRulesReply"] as? Bool == true && rec["moveUCI"] is String
                    && rec["identityStillCurrent"] as? Bool == true
            }
            let analyzed = Set(recommendations.filter(plyOK).compactMap { $0["ply"] as? Int })
            let required = Self.specialAnalyzedPlies.union([22])
            let clearedEveryStep = allSteps.allSatisfy { $0["recommendationClearedAtTap"] as? Bool != false }
            record("special-text-recommendations-only-at-tracked-positions",
                   pass: required.isSubset(of: analyzed) && recommendations.allSatisfy(plyOK) && clearedEveryStep,
                   details: ["recommendations": recommendations, "requiredPlies": required.sorted(), "pliesWithLegalText": analyzed.sorted(),
                             "recommendationClearedAtEveryStepTap": clearedEveryStep, "speakRequests": SelfTestSilentSpeech.shared.speakRequests],
                   label: scriptedLabel)
        }

        // S7. Tracker and engine never in flight together in the whole special section.
        do {
            var engineOpen = 0, trackerOpen = 0, intervalOverlaps = 0
            for e in log.events(since: specialStart) {
                switch e["event"] as? String ?? "" {
                case "replay.engine.validate.begin", "replay.engine.analyze.begin", "replay.engine.legalText.begin":
                    if trackerOpen > 0 { intervalOverlaps += 1 }; engineOpen += 1
                case "replay.engine.validate.end", "replay.engine.validate.error", "replay.engine.analyze.reply", "replay.engine.analyze.error",
                     "replay.engine.legalText.end", "replay.engine.legalText.error": engineOpen -= 1
                case "replay.tracker.begin": if engineOpen > 0 { intervalOverlaps += 1 }; trackerOpen += 1
                case "replay.tracker.end", "replay.tracker.error": trackerOpen -= 1
                default: break
                }
            }
            let probeOverlaps = probes.reduce(0) { $0 + $1.overlaps }
            record("special-tracker-and-engine-never-concurrent", pass: probeOverlaps == 0 && intervalOverlaps == 0,
                   details: ["probeOverlaps": probeOverlaps, "logIntervalOverlaps": intervalOverlaps,
                             "trackerRequests": probes.reduce(0) { $0 + $1.trackerRequests }, "engineAnalyzeCalls": probes.reduce(0) { $0 + $1.analyzeCalls }])
        }

        // Timings for the report (Simulator or phone, scripted review).
        let recognition = allSteps.flatMap { ($0["recognitionMs"] as? [Double]) ?? [] }.sorted()
        let search = recommendations.compactMap { number($0["engineSearchMs"]) }.sorted()
        let analysis = recommendations.compactMap { number($0["analysisTotalMs"]) }.sorted()
        func summary(_ v: [Double]) -> [String: Any] {
            v.isEmpty ? ["count": 0] : ["count": v.count, "min": v.first!, "median": v[v.count / 2], "max": v.last!]
        }
        specialTimings = ["recognitionMsPerFrame": summary(recognition), "engineSearchMs": summary(search),
                          "analysisTotalMs": summary(analysis), "engineStartMs": engineStarts]
        if Task.isCancelled { return }

        // Switch game while a real analysis (on the pre-started engine) runs: the old game's result is never shown.
        do {
            var d: [String: Any] = [:], pass = false
            r.selectSequence("opening")                    // "Game" picker: stops this engine
            if await startEngine(), let probe = Self.currentReplayProbe {
                d["firstFrame"] = await replayStep(r)
                d["review"] = await replayReview(r, fen: Self.scriptedReplayFENs[0])
                let (spare, spareWaitMs) = await waitSpareReady { await probe.spareStatus() }
                d["spareBeforeAnalysis"] = spare ?? NSNull(); d["spareWaitMs"] = spareWaitMs
                if r.phase == .tracking && r.canAnalyze, let identity = r.currentIdentity {
                    let first = log.events.count, s0 = ContinuousClock.now
                    r.analyze(); log.record("selftest.replay.switch-analyze-called", ["fen": identity.fen])
                    let sentMs = await waitForAnalysisSent(since: first, event: "replay.engine.analyze.begin", from: s0)
                    let analyzingAtSwitch = r.analyzing
                    let replied = log.events(since: first).contains { ["replay.engine.analyze.reply", "replay.engine.analyze.error"].contains($0["event"] as? String ?? "") }
                    log.record("selftest.replay.switch-game-during-analysis", ["msAfterAnalyze": elapsedMilliseconds(s0)])
                    let switchMs = log.now()
                    r.selectSequence("special")             // "Game" picker, mid-analysis
                    let clearedAtSwitch = r.recommendation == nil && r.move == nil
                    var everVisible = false
                    let window = ContinuousClock.now
                    while elapsedMilliseconds(window) < 3000 { if r.recommendation != nil || r.move != nil { everVisible = true }; await pause(10) }
                    let events = log.events(since: first)
                    let outcome = events.first { ["replay.engine.analyze.reply", "replay.engine.analyze.error"].contains($0["event"] as? String ?? "") }
                    let legalTextAfterSwitch = events.filter { $0["event"] as? String == "replay.engine.legalText.begin" && (number($0["tMs"]) ?? 0) > switchMs }.count
                    d["analysisRequestSentThenSettledMs"] = sentMs ?? NSNull(); d["analyzingAtSwitch"] = analyzingAtSwitch
                    d["engineReplyBeforeSwitch"] = replied; d["recommendationClearedAtSwitch"] = clearedAtSwitch
                    d["recommendationEverVisible"] = everVisible; d["analysisOutcome"] = outcome ?? NSNull()
                    d["legalTextRequestsAfterSwitch"] = legalTextAfterSwitch; d["observationWindowMs"] = 3000
                    d["sequenceAfter"] = r.selectedSequence.id; d["phaseAfter"] = "\(r.phase)"; d["oldEngineRunning"] = probe.runtimeRunning
                    d["events"] = events
                    pass = spare == "ready" && sentMs != nil && analyzingAtSwitch && !replied && clearedAtSwitch && !everVisible
                        && legalTextAfterSwitch == 0 && r.recommendation == nil && r.move == nil && r.trackedFEN == nil
                        && r.selectedSequence.id == "special" && r.phase == .engineStopped && !r.ready && !probe.runtimeRunning
                } else { d["failure"] = "could not reach a tracked, analyzable first frame of the opening game" }
            } else { d["failure"] = "engine did not start for the opening game" }
            record("replay-switch-game-during-analysis-real-engine", pass: pass, details: d, label: scriptedLabel)
        }
        // Leave the replay mode clean.
        r.leave()
    }

    // MARK: - Occupancy tracker wiring (docs/OCCUPANCY_TRACKER.md "Wiring"); SYNTHETIC scripted readings, no camera

    static let occupancyTimeoutSeconds = 90
    /// Readings from a FEN's piece placement: every square white / black / empty, confidence 1; `hidden` squares read unknown.
    static func occupancySquares(_ fen: String, hidden: Set<String> = []) -> [String: Any] {
        var out: [String: Any] = [:]
        let files = Array("abcdefgh")
        for (index, row) in fen.split(separator: " ")[0].split(separator: "/").enumerated() {
            var file = 0
            for ch in row {
                if let n = ch.wholeNumberValue { for _ in 0..<n { out["\(files[file])\(8 - index)"] = ["label": "empty", "confidence": 1]; file += 1 } }
                else { out["\(files[file])\(8 - index)"] = ["label": ch.isUppercase ? "white" : "black", "confidence": 1]; file += 1 }
            }
        }
        for square in hidden { out[square] = ["label": "unknown", "confidence": 1] }
        return out
    }
    /// Scripted feed: one reading every 100 ms of virtual capture time, consecutive sequence numbers, a distinct hash each.
    @MainActor private final class ScriptedFeed {
        let submit: @MainActor (String) async throws -> String; let session: [String: Any]; var sequence = 0; var time = 0; var requests = 0
        init(runtime: NativeEngineRuntime, session: [String: Any], time: Int = 0) {
            self.submit = { try await runtime.submit(commandJSON: $0, timeoutMilliseconds: 5_000) }; self.session = session; self.time = time
        }
        init(backend: LocalOfflineBackend, session: [String: Any]) { self.submit = { try await backend.submitRuntimeCommand($0) }; self.session = session }
        @MainActor func send(_ kind: String, _ fields: [String: Any]) async throws -> [String: Any] {
            requests += 1
            var command = fields; command["schemaVersion"] = 1; command["kind"] = kind; command["requestId"] = "occupancy-\(kind)-\(requests)"
            let text = String(data: try JSONSerialization.data(withJSONObject: command, options: [.sortedKeys]), encoding: .utf8)!
            return (try JSONSerialization.jsonObject(with: Data(try await submit(text).utf8)) as? [String: Any]) ?? [:]
        }
        @MainActor func start(_ fen: String) async throws -> [String: Any] {
            try await send("trackerStart", ["session": session, "fen": fen, "reviewed": ["pieces": true, "turn": true, "castling": true, "enPassant": true, "counters": true], "atMs": time])
        }
        @MainActor func read(_ fen: String, hidden: Set<String> = [], times: Int = 1) async throws -> [String: Any] {
            var last: [String: Any] = [:]
            for _ in 0..<times {
                sequence += 1; time += 100
                var identity = session; identity["sequence"] = sequence
                identity["frameSha256"] = NativeSyntheticRecognizer.sha256(Data("\(session["sessionId"] ?? ""):\(session["epoch"] ?? ""):\(sequence)".utf8))
                last = try await send("trackerIngest", ["reading": ["identity": identity, "capturedAtMs": time, "squares": SelfTestRunner.occupancySquares(fen, hidden: hidden)]])
            }
            return last
        }
        @MainActor func snapshot(after ms: Int) async throws -> [String: Any] { try await send("trackerSnapshot", ["atMs": time + ms]) }
    }
    private static func trackerSummary(_ reply: [String: Any]) -> [String: Any] {
        let state = reply["state"] as? [String: Any] ?? [:]
        return ["trackingReady": jsonValue(reply["trackingReady"]), "guidanceAllowed": jsonValue(reply["guidanceAllowed"]), "status": jsonValue(state["status"]),
                "reason": jsonValue(state["reason"]), "fen": jsonValue(state["fen"]), "lastMove": jsonValue((state["lastMove"] as? [String: Any])?["san"])]
    }

    private func runOccupancyChecks() async {
        log.record("selftest.occupancy.begin")
        let startFEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        let afterE4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
        guard let resources = Self.studyResources, let directory = try? resources.runtimeDirectory() else {
            for name in ["occupancy-tracker-off-refuses-every-request", "occupancy-tracker-on-honest-move-trusted", "occupancy-tracker-on-hidden-swap-revoked", "occupancy-tracker-on-honest-promotion-trusted"] {
                record(name, pass: false, details: ["failure": "no runtime directory"])
            }
            return
        }
        // 1. The app's own backend (LocalOfflineBackend, exactly as the app builds it), setting as launched:
        // every tracker request refused, the engine still answers.
        do {
            var d: [String: Any] = ["settingEnabled": TrackerSetting.enabled, "launchArgument": TrackerSetting.launchArgument]
            var outcomes: [String: String] = [:], engineOK = false
            if let backend = try? LocalOfflineBackend(resources: resources) {
                d["backendRuntimeSettingEnabled"] = backend.occupancyTrackerEnabled
                do {
                    try await backend.start()
                    let feed = ScriptedFeed(backend: backend, session: ["sessionId": "selftest-off", "epoch": 1])
                    for kind in ["trackerStart", "trackerIngest", "trackerSnapshot", "trackerStop", "trackerAnswerPromotion"] {
                        do { _ = try await feed.send(kind, kind == "trackerSnapshot" ? ["atMs": 0] : [:]); outcomes[kind] = "accepted" }
                        catch NativeEngineRuntimeError.unavailable(let message) where message == NativeEngineRuntime.occupancyDisabledMessage { outcomes[kind] = "refused-disabled" }
                        catch { outcomes[kind] = "error: \(error)" }
                    }
                    let position = try await feed.send("position", ["fen": startFEN])
                    engineOK = ((position["position"] as? [String: Any])?["legalMoves"] as? [Any])?.count == 20
                } catch { outcomes["start"] = "error: \(error)" }
                backend.close()
            }
            d["outcomes"] = outcomes; d["engineAnsweredAfterRefusals"] = engineOK
            let pass = !TrackerSetting.enabled && d["backendRuntimeSettingEnabled"] as? Bool == false && outcomes.count == 5 && outcomes.values.allSatisfy { $0 == "refused-disabled" } && engineOK
            record("occupancy-tracker-off-refuses-every-request", pass: pass, details: d, label: "setting as launched (off unless --occupancy-tracker-on)")
        }
        if Task.isCancelled { return }
        // 2 and 3. Test switch on (a runtime created with occupancyTracker: true; the app's own setting is untouched).
        guard let runtime = try? NativeEngineRuntime(resourceDirectory: directory, occupancyTracker: true) else {
            record("occupancy-tracker-on-honest-move-trusted", pass: false, details: ["failure": "runtime refused"])
            record("occupancy-tracker-on-hidden-swap-revoked", pass: false, details: ["failure": "runtime refused"])
            record("occupancy-tracker-on-honest-promotion-trusted", pass: false, details: ["failure": "runtime refused"]); return
        }
        defer { runtime.close() }
        do { try await runtime.start() } catch {
            record("occupancy-tracker-on-honest-move-trusted", pass: false, details: ["failure": "start: \(error)"])
            record("occupancy-tracker-on-hidden-swap-revoked", pass: false, details: ["failure": "start: \(error)"])
            record("occupancy-tracker-on-honest-promotion-trusted", pass: false, details: ["failure": "start: \(error)"]); return
        }
        do {
            var d: [String: Any] = [:]
            let feed = ScriptedFeed(runtime: runtime, session: ["sessionId": "selftest-honest", "epoch": 1])
            // A real 100,000-node analysis is pending in the engine slot while the tracker requests run.
            let identity: [String: Any] = ["sessionId": "selftest-occupancy", "epoch": 1, "sequence": 1, "frameSha256": String(repeating: "c", count: 64), "revision": 1]
            let analyzeText = String(data: try! JSONSerialization.data(withJSONObject: ["schemaVersion": 1, "requestId": "occupancy-held-analysis", "kind": "analyze", "confirmation": true,
                                                                                         "fen": startFEN, "nodes": 100_000, "identity": identity], options: [.sortedKeys]), encoding: .utf8)!
            @MainActor final class Flag { var done = false }
            let analysis = Flag()
            let held = Task { @MainActor () -> String in
                defer { analysis.done = true }
                do { _ = try await runtime.submit(commandJSON: analyzeText, timeoutMilliseconds: 30_000); return "reply" }
                catch NativeEngineRuntimeError.cancelled { return "cancelled" } catch { return "error: \(error)" }
            }
            await pause(20)
            var replies: [String: Any] = [:], ready = false, readyFEN: Any = NSNull(), refusals: [String] = []
            do {
                d["analysisPendingAtFirstTrackerRequest"] = !analysis.done
                replies["start"] = Self.trackerSummary(try await feed.start(startFEN))
                replies["startSeen"] = Self.trackerSummary(try await feed.read(startFEN, times: 2))
                replies["e4FirstReading"] = Self.trackerSummary(try await feed.read(afterE4))
                replies["e4Accepted"] = Self.trackerSummary(try await feed.read(afterE4, times: 10))
                let snap = try await feed.snapshot(after: 50)
                replies["snapshot50ms"] = Self.trackerSummary(snap)
                ready = snap["trackingReady"] as? Bool == true; readyFEN = (snap["state"] as? [String: Any])?["fen"] ?? NSNull()
                replies["snapshot300msNoReading"] = Self.trackerSummary(try await feed.snapshot(after: 300))
                d["analysisPendingAfterTrackerRequests"] = !analysis.done
            } catch { refusals.append("\(error)") }
            d["analysisOutcome"] = await held.value
            d["replies"] = replies; d["errors"] = refusals; d["trackerRequests"] = feed.requests
            let e4 = replies["e4FirstReading"] as? [String: Any], stale = replies["snapshot300msNoReading"] as? [String: Any]
            let pass = refusals.isEmpty && ready && readyFEN as? String == afterE4 && e4?["trackingReady"] as? Bool == false
                && (replies["snapshot50ms"] as? [String: Any])?["lastMove"] as? String == "e4"
                && stale?["trackingReady"] as? Bool == false && stale?["reason"] as? String == "picture-gap"
                && d["analysisOutcome"] as? String == "reply"
            record("occupancy-tracker-on-honest-move-trusted", pass: pass, details: d, label: "scripted SYNTHETIC readings, not a camera; scripted review fixture, not human review")
        }
        if Task.isCancelled { return }
        do {
            var d: [String: Any] = [:], replies: [String: Any] = [:], errors: [String] = []
            // epoch 2: a new tracker session after the honest game (same JS tracker, newer epoch). The tracker has one clock
            // that never runs backwards, so this script continues later in time (the honest game ended near 1,500 ms).
            let feed = ScriptedFeed(runtime: runtime, session: ["sessionId": "selftest-swap", "epoch": 2], time: 10_000)
            do {
                replies["start"] = Self.trackerSummary(try await feed.start(startFEN))
                replies["startSeen"] = Self.trackerSummary(try await feed.read(startFEN, times: 2))
                replies["handOverB1G1"] = Self.trackerSummary(try await feed.read(startFEN, hidden: ["b1", "g1"]))
                replies["e4After"] = Self.trackerSummary(try await feed.read(afterE4, times: 11))
                replies["snapshot"] = Self.trackerSummary(try await feed.snapshot(after: 50))
                replies["laterReadings"] = Self.trackerSummary(try await feed.read(afterE4, times: 3))
            } catch { errors.append("\(error)") }
            d["replies"] = replies; d["errors"] = errors
            let seen = replies["startSeen"] as? [String: Any], after = replies["e4After"] as? [String: Any]
            let pass = errors.isEmpty && seen?["trackingReady"] as? Bool == true
                && after?["trackingReady"] as? Bool == false && after?["reason"] as? String == "pieces-may-have-swapped"
                && (replies["snapshot"] as? [String: Any])?["trackingReady"] as? Bool == false
                && (replies["laterReadings"] as? [String: Any])?["trackingReady"] as? Bool == false
            record("occupancy-tracker-on-hidden-swap-revoked", pass: pass, details: d, label: "scripted SYNTHETIC readings, not a camera; scripted review fixture, not human review")
        }
        if Task.isCancelled { return }
        // 4. Promotion: occupancy cannot see the new piece, so the scripted person answers with trackerAnswerPromotion. An answer
        // stamped with an older reading's time is rejected without effect; the answer stamped with the latest reading is accepted,
        // and the tracker becomes ready only after fresh readings of the promoted position.
        do {
            let promotionFEN = "7k/P7/8/8/8/8/8/K7 w - - 0 1", promotedFEN = "N6k/8/8/8/8/8/8/K7 b - - 0 1"
            var d: [String: Any] = [:], replies: [String: Any] = [:], errors: [String] = []
            var questionAsked = false, lateRejected = false, accepted = false
            let session: [String: Any] = ["sessionId": "selftest-promotion", "epoch": 3]
            let feed = ScriptedFeed(runtime: runtime, session: session, time: 20_000)
            do {
                replies["start"] = Self.trackerSummary(try await feed.start(promotionFEN))
                replies["startSeen"] = Self.trackerSummary(try await feed.read(promotionFEN, times: 2))
                let asked = try await feed.read(promotedFEN, times: 4)
                replies["promotionReadings"] = Self.trackerSummary(asked)
                let questionId = ((asked["state"] as? [String: Any])?["pendingQuestion"] as? [String: Any])?["questionId"] as? String ?? ""
                questionAsked = !questionId.isEmpty && (asked["state"] as? [String: Any])?["status"] as? String == "awaiting-promotion-choice"
                let late = try await feed.send("trackerAnswerPromotion", ["session": session, "questionId": questionId, "piece": "n", "atMs": feed.time - 100])
                let lateState = late["state"] as? [String: Any] ?? [:]
                lateRejected = lateState["rejected"] as? String == "late-answer" && lateState["status"] as? String == "awaiting-promotion-choice"
                replies["lateAnswer"] = Self.trackerSummary(late)
                let answer = try await feed.send("trackerAnswerPromotion", ["session": session, "questionId": questionId, "piece": "n", "atMs": feed.time])
                accepted = (answer["state"] as? [String: Any])?["accepted"] as? Bool == true && answer["trackingReady"] as? Bool == false
                replies["answer"] = Self.trackerSummary(answer)
                replies["promotedSeen"] = Self.trackerSummary(try await feed.read(promotedFEN, times: 2))
                replies["snapshot"] = Self.trackerSummary(try await feed.snapshot(after: 50))
            } catch { errors.append("\(error)") }
            d["replies"] = replies; d["errors"] = errors; d["questionAsked"] = questionAsked; d["lateAnswerRejected"] = lateRejected; d["answerAccepted"] = accepted
            let seen = replies["promotedSeen"] as? [String: Any], snap = replies["snapshot"] as? [String: Any]
            let pass = errors.isEmpty && questionAsked && lateRejected && accepted
                && seen?["trackingReady"] as? Bool == true && seen?["fen"] as? String == promotedFEN
                && snap?["trackingReady"] as? Bool == true && snap?["guidanceAllowed"] as? Bool == false
            record("occupancy-tracker-on-honest-promotion-trusted", pass: pass, details: d, label: "scripted SYNTHETIC readings and a scripted answer, not a camera or a person")
        }
    }

    /// Every analysis that returned a move searched the app's node budget and reported its speed.
    private func searchBudgetCheck() {
        let searches = log.searches
        let modes = Set(searches.compactMap { $0["mode"] as? String })
        let ok = searches.filter { $0["searchReported"] as? Bool == true && Self.withinBudget($0["nodes"] as? Int) && ($0["nodesPerSecond"] as? Int ?? 0) > 0 }
        record("every-analysis-searched-node-budget-with-speed-reported",
               pass: !searches.isEmpty && ok.count == searches.count && modes == ["study", "replay"],
               details: ["budgetNodes": jsonValue(Self.budgetNodes), "analyses": searches.count, "withinBudgetWithSpeed": ok.count,
                         "modes": modes.sorted(), "summary": searchSummary()])
    }
    /// Per-analysis search facts and their medians (report section "engineSearch").
    private func searchSummary() -> [String: Any] {
        let searches = log.searches
        func median(_ key: String) -> Any {
            let values = searches.compactMap { ($0[key] as? NSNumber)?.doubleValue }.sorted()
            return values.isEmpty ? NSNull() : values[values.count / 2]
        }
        var paths: [String: Int] = [:]
        for search in searches { paths[search["startup"] as? String ?? "none", default: 0] += 1 }
        return ["budgetNodes": jsonValue(Self.budgetNodes), "count": searches.count, "medianNodes": median("nodes"),
                "medianNodesPerSecond": median("nodesPerSecond"), "medianSearchMs": median("searchMs"), "medianStartupMs": median("startupMs"),
                "startupPaths": paths, "perAnalysis": searches]
    }

    // MARK: - Report

    private func finish(incomplete: Bool, reason: String?) {
        guard !finished else { return }
        finished = true
        log.record("selftest.end", ["incomplete": incomplete])
        writeReport(incomplete: incomplete, reason: reason)
        let passed = checks.filter { $0["pass"] as? Bool == true }.count
        status = incomplete ? "Self-test INCOMPLETE: \(passed) of \(checks.count) passed (\(reason ?? "cancelled"))"
                            : "Self-test complete: \(passed) of \(checks.count) passed"
    }
    private static func deviceModel() -> String {
        let env = ProcessInfo.processInfo.environment
        if let sim = env["SIMULATOR_MODEL_IDENTIFIER"] { return "Simulator \(env["SIMULATOR_DEVICE_NAME"] ?? "") (\(sim))" }
        var info = utsname(); uname(&info)
        let machine = withUnsafeBytes(of: &info.machine) { String(decoding: $0.prefix { $0 != 0 }, as: UTF8.self) }
        return "\(UIDevice.current.model) (\(machine))"
    }
    /// Clearly named section for the special-move replay game: per-check pass/fail plus timings.
    private func specialSection() -> [String: Any] {
        let special = checks.filter { ($0["name"] as? String ?? "").hasPrefix("special-") }
        let passed = special.filter { $0["pass"] as? Bool == true }.count
        return ["title": "Special-move replay game: 25 plies with en passant, captures, promotion (cxd8=Q+), both castlings; occlusion and missing-piece interruptions",
                "review": scriptedLabel, "expectedChecks": 7, "checksRun": special.count, "checksPassed": passed,
                "allPassed": special.count == 7 && passed == 7,
                "checks": special.map { ["name": $0["name"] ?? NSNull(), "pass": $0["pass"] ?? NSNull()] },
                "timings": specialTimings]
    }
    private func writeReport(incomplete: Bool, reason: String?) {
        let iso = ISO8601DateFormatter(); iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let info = Bundle.main.infoDictionary ?? [:]
        let passed = checks.filter { $0["pass"] as? Bool == true }.count
        let report: [String: Any] = [
            "schemaVersion": 1, "kind": "chess-companion-in-app-self-test",
            "reviewLabel": scriptedLabel, "audio": "none: text only, speech synthesizer never constructed",
            "backendWrapper": "pass-through recording probe around the real LocalOfflineBackend",
            "appVersion": info["CFBundleShortVersionString"] ?? NSNull(), "appBuild": info["CFBundleVersion"] ?? NSNull(),
            "bundleIdentifier": Bundle.main.bundleIdentifier ?? NSNull(),
            "deviceModel": Self.deviceModel(), "osName": UIDevice.current.systemName, "osVersion": UIDevice.current.systemVersion,
            "startTime": iso.string(from: startDate), "endTime": iso.string(from: Date()),
            "overallTimeoutSeconds": Self.overallTimeoutSeconds,
            "incomplete": incomplete, "incompleteReason": reason ?? NSNull(),
            "checksRun": checks.count, "checksPassed": passed, "allPassed": !incomplete && passed == checks.count && !checks.isEmpty,
            "speakRequests": SelfTestSilentSpeech.shared.speakRequests,
            "specialTimeoutSeconds": Self.specialTimeoutSeconds,
            "replay": "Replay game checks drive ReplayGameModel with real recognition, the real bundled tracker in WebKit and the real engine; review is the scripted fixture; text only, no speech dependency",
            "specialReplayGame": specialSection(),
            "engineSearch": searchSummary(),
            "checks": checks, "eventLog": log.events,
        ]
        guard JSONSerialization.isValidJSONObject(report),
              let data = try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]),
              let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first else {
            status = "Self-test: report could not be serialized"; return
        }
        try? data.write(to: documents.appendingPathComponent("selftest-report.json"), options: .atomic)
    }
}

/// View hook: inert unless launched with --chess-self-test.
struct SelfTestHook: ViewModifier {
    let model: OfflineStudyModel
    let replay: ReplayGameModel
    let modeState: AppModeState
    @StateObject private var runner = SelfTestRunner()
    func body(content: Content) -> some View {
        if SelfTestRunner.requested {
            content
                .safeAreaInset(edge: .top) {
                    Text(runner.status).font(.footnote.monospaced()).padding(6).frame(maxWidth: .infinity)
                        .background(Color.yellow.opacity(0.3)).accessibilityIdentifier("self-test-status")
                }
                .task {
                    try? await Task.sleep(for: .seconds(1)) // let the scene become active first
                    await runner.run(model: model, replay: replay, modeState: modeState)
                }
        } else {
            content
        }
    }
}
#endif
