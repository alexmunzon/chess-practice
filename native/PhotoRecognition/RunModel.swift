import Foundation
import CoreML

// Only Apple CoreML loads the pinned data-only graph. No plugin/custom code loading.
do {
    let args = CommandLine.arguments
    guard args.count >= 4 else { throw NSError(domain: "Usage: RunModel model.mlpackage input.f32 output.json [input output ...]", code: 1) }
    let begin = Date()
    let compiled = try MLModel.compileModel(at: URL(fileURLWithPath: args[1]))
    let config = MLModelConfiguration()
    let cpuDiagnostic = ProcessInfo.processInfo.environment["CHESS_COREML_CPU_DIAGNOSTIC"] == "1"
    config.computeUnits = cpuDiagnostic ? .cpuOnly : .cpuAndGPU
    config.allowLowPrecisionAccumulationOnGPU = false
    let model = try MLModel(contentsOf: compiled, configuration: config)
    let loadMs = Date().timeIntervalSince(begin)*1000
    guard (args.count - 2) % 2 == 0 else { throw NSError(domain: "Input/output pairs required", code: 1) }
    for offset in stride(from: 2, to: args.count, by: 2) {
        let data = try Data(contentsOf: URL(fileURLWithPath: args[offset]))
        guard data.count == 3*644*644*4 else { throw NSError(domain: "Wrong input byte count", code: 1) }
        let tensor = try MLMultiArray(shape: [1,3,644,644], dataType: .float32)
        data.copyBytes(to: tensor.dataPointer.assumingMemoryBound(to: UInt8.self), count: data.count)
        let provider = try MLDictionaryFeatureProvider(dictionary: ["image": tensor])
        var times = [Double](); var values = [Double]()
        for _ in 0..<3 {
            let start = Date()
            let result = try model.prediction(from: provider)
            times.append(Date().timeIntervalSince(start)*1000)
            guard let logits = result.featureValue(for: "logits")?.multiArrayValue,
                  logits.shape.map({$0.intValue}) == [1,64,13], logits.dataType == .float32 else {
                throw NSError(domain: "Invalid model output schema", code: 1)
            }
            values = (0..<832).map { logits[$0].doubleValue }
            guard values.allSatisfy({$0.isFinite}) else { throw NSError(domain: "Nonfinite logits", code: 1) }
        }
        let payload: [String: Any] = ["logits":values,"inferenceMs":times,"compileAndLoadMs":loadMs,"computeUnits":cpuDiagnostic ? "CPU_ONLY_DIAGNOSTIC" : "CPU_AND_GPU", "allowLowPrecisionAccumulationOnGPU":false]
        try JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted,.sortedKeys]).write(to: URL(fileURLWithPath: args[offset+1]))
    }
} catch { fputs("CoreML evaluation failed: \(error)\n", stderr); exit(1) }
