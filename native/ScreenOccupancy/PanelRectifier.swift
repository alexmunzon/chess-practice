import Foundation

/// Port of screen_pipeline.py rectify(): warp the quad `corners` onto panel pixels 64..576 of a
/// 640x640 panel (outside = grey 128). Corner i goes to panel corner i of (64,64), (576,64),
/// (576,576), (64,576), i.e. corner 0 = panel top-left. Image coordinates have pixel centres at integers;
/// panel coordinates have pixel EDGES at integers (panel pixel u is sampled at u + (s + 0.5) / k).
/// Uses Homography.swift from native/ScreenBoardVision (compiled alongside, not edited).
public enum PanelRectifier {
    public static let panel = 640
    public static let boardLo = 64
    public static let boardHi = 576
    public static let supersampleMax = 3

    static func boardSide(_ c: [Point2]) -> Double {
        var s = 0.0
        for k in 0..<4 { s += hypot(c[k].x - c[(k + 1) % 4].x, c[k].y - c[(k + 1) % 4].y) }
        return s / 4
    }

    /// Supersampling factor k (k x k samples per panel pixel), as Python.
    static func supersample(_ corners: [Point2]) -> Int {
        let n = Double(boardHi - boardLo)
        return Int(min(Double(supersampleMax), max(1, (boardSide(corners) / n - 0.05).rounded(.up))))
    }

    /// Panel -> image homography (Python: homography(panel points, corners)).
    static func panelToImage(_ corners: [Point2]) -> Homography? {
        let lo = Double(boardLo), hi = Double(boardHi)
        let src = [Point2(x: lo, y: lo), Point2(x: hi, y: lo), Point2(x: hi, y: hi), Point2(x: lo, y: hi)]
        return Homography.fit(src, corners)
    }

    static func rectify(_ image: OccupancyRGBImage, corners: [Point2]) -> OccupancyRGBImage? {
        guard corners.count == 4, corners.allSatisfy({ $0.x.isFinite && $0.y.isFinite }),
              let hm = panelToImage(corners) else { return nil }
        let h = hm.h
        let (h0, h1, h2, h3, h4, h5, h6, h7, h8) = (h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7], h[8])
        let k = supersample(corners)
        let n = boardHi - boardLo
        var acc = [Float](repeating: 0, count: n * n * 3)
        let wid = image.width, hgt = image.height
        let xmax = Double(wid) - 1.001, ymax = Double(hgt) - 1.001
        let offs = (0..<k).map { (Double($0) + 0.5) / Double(k) }
        // Per panel pixel, sub-samples are added in Python's order (oy outer, ox inner), so the float32
        // accumulator sees exactly the same sequence of additions; only the loop nesting differs.
        image.pixels.withUnsafeBufferPointer { img in
            acc.withUnsafeMutableBufferPointer { a in
                for j in 0..<n {
                    for i in 0..<n {
                        var a0: Float = 0, a1: Float = 0, a2: Float = 0
                        for oy in offs {
                            let v = Double(j &+ boardLo) + oy
                            for ox in offs {
                                let u = Double(i &+ boardLo) + ox
                                let den = h6 * u + h7 * v + h8
                                let x = (h0 * u + h1 * v + h2) / den
                                let y = (h3 * u + h4 * v + h5) / den
                                let xc = min(max(x, 0), xmax), yc = min(max(y, 0), ymax)  // np.clip, then floor
                                let x0 = Int(xc.rounded(.down)), y0 = Int(yc.rounded(.down))
                                let fx = xc - Double(x0), fy = yc - Double(y0)
                                let p00 = (y0 &* wid &+ x0) &* 3, p01 = p00 &+ 3, p10 = p00 &+ wid &* 3, p11 = p10 &+ 3
                                // Same association as numpy: ((img * (1-fx)) * (1-fy)) + ..., float32 acc += float64
                                let w00 = 1 - fx, w01 = fx, w10 = 1 - fx, w11 = fx, wy0 = 1 - fy, wy1 = fy
                                @inline(__always) func s(_ c: Int) -> Double {
                                    Double(img[p00 &+ c]) * w00 * wy0 + Double(img[p01 &+ c]) * w01 * wy0
                                        + Double(img[p10 &+ c]) * w10 * wy1 + Double(img[p11 &+ c]) * w11 * wy1
                                }
                                a0 = Float(Double(a0) + s(0)); a1 = Float(Double(a1) + s(1)); a2 = Float(Double(a2) + s(2))
                            }
                        }
                        let o = (j &* n &+ i) &* 3
                        a[o] = a0; a[o &+ 1] = a1; a[o &+ 2] = a2
                    }
                }
            }
        }
        var out = [UInt8](repeating: 128, count: panel * panel * 3)
        let kk = Float(k * k)
        for j in 0..<n {
            for i in 0..<n {
                for c in 0..<3 {
                    let v = acc[(j * n + i) * 3 + c] / kk + 0.5  // float32, as numpy
                    out[((j + boardLo) * panel + i + boardLo) * 3 + c] = UInt8(min(max(v, 0), 255))  // truncation
                }
            }
        }
        return OccupancyRGBImage(width: panel, height: panel, pixels: out)
    }
}
