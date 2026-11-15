import Foundation

// Standalone Mac check program for ReplayTracker.swift against the golden JS transcript.
// Usage: replay-tracker-checks <transcript.json> [--emit-requests <out.json>]
// Compile: swiftc -parse-as-library -swift-version 6 ReplayTracker.swift ReplayTrackerChecks.swift

@MainActor private var passed = 0, failed = 0
@MainActor private func check(_ condition: Bool, _ name: String) {
    if condition { passed += 1 } else { failed += 1; print("FAIL: \(name)") }
}

/// Deep JSON equality that never confuses booleans with numbers.
private func jsonEqual(_ a: Any, _ b: Any) -> Bool {
    if a is NSNull || b is NSNull { return a is NSNull && b is NSNull }
    if let x = a as? NSNumber, let y = b as? NSNumber {
        guard ReplayJSON.isBool(x) == ReplayJSON.isBool(y) else { return false }
        return ReplayJSON.isBool(x) ? x.boolValue == y.boolValue : x.doubleValue == y.doubleValue
    }
    if let x = a as? String, let y = b as? String { return x == y }
    if let x = a as? [Any], let y = b as? [Any] { return x.count == y.count && zip(x, y).allSatisfy { jsonEqual($0, $1) } }
    if let x = a as? [String: Any], let y = b as? [String: Any] {
        return Set(x.keys) == Set(y.keys) && x.allSatisfy { key, value in jsonEqual(value, y[key]!) }
    }
    return false
}
private func parse(_ text: String) -> Any? { text.data(using: .utf8).flatMap { try? JSONSerialization.jsonObject(with: $0) } }
private func text(_ value: Any) -> String {
    String(data: try! JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]), encoding: .utf8)!
}
private func sessionOf(_ value: Any?) -> ReplaySession {
    let o = value as! [String: Any]
    return ReplaySession(sessionId: o["sessionId"] as! String, epoch: (o["epoch"] as! NSNumber).uint64Value)
}

/// Rebuilds each golden request through the Swift builders. Returns nil for kinds Swift cannot build.
private func swiftRequest(_ golden: [String: Any]) throws -> ReplayRequest? {
    let id = golden["requestId"] as! String
    switch golden["kind"] as! String {
    case "initialize":
        return try ReplayRequestBuilder.initialize(requestId: id, session: sessionOf(golden["session"]), fen: golden["fen"] as! String,
            review: ReplayHumanReview(pieces: true, turn: true, castling: true, enPassant: true, counters: true))
    case "observe":
        let frame = golden["frame"] as! [String: Any], identity = frame["identity"] as! [String: Any]
        var squares: [String: ReplaySquare] = [:]
        for (name, cell) in frame["squares"] as! [String: [String: Any]] {
            squares[name] = ReplaySquare(label: cell["label"] as! String, confidence: (cell["confidence"] as! NSNumber).doubleValue)
        }
        return try ReplayRequestBuilder.observe(requestId: id, frame: ReplayFrame(session: sessionOf(identity),
            sequence: (identity["sequence"] as! NSNumber).uint64Value, frameSha256: identity["frameSha256"] as! String,
            capturedAtMs: (frame["capturedAtMs"] as! NSNumber).uint64Value, squares: squares))
    case "invalidate":
        return try ReplayRequestBuilder.invalidate(requestId: id, session: sessionOf(golden["session"]),
            reason: ReplayInvalidationReason(rawValue: golden["reason"] as! String)!)
    case "snapshot":
        return try ReplayRequestBuilder.snapshot(requestId: id, session: sessionOf(golden["session"]))
    default: return nil
    }
}

/// Whether a decoded state carries exactly the golden reply's values.
private func matchesGolden(_ state: ReplayTrackingState, _ reply: [String: Any]) -> Bool {
    let s = reply["state"] as! [String: Any]
    var move: Any = NSNull()
    if let m = state.lastMove {
        var o: [String: Any] = ["from": m.from, "to": m.to, "san": m.san]; if let p = m.promotion { o["promotion"] = p }; move = o
    }
    var frame: Any = NSNull()
    if let f = state.lastFrame {
        frame = ["sessionId": f.session.sessionId, "epoch": NSNumber(value: f.session.epoch), "sequence": NSNumber(value: f.sequence),
                 "frameSha256": f.frameSha256, "capturedAtMs": NSNumber(value: f.capturedAtMs)]
    }
    return state.requestId == reply["requestId"] as? String && state.kind.rawValue == reply["kind"] as? String &&
        state.trackingReady == ReplayJSON.bool(reply["trackingReady"]) && state.status == s["status"] as? String &&
        state.reason == s["reason"] as? String && state.revision == ReplayJSON.unsigned(s["revision"]) &&
        jsonEqual(state.fen.map { $0 as Any } ?? NSNull(), s["fen"]!) && jsonEqual(move, s["lastMove"]!) &&
        jsonEqual(frame, reply["lastFrame"]!) && state.ignored == reply["ignored"] as? String
}

private func isRevoked(_ outcome: ReplayOutcome) -> Bool {
    if case .revokedRenewedReviewRequired = outcome { return true }; return false
}

/// Replays golden replies by requestId and checks each received request against the golden one.
@MainActor private final class GoldenTransport: ReplayTrackerTransport {
    let pairs: [String: (request: [String: Any], reply: String)]
    var mismatches: [String] = [], sent = 0
    var failNext = false
    var suspended: CheckedContinuation<String, Error>?
    init(pairs: [String: (request: [String: Any], reply: String)]) { self.pairs = pairs }
    func submit(requestJSON: String, timeoutMilliseconds: Int) async throws -> String {
        sent += 1
        if failNext { failNext = false; throw URLError(.timedOut) }
        let sent = parse(requestJSON) as! [String: Any], id = sent["requestId"] as! String
        guard let pair = pairs[id] else { mismatches.append(id); throw URLError(.badServerResponse) }
        if pair.request["kind"] as? String == sent["kind"] as? String, !jsonEqual(sent, pair.request) { mismatches.append(id) }
        return pair.reply
    }
}

@MainActor private final class SuspendingTransport: ReplayTrackerTransport {
    var continuation: CheckedContinuation<String, Error>?
    var replyFor: [String: String] = [:]
    var sent = 0
    func submit(requestJSON: String, timeoutMilliseconds: Int) async throws -> String {
        sent += 1
        let id = (parse(requestJSON) as! [String: Any])["requestId"] as! String
        if let reply = replyFor[id] { return reply }
        return try await withCheckedThrowingContinuation { continuation = $0 }
    }
}

@main struct ReplayTrackerChecks {
    @MainActor static func main() async {
        let args = CommandLine.arguments
        guard args.count >= 2, let data = FileManager.default.contents(atPath: args[1]),
              let transcript = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] else {
            print("usage: replay-tracker-checks <transcript.json> [--emit-requests <out.json>]"); exit(2)
        }
        check(transcript.count == 28, "golden transcript has 28 pairs")
        let active = ReplaySession(sessionId: "replay-golden", epoch: 1)
        var built: [ReplayRequest?] = []
        var emitted: [[String: Any]] = []

        // (a) + (b): every golden pair.
        for (index, pair) in transcript.enumerated() {
            let step = index + 1
            let goldenRequest = pair["request"] as! [String: Any], goldenReply = pair["reply"] as! [String: Any]
            let request: ReplayRequest?
            do { request = try swiftRequest(goldenRequest) } catch { request = nil; check(false, "step \(step) builder threw \(error)") }
            built.append(request)
            if let request {
                check(jsonEqual(parse(request.json) as Any, goldenRequest), "step \(step) Swift request equals golden request")
                emitted.append(["step": step, "source": "swift-builder", "json": request.json])
            } else {
                // Only the deliberately foreign `analyze` envelope (step 27) has no Swift builder.
                check(goldenRequest["kind"] as? String == "analyze", "step \(step) only analyze is unbuildable")
                emitted.append(["step": step, "source": "golden-verbatim", "json": text(goldenRequest)])
            }
            // Error replies are decoded against the host request that would carry that requestId.
            let decodeAs = try! request ?? ReplayRequestBuilder.snapshot(requestId: goldenRequest["requestId"] as! String, session: active)
            let outcome = ReplayReplyDecoder.decode(text(goldenReply), for: decodeAs, activeSession: active)
            switch step {
            case 27: check(outcome == .revokedRenewedReviewRequired(.errorReply(code: "INVALID_REQUEST")), "step 27 error reply revokes")
            case 28: check(outcome == .revokedRenewedReviewRequired(.trackerNeedsConfirmation(reason: "manual-edit")), "step 28 revoked state is unusable")
            default:
                if let state = outcome.trackingState { check(matchesGolden(state, goldenReply), "step \(step) decoded state equals golden reply") }
                else { check(false, "step \(step) golden reply decodes: \(outcome)") }
            }
        }

        // (c) negative cases: each mutates one golden reply and must revoke.
        func negative(_ step: Int, _ name: String, _ mutate: (inout [String: Any]) -> Void) {
            var reply = transcript[step - 1]["reply"] as! [String: Any]
            mutate(&reply)
            check(isRevoked(ReplayReplyDecoder.decode(text(reply), for: built[step - 1]!, activeSession: active)), "negative: \(name)")
        }
        func state(_ r: inout [String: Any], _ key: String, _ value: Any?) {
            var s = r["state"] as! [String: Any]; s[key] = value; r["state"] = s
        }
        negative(5, "extra top-level key") { $0["advice"] = "e4" }
        negative(5, "extra state key") { state(&$0, "bestMove", "e2e4") }
        negative(5, "missing top-level key") { $0["state"] = nil }
        negative(5, "missing state key") { state(&$0, "historyComplete", nil) }
        negative(5, "guidanceAllowed true") { $0["guidanceAllowed"] = true }
        negative(5, "liveGuidanceAllowed true") { $0["liveGuidanceAllowed"] = true }
        negative(5, "guidanceAllowed numeric 0") { $0["guidanceAllowed"] = 0 }
        negative(5, "historyComplete true") { state(&$0, "historyComplete", true) }
        negative(5, "wrong requestId") { $0["requestId"] = "req-6" }
        negative(5, "wrong kind") { $0["kind"] = "snapshot" }
        negative(5, "foreign session") { $0["session"] = ["sessionId": "other-game", "epoch": 1] }
        negative(5, "foreign epoch") { $0["session"] = ["sessionId": "replay-golden", "epoch": 2] }
        negative(5, "wrong runtime") { $0["runtime"] = "remote" }
        negative(5, "wrong mode") { $0["mode"] = "live" }
        negative(5, "wrong schemaVersion") { $0["schemaVersion"] = 2 }
        negative(5, "string schemaVersion") { $0["schemaVersion"] = "1" }
        negative(5, "lastFrame not the accepted frame") {
            var f = $0["lastFrame"] as! [String: Any]; f["sequence"] = 99; $0["lastFrame"] = f
        }
        negative(4, "trackingReady true while stabilizing") { $0["trackingReady"] = true }
        negative(26, "ignored on snapshot") { $0["ignored"] = "repeated-or-reordered-frame" }
        negative(5, "error reply for this request") {
            $0 = ["schemaVersion": 1, "requestId": "req-5", "kind": "observe", "runtime": "on-device-local", "mode": "replay-only",
                  "guidanceAllowed": false, "liveGuidanceAllowed": false,
                  "error": ["code": "FRAME_IDENTITY_CONFLICT", "message": "x", "trackerRevoked": true]]
        }
        negative(5, "STALE_SESSION error (trackerRevoked false) still revokes") {
            $0 = ["schemaVersion": 1, "requestId": "req-5", "kind": "observe", "runtime": "on-device-local", "mode": "replay-only",
                  "guidanceAllowed": false, "liveGuidanceAllowed": false,
                  "error": ["code": "STALE_SESSION", "message": "x", "trackerRevoked": false]]
        }
        let full = text(transcript[4]["reply"]!)
        check(isRevoked(ReplayReplyDecoder.decode(String(full.dropLast(7)), for: built[4]!, activeSession: active)), "negative: truncated JSON")
        check(isRevoked(ReplayReplyDecoder.decode("", for: built[4]!, activeSession: active)), "negative: empty reply")

        // Builder refuses what the JS side would reject.
        let session = active
        check((try? ReplayRequestBuilder.initialize(requestId: "r1", session: session, fen: "8/8/8/8/8/8/8/K6k w - - 0 1",
            review: ReplayHumanReview(pieces: true, turn: true, castling: false, enPassant: true, counters: true))) == nil, "builder: incomplete review refused")
        check((try? ReplayRequestBuilder.initialize(requestId: "r1", session: session, fen: "8/8/8/8/8/8/8/K6k w - -",
            review: ReplayHumanReview(pieces: true, turn: true, castling: true, enPassant: true, counters: true))) == nil, "builder: four-field FEN refused")
        check((try? ReplayRequestBuilder.snapshot(requestId: "bad id!", session: session)) == nil, "builder: bad requestId refused")
        check((try? ReplayRequestBuilder.snapshot(requestId: "r1", session: ReplaySession(sessionId: "s", epoch: 0))) == nil, "builder: epoch 0 refused")

        // (d) tracker client through mocked transports.
        var pairs: [String: (request: [String: Any], reply: String)] = [:]
        for pair in transcript {
            let request = pair["request"] as! [String: Any]
            pairs[request["requestId"] as! String] = (request, text(pair["reply"]!))
        }
        let golden = GoldenTransport(pairs: pairs)
        let tracker = ReplayTracker(transport: golden, requestIdPrefix: "req-")
        var playbackOK = true
        for (index, pair) in transcript.prefix(26).enumerated() {
            let request = pair["request"] as! [String: Any], reply = pair["reply"] as! [String: Any]
            let outcome: ReplayOutcome
            switch request["kind"] as! String {
            case "initialize": outcome = await tracker.initialize(session: sessionOf(request["session"]), fen: request["fen"] as! String,
                review: ReplayHumanReview(pieces: true, turn: true, castling: true, enPassant: true, counters: true))
            case "observe":
                let frame = request["frame"] as! [String: Any], identity = frame["identity"] as! [String: Any]
                var squares: [String: ReplaySquare] = [:]
                for (name, cell) in frame["squares"] as! [String: [String: Any]] {
                    squares[name] = ReplaySquare(label: cell["label"] as! String, confidence: (cell["confidence"] as! NSNumber).doubleValue)
                }
                outcome = await tracker.observe(ReplayFrame(session: sessionOf(identity), sequence: (identity["sequence"] as! NSNumber).uint64Value,
                    frameSha256: identity["frameSha256"] as! String, capturedAtMs: (frame["capturedAtMs"] as! NSNumber).uint64Value, squares: squares))
            default: outcome = await tracker.snapshot()
            }
            if !(outcome.trackingState.map { matchesGolden($0, reply) } ?? false) { playbackOK = false; print("playback step \(index + 1): \(outcome)") }
        }
        check(playbackOK && golden.mismatches.isEmpty && golden.sent == 26, "tracker client plays golden steps 1-26 with golden requests")
        check(tracker.isTrackingUsable, "tracker usable after golden step 26")
        // Step 27's golden error reply arrives for the host's next request (req-27): revoked.
        check(isRevoked(await tracker.snapshot()), "error reply through tracker client revokes")
        let sentBefore = golden.sent
        check(await tracker.snapshot() == .revokedRenewedReviewRequired(.notInitialized) && golden.sent == sentBefore,
              "revocation latches: no request sent until a new initialize")

        // Transport failure.
        let failing = GoldenTransport(pairs: pairs)
        let t2 = ReplayTracker(transport: failing, requestIdPrefix: "req-")
        let initRequest = transcript[0]["request"] as! [String: Any]
        let review = ReplayHumanReview(pieces: true, turn: true, castling: true, enPassant: true, counters: true)
        check(await t2.initialize(session: active, fen: initRequest["fen"] as! String, review: review).trackingState != nil, "mock: initialize succeeds")
        failing.failNext = true
        let failure = await t2.snapshot()
        check(isRevoked(failure) && !t2.isTrackingUsable, "mock: transport failure revokes")
        if case .revokedRenewedReviewRequired(.transportFailure) = failure { check(true, "mock: cause is transport failure") }
        else { check(false, "mock: cause is transport failure (\(failure))") }

        // Concurrent request: the second call revokes and the first reply is discarded.
        let suspending = SuspendingTransport()
        suspending.replyFor["req-1"] = text(transcript[0]["reply"]!)
        let t3 = ReplayTracker(transport: suspending, requestIdPrefix: "req-")
        _ = await t3.initialize(session: active, fen: initRequest["fen"] as! String, review: review)
        let first = Task { @MainActor in await t3.snapshot() }
        while suspending.continuation == nil { await Task.yield() }
        let second = await t3.snapshot()
        suspending.continuation?.resume(returning: text(transcript[25]["reply"]!).replacingOccurrences(of: "req-26", with: "req-2"))
        let firstOutcome = await first.value
        check(second == .revokedRenewedReviewRequired(.concurrentRequest), "concurrent request revokes")
        check(isRevoked(firstOutcome) && !t3.isTrackingUsable, "in-flight reply after concurrent revocation is discarded")

        // Deliberate invalidate always revokes.
        let t4 = ReplayTracker(transport: GoldenTransport(pairs: pairs), requestIdPrefix: "req-")
        _ = await t4.initialize(session: active, fen: initRequest["fen"] as! String, review: review)
        check(await t4.invalidate(reason: .interrupted) == .revokedRenewedReviewRequired(.invalidated(.interrupted)) && !t4.isTrackingUsable,
              "invalidate revokes")

        if let index = args.firstIndex(of: "--emit-requests"), index + 1 < args.count {
            let out = try! JSONSerialization.data(withJSONObject: emitted, options: [.prettyPrinted, .sortedKeys])
            FileManager.default.createFile(atPath: args[index + 1], contents: out)
        }
        print("\(passed)/\(passed + failed) checks passed")
        exit(failed == 0 ? 0 : 1)
    }
}
