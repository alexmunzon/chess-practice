// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "ChessCompanionRuntime",
    platforms: [.macOS(.v14), .iOS("17.2")],
    products: [.library(name: "ChessCompanionRuntime", targets: ["ChessCompanionRuntime"])],
    targets: [
        .target(
            name: "ChessCompanionRuntime",
            path: ".",
            exclude: ["README.md", "index.html", "runtime.js", "VerifyRuntime.swift"],
            sources: ["NativeEngineRuntime.swift"]
        )
    ]
)
