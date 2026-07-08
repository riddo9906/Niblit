#!/usr/bin/env node
/**
 * niblit-build.js — cross-platform build orchestrator for the complete Niblit runtime.
 *
 * Usage (via package.json scripts):
 *   npm run build          — installs Python package + builds niblit-ui (Vite)
 *   npm run tauri:build    — installs Python package + builds niblit-ui (Tauri desktop executable)
 *
 * Build steps:
 *   1. Install the Niblit Python package in editable mode (`pip install -e .`).
 *   2. Discover niblit-ui (uses the same search order as modules/niblit_ui_launcher.py).
 *   3. Install niblit-ui npm dependencies if node_modules is missing.
 *   4. Run `npm run build` or `npm run tauri:build` inside niblit-ui.
 *
 * Override the niblit-ui location:
 *   NIBLIT_UI_PATH=/path/to/niblit-ui  npm run build
 */

"use strict";

const { execSync, spawnSync } = require("child_process");
const path = require("path");
const fs = require("fs");

const tauriMode = process.argv.includes("--tauri");
const repoRoot = path.resolve(__dirname, "..");

// ── Helpers ──────────────────────────────────────────────────────────────────

function run(cmd, opts = {}) {
  console.log(`[niblit-build] $ ${cmd}`);
  const result = spawnSync(cmd, {
    shell: true,
    stdio: "inherit",
    ...opts,
  });
  if (result.status !== 0) {
    const exitCode = result.status ?? 1;
    console.error(`[niblit-build] Command failed with exit code ${exitCode}: ${cmd}`);
    process.exit(exitCode);
  }
}

function resolvePython() {
  if (process.env.PYTHON) return process.env.PYTHON;
  return process.platform === "win32" ? "python" : "python3";
}

function resolveNpm() {
  return process.platform === "win32" ? "npm.cmd" : "npm";
}

// ── Discover niblit-ui ───────────────────────────────────────────────────────
// Mirrors the search order in modules/niblit_ui_launcher.find_niblit_ui_root().

function findUiRoot() {
  const candidates = [
    process.env.NIBLIT_UI_PATH || "",
    process.env.NIBLIT_UI_ROOT || "",
    path.resolve(repoRoot, "..", "niblit-ui"),
    path.resolve(repoRoot, "..", "Niblit-ui"),
    path.resolve(repoRoot, "niblit-ui"),
  ].filter(Boolean);

  for (const candidate of candidates) {
    const pkg = path.join(candidate, "package.json");
    if (fs.existsSync(pkg)) {
      return candidate;
    }
  }
  return null;
}

// ── Step 1: Python package ───────────────────────────────────────────────────

const pythonBin = resolvePython();
const npmBin = resolveNpm();
const label = tauriMode ? "tauri:build" : "build";

console.log(`[niblit-build] Starting Niblit build (${label})…`);

console.log("[niblit-build] Step 1/3 — Installing Python package…");
try {
  run(`${pythonBin} -m pip install -e .`, { cwd: repoRoot });
  console.log("[niblit-build] ✅ Python package installed");
} catch (err) {
  // Non-fatal: package may already be installed or pip unavailable in CI.
  console.warn(`[niblit-build] ⚠️  Python install warning — continuing (${err.message})`);
}

// ── Step 2: Discover niblit-ui ───────────────────────────────────────────────

console.log("[niblit-build] Step 2/3 — Locating niblit-ui…");
const uiRoot = findUiRoot();

if (!uiRoot) {
  console.error("[niblit-build] ❌ niblit-ui not found.");
  console.error("[niblit-build]    Set NIBLIT_UI_PATH or NIBLIT_UI_ROOT to the niblit-ui directory,");
  console.error("[niblit-build]    or place niblit-ui as a sibling of this repository.");
  process.exit(1);
}

console.log(`[niblit-build] ✅ Found niblit-ui at: ${uiRoot}`);

// ── Step 3: Build niblit-ui ──────────────────────────────────────────────────

console.log(`[niblit-build] Step 3/3 — Building niblit-ui (${label})…`);

const nodeModules = path.join(uiRoot, "node_modules");
if (!fs.existsSync(nodeModules)) {
  console.log("[niblit-build]    node_modules not found — running npm install first…");
  run(`${npmBin} install`, { cwd: uiRoot });
}

const buildEnv = {
  ...process.env,
  NIBLIT_CLOUD_AUTOSTART: "1",
};

const buildCmd = tauriMode
  ? `${npmBin} run tauri:build`
  : `${npmBin} run build`;

run(buildCmd, { cwd: uiRoot, env: buildEnv });
console.log(`[niblit-build] ✅ niblit-ui ${label} complete`);

console.log("[niblit-build] ✅ Niblit build finished.");
