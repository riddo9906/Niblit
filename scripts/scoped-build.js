#!/usr/bin/env node
'use strict';
// Build-only entrypoint. Planning is the default and never creates directories.
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');
const { buildPaths, buildEnvironment, tauriExecutable } = require('./build-paths');

function plan(args = process.argv.slice(2), inherited = process.env) {
  const options = { component: 'all' };
  for (let i = 0; i < args.length; i++) {
    const key = args[i];
    if (['--root', '--id', '--component'].includes(key)) {
      if (!args[i + 1] || args[i + 1].startsWith('--')) throw new Error('Missing option value');
      options[key.slice(2)] = args[++i];
    } else if (key === '--execute') options.execute = true;
    else if (key === '--plan') options.planOnly = true;
    else throw new Error('Unknown build option: ' + key);
  }
  if (options.execute && options.planOnly) throw new Error('Choose either planning or execution, never both');
  if (!['all', 'core', 'ui', 'cloud', 'lean', 'freqtrade'].includes(options.component)) throw new Error('Unknown component');
  const root = path.resolve(__dirname, '..');
  const sourceRoots = {
    core: root,
    ui: inherited.NIBLIT_UI_PATH || inherited.NIBLIT_UI_ROOT || path.resolve(root, '../niblit-ui'),
    cloud: inherited.NIBLIT_CLOUD_SERVER_PATH || path.resolve(root, '../Niblit-cloud-server'),
    lean: inherited.NIBLIT_LEAN_ALGOS_ROOT || inherited.NIBLIT_LEAN_ALGOS || path.resolve(root, '../niblit-lean-algos'),
  };
  if (Object.values(sourceRoots).some(p => !path.isAbsolute(p))) throw new Error('Source overrides must be absolute');
  const inputs = { ...inherited, NIBLIT_BUILD_ROOT: options.root || inherited.NIBLIT_BUILD_ROOT };
  if (!inputs.NIBLIT_BUILD_ROOT) throw new Error('Set --root or NIBLIT_BUILD_ROOT explicitly');
  if (options.id) inputs.NIBLIT_BUILD_ID = options.id;
  const paths = buildPaths(root, inputs);
  const env = buildEnvironment(paths, inherited);
  const pythonAt = (directory, names) => names.map(name => path.join(directory, name)).find(p => fs.existsSync(p) && fs.statSync(p).isFile());
  const corePython = inherited.PYTHON || pythonAt(root, ['niblit-env/Scripts/python.exe', '.venv/bin/python']);
  const cloudPython = inherited.NIBLIT_CLOUD_PYTHON || pythonAt(sourceRoots.cloud, ['venv/Scripts/python.exe', '.venv/Scripts/python.exe', '.venv/bin/python']);
  const leanPython = inherited.NIBLIT_LEAN_PYTHON || pythonAt(sourceRoots.lean, ['.venv/Scripts/python.exe', 'niblit-env/Scripts/python.exe', '.venv/bin/python']);
  const freqtradeRoot = inherited.NIBLIT_FREQTRADE_ROOT || path.resolve(root, '../freqtrade');
  const freqtradePython = inherited.NIBLIT_FREQTRADE_PYTHON || pythonAt(freqtradeRoot, ['.venv/Scripts/python.exe', 'venv/Scripts/python.exe', '.venv/bin/python']);
  for (const python of [corePython, cloudPython, leanPython, freqtradePython]) {
    if (python && !path.isAbsolute(python)) throw new Error('Build interpreter overrides must be absolute');
  }
  if (corePython) env.PYTHON = corePython;
  if (cloudPython) env.NIBLIT_CLOUD_PYTHON = cloudPython;
  if (leanPython) env.NIBLIT_LEAN_PYTHON = leanPython;
  if (freqtradePython) env.NIBLIT_FREQTRADE_PYTHON = freqtradePython;
  const pyinstaller = (python, spec, component) => ({ executable: python || null,
    args: ['-m', 'PyInstaller', '--noconfirm', '--distpath', component === 'core' ? paths.dist : paths.staged,
      '--workpath', path.join(paths.work, '_pyinstaller_' + component), spec], cwd: path.dirname(spec) });
  const commands = {
    all: { executable: process.execPath, args: [path.join(root, 'scripts/niblit-build.js'), '--tauri'], cwd: root },
    core: pyinstaller(corePython, path.join(root, 'niblit.spec'), 'core'),
    cloud: pyinstaller(cloudPython, path.join(sourceRoots.cloud, 'niblit-cloud-server.spec'), 'cloud'),
    lean: pyinstaller(leanPython, path.join(sourceRoots.lean, 'niblit-lean-algos.spec'), 'lean'),
    freqtrade: pyinstaller(freqtradePython, path.join(sourceRoots.lean, 'freqtrade_worker.spec'), 'freqtrade'),
    ui: { executable: process.execPath, args: [path.join(sourceRoots.ui, 'scripts/scoped-build.mjs'), '--tauri'], cwd: sourceRoots.ui },
  };
  const selected = commands[options.component];
  const buildKeys = ['NIBLIT_BUILD_ROOT', 'NIBLIT_BUILD_ID', 'NIBLIT_BUILD_STAGING_DIR', 'NIBLIT_BUILD_DIST_DIR',
    'NIBLIT_BUILD_WORK_DIR', 'CARGO_TARGET_DIR', 'NIBLIT_UI_DIST_DIR', 'NIBLIT_TS_BUILD_INFO_DIR',
    'TEMP', 'TMP', 'TMPDIR', 'PIP_CACHE_DIR', 'npm_config_cache', 'PYINSTALLER_CONFIG_DIR', 'NODE_COMPILE_CACHE',
    'PYTHONPYCACHEPREFIX', 'CARGO_NET_OFFLINE', 'npm_config_offline', 'PIP_NO_INDEX', 'NIBLIT_BUILD_NO_INSTALL'];
  return { execute: Boolean(options.execute), component: options.component, paths, sourceRoots, env,
    publicPlan: { schema_version: 'scoped-build/1', component: options.component, paths, sourceRoots,
      environment: Object.fromEntries(buildKeys.map(k => [k, env[k]])), commands,
      tauriExecutable: tauriExecutable(sourceRoots.ui, env),
      dependencyInputs: { corePython, cloudPython, leanPython, freqtradePython },
      preservedRuntimeSettings: ['memory locations', 'model locations', 'credentials', 'service endpoints', 'trading permissions'],
      filesWritten: false, servicesStarted: false, dependenciesInstalled: false, packagedBuildVerified: false }, selected };
}

function execute(configuration) {
  const { paths, selected, env, component } = configuration;
  if (!selected.executable || !fs.existsSync(selected.executable)) throw new Error('Required installed build interpreter unavailable');
  const outputs = component === 'all' ? [paths.staged, paths.frontend, paths.final]
    : component === 'ui' ? [paths.frontend] : [component === 'core' ? paths.final : path.join(paths.staged, component === 'lean' ? 'lean-algos' : component)];
  if (outputs.some(p => fs.existsSync(p) && fs.readdirSync(p).length)) throw new Error('Refusing to replace existing build output; choose a new build ID');
  // No deletes, dependency installs, global environment changes or service calls.
  for (const directory of [paths.work, paths.staged, paths.dist, paths.temp, paths.tsInfo,
    env.PIP_CACHE_DIR, env.npm_config_cache, env.PYINSTALLER_CONFIG_DIR, env.NODE_COMPILE_CACHE]) fs.mkdirSync(directory, { recursive: true });
  const lock = path.join(paths.work, '.scoped-build.lock');
  const handle = fs.openSync(lock, 'wx'); // Existing/uncertain builds require operator reconciliation.
  fs.writeFileSync(handle, JSON.stringify({ pid: process.pid, component, id: paths.id }));
  try {
    const result = spawnSync(selected.executable, selected.args, { cwd: selected.cwd, env, stdio: 'inherit', shell: false });
    if (result.error) throw result.error;
    return result.status ?? 1;
  } finally {
    fs.closeSync(handle);
    // Remove only this invocation's lock, never compiler/user artifacts.
    if (JSON.parse(fs.readFileSync(lock, 'utf8')).pid === process.pid) fs.unlinkSync(lock);
  }
}
if (require.main === module) {
  try {
    const configuration = plan();
    if (configuration.execute) process.exitCode = execute(configuration);
    else console.log(JSON.stringify(configuration.publicPlan, null, 2));
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
module.exports = { plan };
