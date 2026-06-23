// main.swift — Niblit Swift node executable entry-point
//
// This file is the only source in the NiblitNodeExec target. All real
// logic lives in the NiblitNode library target (Sources/NiblitNode/) so
// the test target can import it directly.

import Foundation
import NiblitNode

@main
struct NiblitNodeExec {
    static func main() async {
        do {
            try await NiblitNodeCommand.main()
        } catch {
            fputs("[Niblit Swift] \(error)\n", stderr)
            Foundation.exit(1)
        }
    }
}
