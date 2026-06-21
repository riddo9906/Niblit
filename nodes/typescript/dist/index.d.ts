/**
 * index.ts — Niblit TypeScript/Node.js deployment node entry-point
 *
 * This node:
 * 1. Connects to the Niblit Python core REST API
 * 2. Exchanges cross-environment state (load on start, save on shutdown)
 * 3. Registers with the Niblit self-improving runtime and responds to challenges
 * 4. Provides an interactive CLI that proxies commands to Niblit
 * 5. Reports Node.js environment capabilities back to the Python core
 *
 * Usage:
 *   NIBLIT_URL=http://localhost:8000 node dist/index.js
 *   NIBLIT_URL=http://localhost:8000 node dist/index.js "tell me about yourself"
 */
export {};
//# sourceMappingURL=index.d.ts.map