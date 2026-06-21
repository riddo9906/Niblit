"use strict";
/**
 * niblit-runtime-adapter.ts — Niblit Runtime compatibility adapter for Node.js
 *
 * Implements the Niblit runtime adaptation contract:
 * - Registers this Node.js component with the Python NiblitRuntime
 * - Accepts AdaptationChallenges and self-adapts by adopting new capabilities
 * - Reports its current level back so the runtime knows it's keeping up
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.DefaultNodeRuntimeAdapter = void 0;
/**
 * DefaultNodeRuntimeAdapter: automatically adopts all capabilities listed in
 * the challenge's required_capabilities and bumps its own level accordingly.
 */
class DefaultNodeRuntimeAdapter {
    constructor(client, initialLevel = 1.0, name = "niblit-node") {
        this.client = client;
        this.level = initialLevel;
        this.name = name;
        this.capabilities = new Set([
            "state_portability",
            "knowledge_exchange",
        ]);
    }
    async onChallenge(challenge) {
        console.log(`[NiblitRuntimeAdapter] Challenge received: runtime=${challenge.current_runtime_level.toFixed(4)} our_level=${challenge.component_level.toFixed(4)} delta=${challenge.delta.toFixed(4)}`);
        // Adopt every required capability listed in the challenge
        for (const cap of challenge.required_capabilities) {
            this.capabilities.add(cap);
            console.log(`[NiblitRuntimeAdapter] Adopted capability: ${cap}`);
        }
        // Advance our declared level to match the runtime
        this.level = challenge.current_runtime_level;
        console.log(`[NiblitRuntimeAdapter] Self-adapted to level ${this.level.toFixed(4)}`);
        // Report back to the Python core
        await this.reportLevel();
    }
    async reportLevel() {
        try {
            await this.client.reportEnvCapabilities({
                component_name: this.name,
                declared_level: this.level,
                capabilities: Array.from(this.capabilities),
                runtime: "node",
                platform: `${process.platform}/${process.arch}`,
                node_version: process.version,
            });
            return true;
        }
        catch (err) {
            console.warn(`[NiblitRuntimeAdapter] reportLevel failed: ${err}`);
            return false;
        }
    }
}
exports.DefaultNodeRuntimeAdapter = DefaultNodeRuntimeAdapter;
//# sourceMappingURL=niblit-runtime-adapter.js.map