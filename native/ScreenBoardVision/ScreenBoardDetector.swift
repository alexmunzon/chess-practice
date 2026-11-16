import Foundation

/// Finds an 8x8 chess board shown on a screen, without fiducial markers.
///
/// Method: X-corner (saddle) detection on a half-resolution image, lattice growth over
/// corners with alternating polarity, placement of the 7x7 internal-corner block that best
/// explains an 8x8 checker with a non-checker ring outside it, sub-pixel refinement at full
/// resolution, robust homography fit, and outer corners extrapolated from the lattice.
/// The bezel, page and other rectangles have no X-corners, so they cannot be selected.
struct DetectorParameters {
    var ringRadius: Float = 5            // half-res pixels
    var preBlurSigma: Float = 0.8        // half-res pre-smoothing
    var minResponseAbsolute: Float = 60  // ChESS units (gray levels x ~8)
    var minResponseFraction: Float = 0.06
    var maxCandidates = 900
    var maxSeeds = 60
    var matchTolerance: Double = 0.28    // fraction of local square size
    var polarityThreshold: Float = -0.2  // cos of 2nd-harmonic phase difference, adjacent corners
    var minLatticePoints = 16
    var maxTrimmedEdgePoints = 3         // sparse 8th row of board-edge junctions that may be trimmed
    var minSpan = 4                      // internal-corner span needed in both directions (max 6)
    var minCellAgreement: Double = 0.80
    var maxRingRatio: Double = 0.45
    var minPlacementMargin: Double = 0.35
    var minCheckerContrast: Double = 8   // gray levels
    var refineSigma: Float = 1.0
    var minConfidence: Double = 0.55
    /// Curved-edge self-check: the outer corners from the straight-line (homography) fit and from a
    /// fit with one radial (barrel/pincushion) lens term may differ by at most this share of the
    /// board side. Set a priori to half the 5 % wrong-corner line, not tuned on pictures.
    var maxCurveShiftFraction: Double = 0.025
}

struct Detection {
    var found = false
    var corners: [Point2] = []
    var confidence = 0.0
    var reason = ""
    var candidates = 0
    var latticePoints = 0
    var span = (0, 0)
    var cellAgreement = 0.0
    var ringRatio = 0.0
    var placementMargin = -1.0
    var fitRMS = -1.0
    var lensK1 = 0.0          // radial term of the best lens fit (r normalized by the image half-diagonal)
    var curveShift = -1.0     // largest outer-corner disagreement, straight vs lens fit, share of board side
    var lensK2 = 0.0          // second radial term of the lens fit (r^4)
    var lensCentre = (-1.0, -1.0)  // fitted lens centre, image pixels
}

private struct XCorner { var x: Double; var y: Double; var r: Float; var zr: Float; var zi: Float }
private struct Key: Hashable { var i: Int; var j: Int }

struct ScreenBoardDetector {
    var params = DetectorParameters()

    func detect(_ full: GrayImage) -> Detection {
        var result = Detection()
        let half = full.halved().blurred(sigma: params.preBlurSigma)
        let corners = xCorners(half)
        result.candidates = corners.count
        guard corners.count >= params.minLatticePoints else { result.reason = "too-few-x-corners"; return result }

        guard var (lattice, hHalf) = bestLattice(corners) else { result.reason = "no-lattice"; return result }
        // Board-edge T-junctions can attach as a sparse 8th row/column of the lattice. Trim a
        // sparse end row; a densely populated 8th row means a grid larger than 8x8 (reject).
        for axis in 0..<2 {
            while true {
                let vals = lattice.keys.map { axis == 0 ? $0.i : $0.j }
                guard let lo = vals.min(), let hi = vals.max(), hi - lo > 6 else { break }
                let nLo = vals.filter { $0 == lo }.count, nHi = vals.filter { $0 == hi }.count
                let drop = nLo <= nHi ? lo : hi
                if min(nLo, nHi) > params.maxTrimmedEdgePoints { break }
                lattice = lattice.filter { (axis == 0 ? $0.key.i : $0.key.j) != drop }
            }
        }
        result.latticePoints = lattice.count
        let iv = lattice.keys.map(\.i), jv = lattice.keys.map(\.j)
        let (imin, imax, jmin, jmax) = (iv.min()!, iv.max()!, jv.min()!, jv.max()!)
        result.span = (imax - imin, jmax - jmin)
        guard lattice.count >= params.minLatticePoints else { result.reason = "lattice-too-small"; return result }
        guard imax - imin <= 6, jmax - jmin <= 6 else { result.reason = "grid-larger-than-8x8"; return result }
        guard imax - imin >= params.minSpan, jmax - jmin >= params.minSpan else { result.reason = "lattice-span-too-small"; return result }

        // Lattice -> full-res image. Half-res pixel k has its center at full-res 2k + 0.5.
        let toFull = Homography(h: [2, 0, 0.5, 0, 2, 0.5, 0, 0, 1])
        var hFull = Homography(h: Homography.mul(toFull.h, hHalf.h))
        let smooth = full.blurred(sigma: params.refineSigma)

        // Sub-pixel refinement of detected lattice corners, then robust refit.
        var src: [Point2] = [], dst: [Point2] = []
        for (k, idx) in lattice {
            let p0 = Point2(x: 2 * corners[idx].x + 0.5, y: 2 * corners[idx].y + 0.5)
            let s = localSquare(hFull, Double(k.i), Double(k.j))
            if let p = refine(smooth, p0, radius: Int(min(12, max(3, 0.22 * s)).rounded()), limit: 0.25 * s) {
                src.append(Point2(x: Double(k.i), y: Double(k.j))); dst.append(p)
            }
        }
        guard src.count >= params.minLatticePoints, var fit = Homography.fit(src, dst) else {
            result.reason = "refinement-failed"; return result
        }
        var rms = 0.0
        for _ in 0..<3 {
            let res = zip(src, dst).map { s, d -> Double in let q = fit.apply(s.x, s.y); return hypot(q.x - d.x, q.y - d.y) }
            let med = res.sorted()[res.count / 2]
            let keep = res.indices.filter { res[$0] <= max(1.0, 2.5 * med) }
            if keep.count == res.count || keep.count < params.minLatticePoints { rms = sqrt(res.map { $0 * $0 }.reduce(0, +) / Double(res.count)); break }
            src = keep.map { src[$0] }; dst = keep.map { dst[$0] }
            guard let f = Homography.fit(src, dst) else { break }
            fit = f
        }
        if rms == 0 {
            let res = zip(src, dst).map { s, d -> Double in let q = fit.apply(s.x, s.y); return hypot(q.x - d.x, q.y - d.y) }
            rms = sqrt(res.map { $0 * $0 }.reduce(0, +) / Double(max(1, res.count)))
        }
        hFull = fit
        result.fitRMS = rms

        // Choose which 7x7 internal-corner block is the board (resolves partial lattices).
        var scored: [(score: Double, a: Int, b: Int, agree: Double, ring: Double, contrast: Double)] = []
        for a in (imax - 6)...imin {
            for b in (jmax - 6)...jmin {
                let s = placementScore(smooth, hFull, a, b)
                scored.append((s.agree - s.ring, a, b, s.agree, s.ring, s.contrast))
            }
        }
        scored.sort { $0.score > $1.score }
        let best = scored[0]
        result.cellAgreement = best.agree
        result.ringRatio = best.ring
        let margin = scored.count > 1 ? best.score - scored[1].score : 1.0
        result.placementMargin = scored.count > 1 ? margin : -1

        let quad = [(best.a - 1, best.b - 1), (best.a + 7, best.b - 1), (best.a + 7, best.b + 7), (best.a - 1, best.b + 7)]
            .map { hFull.apply(Double($0.0), Double($0.1)) }
        result.corners = ordered(quad)

        // Curved-edge self-check. A wide lens bends straight board edges; a homography fitted to the
        // inner grid then extrapolates the outer corners to the wrong place. Fit the same grid points with
        // one radial lens term (free centre) and compare the outer corners of the two models.
        let outerIJ = [(best.a - 1, best.b - 1), (best.a + 7, best.b - 1), (best.a + 7, best.b + 7), (best.a - 1, best.b + 7)]
        if let lens = ScreenBoardDetector.radialFit(src, dst, width: full.width, height: full.height) {
            result.lensK1 = lens.k1
            result.lensK2 = lens.k2
            result.lensCentre = (lens.c.x, lens.c.y)
            result.curveShift = ScreenBoardDetector.curveShift(lens, outerIJ: outerIJ, quad: quad)
        } else {
            result.curveShift = .nan
        }

        let support = min(1.0, Double(src.count) / 25.0)
        let marginFactor = scored.count > 1 ? min(1.0, margin / 0.7) : 1.0
        result.confidence = max(0, min(1, best.agree * (1 - best.ring) * support * marginFactor))

        if best.contrast < params.minCheckerContrast { result.reason = "checker-contrast-too-low"; return result }
        if best.agree < params.minCellAgreement { result.reason = "not-an-8x8-checker"; return result }
        if best.ring > params.maxRingRatio { result.reason = "checker-continues-outside-8x8"; return result }
        if scored.count > 1 && margin < params.minPlacementMargin { result.reason = "ambiguous-board-placement"; return result }
        if result.confidence < params.minConfidence { result.reason = "low-confidence"; return result }
        if let why = ScreenBoardDetector.curveVerdict(result.curveShift, limit: params.maxCurveShiftFraction) {
            result.reason = why; return result
        }
        result.found = true
        result.reason = "ok"
        return result
    }

    // MARK: X-corners (ChESS-style ring response)

    private func xCorners(_ img: GrayImage) -> [XCorner] {
        let w = img.width, h = img.height
        let r = params.ringRadius
        let border = Int(r.rounded(.up)) + 2
        var offs: [(Int, Float, Float)] = []   // (base offset, fx, fy) per ring sample
        var cosT: [Float] = [], sinT: [Float] = []
        for n in 0..<16 {
            let t = Float(n) * 2 * .pi / 16
            let dx = r * cos(t), dy = r * sin(t)
            let ix = Int(floor(dx)), iy = Int(floor(dy))
            offs.append((iy * w + ix, dx - Float(ix), dy - Float(iy)))
            cosT.append(cos(2 * t)); sinT.append(sin(2 * t))
        }
        var resp = [Float](repeating: 0, count: w * h)
        var maxR: Float = 0
        img.pixels.withUnsafeBufferPointer { p in
            var s = [Float](repeating: 0, count: 16)
            for y in border..<(h - border) {
                for x in border..<(w - border) {
                    let c = y * w + x
                    var sum: Float = 0
                    for n in 0..<16 {
                        let (o, fx, fy) = offs[n]
                        let i = c + o
                        let a = p[i], b = p[i + 1], cc = p[i + w], d = p[i + w + 1]
                        let v = a + (b - a) * fx + (cc - a) * fy + (a - b - cc + d) * fx * fy
                        s[n] = v; sum += v
                    }
                    var sr: Float = 0, dr: Float = 0
                    for n in 0..<4 { sr += abs(s[n] + s[n + 8] - s[n + 4] - s[n + 12]) }
                    for n in 0..<8 { dr += abs(s[n] - s[n + 8]) }
                    let local = (p[c] + p[c - 1] + p[c + 1] + p[c - w] + p[c + w]) / 5
                    let rr = sr - dr - abs(sum / 16 - local) * 16
                    resp[c] = rr
                    if rr > maxR { maxR = rr }
                }
            }
        }
        let thr = max(params.minResponseAbsolute, params.minResponseFraction * maxR)
        var out: [XCorner] = []
        let nms = 3
        for y in (border + nms)..<(h - border - nms) {
            for x in (border + nms)..<(w - border - nms) {
                let v = resp[y * w + x]
                if v < thr { continue }
                var isMax = true
                outer: for dy in -nms...nms {
                    for dx in -nms...nms where dx != 0 || dy != 0 {
                        let q = resp[(y + dy) * w + x + dx]
                        if q > v || (q == v && (dy < 0 || (dy == 0 && dx < 0))) { isMax = false; break outer }
                    }
                }
                if !isMax { continue }
                let l = resp[y * w + x - 1], rr = resp[y * w + x + 1], u = resp[(y - 1) * w + x], d = resp[(y + 1) * w + x]
                let ddx = l - 2 * v + rr, ddy = u - 2 * v + d
                let ox = ddx < 0 ? Double(max(-0.5, min(0.5, 0.5 * (l - rr) / ddx))) : 0
                let oy = ddy < 0 ? Double(max(-0.5, min(0.5, 0.5 * (u - d) / ddy))) : 0
                var zr: Float = 0, zi: Float = 0
                for n in 0..<16 {
                    let t = Float(n) * 2 * .pi / 16
                    let sv = img.sample(Float(x) + r * cos(t), Float(y) + r * sin(t))
                    zr += sv * cosT[n]; zi -= sv * sinT[n]
                }
                let m = max(1e-6, (zr * zr + zi * zi).squareRoot())
                out.append(XCorner(x: Double(x) + ox, y: Double(y) + oy, r: v, zr: zr / m, zi: zi / m))
            }
        }
        out.sort { $0.r > $1.r }
        if out.count > params.maxCandidates { out.removeLast(out.count - params.maxCandidates) }
        return out
    }

    // MARK: Lattice growth

    private func bestLattice(_ pts: [XCorner]) -> ([Key: Int], Homography)? {
        let cell = 16.0
        var buckets: [Key: [Int]] = [:]
        for (i, p) in pts.enumerated() { buckets[Key(i: Int(p.x / cell), j: Int(p.y / cell)), default: []].append(i) }
        func nearest(_ x: Double, _ y: Double, _ radius: Double, _ used: Set<Int>) -> Int? {
            let r = Int((radius / cell).rounded(.up))
            let cx = Int(x / cell), cy = Int(y / cell)
            var best: Int? = nil, bd = radius
            for by in (cy - r)...(cy + r) { for bx in (cx - r)...(cx + r) {
                for i in buckets[Key(i: bx, j: by)] ?? [] where !used.contains(i) {
                    let d = hypot(pts[i].x - x, pts[i].y - y)
                    if d < bd { bd = d; best = i }
                }
            } }
            return best
        }
        func pol(_ a: Int, _ b: Int) -> Float { pts[a].zr * pts[b].zr + pts[a].zi * pts[b].zi }

        var best: ([Key: Int], Homography)? = nil
        var claimed = Set<Int>()
        for seed in 0..<min(params.maxSeeds, pts.count) where !claimed.contains(seed) {
            let c = pts[seed]
            var cand: [(Int, Double)] = []
            for i in pts.indices where i != seed && pol(i, seed) < params.polarityThreshold {
                let d: Double = hypot(pts[i].x - c.x, pts[i].y - c.y)
                if d > 3 && d < 260 { cand.append((i, d)) }
            }
            cand.sort { $0.1 < $1.1 }
            let neigh: [Int] = cand.prefix(6).map { $0.0 }
            var pairs: [(Int, Int, Double)] = []
            for (ia, a) in neigh.enumerated() { for b in neigh[(ia + 1)...] {
                let ux = pts[a].x - c.x, uy = pts[a].y - c.y, vx = pts[b].x - c.x, vy = pts[b].y - c.y
                let lu = hypot(ux, uy), lv = hypot(vx, vy)
                guard lu / lv < 2, lv / lu < 2, abs(ux * vy - uy * vx) / (lu * lv) > 0.64 else { continue }
                pairs.append((a, b, lu + lv))
            } }
            pairs.sort { $0.2 < $1.2 }
            for (a, b, _) in pairs.prefix(3) {
                guard let grown = grow(pts, seed: seed, a: a, b: b, nearest: nearest, pol: pol) else { continue }
                if best == nil || grown.0.count > best!.0.count { best = grown }
            }
            if let b = best, b.0.count >= 20 { claimed.formUnion(b.0.values) }
            if let b = best, b.0.count >= 45 { break }
        }
        return best
    }

    private func grow(_ pts: [XCorner], seed: Int, a: Int, b: Int,
                      nearest: (Double, Double, Double, Set<Int>) -> Int?,
                      pol: (Int, Int) -> Float) -> ([Key: Int], Homography)? {
        let c = pts[seed]
        let u = (pts[a].x - c.x, pts[a].y - c.y), v = (pts[b].x - c.x, pts[b].y - c.y)
        var known: [Key: Int] = [Key(i: 0, j: 0): seed, Key(i: 1, j: 0): a, Key(i: 0, j: 1): b]
        var used: Set<Int> = [seed, a, b]
        var model: Homography? = nil
        func predict(_ i: Int, _ j: Int) -> Point2 {
            if let m = model { return m.apply(Double(i), Double(j)) }
            return Point2(x: c.x + Double(i) * u.0 + Double(j) * v.0, y: c.y + Double(i) * u.1 + Double(j) * v.1)
        }
        for _ in 0..<20 {
            var frontier = Set<Key>()
            for k in known.keys {
                for (di, dj) in [(1, 0), (-1, 0), (0, 1), (0, -1)] {
                    let n = Key(i: k.i + di, j: k.j + dj)
                    if known[n] == nil && abs(n.i) <= 10 && abs(n.j) <= 10 { frontier.insert(n) }
                }
            }
            var additions: [(Key, Int)] = []
            for f in frontier.sorted(by: { ($0.i, $0.j) < ($1.i, $1.j) }) {
                let p = predict(f.i, f.j)
                let px = predict(f.i + 1, f.j), py = predict(f.i, f.j + 1)
                let s = min(hypot(px.x - p.x, px.y - p.y), hypot(py.x - p.x, py.y - p.y))
                guard s > 3, let idx = nearest(p.x, p.y, params.matchTolerance * s, used) else { continue }
                let nb = [(1, 0), (-1, 0), (0, 1), (0, -1)].compactMap { known[Key(i: f.i + $0.0, j: f.j + $0.1)] }
                guard !nb.isEmpty, nb.allSatisfy({ pol(idx, $0) < params.polarityThreshold }) else { continue }
                additions.append((f, idx))
                used.insert(idx)
            }
            if additions.isEmpty { break }
            for (k, idx) in additions { known[k] = idx }
            let iv = Set(known.keys.map(\.i)), jv = Set(known.keys.map(\.j))
            if known.count >= 5 && iv.count >= 2 && jv.count >= 2 {
                let src = known.keys.map { Point2(x: Double($0.i), y: Double($0.j)) }
                let dst = known.values.map { Point2(x: pts[$0].x, y: pts[$0].y) }
                if let m = Homography.fit(src, dst) { model = m }
            }
        }
        guard known.count >= 6, let m = model else { return nil }
        // Drop points that disagree with the global fit.
        var kept: [Key: Int] = [:]
        for (k, idx) in known {
            let p = m.apply(Double(k.i), Double(k.j))
            let q = m.apply(Double(k.i + 1), Double(k.j))
            if hypot(p.x - pts[idx].x, p.y - pts[idx].y) <= 0.2 * hypot(q.x - p.x, q.y - p.y) { kept[k] = idx }
        }
        let src = kept.keys.map { Point2(x: Double($0.i), y: Double($0.j)) }
        let dst = kept.values.map { Point2(x: pts[$0].x, y: pts[$0].y) }
        guard kept.count >= 6, let fit = Homography.fit(src, dst) else { return nil }
        return (kept, fit)
    }

    // MARK: Refinement and verification

    private func localSquare(_ h: Homography, _ i: Double, _ j: Double) -> Double {
        let p = h.apply(i, j), a = h.apply(i + 1, j), b = h.apply(i, j + 1)
        return min(hypot(a.x - p.x, a.y - p.y), hypot(b.x - p.x, b.y - p.y))
    }

    /// Gradient-orthogonality sub-pixel saddle refinement (as in cornerSubPix).
    private func refine(_ img: GrayImage, _ start: Point2, radius: Int, limit: Double) -> Point2? {
        var q = start
        for _ in 0..<6 {
            var g11 = 0.0, g12 = 0.0, g22 = 0.0, b1 = 0.0, b2 = 0.0
            let cx = Int(q.x.rounded()), cy = Int(q.y.rounded())
            let sig2 = Double(radius * radius) / 2
            for dy in -radius...radius { for dx in -radius...radius {
                let x = cx + dx, y = cy + dy
                guard x > 0, y > 0, x < img.width - 1, y < img.height - 1 else { continue }
                let gx = Double(img.at(x + 1, y) - img.at(x - 1, y)) * 0.5
                let gy = Double(img.at(x, y + 1) - img.at(x, y - 1)) * 0.5
                let wgt = exp(-Double(dx * dx + dy * dy) / (2 * sig2))
                let a = gx * gx * wgt, b = gx * gy * wgt, c = gy * gy * wgt
                g11 += a; g12 += b; g22 += c
                b1 += a * Double(x) + b * Double(y); b2 += b * Double(x) + c * Double(y)
            } }
            let det = g11 * g22 - g12 * g12
            guard det > 1e-6 * (g11 + g22) * (g11 + g22), det > 0 else { return nil }
            let nx = (g22 * b1 - g12 * b2) / det, ny = (g11 * b2 - g12 * b1) / det
            let moved = hypot(nx - q.x, ny - q.y)
            q = Point2(x: nx, y: ny)
            if hypot(q.x - start.x, q.y - start.y) > limit { return nil }
            if moved < 0.02 { break }
        }
        return q
    }

    /// Radial lens model: x_d = c + (x_u - c)(1 + k1 r^2 + k2 r^4), r^2 = |x_u - c|^2 / norm (norm = squared
    /// image half-diagonal). The centre c is fitted too: a real lens centre need not be the picture centre.
    /// `h` maps lattice (i, j) to undistorted image coordinates.
    struct LensFit {
        var k1: Double
        var k2 = 0.0
        var h: Homography
        var c: Point2
        var norm: Double
        func rho(_ p: Point2) -> Double { ((p.x - c.x) * (p.x - c.x) + (p.y - c.y) * (p.y - c.y)) / norm }
        func scale(_ p: Point2) -> Double { let r = rho(p); return 1 + k1 * r + k2 * r * r }
        /// Radial map is one-to-one at p: d/dr of r(1 + k1 r^2 + k2 r^4) = 1 + 3 k1 r^2 + 5 k2 r^4 stays positive.
        func monotonic(_ p: Point2) -> Bool { let r = rho(p); return 1 + 3 * k1 * r + 5 * k2 * r * r > 0.1 }
        func distort(_ p: Point2) -> Point2 {
            let s = scale(p)
            return Point2(x: c.x + (p.x - c.x) * s, y: c.y + (p.y - c.y) * s)
        }
        /// Inverse of `distort` by fixed-point iteration; nil unless it converges to a finite point.
        func undistort(_ p: Point2) -> Point2? {
            var q = p
            for _ in 0..<30 {
                let s = scale(q)
                guard s > 0.1 else { return nil }
                let n = Point2(x: c.x + (p.x - c.x) / s, y: c.y + (p.y - c.y) / s)
                let moved = hypot(n.x - q.x, n.y - q.y)
                q = n
                if moved < 1e-4 { break }
            }
            let back = distort(q)
            guard q.x.isFinite, q.y.isFinite, hypot(back.x - p.x, back.y - p.y) < 0.01 else { return nil }
            return q
        }
    }

    /// Best homography + one radial term (k1, k2 = 0) with free centre for the refined grid points (residuals
    /// in image pixels). k1 in [-0.6, 0.6], centre anywhere inside the picture: a 5x5 grid of centres, each
    /// with a 1-D search over k1, then a pattern search over (centre x, centre y, k1) from the best one.
    /// A second free term (k2) was tried and dropped: 3x slower and the grid cannot pin it down.
    /// Returns nil if no finite fit exists.
    static func radialFit(_ src: [Point2], _ dst: [Point2], width: Int, height: Int) -> LensFit? {
        let norm = Double(width * width + height * height) / 4
        let xmax = Double(width - 1), ymax = Double(height - 1)
        let kLo = -0.6, kHi = 0.6
        func evaluate(_ cx: Double, _ cy: Double, _ k1: Double) -> (Double, LensFit)? {
            guard cx >= 0, cx <= xmax, cy >= 0, cy <= ymax, k1 >= kLo, k1 <= kHi else { return nil }
            var model = LensFit(k1: k1, h: Homography(h: [1, 0, 0, 0, 1, 0, 0, 0, 1]), c: Point2(x: cx, y: cy), norm: norm)
            var und: [Point2] = []
            for d in dst {
                guard let u = model.undistort(d), model.monotonic(u) else { return nil }
                und.append(u)
            }
            guard let h = Homography.fit(src, und) else { return nil }
            model.h = h
            var ss = 0.0
            for (s, d) in zip(src, dst) {
                let p = model.distort(h.apply(s.x, s.y))
                ss += (p.x - d.x) * (p.x - d.x) + (p.y - d.y) * (p.y - d.y)
            }
            return ss.isFinite ? (ss, model) : nil
        }
        func searchK(_ cx: Double, _ cy: Double) -> (Double, Double)? {
            let steps = 24
            var bestK = 0.0, bestCost = Double.infinity
            for n in 0...steps {
                let k = kLo + (kHi - kLo) * Double(n) / Double(steps)
                if let (cost, _) = evaluate(cx, cy, k), cost < bestCost { bestCost = cost; bestK = k }
            }
            guard bestCost.isFinite else { return nil }
            let step = (kHi - kLo) / Double(steps)
            var a = max(kLo, bestK - step), b = min(kHi, bestK + step)
            let g = (sqrt(5.0) - 1) / 2
            for _ in 0..<30 {
                let x1 = b - g * (b - a), x2 = a + g * (b - a)
                let f1 = evaluate(cx, cy, x1)?.0 ?? .infinity, f2 = evaluate(cx, cy, x2)?.0 ?? .infinity
                if f1 < f2 { b = x2 } else { a = x1 }
            }
            let k = (a + b) / 2
            if let (cost, _) = evaluate(cx, cy, k), cost <= bestCost { return (cost, k) }
            return (bestCost, bestK)
        }
        var best: (cost: Double, x: Double, y: Double, k: Double)? = nil
        for fy in [0.0, 0.25, 0.5, 0.75, 1.0] {
            for fx in [0.0, 0.25, 0.5, 0.75, 1.0] {
                if let (cost, k) = searchK(fx * xmax, fy * ymax), best == nil || cost < best!.cost {
                    best = (cost, fx * xmax, fy * ymax, k)
                }
            }
        }
        guard var cur = best else { return nil }
        var step = (x: xmax / 8, y: ymax / 8, k: 0.025)
        var iterations = 0
        while step.x > 0.5 && iterations < 400 {
            iterations += 1
            var moved = false
            for (dx, dy, dk) in [(step.x, 0.0, 0.0), (-step.x, 0, 0), (0, step.y, 0), (0, -step.y, 0),
                                 (0, 0, step.k), (0, 0, -step.k)] {
                if let (cost, _) = evaluate(cur.x + dx, cur.y + dy, cur.k + dk), cost < cur.cost {
                    cur = (cost, cur.x + dx, cur.y + dy, cur.k + dk); moved = true
                }
            }
            if !moved { step = (step.x / 2, step.y / 2, step.k / 2) }
        }
        return evaluate(cur.x, cur.y, cur.k)?.1
    }

    /// Decision of the curved-edge check: nil = pass. Any non-finite or negative shift (no usable lens
    /// fit) rejects, so a NaN can never pass the comparison.
    static func curveVerdict(_ shift: Double, limit: Double) -> String? {
        guard shift.isFinite, shift >= 0 else { return "lens-fit-failed" }
        return shift > limit ? "board-edges-curved" : nil
    }

    /// Largest distance between the straight-fit outer corners `quad` (lattice positions `outerIJ`) and the
    /// same corners under `lens`, as a share of the quad's mean side. NaN when any value is not finite.
    static func curveShift(_ lens: LensFit, outerIJ: [(Int, Int)], quad: [Point2]) -> Double {
        let side = (0..<4).map { hypot(quad[$0].x - quad[($0 + 1) % 4].x, quad[$0].y - quad[($0 + 1) % 4].y) }
            .reduce(0, +) / 4
        var worst = 0.0
        for (ij, q) in zip(outerIJ, quad) {
            let u = lens.h.apply(Double(ij.0), Double(ij.1))
            guard lens.monotonic(u) else { return .nan }
            let p = lens.distort(u)
            let d = hypot(p.x - q.x, p.y - q.y)
            guard d.isFinite else { return .nan }
            worst = max(worst, d)
        }
        guard side.isFinite, side > 0 else { return .nan }
        return worst / side
    }

    /// Cell-level checker test for the board whose internal corners are lattice a..a+6, b..b+6.
    private func placementScore(_ img: GrayImage, _ h: Homography, _ a: Int, _ b: Int)
        -> (agree: Double, ring: Double, contrast: Double) {
        // Board cells: sample near the four cell corners (pieces sit in the middle).
        // Ring cells: dense 5x5 grid, so thin periodic UI (text lines) averages out.
        let inner: [Double] = [0.12, 0.25, 0.75, 0.88]
        let dense: [Double] = [0.1, 0.3, 0.5, 0.7, 0.9]
        func cellValue(_ k: Int, _ l: Int) -> Double? {
            let grid = (k < 0 || k > 7 || l < 0 || l > 7) ? dense : inner
            var s = 0.0
            for fx in grid { for fy in grid {
                let p = h.apply(Double(a - 1 + k) + fx, Double(b - 1 + l) + fy)
                guard p.x >= 0, p.y >= 0, p.x <= Double(img.width - 1), p.y <= Double(img.height - 1) else { return nil }
                s += Double(img.sample(Float(p.x), Float(p.y)))
            } }
            return s / Double(grid.count * grid.count)
        }
        var v = [[Double?]](repeating: [Double?](repeating: nil, count: 10), count: 10)
        for k in -1...8 { for l in -1...8 { v[k + 1][l + 1] = cellValue(k, l) } }
        var signed = 0.0, n = 0.0
        for k in 0..<8 { for l in 0..<8 { if let x = v[k + 1][l + 1] { signed += ((k + l) % 2 == 0 ? 1 : -1) * x; n += 1 } } }
        guard n > 0 else { return (0, 1, 0) }
        let contrast = signed / n * 2          // light minus dark, signed
        let s0: Double = contrast >= 0 ? 1 : -1
        var agree = 0.0, total = 0.0
        for k in 0..<8 { for l in 0..<8 {
            guard let x = v[k + 1][l + 1] else { continue }
            let nb = [(1, 0), (-1, 0), (0, 1), (0, -1)].compactMap { d -> Double? in
                let kk = k + d.0, ll = l + d.1
                guard kk >= 0, kk < 8, ll >= 0, ll < 8 else { return nil }
                return v[kk + 1][ll + 1]
            }
            guard !nb.isEmpty else { continue }
            let diff = x - nb.reduce(0, +) / Double(nb.count)
            total += 1
            if s0 * ((k + l) % 2 == 0 ? 1 : -1) * diff > 0 { agree += 1 }
        } }
        // Ring: does the alternation continue one square beyond any side?
        var ringMax = 0.0
        let sides: [[(Int, Int)]] = [(0..<8).map { ($0, -1) }, (0..<8).map { ($0, 8) },
                                      (0..<8).map { (-1, $0) }, (0..<8).map { (8, $0) }]
        for side in sides {
            // Alternating sum along the ring row: ~contrast/2 if the checker continues, ~0 if uniform.
            let cells = side.compactMap { kl -> (Double, Double)? in
                guard let x = v[kl.0 + 1][kl.1 + 1] else { return nil }
                return (x, (((kl.0 + kl.1) % 2 + 2) % 2 == 0 ? 1 : -1))
            }
            guard cells.count >= 4 else { continue }
            let mean = cells.map(\.0).reduce(0, +) / Double(cells.count)
            let alt = cells.map { s0 * $0.1 * ($0.0 - mean) }.reduce(0, +) / Double(cells.count)
            ringMax = max(ringMax, alt / max(1e-6, abs(contrast) / 2))
        }
        return (total > 0 ? agree / total : 0, max(0, ringMax), abs(contrast))
    }

    private func ordered(_ q: [Point2]) -> [Point2] {
        var pts = q
        var area = 0.0
        for i in 0..<4 { let a = pts[i], b = pts[(i + 1) % 4]; area += a.x * b.y - b.x * a.y }
        if area < 0 { pts = [pts[0], pts[3], pts[2], pts[1]] }   // clockwise with y pointing down
        let start = pts.indices.min { pts[$0].x + pts[$0].y < pts[$1].x + pts[$1].y }!
        return (0..<4).map { pts[(start + $0) % 4] }
    }
}
