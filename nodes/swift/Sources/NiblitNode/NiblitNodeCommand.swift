// NiblitNodeCommand.swift — Niblit Swift deployment node entry-point
//
// This command mirrors the behaviour of:
//   nodes/typescript/src/index.ts
//   nodes/rust/src/main.rs
//
// What it does on startup:
//   1. Health-check the Niblit Python core.
//   2. Pull NiblitStateEnvelope (or create a fresh one).
//   3. Register with the self-improving runtime via /api/env/capabilities.
//   4. Run in single-command mode or drop into an interactive REPL.
//   5. Push the updated envelope back on exit.
//
// Environment variables:
//   NIBLIT_URL      — Base URL for the Niblit core API (default: http://localhost:8000)
//   NIBLIT_API_KEY  — Optional API key (X-Niblit-Key header)
//
// Note: @main lives in Sources/NiblitNodeExec/main.swift so this struct can
// be part of the library target and imported directly by the test target.

import Foundation

// MARK: – Command

public struct NiblitNodeCommand {
    public var url: String
    public var apiKey: String?
    public var timeout: Double
    public var message: [String]

    public init(
        url: String = ProcessInfo.processInfo.environment["NIBLIT_URL"] ?? "http://localhost:8000",
        apiKey: String? = ProcessInfo.processInfo.environment["NIBLIT_API_KEY"],
        timeout: Double = 20,
        message: [String] = []
    ) {
        self.url = url
        self.apiKey = apiKey
        self.timeout = timeout
        self.message = message
    }

    public static func main() async throws {
        let command = try parseCommandLineArguments(CommandLine.arguments)
        try await command.run()
    }

    public static func parseCommandLineArguments(_ arguments: [String]) throws -> NiblitNodeCommand {
        var url = ProcessInfo.processInfo.environment["NIBLIT_URL"] ?? "http://localhost:8000"
        var apiKey = ProcessInfo.processInfo.environment["NIBLIT_API_KEY"]
        var timeout: Double = 20
        var message: [String] = []

        var index = 0
        while index < arguments.count {
            let argument = arguments[index]
            switch argument {
            case "--url":
                guard index + 1 < arguments.count else { throw CLIError.missingValue(for: "--url") }
                url = arguments[index + 1]
                index += 1
            case "--api-key":
                guard index + 1 < arguments.count else { throw CLIError.missingValue(for: "--api-key") }
                apiKey = arguments[index + 1]
                index += 1
            case "--timeout":
                guard index + 1 < arguments.count else { throw CLIError.missingValue(for: "--timeout") }
                guard let parsedTimeout = Double(arguments[index + 1]) else {
                    throw CLIError.invalidValue(arguments[index + 1], for: "--timeout")
                }
                timeout = parsedTimeout
                index += 1
            case "--help", "-h":
                printUsage()
                throw CLIError.helpRequested
            default:
                if argument.hasPrefix("-") {
                    throw CLIError.unknownOption(argument)
                }
                message.append(argument)
            }
            index += 1
        }

        return NiblitNodeCommand(url: url, apiKey: apiKey, timeout: timeout, message: message)
    }

    private static func printUsage() {
        fputs("""
        Usage:
          niblit-node [--url URL] [--api-key KEY] [--timeout SECONDS] [message ...]
        """, stdout)
    }

    private enum CLIError: Error, CustomStringConvertible {
        case missingValue(for: String)
        case invalidValue(String, for: String)
        case unknownOption(String)
        case helpRequested

        var description: String {
            switch self {
            case .missingValue(let option):
                return "Missing value for \(option)"
            case .invalidValue(let value, let option):
                return "Invalid value '\(value)' for \(option)"
            case .unknownOption(let option):
                return "Unknown option \(option)"
            case .helpRequested:
                return "Help requested"
            }
        }
    }

    // ── Run ──────────────────────────────────────────────────────────────────

    public func run() async throws {
        let client  = NiblitClient(baseURL: self.url, apiKey: self.apiKey, timeoutSeconds: self.timeout)
        let adapter = DefaultSwiftRuntimeAdapter(client: client)

        // 1 ── Health check ──────────────────────────────────────────────────
        do {
            let health = try await client.health()
            fputs("[Niblit Swift] Connected to \(url) — status: \(health.status)\n", stderr)
            if let lvl = health.runtimeLevel {
                fputs("[Niblit Swift] Runtime level: \(String(format: "%.4f", lvl))\n", stderr)
            }
        } catch {
            fputs("[Niblit Swift] Could not reach \(url): \(error)\n", stderr)
            fputs("[Niblit Swift] Continuing in offline mode — state will be local only.\n", stderr)
        }

        // 2 ── State: pull from Python core or start fresh ───────────────────
        var envelope: NiblitStateEnvelope
        if let remote = try? await client.pullState() {
            envelope = remote
        } else {
            envelope = .new()
        }
        envelope.lastRuntime = "swift"
        if !envelope.runtimeHistory.contains("swift") {
            envelope.runtimeHistory.append("swift")
        }
        envelope.lastActiveTs = Date().timeIntervalSince1970
        envelope.seal()

        // 3 ── Report Swift environment capabilities ─────────────────────────
        let swiftCaps: [String: JSONValue] = [
            "runtime":            "swift",
            "platform":           .string(envelope.originPlatform),
            "swift_version":      .string(swiftVersionString()),
            "component_name":     "niblit-swift-node",
            "declared_level":     .double(1.0),
            "capabilities":       ["state_portability", "knowledge_exchange", "swift_native"],
            "memory_model":       "ARC",
            "concurrency_model":  "Swift Structured Concurrency (async/await)",
        ]
        _ = try? await client.reportEnvCapabilities(swiftCaps)
        await adapter.reportLevel()

        // 4 ── Single-command or interactive mode ────────────────────────────
        if !self.message.isEmpty {
            try await runSingleCommand(
                message:  self.message.joined(separator: " "),
                client:   client,
                envelope: &envelope
            )
        } else {
            try await runREPL(client: client, envelope: &envelope)
        }

        // 5 ── Graceful shutdown: persist state ──────────────────────────────
        fputs("\n[Niblit Swift] Saving state and disconnecting…\n", stderr)
        envelope.seal()
        _ = try? await client.pushState(envelope)
        fputs("[Niblit Swift] Goodbye.\n", stderr)
    }

    // MARK: – Single-command mode

    private func runSingleCommand(
        message:  String,
        client:   NiblitClient,
        envelope: inout NiblitStateEnvelope
    ) async throws {
        envelope.lastCommand    = message
        envelope.totalCommands += 1
        do {
            let resp = try await client.chat(message: message, sessionId: envelope.sessionId)
            print(resp.response)
            envelope.lastResponseSnippet = String(resp.response.prefix(200))
            envelope.seal()
            _ = try? await client.pushState(envelope)
        } catch {
            fputs("[Niblit Swift] Chat error: \(error)\n", stderr)
            throw NSError(domain: "NiblitSwift", code: 1, userInfo: [NSLocalizedDescriptionKey: "Chat request failed"])
        }
    }

    // MARK: – Interactive REPL

    private func runREPL(
        client:   NiblitClient,
        envelope: inout NiblitStateEnvelope
    ) async throws {
        fputs("[Niblit Swift] Interactive mode. Type 'exit' or Ctrl-D to quit.\n\n", stderr)

        while true {
            print("niblit> ", terminator: "")
            fflush(stdout)

            guard let line = readLine(strippingNewline: true) else { break }  // EOF
            let input = line.trimmingCharacters(in: .whitespaces)
            if input.isEmpty { continue }
            if input == "exit" || input == "quit" { break }

            // Local commands ─────────────────────────────────────────────────
            if input == "state" {
                if let data   = try? JSONEncoder.niblit.encode(envelope),
                   let obj    = try? JSONSerialization.jsonObject(with: data),
                   let pretty = try? JSONSerialization.data(withJSONObject: obj, options: .prettyPrinted),
                   let str    = String(data: pretty, encoding: .utf8) {
                    print(str)
                }
                continue
            }

            if input == "capabilities" {
                let caps: [String: JSONValue] = [
                    "component_name": "niblit-swift-node",
                    "declared_level": .double(1.0),
                    "capabilities":   ["state_portability", "knowledge_exchange", "swift_native"],
                    "runtime":        "swift",
                ]
                _ = try? await client.reportEnvCapabilities(caps)
                continue
            }

            // Remote chat ────────────────────────────────────────────────────
            envelope.lastCommand    = input
            envelope.totalCommands += 1
            envelope.lastActiveTs   = Date().timeIntervalSince1970

            do {
                let resp = try await client.chat(message: input, sessionId: envelope.sessionId)
                print("\n\(resp.response)\n")
                envelope.lastResponseSnippet = String(resp.response.prefix(200))
                envelope.seal()
                // Push every 5 commands to reduce network chatter
                if envelope.totalCommands % 5 == 0 {
                    _ = try? await client.pushState(envelope)
                }
            } catch {
                fputs("[Niblit Swift] Error: \(error)\n", stderr)
            }
        }
    }
}

// MARK: – Swift version helper

private func swiftVersionString() -> String {
#if swift(>=5.10)
    return "5.10+"
#elseif swift(>=5.9)
    return "5.9"
#else
    return "5.x"
#endif
}
