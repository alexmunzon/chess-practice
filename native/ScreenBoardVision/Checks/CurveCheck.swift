import Foundation

// Checks for the curved-edge self-check (no pictures needed). Build and run from native/ScreenBoardVision:
//   swiftc -O -parse-as-library GrayImage.swift Homography.swift ScreenBoardDetector.swift \
//       Checks/CurveCheck.swift -o curve-check && ./curve-check
// 1. Non-finite values reject.  2. Synthetic 8x8 grids under radial lens distortion (k1, k2) with the lens centre
// moved 0-350 px from the picture centre in 8 directions, barrel and pincushion: no grid with a one-term
// lens (k2 = 0) whose straight-fit corners are more than 5% of the side off may pass the check. Profiles
// with a k2 term are outside the fitted model and only reported. Exit code 1 on any failure.

@main
struct CurveCheck {
    static func main() {
        var failures = 0
        func expect(_ ok: Bool, _ what: String) {
            print((ok ? "PASS " : "FAIL ") + what)
            if !ok { failures += 1 }
        }
        let limit = DetectorParameters().maxCurveShiftFraction

        // 1. Non-finite handling.
        for v in [Double.nan, .infinity, -.infinity, -1.0] {
            expect(ScreenBoardDetector.curveVerdict(v, limit: limit) == "lens-fit-failed", "verdict(\(v)) rejects")
        }
        expect(ScreenBoardDetector.curveVerdict(0.01, limit: limit) == nil, "verdict(1%) passes")
        expect(ScreenBoardDetector.curveVerdict(0.03, limit: limit) == "board-edges-curved", "verdict(3%) rejects")
        let W = 1920, H = 1080
        let grid = (0...6).flatMap { j in (0...6).map { i in Point2(x: Double(i), y: Double(j)) } }
        let plain = grid.map { Point2(x: 700 + 90 * $0.x, y: 250 + 90 * $0.y) }
        var withNaN = plain; withNaN[10] = Point2(x: .nan, y: 3)
        expect(ScreenBoardDetector.radialFit(grid, withNaN, width: W, height: H) == nil, "radialFit with a NaN point gives no fit")
        if let lens = ScreenBoardDetector.radialFit(grid, plain, width: W, height: H) {
            let nanQuad = [Point2(x: .nan, y: 0), Point2(x: 1, y: 0), Point2(x: 1, y: 1), Point2(x: 0, y: 1)]
            let s = ScreenBoardDetector.curveShift(lens, outerIJ: [(-1, -1), (7, -1), (7, 7), (-1, 7)], quad: nanQuad)
            expect(!s.isFinite && ScreenBoardDetector.curveVerdict(s, limit: limit) != nil, "NaN corner gives a rejecting shift")
        } else { expect(false, "radialFit on a flat grid") }

        // 2. Synthetic sweep. Board: projective quad of ~720 px, placed centred or off to the side.
        let norm = Double(W * W + H * H) / 4
        let c0 = Point2(x: Double(W - 1) / 2, y: Double(H - 1) / 2)
        let boards: [[Point2]] = [  // outer corners TL, TR, BR, BL of the undistorted board
            [Point2(x: 600, y: 160), Point2(x: 1330, y: 190), Point2(x: 1300, y: 900), Point2(x: 630, y: 930)],
            [Point2(x: 150, y: 120), Point2(x: 820, y: 100), Point2(x: 850, y: 780), Point2(x: 120, y: 760)],
            [Point2(x: 1150, y: 300), Point2(x: 1780, y: 330), Point2(x: 1760, y: 990), Point2(x: 1170, y: 960)],
        ]
        let offsets = stride(from: 0.0, through: 350.0, by: 50.0)
        let dirs = (0..<8).map { Double($0) * .pi / 4 }
        // (k1, k2): barrel, pincushion, edge-heavy (k2 only) and moustache (opposite signs).
        let ks: [(Double, Double)] = [(-0.45, 0), (-0.35, 0), (-0.25, 0), (-0.15, 0), (0.15, 0), (0.3, 0), (0.45, 0),
                                      (0, -0.25), (0, -0.4), (0.15, -0.35), (-0.3, 0.2)]
        var cases = 0, missed = 0, rejected = 0, unsafe = 0, fitFailed = 0, unsafe1 = 0, missed1 = 0
        var rows: [String: (n: Int, unsafe: Int, missed: Int, ratioMin: Double)] = [:]
        for (bi, b) in boards.enumerated() {
            guard let hb = Homography.fit([Point2(x: -1, y: -1), Point2(x: 7, y: -1), Point2(x: 7, y: 7), Point2(x: -1, y: 7)], b)
            else { continue }
            for off in offsets { for (di, a) in dirs.enumerated() where off > 0 || di == 0 { for k in ks {
                let c = Point2(x: c0.x + off * cos(a), y: c0.y + off * sin(a))
                let truth = ScreenBoardDetector.LensFit(k1: k.0, k2: k.1, h: hb, c: c, norm: norm)
                func D(_ i: Double, _ j: Double) -> Point2 { truth.distort(hb.apply(i, j)) }
                let outer = [(-1, -1), (7, -1), (7, 7), (-1, 7)]
                let trueOuter = outer.map { D(Double($0.0), Double($0.1)) }
                guard trueOuter.allSatisfy({ $0.x > 2 && $0.y > 2 && $0.x < Double(W - 3) && $0.y < Double(H - 3) }),
                      outer.allSatisfy({ truth.monotonic(hb.apply(Double($0.0), Double($0.1))) }) else { continue }
                // Measured grid: distorted inner corners plus a fixed +-0.15 px pattern (sub-pixel refinement noise).
                let dst = grid.enumerated().map { n, g -> Point2 in
                    let p = D(g.x, g.y)
                    return Point2(x: p.x + 0.15 * (n % 3 == 0 ? 1 : -1), y: p.y + 0.15 * (n % 5 < 2 ? 1 : -1))
                }
                guard let h0 = Homography.fit(grid, dst) else { continue }
                let quad = outer.map { h0.apply(Double($0.0), Double($0.1)) }
                let side = (0..<4).map { hypot(quad[$0].x - quad[($0 + 1) % 4].x, quad[$0].y - quad[($0 + 1) % 4].y) }.reduce(0, +) / 4
                let err = zip(quad, trueOuter).map { hypot($0.x - $1.x, $0.y - $1.y) }.max()! / side
                cases += 1
                var shift = Double.nan
                if let lens = ScreenBoardDetector.radialFit(grid, dst, width: W, height: H) {
                    shift = ScreenBoardDetector.curveShift(lens, outerIJ: outer, quad: quad)
                } else { fitFailed += 1 }
                let pass = ScreenBoardDetector.curveVerdict(shift, limit: limit) == nil
                if !pass { rejected += 1 }
                if err > 0.05, k.1 == 0 { unsafe1 += 1; if pass { missed1 += 1 } }
                if err > 0.05 { unsafe += 1; if pass { missed += 1
                    print(String(format: "  MISSED board %d offset %.0f dir %d k1 %.2f k2 %.2f: error %.2f%%, shift %.2f%%", bi, off, di, k.0, k.1, 100 * err, 100 * shift)) } }
                for key in [String(format: "offset %3.0f px", off), String(format: "k1 %+.2f k2 %+.2f", k.0, k.1)] {
                var r = rows[key] ?? (0, 0, 0, .infinity)
                r.n += 1
                if err > 0.05 {
                    r.unsafe += 1
                    if pass { r.missed += 1 }
                }
                if err > 0.01, shift.isFinite { r.ratioMin = min(r.ratioMin, shift / err) }
                rows[key] = r
                }
            } } }
        }
        for key in rows.keys.sorted() {
            let r = rows[key]!
            print(String(format: "%@: %d grids, %d with corners >5%% off, %d of them passed the check, lowest shift/error (error >1%%) %.2f",
                         key, r.n, r.unsafe, r.missed, r.ratioMin))
        }
        print("sweep: \(cases) grids, \(unsafe) with straight-fit corners >5% off, \(missed) of those passed, \(rejected) rejected in total, \(fitFailed) without a lens fit")
        print("model class (one radial term k1, any centre): \(unsafe1) grids with corners >5% off, \(missed1) passed")
        print("outside the model (k2 profiles, informational): \(unsafe - unsafe1) grids with corners >5% off, \(missed - missed1) passed")
        expect(unsafe1 > 0 && missed1 == 0, "no one-term-lens grid with corners >5% off passes the curved-edge check")
        print(failures == 0 ? "ALL CHECKS PASSED" : "\(failures) CHECK(S) FAILED")
        exit(failures == 0 ? 0 : 1)
    }
}
