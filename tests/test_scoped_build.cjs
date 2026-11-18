const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const { spawnSync } = require('node:child_process');
const { buildPaths, buildEnvironment, tauriExecutable } = require('../scripts/build-paths');
const { plan } = require('../scripts/scoped-build');
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'niblit-scoped-config-'));
const source = path.join(temp, 'source'); fs.mkdirSync(source);
const root = path.join(temp, 'outputs');
const settings = { NIBLIT_BUILD_ROOT: root, NIBLIT_BUILD_ID: 'fixture-1' };

test('scoped outputs are separated from sources and candidate', () => {
  const p = buildPaths(source, settings);
  assert.equal(p.work, path.join(root, 'pyinstaller-work', 'fixture-1'));
  assert.equal(p.frontend, path.join(root, 'builds', 'fixture-1', 'ui-dist'));
  assert.equal(p.cargo, path.join(root, 'cargo-target'));
  assert.equal(fs.existsSync(root), false);
});
test('legacy explicit overrides are retained without a scoped root', () => {
  const p = buildPaths(source, { NIBLIT_BUILD_ID: 'legacy', NIBLIT_BUILD_DIST_DIR: path.join(temp, 'legacy-dist') });
  assert.equal(p.dist, path.join(temp, 'legacy-dist'));
});
test('material runtime settings and caller environment remain unchanged', () => {
  const env = { ...settings, NIBLIT_MEMORY_PATH: path.join(temp, 'private', 'memory.json'),
    QDRANT_URL: 'http://127.0.0.1:6333', NIBLIT_EXECUTION_ENABLED: 'false', API_SECRET: 'synthetic-private' };
  const before = JSON.stringify(env); const next = buildEnvironment(buildPaths(source, env), env);
  for (const key of ['NIBLIT_MEMORY_PATH', 'QDRANT_URL', 'NIBLIT_EXECUTION_ENABLED', 'API_SECRET']) assert.equal(next[key], env[key]);
  assert.equal(JSON.stringify(env), before);
  assert.equal(next.NIBLIT_BUILD_NO_INSTALL, '1');
  for (const key of ['TEMP', 'TMP', 'TMPDIR', 'PIP_CACHE_DIR', 'npm_config_cache', 'PYINSTALLER_CONFIG_DIR', 'NODE_COMPILE_CACHE']) assert.ok(next[key].startsWith(root));
});
test('relative roots and traversal build IDs fail closed', () => {
  assert.throws(() => buildPaths(source, { ...settings, NIBLIT_BUILD_ROOT: 'relative' }), /absolute/);
  assert.throws(() => buildPaths(source, { ...settings, NIBLIT_BUILD_ID: '../private' }), /Invalid/);
});
test('protected source and model locations cannot become build output', () => {
  assert.throws(() => buildPaths(source, { ...settings, NIBLIT_BUILD_ROOT: source }), /protected/);
  assert.throws(() => buildPaths(source, { ...settings, NIBLIT_BUILD_DIST_DIR: path.join(os.homedir(), 'llama_migration', 'models') }), /protected/);
});
test('explicit outputs outside the scoped root fail closed', () => {
  assert.throws(() => buildPaths(source, { ...settings, NIBLIT_BUILD_DIST_DIR: path.join(temp, 'elsewhere') }), /inside/);
});
test('candidate and temporary work cannot contain each other', () => {
  assert.throws(() => buildPaths(source, { ...settings, NIBLIT_BUILD_WORK_DIR: path.join(root, 'releases', 'candidates', 'fixture-1', 'niblit', 'work') }), /separate/);
});
test('existing installed candidate is never overwritten', () => {
  const p = buildPaths(source, { ...settings, NIBLIT_BUILD_ID: 'existing' });
  fs.mkdirSync(p.final, { recursive: true });
  assert.throws(() => buildPaths(source, { ...settings, NIBLIT_BUILD_ID: 'existing' }), /overwrite/);
});
test('junction escape is rejected before creating output', () => {
  const junction = path.join(temp, 'source-link');
  fs.symlinkSync(source, junction, process.platform === 'win32' ? 'junction' : 'dir');
  assert.throws(() => buildPaths(source, { ...settings, NIBLIT_BUILD_ROOT: junction }), /protected/);
});
test('Cargo target output and optional triple are resolved explicitly', () => {
  const suffix = process.platform === 'win32' ? 'niblit-ui.exe' : 'niblit-ui';
  assert.equal(tauriExecutable(source, { CARGO_TARGET_DIR: root }), path.join(root, 'release', suffix));
  assert.equal(tauriExecutable(source, { CARGO_TARGET_DIR: root, CARGO_BUILD_TARGET: 'x86_64-pc-windows-msvc' }), path.join(root, 'x86_64-pc-windows-msvc', 'release', suffix));
  assert.throws(() => tauriExecutable(source, { CARGO_TARGET_DIR: root, CARGO_BUILD_TARGET: '../escape' }), /Invalid/);
});
test('public plans contain only build settings, not private environment', () => {
  const p = plan(['--root', root, '--id', 'public', '--component', 'cloud'], { API_SECRET: 'synthetic-private' });
  assert.equal(p.publicPlan.servicesStarted, false);
  assert.equal(p.publicPlan.filesWritten, false);
  assert.ok(!JSON.stringify(p.publicPlan).includes('synthetic-private'));
  assert.ok(p.selected.args.includes('--workpath'));
});
test('existing source aliases work and relative overrides are rejected', () => {
  const p = plan(['--root', root, '--id', 'aliases'], { NIBLIT_UI_ROOT: source });
  assert.equal(p.publicPlan.sourceRoots.ui, source);
  assert.throws(() => plan(['--root', root], { NIBLIT_UI_PATH: 'relative' }), /absolute/);
  assert.throws(() => plan(['--root', root], { PYTHON: 'python' }), /absolute/);
  assert.throws(() => plan(['--root', root, '--plan', '--execute'], {}), /never both/);
});
test('UI plan preserves Tauri arguments and uses D-compatible frontend override', () => {
  const core = path.resolve(__dirname, '..'); const env = buildEnvironment(buildPaths(core, settings), process.env);
  const script = path.resolve(core, '../niblit-ui/scripts/scoped-build.mjs');
  const run = spawnSync(process.execPath, [script, '--tauri', '--plan', '--no-bundle'], { env, encoding: 'utf8' });
  assert.equal(run.status, 0, run.stderr);
  const output = JSON.parse(run.stdout); const args = output.commands[0].args;
  assert.ok(args.includes('--no-bundle'));
  assert.equal(JSON.parse(args[args.indexOf('--config') + 1]).build.frontendDist, env.NIBLIT_UI_DIST_DIR);
});
test('UI type-check plan writes build metadata only to the scoped cache', () => {
  const core = path.resolve(__dirname, '..'); const env = buildEnvironment(buildPaths(core, settings), process.env);
  const run = spawnSync(process.execPath, [path.resolve(core, '../niblit-ui/scripts/scoped-build.mjs'), '--plan'], { env, encoding: 'utf8' });
  assert.equal(run.status, 0, run.stderr);
  const output = JSON.parse(run.stdout);
  assert.ok(output.commands.slice(0, 2).every(c => c.args.includes('--noEmit') && c.args.includes('--tsBuildInfoFile')));
});
