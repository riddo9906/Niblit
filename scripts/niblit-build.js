#!/usr/bin/env node
/**
 * niblit-build.js — cross-platform build orchestrator for the complete Niblit runtime.
 *
 * Usage (via package.json scripts):
 *   npm run build          — full desktop-runtime build (Tauri + PyInstaller)
 *   npm run build:ui       — installs Python package + builds niblit-ui (Vite)
 *   npm run tauri:build    — full production build: validates all sibling repos,
 *                            bundles niblit-cloud-server via PyInstaller, builds
 *                            niblit-ui (Tauri), then bundles niblit core via
 *                            PyInstaller producing dist/niblit/niblit.exe.
 *
 * Build steps (tauri:build / --tauri):
 *   1. Validate all required sibling repositories exist.
 *   2. Install the Niblit Python package in editable mode (`pip install -e .`).
 *   3. Build niblit-ui (Tauri) — produces the desktop .exe.
 *   4. Bundle niblit-cloud-server via PyInstaller → dist/_staged/cloud/.
 *   5. Stage the Tauri UI exe into dist/_staged/niblit-ui.exe.
 *   6. Bundle niblit core via PyInstaller (niblit.spec) → dist/niblit/niblit.exe.
 *
 * Build steps (build / no --tauri):
 *   1. Install the Niblit Python package in editable mode.
 *   2. Discover niblit-ui and run `npm run build` (Vite dev server bundle).
 *
 * Environment overrides:
 *   NIBLIT_UI_PATH          — absolute path to the niblit-ui repository
 *   NIBLIT_UI_ROOT          — alias for NIBLIT_UI_PATH
 *   NIBLIT_CLOUD_SERVER_PATH — absolute path to the niblit-cloud-server repository
 *   NIBLIT_LEAN_ALGOS_ROOT  — absolute path to the niblit-lean-algos repository
 *   NIBLIT_CLOUD_PYTHON / NIBLIT_LEAN_PYTHON — service build interpreters
 *   NIBLIT_BUILD_STAGING_DIR / NIBLIT_BUILD_DIST_DIR / NIBLIT_BUILD_WORK_DIR
 *   NIBLIT_SKIP_UI_BUILD    — set to 1 to reuse the existing Tauri executable
 *   PYTHON                  — path to the Python executable (default: python / python3)
 *   NIBLIT_SKIP_PYINSTALLER — set to 1 to skip PyInstaller bundling steps
 */

"use strict";

const { spawnSync } = require("child_process");
const path = require("path");
const fs = require("fs");

const tauriMode = process.argv.includes("--tauri");
const repoRoot = path.resolve(__dirname, "..");
const stagedDir = path.resolve(process.env.NIBLIT_BUILD_STAGING_DIR || path.join(repoRoot, "dist", "_staged"));
const distDir = path.resolve(process.env.NIBLIT_BUILD_DIST_DIR || path.join(repoRoot, "dist"));
const buildWorkDir = path.resolve(process.env.NIBLIT_BUILD_WORK_DIR || path.join(repoRoot, "build"));
const skipUiBuild = process.env.NIBLIT_SKIP_UI_BUILD === "1";

// ── Helpers ───────────────────────────────────────────────────────────────────

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

function quoteArg(value) {
  const text = String(value);
  return `"${text.replace(/"/g, '\\"')}"`;
}

function repositoryPython(repoRoot, overrideName) {
  if (overrideName && process.env[overrideName]) return process.env[overrideName];
  const pythonRelativePath = process.platform === "win32" ? "Scripts/python.exe" : "bin/python";
  for (const envName of ["venv", ".venv"]) {
    const existingPython = path.join(repoRoot, envName, pythonRelativePath);
    if (fs.existsSync(existingPython)) return existingPython;
  }
  const venvRoot = path.join(repoRoot, ".venv");
  const venvPython = path.join(venvRoot, pythonRelativePath);
  console.log(`[niblit-build] Creating isolated build environment: ${venvRoot}`);
  run([pythonBin, "-m", "venv", venvRoot].map(quoteArg).join(" "), { cwd: repoRoot });
  if (!fs.existsSync(venvPython)) {
    console.error(`[niblit-build] Failed to create service virtual environment: ${venvRoot}`);
    process.exit(1);
  }
  return venvPython;
}

function hasPythonModule(python, module, env = process.env) {
  const result = spawnSync(python, ["-c", `import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('${module}') else 1)`], { env });
  return result.status === 0;
}

function applyLeanEnv(env, leanRoot) {
  if (!leanRoot) {
    return env;
  }
  return {
    ...env,
    NIBLIT_LEAN_ALGOS_ROOT: leanRoot,
    NIBLIT_LEAN_ALGOS: leanRoot,
  };
}

// ── Repository discovery ──────────────────────────────────────────────────────
// All find* functions mirror the search order in modules/niblit_ui_launcher.py
// so both the build script and the Python runtime find the same repos.

/**
 * Discover the niblit-ui repository root.
 * Checks (in order): NIBLIT_UI_PATH env, NIBLIT_UI_ROOT env, sibling dirs.
 */
function findUiRoot() {
  const candidates = [
    process.env.NIBLIT_UI_PATH || "",
    process.env.NIBLIT_UI_ROOT || "",
    path.resolve(repoRoot, "..", "niblit-ui"),
    path.resolve(repoRoot, "..", "Niblit-ui"),
    path.resolve(repoRoot, "niblit-ui"),
  ].filter(Boolean);

  for (const candidate of candidates) {
    if (fs.existsSync(path.join(candidate, "package.json"))) {
      return candidate;
    }
  }
  return null;
}

/**
 * Discover the niblit-cloud-server repository root.
 * Checks: NIBLIT_CLOUD_SERVER_PATH env, then sibling dirs.
 * Marker file: app/main.py (FastAPI entry point).
 */
function findCloudServerRoot() {
  const candidates = [
    process.env.NIBLIT_CLOUD_SERVER_PATH || "",
    path.resolve(repoRoot, "..", "niblit-cloud-server"),
    path.resolve(repoRoot, "..", "Niblit-cloud-server"),
  ].filter(Boolean);

  for (const candidate of candidates) {
    if (fs.existsSync(path.join(candidate, "app", "main.py"))) {
      return candidate;
    }
  }
  return null;
}

/**
 * Confirm niblit-lean-algos is present (already a subdirectory inside this repo).
 * Falls back to the sibling directory if the subdirectory is absent.
 */
function findLeanAlgosRoot() {
  const envRoot = process.env.NIBLIT_LEAN_ALGOS_ROOT || process.env.NIBLIT_LEAN_ALGOS || "";
  if (envRoot && fs.existsSync(path.join(envRoot, "niblit_bridge"))) {
    return path.resolve(envRoot);
  }
  const sibling = path.resolve(repoRoot, "..", "niblit-lean-algos");
  if (fs.existsSync(path.join(sibling, "niblit_bridge"))) {
    return sibling;
  }
  const internal = path.join(repoRoot, "niblit-lean-algos");
  if (fs.existsSync(path.join(internal, "niblit_bridge"))) {
    return internal;
  }
  return null;
}

// ── Locate the Tauri-built executable ────────────────────────────────────────

/**
 * After `npm run tauri:build`, Tauri places the unwrapped Windows exe at:
 *   src-tauri/target/release/<binary-name>.exe
 *
 * This function returns that path, or null if not found.
 */
function findTauriExe(uiRoot) {
  const releaseDir = path.join(uiRoot, "src-tauri", "target", "release");
  if (!fs.existsSync(releaseDir)) return null;

  const entries = fs.readdirSync(releaseDir);
  for (const entry of entries) {
    // Skip NSIS installer bundles (they live deeper in bundle/nsis/)
    if (entry.endsWith(".exe") && !entry.endsWith("-setup.exe")) {
      const full = path.join(releaseDir, entry);
      if (fs.statSync(full).isFile()) {
        return full;
      }
    }
  }
  return null;
}

// ── Step helpers ──────────────────────────────────────────────────────────────

const pythonBin = resolvePython();
const npmBin = resolveNpm();
const skipPyInstaller = (process.env.NIBLIT_SKIP_PYINSTALLER || "").trim() === "1";
const label = tauriMode ? "tauri:build" : "build";

console.log(`[niblit-build] ════════════════════════════════════════`);
console.log(`[niblit-build]  Niblit build  (${label})`);
console.log(`[niblit-build] ════════════════════════════════════════`);

// ── Step 0 (tauri mode only): Validate all sibling repositories ───────────────

if (tauriMode) {
  console.log("\n[niblit-build] Step 0 — Validating sibling repositories…");

  const uiRootEarly = findUiRoot();
  if (!uiRootEarly) {
    console.error("[niblit-build] ❌ niblit-ui not found.");
    console.error("[niblit-build]    Set NIBLIT_UI_PATH to the niblit-ui directory,");
    console.error("[niblit-build]    or place niblit-ui as a sibling of this repository.");
    process.exit(1);
  }
  console.log(`[niblit-build]   ✅ niblit-ui          → ${uiRootEarly}`);

  const cloudRootEarly = findCloudServerRoot();
  if (!cloudRootEarly) {
    console.error("[niblit-build] ❌ niblit-cloud-server not found.");
    console.error("[niblit-build]    Set NIBLIT_CLOUD_SERVER_PATH to the niblit-cloud-server directory,");
    console.error("[niblit-build]    or place niblit-cloud-server as a sibling of this repository.");
    process.exit(1);
  }
  console.log(`[niblit-build]   ✅ niblit-cloud-server → ${cloudRootEarly}`);

  const leanRootEarly = findLeanAlgosRoot();
  if (!leanRootEarly) {
    console.error("[niblit-build] ❌ niblit-lean-algos not found.");
    console.error("[niblit-build]    Set NIBLIT_LEAN_ALGOS_ROOT to the niblit-lean-algos directory,");
    console.error("[niblit-build]    or place niblit-lean-algos inside this repository or as a sibling.");
    process.exit(1);
  }
  console.log(`[niblit-build]   ✅ niblit-lean-algos   → ${leanRootEarly}`);

  console.log("[niblit-build] ✅ Repository validation complete.");
}

// ── Step 1: Install the Python package ───────────────────────────────────────

console.log("\n[niblit-build] Step 1 — Installing Python package (pip install -e .)…");
if (tauriMode && hasPythonModule(pythonBin, "PyInstaller")) {
  console.log("[niblit-build] ✅ PyInstaller is already available; skipping editable install to avoid unnecessary dependency changes.");
} else try {
  const editableTarget = tauriMode && !skipPyInstaller ? '".[build]"' : '"."';
  run(`${pythonBin} -m pip install -e ${editableTarget}`, { cwd: repoRoot });
  console.log("[niblit-build] ✅ Python package installed.");
} catch (err) {
  // Non-fatal: package may already be installed or pip unavailable in CI.
  console.warn(`[niblit-build] ⚠️  Python install warning — continuing (${err.message})`);
}

// ── Step 2: Discover niblit-ui ────────────────────────────────────────────────

console.log("\n[niblit-build] Step 2 — Locating niblit-ui…");
const uiRoot = findUiRoot();
const leanRoot = findLeanAlgosRoot();

if (!uiRoot) {
  console.error("[niblit-build] ❌ niblit-ui not found.");
  console.error("[niblit-build]    Set NIBLIT_UI_PATH or NIBLIT_UI_ROOT to the niblit-ui directory,");
  console.error("[niblit-build]    or place niblit-ui as a sibling of this repository.");
  process.exit(1);
}
console.log(`[niblit-build] ✅ Found niblit-ui at: ${uiRoot}`);
if (tauriMode && !leanRoot) {
  console.error(
    "[niblit-build] ❌ niblit-lean-algos not found.\n" +
    "[niblit-build]    The packaged desktop runtime requires the Lean execution layer."
  );
  process.exit(1);
}
if (leanRoot) {
  Object.assign(process.env, applyLeanEnv(process.env, leanRoot));
}

// ── Step 3: Build niblit-ui ───────────────────────────────────────────────────

console.log(`\n[niblit-build] Step 3 — Building niblit-ui (${label})…`);

if (skipUiBuild) {
  console.log("[niblit-build] ⏭ NIBLIT_SKIP_UI_BUILD=1 — using the existing Tauri executable.");
} else {
  const nodeModules = path.join(uiRoot, "node_modules");
  if (!fs.existsSync(nodeModules)) {
    console.log("[niblit-build]    node_modules not found — running npm install first…");
    run(`${npmBin} install`, { cwd: uiRoot });
  }

  const buildEnv = applyLeanEnv({ ...process.env, NIBLIT_CLOUD_AUTOSTART: "1" }, leanRoot);
  const buildCmd = tauriMode ? `${npmBin} run tauri:build` : `${npmBin} run build`;
  run(buildCmd, { cwd: uiRoot, env: buildEnv });
  console.log(`[niblit-build] ✅ niblit-ui ${label} complete.`);
}

// ── Steps 4–6: Full packaging (tauri mode only) ───────────────────────────────

if (!tauriMode) {
  console.log("\n[niblit-build] ✅ Niblit build finished (dev mode — no PyInstaller packaging).");
  process.exit(0);
}

if (skipPyInstaller) {
  console.log("\n[niblit-build] ⏭  NIBLIT_SKIP_PYINSTALLER=1 — skipping PyInstaller steps.");
  console.log("[niblit-build] ✅ Niblit tauri:build finished (no packaging).");
  process.exit(0);
}

// ── Step 4: Bundle niblit-cloud-server via PyInstaller ────────────────────────

console.log("\n[niblit-build] Step 4 — Bundling niblit-cloud-server via PyInstaller…");

const cloudRoot = findCloudServerRoot(); // already validated above
const stagedCloudDir = path.join(stagedDir, "cloud");
const cloudVenvPython = repositoryPython(cloudRoot, "NIBLIT_CLOUD_PYTHON");
const cloudRequirements = path.join(cloudRoot, "requirements.txt");
if (fs.existsSync(cloudRequirements)) {
  run([cloudVenvPython, "-m", "pip", "install", "-r", cloudRequirements].map(quoteArg).join(" "), { cwd: cloudRoot });
}
if (!hasPythonModule(cloudVenvPython, "PyInstaller")) {
  run([cloudVenvPython, "-m", "pip", "install", "pyinstaller>=6.0"].map(quoteArg).join(" "), { cwd: cloudRoot });
}
const cloudPython = cloudVenvPython;
const cloudBuildEnv = { ...process.env };

// Ensure staging directory exists.
fs.mkdirSync(stagedDir, { recursive: true });

// Build: pyinstaller --onedir --name niblit-cloud --distpath <staged>
//        app/main.py
// We pass --noconfirm to overwrite any previous output silently.
const cloudSpec = path.join(cloudRoot, "niblit-cloud-server.spec");
if (!fs.existsSync(cloudSpec)) {
  console.error("[niblit-build] Cloud-server spec not found: " + cloudSpec);
  process.exit(1);
}
const cloudPyinstallerCmd = [
  cloudPython, "-m", "PyInstaller", "--noconfirm",
  "--distpath", stagedDir,
  "--workpath", path.join(buildWorkDir, "_pyinstaller_cloud"),
  cloudSpec,
].map(quoteArg).join(" ");
const nativeLlamaRoot = process.env.NIBLIT_LLAMA_CPP_ROOT || path.join(require("os").homedir(), "llama_migration", "llama.cpp");
if (!cloudBuildEnv.NIBLIT_LLAMA_CPP_ROOT && fs.existsSync(nativeLlamaRoot)) {
  cloudBuildEnv.NIBLIT_LLAMA_CPP_ROOT = nativeLlamaRoot;
}
console.log(`[niblit-build] Native llama.cpp build root: ${cloudBuildEnv.NIBLIT_LLAMA_CPP_ROOT || "not found; optional sidecar omitted"}`);
run(cloudPyinstallerCmd, { cwd: cloudRoot, env: cloudBuildEnv });

const cloudExe = path.join(stagedCloudDir, process.platform === "win32" ? "niblit-cloud.exe" : "niblit-cloud");
if (!fs.existsSync(cloudExe)) {
  console.error(`[niblit-build] ❌ Expected cloud-server bundle not found at: ${cloudExe}`);
  process.exit(1);
}
console.log(`[niblit-build] ✅ Cloud-server bundle: ${stagedCloudDir}`);

// ── Step 5: Stage niblit-lean-algos ──────────────────────────────────────────
// Mirrors how niblit-cloud-server is staged in Step 4.  Installs Python deps
// then copies niblit_bridge/, algorithms/, and lean.json into dist/_staged/lean-algos/
// so that niblit.spec can include them as data files (lean-algos/*).

console.log("\n[niblit-build] Step 5 — Staging niblit-lean-algos…");

const leanRootFinal = findLeanAlgosRoot(); // already validated in Step 0
const stagedLeanDir = path.join(stagedDir, "lean-algos");
fs.mkdirSync(stagedLeanDir, { recursive: true });
const leanPython = repositoryPython(leanRootFinal, "NIBLIT_LEAN_PYTHON");

// Install the Lean runtime dependencies and build its repository-owned spec.
const leanReqsFile = path.join(leanRootFinal, "requirements.txt");
if (fs.existsSync(leanReqsFile)) {
  run([leanPython, "-m", "pip", "install", "-r", leanReqsFile].map(quoteArg).join(" "), { cwd: leanRootFinal });
}
if (!hasPythonModule(leanPython, "PyInstaller")) {
  run([leanPython, "-m", "pip", "install", "pyinstaller>=6.0"].map(quoteArg).join(" "), { cwd: leanRootFinal });
}
const leanSpec = path.join(leanRootFinal, "niblit-lean-algos.spec");
if (!fs.existsSync(leanSpec)) {
  console.error("[niblit-build] Lean-algos spec not found: " + leanSpec);
  process.exit(1);
}
const leanPyinstallerCmd = [
  leanPython, "-m", "PyInstaller", "--noconfirm",
  "--distpath", stagedDir,
  "--workpath", path.join(buildWorkDir, "_pyinstaller_lean"),
  leanSpec,
].map(quoteArg).join(" ");
run(leanPyinstallerCmd, { cwd: leanRootFinal });

const leanExe = path.join(stagedLeanDir, process.platform === "win32" ? "niblit-lean-algos.exe" : "niblit-lean-algos");
if (!fs.existsSync(leanExe)) {
  console.error("[niblit-build] Expected Lean runtime executable not found: " + leanExe);
  process.exit(1);
}
console.log(`[niblit-build] ✅ niblit-lean-algos staged: ${stagedLeanDir}`);

// ── Step 6: Stage the Tauri UI executable ────────────────────────────────────

console.log("\n[niblit-build] Step 6 — Staging Tauri UI executable…");

const tauriExeSrc = findTauriExe(uiRoot);
if (!tauriExeSrc) {
  console.error("[niblit-build] ❌ Tauri .exe not found in src-tauri/target/release/.");
  console.error("[niblit-build]    Ensure the niblit-ui tauri:build step completed successfully.");
  process.exit(1);
}

const tauriExeDest = path.join(stagedDir, "niblit-ui.exe");
fs.copyFileSync(tauriExeSrc, tauriExeDest);
console.log(`[niblit-build] ✅ Staged Tauri exe: ${tauriExeDest}`);

// ── Step 7: Bundle niblit core via PyInstaller ────────────────────────────────

console.log("\n[niblit-build] Step 7 — Bundling Niblit core via PyInstaller (niblit.spec)…");

const specFile = path.join(repoRoot, "niblit.spec");
if (!fs.existsSync(specFile)) {
  console.error(`[niblit-build] ❌ niblit.spec not found at: ${specFile}`);
  process.exit(1);
}

const corePyinstallerCmd = [
  pythonBin,
  "-m", "PyInstaller",
  "--noconfirm",
  "--distpath", distDir,
  "--workpath", path.join(buildWorkDir, "_pyinstaller_core"),
  specFile,
].map(quoteArg).join(" ");

run(corePyinstallerCmd, { cwd: repoRoot });

const finalExe = path.join(
  distDir, "niblit",
  process.platform === "win32" ? "niblit.exe" : "niblit"
);
if (!fs.existsSync(finalExe)) {
  console.error(`[niblit-build] ❌ Expected final executable not found at: ${finalExe}`);
  process.exit(1);
}

for (const relative of [
  "niblit-ui.exe",
  path.join("cloud", process.platform === "win32" ? "niblit-cloud.exe" : "niblit-cloud"),
  path.join("lean-algos", process.platform === "win32" ? "niblit-lean-algos.exe" : "niblit-lean-algos"),
]) {
  const required = path.join(path.dirname(finalExe), relative);
  if (!fs.existsSync(required)) {
    console.error(`[niblit-build] Required packaged component missing: ${required}`);
    process.exit(1);
  }
}

console.log("\n[niblit-build] ════════════════════════════════════════");
console.log("[niblit-build]  ✅ Niblit build complete!");
console.log(`[niblit-build]     Executable : ${finalExe}`);
console.log("[niblit-build]     Run niblit.exe to start the complete system.");
console.log("[niblit-build] ════════════════════════════════════════");
