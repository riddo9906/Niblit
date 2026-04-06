// main.swift — Niblit Swift node executable entry-point
//
// This file is the only source in the NiblitNodeExec target.  All real
// logic lives in the NiblitNode library target (Sources/NiblitNode/) so
// the test target can import it directly.
//
// ArgumentParser's `AsyncParsableCommand` generates a static `main()` that
// parses arguments, constructs the command, and calls `run() async throws`.
// Calling it here keeps the executable wrapper completely minimal.

import NiblitNode

NiblitNodeCommand.main()
