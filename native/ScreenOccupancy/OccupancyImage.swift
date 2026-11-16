import CoreGraphics
import Foundation
import ImageIO

/// Top-left, row-major, interleaved 8-bit RGB. Pixel (x, y) has its centre at (x, y).
public struct OccupancyRGBImage {
    public let width: Int
    public let height: Int
    public var pixels: [UInt8]

    public init(width: Int, height: Int, pixels: [UInt8]) {
        precondition(pixels.count == width * height * 3)
        self.width = width
        self.height = height
        self.pixels = pixels
    }
}

public enum OccupancyImageError: Error, CustomStringConvertible {
    case unreadable, unsupported, nonopaque, tooLarge
    public var description: String {
        switch self {
        case .unreadable: return "unreadable-image"
        case .unsupported: return "unsupported-image-layout"
        case .nonopaque: return "nonopaque-image"
        case .tooLarge: return "image-too-large"
        }
    }
}

/// Decodes PNG/JPEG with ImageIO. For 8-bit RGB / RGBA / gray bitmaps the decoded bytes are read
/// directly from the CGImage data provider with NO colour conversion, so a PNG gives exactly the same
/// values as Pillow's `Image.open(p).convert('RGB')` (the reference path). Other layouts are drawn into
/// an sRGB context (not asserted equal to Pillow). EXIF orientation is ignored, as Pillow does.
public enum OccupancyImageDecoder {
    public static let maximumPixels = 40_000_000

    public static func decode(_ data: Data) throws -> OccupancyRGBImage {
        guard let source = CGImageSourceCreateWithData(data as CFData, [kCGImageSourceShouldCache: false] as CFDictionary),
              CGImageSourceGetCount(source) >= 1,
              let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else { throw OccupancyImageError.unreadable }
        let w = image.width, h = image.height
        guard w > 0, h > 0, w * h <= maximumPixels else { throw OccupancyImageError.tooLarge }
        if let direct = try raw(image, w, h) { return direct }
        return try drawn(image, w, h)
    }

    private static func raw(_ image: CGImage, _ w: Int, _ h: Int) throws -> OccupancyRGBImage? {
        guard image.bitsPerComponent == 8, let model = image.colorSpace?.model,
              let cfdata = image.dataProvider?.data, let base = CFDataGetBytePtr(cfdata) else { return nil }
        let bpp = image.bitsPerPixel / 8, stride = image.bytesPerRow
        let alpha = image.alphaInfo
        let little = image.bitmapInfo.contains(.byteOrder32Little)
        guard CFDataGetLength(cfdata) >= stride * (h - 1) + w * bpp else { return nil }
        var out = [UInt8](repeating: 0, count: w * h * 3)
        switch (model, bpp) {
        case (.monochrome, 1):
            for y in 0..<h { for x in 0..<w { let v = base[y * stride + x]; let o = (y * w + x) * 3
                out[o] = v; out[o + 1] = v; out[o + 2] = v } }
        case (.rgb, 3) where alpha == .none && !little:
            for y in 0..<h { for x in 0..<w { let i = y * stride + x * 3, o = (y * w + x) * 3
                out[o] = base[i]; out[o + 1] = base[i + 1]; out[o + 2] = base[i + 2] } }
        case (.rgb, 4):
            // Byte positions of R, G, B, A inside one 4-byte pixel, as stored in memory.
            let alphaFirst = alpha == .first || alpha == .premultipliedFirst || alpha == .noneSkipFirst
            let hasAlpha = alpha == .first || alpha == .last || alpha == .premultipliedFirst || alpha == .premultipliedLast
            var pos = alphaFirst ? [1, 2, 3, 0] : [0, 1, 2, 3]  // r, g, b, a in big-endian order
            if little { pos = pos.map { 3 - $0 } }
            for y in 0..<h {
                for x in 0..<w {
                    let i = y * stride + x * 4, o = (y * w + x) * 3
                    if hasAlpha && base[i + pos[3]] != 255 { throw OccupancyImageError.nonopaque }
                    out[o] = base[i + pos[0]]; out[o + 1] = base[i + pos[1]]; out[o + 2] = base[i + pos[2]]
                }
            }
        default:
            return nil
        }
        return OccupancyRGBImage(width: w, height: h, pixels: out)
    }

    private static func drawn(_ image: CGImage, _ w: Int, _ h: Int) throws -> OccupancyRGBImage {
        guard let space = CGColorSpace(name: CGColorSpace.sRGB) else { throw OccupancyImageError.unsupported }
        var rgba = [UInt8](repeating: 0, count: w * h * 4)
        let ok = rgba.withUnsafeMutableBytes { buf -> Bool in
            guard let ctx = CGContext(data: buf.baseAddress, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4,
                                      space: space, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
                                        | CGBitmapInfo.byteOrder32Big.rawValue) else { return false }
            ctx.setBlendMode(.copy)
            ctx.interpolationQuality = .none
            ctx.draw(image, in: CGRect(x: 0, y: 0, width: w, height: h))
            return true
        }
        guard ok else { throw OccupancyImageError.unsupported }
        var out = [UInt8](repeating: 0, count: w * h * 3)
        for p in 0..<(w * h) {
            guard rgba[p * 4 + 3] == 255 else { throw OccupancyImageError.nonopaque }
            out[p * 3] = rgba[p * 4]; out[p * 3 + 1] = rgba[p * 4 + 1]; out[p * 3 + 2] = rgba[p * 4 + 2]
        }
        return OccupancyRGBImage(width: w, height: h, pixels: out)
    }
}
