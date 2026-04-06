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

import ArgumentParser
import Foundation

// MARK: – Command

public struct NiblitNodeCommand: AsyncParsableCommand {

    public static var configuration = CommandConfiguration(
        commandName: "niblit-node",
        abstract:    "Niblit Swift deployment node",
        discussion:  """
        Connects to the Niblit Python core REST API, exchanges cross-environment
        state, and either runs a single command or drops into an interactive REPL.

        Usage examples:
          NIBLIT_URL=http://localhost:8000 niblit-node
          NIBLIT_URL=http://localhost:8000 niblit-node "tell me about transformers"
        """,
        version:     "1.0.0"
    )

    public init() {}

    // ── Options ──────────────────────────────────────────────────────────────

    @Option(name: .long, help: "Niblit API base URL.")
    public var url: String = ProcessInfo.processInfo.environment["NIBLIT_URL"]
                             ?? "http://localhost:8000"

    @Option(name: .long, help: "Optional API key (X-Niblit-Key header).")
    public var apiKey: String? = ProcessInfo.processInfo.environment["NIBLIT_API_KEY"]

    @Option(name: .long, help: "HTTP timeout in seconds.")
    public var timeout: Double = 20

    @Argument(help: "Message to send (non-interactive mode). Omit for REPL.")
    public var message: [String] = []

    // ── Run ──────────────────────────────────────────────────────────────────

    public mutating func run() async throws {
        let client  = NiblitClient(baseURL: url, apiKey: apiKey, timeoutSeconds: timeout)
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
        if !message.isEmpty {
            try await runSingleCommand(
                message:  message.joined(separator: " "),
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
            throw ExitCode.failure
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
