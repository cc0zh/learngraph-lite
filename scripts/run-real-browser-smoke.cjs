'use strict';
// Deliberately separate from default CI and fixture browser tests; incurs real API cost.
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const stamp = new Date().toISOString().replace(/[:.]/g, '-');
const database = path.join(root, '.local', `p0-browser-real-${stamp}.sqlite3`);
const report = path.join(root, '.local', `p0-browser-real-${stamp}.json`);
fs.mkdirSync(path.dirname(database), { recursive: true });
if (fs.existsSync(database) || fs.existsSync(report)) throw new Error('Refusing to replace real evidence.');
console.log('Real-model browser acceptance: at most 14 provider calls; isolated local data.');
console.log(`Database: ${path.relative(root, database)}\nReport: ${path.relative(root, report)}`);
const child = spawn(process.execPath, [path.join(root, 'node_modules', '@playwright', 'test', 'cli.js'),
  'test', '--config', 'frontend/playwright.real.config.ts'], {
  cwd: root, stdio: 'inherit', windowsHide: true,
  env: { ...process.env, LEARNGRAPH_REAL_BROWSER_APPROVED: '1', LEARNGRAPH_DATABASE_PATH: database,
    LEARNGRAPH_REAL_BROWSER_REPORT: report },
});
child.on('error', error => { console.error(error.message); process.exitCode = 1; });
child.on('exit', code => { process.exitCode = code || 0; });
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
