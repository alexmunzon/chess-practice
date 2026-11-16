// Pure-logic checks for FrameAgeRules.swift (no Simulator, no SDK). Built and run on macOS by
// tests/mock_glasses_frame_age.py: `swiftc -parse-as-library FrameAgeRules.swift FrameAgeRulesChecks.swift`.
// Prints one line per check and "n of m passed"; exits 1 if any check fails.
import Foundation

@main struct FrameAgeRulesChecks {
    nonisolated(unsafe) static var passed = 0
    nonisolated(unsafe) static var total = 0

    static func check(_ name: String, _ condition: Bool) {
        total += 1
        if condition { passed += 1; print("PASS \(name)") } else { print("FAIL \(name)") }
    }

    static func main() {
        nonce(); offset(); liveness()
        print("\(passed) of \(total) passed")
        exit(passed == total ? 0 : 1)
    }

    static func nonce() {
        var g = NonceAgeGate(maxAge: 3.0, displayMargin: 0.05)
        check("nonce: rejects before any epoch", !g.evaluate(code: 1, frameEpoch: 0, now: 1).accept)
        g.startEpoch(1)
        for code in 0..<15 { g.recordDisplay(code: code, at: 100 + 2 * Double(code)) }
        check("nonce: fresh frame early in its slot accepted", g.evaluate(code: 3, frameEpoch: 1, now: 106.1).accept)
        check("nonce: fresh frame at end of 2 s slot accepted (bound 2.05)", g.evaluate(code: 3, frameEpoch: 1, now: 108.0).accept)
        // Display of code 3 at 106; age bound = now - 106 + 0.05.
        check("nonce: bound just under limit accepted", g.evaluate(code: 3, frameEpoch: 1, now: 108.94).accept)
        check("nonce: bound just over limit rejected", g.evaluate(code: 3, frameEpoch: 1, now: 108.96).reason == "too-old")
        check("nonce: unreadable code rejected", g.evaluate(code: nil, frameEpoch: 1, now: 106.1).reason == "unreadable-code")
        check("nonce: code never displayed rejected", g.evaluate(code: 99, frameEpoch: 1, now: 106.1).reason == "code-never-displayed")
        check("nonce: code displayed only in the future rejected", { var h = NonceAgeGate(maxAge: 3, displayMargin: 0); h.startEpoch(1); h.recordDisplay(code: 5, at: 200); return h.evaluate(code: 5, frameEpoch: 1, now: 199).reason == "code-never-displayed" }())
        // A repeated code keeps its EARLIEST display, so a wrapped code cannot make an old frame look new.
        g.recordDisplay(code: 3, at: 136)
        check("nonce: repeated code bounded by earliest display (fail closed)", g.evaluate(code: 3, frameEpoch: 1, now: 136.5).reason == "too-old")
        check("nonce: frame from an older stream rejected", { var h = g; h.startEpoch(2); h.recordDisplay(code: 3, at: 200); return h.evaluate(code: 3, frameEpoch: 1, now: 200.1).reason == "other-stream" }())
        check("nonce: new epoch discards old display log", { var h = g; h.startEpoch(2); return h.evaluate(code: 3, frameEpoch: 2, now: 106.1).reason == "code-never-displayed" }())
        check("nonce: margin makes bound larger (conservative)", (g.evaluate(code: 4, frameEpoch: 1, now: 109).value ?? 0) > 1.0)
    }

    static func offset() {
        // Warm-up: 3 frames and 0.1 s. Fixed clock offset 50 s, base delivery 0.02 s, frames every 1/30 s.
        func fresh(_ g: inout OffsetMonitorGate, from i0: Int, count: Int, epoch: UInt64 = 1, delay: Double = 0, start: Double = 50) -> [FrameAgeVerdict] {
            (i0..<(i0 + count)).map { i in
                let pts = Double(i) / 30, receipt = start + pts + 0.02 + delay
                return g.observe(pts: pts, receipt: receipt, now: receipt, frameEpoch: epoch)
            }
        }
        var g = OffsetMonitorGate(maxExcess: 0.25, window: 10, warmupFrames: 3, warmupSeconds: 0.1)
        let first = fresh(&g, from: 0, count: 2)
        check("offset: warming-up frames rejected", first.allSatisfy { $0.reason == "warming-up" })
        let steady = fresh(&g, from: 2, count: 60)
        check("offset: steady fresh frames accepted after warm-up", steady.dropFirst(2).allSatisfy(\.accept))
        // Frame 62 delayed in the app: receipt on time, judged later.
        let r62 = 50 + 62.0 / 30 + 0.02
        check("offset: in-app delay just under threshold accepted", g.observe(pts: 62.0 / 30, receipt: r62, now: r62 + 0.24, frameEpoch: 1).accept)
        let r63 = 50 + 63.0 / 30 + 0.02
        check("offset: in-app delay just over threshold rejected", g.observe(pts: 63.0 / 30, receipt: r63, now: r63 + 0.26, frameEpoch: 1).reason == "late")
        // Frame 64 delayed before the phone received it (receipt itself late).
        let r64 = 50 + 64.0 / 30 + 0.02 + 0.3
        check("offset: delay before receipt detected via timestamp", g.observe(pts: 64.0 / 30, receipt: r64, now: r64, frameEpoch: 1).reason == "late")
        check("offset: out-of-order timestamp rejected", g.observe(pts: 63.5 / 30, receipt: r64 + 0.01, now: r64 + 0.01, frameEpoch: 1).reason == "timestamp-not-increasing")
        check("offset: missing timestamp rejected", g.observe(pts: nil, receipt: r64, now: r64, frameEpoch: 1).reason == "no-timestamp")
        check("offset: poll rejects a latest frame that keeps ageing", g.evaluate(pts: 61.0 / 30, frameEpoch: 1, now: 50 + 61.0 / 30 + 0.02 + 0.3).reason == "late")
        // Stream restart: timestamps go back to 0 on a new epoch; old-epoch frames are rejected.
        var h = g
        let restart = fresh(&h, from: 0, count: 10, epoch: 2, start: 90)
        check("offset: new epoch resets and re-warms", restart[0].reason == "warming-up" && restart.last?.accept == true)
        check("offset: frame from older stream rejected", h.observe(pts: 70.0 / 30, receipt: 92, now: 92, frameEpoch: 1).reason == "other-stream")
        // A timestamp reset INSIDE a stream (not seen in the mock) fails closed: every later frame is rejected.
        var k = g
        let reset = fresh(&k, from: 0, count: 5, epoch: 1, start: 60)
        check("offset: in-stream timestamp reset fails closed", reset.allSatisfy { !$0.accept })
        // Known weakness, recorded on purpose: a delay present from the START of a stream is learned as normal.
        var s = OffsetMonitorGate(maxExcess: 0.25, window: 10, warmupFrames: 3, warmupSeconds: 0.1)
        let delayedStart = fresh(&s, from: 0, count: 30, delay: 1.0)
        check("offset: delay present from stream start is NOT detected (relative-only weakness)", delayedStart.last?.accept == true)
        // Known weakness 2: a sustained delay longer than the window becomes the new minimum.
        var w = OffsetMonitorGate(maxExcess: 0.25, window: 2, warmupFrames: 3, warmupSeconds: 0.1)
        _ = fresh(&w, from: 0, count: 60)
        let sustained = fresh(&w, from: 60, count: 120, delay: 1.0)
        check("offset: sustained delay detected while the window still holds fresh frames", !sustained[0].accept && !sustained[15].accept)
        check("offset: sustained delay accepted once it fills the window (windowed weakness)", sustained.last?.accept == true)
        var whole = OffsetMonitorGate(maxExcess: 0.25, window: nil, warmupFrames: 3, warmupSeconds: 0.1)
        _ = fresh(&whole, from: 0, count: 60)
        check("offset: whole-stream minimum keeps rejecting a sustained delay", fresh(&whole, from: 60, count: 120, delay: 1.0).allSatisfy { !$0.accept })
    }

    static func liveness() {
        var g = LivenessBudgetGate(budget: 0.5, limit: 1.0, maxGap: 0.3, agreeingFrames: 2)
        check("liveness: first frame waits for agreement", g.observe(key: "a", receipt: 10, now: 10, frameEpoch: 1).reason == "awaiting-agreement")
        check("liveness: second agreeing frame accepted", g.observe(key: "a", receipt: 10.033, now: 10.033, frameEpoch: 1).accept)
        check("liveness: changed board restarts agreement", g.observe(key: "b", receipt: 10.066, now: 10.066, frameEpoch: 1).reason == "awaiting-agreement")
        _ = g.observe(key: "b", receipt: 10.1, now: 10.1, frameEpoch: 1)
        check("liveness: in-app hold just under limit - budget accepted", g.observe(key: "b", receipt: 10.13, now: 10.13 + 0.49, frameEpoch: 1).accept)
        check("liveness: in-app hold just over limit - budget rejected", g.observe(key: "b", receipt: 10.16, now: 10.16 + 0.51, frameEpoch: 1).reason == "over-budget")
        check("liveness: poll within gap accepted", g.evaluate(receipt: 10.16, frameEpoch: 1, now: 10.16 + 0.29).accept)
        check("liveness: poll after gap rejected", g.evaluate(receipt: 10.16, frameEpoch: 1, now: 10.16 + 0.31).reason == "gap")
        check("liveness: frame after a gap restarts agreement", g.observe(key: "b", receipt: 11.0, now: 11.0, frameEpoch: 1).reason == "awaiting-agreement")
        check("liveness: no board resets agreement", g.observe(key: nil, receipt: 11.03, now: 11.03, frameEpoch: 1).reason == "no-board")
        check("liveness: older stream rejected", { var h = g; _ = h.observe(key: "c", receipt: 20, now: 20, frameEpoch: 2); return h.observe(key: "c", receipt: 20.03, now: 20.03, frameEpoch: 1).reason == "other-stream" }())
        // Known weakness: a frame delayed BEFORE the phone received it looks fresh to this rule.
        var u = LivenessBudgetGate(budget: 0.5, limit: 1.0, maxGap: 0.3, agreeingFrames: 2)
        _ = u.observe(key: "a", receipt: 5, now: 5, frameEpoch: 1)
        check("liveness: upstream delay invisible (receipt is late, gap small)", u.observe(key: "a", receipt: 5.03, now: 5.03, frameEpoch: 1).accept)
    }
}
