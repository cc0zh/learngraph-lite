#!/usr/bin/env node
'use strict';

const { path, repoRoot, filesIn, run, main } = require('./lib/common.cjs');
const { checkDocs, checkRepo, checkActions } = require('./lib/checks.cjs');

main(() => {
  checkDocs(repoRoot);
  checkRepo(repoRoot);
  checkActions(repoRoot);
  for (const dir of ['scripts', 'tests']) {
    for (const file of filesIn(path.join(repoRoot, dir)).filter((file) => file.endsWith('.cjs'))) {
      run(process.execPath, ['--check', file]);
    }
  }
  run('uv', ['run', '--locked', 'python', 'scripts/check-python-boundaries.py'], { stdio: 'inherit' });
  run('uv', ['run', '--locked', 'python', 'scripts/run-python-tests.py'], { stdio: 'inherit' });
  run(process.execPath, ['--test', 'tests/tooling.test.cjs'], { stdio: 'inherit' });
  console.log('基础 CI 检查通过');
});
