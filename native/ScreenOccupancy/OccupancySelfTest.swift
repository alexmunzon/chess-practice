import Foundation

/// Unit checks of the pieces most likely to be ported wrong. Expected values were produced by the frozen
/// Python code (scripts/recognition/occupancy_classifier_v3.py, screen_pipeline.py) on the same synthetic inputs.
public enum OccupancySelfTest {
    public static func run() -> (Bool, [String]) {
        var lines: [String] = []
        var allOK = true
        func check(_ name: String, _ ok: Bool, _ info: String = "") {
            allOK = allOK && ok
            lines.append("\(ok ? "PASS" : "FAIL") \(name)\(info.isEmpty ? "" : ": " + info)")
        }
        func near(_ a: Double, _ b: Double, _ tol: Double = 1e-9) -> Bool { abs(a - b) <= tol }
        let T = OccupancyV3.T
        let ref = SIMD3<Double>(180, 170, 150), contrast = 60.0

        // 1. Homography direction (panel -> image) and corner mapping.
        let corners = [Point2(x: 100, y: 50), Point2(x: 900, y: 80), Point2(x: 880, y: 700), Point2(x: 90, y: 690)]
        if let h = PanelRectifier.panelToImage(corners) {
            let a = h.apply(64, 64), c = h.apply(320, 320)
            check("homography panel->image", near(a.x, 100, 1e-6) && near(a.y, 50, 1e-6)
                  && near(c.x, 498.67704280156573, 1e-6) && near(c.y, 382.23086900135354, 1e-6), "\(c.x),\(c.y)")
        } else { check("homography panel->image", false, "fit failed") }

        // 2. Pixel-centre convention: identity quad, image R = x mod 256, G = y mod 256.
        var g = [UInt8](repeating: 0, count: 700 * 700 * 3)
        for y in 0..<700 { for x in 0..<700 { g[(y * 700 + x) * 3] = UInt8(x % 256); g[(y * 700 + x) * 3 + 1] = UInt8(y % 256) } }
        let quad = [Point2(x: 63.5, y: 63.5), Point2(x: 575.5, y: 63.5), Point2(x: 575.5, y: 575.5), Point2(x: 63.5, y: 575.5)]
        if let p = PanelRectifier.rectify(OccupancyRGBImage(width: 700, height: 700, pixels: g), corners: quad) {
            func px(_ y: Int, _ x: Int) -> [UInt8] { (0..<3).map { p.pixels[(y * 640 + x) * 3 + $0] } }
            check("rectify pixel centres", px(64, 64) == [64, 64, 0] && px(64, 300) == [44, 64, 0]
                  && px(575, 575) == [63, 63, 0] && px(10, 10) == [128, 128, 128], "\(px(64, 64)) \(px(64, 300)) \(px(575, 575))")
        } else { check("rectify pixel centres", false, "nil") }

        // 3. Bilinear sampling clamps at borders (x beyond the right edge -> width - 1.001; y < 0 -> 0).
        let small = OccupancyRGBImage(width: 4, height: 3, pixels: (0..<12).flatMap { [UInt8($0), UInt8($0), UInt8($0)] })
        // quad mapping panel (64..576) onto points outside the image: sample the panel pixel whose centre maps to (5, 0.5)
        let far = [Point2(x: 5, y: 0.5), Point2(x: 6, y: 0.5), Point2(x: 6, y: 1.5), Point2(x: 5, y: 1.5)]
        if let p = PanelRectifier.rectify(small, corners: far) {
            // panel pixel (64,64) samples near (5.001, 0.501) -> clamped x = 2.999: 0.501 of the way to row 1 ->
            // Python _bilinear(img, 5.0, 0.5) = 4.999 (value + 0.5, truncated = 5)
            check("bilinear border clamp", p.pixels[(64 * 640 + 64) * 3] == 5, "\(p.pixels[(64 * 640 + 64) * 3])")
        } else { check("bilinear border clamp", false) }

        // 4. Square order and rotation mapping (np.rot90 semantics from screen_pipeline.py).
        let idx = Array(0..<64)
        let s1 = OccupancyV3.screenFromA8(idx, 1), b1 = OccupancyV3.a8FromScreen(idx, 1)
        let s3 = OccupancyV3.screenFromA8(idx, 3)
        var roundTrip = true
        for r in 0..<4 { roundTrip = roundTrip && OccupancyV3.a8FromScreen(OccupancyV3.screenFromA8(idx, r), r) == idx }
        check("square order + rotation", OccupancyV3.squares[0] == "a8" && OccupancyV3.squares[7] == "h8"
              && OccupancyV3.squares[63] == "h1" && OccupancyV3.dark[0] == 0 && OccupancyV3.dark[56] == 1
              && Array(s1.prefix(9)) == [56, 48, 40, 32, 24, 16, 8, 0, 57] && Array(b1.prefix(9)) == [7, 15, 23, 31, 39, 47, 55, 63, 6]
              && Array(s3.prefix(3)) == [7, 15, 23] && roundTrip)

        // 5. Pillow GaussianBlur(1.0), bit exact on a 9x7 pattern.
        var pat = [UInt8](repeating: 0, count: 9 * 7 * 3)
        for y in 0..<7 { for x in 7..<9 { for c in 0..<3 { pat[(y * 9 + x) * 3 + c] = 200 } } }
        pat[(3 * 9 + 4) * 3] = 255; pat[(3 * 9 + 4) * 3 + 1] = 128; pat[(3 * 9 + 4) * 3 + 2] = 9
        let bl = PillowBlur.gaussian(OccupancyRGBImage(width: 9, height: 7, pixels: pat), radius: 1.0)
        let expR: [UInt8] = [0, 0, 0, 0, 1, 12, 59, 141, 187, 0, 0, 0, 3, 7, 15, 59, 141, 187, 0, 0, 3, 14, 25, 26, 62, 141, 187, 0, 1, 6, 24, 43, 36, 65, 142, 187, 0, 0, 3, 14, 25, 26, 62, 141, 187, 0, 0, 0, 3, 7, 15, 59, 141, 187, 0, 0, 0, 0, 1, 12, 59, 141, 187]
        let expG: [UInt8] = [0, 0, 0, 0, 1, 12, 59, 141, 187, 0, 0, 0, 2, 4, 14, 59, 141, 187, 0, 0, 1, 7, 13, 19, 60, 141, 187, 0, 0, 3, 12, 22, 24, 62, 141, 187, 0, 0, 1, 7, 13, 19, 60, 141, 187, 0, 0, 0, 2, 4, 14, 59, 141, 187, 0, 0, 0, 0, 1, 12, 59, 141, 187]
        let gotR = (0..<63).map { bl.pixels[$0 * 3] }, gotG = (0..<63).map { bl.pixels[$0 * 3 + 1] }
        check("Pillow GaussianBlur(1.0) bit exact", gotR == expR && gotG == expG, "radius \(PillowBlur.extendedBoxRadius(1.0)) weights \(PillowBlur.weights(PillowBlur.extendedBoxRadius(1.0)))")

        // 5b. Board-region blur equals the whole-panel blur inside the board (random panel).
        var rnd = [UInt8](repeating: 0, count: 640 * 640 * 3)
        var seed: UInt64 = 12345
        for i in 0..<rnd.count { seed = seed &* 6364136223846793005 &+ 1442695040888963407; rnd[i] = UInt8(truncatingIfNeeded: seed >> 56) }
        let rp = OccupancyRGBImage(width: 640, height: 640, pixels: rnd)
        let full = PillowBlur.gaussian(rp, radius: 1.0), part = OccupancyV3.prepare(rp).smooth
        var same = true
        for y in 64..<576 { for x in 64..<576 { for c in 0..<3 where full.pixels[(y * 640 + x) * 3 + c] != part.pixels[(y * 640 + x) * 3 + c] { same = false } } }
        check("board-region blur == whole-panel blur on the board", same)
        let gen = PillowBlur.gaussian(rp, radius: 1.0, region: (0, 0, 640, 640), generic: true)
        check("radius-0 fast blur == generic Pillow box-line blur", gen.pixels == full.pixels)

        // 6. Local lighting fit on a synthetic striped tile (brightness factor +10 % / -5 % in 8-row bands).
        var stripe = [SIMD3<Double>](repeating: ref, count: T * T)
        for r in 0..<T { let k = (r / 8) % 2 == 0 ? 0.10 : -0.05; for c in 0..<T { stripe[r * T + c] = ref * (1 + k) } }
        let (off, loc) = OccupancyV3.localCorrection(stripe, ref, contrast)
        let ms = OccupancyV3.measure(stripe, ref, contrast)
        check("lighting fit on striped tile", near(loc.shift, 0.28451666666666664, 1e-9) && near(loc.step, 0.06096785714286178, 1e-9)
              && near(loc.side, 0) && loc.unexplained < 1e-9 && ms.fg == 0 && ms.edge == 0 && ms.border == 0
              && near(off[30 * T + 30].x, -1.2857142857142687, 1e-9) && near(off[30 * T + 30].z, -1.0714285714285643, 1e-9),
              "shift \(loc.shift) step \(loc.step)")

        // 7. Edge cue and fill on a synthetic outline (2 px dark rectangle outline).
        var outline = [SIMD3<Double>](repeating: ref, count: T * T)
        let dk = SIMD3<Double>(40, 40, 40)
        for r in 15..<50 { for c in [20, 21, 42, 43] { outline[r * T + c] = dk } }
        for c in 20..<44 { for r in [15, 16, 48, 49] { outline[r * T + c] = dk } }
        let mo = OccupancyV3.measure(outline, ref, contrast)
        check("edge cue on synthetic outline", near(mo.fg, 0.11) && near(mo.edge, 0.132) && mo.border == 0
              && mo.fill?.pixels.count == 140 && mo.fill?.weights.reduce(0, +) == 296, "fg \(mo.fg) edge \(mo.edge) fill \(mo.fill?.pixels.count ?? -1)")

        // 8. Deep core of a filled disc.
        var disc = [SIMD3<Double>](repeating: ref, count: T * T)
        for y in 0..<T { for x in 0..<T where (y - 30) * (y - 30) + (x - 32) * (x - 32) <= 196 { disc[y * T + x] = SIMD3(240, 240, 240) } }
        let md = OccupancyV3.measure(disc, ref, contrast)
        check("deep core weights (disc)", near(md.fg, 0.3065) && near(md.edge, 0.056) && md.fill?.pixels.count == 113
              && md.fill?.weights.reduce(0, +) == 204 && md.fill?.weights.max() == 4)

        // 9. Clipping rule: clipped piece fill allowed when calm and ring unclipped; not under strong lighting or on the ring.
        var raw = [UInt8](repeating: 120, count: 640 * 640 * 3)
        func setTile(_ rows: Range<Int>, _ cols: Range<Int>) { for r in rows { for c in cols { for ch in 0..<3 { raw[((64 + r) * 640 + 64 + c) * 3 + ch] = 255 } } } }
        setTile(20..<50, 20..<44)
        var img = OccupancyRGBImage(width: 640, height: 640, pixels: raw)
        var calm = OccupancyV3.Local(); calm.shift = 0.1
        var strong = OccupancyV3.Local(); strong.shift = 0.2
        let s_a = OccupancyV3.saturation(img, 0, calm), s_b = OccupancyV3.saturation(img, 0, strong)
        setTile(3..<7, 3..<61)
        img = OccupancyRGBImage(width: 640, height: 640, pixels: raw)
        let s_c = OccupancyV3.saturation(img, 0, calm)
        check("clipping rule", s_a == (0.17578125, false) && s_b == (0.17578125, true) && s_c == (0.232421875, true))

        // 10. Policy constants: 39 entries, spot values (conformance.py compares all 39 with Python).
        let pol = Dictionary(uniqueKeysWithValues: OccupancyV3.policy().map { ($0.0, "\($0.1)") })
        check("policy constants", pol.count == 39 && pol["FG_DISTANCE"] == "40.0" && pol["COLOUR_MAX_ROW"] == "46"
              && pol["CAL_SHARPNESS_MIN"] == "0.05"
              && pol["CAL_VOTE_MEAN_MIN"] == "0.85" && pol["GAIN_RANGE"] == "[0.33, 3.0]" && pol["FILL_EDGE_GUARD"] == "-1")

        // 10b. v3.1: a stored sharpness reference of 0, negative, NaN, infinite or missing (JSON) -> all 64 unknown.
        let base = OccupancyV3.Calibration(emptyRef: [SIMD3(231, 216, 184), SIMD3(103, 132, 101)], contrast: 92,
                                           boundarySharpness: 0.8, whiteRef: SIMD3(248, 245, 231), blackRef: SIMD3(35, 38, 43))
        var refusals: [String] = []
        for v in [0.0, -0.5, Double.nan, Double.infinity] {
            var c = base; c.boundarySharpness = v
            let cells = OccupancyV3.classify(OccupancyV3.prepare(rp), calibration: c)
            if cells.count == 64 && cells.allSatisfy({ $0.label == "unknown" && $0.reasons == ["calibration-sharpness-invalid"] }) {
                refusals.append("\(v)")
            }
        }
        let fromJSON = OccupancyJSON.calibration(from: ["emptyRef": [[231, 216, 184], [103, 132, 101]], "contrast": 92,
                                                         "fillRef": ["white": [248, 245, 231], "black": [35, 38, 43]]])
        let boolJSON = OccupancyJSON.calibration(from: ["emptyRef": [[231, 216, 184], [103, 132, 101]], "contrast": 92,
                                                         "boundarySharpness": true,
                                                         "fillRef": ["white": [248, 245, 231], "black": [35, 38, 43]]])
        let missingOK = fromJSON.map { c in OccupancyV3.classify(OccupancyV3.prepare(rp), calibration: c)
            .allSatisfy { $0.label == "unknown" && $0.reasons == ["calibration-sharpness-invalid"] } } ?? false
        check("invalid sharpness reference abstains everywhere", refusals.count == 4 && missingOK
              && boolJSON.map { $0.boundarySharpness.isNaN } == true
              && OccupancyV3.sharpnessReferenceOK(0.05) && !OccupancyV3.sharpnessReferenceOK(0.0499)
              && OccupancyV3.sharpnessReferenceOK(0.8), "refused \(refusals), missing key refused \(missingOK)")

        // 11. numpy median conventions.
        check("median even/odd", OccupancyV3.median([3, 1, 2]) == 2 && OccupancyV3.median([4, 1, 3, 2]) == 2.5
              && OccupancyV3.medianByte([0, 2, 2] + [Int](repeating: 0, count: 253), 4) == 1.5)
        lines.append(allOK ? "self-test: all passed" : "self-test: FAILED")
        return (allOK, lines)
    }
}
