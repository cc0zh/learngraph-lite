#!/usr/bin/env node
'use strict';
const { repoRoot, main } = require('./lib/common.cjs');
const { checkDocs } = require('./lib/checks.cjs');
main(() => {
  checkDocs(repoRoot);
  console.log('文档骨架和本地 Markdown 链接检查通过');
});
