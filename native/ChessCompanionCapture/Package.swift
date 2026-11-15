// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "ChessCompanionCapture",
    platforms: [.macOS(.v13), .iOS("17.2")],
    products: [.library(name: "ChessCompanionCapture", targets: ["ChessCompanionCapture"])],
    targets: [
        .target(name: "ChessCompanionCapture"),
        .executableTarget(name: "CaptureContractChecks", dependencies: ["ChessCompanionCapture"], path: "Tests/ChessCompanionCaptureTests")
    ]
)
