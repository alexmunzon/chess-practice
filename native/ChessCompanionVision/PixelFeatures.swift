import Foundation

/// Fixed synthetic-template preprocessing, implemented without Python or a GPU.
/// The 0.5-radius blur coefficients and separable bilinear rounding were checked
/// numerically against local Pillow 12.3.0 on deterministic development inputs.
/// This is a narrow preprocessing contract, not general Pillow compatibility.
public enum PixelFeatures {
    private static let tileSize = 64
    private static let featureSize = 28

    /// Clamp/truncate RGB64 -> GaussianBlur(0.5) -> RGB32 -> crop 2px -> RGB/255.
    /// Malformed internal arrays fail closed with an empty feature vector.
    public static func extract(_ pixels: [Double]) -> [Double] {
        guard pixels.count == tileSize * tileSize * 3,
              pixels.allSatisfy({ $0.isFinite }) else { return [] }
        var bytes = pixels.map { UInt8(min(255.0, max(0.0, $0))) }
        // Pillow's extended-box Gaussian approximation runs three horizontal
        // passes, then three vertical passes. Integer rounding occurs each pass.
        for _ in 0..<3 { bytes = blurPass(bytes, horizontal: true) }
        for _ in 0..<3 { bytes = blurPass(bytes, horizontal: false) }
        let small = resizeRGB(bytes, width: tileSize, height: tileSize,
                              toWidth: 32, toHeight: 32)
        var result = [Double]()
        result.reserveCapacity(featureSize * featureSize * 3)
        for y in 2..<30 {
            for x in 2..<30 {
                let offset = (y * 32 + x) * 3
                for channel in 0..<3 { result.append(Double(small[offset + channel]) / 255.0) }
            }
        }
        return result
    }

    private static func blurPass(_ input: [UInt8], horizontal: Bool) -> [UInt8] {
        // Fixed 24-bit coefficients sum to 2^24; radius is always 0.5 here.
        let center: Int64 = 15_379_114
        let outer: Int64 = 699_051
        let rounding: Int64 = 1 << 23
        var output = [UInt8](repeating: 0, count: input.count)
        for y in 0..<tileSize {
            for x in 0..<tileSize {
                let priorX = horizontal ? max(0, x - 1) : x
                let nextX = horizontal ? min(tileSize - 1, x + 1) : x
                let priorY = horizontal ? y : max(0, y - 1)
                let nextY = horizontal ? y : min(tileSize - 1, y + 1)
                let index = (y * tileSize + x) * 3
                let previous = (priorY * tileSize + priorX) * 3
                let next = (nextY * tileSize + nextX) * 3
                for channel in 0..<3 {
                    let value = center * Int64(input[index + channel])
                        + outer * (Int64(input[previous + channel]) + Int64(input[next + channel]))
                    output[index + channel] = UInt8((value + rounding) >> 24)
                }
            }
        }
        return output
    }

    private struct ResampleWeights {
        let start: Int
        let coefficients: [Int64]
    }

    private static func weights(input: Int, output: Int) -> [ResampleWeights] {
        let scale = Double(input) / Double(output)
        let filterScale = max(1.0, scale)
        let precision = Double(1 << 22)
        return (0..<output).map { destination in
            let center = (Double(destination) + 0.5) * scale
            let start = max(0, Int(center - filterScale + 0.5))
            let end = min(input, Int(center + filterScale + 0.5))
            let values = (start..<end).map { source in
                max(0.0, 1.0 - abs((Double(source) + 0.5 - center) / filterScale))
            }
            let total = values.reduce(0.0, +)
            return ResampleWeights(start: start,
                coefficients: values.map { Int64($0 / total * precision + 0.5) })
        }
    }

    /// Separable antialiased triangle resampling with 22-bit coefficient rounding.
    /// This also supports the recognizer's bounded marker-detection downsample.
    public static func resizeRGB(_ pixels: [UInt8], width: Int, height: Int,
                                 toWidth: Int, toHeight: Int) -> [UInt8] {
        guard width > 0, height > 0, toWidth > 0, toHeight > 0,
              [width, height, toWidth, toHeight].allSatisfy({ $0 <= 8192 }),
              pixels.count == width * height * 3 else { return [] }
        if width == toWidth && height == toHeight { return pixels }
        let rounding: Int64 = 1 << 21
        var horizontal = pixels
        if width != toWidth {
            let plan = weights(input: width, output: toWidth)
            horizontal = [UInt8](repeating: 0, count: toWidth * height * 3)
            for y in 0..<height {
                for x in 0..<toWidth {
                    for channel in 0..<3 {
                        var value = rounding
                        for (offset, weight) in plan[x].coefficients.enumerated() {
                            value += Int64(pixels[(y * width + plan[x].start + offset) * 3 + channel]) * weight
                        }
                        horizontal[(y * toWidth + x) * 3 + channel] = UInt8(clamping: value >> 22)
                    }
                }
            }
        }
        if height == toHeight { return horizontal }
        let plan = weights(input: height, output: toHeight)
        var result = [UInt8](repeating: 0, count: toWidth * toHeight * 3)
        for y in 0..<toHeight {
            for x in 0..<toWidth {
                for channel in 0..<3 {
                    var value = rounding
                    for (offset, weight) in plan[y].coefficients.enumerated() {
                        value += Int64(horizontal[((plan[y].start + offset) * toWidth + x) * 3 + channel]) * weight
                    }
                    result[(y * toWidth + x) * 3 + channel] = UInt8(clamping: value >> 22)
                }
            }
        }
        return result
    }

    /// Mean squared horizontal + vertical gradient of the RGB-mean feature.
    public static func edgeEnergy(_ features: [Double]) -> Double {
        guard features.count == featureSize * featureSize * 3,
              features.allSatisfy({ $0.isFinite }) else { return .nan }
        var gray = [Double](repeating: 0, count: featureSize * featureSize)
        for index in gray.indices {
            gray[index] = (features[index * 3] + features[index * 3 + 1] + features[index * 3 + 2]) / 3.0
        }
        var vertical = 0.0, horizontal = 0.0
        for y in 0..<featureSize {
            for x in 0..<featureSize {
                let index = y * featureSize + x
                if y + 1 < featureSize {
                    let delta = gray[index + featureSize] - gray[index]
                    vertical += delta * delta
                }
                if x + 1 < featureSize {
                    let delta = gray[index + 1] - gray[index]
                    horizontal += delta * delta
                }
            }
        }
        let count = Double(featureSize * (featureSize - 1))
        return vertical / count + horizontal / count
    }
}
