"use strict";
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
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
const readline = __importStar(require("node:readline"));
const os = __importStar(require("node:os"));
const niblit_client_js_1 = require("./niblit-client.js");
const niblit_state_js_1 = require("./niblit-state.js");
const niblit_runtime_adapter_js_1 = require("./niblit-runtime-adapter.js");
const NIBLIT_URL = process.env.NIBLIT_URL ?? "http://localhost:8000/v1";
const NIBLIT_API_KEY = process.env.NIBLIT_API_KEY;
async function main() {
    const client = new niblit_client_js_1.NiblitClient({
        baseUrl: NIBLIT_URL,
        apiKey: NIBLIT_API_KEY,
        timeoutMs: 20000,
    });
    // ── Health check ──────────────────────────────────────────────────────────
    try {
        const health = await client.health();
        console.log(`[Niblit Node] Connected to ${NIBLIT_URL} — status: ${health.status}`);
        if (health.runtime_level != null) {
            console.log(`[Niblit Node] Runtime level: ${health.runtime_level}`);
        }
    }
    catch (err) {
        console.warn(`[Niblit Node] Could not reach ${NIBLIT_URL}: ${err}`);
        console.warn("[Niblit Node] Continuing in offline mode — state will be local only.");
    }
    // ── State: pull from Python core or start fresh ────────────────────────────
    let envelope = (await client.pullState()) ?? (0, niblit_state_js_1.emptyEnvelope)();
    envelope.last_runtime = "node";
    if (!envelope.runtime_history.includes("node")) {
        envelope.runtime_history.push("node");
    }
    envelope.last_active_ts = Date.now() / 1000;
    envelope = await (0, niblit_state_js_1.sealEnvelope)(envelope);
    // ── Runtime adapter: register & adopt capabilities ─────────────────────────
    const adapter = new niblit_runtime_adapter_js_1.DefaultNodeRuntimeAdapter(client, 1.0, "niblit-node");
    await adapter.reportLevel();
    // ── Report Node.js environment capabilities ─────────────────────────────────
    const nodeCaps = {
        node_version: process.version,
        platform: `${process.platform}/${process.arch}`,
        cpu_count: os.cpus().length,
        total_memory_mb: Math.round(os.totalmem() / 1024 / 1024),
        free_memory_mb: Math.round(os.freemem() / 1024 / 1024),
        hostname: os.hostname(),
        uptime_secs: os.uptime(),
    };
    await client.reportEnvCapabilities(nodeCaps);
    // ── Single-command mode ────────────────────────────────────────────────────
    const args = process.argv.slice(2);
    if (args.length > 0) {
        const message = args.join(" ");
        envelope.last_command = message;
        envelope.total_commands += 1;
        try {
            const resp = await client.chat(message, envelope.session_id);
            console.log(resp.response);
            envelope.last_response_snippet = resp.response.slice(0, 200);
            envelope = await (0, niblit_state_js_1.sealEnvelope)(envelope);
            await client.pushState(envelope);
        }
        catch (err) {
            console.error(`[Niblit Node] Chat error: ${err}`);
            process.exit(1);
        }
        return;
    }
    // ── Interactive REPL ───────────────────────────────────────────────────────
    console.log("[Niblit Node] Interactive mode. Type 'exit' or Ctrl-C to quit.\n");
    const rl = readline.createInterface({
        input: process.stdin,
        output: process.stdout,
        prompt: "niblit> ",
    });
    rl.prompt();
    rl.on("line", async (line) => {
        const input = line.trim();
        if (!input) {
            rl.prompt();
            return;
        }
        if (input === "exit" || input === "quit") {
            rl.close();
            return;
        }
        // Local state-dump command
        if (input === "state") {
            console.log(JSON.stringify(envelope, null, 2));
            rl.prompt();
            return;
        }
        envelope.last_command = input;
        envelope.total_commands += 1;
        envelope.last_active_ts = Date.now() / 1000;
        try {
            const resp = await client.chat(input, envelope.session_id);
            console.log("\n" + resp.response + "\n");
            envelope.last_response_snippet = resp.response.slice(0, 200);
            envelope = await (0, niblit_state_js_1.sealEnvelope)(envelope);
            // Push state on every Nth command to avoid hammering the API
            if (envelope.total_commands % 5 === 0) {
                await client.pushState(envelope);
            }
        }
        catch (err) {
            console.error(`[Niblit Node] Error: ${err}`);
        }
        rl.prompt();
    });
    rl.on("close", async () => {
        console.log("\n[Niblit Node] Saving state and disconnecting…");
        envelope = await (0, niblit_state_js_1.sealEnvelope)(envelope);
        await client.pushState(envelope);
        console.log("[Niblit Node] Goodbye.");
        process.exit(0);
    });
}
main().catch((err) => {
    console.error("[Niblit Node] Fatal error:", err);
    process.exit(1);
});
//# sourceMappingURL=index.js.map