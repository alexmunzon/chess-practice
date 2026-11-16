import Foundation

/// Swift port of scripts/recognition/occupancy_classifier_v3.py (v3.1; see FROZEN-v3.1.sha256 in the build folder).
/// Every step keeps the Python order of operations where it is cheap to do so; see README.md.
public enum OccupancyV3 {
    // ---- Policy: identical values to Python policy() (39 entries, checked by conformance.py). ----
    public static let boardOrigin = (64, 64)
    public static let labelsList = ["empty", "white", "black", "unknown"]
    public static let version = "v3"
    public static let preBlurRadius = 1.0
    public static let gainRange = (0.33, 3.0)
    public static let frameSharpnessMin = 0.4
    public static let calSharpnessMin = 0.05  // v3.1: start sharpness must be finite and >= this
    public static let fgDistance = 40.0
    public static let emptyMaxFg = 0.03
    public static let pieceMinFg = 0.08
    public static let edgeLevel = 0.22
    public static let emptyMaxEdge = 0.005
    public static let pieceMinEdge = 0.015
    public static let borderMaxFrac = 0.20
    public static let localSmoothRows = 7
    public static let localMaxShift = 0.60
    public static let localMaxStep = 0.12
    public static let localMaxUnexplained = 0.30
    public static let localMaxMult = 0.20
    public static let localMaxDarkHaze = 0.25
    public static let localSideMax = 0.40
    public static let neighbourRule = 1
    public static let saturatedLevel = 250
    public static let saturatedMaxFrac = 0.05
    public static let saturatedOkMaxShift = 0.15
    public static let saturatedOkMaxRing = 0.02
    public static let colourMaxRow = 46
    public static let silClosePx = 2
    public static let coreMinDepth = 2
    public static let coreDepthBand = 3
    public static let fillEdgeGuard = -1
    public static let minFillPixels = 40
    public static let colorVoteMin = 0.75
    public static let calVoteMin = 0.60
    public static let calVoteMeanMin = 0.85
    public static let colorMaxDist = 70.0
    public static let colorMinSeparation = 0.35
    public static let minSamplesPerClass = 2
    public static let abstainBelow = 0.5

    /// (name, value) in Python's policy() order; value is Int, Double, String or an array of those.
    public static func policy() -> [(String, Any)] {
        let p: [(String, Any)] = [("BOARD_ORIGIN", [boardOrigin.0, boardOrigin.1]), ("LABELS", labelsList), ("VERSION", version),
         ("PRE_BLUR_RADIUS", preBlurRadius), ("GAIN_RANGE", [gainRange.0, gainRange.1]),
         ("FRAME_SHARPNESS_MIN", frameSharpnessMin), ("CAL_SHARPNESS_MIN", calSharpnessMin), ("FG_DISTANCE", fgDistance), ("EMPTY_MAX_FG", emptyMaxFg),
         ("PIECE_MIN_FG", pieceMinFg), ("EDGE_LEVEL", edgeLevel), ("EMPTY_MAX_EDGE", emptyMaxEdge),
         ("PIECE_MIN_EDGE", pieceMinEdge), ("BORDER_MAX_FRAC", borderMaxFrac), ("LOCAL_SMOOTH_ROWS", localSmoothRows),
         ("LOCAL_MAX_SHIFT", localMaxShift), ("LOCAL_MAX_STEP", localMaxStep),
         ("LOCAL_MAX_UNEXPLAINED", localMaxUnexplained), ("LOCAL_MAX_MULT", localMaxMult),
         ("LOCAL_MAX_DARK_HAZE", localMaxDarkHaze), ("LOCAL_SIDE_MAX", localSideMax), ("NEIGHBOUR_RULE", neighbourRule),
         ("SATURATED_LEVEL", saturatedLevel), ("SATURATED_MAX_FRAC", saturatedMaxFrac),
         ("SATURATED_OK_MAX_SHIFT", saturatedOkMaxShift), ("SATURATED_OK_MAX_RING", saturatedOkMaxRing),
         ("COLOUR_MAX_ROW", colourMaxRow), ("SIL_CLOSE_PX", silClosePx), ("CORE_MIN_DEPTH", coreMinDepth),
         ("CORE_DEPTH_BAND", coreDepthBand), ("FILL_EDGE_GUARD", fillEdgeGuard), ("MIN_FILL_PIXELS", minFillPixels),
         ("COLOR_VOTE_MIN", colorVoteMin), ("CAL_VOTE_MIN", calVoteMin), ("CAL_VOTE_MEAN_MIN", calVoteMeanMin),
         ("COLOR_MAX_DIST", colorMaxDist), ("COLOR_MIN_SEPARATION", colorMinSeparation),
         ("MIN_SAMPLES_PER_CLASS", minSamplesPerClass), ("ABSTAIN_BELOW", abstainBelow)]
        return p
    }

    // ---- Squares, masks ----
    public static let T = 64
    /// a8, b8, ..., h8, a7, ..., h1 (panel tile order; row-major from the panel top-left).
    public static let squares: [String] = (0..<64).map { (i: Int) -> String in
        let files: [String] = ["a", "b", "c", "d", "e", "f", "g", "h"]
        return files[i % 8] + String(8 - i / 8)
    }
    public static let dark: [Int] = (0..<64).map { ($0 / 8 + $0 % 8) % 2 }
    static let lum = (0.299, 0.587, 0.114)

    static func mask(_ rects: [(Range<Int>, Range<Int>)]) -> [Bool] {
        var m = [Bool](repeating: false, count: T * T)
        for (rows, cols) in rects { for r in rows { for c in cols { m[r * T + c] = true } } }
        return m
    }
    static let borderMask = mask([(3..<7, 3..<61), (57..<61, 3..<61), (3..<61, 3..<7), (3..<61, 57..<61)])
    static let topBotMask = mask([(3..<7, 8..<56), (57..<61, 8..<56)])
    static let windowMask = mask([(8..<58, 12..<52)])
    static let borderOrWindow = zip(borderMask, windowMask).map { $0 || $1 }
    static let borderIndices = (0..<(T * T)).filter { borderMask[$0] }
    static let topBotIndices = (0..<(T * T)).filter { topBotMask[$0] }
    static let windowCount = windowMask.filter { $0 }.count
    static let leftCols = 3..<8, rightCols = (T - 8)..<(T - 3), stripRows = 3..<(T - 3)

    // ---- Small numeric helpers matching numpy ----
    @inline(__always) static func dot3(_ a: SIMD3<Double>, _ b: SIMD3<Double>) -> Double { a.x * b.x + a.y * b.y + a.z * b.z }
    @inline(__always) static func lumOf(_ a: SIMD3<Double>) -> Double { a.x * lum.0 + a.y * lum.1 + a.z * lum.2 }
    @inline(__always) static func norm3(_ a: SIMD3<Double>) -> Double { (a.x * a.x + a.y * a.y + a.z * a.z).squareRoot() }

    /// numpy.median of a list (sorts a copy; even length = mean of the two middle values).
    public static func median(_ v: [Double]) -> Double {
        precondition(!v.isEmpty)
        let s = v.sorted()
        let n = s.count
        return n % 2 == 1 ? s[n / 2] : (s[n / 2 - 1] + s[n / 2]) / 2
    }

    /// Median of integer-valued 0...255 samples via a histogram (exact, same result as numpy).
    static func medianByte(_ hist: [Int], _ n: Int) -> Double {
        func kth(_ k: Int) -> Double { var c = 0; for v in 0..<256 { c += hist[v]; if c > k { return Double(v) } }; return 255 }
        return n % 2 == 1 ? kth(n / 2) : (kth(n / 2 - 1) + kth(n / 2)) / 2
    }

    @inline(__always) static func clamp01(_ v: Double) -> Double { min(1.0, max(0.0, v)) }

    // ---- Panels and tiles ----
    /// A prepared panel: raw and Pillow-blurred pixels as Double (rows x cols x 3).
    public struct Prepared {
        public let raw: OccupancyRGBImage
        public let smooth: OccupancyRGBImage
    }

    public static func prepare(_ panel: OccupancyRGBImage) -> Prepared {
        // Only the board (64..576) is ever read from the smoothed panel; blur it with a 3 px margin (exact there).
        let lo = boardOrigin.0 - 3, hi = boardOrigin.0 + 8 * T + 3
        return Prepared(raw: panel, smooth: PillowBlur.gaussian(panel, radius: preBlurRadius, region: (lo, lo, hi, hi)))
    }

    /// Tile i (row-major 64x64) as SIMD3<Double>, optionally with per-channel gain/offset (tile * gain + offset).
    static func tile(_ img: OccupancyRGBImage, _ i: Int, gain: SIMD3<Double>? = nil, offset: SIMD3<Double>? = nil) -> [SIMD3<Double>] {
        let (x0, y0) = (boardOrigin.0 + (i % 8) * T, boardOrigin.1 + (i / 8) * T)
        var out = [SIMD3<Double>](repeating: .zero, count: T * T)
        img.pixels.withUnsafeBufferPointer { p in
            for r in 0..<T {
                let base = ((y0 + r) * img.width + x0) * 3
                for c in 0..<T {
                    let q = base + c * 3
                    var v = SIMD3<Double>(Double(p[q]), Double(p[q + 1]), Double(p[q + 2]))
                    if let g = gain, let o = offset { v = v * g + o }
                    out[r * T + c] = v
                }
            }
        }
        return out
    }

    // ---- Boundary sharpness (v2) ----
    public static func sharpness(_ smooth: OccupancyRGBImage) -> Double {
        let w = smooth.width
        func lumAt(_ y: Int, _ x: Int) -> Double {
            let q = (y * w + x) * 3
            return (Double(smooth.pixels[q]) + Double(smooth.pixels[q + 1]) + Double(smooth.pixels[q + 2])) / 3
        }
        func colMean(_ y: Int, _ x: Int) -> Double {  // 8 rows, numpy pairwise sum for n == 8
            let a = (0..<8).map { lumAt(y + $0, x) }
            return (((a[0] + a[1]) + (a[2] + a[3])) + ((a[4] + a[5]) + (a[6] + a[7]))) / 8
        }
        let (x0, y0) = boardOrigin
        var ratios: [Double] = []
        for r in 0..<8 {
            let ys = y0 + r * T + 4
            for c in 1..<8 {
                let x = x0 + c * T
                var near = -Double.infinity
                for o in -4...4 { near = max(near, abs(colMean(ys, x + o - 2) - colMean(ys, x + o + 1))) }
                let far = abs(colMean(ys, x - 9) - colMean(ys, x + 8))
                if far > 10 { ratios.append(near / far) }
            }
        }
        return ratios.isEmpty ? 0 : median(ratios)
    }

    /// v3.1 (Python _sharpness_reference_ok): only a finite number >= calSharpnessMin can serve as the blur gate's
    /// reference; with 0, a negative number, NaN or a missing value (read as NaN) the gate could never fire.
    public static func sharpnessReferenceOK(_ v: Double) -> Bool { v.isFinite && v >= calSharpnessMin }

    // ---- Morphology ----
    /// 4-neighbour dilation n times (zero outside), numpy _dilate.
    static func dilate(_ m: [Bool], _ n: Int) -> [Bool] {
        var out = m
        for _ in 0..<n {
            var g = out
            for r in 0..<T {
                for c in 0..<T where !out[r * T + c] {
                    if (r > 0 && out[(r - 1) * T + c]) || (r < T - 1 && out[(r + 1) * T + c])
                        || (c > 0 && out[r * T + c - 1]) || (c < T - 1 && out[r * T + c + 1]) { g[r * T + c] = true }
                }
            }
            out = g
        }
        return out
    }

    /// Pillow MinFilter(3) on a binary image: 3x3 minimum with edge replication (image.expand(1)).
    static func erode3(_ m: [Bool]) -> [Bool] {
        var out = [Bool](repeating: false, count: T * T)
        m.withUnsafeBufferPointer { p in
            out.withUnsafeMutableBufferPointer { o in
                for r in 0..<T {
                    let r0 = max(r - 1, 0) * T, r1 = r * T, r2 = min(r + 1, T - 1) * T
                    for c in 0..<T where p[r1 + c] {
                        let c0 = max(c - 1, 0), c2 = min(c + 1, T - 1)
                        o[r1 + c] = p[r0 + c0] && p[r0 + c] && p[r0 + c2] && p[r1 + c0] && p[r1 + c2]
                            && p[r2 + c0] && p[r2 + c] && p[r2 + c2]
                    }
                }
            }
        }
        return out
    }

    /// numpy _fill_holes: 4-connected flood of non-mask pixels from the tile border, at most T*4 growth steps.
    static func fillHoles(_ m: [Bool]) -> [Bool] {
        var dist = [Int](repeating: -1, count: T * T)
        var queue: [Int] = []
        queue.reserveCapacity(T * T)
        for i in 0..<(T * T) {
            let r = i / T, c = i % T
            if (r == 0 || r == T - 1 || c == 0 || c == T - 1) && !m[i] { dist[i] = 0; queue.append(i) }
        }
        var head = 0
        while head < queue.count {
            let i = queue[head]; head += 1
            if dist[i] >= T * 4 { continue }
            let r = i / T, c = i % T
            @inline(__always) func visit(_ j: Int) {
                if !m[j] && dist[j] < 0 { dist[j] = dist[i] + 1; queue.append(j) }
            }
            if r > 0 { visit(i - T) }
            if r < T - 1 { visit(i + T) }
            if c > 0 { visit(i - 1) }
            if c < T - 1 { visit(i + 1) }
        }
        return dist.map { $0 < 0 }
    }

    /// numpy _deep_core: integer weights (0 = not core).
    static func deepCore(_ fg: [Bool]) -> [Int] {
        var current = silClosePx > 0 ? fillHoles(dilate(fg, silClosePx)) : fillHoles(fg)
        for _ in 0..<silClosePx { current = erode3(current) }
        var depth = [Int](repeating: 0, count: T * T)
        for level in 1..<20 {
            current = erode3(current)
            if !current.contains(true) { break }
            for i in 0..<(T * T) where current[i] { depth[i] = level }
        }
        let floor = max(coreMinDepth, depth.max()! - coreDepthBand)
        return depth.map { $0 >= floor ? $0 - floor + 1 : 0 }
    }

    // ---- Local lighting ----
    public struct Local: Equatable {
        public var shift = 0.0, step = 0.0, side = 0.0, unexplained = 0.0
    }

    /// Centred running mean over rows with edge padding (cumsum difference, as numpy).
    static func runningMean(_ v: [SIMD3<Double>], _ n: Int) -> [SIMD3<Double>] {
        let pad = n / 2
        let padded = Array(repeating: v[0], count: pad) + v + Array(repeating: v[v.count - 1], count: pad)
        var c = [SIMD3<Double>](repeating: .zero, count: padded.count + 1)
        for i in 0..<padded.count { c[i + 1] = c[i] + padded[i] }
        return (0..<v.count).map { (c[$0 + n] - c[$0]) / Double(n) }
    }

    /// Box-constrained least squares per row: delta ~ k * ref + b * (1,1,1), |k| <= kmax, b >= bmin.
    static func lightingFit(_ delta: [SIMD3<Double>], _ ref: SIMD3<Double>, _ contrast: Double) -> ([SIMD3<Double>], [Double]) {
        let kmax = localMaxMult, bmin = -localMaxDarkHaze * contrast
        let rr = dot3(ref, ref), r1 = (ref.x + ref.y) + ref.z, n1 = 3.0
        let det = rr * n1 - r1 * r1
        var fits = [SIMD3<Double>](repeating: .zero, count: delta.count)
        var ress = [Double](repeating: 0, count: delta.count)
        for (i, d) in delta.enumerated() {
            let dr = dot3(d, ref), d1 = (d.x + d.y) + d.z
            let k0 = (dr * n1 - d1 * r1) / det, b0 = (rr * d1 - r1 * dr) / det
            var cands: [(Double, Double, Bool)] = [(k0, b0, abs(k0) <= kmax && b0 >= bmin)]
            for kf in [-kmax, kmax] { let bb = (d1 - kf * r1) / n1; cands.append((kf, bb, bb >= bmin)) }
            let kk = (dr - bmin * r1) / rr
            cands.append((kk, bmin, abs(kk) <= kmax))
            for kf in [-kmax, kmax] { cands.append((kf, bmin, true)) }
            var bestFit = SIMD3<Double>.zero, bestRes = Double.nan
            for (j, (k, b, ok)) in cands.enumerated() {
                let fit = SIMD3<Double>(k * ref.x + b, k * ref.y + b, k * ref.z + b)
                let res = ok ? norm3(d - fit) : Double.infinity
                if j == 0 || res < bestRes { bestFit = fit; bestRes = res }
            }
            fits[i] = bestFit; ress[i] = bestRes
        }
        return (fits, ress)
    }

    static func median5Rows(_ tile: [SIMD3<Double>], _ cols: Range<Int>, _ ref: SIMD3<Double>) -> [SIMD3<Double>] {
        stripRows.map { r in
            var out = SIMD3<Double>.zero
            for ch in 0..<3 {
                var v = cols.map { tile[r * T + $0][ch] }
                v.sort()
                out[ch] = v[v.count / 2]  // 5 values: exact middle
            }
            return out - ref
        }
    }

    static func localCorrection(_ tile: [SIMD3<Double>], _ ref: SIMD3<Double>, _ contrast: Double) -> ([SIMD3<Double>], Local) {
        let left = runningMean(median5Rows(tile, leftCols, ref), localSmoothRows)
        let right = runningMean(median5Rows(tile, rightCols, ref), localSmoothRows)
        let (fitL, resL) = lightingFit(left, ref, contrast)
        let (fitR, resR) = lightingFit(right, ref, contrast)
        let pad = (T - left.count) / 2
        func full(_ f: [SIMD3<Double>]) -> [SIMD3<Double>] {
            Array(repeating: f[0], count: pad) + f + Array(repeating: f[f.count - 1], count: pad)
        }
        let fl = full(fitL), fr = full(fitR)
        var offset = [SIMD3<Double>](repeating: .zero, count: T * T)
        for x in 0..<T {
            let w = min(1.0, max(0.0, (Double(x) - 5.0) / (Double(T) - 11.0)))
            for y in 0..<T { offset[y * T + x] = fl[y] * (1 - w) + fr[y] * w }
        }
        let lumL = fitL.map(lumOf), lumR = fitR.map(lumOf)
        var local = Local()
        local.shift = (lumL + lumR).map(abs).max()! / contrast
        func maxDiff(_ a: [Double]) -> Double { (1..<a.count).map { abs(a[$0] - a[$0 - 1]) }.max()! }
        local.step = max(maxDiff(lumL), maxDiff(lumR)) / contrast
        local.side = zip(lumL, lumR).map { abs($0 - $1) }.max()! / contrast
        local.unexplained = max(resL.max()!, resR.max()!) / contrast
        return (offset, local)
    }

    static func edges(_ tile: [SIMD3<Double>], _ contrast: Double) -> [Bool] {
        let l = tile.map(lumOf)
        var e = [Bool](repeating: false, count: T * T)
        let level = edgeLevel * contrast
        for r in 0..<T { for c in 1..<(T - 1) { e[r * T + c] = abs(l[r * T + c + 1] - l[r * T + c - 1]) / 2 > level } }
        return e
    }

    public struct Fill {
        public var pixels: [SIMD3<Double>]
        public var weights: [Double]
    }

    public struct Measure {
        public var fg = 0.0, border = 0.0, edge = 0.0
        public var fill: Fill?
        public var local = Local()
    }

    static func measure(_ tile: [SIMD3<Double>], _ ref: SIMD3<Double>, _ contrast: Double) -> Measure {
        let (offset, local) = localCorrection(tile, ref, contrast)
        var corrected = [SIMD3<Double>](repeating: .zero, count: T * T)
        var fg = [Bool](repeating: false, count: T * T)
        var dist = [Double](repeating: 0, count: T * T)
        var fgCount = 0
        for i in 0..<(T * T) {
            corrected[i] = tile[i] - offset[i]
            dist[i] = norm3(corrected[i] - ref)
            if windowMask[i] && dist[i] > fgDistance { fg[i] = true; fgCount += 1 }
        }
        var m = Measure()
        m.local = local
        m.fg = Double(fgCount) / Double(windowCount)
        var nb = 0
        for q in topBotIndices where dist[q] > fgDistance { nb += 1 }
        m.border = Double(nb) / Double(topBotIndices.count)
        let e = edges(tile, contrast)
        var ne = 0
        for q in 0..<(T * T) where e[q] && windowMask[q] { ne += 1 }
        m.edge = Double(ne) / Double(windowCount)
        if fgCount >= minFillPixels {
            var weights = deepCore(fg)
            if fillEdgeGuard >= 0 {
                let guardMask = fillEdgeGuard > 0 ? dilate(e, fillEdgeGuard) : e
                for i in 0..<(T * T) where guardMask[i] { weights[i] = 0 }
            }
            for i in (colourMaxRow * T)..<(T * T) { weights[i] = 0 }
            var px: [SIMD3<Double>] = [], wt: [Double] = []
            for i in 0..<(T * T) where weights[i] > 0 { px.append(corrected[i]); wt.append(Double(weights[i])) }
            if px.count >= minFillPixels { m.fill = Fill(pixels: px, weights: wt) }
        }
        return m
    }

    /// Depth-weighted vote: (label, share, median distance to the nearer reference).
    static func vote(_ fill: Fill, _ white: SIMD3<Double>, _ black: SIMD3<Double>) -> (String, Double, Double) {
        var wsum = 0.0, total = 0.0
        var mins = [Double](); mins.reserveCapacity(fill.pixels.count)
        for (p, w) in zip(fill.pixels, fill.weights) {
            let dw = norm3(p - white), db = norm3(p - black)
            if dw < db { wsum += w }
            total += w
            mins.append(min(dw, db))
        }
        let share = wsum / total
        return (share >= 0.5 ? "white" : "black", max(share, 1 - share), median(mins))
    }

    static func cues(_ m: Measure) -> (String, String) {
        let fgCue = m.fg <= emptyMaxFg ? "empty" : (m.fg >= pieceMinFg ? "piece" : "ambiguous")
        let edgeCue = m.edge <= emptyMaxEdge ? "empty" : (m.edge >= pieceMinEdge ? "piece" : "ambiguous")
        return (fgCue, edgeCue)
    }

    /// (clipped share, forces abstention). Uses the RAW (unblurred) tile.
    static func saturation(_ raw: OccupancyRGBImage, _ i: Int, _ local: Local) -> (Double, Bool) {
        let (x0, y0) = (boardOrigin.0 + (i % 8) * T, boardOrigin.1 + (i / 8) * T)
        var clipped = [Bool](repeating: false, count: T * T)
        var n = 0
        for r in 0..<T {
            for c in 0..<T {
                let q = ((y0 + r) * raw.width + x0 + c) * 3
                if min(raw.pixels[q], raw.pixels[q + 1], raw.pixels[q + 2]) >= UInt8(saturatedLevel) { clipped[r * T + c] = true; n += 1 }
            }
        }
        let frac = Double(n) / Double(T * T)
        if frac <= saturatedMaxFrac { return (frac, false) }
        let ring = Double(borderIndices.filter { clipped[$0] }.count) / Double(borderIndices.count)
        let calm = local.shift <= saturatedOkMaxShift && ring <= saturatedOkMaxRing
        return (frac, !calm)
    }

    static func sharpLighting(_ l: Local) -> Bool { l.step > localMaxStep || l.side > localSideMax }

    static func localReasons(_ l: Local) -> [String] {
        var r: [String] = []
        if l.shift > localMaxShift { r.append("local-lighting-too-strong") }
        if l.step > localMaxStep { r.append("local-lighting-stripe") }
        if l.side > localSideMax { r.append("local-lighting-uneven") }
        if l.unexplained > localMaxUnexplained { r.append("local-change-is-not-lighting") }
        return r
    }

    // ---- Calibration ----
    public struct Calibration {
        public var emptyRef: [SIMD3<Double>]  // [light, dark]
        public var contrast: Double
        public var boundarySharpness: Double
        public var whiteRef: SIMD3<Double>
        public var blackRef: SIMD3<Double>
        public init(emptyRef: [SIMD3<Double>], contrast: Double, boundarySharpness: Double,
                    whiteRef: SIMD3<Double>, blackRef: SIMD3<Double>) {
            self.emptyRef = emptyRef; self.contrast = contrast; self.boundarySharpness = boundarySharpness
            self.whiteRef = whiteRef; self.blackRef = blackRef
        }
    }

    public struct CalibrationError: Error, CustomStringConvertible {
        public let message: String
        public let problems: [(String, String)]
        public var description: String { message }
    }

    /// occupancy: 64 labels "empty"/"white"/"black" in PANEL tile order (a8..h1 of the panel).
    public static func calibrate(_ prepared: Prepared, occupancy: [String]) throws -> Calibration {
        guard occupancy.count == 64, occupancy.allSatisfy({ ["empty", "white", "black"].contains($0) }) else {
            throw CalibrationError(message: "occupancy must label all 64 squares empty/white/black", problems: [])
        }
        let tiles = (0..<64).map { tile(prepared.smooth, $0) }
        var emptyRef: [SIMD3<Double>] = []
        for parity in 0..<2 {
            let idx = (0..<64).filter { occupancy[$0] == "empty" && dark[$0] == parity }
            if idx.count < minSamplesPerClass {
                throw CalibrationError(message: "too-few-empty-\(parity == 1 ? "dark" : "light")-squares", problems: [])
            }
            var hist = [[Int]](repeating: [Int](repeating: 0, count: 256), count: 3)
            var n = 0
            for i in idx { for p in 0..<(T * T) where borderOrWindow[p] { n += 1; for c in 0..<3 { hist[c][Int(tiles[i][p][c])] += 1 } } }
            emptyRef.append(SIMD3(medianByte(hist[0], n), medianByte(hist[1], n), medianByte(hist[2], n)))
        }
        let contrast = abs(lumOf(emptyRef[0] - emptyRef[1]))
        if contrast < 10 { throw CalibrationError(message: "light-and-dark-squares-indistinguishable", problems: []) }
        let measures = (0..<64).map { measure(tiles[$0], emptyRef[dark[$0]], contrast) }
        var fills: [String: [SIMD3<Double>]] = [:]
        for colour in ["white", "black"] {
            let idx = (0..<64).filter { occupancy[$0] == colour && measures[$0].fill != nil }
            if idx.count < minSamplesPerClass {
                throw CalibrationError(message: "too-few-\(colour)-pieces-with-readable-fill", problems: [])
            }
            fills[colour] = idx.flatMap { measures[$0].fill!.pixels }
        }
        func halfMedian(_ px: [SIMD3<Double>], bright: Bool) -> SIMD3<Double> {
            let l = px.map(lumOf)
            let med = median(l)
            let sel = px.indices.filter { bright ? l[$0] >= med : l[$0] <= med }.map { px[$0] }
            return SIMD3(median(sel.map { $0.x }), median(sel.map { $0.y }), median(sel.map { $0.z }))
        }
        let whiteRef = halfMedian(fills["white"]!, bright: true)
        let blackRef = halfMedian(fills["black"]!, bright: false)
        var problems: [(String, String)] = []
        var shares: [String: [Double]] = [:]
        var shareOrder: [String] = []
        if lumOf(whiteRef - blackRef) < colorMinSeparation * 255 { problems.append(("*", "white-fill-not-lighter-than-black")) }
        for i in 0..<64 {
            let m = measures[i]
            var reasons = localReasons(m.local)
            if saturation(prepared.raw, i, m.local).1 { reasons.append("saturated-pixels") }
            if m.border > borderMaxFrac { reasons.append("background-mismatch") }
            let (fgCue, edgeCue) = cues(m)
            if occupancy[i] == "empty" {
                if fgCue != "empty" || edgeCue != "empty" { reasons.append("stated-empty-but-occupied") }
            } else if fgCue != "piece" || edgeCue != "piece" || m.fill == nil {
                reasons.append("stated-occupied-but-empty")
            } else {
                let (label, share, dist) = vote(m.fill!, whiteRef, blackRef)
                if label != occupancy[i] || share < calVoteMin || dist > colorMaxDist {
                    reasons.append("stated-\(occupancy[i])-colour-mismatch")
                } else {
                    if shares[occupancy[i]] == nil { shareOrder.append(occupancy[i]) }
                    shares[occupancy[i], default: []].append(share)
                }
            }
            if let first = reasons.first { problems.append((squares[i], first)) }
        }
        for colour in shareOrder {
            let v = shares[colour]!
            if v.reduce(0, +) / Double(v.count) < calVoteMeanMin { problems.append(("*", "\(colour)-pieces-colour-vote-weak")) }
        }
        if !problems.isEmpty {
            let msg = "\(problems.count) square(s) disagree with stated occupancy: "
                + problems.prefix(8).map { "\($0.0):\($0.1)" }.joined(separator: ", ")
            throw CalibrationError(message: msg, problems: problems)
        }
        let sharp = sharpness(prepared.smooth)
        if !sharpnessReferenceOK(sharp) {  // v3.1: no usable reference for the blur gate -> not a start picture
            throw CalibrationError(message: "start-boundary-sharpness-unusable:\(sharp)", problems: [])
        }
        return Calibration(emptyRef: emptyRef, contrast: contrast, boundarySharpness: sharp,
                           whiteRef: whiteRef, blackRef: blackRef)
    }

    // ---- Classification ----
    public struct Cell {
        public var label: String
        public var rawLabel: String?
        public var confidence: Double
        public var reasons: [String]
        public var detail: [(String, Any)]  // fgFrac, edgeFrac, ... (same keys as Python's cell)
    }

    static func abstainAll(_ reason: String) -> [Cell] {
        (0..<64).map { _ in Cell(label: "unknown", rawLabel: nil, confidence: 0, reasons: [reason], detail: []) }
    }

    /// Python round(v, n) for reporting (half-even on the decimal value is not reproduced; ties are rare).
    public static func round(_ v: Double, _ n: Int) -> Double {
        let s = pow(10.0, Double(n))
        return (v * s).rounded() / s
    }

    /// Returns 64 cells in PANEL tile order.
    public static func classify(_ prepared: Prepared, calibration cal: Calibration) -> [Cell] {
        if !sharpnessReferenceOK(cal.boundarySharpness) { return abstainAll("calibration-sharpness-invalid") }  // v3.1
        let e0 = cal.emptyRef[0], e1 = cal.emptyRef[1]
        var hist = [[[Int]]](repeating: [[Int]](repeating: [Int](repeating: 0, count: 256), count: 3), count: 2)
        var counts = [0, 0]
        let sm = prepared.smooth
        for i in 0..<64 {
            let p = dark[i]
            let (x0, y0) = (boardOrigin.0 + (i % 8) * T, boardOrigin.1 + (i / 8) * T)
            for q in borderIndices {
                let o = ((y0 + q / T) * sm.width + x0 + q % T) * 3
                counts[p] += 1
                for c in 0..<3 { hist[p][c][Int(sm.pixels[o + c])] += 1 }
            }
        }
        let observed = (0..<2).map { p in SIMD3((0..<3).map { medianByte(hist[p][$0], counts[p]) }) }
        let span = observed[0] - observed[1]
        if abs(span.x) < 1e-6 || abs(span.y) < 1e-6 || abs(span.z) < 1e-6 { return abstainAll("lighting-out-of-range") }
        let gain = (e0 - e1) / span
        let offset = e0 - gain * observed[0]
        for c in 0..<3 where !(gain[c] >= gainRange.0 && gain[c] <= gainRange.1) { return abstainAll("lighting-out-of-range") }
        if sharpness(sm) < frameSharpnessMin * cal.boundarySharpness { return abstainAll("frame-too-blurry") }
        let measures = (0..<64).map { measure(tile(sm, $0, gain: gain, offset: offset), cal.emptyRef[dark[$0]], cal.contrast) }
        let sharp = measures.map { sharpLighting($0.local) }
        var out: [Cell] = []
        for i in 0..<64 {
            let m = measures[i]
            let (saturated, satBad) = saturation(prepared.raw, i, m.local)
            var reasons = localReasons(m.local)
            var scores: [Double] = [clamp01(1 - m.border / (2 * borderMaxFrac)),
                                    satBad ? clamp01(1 - saturated / (2 * saturatedMaxFrac)) : 1.0]
            if m.border > borderMaxFrac { reasons.append("background-mismatch") }
            if satBad { reasons.append("saturated-pixels") }
            if neighbourRule != 0 {
                let r = i / 8, c = i % 8
                var hit = false
                for dr in -1...1 { for dc in -1...1 where (dr != 0 || dc != 0) && (0..<8).contains(r + dr) && (0..<8).contains(c + dc) {
                    if sharp[(r + dr) * 8 + c + dc] { hit = true } } }
                if hit { reasons.append("neighbour-lighting-not-smooth") }
            }
            let (fgCue, edgeCue) = cues(m)
            if fgCue != edgeCue || fgCue == "ambiguous" { reasons.append("occupancy-cues-disagree:\(fgCue)/\(edgeCue)") }
            if fgCue == "empty" { scores.append(clamp01(0.5 + 0.5 * (emptyMaxFg - m.fg) / emptyMaxFg)) }
            else if fgCue == "piece" { scores.append(clamp01(0.5 + 0.5 * (m.fg - pieceMinFg) / pieceMinFg)) }
            else { scores.append(0) }
            var label = fgCue == "empty" ? "empty" : "piece"
            var colourInfo: [(String, Any)] = []
            if label == "piece" {
                if let fill = m.fill {
                    let (l, share, dist) = vote(fill, cal.whiteRef, cal.blackRef)
                    label = l
                    colourInfo = [("colourShare", round(share, 4)), ("colourDist", round(dist, 2)), ("fillPixels", fill.pixels.count)]
                    scores.append(min(clamp01(0.5 + 0.5 * (share - colorVoteMin) / (1 - colorVoteMin)),
                                      clamp01(1 - dist / (2 * colorMaxDist))))
                    if share < colorVoteMin { reasons.append("ambiguous-colour") }
                    if dist > colorMaxDist { reasons.append("unfamiliar-foreground-colour") }
                } else {
                    reasons.append("no-fill-colour"); scores.append(0)
                }
            }
            if !reasons.isEmpty { scores.append(0) }
            let confidence = scores.min()!
            let detail: [(String, Any)] = [("fgFrac", round(m.fg, 4)), ("edgeFrac", round(m.edge, 4)),
                                           ("borderFrac", round(m.border, 4)), ("saturatedFrac", round(saturated, 4)),
                                           ("local", [("shift", round(m.local.shift, 3)), ("step", round(m.local.step, 3)),
                                                      ("side", round(m.local.side, 3)),
                                                      ("unexplained", round(m.local.unexplained, 3))] as [(String, Any)])]
                + colourInfo
            let conf = round(confidence, 4)
            if !reasons.isEmpty || confidence < abstainBelow {
                out.append(Cell(label: "unknown", rawLabel: label, confidence: conf,
                                reasons: reasons.isEmpty ? ["low-confidence"] : reasons, detail: detail))
            } else {
                out.append(Cell(label: label, rawLabel: label, confidence: conf, reasons: [], detail: detail))
            }
        }
        return out
    }

    // ---- Orientation (screen_pipeline.py screen_from_a8 / a8_from_screen) ----
    /// np.rot90(grid, k) on an 8x8 grid stored row-major (k counter-clockwise quarter turns).
    public static func rot90<T>(_ v: [T], _ k: Int) -> [T] {
        var g = v
        for _ in 0..<(((k % 4) + 4) % 4) {
            var n = g
            for i in 0..<8 { for j in 0..<8 { n[i * 8 + j] = g[j * 8 + (7 - i)] } }
            g = n
        }
        return g
    }

    /// Board a8..h1 order -> screen-upright panel tile order, when detector corner r is a8.
    public static func screenFromA8<T>(_ v: [T], _ r: Int) -> [T] { rot90(v, -r) }
    /// Panel tile order -> board a8..h1 order.
    public static func a8FromScreen<T>(_ v: [T], _ r: Int) -> [T] { rot90(v, r) }
}
