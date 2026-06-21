"use strict";
/**
 * niblit-state.ts — Niblit portable state envelope for TypeScript
 *
 * Mirrors the Python NiblitStateEnvelope schema exactly.
 * Any TypeScript component that exchanges state with the Niblit Python core
 * must use this interface.
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
exports.computeChecksum = computeChecksum;
exports.sealEnvelope = sealEnvelope;
exports.verifyEnvelope = verifyEnvelope;
exports.emptyEnvelope = emptyEnvelope;
/**
 * Compute the same 16-char SHA-256 prefix checksum as the Python side.
 * Uses the Web Crypto API (Node 19+) or the node:crypto module.
 */
async function computeChecksum(envelope) {
    const { createHash } = await Promise.resolve().then(() => __importStar(require("node:crypto")));
    const stable = { ...envelope };
    delete stable.checksum;
    const raw = JSON.stringify(stable, Object.keys(stable).sort());
    return createHash("sha256").update(raw).digest("hex").slice(0, 16);
}
async function sealEnvelope(envelope) {
    const sealed = { ...envelope };
    sealed.checksum = await computeChecksum(envelope);
    return sealed;
}
async function verifyEnvelope(envelope) {
    const expected = await computeChecksum(envelope);
    return expected === envelope.checksum;
}
function emptyEnvelope(sessionId) {
    const { randomUUID } = require("node:crypto");
    return {
        session_id: sessionId ?? randomUUID(),
        niblit_version: "1.0",
        origin_runtime: "node",
        origin_platform: `${process.platform}/${process.arch}`,
        last_runtime: "node",
        runtime_history: [],
        total_commands: 0,
        total_facts: 0,
        total_interactions: 0,
        known_topics: [],
        knowledge_summary: "",
        last_command: "",
        last_response_snippet: "",
        last_active_ts: Date.now() / 1000,
        env_capabilities: {},
        extras: {},
        checksum: "",
    };
}
//# sourceMappingURL=niblit-state.js.map