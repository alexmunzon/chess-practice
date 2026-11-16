// Phase 5 of docs/MOCK_DEVICE_KIT_PLAN.md: the three candidate frame-age rules as pure logic (no clock, no SDK).
// Harness-only. The live trust decision (CaptureCoordinator: every glasses frame is `.unknownDAT`, no permit)
// is NOT changed and does not use these rules. Results: docs/MOCK_GLASSES_FRAME_AGE.md.
// Every time is in seconds of one phone clock (ProcessInfo.systemUptime in the harness). Each gate tags frames
// with the stream epoch they came from; a frame from an older stream is always rejected.
import Foundation

public struct FrameAgeVerdict: Equatable, Sendable {
    public let accept: Bool
    public let reason: String
    /// Method-specific number the decision used (age bound, excess delay or budgeted age); nil if none.
    public let value: Double?
    static func reject(_ reason: String, _ value: Double? = nil) -> FrameAgeVerdict { .init(accept: false, reason: reason, value: value) }
    static func ok(_ value: Double?) -> FrameAgeVerdict { .init(accept: true, reason: "ok", value: value) }
}

/// Method 1, on-screen nonce. A display logs when it showed each code. A frame showing code N was captured no
/// earlier than the first logged display of N, so `now - earliestDisplay(N) + displayMargin` is an upper bound
/// on its age. Codes that repeat are bounded by their EARLIEST display (fail closed). Unreadable codes, codes
/// never displayed and codes from another display session are rejected.
public struct NonceAgeGate: Sendable {
    public let maxAge: Double
    public let displayMargin: Double
    public private(set) var epoch: UInt64 = 0
    private var displays: [Int: Double] = [:]   // code -> earliest display time in this epoch

    public init(maxAge: Double, displayMargin: Double) {
        precondition(maxAge.isFinite && maxAge > 0 && displayMargin.isFinite && displayMargin >= 0)
        self.maxAge = maxAge; self.displayMargin = displayMargin
    }

    /// Starts a new display session: the log of the previous one is discarded.
    public mutating func startEpoch(_ newEpoch: UInt64) {
        precondition(newEpoch > epoch)
        epoch = newEpoch; displays = [:]
    }

    public mutating func recordDisplay(code: Int, at time: Double) {
        guard time.isFinite else { return }
        if let first = displays[code], first <= time { return }
        displays[code] = time
    }

    public func evaluate(code: Int?, frameEpoch: UInt64, now: Double) -> FrameAgeVerdict {
        guard frameEpoch == epoch, epoch > 0 else { return .reject("other-stream") }
        guard now.isFinite else { return .reject("invalid-clock") }
        guard let code else { return .reject("unreadable-code") }
        guard let first = displays[code], first <= now else { return .reject("code-never-displayed") }
        let bound = now - first + displayMargin
        return bound <= maxAge ? .ok(bound) : .reject("too-old", bound)
    }
}

/// Method 2, learned clock offset. offset = phone receipt - frame timestamp. The smallest offset seen in the
/// window approximates "fixed clock offset + fastest delivery". A frame is late when (now - timestamp) exceeds
/// that minimum by more than `maxExcess`. It measures delay only relative to the fastest frame in the window.
/// `window == nil` keeps the minimum for the whole stream. A new stream (higher epoch) resets everything;
/// timestamps that do not increase are rejected (a late, out-of-order frame, or a reset inside a stream).
public struct OffsetMonitorGate: Sendable {
    public let maxExcess: Double
    public let window: Double?
    public let warmupFrames: Int
    public let warmupSeconds: Double
    public private(set) var epoch: UInt64 = 0
    private var firstReceipt: Double?
    private var maxPTS: Double?
    private var count = 0
    private var samples: [(receipt: Double, offset: Double)] = []

    public init(maxExcess: Double, window: Double?, warmupFrames: Int, warmupSeconds: Double) {
        precondition(maxExcess.isFinite && maxExcess >= 0 && warmupFrames >= 1 && warmupSeconds >= 0)
        if let window { precondition(window.isFinite && window > 0) }
        self.maxExcess = maxExcess; self.window = window; self.warmupFrames = warmupFrames; self.warmupSeconds = warmupSeconds
    }

    public var minimumOffset: Double? { samples.map(\.offset).min() }

    /// Called once per delivered frame. `receipt` is when the phone received it; `now` is when it is judged
    /// (equal to `receipt` unless the frame waited inside the app).
    public mutating func observe(pts: Double?, receipt: Double, now: Double, frameEpoch: UInt64) -> FrameAgeVerdict {
        if frameEpoch > epoch {
            epoch = frameEpoch; firstReceipt = nil; maxPTS = nil; count = 0; samples = []
        } else if frameEpoch < epoch {
            return .reject("other-stream")
        }
        guard let pts, pts.isFinite, receipt.isFinite, now.isFinite else { return .reject("no-timestamp") }
        if let maxPTS, pts <= maxPTS { return .reject("timestamp-not-increasing") }
        maxPTS = pts
        if firstReceipt == nil { firstReceipt = receipt }
        count += 1
        samples.append((receipt, receipt - pts))
        if let window { samples.removeAll { $0.receipt < receipt - window } }
        return evaluate(pts: pts, frameEpoch: frameEpoch, now: now)
    }

    /// Re-judges an already observed frame at a later time (used to poll "is the latest frame still current?").
    public func evaluate(pts: Double?, frameEpoch: UInt64, now: Double) -> FrameAgeVerdict {
        guard frameEpoch == epoch, epoch > 0 else { return .reject("other-stream") }
        guard let pts, pts.isFinite, now.isFinite else { return .reject("no-timestamp") }
        guard let first = firstReceipt, count >= warmupFrames, now - first >= warmupSeconds,
              let minimum = minimumOffset else { return .reject("warming-up") }
        let excess = (now - pts) - minimum
        return excess <= maxExcess ? .ok(excess) : .reject("late", excess)
    }
}

/// Method 3, latency budget plus liveness. Accept a frame only if (now - receipt) + budget <= limit, frames keep
/// arriving with no gap longer than `maxGap`, and `agreeingFrames` consecutive frames agree on the board.
/// `budget` must come from a hardware measurement; in the mock it is a placeholder. A gap restarts agreement.
public struct LivenessBudgetGate: Sendable {
    public let budget: Double
    public let limit: Double
    public let maxGap: Double
    public let agreeingFrames: Int
    public private(set) var epoch: UInt64 = 0
    private var lastArrival: Double?
    private var lastKey: String?
    private var streak = 0

    public init(budget: Double, limit: Double, maxGap: Double, agreeingFrames: Int) {
        precondition(budget.isFinite && budget >= 0 && limit.isFinite && limit > 0 && maxGap.isFinite && maxGap > 0 && agreeingFrames >= 1)
        self.budget = budget; self.limit = limit; self.maxGap = maxGap; self.agreeingFrames = agreeingFrames
    }

    /// `key` is the recognised board (nil if none); `receipt` is when the phone received the frame.
    public mutating func observe(key: String?, receipt: Double, now: Double, frameEpoch: UInt64) -> FrameAgeVerdict {
        if frameEpoch > epoch {
            epoch = frameEpoch; lastArrival = nil; lastKey = nil; streak = 0
        } else if frameEpoch < epoch {
            return .reject("other-stream")
        }
        guard receipt.isFinite, now.isFinite else { return .reject("invalid-clock") }
        if let last = lastArrival, receipt - last > maxGap { streak = 0; lastKey = nil }
        lastArrival = max(lastArrival ?? receipt, receipt)
        guard let key else { streak = 0; lastKey = nil; return .reject("no-board") }
        streak = key == lastKey ? streak + 1 : 1
        lastKey = key
        return judge(receipt: receipt, now: now)
    }

    /// Polls the latest observed frame at a later time: also fails when no frame arrived for longer than maxGap.
    public func evaluate(receipt: Double, frameEpoch: UInt64, now: Double) -> FrameAgeVerdict {
        guard frameEpoch == epoch, epoch > 0, let last = lastArrival else { return .reject("other-stream") }
        guard now.isFinite else { return .reject("invalid-clock") }
        if now - last > maxGap { return .reject("gap", now - last) }
        return judge(receipt: receipt, now: now)
    }

    private func judge(receipt: Double, now: Double) -> FrameAgeVerdict {
        guard streak >= agreeingFrames else { return .reject("awaiting-agreement") }
        let budgeted = (now - receipt) + budget
        return budgeted <= limit ? .ok(budgeted) : .reject("over-budget", budgeted)
    }
}
