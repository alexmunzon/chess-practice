import CoreGraphics
import Foundation
import ImageIO

/// Single-channel float image, 0...255, row-major. Pixel (x, y) has its center at (x, y).
struct GrayImage {
    let width: Int
    let height: Int
    var pixels: [Float]

    init(width: Int, height: Int, pixels: [Float]) {
        self.width = width
        self.height = height
        self.pixels = pixels
    }

    /// Decodes PNG/JPEG bytes with ImageIO and converts to 8-bit device gray via CoreGraphics.
    init?(imageData: Data, maxPixels: Int = 40_000_000) {
        guard let source = CGImageSourceCreateWithData(imageData as CFData, nil),
              let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else { return nil }
        let w = image.width, h = image.height
        guard w > 16, h > 16, w * h <= maxPixels else { return nil }
        var bytes = [UInt8](repeating: 0, count: w * h)
        let ok: Bool = bytes.withUnsafeMutableBytes { raw in
            guard let ctx = CGContext(data: raw.baseAddress, width: w, height: h, bitsPerComponent: 8,
                                      bytesPerRow: w, space: CGColorSpaceCreateDeviceGray(),
                                      bitmapInfo: CGImageAlphaInfo.none.rawValue) else { return false }
            ctx.interpolationQuality = .none
            ctx.draw(image, in: CGRect(x: 0, y: 0, width: w, height: h))
            return true
        }
        guard ok else { return nil }
        self.width = w
        self.height = h
        self.pixels = bytes.map { Float($0) }
    }

    @inline(__always) func at(_ x: Int, _ y: Int) -> Float {
        let cx = min(max(x, 0), width - 1), cy = min(max(y, 0), height - 1)
        return pixels[cy * width + cx]
    }

    /// Bilinear sample with edge clamping.
    @inline(__always) func sample(_ x: Float, _ y: Float) -> Float {
        let xc = min(max(x, 0), Float(width) - 1.001), yc = min(max(y, 0), Float(height) - 1.001)
        let x0 = Int(xc), y0 = Int(yc)
        let fx = xc - Float(x0), fy = yc - Float(y0)
        let i = y0 * width + x0
        let a = pixels[i], b = pixels[i + 1], c = pixels[i + width], d = pixels[i + width + 1]
        return a + (b - a) * fx + (c - a) * fy + (a - b - c + d) * fx * fy
    }

    /// 2x2 box downsample. New pixel k covers old pixels 2k, 2k+1 (center 2k + 0.5).
    func halved() -> GrayImage {
        let w = width / 2, h = height / 2
        var out = [Float](repeating: 0, count: w * h)
        pixels.withUnsafeBufferPointer { p in
            for y in 0..<h {
                let r0 = 2 * y * width, r1 = r0 + width
                for x in 0..<w {
                    out[y * w + x] = 0.25 * (p[r0 + 2*x] + p[r0 + 2*x + 1] + p[r1 + 2*x] + p[r1 + 2*x + 1])
                }
            }
        }
        return GrayImage(width: w, height: h, pixels: out)
    }

    /// Separable Gaussian blur with clamped borders.
    func blurred(sigma: Float) -> GrayImage {
        guard sigma > 0.05 else { return self }
        let radius = max(1, Int((3 * sigma).rounded(.up)))
        var kernel = (-radius...radius).map { exp(-Float($0 * $0) / (2 * sigma * sigma)) }
        let total = kernel.reduce(0, +)
        kernel = kernel.map { $0 / total }
        var tmp = [Float](repeating: 0, count: pixels.count)
        var out = tmp
        let w = width, h = height
        pixels.withUnsafeBufferPointer { p in
            for y in 0..<h {
                let row = y * w
                for x in 0..<w {
                    var s: Float = 0
                    for k in -radius...radius {
                        s += kernel[k + radius] * p[row + min(max(x + k, 0), w - 1)]
                    }
                    tmp[row + x] = s
                }
            }
        }
        tmp.withUnsafeBufferPointer { p in
            for y in 0..<h {
                for x in 0..<w {
                    var s: Float = 0
                    for k in -radius...radius {
                        s += kernel[k + radius] * p[min(max(y + k, 0), h - 1) * w + x]
                    }
                    out[y * w + x] = s
                }
            }
        }
        return GrayImage(width: w, height: h, pixels: out)
    }
}
