# Niblit TypeScript/Node.js Node

A TypeScript deployment node for Niblit that:
- Connects to the Niblit Python core REST API
- Exchanges cross-environment state (JSON envelope shared with Python and Rust)
- Registers with Niblit's self-improving runtime and auto-adapts to challenges
- Reports Node.js environment capabilities to the Python core

## Quick start

```bash
cd nodes/typescript
npm install
npm run build

# Point at your Niblit instance
NIBLIT_URL=http://localhost:8000 npm start

# Or run a single command
NIBLIT_URL=http://localhost:8000 node dist/index.js "tell me about transformers"

# Development (no build step)
NIBLIT_URL=http://localhost:8000 npx ts-node src/index.ts
```

## Environment variables

| Variable         | Default                  | Description                           |
|------------------|--------------------------|---------------------------------------|
| `NIBLIT_URL`     | `http://localhost:8000`  | URL of the Niblit Python core API     |
| `NIBLIT_API_KEY` | *(none)*                 | Optional API key (`X-Niblit-Key`)     |

## Cross-environment state

The node reads `NiblitStateEnvelope` from the Python core on startup and writes it back on exit.  The envelope is defined in `src/niblit-state.ts` and is byte-for-byte compatible with `modules/env_state.py`.

## Runtime adaptation

When the Niblit self-improving runtime (`modules/niblit_runtime.py`) raises its level, it issues `AdaptationChallenge` objects to registered components.  `DefaultNodeRuntimeAdapter` automatically adopts all required capabilities and reports its new level back, keeping this node in sync.

## API endpoints used

| Method | Path                    | Purpose                                 |
|--------|-------------------------|-----------------------------------------|
| GET    | `/health`               | Health check + runtime level            |
| POST   | `/chat`                 | Send a message to Niblit                |
| GET    | `/api/state`            | Pull current state envelope             |
| POST   | `/api/state`            | Push updated state envelope             |
| POST   | `/api/env/capabilities` | Report Node.js environment capabilities |
