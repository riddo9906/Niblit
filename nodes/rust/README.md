# Niblit Rust Node

A Rust deployment node for Niblit that:
- Connects to the Niblit Python core REST API
- Exchanges cross-environment state (JSON envelope shared with Python and TypeScript)
- Registers with Niblit's self-improving runtime and auto-adapts to challenges
- Reports Rust/OS environment capabilities to the Python core

## Quick start

```bash
cd nodes/rust

# Debug build and run (interactive)
NIBLIT_URL=http://localhost:8000 cargo run

# Single command
NIBLIT_URL=http://localhost:8000 cargo run -- "tell me about transformers"

# Release build
cargo build --release
NIBLIT_URL=http://localhost:8000 ./target/release/niblit-node
```

## Environment variables

| Variable         | Default                  | Description                           |
|------------------|--------------------------|---------------------------------------|
| `NIBLIT_URL`     | `http://localhost:8000`  | URL of the Niblit Python core API     |
| `NIBLIT_API_KEY` | *(none)*                 | Optional API key (`X-Niblit-Key`)     |

## Cross-environment state

The node reads `NiblitStateEnvelope` from the Python core on startup and writes it back on exit.  The struct is defined in `src/niblit_state.rs` and is byte-for-byte compatible with `modules/env_state.py` and `nodes/typescript/src/niblit-state.ts`.

## API endpoints used

| Method | Path                    | Purpose                                 |
|--------|-------------------------|-----------------------------------------|
| GET    | `/health`               | Health check + runtime level            |
| POST   | `/chat`                 | Send a message to Niblit                |
| GET    | `/api/state`            | Pull current state envelope             |
| POST   | `/api/state`            | Push updated state envelope             |
| POST   | `/api/env/capabilities` | Report Rust environment capabilities    |
