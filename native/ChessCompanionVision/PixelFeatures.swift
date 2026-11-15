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
        let count = tileSize * tileSize * 3
        guard pixels.count == count else { return [] }
        return pixels.withUnsafeBufferPointer { source -> [Double] in
            for value in source where !value.isFinite { return [] }
            // Same integer arithmetic as before (blur x3 horizontal, x3 vertical, then the
            // separable 64->32 resize), but with two reused byte buffers and resampling
            // weights computed once instead of per-pass/per-tile allocations.
            var front = [UInt8](repeating: 0, count: count), back = [UInt8](repeating: 0, count: count)
            front.withUnsafeMutableBufferPointer { a in
                back.withUnsafeMutableBufferPointer { b in
                    for index in 0..<count { a[index] = UInt8(min(255.0, max(0.0, source[index]))) }
                    // Pillow's extended-box Gaussian approximation runs three horizontal
                    // passes, then three vertical passes. Integer rounding occurs each pass.
                    blurPass(a, into: b, horizontal: true); blurPass(b, into: a, horizontal: true); blurPass(a, into: b, horizontal: true)
                    blurPass(b, into: a, horizontal: false); blurPass(a, into: b, horizontal: false); blurPass(b, into: a, horizontal: false)
                }
            }
            var result = [Double](repeating: 0, count: featureSize * featureSize * 3)
            front.withUnsafeBufferPointer { blurred in
                result.withUnsafeMutableBufferPointer { output in downsampleCrop(blurred, into: output) }
            }
            return result
        }
    }

    /// One fixed 0.5-radius pass (horizontal or vertical) over a 64x64 RGB tile.
    /// value = center*p + outer*(prior + next), rounded with >>24; edges clamp to the
    /// tile, so the first/last pixel reuse themselves as prior/next neighbor.
    private static func blurPass(_ input: UnsafeMutableBufferPointer<UInt8>, into output: UnsafeMutableBufferPointer<UInt8>,
                                 horizontal: Bool) {
        // Fixed 24-bit coefficients sum to 2^24; radius is always 0.5 here.
        let center: Int64 = 15_379_114
        let outer: Int64 = 699_051
        let rounding: Int64 = 1 << 23
        let step = horizontal ? 3 : tileSize * 3          // distance to the neighbor along the pass
        for y in 0..<tileSize {
            for x in 0..<tileSize {
                let position = horizontal ? x : y
                let index = (y * tileSize + x) * 3
                let previous = position > 0 ? index - step : index
                let next = position < tileSize - 1 ? index + step : index
                for channel in 0..<3 {
                    let value = center * Int64(input[index + channel])
                        + outer * (Int64(input[previous + channel]) + Int64(input[next + channel]))
                    output[index + channel] = UInt8((value + rounding) >> 24)
                }
            }
        }
    }

    /// Weights of the fixed 64->32 feature resize: computed once; an immutable
    /// lazily initialized static, so it is safe to share across threads/actors.
    private static let featureResizePlan = weights(input: 64, output: 32)

    /// resizeRGB(64x64 -> 32x32), then the 2-pixel crop and /255. Same 22-bit integer
    /// accumulation as resizeRGB; only the 28x28 output pixels that are kept are computed.
    private static func downsampleCrop(_ input: UnsafeBufferPointer<UInt8>, into output: UnsafeMutableBufferPointer<Double>) {
        let plan = featureResizePlan
        let rounding: Int64 = 1 << 21
        var horizontal = [UInt8](repeating: 0, count: 32 * tileSize * 3)
        horizontal.withUnsafeMutableBufferPointer { h in
            for y in 0..<tileSize {
                for x in 0..<32 {
                    let start = plan[x].start
                    plan[x].coefficients.withUnsafeBufferPointer { weights in
                        for channel in 0..<3 {
                            var value = rounding
                            for offset in 0..<weights.count {
                                value += Int64(input[(y * tileSize + start + offset) * 3 + channel]) * weights[offset]
                            }
                            h[(y * 32 + x) * 3 + channel] = UInt8(clamping: value >> 22)
                        }
                    }
                }
            }
            var cursor = 0
            for y in 2..<30 {
                let start = plan[y].start
                plan[y].coefficients.withUnsafeBufferPointer { weights in
                    for x in 2..<30 {
                        for channel in 0..<3 {
                            var value = rounding
                            for offset in 0..<weights.count {
                                value += Int64(h[((start + offset) * 32 + x) * 3 + channel]) * weights[offset]
                            }
                            output[cursor] = Double(UInt8(clamping: value >> 22)) / 255.0
                            cursor += 1
                        }
                    }
                }
            }
        }
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
        guard features.count == featureSize * featureSize * 3 else { return .nan }
        return features.withUnsafeBufferPointer { input -> Double in
            for value in input where !value.isFinite { return .nan }
            var grayStorage = [Double](repeating: 0, count: featureSize * featureSize)
            return grayStorage.withUnsafeMutableBufferPointer { gray -> Double in
                for index in 0..<gray.count {
                    gray[index] = (input[index * 3] + input[index * 3 + 1] + input[index * 3 + 2]) / 3.0
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
    }
}
