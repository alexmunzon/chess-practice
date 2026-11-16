import Foundation

/// Bit-exact port of Pillow's ImageFilter.GaussianBlur(radius) for 8-bit RGB images: an "extended box"
/// approximation (Gwosdek et al.) with 3 passes horizontally, then 3 passes vertically, each pass on
/// 8-bit values with 24-bit fixed-point weights and edge replication (Pillow BoxBlur.c).
public enum PillowBlur {
    /// Pillow `_gaussian_blur_radius(radius, passes)`, in C float/double precision as compiled there.
    public static func extendedBoxRadius(_ radius: Float, passes: Int = 3) -> Float {
        let sigma2: Float = radius * radius / Float(passes)
        let L = Float((12.0 * Double(sigma2) + 1.0).squareRoot())
        let l = Float(((Double(L) - 1.0) / 2.0).rounded(.down))
        var a: Float = (2 * l + 1) * (l * (l + 1) - 3 * sigma2)
        a /= 6 * (sigma2 - (l + 1) * (l + 1))
        return l + a
    }

    /// Fixed-point weights (ww for the integer box, fw for each fractional end pixel), Pillow ImagingHorizontalBoxBlur.
    public static func weights(_ floatRadius: Float) -> (radius: Int, ww: UInt32, fw: UInt32) {
        let radius = Int(floatRadius)
        let ww = UInt32(Float(UInt32(1 << 24)) / (floatRadius * 2 + 1))
        let fw = (UInt32(1 << 24) - UInt32(radius * 2 + 1) &* ww) / 2
        return (radius, ww, fw)
    }

    /// Blur of the whole image (bit exact with Pillow).
    public static func gaussian(_ image: OccupancyRGBImage, radius: Double) -> OccupancyRGBImage {
        gaussian(image, radius: radius, region: (0, 0, image.width, image.height))
    }

    /// Blurs only `region` (x0, y0, x1, y1), treating it as if it were the whole image (edge replication at its
    /// border); pixels outside are copied unchanged. With 3 passes of an integer radius r, a pixel more than
    /// 3 * (r + 1) px inside the region equals Pillow's whole-image blur (the square reader uses only the
    /// board, so the panel is blurred on the board plus a 3 px margin; checked by the self-test).
    public static func gaussian(_ image: OccupancyRGBImage, radius: Double, region: (Int, Int, Int, Int),
                                generic: Bool = false) -> OccupancyRGBImage {
        if radius == 0 { return image }
        let r = extendedBoxRadius(Float(radius))
        if weights(r).radius == 0 && !generic && region.2 - region.0 >= 2 && region.3 - region.1 >= 2 {
            return gaussianRadius0(image, ww: weights(r).ww, fw: weights(r).fw, region: region)
        }
        let (x0, y0, x1, y1) = region
        let w = image.width, rw = x1 - x0, rh = y1 - y0
        var buf = image.pixels
        let (ir, ww, fw) = weights(r)
        var a = [UInt8](repeating: 0, count: max(rw, rh) * 3)
        var b = a
        a.withUnsafeMutableBufferPointer { pa in
            b.withUnsafeMutableBufferPointer { pb in
                buf.withUnsafeMutableBufferPointer { p in
                    let A = pa.baseAddress!, B = pb.baseAddress!, P = p.baseAddress!
                    for y in y0..<y1 {  // horizontal: 3 passes over each row
                        let row = P + (y * w + x0) * 3
                        A.update(from: row, count: rw * 3)
                        boxLine(B, A, n: rw, radius: ir, ww: ww, fw: fw)
                        boxLine(A, B, n: rw, radius: ir, ww: ww, fw: fw)
                        boxLine(row, A, n: rw, radius: ir, ww: ww, fw: fw)
                    }
                    for x in x0..<x1 {  // vertical: 3 passes over each column (Pillow transposes; same arithmetic)
                        var q = (y0 * w + x) * 3
                        for y in 0..<rh { A[y * 3] = P[q]; A[y * 3 + 1] = P[q + 1]; A[y * 3 + 2] = P[q + 2]; q += w * 3 }
                        boxLine(B, A, n: rh, radius: ir, ww: ww, fw: fw)
                        boxLine(A, B, n: rh, radius: ir, ww: ww, fw: fw)
                        boxLine(B, A, n: rh, radius: ir, ww: ww, fw: fw)
                        q = (y0 * w + x) * 3
                        for y in 0..<rh { P[q] = B[y * 3]; P[q + 1] = B[y * 3 + 1]; P[q + 2] = B[y * 3 + 2]; q += w * 3 }
                    }
                }
            }
        }
        return OccupancyRGBImage(width: image.width, height: image.height, pixels: buf)
    }

    /// Same arithmetic as boxLine when the integer box radius is 0 (sigma 1.0 gives 0.25): the running sum is then
    /// the centre pixel itself, so out[x] = (p[x] * ww + (p[x-1] + p[x+1]) * fw + 2^23) >> 24 with clamped ends.
    /// No serial dependency, so rows and the vertical passes (done row by row over whole rows) vectorise.
    static func gaussianRadius0(_ image: OccupancyRGBImage, ww: UInt32, fw: UInt32, region: (Int, Int, Int, Int)) -> OccupancyRGBImage {
        let (x0, y0, x1, y1) = region
        let w = image.width, rw = x1 - x0, rh = y1 - y0, n = rw * 3
        var a = [UInt8](repeating: 0, count: rh * n), b = a
        var buf = image.pixels
        a.withUnsafeMutableBufferPointer { pa in
            b.withUnsafeMutableBufferPointer { pb in
                buf.withUnsafeMutableBufferPointer { p in
                    let A = pa.baseAddress!, B = pb.baseAddress!, P = p.baseAddress!
                    for y in 0..<rh { A.advanced(by: y &* n).update(from: P.advanced(by: ((y0 &+ y) &* w &+ x0) &* 3), count: n) }
                    @inline(__always) func k(_ c: UInt8, _ l: UInt8, _ r: UInt8) -> UInt8 {
                        UInt8(truncatingIfNeeded: (UInt32(c) &* ww &+ (UInt32(l) &+ UInt32(r)) &* fw &+ (1 << 23)) >> 24)
                    }
                    func hpass(_ dst: UnsafeMutablePointer<UInt8>, _ src: UnsafeMutablePointer<UInt8>) {
                        for y in 0..<rh {
                            let s = src.advanced(by: y &* n), d = dst.advanced(by: y &* n)
                            for c in 0..<3 {
                                d[c] = k(s[c], s[c], s[3 &+ c])
                                d[n &- 3 &+ c] = k(s[n &- 3 &+ c], s[n &- 6 &+ c], s[n &- 3 &+ c])
                            }
                            var i = 3
                            while i < n &- 3 { d[i] = k(s[i], s[i &- 3], s[i &+ 3]); i &+= 1 }
                        }
                    }
                    func vpass(_ dst: UnsafeMutablePointer<UInt8>, _ src: UnsafeMutablePointer<UInt8>) {
                        for y in 0..<rh {
                            let s = src.advanced(by: y &* n), d = dst.advanced(by: y &* n)
                            let up = src.advanced(by: max(y &- 1, 0) &* n), dn = src.advanced(by: min(y &+ 1, rh &- 1) &* n)
                            for i in 0..<n { d[i] = k(s[i], up[i], dn[i]) }
                        }
                    }
                    hpass(B, A); hpass(A, B); hpass(B, A)
                    vpass(A, B); vpass(B, A); vpass(A, B)
                    for y in 0..<rh { P.advanced(by: ((y0 &+ y) &* w &+ x0) &* 3).update(from: A.advanced(by: y &* n), count: n) }
                }
            }
        }
        return OccupancyRGBImage(width: image.width, height: image.height, pixels: buf)
    }

    /// Pillow ImagingLineBoxBlur32 on one line of n pixels with 3 interleaved channels (out must not alias inp).
    /// Written without nested closures so the accumulator stays in a register.
    @inline(__always)
    static func boxLine(_ out: UnsafeMutablePointer<UInt8>, _ inp: UnsafePointer<UInt8>, n: Int, radius: Int, ww: UInt32, fw: UInt32) {
        let lastx = n - 1
        let edgeA = min(radius + 1, n), edgeB = max(n - radius - 1, 0)
        let lo1 = edgeA <= edgeB ? edgeA : edgeB   // end of the "left clamped" segment
        let hi1 = edgeA <= edgeB ? edgeB : edgeA   // start of the "right clamped" segment
        for c in 0..<3 {
            var acc: UInt32 = UInt32(inp[c]) &* UInt32(radius + 1)
            var x = 0
            while x < edgeA - 1 { acc &+= UInt32(inp[x * 3 + c]); x += 1 }
            acc &+= UInt32(inp[lastx * 3 + c]) &* UInt32(radius - edgeA + 1)
            let first = UInt32(inp[c]), last = UInt32(inp[lastx * 3 + c])
            x = 0
            while x < lo1 {  // subtract the first pixel, add x + radius
                acc = acc &+ UInt32(inp[(x + radius) * 3 + c]) &- first
                let bulk = acc &* ww &+ (first &+ UInt32(inp[(x + radius + 1) * 3 + c])) &* fw
                out[x * 3 + c] = UInt8(truncatingIfNeeded: (bulk &+ (1 << 23)) >> 24)
                x += 1
            }
            if edgeA <= edgeB {
                while x < hi1 {
                    let left = UInt32(inp[(x - radius - 1) * 3 + c])
                    acc = acc &+ UInt32(inp[(x + radius) * 3 + c]) &- left
                    let bulk = acc &* ww &+ (left &+ UInt32(inp[(x + radius + 1) * 3 + c])) &* fw
                    out[x * 3 + c] = UInt8(truncatingIfNeeded: (bulk &+ (1 << 23)) >> 24)
                    x += 1
                }
            } else {
                while x < hi1 {  // radius wider than the line: both ends clamped
                    acc = acc &+ last &- first
                    let bulk = acc &* ww &+ (first &+ last) &* fw
                    out[x * 3 + c] = UInt8(truncatingIfNeeded: (bulk &+ (1 << 23)) >> 24)
                    x += 1
                }
            }
            while x <= lastx {  // subtract x - radius - 1, add the last pixel
                let left = UInt32(inp[(x - radius - 1) * 3 + c])
                acc = acc &+ last &- left
                let bulk = acc &* ww &+ (left &+ last) &* fw
                out[x * 3 + c] = UInt8(truncatingIfNeeded: (bulk &+ (1 << 23)) >> 24)
                x += 1
            }
        }
    }
}
