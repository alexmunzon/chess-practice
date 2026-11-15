import Foundation

/// macOS conformance runner only. iPhone callers invoke the library directly
/// with Data and bundled template Data; no subprocess is needed on the phone.
@main
struct NativeVisionCLI {
    static func main() {
        do {
            let args=Array(CommandLine.arguments.dropFirst())
            guard args.count>=3,args[0]=="--assets" else {throw NativeSyntheticRecognizer.Failure("usage: native-vision --assets TEMPLATE.json IMAGE [IMAGE ...]")}
            let recognizer=try NativeSyntheticRecognizer(templateData:Data(contentsOf:URL(fileURLWithPath:args[1])))
            for image in args.dropFirst(2) {
                let result=try recognizer.recognize(imageData:Data(contentsOf:URL(fileURLWithPath:image)))
                let data=try JSONSerialization.data(withJSONObject:result,options:[.sortedKeys])
                FileHandle.standardOutput.write(data);FileHandle.standardOutput.write(Data([10]))
            }
        } catch {FileHandle.standardError.write(Data("Native synthetic recognition failed: \(error)\n".utf8));exit(1)}
    }
}
