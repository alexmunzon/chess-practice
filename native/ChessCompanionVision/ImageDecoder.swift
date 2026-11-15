import Foundation
import CoreGraphics
import ImageIO

/// Top-left, row-major, interleaved 8-bit RGB pixels after EXIF orientation.
public struct RGBImage {
    public let width: Int
    public let height: Int
    public let pixels: [UInt8]

    public init(width: Int, height: Int, pixels: [UInt8]) {
        self.width = width
        self.height = height
        self.pixels = pixels
    }
}

public enum ImageDecodeError: Error, LocalizedError {
    case invalidByteCount
    case unsupportedFormat
    case invalidImage
    case multipleFrames
    case invalidDimensions
    case invalidOrientation
    case nonopaqueImage
    case allocationFailed

    public var errorDescription: String? {
        switch self {
        case .invalidByteCount: return "Expected at most 8 MiB of image bytes."
        case .unsupportedFormat: return "A supported PNG, JPEG or WebP image is required."
        case .invalidImage: return "Image decoding failed."
        case .multipleFrames: return "Only single-frame images are supported."
        case .invalidDimensions: return "Image dimensions exceed the supported bounds."
        case .invalidOrientation: return "Unsupported EXIF image orientation."
        case .nonopaqueImage: return "Nonopaque images are unsupported."
        case .allocationFailed: return "Unable to allocate the bounded image buffer."
        }
    }
}

/// ImageIO/CoreGraphics decoding only: no Vision, CoreML, GPU, camera or metadata
/// supplied by a caller. Embedded color profiles are converted by CoreGraphics
/// to sRGB. Color-profile/JPEG decoder equivalence with Pillow is not asserted.
/// WebP is accepted only when this platform's ImageIO can decode it.
public enum ImageDecoder {
    public static let maximumBytes = 8 * 1024 * 1024
    public static let maximumDimension = 8192
    public static let maximumPixels = 25_000_000

    public static func decode(_ data: Data) throws -> RGBImage {
        guard !data.isEmpty, data.count <= maximumBytes else {
            throw ImageDecodeError.invalidByteCount
        }
        guard supportedSignature(data) else { throw ImageDecodeError.unsupportedFormat }
        let options = [kCGImageSourceShouldCache: false] as CFDictionary
        guard let source = CGImageSourceCreateWithData(data as CFData, options) else {
            throw ImageDecodeError.invalidImage
        }
        guard CGImageSourceGetCount(source) == 1 else { throw ImageDecodeError.multipleFrames }
        guard let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let width = (properties[kCGImagePropertyPixelWidth] as? NSNumber)?.intValue,
              let height = (properties[kCGImagePropertyPixelHeight] as? NSNumber)?.intValue,
              width > 0, height > 0, width <= maximumDimension, height <= maximumDimension,
              width * height <= maximumPixels else {
            throw ImageDecodeError.invalidDimensions
        }
        let orientation = (properties[kCGImagePropertyOrientation] as? NSNumber)?.intValue ?? 1
        guard (1...8).contains(orientation) else { throw ImageDecodeError.invalidOrientation }

        // Bounds are checked before decompression or bitmap allocation. Using
        // CreateImageAtIndex rather than a transformed thumbnail leaves EXIF
        // handling to the one explicit permutation below.
        guard let image = CGImageSourceCreateImageAtIndex(source, 0, options),
              image.width == width, image.height == height else {
            throw ImageDecodeError.invalidImage
        }
        guard let colorSpace = CGColorSpace(name: CGColorSpace.sRGB) else {
            throw ImageDecodeError.allocationFailed
        }
        var rgba = [UInt8](repeating: 0, count: width * height * 4)
        let drawn = rgba.withUnsafeMutableBytes { buffer -> Bool in
            guard let context = CGContext(data: buffer.baseAddress, width: width, height: height,
                                          bitsPerComponent: 8, bytesPerRow: width * 4,
                                          space: colorSpace,
                                          bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue |
                                            CGBitmapInfo.byteOrder32Big.rawValue) else { return false }
            context.setBlendMode(.copy)
            context.interpolationQuality = .none
            context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
            return true
        }
        guard drawn else { throw ImageDecodeError.allocationFailed }
        // Inspect decoded alpha, including PNG palette transparency. Dropping
        // alpha could otherwise reveal pieces hidden in the displayed image.
        for offset in stride(from: 3, to: rgba.count, by: 4) {
            guard rgba[offset] == 255 else { throw ImageDecodeError.nonopaqueImage }
        }
        let swapsAxes = orientation >= 5
        let outputWidth = swapsAxes ? height : width
        let outputHeight = swapsAxes ? width : height
        var rgb = [UInt8](repeating: 0, count: outputWidth * outputHeight * 3)
        for sourceY in 0..<height {
            for sourceX in 0..<width {
                let destination: (Int, Int)
                switch orientation {
                case 1: destination = (sourceX, sourceY)
                case 2: destination = (width - 1 - sourceX, sourceY)
                case 3: destination = (width - 1 - sourceX, height - 1 - sourceY)
                case 4: destination = (sourceX, height - 1 - sourceY)
                case 5: destination = (sourceY, sourceX)
                case 6: destination = (height - 1 - sourceY, sourceX)
                case 7: destination = (height - 1 - sourceY, width - 1 - sourceX)
                default: destination = (sourceY, width - 1 - sourceX) // EXIF 8
                }
                let inputOffset = (sourceY * width + sourceX) * 4
                let outputOffset = (destination.1 * outputWidth + destination.0) * 3
                rgb[outputOffset] = rgba[inputOffset]
                rgb[outputOffset + 1] = rgba[inputOffset + 1]
                rgb[outputOffset + 2] = rgba[inputOffset + 2]
            }
        }
        return RGBImage(width: outputWidth, height: outputHeight, pixels: rgb)
    }

    private static func supportedSignature(_ data: Data) -> Bool {
        let prefix = Array(data.prefix(12))
        if prefix.count >= 8, Array(prefix.prefix(8)) == [137, 80, 78, 71, 13, 10, 26, 10] { return true }
        if prefix.count >= 3, prefix[0] == 255, prefix[1] == 216, prefix[2] == 255 { return true }
        return prefix.count == 12 && Array(prefix[0..<4]) == [82, 73, 70, 70] &&
            Array(prefix[8..<12]) == [87, 69, 66, 80]
    }
}
