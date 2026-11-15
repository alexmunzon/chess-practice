import Foundation

struct Point2 { var x: Double; var y: Double }

/// 3x3 projective map, row-major, h[8] normalized to 1 when possible.
struct Homography {
    var h: [Double]

    func apply(_ x: Double, _ y: Double) -> Point2 {
        let w = h[6] * x + h[7] * y + h[8]
        return Point2(x: (h[0] * x + h[1] * y + h[2]) / w, y: (h[3] * x + h[4] * y + h[5]) / w)
    }

    /// Least-squares DLT with Hartley normalization (needs >= 4 points, not all collinear).
    static func fit(_ src: [Point2], _ dst: [Point2]) -> Homography? {
        let n = src.count
        guard n >= 4, dst.count == n else { return nil }
        func normalizer(_ p: [Point2]) -> (Double, Double, Double) {
            let mx = p.map(\.x).reduce(0, +) / Double(p.count)
            let my = p.map(\.y).reduce(0, +) / Double(p.count)
            let d = p.map { hypot($0.x - mx, $0.y - my) }.reduce(0, +) / Double(p.count)
            return (mx, my, d > 1e-12 ? sqrt(2) / d : 1)
        }
        let (sx, sy, ss) = normalizer(src), (dx, dy, ds) = normalizer(dst)
        // Normal equations for 8 unknowns with h33 = 1 in normalized coordinates.
        var ata = [Double](repeating: 0, count: 64)
        var atb = [Double](repeating: 0, count: 8)
        for k in 0..<n {
            let x = (src[k].x - sx) * ss, y = (src[k].y - sy) * ss
            let u = (dst[k].x - dx) * ds, v = (dst[k].y - dy) * ds
            let r1: [Double] = [x, y, 1, 0, 0, 0, -u * x, -u * y]
            let r2: [Double] = [0, 0, 0, x, y, 1, -v * x, -v * y]
            for i in 0..<8 {
                atb[i] += r1[i] * u + r2[i] * v
                for j in 0..<8 { ata[i * 8 + j] += r1[i] * r1[j] + r2[i] * r2[j] }
            }
        }
        guard let sol = solve(ata, atb, 8) else { return nil }
        let hn = sol + [1]
        // H = Tdst^-1 * Hn * Tsrc
        let tsrc: [Double] = [ss, 0, -ss * sx, 0, ss, -ss * sy, 0, 0, 1]
        let tdstInv: [Double] = [1 / ds, 0, dx, 0, 1 / ds, dy, 0, 0, 1]
        let m = mul(tdstInv, mul(hn, tsrc))
        guard abs(m[8]) > 1e-15 else { return nil }
        return Homography(h: m.map { $0 / m[8] })
    }

    static func mul(_ a: [Double], _ b: [Double]) -> [Double] {
        var c = [Double](repeating: 0, count: 9)
        for i in 0..<3 { for j in 0..<3 { for k in 0..<3 { c[i * 3 + j] += a[i * 3 + k] * b[k * 3 + j] } } }
        return c
    }

    static func solve(_ a: [Double], _ b: [Double], _ n: Int) -> [Double]? {
        var m = a, r = b
        for col in 0..<n {
            var piv = col
            for row in col + 1..<n where abs(m[row * n + col]) > abs(m[piv * n + col]) { piv = row }
            guard abs(m[piv * n + col]) > 1e-12 else { return nil }
            if piv != col {
                for j in 0..<n { m.swapAt(col * n + j, piv * n + j) }
                r.swapAt(col, piv)
            }
            for row in 0..<n where row != col {
                let f = m[row * n + col] / m[col * n + col]
                if f == 0 { continue }
                for j in col..<n { m[row * n + j] -= f * m[col * n + j] }
                r[row] -= f * r[col]
            }
        }
        return (0..<n).map { r[$0] / m[$0 * n + $0] }
    }
}
