'use strict';
// Isolate each build from installed releases and mutable user data.
const path = require('path');
const fs = require('fs');
const { randomUUID } = require('crypto');

function buildPaths(root, env = process.env) {
  const id = 'build-' + new Date().toISOString().replace(/[:.]/g, '-') + '-' + randomUUID().slice(0, 8);
  const dist = path.resolve(env.NIBLIT_BUILD_DIST_DIR || path.join(root, 'dist', 'releases', id));
  const work = path.resolve(env.NIBLIT_BUILD_WORK_DIR || path.join(root, 'build', id));
  const staged = path.resolve(env.NIBLIT_BUILD_STAGING_DIR || path.join(work, '_staged'));
  const final = path.join(dist, 'niblit');
  if (fs.existsSync(final)) throw new Error('Refusing to overwrite an existing niblit bundle. Select a new NIBLIT_BUILD_DIST_DIR.');
  const inside = (candidate, parent) => {
    const relative = path.relative(parent, candidate);
    return relative === '' || (!relative.startsWith('..' + path.sep) && relative !== '..' && !path.isAbsolute(relative));
  };
  if (inside(staged, final) || inside(final, staged) || inside(work, final)) {
    throw new Error('Build staging/work paths must be separate from the final niblit bundle.');
  }
  return { dist, work, staged, final };
}
module.exports = { buildPaths };
