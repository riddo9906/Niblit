#!/usr/bin/env node
/**
 * niblit-dev.js — cross-platform launcher for the complete Niblit runtime.
 *
 * Usage (via package.json scripts):
 *   npm run dev          — starts Niblit Core + Cloud Server + niblit-ui (Vite mode)
 *   npm run tauri:dev    — starts Niblit Core + Cloud Server + niblit-ui (Tauri mode)
 *
 * Both commands do the same thing: spawn `python main.py` with the right
 * environment variables.  main.py already owns the full startup sequence:
 *   Phase 0  — Core, DB, identity, internet
 *   Phase 1  — Memory, Skills, Cognitive, Lean Algorithms, APIs
 *   UI launch — discovers niblit-ui and runs `npm run tauri:dev` (or `npm run dev`)
 *               inside it via modules/niblit_ui_launcher.py
 *
 * Environment variables set by this script:
 *   NIBLIT_CLOUD_AUTOSTART=1   — tells niblit_ui_launcher to start the Cloud Server
 *   NIBLIT_UI_TAURI=1          — (tauri:dev only) forces Tauri mode in niblit_ui_launcher
 *
 * Override the niblit-ui location:
 *   NIBLIT_UI_PATH=/path/to/niblit-ui  npm run dev
 */

"use strict";

const { spawn } = require("child_process");
const path = require("path");

const tauriMode = process.argv.includes("--tauri");
const repoRoot = path.resolve(__dirname, "..");

// Resolve the Python executable: honour PYTHON env var, then try python3,
// then fall back to python (Windows default).
function resolvePython() {
  if (process.env.PYTHON) return process.env.PYTHON;
  return process.platform === "win32" ? "python" : "python3";
}

const pythonBin = resolvePython();

const env = {
  ...process.env,
  NIBLIT_CLOUD_AUTOSTART: "1",
};

if (tauriMode) {
  env.NIBLIT_UI_TAURI = "1";
}

const label = tauriMode ? "tauri:dev" : "dev";
console.log(`[niblit] Starting complete runtime (${label})…`);
console.log(`[niblit] Python: ${pythonBin}`);
console.log(`[niblit] Root:   ${repoRoot}`);
if (tauriMode) {
  console.log("[niblit] Tauri mode: niblit-ui will be launched as a Tauri window");
}
console.log("[niblit] Cloud Server autostart: enabled");

const proc = spawn(pythonBin, ["main.py"], {
  stdio: "inherit",
  env,
  cwd: repoRoot,
  windowsHide: false,
});

// Forward termination signals so the Python process shuts down cleanly.
function forwardSignal(sig) {
  try {
    proc.kill(sig);
  } catch (_) {
    // process may have already exited
  }
}

process.on("SIGINT", () => forwardSignal("SIGINT"));
process.on("SIGTERM", () => forwardSignal("SIGTERM"));

proc.on("error", (err) => {
  console.error(`[niblit] Failed to start Python runtime: ${err.message}`);
  console.error("[niblit] Make sure Python 3 is installed and on your PATH.");
  console.error("[niblit] You can override the executable with:  PYTHON=/path/to/python npm run dev");
  process.exit(1);
});

proc.on("exit", (code, signal) => {
  if (signal) {
    console.log(`[niblit] Runtime terminated by signal ${signal}`);
    process.exit(0);
  }
  process.exit(code ?? 0);
});
