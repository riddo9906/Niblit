// swift-tools-version: 6.3
import PackageDescription

let package = Package(
    name: "swift-argument-parser",
    products: [
        .library(name: "ArgumentParser", targets: ["ArgumentParser"]),
    ],
    targets: [
        .target(name: "ArgumentParser", path: "Sources/ArgumentParser")
    ]
)
