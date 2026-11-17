// macOS checks of NativeEngineRuntime's request guards, compiled together with the REAL NativeEngineRuntime.swift.
// Static checks (kind lists, the busy rule, the asset manifest) plus live checks that send commands through the real
// `submit` to a headless WKWebView running the built bundle (real local Stockfish searches; no network, device,
// camera, microphone or speech). Removing the busy-prewarm guard from `submit` makes the live checks fail. A second
// runtime with the occupancy setting ON checks the separate occupancy pending slot with SYNTHETIC readings.
// Usage: RuntimeGuardChecks RUNTIME_ASSET_DIRECTORY   (a bundle built by scripts/build-device-runtime.mjs)
#if os(macOS)
import Foundation

private struct CheckFailed: Error, CustomStringConvertible { let message: String; var description: String { message } }
private func require(_ condition: Bool, _ message: String) throws { if !condition { throw CheckFailed(message: message) } }

@MainActor private enum Live {
    static let startFEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    static let busyMessage = "Runtime busy; prewarm skipped."
    static var counter = 0
    static func command(_ kind: String, _ fields: [String: Any] = [:]) -> String {
        counter += 1
        var c = fields; c["schemaVersion"] = 1; c["kind"] = kind; c["requestId"] = "guard-\(kind)-\(counter)"
        return String(data: try! JSONSerialization.data(withJSONObject: c, options: [.sortedKeys]), encoding: .utf8)!
    }
    static func analysis() -> String {
        let identity: [String: Any] = ["sessionId": "guard", "epoch": 1, "sequence": counter + 1, "frameSha256": String(repeating: "b", count: 64), "revision": 1]
        return command("analyze", ["confirmation": true, "fen": startFEN, "nodes": 100_000, "identity": identity])
    }
    static let occupancyBusyMessage = "Runtime busy; occupancy tracker request refused."
    /// "reply[keys]" (plus " ready=true|false" when the reply has `trackingReady`), "cancelled", "timed-out", "refused-busy",
    /// "refused-occupancy-busy", "refused: ...", "error: ..." or "no-reply-within-Ns" (the request never settled: a leaked slot).
    static func outcome(_ runtime: NativeEngineRuntime, _ text: String, timeout: Int = 5_000) async -> String {
        // A request whose continuation is never resumed would hang the harness; bound every wait instead.
        let seconds = timeout / 1000 + 5
        return await withCheckedContinuation { (continuation: CheckedContinuation<String, Never>) in
            let settled = Settled()
            Task { @MainActor in
                let result = await rawOutcome(runtime, text, timeout: timeout)
                if !settled.done { settled.done = true; continuation.resume(returning: result) }
            }
            Task { @MainActor in
                try? await Task.sleep(for: .seconds(seconds))
                if !settled.done { settled.done = true; continuation.resume(returning: "no-reply-within-\(seconds)s") }
            }
        }
    }
    @MainActor private final class Settled { var done = false }
    private static func rawOutcome(_ runtime: NativeEngineRuntime, _ text: String, timeout: Int) async -> String {
        do {
            let reply = try await runtime.submit(commandJSON: text, timeoutMilliseconds: timeout)
            let object = (try? JSONSerialization.jsonObject(with: Data(reply.utf8))) as? [String: Any]
            let keys = object.map { $0.keys.sorted().joined(separator: ",") } ?? "?"
            let ready = (object?["trackingReady"] as? Bool).map { " ready=\($0)" } ?? ""
            return "reply[\(keys)]\(ready)"
        }
        catch NativeEngineRuntimeError.cancelled { return "cancelled" }
        catch NativeEngineRuntimeError.timedOut { return "timed-out" }
        catch NativeEngineRuntimeError.unavailable(let message) {
            return message == busyMessage ? "refused-busy" : message == occupancyBusyMessage ? "refused-occupancy-busy" : "refused: \(message)"
        }
        catch { return "error: \(error)" }
    }
    // Well-formed Replay tracker requests (same shape as tests/fixtures/replay-runtime/transcript.json).
    static let replaySession: [String: Any] = ["sessionId": "guard-replay", "epoch": 1]
    static let reviewed: [String: Any] = ["pieces": true, "turn": true, "castling": true, "enPassant": true, "counters": true]
    static func replay(_ kind: String, _ fields: [String: Any] = [:]) -> String {
        var c = fields; c["mode"] = "trusted-replay"; c["clockDomain"] = "replay-synthetic-v1"; c["session"] = replaySession
        return command(kind, c)
    }
    // Well-formed occupancy-tracker requests (docs/OCCUPANCY_TRACKER.md "Wiring"); SYNTHETIC readings of the start position.
    static func squares() -> [String: Any] {
        var out: [String: Any] = [:]; let files = Array("abcdefgh")
        for (index, row) in startFEN.split(separator: " ")[0].split(separator: "/").enumerated() {
            var file = 0
            for ch in row {
                if let n = ch.wholeNumberValue { for _ in 0..<n { out["\(files[file])\(8 - index)"] = ["label": "empty", "confidence": 1]; file += 1 } }
                else { out["\(files[file])\(8 - index)"] = ["label": ch.isUppercase ? "white" : "black", "confidence": 1]; file += 1 }
            }
        }
        return out
    }
    static func trackerStart(_ session: [String: Any], at t: Int) -> String {
        command("trackerStart", ["session": session, "fen": startFEN, "reviewed": reviewed, "atMs": t])
    }
    static func ingest(_ session: [String: Any], _ sequence: Int, at t: Int) -> String {
        var identity = session; identity["sequence"] = sequence
        identity["frameSha256"] = String(format: "%064x", sequence * 7919 + t + (session["epoch"] as! Int) * 1_000_003)
        return command("trackerIngest", ["reading": ["identity": identity, "capturedAtMs": t, "squares": squares()]])
    }
    /// A promotion answer (`trackerAnswerPromotion`); with no question open the page answers it `answer-rejected`, trust unchanged.
    static func answer(_ session: [String: Any], at t: Int, questionId: String = "promotion:guard:none") -> String {
        command("trackerAnswerPromotion", ["session": session, "questionId": questionId, "piece": "q", "atMs": t])
    }
    /// Start, then two readings of the confirmed position; true when the second reply says tracking is ready.
    static func makeReady(_ runtime: NativeEngineRuntime, _ session: [String: Any], at t: Int) async -> Bool {
        _ = await outcome(runtime, trackerStart(session, at: t))
        _ = await outcome(runtime, ingest(session, 1, at: t + 100))
        return await outcome(runtime, ingest(session, 2, at: t + 200)).hasSuffix(" ready=true")
    }
}

@main @MainActor struct RuntimeGuardChecks {
    static var failures = 0, total = 0
    static func check(_ name: String, _ pass: Bool, _ detail: String = "") {
        total += 1; if !pass { failures += 1 }
        print("\(pass ? "PASS" : "FAIL"): \(name)\(detail.isEmpty ? "" : " :: \(detail)")"); fflush(stdout)
    }
    static func main() {
        guard CommandLine.arguments.count == 2 else { print("Usage: RuntimeGuardChecks RUNTIME_ASSET_DIRECTORY"); exit(2) }
        let directory = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
        Task { @MainActor in
            staticChecks(directory)
            await liveChecks(directory)
            print("\(total - failures)/\(total) runtime guard checks passed (macOS WKWebView, real NativeEngineRuntime.swift).")
            exit(failures == 0 ? 0 : 1)
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 300) { print("HARNESS TIMEOUT after 300 s: not a pass."); exit(3) }
        RunLoop.main.run()
    }

    static func staticChecks(_ directory: URL) {
        let checks: [(String, @MainActor () throws -> Void)] = [
            ("exactly two prewarm kinds were added to the engine kinds", {
                try require(NativeEngineRuntime.engineKinds == ["position", "move", "analyze", "cancel", "prewarm", "cancelPrewarm"], "engine kinds changed")
                try require(NativeEngineRuntime.trackerKinds == ["initialize", "observe", "invalidate", "snapshot"], "tracker kinds changed")
                for kind in ["warmup", "go", "Prewarm", "bestmove", ""] { try require(!NativeEngineRuntime.engineKinds.contains(kind), "unknown kind accepted: \(kind)") }
            }),
            ("busy rule table: a prewarm or cancelPrewarm never supersedes a pending real request (engine or tracker)", {
                let real = NativeEngineRuntime.trackerKinds.union(["position", "move", "analyze", "cancel"])
                for pending in real {
                    for kind in ["prewarm", "cancelPrewarm"] {
                        try require(!NativeEngineRuntime.mayReplace(pendingKind: pending, with: kind), "\(kind) may replace pending \(pending)")
                    }
                }
                for pending in ["prewarm", "cancelPrewarm"] {
                    for kind in ["prewarm", "cancelPrewarm"] { try require(NativeEngineRuntime.mayReplace(pendingKind: pending, with: kind), "\(kind) blocked by pending \(pending)") }
                }
                for kind in real.union(["prewarm", "cancelPrewarm"]) { try require(NativeEngineRuntime.mayReplace(pendingKind: nil, with: kind), "\(kind) blocked with nothing pending") }
                // Real requests keep superseding anything (unchanged single-pending behaviour).
                for kind in real { for pending in real.union(["prewarm", "cancelPrewarm"]) { try require(NativeEngineRuntime.mayReplace(pendingKind: pending, with: kind), "\(kind) blocked by \(pending)") } }
            }),
            ("the asset manifest must be exactly the 18 allowed assets", {
                let manifest = try JSONSerialization.jsonObject(with: Data(contentsOf: directory.appendingPathComponent("runtime-manifest.json"))) as! [String: Any]
                try require((manifest["assets"] as? [String: Any])?.count == 18, "the bundle's manifest does not list 18 assets")
                @MainActor func refused(_ edit: (inout [String: Any]) -> Void) throws -> Bool {
                    let temp = FileManager.default.temporaryDirectory.appendingPathComponent("runtime-guard-\(UUID().uuidString)", isDirectory: true)
                    defer { try? FileManager.default.removeItem(at: temp) }
                    try FileManager.default.createDirectory(at: temp, withIntermediateDirectories: true)
                    var copy = manifest, assets = manifest["assets"] as! [String: Any]
                    edit(&assets); copy["assets"] = assets
                    try JSONSerialization.data(withJSONObject: copy).write(to: temp.appendingPathComponent("runtime-manifest.json"))
                    do { _ = try NativeEngineRuntime(resourceDirectory: temp); return false } catch { return true }
                }
                try require(try !refused { _ in }, "the real manifest was refused")
                try require(try refused { $0["core/unknown.js"] = $0["runtime.js"] }, "an unknown asset was accepted")
                try require(try refused { $0.removeValue(forKey: "core/prewarmed-engine.js") }, "the 17-asset manifest was accepted")
            }),
        ]
        for (name, body) in checks {
            do { try body(); check(name, true) } catch { check(name, false, "\(error)") }
        }
    }

    /// Live: the real `submit` with the real bundle. Each busy case holds a real request pending, sends the housekeeping
    /// kind, and requires both a busy refusal AND that the held request still gets its own reply (not cancelled).
    static func liveChecks(_ directory: URL) async {
        let runtime: NativeEngineRuntime
        do { runtime = try NativeEngineRuntime(resourceDirectory: directory); try await runtime.start() }
        catch { check("live: the real runtime starts", false, "\(error)"); return }
        check("live: the real runtime starts", runtime.isReady)
        for kind in ["prewarm", "cancelPrewarm"] {
            // A 100,000-node analysis stands in for a real engine request (it runs for hundreds of milliseconds).
            let analysisText = Live.analysis()
            let held = Task { @MainActor in await Live.outcome(runtime, analysisText, timeout: 30_000) }
            try? await Task.sleep(for: .milliseconds(20))            // the analysis is now the runtime's pending request
            let housekeeping = await Live.outcome(runtime, Live.command(kind))
            let analysis = await held.value
            let note = analysis == "timed-out" ? " (the held analysis TIMED OUT after 30 s: not a pass; machine too slow or engine hung)" : ""
            check("live: a \(kind) sent while a real analysis is pending is refused as busy and the analysis still replies",
                  housekeeping == "refused-busy" && analysis.hasPrefix("reply["), "\(kind)=\(housekeeping) analysis=\(analysis)\(note)")
        }
        // A Replay tracker request is answered synchronously by the page, so it is held pending by ordering, not by time:
        // both tasks run on the main actor in creation order, and the tracker task sets the pending slot before it suspends.
        // Both held requests are well formed (an initialize, then a snapshot of that session), so each must get a normal reply.
        let replayCases: [(String, String)] = [
            ("prewarm", Live.replay("initialize", ["fen": Live.startFEN, "reviewed": Live.reviewed])),
            ("cancelPrewarm", Live.replay("snapshot")),
        ]
        for (kind, trackerText) in replayCases {
            let tracker = Task { @MainActor in await Live.outcome(runtime, trackerText) }
            let housekeepingText = Live.command(kind)
            let housekeeping = Task { @MainActor in await Live.outcome(runtime, housekeepingText) }
            let (trackerOutcome, housekeepingOutcome) = (await tracker.value, await housekeeping.value)
            check("live: a \(kind) sent while a well-formed Replay tracker request is pending is refused as busy and the tracker request gets its normal reply",
                  housekeepingOutcome == "refused-busy" && trackerOutcome.hasPrefix("reply[") && !trackerOutcome.contains("error"),
                  "\(kind)=\(housekeepingOutcome) tracker=\(trackerOutcome)")
        }
        // Controls: with nothing pending both housekeeping kinds are accepted, with replies that carry no position or move.
        let prewarmAlone = await Live.outcome(runtime, Live.command("prewarm"))
        let cancelAlone = await Live.outcome(runtime, Live.command("cancelPrewarm"))
        check("live: with nothing pending, prewarm and cancelPrewarm are accepted with housekeeping-only replies",
              prewarmAlone == "reply[kind,requestId,runtime,schemaVersion,spare]" && cancelAlone == "reply[cancelled,kind,requestId,runtime,schemaVersion]",
              "prewarm=\(prewarmAlone) cancelPrewarm=\(cancelAlone)")
        check("live: the runtime stayed ready", runtime.isReady)
        // Setting off (the default): the promotion answer is refused by Swift's own gate, before readiness checks: a runtime
        // that was never started still says "disabled" (without that gate it would say "not ready"), and so does a started one.
        let offAnswer = Live.answer(["sessionId": "guard-off", "epoch": 1], at: 0)
        var unstarted = "runtime refused"
        if let idle = try? NativeEngineRuntime(resourceDirectory: directory) { unstarted = await Live.outcome(idle, offAnswer); idle.close() }
        let started = await Live.outcome(runtime, offAnswer)
        let disabled = "refused: " + NativeEngineRuntime.occupancyDisabledMessage
        check("live, setting off: trackerAnswerPromotion is refused by Swift before readiness checks, and on a started runtime",
              unstarted == disabled && started == disabled, "unstarted=\(unstarted) started=\(started)")
        runtime.close()
        await occupancyChecks(directory)
    }

    /// Live, occupancy setting ON: the second (occupancy) pending slot. One engine page at a time, so this runs after
    /// the first runtime is closed. Every wait is bounded, so a leaked slot shows as "no-reply-within-Ns", never a hang.
    static func occupancyChecks(_ directory: URL) async {
        let runtime: NativeEngineRuntime
        do { runtime = try NativeEngineRuntime(resourceDirectory: directory, occupancyTracker: true); try await runtime.start() }
        catch { check("occupancy: the real runtime starts with the setting on", false, "\(error)"); return }
        check("occupancy: the real runtime starts with the setting on", runtime.isReady && runtime.occupancyTrackerEnabled)
        // 1. A second occupancy request while one is pending is refused as busy; the first still gets its reply.
        let s1: [String: Any] = ["sessionId": "guard-occupancy", "epoch": 1]
        var ready = await Live.makeReady(runtime, s1, at: 0)
        let firstText = Live.command("trackerSnapshot", ["atMs": 300]), secondText = Live.command("trackerSnapshot", ["atMs": 310])
        let first = Task { @MainActor in await Live.outcome(runtime, firstText) }
        let second = Task { @MainActor in await Live.outcome(runtime, secondText) }
        let (firstOutcome, secondOutcome) = (await first.value, await second.value)
        check("occupancy: a second tracker request while one is pending is refused as busy and the first still replies",
              ready && firstOutcome.hasPrefix("reply[") && secondOutcome == "refused-occupancy-busy",
              "ready before=\(ready) first=\(firstOutcome) second=\(secondOutcome)")
        // 2. Tracker traffic never cancels, or shares the slot of, a pending engine analysis.
        let s2: [String: Any] = ["sessionId": "guard-occupancy", "epoch": 2]
        let analysisText = Live.analysis()
        let held = Task { @MainActor in await Live.outcome(runtime, analysisText, timeout: 30_000) }
        try? await Task.sleep(for: .milliseconds(20))                // the analysis is now the engine slot's pending request
        ready = await Live.makeReady(runtime, s2, at: 1000)
        let analysis = await held.value
        check("occupancy: tracker requests sent while an analysis is pending get replies and the analysis still replies",
              ready && analysis.hasPrefix("reply["), "tracking ready=\(ready) analysis=\(analysis)")
        // 3. A stop is never refused: it supersedes a pending reading, and tracking is gone afterwards.
        let s3: [String: Any] = ["sessionId": "guard-occupancy", "epoch": 3]
        ready = await Live.makeReady(runtime, s3, at: 2000)
        let readingText = Live.ingest(s3, 3, at: 2300), stopText = Live.command("trackerStop")
        let reading = Task { @MainActor in await Live.outcome(runtime, readingText) }
        let stop = Task { @MainActor in await Live.outcome(runtime, stopText) }
        let (readingOutcome, stopOutcome) = (await reading.value, await stop.value)
        let after = await Live.outcome(runtime, Live.command("trackerSnapshot", ["atMs": 2310]))
        check("occupancy: a stop sent while a reading is pending is not refused, and the next snapshot is not ready",
              ready && stopOutcome.hasPrefix("reply[") && after.hasSuffix(" ready=false"),
              "ready before=\(ready) reading=\(readingOutcome) stop=\(stopOutcome) snapshot=\(after)")
        // 4. Promotion answer, busy slot: refused as busy while a snapshot is pending, and the refusal revokes (any Swift-side failure).
        let s4: [String: Any] = ["sessionId": "guard-occupancy", "epoch": 4]
        ready = await Live.makeReady(runtime, s4, at: 3000)
        let heldText = Live.command("trackerSnapshot", ["atMs": 3210]), busyAnswerText = Live.answer(s4, at: 3200)
        let heldSnap = Task { @MainActor in await Live.outcome(runtime, heldText) }
        let busyAnswer = Task { @MainActor in await Live.outcome(runtime, busyAnswerText) }
        let (heldOutcome, busyOutcome) = (await heldSnap.value, await busyAnswer.value)
        let afterBusy = await Live.outcome(runtime, Live.command("trackerSnapshot", ["atMs": 3220]))
        check("occupancy: a promotion answer while a tracker request is pending is refused as busy, the first still replies, and tracking is revoked",
              ready && heldOutcome.hasSuffix(" ready=true") && busyOutcome == "refused-occupancy-busy" && afterBusy.hasSuffix(" ready=false"),
              "ready before=\(ready) held=\(heldOutcome) answer=\(busyOutcome) snapshot=\(afterBusy)")
        // 5. A stop is never refused: it supersedes a pending promotion answer.
        let s5: [String: Any] = ["sessionId": "guard-occupancy", "epoch": 5]
        ready = await Live.makeReady(runtime, s5, at: 4000)
        let pendingAnswerText = Live.answer(s5, at: 4200), stop2Text = Live.command("trackerStop")
        let pendingAnswer = Task { @MainActor in await Live.outcome(runtime, pendingAnswerText) }
        let stop2 = Task { @MainActor in await Live.outcome(runtime, stop2Text) }
        let (answerOutcome, stop2Outcome) = (await pendingAnswer.value, await stop2.value)
        let afterStop = await Live.outcome(runtime, Live.command("trackerSnapshot", ["atMs": 4210]))
        check("occupancy: a stop sent while a promotion answer is pending is not refused, and the next snapshot is not ready",
              ready && stop2Outcome.hasPrefix("reply[") && afterStop.hasSuffix(" ready=false"),
              "ready before=\(ready) answer=\(answerOutcome) stop=\(stop2Outcome) snapshot=\(afterStop)")
        // 6. An oversized answer is refused before it reaches the page, and revokes.
        let s6: [String: Any] = ["sessionId": "guard-occupancy", "epoch": 6]
        ready = await Live.makeReady(runtime, s6, at: 5000)
        let oversized = await Live.outcome(runtime, Live.answer(s6, at: 5200, questionId: String(repeating: "q", count: 17_000)))
        let afterOversized = await Live.outcome(runtime, Live.command("trackerSnapshot", ["atMs": 5210]))
        check("occupancy: an oversized promotion answer is refused and revokes",
              ready && oversized.hasPrefix("refused") && afterOversized.hasSuffix(" ready=false"), "ready before=\(ready) answer=\(oversized) snapshot=\(afterOversized)")
        // 6b. An answer carrying a `mode` field is refused by Swift's own kind check (not only by the page), and revokes.
        let s6b: [String: Any] = ["sessionId": "guard-occupancy", "epoch": 7]
        ready = await Live.makeReady(runtime, s6b, at: 7000)
        let withMode = Live.command("trackerAnswerPromotion", ["session": s6b, "questionId": "promotion:guard:none", "piece": "q", "atMs": 7200, "mode": "trusted-replay"])
        let modeOutcome = await Live.outcome(runtime, withMode)
        let afterMode = await Live.outcome(runtime, Live.command("trackerSnapshot", ["atMs": 7210]))
        check("occupancy: a promotion answer with a mode field is refused by Swift and revokes",
              ready && modeOutcome == "refused: Runtime not ready or command invalid." && afterMode.hasSuffix(" ready=false"),
              "ready before=\(ready) answer=\(modeOutcome) snapshot=\(afterMode)")
        // 7. Control: an answer with no promotion waiting passes Swift's reply checks and leaves trust unchanged (the tracker's rule).
        let s7: [String: Any] = ["sessionId": "guard-occupancy", "epoch": 9]
        ready = await Live.makeReady(runtime, s7, at: 8000)
        let noQuestion = await Live.outcome(runtime, Live.answer(s7, at: 8200))
        check("occupancy: a promotion answer with no question open gets a normal reply and changes nothing",
              ready && noQuestion.hasPrefix("reply[") && noQuestion.hasSuffix(" ready=true"), "ready before=\(ready) answer=\(noQuestion)")
        check("occupancy: the runtime stayed ready", runtime.isReady)
        runtime.close()
    }
}
#endif
