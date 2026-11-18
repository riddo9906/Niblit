'use strict';
// Isolate each build from installed releases and mutable user data.
const path = require('path');
const fs = require('fs');
const { randomUUID } = require('crypto');
const os = require('os');

function inside(candidate, parent) {
  const relative = path.relative(parent, candidate);
  return relative === '' || (!relative.startsWith('..' + path.sep) && relative !== '..' && !path.isAbsolute(relative));
}

// Resolve existing junctions even when the final output directory does not exist.
function physicalPath(value) {
  let parent = path.resolve(value);
  const tail = [];
  while (!fs.existsSync(parent)) {
    const next = path.dirname(parent);
    if (next === parent) break;
    tail.unshift(path.basename(parent)); parent = next;
  }
  return path.join(fs.existsSync(parent) ? fs.realpathSync(parent) : parent, ...tail);
}

function absolute(value, label) {
  if (!path.isAbsolute(value)) throw new Error(label + ' must be absolute');
  return path.resolve(value);
}

function tauriExecutable(uiRoot, env = process.env) {
  const target = env.CARGO_TARGET_DIR
    ? absolute(env.CARGO_TARGET_DIR, 'CARGO_TARGET_DIR') : path.join(uiRoot, 'src-tauri', 'target');
  const triple = env.CARGO_BUILD_TARGET || '';
  if (triple && !/^[a-zA-Z0-9_-]+$/.test(triple)) throw new Error('Invalid Cargo target triple');
  return path.join(target, triple, 'release', process.platform === 'win32' ? 'niblit-ui.exe' : 'niblit-ui');
}

function buildPaths(root, env = process.env) {
  const id = env.NIBLIT_BUILD_ID || 'build-' + new Date().toISOString().replace(/[:.]/g, '-') + '-' + randomUUID().slice(0, 8);
  if (!/^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}$/.test(id) || id === '..') throw new Error('Invalid build ID');
  const scoped = Boolean(env.NIBLIT_BUILD_ROOT);
  const base = scoped ? absolute(env.NIBLIT_BUILD_ROOT, 'NIBLIT_BUILD_ROOT') : root;
  const dist = absolute(env.NIBLIT_BUILD_DIST_DIR || path.join(base, scoped ? 'releases/candidates' : 'dist/releases', id), 'dist');
  const work = absolute(env.NIBLIT_BUILD_WORK_DIR || path.join(base, scoped ? 'pyinstaller-work' : 'build', id), 'work');
  const staged = absolute(env.NIBLIT_BUILD_STAGING_DIR || (scoped ? path.join(base, 'builds', id, 'staged') : path.join(work, '_staged')), 'staging');
  const final = path.join(dist, 'niblit');
  if (fs.existsSync(final)) throw new Error('Refusing to overwrite an existing niblit bundle. Select a new NIBLIT_BUILD_DIST_DIR.');
  if (inside(staged, final) || inside(final, staged) || inside(work, final) || inside(final, work)) {
    throw new Error('Build staging/work paths must be separate from the final niblit bundle.');
  }
  if (!scoped) return { dist, work, staged, final };
  const cargo = absolute(env.CARGO_TARGET_DIR || path.join(base, 'cargo-target'), 'Cargo target');
  const frontend = absolute(env.NIBLIT_UI_DIST_DIR || path.join(base, 'builds', id, 'ui-dist'), 'frontend');
  const temp = path.join(base, 'temp', id);
  const cache = path.join(base, 'cache');
  const tsInfo = path.join(cache, 'typescript', id);
  const protectedRoots = [root,
    env.NIBLIT_UI_PATH || env.NIBLIT_UI_ROOT || path.join(root, '..', 'niblit-ui'),
    env.NIBLIT_CLOUD_SERVER_PATH || path.join(root, '..', 'Niblit-cloud-server'),
    env.NIBLIT_LEAN_ALGOS_ROOT || env.NIBLIT_LEAN_ALGOS || path.join(root, '..', 'niblit-lean-algos'),
    env.NIBLIT_FREQTRADE_ROOT || path.join(root, '..', 'freqtrade'),
    path.join(os.homedir(), 'llama_migration')];
  for (const name of ['NIBLIT_MEMORY_PATH', 'NIBLIT_MEMORY_LAB_LEDGER', 'NIBLIT_LLAMA_CPP_ROOT']) {
    if (env[name]) protectedRoots.push(absolute(env[name], name));
  }
  for (const output of [dist, work, staged, cargo, frontend, temp, cache, tsInfo]) {
    const physical = physicalPath(output);
    if (protectedRoots.some(p => inside(physical, physicalPath(p)) || inside(physicalPath(p), physical))) {
      throw new Error('Build output overlaps protected source, model or data location');
    }
    if (!inside(physical, physicalPath(base))) throw new Error('Scoped output must remain inside NIBLIT_BUILD_ROOT');
  }
  for (const output of [cargo, frontend, temp, cache]) {
    if (inside(output, final) || inside(final, output)) throw new Error('Cache/output overlaps final bundle');
  }
  return { id, root: base, dist, work, staged, final, cargo, frontend, temp, cache, tsInfo };
}

function buildEnvironment(paths, env = process.env) {
  const result = { ...env, NIBLIT_BUILD_STAGING_DIR: paths.staged,
    NIBLIT_BUILD_DIST_DIR: paths.dist, NIBLIT_BUILD_WORK_DIR: paths.work };
  if (paths.root) Object.assign(result, {
    NIBLIT_BUILD_ROOT: paths.root, NIBLIT_BUILD_ID: paths.id,
    CARGO_TARGET_DIR: paths.cargo, NIBLIT_UI_DIST_DIR: paths.frontend,
    NIBLIT_TS_BUILD_INFO_DIR: paths.tsInfo,
    TEMP: paths.temp, TMP: paths.temp, TMPDIR: paths.temp,
    PIP_CACHE_DIR: path.join(paths.cache, 'pip'), npm_config_cache: path.join(paths.cache, 'npm'),
    PYINSTALLER_CONFIG_DIR: path.join(paths.cache, 'pyinstaller'),
    NODE_COMPILE_CACHE: path.join(paths.cache, 'node'), PYTHONPYCACHEPREFIX: path.join(paths.cache, 'python'),
    CARGO_NET_OFFLINE: 'true', npm_config_offline: 'true', PIP_NO_INDEX: '1', NIBLIT_BUILD_NO_INSTALL: '1',
  });
  return result;
}
module.exports = { buildPaths, buildEnvironment, tauriExecutable };
