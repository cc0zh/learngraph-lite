'use strict';
const { spawn } = require('node:child_process');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const factory = process.argv.includes('--real') ? 'create_real_app' : 'create_business_fixture_app';
const api = spawn('uv', ['run', '--locked', 'uvicorn', `learngraph_lite.bootstrap:${factory}`, '--factory', '--app-dir', 'src', '--host', '127.0.0.1', '--port', '8000', '--timeout-graceful-shutdown', '2'], { cwd: root, stdio: 'inherit', windowsHide: true });
const web = spawn(process.execPath, [path.join(root, 'node_modules/vite/bin/vite.js'), '--host', '127.0.0.1'], { cwd: path.join(root, 'frontend'), stdio: 'inherit', windowsHide: true });
let stopping = false;
function stop(code = 0) { if (stopping) return; stopping = true; api.kill(); web.kill(); process.exitCode = code; }
for (const child of [api, web]) { child.on('error', (err) => { console.error(err.message); stop(1); }); child.on('exit', (code) => stop(code || 0)); }
process.on('SIGINT', () => stop());
process.on('SIGTERM', () => stop());
