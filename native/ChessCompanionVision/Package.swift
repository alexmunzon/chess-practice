// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "ChessCompanionVision",
    platforms: [.iOS(.v16), .macOS(.v13)],
    products: [.library(name: "ChessCompanionVision", targets: ["ChessCompanionVision"])],
    targets: [.target(name: "ChessCompanionVision", path: ".",
                      exclude: ["NativeVisionCLI.swift", "export_fixed_templates.py", "conformance.py", "README.md"],
                      sources: ["ImageDecoder.swift", "PixelFeatures.swift", "SyntheticRecognizer.swift", "BundledAssets.swift"],
                      resources: [.process("Assets")])]
)
