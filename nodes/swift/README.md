# Niblit Swift Node

A Swift deployment node for Niblit that:
- Connects to the Niblit Python core REST API using Foundation's `URLSession`
- Exchanges `NiblitStateEnvelope` across Python / Node.js / Rust / Swift runtimes
- Registers with Niblit's self-improving runtime and auto-adapts to challenges
- Reports Swift/macOS environment capabilities to the Python core
- Provides an interactive REPL and single-command mode

## Quick start

```bash
cd nodes/swift

# Debug build and run (interactive REPL)
NIBLIT_URL=http://localhost:8000 swift run

# Single command (non-interactive)
NIBLIT_URL=http://localhost:8000 swift run niblit-node "tell me about transformers"

# Optimised release build
swift build -c release
NIBLIT_URL=http://localhost:8000 .build/release/niblit-node

# Run tests
swift test
```

## Environment variables

| Variable         | Default                 | Description                          |
|------------------|-------------------------|--------------------------------------|
| `NIBLIT_URL`     | `http://localhost:8000` | URL of the Niblit Python core API    |
| `NIBLIT_API_KEY` | *(none)*                | Optional API key (`X-Niblit-Key`)    |

CLI flags `--url` and `--api-key` override the environment variables.

## Package structure

```
nodes/swift/
├── Package.swift                           # SPM manifest (swift-tools-version 5.9)
├── Sources/
│   └── NiblitNode/
│       ├── JSONValue.swift                 # Recursive, type-safe JSON value enum
│       ├── NiblitState.swift               # NiblitStateEnvelope + CryptoKit checksum
│       ├── NiblitClient.swift              # URLSession async HTTP client
│       ├── NiblitRuntimeAdapter.swift      # Self-adaptive runtime registration
│       └── NiblitNodeCommand.swift         # ArgumentParser entry-point + REPL
└── Tests/
    └── NiblitNodeTests/
        └── NiblitStateTests.swift          # State checksum & JSON round-trip tests
```

## Cross-environment state

The node reads `NiblitStateEnvelope` from the Python core on startup and writes it back on exit.  The struct is defined in `NiblitState.swift` and is byte-for-byte compatible with:

| File | Runtime |
|------|---------|
| `modules/env_state.py` | Python |
| `nodes/typescript/src/niblit-state.ts` | TypeScript / Node.js |
| `nodes/rust/src/niblit_state.rs` | Rust |
| `nodes/swift/Sources/NiblitNode/NiblitState.swift` | Swift |

### Checksum algorithm

All four runtimes use the same algorithm:
1. Serialize the envelope to JSON with **sorted keys**, excluding the `checksum` field.
2. SHA-256 hash the UTF-8 bytes.
3. Hex-encode; keep the first **16 characters**.

## API endpoints used

| Method | Path                    | Purpose                                  |
|--------|-------------------------|------------------------------------------|
| GET    | `/health`               | Health check + runtime level             |
| POST   | `/chat`                 | Send a message to Niblit                 |
| GET    | `/api/state`            | Pull current state envelope              |
| POST   | `/api/state`            | Push updated state envelope              |
| POST   | `/api/env/capabilities` | Report Swift environment capabilities    |

## Interactive REPL commands

| Command        | Effect                                      |
|----------------|---------------------------------------------|
| *(any text)*   | Forward to Niblit `/chat`, print response   |
| `state`        | Pretty-print the current state envelope     |
| `capabilities` | Re-report env capabilities to Python core  |
| `exit` / `quit`| Save state and exit                         |
| Ctrl-D         | EOF — save state and exit                   |

## Runtime adaptation

When the Niblit self-improving runtime raises its level it issues `AdaptationChallenge` objects.  `DefaultSwiftRuntimeAdapter` automatically adopts all required capabilities and reports the new level back, keeping this node in sync with the Python core.

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| [swift-argument-parser](https://github.com/apple/swift-argument-parser) | ≥ 1.3.0 | CLI argument parsing |
| Foundation (system) | — | URLSession HTTP client |
| CryptoKit (system)  | — | SHA-256 envelope checksum |
