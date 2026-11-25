'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
function sha(file) { return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex'); }
function writeNewOrMatching(file, data) {
  if (fs.existsSync(file)) {
    if (fs.readFileSync(file, 'utf8') !== data) throw new Error('Existing release binding differs: ' + file);
    return;
  }
  fs.writeFileSync(file, data, {flag:'wx'});
}
function bindRelease(bundle, sourceManifest) {
  if (!path.isAbsolute(bundle) || !path.isAbsolute(sourceManifest)) throw new Error('Absolute paths required');
  const main = path.join(bundle, process.platform === 'win32' ? 'niblit.exe' : 'niblit');
  if (!fs.statSync(main).isFile()) throw new Error('Missing packaged Core');
  const manifest = JSON.parse(fs.readFileSync(sourceManifest, 'utf8'));
  if (manifest.schema_version !== 'niblit-environment/1') throw new Error('Unsupported installation manifest');
  if (!manifest.resources?.configuration?.path || !fs.existsSync(manifest.resources.configuration.path)) throw new Error('Missing approved configuration');
  const config = path.resolve(manifest.resources.configuration.path);
  for (const name of ['ui','cloud_executable']) {
    const spec = manifest.resources[name];
    if (spec?.kind !== 'executable' || spec.base !== 'installation') throw new Error('Missing installation-bound '+name);
    const file = path.resolve(bundle, spec.path);
    if (file !== path.join(bundle, spec.path) || !file.startsWith(path.resolve(bundle)+path.sep) || !fs.statSync(file).isFile()) throw new Error('Invalid '+name+' executable');
    spec.sha256 = sha(file);
  }
  const buildName = path.basename(path.dirname(bundle));
  if (!/^build-[A-Za-z0-9T_.-]+$/.test(buildName)) throw new Error('Versioned build directory required');
  const destination = path.join(path.dirname(sourceManifest), `installation-${buildName}.json`);
  const manifestText = JSON.stringify(manifest,null,2);
  writeNewOrMatching(destination,manifestText);
  const anchor = {manifest:destination,manifest_sha256:sha(destination),configuration:config};
  const anchorPath = path.join(bundle,'release-runtime.json');
  writeNewOrMatching(anchorPath,JSON.stringify(anchor,null,2));
  if (sha(destination) !== anchor.manifest_sha256) throw new Error('Manifest pin verification failed');
  return {anchorPath,destination};
}
if (require.main === module) {
  try { const result=bindRelease(process.argv[2],process.argv[3]); console.log('[niblit-build] Bound release configuration:',result.anchorPath); }
  catch(error) { console.error('[niblit-build] Release binding failed:',error.message); process.exitCode=1; }
}
module.exports = {bindRelease};