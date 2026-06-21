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

import * as readline from "node:readline";
import * as os from "node:os";

import { NiblitClient } from "./niblit-client.js";
import { emptyEnvelope, sealEnvelope } from "./niblit-state.js";
import { DefaultNodeRuntimeAdapter } from "./niblit-runtime-adapter.js";

const NIBLIT_URL = process.env.NIBLIT_URL ?? "http://localhost:8000/v1";
const NIBLIT_API_KEY = process.env.NIBLIT_API_KEY;

async function main() {
  const client = new NiblitClient({
    baseUrl: NIBLIT_URL,
    apiKey: NIBLIT_API_KEY,
    timeoutMs: 20_000,
  });

  // ── Health check ──────────────────────────────────────────────────────────
  try {
    const health = await client.health();
    console.log(`[Niblit Node] Connected to ${NIBLIT_URL} — status: ${health.status}`);
    if (health.runtime_level != null) {
      console.log(`[Niblit Node] Runtime level: ${health.runtime_level}`);
    }
  } catch (err) {
    console.warn(`[Niblit Node] Could not reach ${NIBLIT_URL}: ${err}`);
    console.warn("[Niblit Node] Continuing in offline mode — state will be local only.");
  }

  // ── State: pull from Python core or start fresh ────────────────────────────
  let envelope = (await client.pullState()) ?? emptyEnvelope();
  envelope.last_runtime = "node";
  if (!envelope.runtime_history.includes("node")) {
    envelope.runtime_history.push("node");
  }
  envelope.last_active_ts = Date.now() / 1000;
  envelope = await sealEnvelope(envelope);

  // ── Runtime adapter: register & adopt capabilities ─────────────────────────
  const adapter = new DefaultNodeRuntimeAdapter(client, 1.0, "niblit-node");
  await adapter.reportLevel();

  // ── Report Node.js environment capabilities ─────────────────────────────────
  const nodeCaps: Record<string, unknown> = {
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
      envelope = await sealEnvelope(envelope);
      await client.pushState(envelope);
    } catch (err) {
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

  rl.on("line", async (line: string) => {
    const input = line.trim();
    if (!input) { rl.prompt(); return; }
    if (input === "exit" || input === "quit") { rl.close(); return; }

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
      envelope = await sealEnvelope(envelope);
      // Push state on every Nth command to avoid hammering the API
      if (envelope.total_commands % 5 === 0) {
        await client.pushState(envelope);
      }
    } catch (err) {
      console.error(`[Niblit Node] Error: ${err}`);
    }

    rl.prompt();
  });

  rl.on("close", async () => {
    console.log("\n[Niblit Node] Saving state and disconnecting…");
    envelope = await sealEnvelope(envelope);
    await client.pushState(envelope);
    console.log("[Niblit Node] Goodbye.");
    process.exit(0);
  });
}

main().catch((err) => {
  console.error("[Niblit Node] Fatal error:", err);
  process.exit(1);
});
