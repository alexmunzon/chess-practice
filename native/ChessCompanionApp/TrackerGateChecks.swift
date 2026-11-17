// macOS checks of the occupancy-tracker gates (docs/OCCUPANCY_TRACKER.md "Wiring"), run against the REAL
// NativeEngineRuntime.swift and TrackerSetting.swift and a runtime bundle built from the current sources, in a headless
// WKWebView. SYNTHETIC readings only; no camera, network, device or audio. Not part of the app build (prepare_app.py lists
// its sources explicitly). Build and run with scripts/check-native.sh.
// Usage: TrackerGateChecks RUNTIME_ASSET_DIRECTORY
//
// Every check is deterministic: none depends on which of two racing events wins. Where a check needs a request to fail
// on the Swift side after it reached the page, it blocks the main thread right after the request is sent, so the 1 ms
// deadline has passed before any reply can be handled (the old out-of-repo N4/N4b checks raced the reply against it).
// Each check also verifies its own setup (for example "the start really timed out"), so a setup that did not hold is
// a FAIL, never a silent pass.
//
// Checks 16-25 (round 2) also read two private fields of the runtime with Swift's Mirror (read-only): which of its two
// pending slots is occupied, to confirm a setup such as "the analysis is still pending when the tracker request is
// sent", and its web view, to make the page's script thread busy so a reply cannot arrive (check 25). Neither changes
// a gate. Check 22 re-launches this program with `--tracker-setting-probe ARG` to read the launch setting.
import Foundation
import WebKit

let startFEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
let disabledMessage = "Occupancy tracker disabled."
let busyMessage = "Runtime busy; occupancy tracker request refused."

/// A request's result in Sendable form: the reply text, or the error mapped to a plain description.
enum Outcome: Sendable {
    case ok(String)
    case failed(String)
    var reply: [String: Any]? {
        if case .ok(let text) = self { return (try? JSONSerialization.jsonObject(with: Data(text.utf8))) as? [String: Any] }
        return nil
    }
    var ready: Bool? { reply?["trackingReady"] as? Bool }
    var error: String? { if case .failed(let e) = self { return e }; return nil }
    var text: String {
        switch self {
        case .ok: return "ok kind=\(reply?["kind"] ?? "-") ready=\(reply?["trackingReady"] ?? "-") reason=\((reply?["state"] as? [String: Any])?["reason"] ?? "-")"
        case .failed(let e): return "error \(e)"
        }
    }
}
func describeError(_ error: any Error) -> String {
    if let e = error as? NativeEngineRuntimeError {
        switch e {
        case .unavailable(let m): return "unavailable(\(m))"
        case .cancelled: return "cancelled"
        case .timedOut: return "timedOut"
        case .invalidReply: return "invalidReply"
        }
    }
    if error is CancellationError { return "cancelled(CancellationError)" }
    return "other(\(error))"
}

/// Watchdog on its own thread: a check that hangs (for example a request whose reply can never arrive) is reported as
/// FAIL with the remaining checks "not reached", and the process exits 1. It never turns a hang into a pass.
final class Watchdog: @unchecked Sendable {
    private let lock = NSLock()
    private var current = "startup", started = Date(), remaining: [String] = [], passed = 0, total = 0
    func begin(_ name: String, remaining rest: [String], passed p: Int, total t: Int) {
        lock.lock(); current = name; started = Date(); remaining = rest; passed = p; total = t; lock.unlock()
    }
    func run(limitSeconds: Double) {
        Thread.detachNewThread { [self] in
            while true {
                Thread.sleep(forTimeInterval: 0.5)
                lock.lock()
                if Date().timeIntervalSince(started) > limitSeconds {
                    print("FAIL: \(current) :: hung for more than \(Int(limitSeconds)) s")
                    for name in remaining { print("FAIL: \(name) :: not reached (an earlier check hung)") }
                    print("\(passed) of \(total) checks passed")
                    fflush(stdout); exit(1)
                }
                lock.unlock()
            }
        }
    }
}
let watchdog = Watchdog()

@MainActor final class Harness {
    let dir: URL
    var counter = 0, clock = 0, epoch = 0, passed = 0
    static let plan = [
        "setting: the tracker setting is off when the app is launched without --occupancy-tracker-on",
        "off: an unstarted runtime made with the default init refuses all 5 tracker kinds with 'Occupancy tracker disabled.'",
        "off: a started runtime made with the default init refuses all 5 tracker kinds with 'Occupancy tracker disabled.'",
        "off: the engine still answers",
        "page gate: with the host flag not exactly true (false, missing, \"true\", 1) the page refuses all 5 kinds TRACKER_DISABLED",
        "page gate: with the host flag true the same page handles a tracker request (the refusals above come from the gate)",
        "slot: trackerStart uses the separate slot (an analysis pending at the same time still replies)",
        "slot: trackerIngest uses the separate slot (an analysis pending at the same time still replies)",
        "slot: trackerSnapshot uses the separate slot (an analysis pending at the same time still replies)",
        "slot: trackerAnswerPromotion uses the separate slot (an analysis pending at the same time still replies)",
        "slot: trackerStop uses the separate slot (an analysis pending at the same time still replies)",
        "busy: a second tracker request while one is pending is refused and revokes, even when resent",
        "stop: a stop sent while a reading is pending is not refused, and the next snapshot is not ready",
        "revoke: a start that Swift reports as timed out (after the page ran it) never becomes ready",
        "revoke: a tracker request cancelled by its caller revokes",
        "revoke: a command Swift cannot classify (unparseable, oversized, no kind) revokes",
        "revoke: a tracker request that times out while an analysis is pending revokes (the analysis is still pending)",
        "revoke: a tracker request cancelled while an analysis is pending revokes (the analysis is still pending)",
        "busy: a second tracker request of a different kind is refused and revokes, and the first caller gets its reply",
        "stop: a stop sent over a pending start, snapshot or promotion answer is not refused and supersedes it",
        "slot: an analysis submitted while a tracker request is pending leaves that tracker request its reply (all 5 kinds)",
        "duplicate keys: all engine kinds refused and revoke; escaped keys caught, nested lookalikes accepted",
        "setting: a launch argument that only starts with --occupancy (or differs from --occupancy-tracker-on) leaves it off",
        "page router: the router itself refuses the tracker kinds unless its flag is exactly true",
        "app pin: compiled LocalOfflineBackend obeys the launch setting and refuses tracker commands off",
        "timer: a tracker reply that never arrives ends in timedOut from the deadline timer",
    ]
    init(dir: URL) { self.dir = dir }

    func begin(_ index: Int) { watchdog.begin(Self.plan[index], remaining: Array(Self.plan[(index + 1)...]), passed: passed, total: Self.plan.count) }
    func check(_ index: Int, _ pass: Bool, _ detail: String) {
        if pass { passed += 1 }
        print("\(pass ? "PASS" : "FAIL"): \(Self.plan[index]) :: \(detail)"); fflush(stdout)
    }

    // MARK: commands
    func json(_ o: [String: Any]) -> String { String(data: try! JSONSerialization.data(withJSONObject: o, options: [.sortedKeys]), encoding: .utf8)! }
    func cmd(_ kind: String, _ fields: [String: Any] = [:]) -> String {
        counter += 1; var c = fields; c["schemaVersion"] = 1; c["kind"] = kind; c["requestId"] = "gate-\(counter)"; return json(c)
    }
    func squares() -> [String: Any] {
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
    let reviewed: [String: Any] = ["pieces": true, "turn": true, "castling": true, "enPassant": true, "counters": true]
    func session() -> [String: Any] { epoch += 1; return ["sessionId": "gate", "epoch": epoch] }
    func start(_ s: [String: Any], at t: Int) -> String { cmd("trackerStart", ["session": s, "fen": startFEN, "reviewed": reviewed, "atMs": t]) }
    func ingest(_ s: [String: Any], _ seq: Int, at t: Int) -> String {
        var id = s; id["sequence"] = seq; id["frameSha256"] = String(format: "%064x", seq * 7919 + t + (s["epoch"] as! Int) * 1_000_003)
        return cmd("trackerIngest", ["reading": ["identity": id, "capturedAtMs": t, "squares": squares()]])
    }
    func snapshot(at t: Int) -> String { cmd("trackerSnapshot", ["atMs": t]) }
    func answer(_ s: [String: Any], at t: Int) -> String { cmd("trackerAnswerPromotion", ["session": s, "questionId": "no-such-question", "piece": "q", "atMs": t]) }
    func analyze() -> String {
        let identity: [String: Any] = ["sessionId": "gate-engine", "epoch": 1, "sequence": counter + 1, "frameSha256": String(repeating: "c", count: 64), "revision": 1]
        return cmd("analyze", ["confirmation": true, "fen": startFEN, "nodes": 20_000, "identity": identity])
    }
    /// One example of each tracker kind, for the off and page-gate checks (contents valid; the gate must refuse first).
    func oneOfEach() -> [String] {
        let s: [String: Any] = ["sessionId": "off", "epoch": 1]
        return [start(s, at: 0), ingest(s, 1, at: 100), snapshot(at: 200), cmd("trackerStop"), answer(s, at: 100)]
    }

    /// Main-actor isolated on purpose: two tasks queued in order submit in that order, with no executor hop between.
    static func submit(_ rt: NativeEngineRuntime, _ text: String, timeout: Int = 10_000) async -> Outcome {
        do { return .ok(try await rt.submit(commandJSON: text, timeoutMilliseconds: timeout)) }
        catch { return .failed(describeError(error)) }
    }
    func run(_ rt: NativeEngineRuntime, _ text: String, timeout: Int = 10_000) async -> Outcome { await Self.submit(rt, text, timeout: timeout) }

    /// A new session on the tracker clock: start, then two agreeing readings 100 ms apart. Returns the session and
    /// whether the second reading made the tracker ready.
    func makeReady(_ rt: NativeEngineRuntime) async -> ([String: Any], Bool) {
        clock += 1_000
        let s = session()
        _ = await run(rt, start(s, at: clock))
        _ = await run(rt, ingest(s, 1, at: clock + 100))
        let r = await run(rt, ingest(s, 2, at: clock + 200))
        clock += 200
        return (s, r.ready == true)
    }
    func snapshotReady(_ rt: NativeEngineRuntime) async -> Outcome { clock += 10; return await run(rt, snapshot(at: clock)) }
    /// An analysis that searches for 3 s (the page's maximum): still pending long after any tracker request settles.
    func longAnalyze() -> String {
        let identity: [String: Any] = ["sessionId": "gate-engine", "epoch": 1, "sequence": counter + 1, "frameSha256": String(repeating: "d", count: 64), "revision": 1]
        return cmd("analyze", ["confirmation": true, "fen": startFEN, "movetimeMs": 3_000, "identity": identity])
    }

    // MARK: read-only peeks at the runtime's private state (Mirror), used only to confirm a check's setup
    static func field(_ rt: NativeEngineRuntime, _ name: String) -> Any? { Mirror(reflecting: rt).children.first { $0.label == name }?.value }
    /// True when the named optional slot ("pending" = engine/replay, "occupancyPending" = tracker) holds a request.
    static func occupied(_ rt: NativeEngineRuntime, _ name: String) -> Bool {
        guard let value = field(rt, name) else { return false }
        let mirror = Mirror(reflecting: value)
        return mirror.displayStyle == .optional && !mirror.children.isEmpty
    }
    static func webView(_ rt: NativeEngineRuntime) -> WKWebView? { field(rt, "webView") as? WKWebView }

    /// The task's result if it finishes within `seconds`, else nil (a caller that would otherwise wait forever).
    func within(_ seconds: Double, _ task: Task<Outcome, Never>) async -> Outcome? {
        await withCheckedContinuation { (c: CheckedContinuation<Outcome?, Never>) in
            let once = Once(c)
            Task { @MainActor in once.resume(await task.value) }
            DispatchQueue.main.asyncAfter(deadline: .now() + seconds) { MainActor.assumeIsolated { once.resume(nil) } }
        }
    }

    // MARK: checks
    func all() async {
        // 0. The app's setting, read from this process's launch arguments (the script passes none).
        begin(0)
        check(0, TrackerSetting.enabled == false && TrackerSetting.launchArgument == "--occupancy-tracker-on",
              "enabled=\(TrackerSetting.enabled) launchArgument=\(TrackerSetting.launchArgument) arguments=\(CommandLine.arguments.count - 1)")

        // 1. Off, never started: Swift must refuse before its readiness check (which would say "Runtime not ready").
        begin(1)
        let unstarted = try! NativeEngineRuntime(resourceDirectory: dir)
        var lines: [String] = []
        for text in oneOfEach() { lines.append(await run(unstarted, text).text) }
        check(1, lines.allSatisfy { $0 == "error unavailable(\(disabledMessage))" }, lines.joined(separator: " | "))
        unstarted.close()

        // 2-3. Off, started (the default init).
        begin(2)
        let off = try! NativeEngineRuntime(resourceDirectory: dir)
        do { try await off.start() } catch { check(2, false, "off runtime did not start: \(describeError(error))") }
        lines = []
        for text in oneOfEach() { lines.append(await run(off, text).text) }
        check(2, off.occupancyTrackerEnabled == false && lines.allSatisfy { $0 == "error unavailable(\(disabledMessage))" },
              "occupancyTrackerEnabled=\(off.occupancyTrackerEnabled) " + lines.joined(separator: " | "))
        begin(3)
        let position = await run(off, cmd("position", ["fen": startFEN]))
        check(3, position.reply?["kind"] as? String == "position", position.text)
        off.close()

        // 4-5. The page gate on its own: a separate web view with the same bundle, no Swift gate in between.
        begin(4)
        let page = PageHost(dir: dir)
        let pageReady = await page.load()
        var refusals: [String] = []
        var allRefused = pageReady
        for flag in ["false", "undefined", "'true'", "1"] {
            for text in oneOfEach() {
                let envelope = await page.submit(text, flagLiteral: flag)
                let code = (envelope?["error"] as? [String: Any])?["code"] as? String
                if envelope?["ok"] as? Bool != false || code != "TRACKER_DISABLED" { allRefused = false }
                refusals.append("\(flag):\(code ?? "ok=\(envelope?["ok"] ?? "none")")")
            }
        }
        check(4, allRefused, "page ready=\(pageReady) " + refusals.joined(separator: " "))
        begin(5)
        let accepted = await page.submit(cmd("trackerStop"), flagLiteral: "true")
        let acceptedReply = accepted?["result"] as? [String: Any]
        check(5, pageReady && accepted?["ok"] as? Bool == true && acceptedReply?["mode"] as? String == "occupancy-tracking",
              "envelope ok=\(accepted?["ok"] ?? "none") mode=\(acceptedReply?["mode"] ?? "-")")
        page.close()

        // 6-15. Setting on.
        let on = try! NativeEngineRuntime(resourceDirectory: dir, occupancyTracker: true)
        do { try await on.start() } catch { print("note: on runtime did not start: \(describeError(error))") }

        // 6-10. Each kind beside a pending analysis. Both tasks are queued on the main actor in this order, so the
        // analysis is pending (engine slot set, page called) before the tracker request is submitted. With one shared
        // slot the tracker request would cancel the analysis.
        let s = session()
        clock += 1_000
        let base = clock
        let kindRequests = [start(s, at: base), ingest(s, 1, at: base + 100), snapshot(at: base + 110), answer(s, at: base + 100), cmd("trackerStop")]
        clock += 200
        for (offset, text) in kindRequests.enumerated() {
            begin(6 + offset)
            let analysisText = analyze()
            let a = Task { @MainActor in await Self.submit(on, analysisText, timeout: 30_000) }
            let t = Task { @MainActor in await Self.submit(on, text) }
            let (tracker, analysis) = (await t.value, await a.value)
            check(6 + offset, tracker.reply?["mode"] as? String == "occupancy-tracking" && analysis.reply?["kind"] as? String == "analyze",
                  "tracker=\(tracker.text) analysis=\(analysis.text)")
        }

        // 11. Busy: two readings queued in order; the second finds the first pending and is refused.
        begin(11)
        do {
            let (s, readyBefore) = await makeReady(on)
            let t3 = clock + 100, t4 = clock + 200; clock += 200
            let first = ingest(s, 3, at: t3), second = ingest(s, 4, at: t4)
            let a = Task { @MainActor in await Self.submit(on, first) }
            let b = Task { @MainActor in await Self.submit(on, second) }
            let (ra, rb) = (await a.value, await b.value)
            let resend = await run(on, ingest(s, 4, at: t4))
            let snap = await snapshotReady(on)
            let setup = readyBefore && rb.error == "unavailable(\(busyMessage))"
            check(11, setup && resend.ready == false && snap.ready == false,
                  "ready before=\(readyBefore) first=\(ra.text) second=\(rb.text) resend=\(resend.text) snapshot=\(snap.text)")
        }

        // 12. Stop while a reading is pending: same ordering, the stop must supersede it, not be refused.
        begin(12)
        do {
            let (s, readyBefore) = await makeReady(on)
            clock += 100
            let reading = ingest(s, 3, at: clock), stop = cmd("trackerStop")
            let a = Task { @MainActor in await Self.submit(on, reading) }
            let b = Task { @MainActor in await Self.submit(on, stop) }
            let (ra, rb) = (await a.value, await b.value)
            let snap = await snapshotReady(on)
            check(12, readyBefore && ra.error == "cancelled" && rb.reply?["kind"] as? String == "trackerStop" && snap.ready == false,
                  "ready before=\(readyBefore) reading=\(ra.text) stop=\(rb.text) snapshot=\(snap.text)")
        }

        // 13. A start that reaches the page but that Swift reports as timed out. The request task is queued first, then
        // a block that holds the main thread for 100 ms: the start is sent to the page, then the 1 ms deadline passes
        // before any reply or timer can be handled, so Swift always reports timedOut (no race).
        begin(13)
        do {
            clock += 1_000
            let s = session(), t0 = clock
            let text = start(s, at: t0)
            let t = Task { @MainActor in await Self.submit(on, text, timeout: 1) }
            DispatchQueue.main.async { Thread.sleep(forTimeInterval: 0.1) }
            let st = await t.value
            let r1 = await run(on, ingest(s, 1, at: t0 + 100))
            let r2 = await run(on, ingest(s, 2, at: t0 + 200))
            let r3 = await run(on, ingest(s, 3, at: t0 + 300))
            clock += 300
            check(13, st.error == "timedOut" && r2.ready == false && r3.ready == false,
                  "start=\(st.text) reading1=\(r1.text) reading2=\(r2.text) reading3=\(r3.text)")
        }

        // 14. A request whose task is cancelled before it runs: Swift throws before sending it, and must still revoke.
        begin(14)
        do {
            let (s, readyBefore) = await makeReady(on)
            clock += 100
            let text = ingest(s, 3, at: clock)
            let t = Task { @MainActor in await Self.submit(on, text) }
            t.cancel()
            let rt = await t.value
            let snap = await snapshotReady(on)
            check(14, readyBefore && rt.error?.hasPrefix("cancelled") == true && snap.ready == false,
                  "ready before=\(readyBefore) request=\(rt.text) snapshot=\(snap.text)")
        }

        // 15. Commands Swift cannot classify, each sent while the tracker is ready.
        begin(15)
        do {
            var pass = true, details: [String] = []
            let oversized = "{\"kind\":\"trackerSnapshot\",\"pad\":\"" + String(repeating: "x", count: 17_000) + "\"}"
            for (label, text) in [("unparseable", "not json"), ("oversized", oversized), ("no kind", "{\"schemaVersion\":1,\"requestId\":\"gate-nokind\"}")] {
                let (_, readyBefore) = await makeReady(on)
                let r = await run(on, text)
                let snap = await snapshotReady(on)
                if !(readyBefore && r.error != nil && snap.ready == false) { pass = false }
                details.append("\(label): ready before=\(readyBefore) request=\(r.text) snapshot=\(snap.text)")
            }
            check(15, pass, details.joined(separator: " | "))
        }

        // 16. A tracker request that times out while an analysis is pending. Same main-thread block as check 13, so the
        // reading always times out. The analysis searches for 3 s; afterwards cancel() must report it cancelled, which
        // proves it was still pending when the revoke ran.
        begin(16)
        do {
            let (s, readyBefore) = await makeReady(on)
            clock += 100
            let reading = ingest(s, 3, at: clock), analysisText = longAnalyze()
            let a = Task { @MainActor in await Self.submit(on, analysisText, timeout: 30_000) }
            let t = Task { @MainActor () -> (Bool, Outcome) in (Self.occupied(on, "pending"), await Self.submit(on, reading, timeout: 1)) }
            DispatchQueue.main.async { Thread.sleep(forTimeInterval: 0.1) }
            let (engineBusy, rt) = await t.value
            let stillPending = Self.occupied(on, "pending")
            on.cancel()
            let ra = await a.value
            let snap = await snapshotReady(on)
            check(16, readyBefore && engineBusy && stillPending && rt.error == "timedOut" && ra.error == "cancelled" && snap.ready == false,
                  "ready before=\(readyBefore) analysis pending at send=\(engineBusy) after=\(stillPending) reading=\(rt.text) analysis=\(ra.text) snapshot=\(snap.text)")
        }

        // 17. A tracker request cancelled (before it runs) while an analysis is pending.
        begin(17)
        do {
            let (s, readyBefore) = await makeReady(on)
            clock += 100
            let reading = ingest(s, 3, at: clock), analysisText = longAnalyze()
            let a = Task { @MainActor in await Self.submit(on, analysisText, timeout: 30_000) }
            let t = Task { @MainActor () -> (Bool, Outcome) in (Self.occupied(on, "pending"), await Self.submit(on, reading)) }
            t.cancel()
            let (engineBusy, rt) = await t.value
            let stillPending = Self.occupied(on, "pending")
            on.cancel()
            let ra = await a.value
            let snap = await snapshotReady(on)
            check(17, readyBefore && engineBusy && stillPending && rt.error?.hasPrefix("cancelled") == true && ra.error == "cancelled" && snap.ready == false,
                  "ready before=\(readyBefore) analysis pending at send=\(engineBusy) after=\(stillPending) reading=\(rt.text) analysis=\(ra.text) snapshot=\(snap.text)")
        }

        // 18. A second tracker request of a DIFFERENT kind while one is pending. The second task records that the slot
        // was occupied when it was submitted. The first caller must still get its own reply (bounded wait: a caller
        // whose slot was overwritten would otherwise wait forever).
        begin(18)
        do {
            var pass = true, details: [String] = []
            for pair in ["reading then snapshot", "snapshot then reading", "start then answer"] {
                let (s, readyBefore) = await makeReady(on)
                clock += 100
                let first: String, second: String, firstKind: String
                switch pair {
                case "reading then snapshot": first = ingest(s, 3, at: clock); second = snapshot(at: clock + 10); firstKind = "trackerIngest"
                case "snapshot then reading": first = snapshot(at: clock); second = ingest(s, 3, at: clock + 10); firstKind = "trackerSnapshot"
                default: first = start(session(), at: clock); second = answer(s, at: clock + 10); firstKind = "trackerStart"
                }
                clock += 10
                let a = Task { @MainActor in await Self.submit(on, first) }
                let b = Task { @MainActor () -> (Bool, Outcome) in (Self.occupied(on, "occupancyPending"), await Self.submit(on, second)) }
                let (slotBusy, rb) = await b.value
                let ra = await within(5, a)
                let snap = await snapshotReady(on)
                if !(readyBefore && slotBusy && rb.error == "unavailable(\(busyMessage))" && ra?.reply?["kind"] as? String == firstKind && snap.ready == false) { pass = false }
                details.append("\(pair): ready before=\(readyBefore) slot busy=\(slotBusy) first=\(ra?.text ?? "no reply within 5 s") second=\(rb.text) snapshot=\(snap.text)")
            }
            check(18, pass, details.joined(separator: " | "))
        }

        // 19. A stop over a pending start, snapshot or promotion answer: the stop is answered, the pending one is cancelled.
        begin(19)
        do {
            var pass = true, details: [String] = []
            for label in ["start", "snapshot", "answer"] {
                let (s, readyBefore) = await makeReady(on)
                clock += 100
                let first = label == "start" ? start(session(), at: clock) : label == "snapshot" ? snapshot(at: clock) : answer(s, at: clock)
                let stop = cmd("trackerStop")
                let a = Task { @MainActor in await Self.submit(on, first) }
                let b = Task { @MainActor () -> (Bool, Outcome) in (Self.occupied(on, "occupancyPending"), await Self.submit(on, stop)) }
                let (slotBusy, rb) = await b.value
                let ra = await within(5, a)
                let snap = await snapshotReady(on)
                if !(readyBefore && slotBusy && ra?.error == "cancelled" && rb.reply?["kind"] as? String == "trackerStop" && snap.ready == false) { pass = false }
                details.append("\(label): ready before=\(readyBefore) slot busy=\(slotBusy) pending=\(ra?.text ?? "no reply within 5 s") stop=\(rb.text) snapshot=\(snap.text)")
            }
            check(19, pass, details.joined(separator: " | "))
        }

        // 20. The reverse order of checks 6-10: the tracker request is queued first, the analysis second; the analysis
        // task records that the tracker slot was occupied when it was submitted. The property is the tracker request's
        // reply; the analysis must not be cancelled by it, but may itself fail (under heavy load the page's 10 s engine
        // start limit was once exceeded), so only "not cancelled" is required of it.
        begin(20)
        do {
            var pass = true, details: [String] = []
            let s = session()
            clock += 1_000
            let base = clock
            let requests = [start(s, at: base), ingest(s, 1, at: base + 100), snapshot(at: base + 110), answer(s, at: base + 100), cmd("trackerStop")]
            clock += 200
            for text in requests {
                let analysisText = analyze()
                let t = Task { @MainActor in await Self.submit(on, text) }
                let a = Task { @MainActor () -> (Bool, Outcome) in (Self.occupied(on, "occupancyPending"), await Self.submit(on, analysisText, timeout: 30_000)) }
                let ((slotBusy, analysis), tracker) = (await a.value, await t.value)
                if !(slotBusy && tracker.reply?["mode"] as? String == "occupancy-tracking" && tracker.reply?["kind"] as? String == ((try? JSONSerialization.jsonObject(with: Data(text.utf8))) as? [String: Any])?["kind"] as? String
                      && analysis.error != "cancelled") { pass = false }
                details.append("slot busy=\(slotBusy) tracker=\(tracker.text) analysis=\(analysis.text)")
            }
            check(20, pass, details.joined(separator: " | "))
        }
        on.close()

        // 21. Duplicate dispatch fields must be refused before execution, both off and on. A fresh trusted
        // baseline before EACH on-case proves that refusal actually revokes rather than inheriting a prior revoke.
        begin(21)
        do {
            var pass = true, details: [String] = []
            for enabled in [false, true] {
                let rt = try! NativeEngineRuntime(resourceDirectory: dir, occupancyTracker: enabled)
                do { try await rt.start() } catch { pass = false }
                var cases: [(String, String)] = []
                for kind in NativeEngineRuntime.engineKinds.sorted() {
                    for key in ["kind", #"k\u0069nd"#] {
                        cases.append(("\(kind)/\(key)", "{\"schemaVersion\":1,\"requestId\":\"dup\",\"kind\":\"\(kind)\",\"\(key)\":\"trackerSnapshot\",\"atMs\":1}"))
                    }
                }
                cases += [("reverse", #"{"schemaVersion":1,"requestId":"dup","kind":"trackerStop","kind":"cancel"}"#),
                          ("same value", #"{"schemaVersion":1,"requestId":"dup","kind":"cancel","kind":"cancel"}"#),
                          ("requestId", #"{"schemaVersion":1,"requestId":"a","requestId":"b","kind":"cancel"}"#),
                          ("mode", #"{"schemaVersion":1,"requestId":"dup","kind":"cancel","mode":null,"mode":"trusted-replay"}"#)]
                for (name, text) in cases {
                    let before = enabled ? await makeReady(rt).1 : rt.isReady
                    let result = await run(rt, text)
                    let revoked = enabled ? await snapshotReady(rt).ready == false : true
                    let ok = before && result.error == "unavailable(Duplicate top-level command key.)" && revoked && rt.isReady
                    pass = pass && ok
                    details.append("\(enabled)/\(name)=\(ok)")
                }
                // Positive controls keep a scanner that merely searches for the word kind from passing.
                let nested = cmd("cancel", ["nested": ["kind": "trackerStop"], "text": #"{ \"kind\": [ ] }"#])
                let escaped = #"{"schemaVersion":1,"requestId":"escaped","k\u0069nd":"cancel","nested":[{"kind":"trackerStop"}]}"#
                for text in [nested, escaped] {
                    let result = await run(rt, text)
                    let ok = result.error == "unavailable(Unsupported command or extra fields.)"
                    pass = pass && ok; details.append("control=\(ok):\(result.text)")
                }
                let plainEscaped = #"{"schemaVersion":1,"requestId":"escaped-valid","k\u0069nd":"cancel"}"#
                let plainResult = await run(rt, plainEscaped)
                let plainOK = plainResult.reply?["kind"] as? String == "cancel"
                pass = pass && plainOK; details.append("escaped valid=\(plainOK)")
                rt.close()
            }
            check(21, pass, details.joined(separator: " | "))
        }

        // 22. The launch setting, read in a fresh copy of this program launched with one extra argument each time.
        begin(22)
        do {
            func probe(_ extra: [String]) -> String {
                let process = Process(), pipe = Pipe()
                process.executableURL = Bundle.main.executableURL ?? URL(fileURLWithPath: CommandLine.arguments[0])
                process.arguments = ["--tracker-setting-probe"] + extra
                process.standardOutput = pipe; process.standardError = pipe
                do { try process.run() } catch { return "launch failed: \(error)" }
                process.waitUntilExit()
                return String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? "-"
            }
            let offArguments = ["--occupancy", "--occupancy-tracker", "--occupancy-tracker-on=1", "--occupancy-tracker-onx", "--occupancy-tracker-off", "--Occupancy-tracker-on", "occupancy-tracker-on"]
            var pass = true, details: [String] = []
            for (extra, expected) in [([], "enabled=false"), (["--occupancy-tracker-on"], "enabled=true")] + offArguments.map({ ([$0], "enabled=false") }) {
                let got = probe(extra)
                if got != expected { pass = false }
                details.append("\(extra.first ?? "(none)") -> \(got)")
            }
            check(22, pass, details.joined(separator: " | "))
        }

        // 23. The page's router on its own (imported from the loaded bundle, stub engine and tracker), so its comparison
        // is checked even though submit() already turns the flag into a boolean.
        begin(23)
        do {
            let page = PageHost(dir: dir)
            let pageReady = await page.load()
            var pass = pageReady, details: [String] = []
            for flag in ["absent", "false", "'true'", "1", "{}", "true"] {
                let got = await page.routerProbe(cmd("trackerStop"), flagLiteral: flag)
                let expected = flag == "true" ? "{\"reached\":true,\"code\":null}" : "{\"reached\":false,\"code\":\"TRACKER_DISABLED\"}"
                if got != expected { pass = false }
                details.append("\(flag): \(got ?? "no result")")
            }
            page.close()
            check(23, pass, "page ready=\(pageReady) " + details.joined(separator: " "))
        }

        // 24. Compile the actual adapter and instantiate it in fresh processes with the setting off/on.
        // A minimal manifest checks the real runtime hash. No synthetic recognizer or speech is invoked here.
        begin(24)
        do {
            var pass = true, details: [String] = []
            for enabled in [false, true] {
                let process = Process(), pipe = Pipe()
                process.executableURL = Bundle.main.executableURL
                process.arguments = ["--app-pin-probe", dir.path] + (enabled ? [TrackerSetting.launchArgument] : [])
                process.standardOutput = pipe; process.standardError = pipe
                do {
                    try process.run()
                    // This child has its own hard watchdog; read before waiting avoids a full-pipe deadlock.
                    let output = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
                    process.waitUntilExit()
                    let ok = process.terminationStatus == 0 && output.contains("APP_PIN_OK enabled=\(enabled)")
                    pass = pass && ok; details.append(output.trimmingCharacters(in: .whitespacesAndNewlines))
                } catch { pass = false; details.append(String(describing: error)) }
            }
            check(24, pass, details.joined(separator: " | "))
        }

        // 25. The deadline timer itself. A dedicated runtime's page script thread is kept busy for 15 s (bounded, so no
        // page keeps spinning after this program), then a tracker snapshot with a 300 ms deadline is sent. Its reply
        // cannot arrive during this check, so only the timer can end it. An engine command sent next also times out,
        // which confirms the page really was busy.
        begin(25)
        do {
            let hung = try! NativeEngineRuntime(resourceDirectory: dir, occupancyTracker: true)
            var startError = "none"
            do { try await hung.start() } catch { startError = describeError(error) }
            let view = Self.webView(hung)
            view?.evaluateJavaScript("{ const end = Date.now() + 15000; while (Date.now() < end) {} }", completionHandler: nil)
            let began = ContinuousClock.now
            let snapText = snapshot(at: 1)
            let r = await within(8, Task { @MainActor in await Self.submit(hung, snapText, timeout: 300) })
            let waited = ContinuousClock.now - began
            let slotAfter = Self.occupied(hung, "occupancyPending")
            let positionText = cmd("position", ["fen": startFEN])
            let p = await within(8, Task { @MainActor in await Self.submit(hung, positionText, timeout: 300) })
            hung.close()
            check(25, startError == "none" && view != nil && r?.error == "timedOut" && waited < .seconds(2) && !slotAfter && p?.error == "timedOut",
                  "start error=\(startError) web view found=\(view != nil) snapshot=\(r?.text ?? "no result within 8 s") after \(waited) slot cleared=\(!slotAfter) engine command=\(p?.text ?? "no result within 8 s")")
        }
    }
}

/// Resumes a continuation once; later calls do nothing.
@MainActor final class Once {
    var continuation: CheckedContinuation<Outcome?, Never>?
    init(_ c: CheckedContinuation<Outcome?, Never>) { continuation = c }
    func resume(_ value: Outcome?) { continuation?.resume(returning: value); continuation = nil }
}

/// A bare web view serving the built bundle, so the page gate can be driven with any host flag. It plays the role of
/// the native host only; it has none of NativeEngineRuntime's gates.
@MainActor final class PageHost: NSObject, WKURLSchemeHandler, WKScriptMessageHandler {
    let dir: URL
    var view: WKWebView?
    var waiters: [String: CheckedContinuation<[String: Any]?, Never>] = [:]
    var readyWaiter: CheckedContinuation<Bool, Never>?
    var types: [String: String] = [:]
    init(dir: URL) {
        self.dir = dir
        super.init()
        if let data = try? Data(contentsOf: dir.appendingPathComponent("runtime-manifest.json")),
           let manifest = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any], let assets = manifest["assets"] as? [String: Any] {
            for (path, asset) in assets { types[path] = (asset as? [String: Any])?["mimeType"] as? String }
        }
    }
    func load() async -> Bool {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.preferences.inactiveSchedulingPolicy = .none
        configuration.setURLSchemeHandler(self, forURLScheme: "chess-local")
        configuration.userContentController.add(self, name: "chessRuntime")
        let view = WKWebView(frame: .zero, configuration: configuration)
        self.view = view
        return await withCheckedContinuation { c in
            readyWaiter = c
            view.load(URLRequest(url: URL(string: "chess-local://bundle/index.html")!))
            DispatchQueue.main.asyncAfter(deadline: .now() + 30) { MainActor.assumeIsolated { self.readyWaiter?.resume(returning: false); self.readyWaiter = nil } }
        }
    }
    /// Calls the page's own submit with the given JavaScript literal as the host flag and returns the reply envelope.
    func submit(_ commandJSON: String, flagLiteral: String) async -> [String: Any]? {
        guard let view else { return nil }
        let transportId = UUID().uuidString
        return await withCheckedContinuation { c in
            waiters[transportId] = c
            let flagArgument = flagLiteral == "undefined" ? "" : ", \(flagLiteral)"
            view.callAsyncJavaScript("globalThis.chessDeviceRuntime.submit(commandJSON, transportId\(flagArgument));",
                                     arguments: ["commandJSON": commandJSON, "transportId": transportId], in: nil, in: .page) { _ in }
            DispatchQueue.main.asyncAfter(deadline: .now() + 10) { MainActor.assumeIsolated { self.waiters.removeValue(forKey: transportId)?.resume(returning: nil) } }
        }
    }
    /// Imports the loaded runtime.js module (the same instance the page runs) and calls its request router directly with
    /// stub backends and the given JavaScript literal as the router's flag ("absent" leaves the option out). Returns
    /// {"reached": whether the occupancy stub was called, "code": the refusal code or null}.
    func routerProbe(_ commandJSON: String, flagLiteral: String) async -> String? {
        guard let view else { return nil }
        let options = flagLiteral == "absent" ? "{}" : "{occupancyTracker: \(flagLiteral)}"
        let body = """
        const m = await import('chess-local://bundle/runtime.js');
        let reached = false;
        const route = m.createRequestRouter({engine: {handle() { return {}; }, cancel() {}}, tracker: {handle() { return '{}'; }},
                                             occupancy: {handle() { reached = true; return {}; }}});
        try { await route(commandJSON, \(options)); return JSON.stringify({reached, code: null}); }
        catch (error) { return JSON.stringify({reached, code: String(error.code)}); }
        """
        return await withCheckedContinuation { c in
            view.callAsyncJavaScript(body, arguments: ["commandJSON": commandJSON], in: nil, in: .page) { result in
                switch result {
                case .success(let value): c.resume(returning: value as? String)
                case .failure(let error): c.resume(returning: "javascript error: \(error.localizedDescription)")
                }
            }
        }
    }
    func close() {
        view?.evaluateJavaScript("globalThis.chessDeviceRuntime?.shutdown();", completionHandler: nil)
        view?.configuration.userContentController.removeScriptMessageHandler(forName: "chessRuntime")
        view = nil
    }
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let text = message.body as? String, let envelope = (try? JSONSerialization.jsonObject(with: Data(text.utf8))) as? [String: Any] else { return }
        if envelope["kind"] as? String == "ready" { readyWaiter?.resume(returning: true); readyWaiter = nil; return }
        if let id = envelope["transportId"] as? String { waiters.removeValue(forKey: id)?.resume(returning: envelope) }
    }
    func webView(_ webView: WKWebView, start urlSchemeTask: any WKURLSchemeTask) {
        guard let url = urlSchemeTask.request.url, url.host == "bundle" else { urlSchemeTask.didFailWithError(URLError(.badURL)); return }
        let path = String(url.path.dropFirst())
        guard let type = types[path], let data = try? Data(contentsOf: dir.appendingPathComponent(path)) else { urlSchemeTask.didFailWithError(URLError(.fileDoesNotExist)); return }
        urlSchemeTask.didReceive(HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1", headerFields: ["Content-Type": type, "Content-Length": String(data.count)])!)
        urlSchemeTask.didReceive(data)
        urlSchemeTask.didFinish()
    }
    func webView(_ webView: WKWebView, stop urlSchemeTask: any WKURLSchemeTask) {}
}

@main struct TrackerGateChecks {
    static func main() {
        // Check 22 launches this program again with this first argument (and at most one more) to read the setting.
        if CommandLine.arguments.count >= 2, CommandLine.arguments[1] == "--tracker-setting-probe" {
            print("enabled=\(TrackerSetting.enabled)"); exit(0)
        }
        if CommandLine.arguments.count >= 3, CommandLine.arguments[1] == "--app-pin-probe" {
            watchdog.run(limitSeconds: 30)
            Task { @MainActor in
                do {
                    let runtimeDir = URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true)
                    let root = runtimeDir.deletingLastPathComponent()
                    let manifest = try Data(contentsOf: runtimeDir.appendingPathComponent("runtime-manifest.json"))
                    let placeholder: [String: Any] = ["byteLength": 1, "sha256": String(repeating: "0", count: 64)]
                    let assets: [String: Any] = ["synthetic-fixture.png": placeholder, "classic-templates-v1.json": placeholder,
                        "Runtime/runtime-manifest.json": ["byteLength": manifest.count, "sha256": NativeSyntheticRecognizer.sha256(manifest)]]
                    let appManifest: [String: Any] = ["schemaVersion": 1, "mode": "private-unsigned-offline-synthetic-study", "assets": assets]
                    try JSONSerialization.data(withJSONObject: appManifest).write(to: root.appendingPathComponent("app-assets.json"), options: .atomic)
                    let backend = try LocalOfflineBackend(resources: StudyResources(root: root))
                    defer { backend.close() }
                    guard backend.occupancyTrackerEnabled == TrackerSetting.enabled else { throw NativeEngineRuntimeError.invalidReply }
                    try await backend.start()
                    let command = #"{"schemaVersion":1,"kind":"trackerStop","requestId":"app-pin"}"#
                    var accepted = false, refusedOff = false
                    do {
                        let reply = try await backend.submitRuntimeCommand(command)
                        let object = try JSONSerialization.jsonObject(with: Data(reply.utf8)) as? [String: Any]
                        accepted = object?["kind"] as? String == "trackerStop"
                    } catch { refusedOff = describeError(error) == "unavailable(Occupancy tracker disabled.)" }
                    guard TrackerSetting.enabled ? accepted : refusedOff else { throw NativeEngineRuntimeError.invalidReply }
                    print("APP_PIN_OK enabled=\(TrackerSetting.enabled)"); fflush(stdout); exit(0)
                } catch { print("APP_PIN_FAIL \(error)"); fflush(stdout); exit(1) }
            }
            RunLoop.main.run(); return
        }
        guard CommandLine.arguments.count == 2 else { print("Usage: TrackerGateChecks RUNTIME_ASSET_DIRECTORY"); exit(2) }
        let dir = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
        watchdog.run(limitSeconds: 60)
        Task { @MainActor in
            let harness = Harness(dir: dir)
            await harness.all()
            print("\(harness.passed) of \(Harness.plan.count) checks passed")
            fflush(stdout)
            exit(harness.passed == Harness.plan.count ? 0 : 1)
        }
        RunLoop.main.run()
    }
}
