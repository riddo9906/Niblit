'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { buildPaths } = require('./build-paths');

test('default builds are unique and do not create or replace a release', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'niblit-build-test-'));
  const first = buildPaths(root, {});
  const second = buildPaths(root, {});
  assert.notEqual(first.dist, second.dist);
  assert.equal(fs.existsSync(first.dist), false);
  assert.notEqual(first.final, path.join(root, 'dist', 'niblit'));
});
test('existing release cannot be silently overwritten', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'niblit-build-test-'));
  fs.mkdirSync(path.join(root, 'niblit'));
  assert.throws(() => buildPaths(root, { NIBLIT_BUILD_DIST_DIR: root }), /Refusing to overwrite/);
});
test('staging cannot be inside final bundle', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'niblit-build-test-'));
  assert.throws(() => buildPaths(root, { NIBLIT_BUILD_DIST_DIR: root,
    NIBLIT_BUILD_STAGING_DIR: path.join(root, 'niblit', 'stage') }), /separate/);
});
