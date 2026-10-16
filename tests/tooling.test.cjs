'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const os = require('node:os');
const { spawnSync } = require('node:child_process');
const { fs, path, repoRoot, filesIn, run } = require('../scripts/lib/common.cjs');
const { createProject } = require('../scripts/create-project.cjs');
const { packageRelease } = require('../scripts/release-package.cjs');
const { checkDocs, checkRepo, checkActions } = require('../scripts/lib/checks.cjs');

function temp(t) {
  const parent = fs.realpathSync(os.tmpdir());
  const dir = fs.mkdtempSync(path.join(parent, 'harness-test-'));
  t.after(() => {
    assert.equal(path.dirname(dir), parent);
    assert.ok(path.basename(dir).startsWith('harness-test-'));
    fs.rmSync(dir, { recursive: true, force: true });
  });
  return dir;
}

function write(root, file, content) {
  const target = path.join(root, file);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, content);
}

function fixture(t) {
  const dir = temp(t);
  const source = path.join(dir, '模板 source');
  write(source, 'package.json', '{"name":"starter-template"}\n');
  write(source, 'README.md', '# starter-template\n');
  write(source, 'docs/guide.md', 'starter-template\n');
  write(source, '.editorconfig', 'root = true\n');
  write(source, 'docs/image.bin', Buffer.from([0, 255, 1, 128]));
  return { dir, source };
}

function docsFixture(t, dir = temp(t)) {
  for (const file of [
    'AGENTS.md', 'README.md', 'CONTRIBUTING.md', 'docs/REPO_COLLAB_GUIDE.md',
    'docs/HISTORY_GUIDE.md', 'docs/PLANS_GUIDE.md', 'docs/ARCHITECTURE.md',
    'docs/CICD.md', 'docs/WINDOWS.md', 'docs/PRODUCT_SENSE.md', 'docs/QUALITY_SCORE.md',
    'docs/RELIABILITY.md', 'docs/SECURITY.md', 'docs/SUPPLY_CHAIN_SECURITY.md',
    'docs/design-docs/core-beliefs.md', 'docs/design-docs/index.md',
    'docs/references/README.md', 'docs/exec-plans/templates/execution-plan.md',
    'docs/exec-plans/tech-debt-tracker.md', 'docs/histories/template.md',
    'docs/releases/feature-release-notes.md',
  ]) write(dir, file, file === 'AGENTS.md' ? 'Knowledge lives in docs/.\n' : '# Fixture\n');
  for (const folder of ['docs/exec-plans/active', 'docs/exec-plans/completed']) {
    fs.mkdirSync(path.join(dir, folder), { recursive: true });
  }
  return dir;
}

test('new project supports spaces, Unicode and literal replacement characters', (t) => {
  const { dir, source } = fixture(t);
  const name = "示例 app $& 'test'";
  const result = createProject([name, dir], source);
  assert.equal(fs.readFileSync(path.join(result.target, 'README.md'), 'utf8'), `# ${name}\n`);
  assert.equal(JSON.parse(fs.readFileSync(path.join(result.target, 'package.json'), 'utf8')).name, name);
  assert.deepEqual(fs.readFileSync(path.join(result.target, 'docs/image.bin')), Buffer.from([0, 255, 1, 128]));
  assert.ok(fs.existsSync(path.join(result.target, '.git')));
  assert.ok(fs.existsSync(path.join(result.target, '.editorconfig')));
});

test('--into preserves existing bytes, Git metadata and conflicting paths; is idempotent', (t) => {
  const { dir, source } = fixture(t);
  const target = path.join(dir, 'existing');
  write(target, 'README.md', 'keep starter-template\r\n');
  write(target, 'package.json', '{"name":"existing","type":"module"}\n');
  write(target, '.git', 'gitdir: keep-this-marker\n');
  write(target, 'docs', 'this file blocks the template directory');
  const original = fs.readFileSync(path.join(target, 'README.md'));
  createProject(['--into', target], source);
  assert.deepEqual(fs.readFileSync(path.join(target, 'README.md')), original);
  assert.equal(JSON.parse(fs.readFileSync(path.join(target, 'package.json'))).type, 'module');
  assert.equal(fs.readFileSync(path.join(target, '.git'), 'utf8'), 'gitdir: keep-this-marker\n');
  assert.equal(fs.readFileSync(path.join(target, 'docs'), 'utf8'), 'this file blocks the template directory');
  assert.equal(createProject(['--into'], source, target).copied, 0);
});

test('template-local caches and credentials are excluded at every depth', (t) => {
  const { dir, source } = fixture(t);
  const directories = ['.git', 'node_modules', 'dist', '.tmp', '.venv', 'coverage',
    '.local', 'build', '__pycache__', 'test-results', 'playwright-report', '.aws', '.ssh'];
  const credentials = ['.env', '.env.production', '.env.production.local', '.npmrc', '.pypirc',
    '.netrc', 'settings.local', 'settings.local.json', '.local-browser.log', 'private.pem', 'private.key',
    'client.p12', 'client.pfx', 'module.pyc'];
  for (const name of directories) {
    write(source, `${name}/secret`, 'do not copy');
    write(source, `docs/nested/${name}/secret`, 'do not copy');
  }
  for (const name of credentials) {
    write(source, name, 'do not copy');
    write(source, `docs/nested/${name}`, 'do not copy');
  }
  const { target } = createProject(['clean', dir], source);
  for (const name of [...directories, ...credentials]) {
    if (name !== '.git') assert.equal(fs.existsSync(path.join(target, name)), false, name);
    assert.equal(fs.existsSync(path.join(target, 'docs/nested', name)), false, name);
  }
  assert.equal(fs.existsSync(path.join(target, '.git/secret')), false);
});

test('--into replaces names only in new files and initializes a missing Git repository', (t) => {
  const { dir, source } = fixture(t);
  const target = path.join(dir, 'existing-app');
  write(target, 'README.md', 'keep starter-template');
  createProject(['--into', target], source);
  assert.equal(fs.readFileSync(path.join(target, 'README.md'), 'utf8'), 'keep starter-template');
  assert.equal(fs.readFileSync(path.join(target, 'docs/guide.md'), 'utf8'), 'existing-app\n');
  assert.ok(fs.existsSync(path.join(target, '.git')));
});

test('initialization and packaging share a clean payload without deleting source history', (t) => {
  const { dir, source } = fixture(t);
  const omitted = [
    'private-notes.txt', '.env.production',
    'public/demo.gif', 'docs/nono-profiles/profile.jsonc',
    'docs/histories/2026-09/old.md', 'docs/histories/undated.md',
    'docs/learnings/2026-09/note.md',
    'docs/exec-plans/active/current-task.md', 'docs/exec-plans/completed/old-task.md',
    'docs/exec-runs/old-task/execution-summary.md',
    'docs/code-understanding/01-EventStream-讲解版.html',
  ];
  for (const file of omitted) write(source, file, 'maintenance material');
  const retained = [
    'docs/histories/template.md', 'docs/learnings/README.md',
    'docs/learnings/WRITING_GUIDE.md', 'docs/exec-plans/active/.gitkeep',
    'docs/exec-plans/completed/.gitkeep', 'docs/exec-runs/templates/execution-summary.md',
  ];
  for (const file of retained) write(source, file, 'project skeleton');
  write(source, '.template/README.md', '# starter-template\nClean project\n');
  write(source, '.template/QUALITY_SCORE.md', '# Not evaluated\n');
  write(source, '.template/feature-release-notes.md', '# No releases\n');
  write(source, 'docs/QUALITY_SCORE.md', 'Maintainer score: B');
  write(source, 'docs/releases/feature-release-notes.md', 'Maintainer release history');
  const { target } = createProject(['starter-template', dir], source);
  packageRelease(source);
  const extracted = path.join(dir, 'extracted');
  fs.mkdirSync(extracted);
  run('tar', ['-xzf', path.join(source, 'dist/repo-metadata.tgz'), '-C', extracted]);
  for (const root of [target, extracted]) {
    for (const file of omitted) assert.equal(fs.existsSync(path.join(root, file)), false, file);
    for (const file of retained) assert.ok(fs.existsSync(path.join(root, file)), file);
    assert.equal(fs.existsSync(path.join(root, '.template')), false);
    assert.equal(fs.readFileSync(path.join(root, 'README.md'), 'utf8'), '# starter-template\nClean project\n');
    assert.equal(fs.readFileSync(path.join(root, 'docs/QUALITY_SCORE.md'), 'utf8'), '# Not evaluated\n');
    assert.equal(fs.readFileSync(path.join(root, 'docs/releases/feature-release-notes.md'), 'utf8'), '# No releases\n');
  }
  const snapshot = (root) => Object.fromEntries(filesIn(root).sort().map((file) => [
    path.relative(root, file), fs.readFileSync(file).toString('base64'),
  ]));
  assert.deepEqual(snapshot(target), snapshot(extracted));
  for (const file of omitted) assert.ok(fs.existsSync(path.join(source, file)), file);
});

test('application initialization and source archives retain linked code and knowledge without local artifacts', (t) => {
  const { dir, source } = fixture(t);
  docsFixture(t, source);
  const retained = {
    'package-lock.json': '{"name":"starter-template","lockfileVersion":3}\n',
    'frontend/package.json': '{"name":"frontend","private":true}\n',
    'frontend/src/main.tsx': 'export const application = "LearnGraph";\n',
    'frontend/tests/p0.spec.ts': '// browser test source\n',
    'evals/run.py': '# offline evaluation source\n',
    'evals/cases/offline.json': '{"cases":[]}\n',
    'docs/.vitepress/config.mts': 'export default {};\n',
    'docs/.vitepress/theme/index.ts': 'export default {};\n',
    'evals/reports/offline-report.md': '# Committed offline report\n',
    'docs/histories/2026-10/change.md': '[learning](../../learnings/2026-10/lesson.md)\n',
    'docs/learnings/2026-10/lesson.md': '[plan](../../exec-plans/completed/done.md)\n',
    'docs/exec-plans/active/current.md': '[source](../../../frontend/src/main.tsx)\n',
    'docs/exec-plans/completed/done.md': '[run](../../exec-runs/task/execution-summary.md)\n',
    'docs/exec-runs/task/execution-summary.md': '# Historical evidence\n',
  };
  for (const [file, content] of Object.entries(retained)) write(source, file, content);
  const readme = '# starter-template · LearnGraph\n[frontend](frontend/package.json)\n[lock](package-lock.json)\n[evals](evals/run.py)\n[history](docs/histories/2026-10/change.md)\n';
  write(source, 'README.md', readme);
  write(source, 'docs/ARCHITECTURE.md', '[active plan](exec-plans/active/current.md)\n');
  write(source, '.template/README.md', '# Generic template override must not replace the application\n');
  const omitted = [
    'frontend/node_modules/installed/index.js', 'frontend/dist/assets/app.js',
    'frontend/test-results/run/trace.zip', 'frontend/playwright-report/data/trace.zip',
    'frontend/.local/trace.zip', 'frontend/nested/.local/trace.zip', 'frontend/settings.local.json',
    'frontend/.env', 'frontend/.env.production', 'frontend/.npmrc', 'frontend/private.key',
    'evals/__pycache__/run.cpython-313.pyc', 'evals/nested/cache.pyc',
    'docs/.vitepress/cache/dependency.js', 'docs/.vitepress/.temp/server.js',
    'docs/.vitepress/dist/index.html',
    'docs/learnings/2026-10/.local/private.md', 'docs/histories/2026-10/.env.production',
  ];
  for (const file of omitted) write(source, file, 'private local artifact');
  const { target } = createProject(['starter-template', dir], source);
  packageRelease(source);
  const extracted = path.join(dir, 'application-release');
  fs.mkdirSync(extracted);
  run('tar', ['-xzf', path.join(source, 'dist/repo-metadata.tgz'), '-C', extracted]);
  for (const root of [target, extracted]) {
    checkDocs(root);
    assert.equal(fs.readFileSync(path.join(root, 'README.md'), 'utf8'), readme);
    assert.equal(fs.existsSync(path.join(root, '.template')), false);
    for (const [file, content] of Object.entries(retained)) {
      assert.equal(fs.readFileSync(path.join(root, file), 'utf8'), content, file);
    }
    for (const file of omitted) assert.equal(fs.existsSync(path.join(root, file)), false, file);
  }
  for (const file of omitted) assert.ok(fs.existsSync(path.join(source, file)), file);
});

test('--into document overrides preserve existing project content', (t) => {
  const { dir, source } = fixture(t);
  write(source, '.template/README.md', '# starter-template\nClean\n');
  write(source, '.template/QUALITY_SCORE.md', 'New project');
  write(source, 'docs/QUALITY_SCORE.md', 'Maintainer scores');
  const target = path.join(dir, 'existing');
  write(target, 'README.md', 'My README\r\n');
  write(target, 'docs/QUALITY_SCORE.md', 'My quality data');
  createProject(['--into', target], source);
  assert.equal(fs.readFileSync(path.join(target, 'README.md'), 'utf8'), 'My README\r\n');
  assert.equal(fs.readFileSync(path.join(target, 'docs/QUALITY_SCORE.md'), 'utf8'), 'My quality data');
});

test('document override directories cannot follow a junction outside the template', (t) => {
  const { dir, source } = fixture(t);
  const outside = path.join(dir, 'outside');
  write(outside, 'README.md', 'external contents');
  fs.symlinkSync(outside, path.join(source, '.template'), process.platform === 'win32' ? 'junction' : 'dir');
  assert.throws(() => createProject(['new', dir], source), /\.template 必须是普通目录/);
  assert.equal(fs.existsSync(path.join(dir, 'new')), false);
});

test('invalid names, extra arguments and existing targets fail without overwriting', (t) => {
  const { dir, source } = fixture(t);
  for (const name of ['../escape', '..', '.', 'CON', 'nul.txt', 'bad:name', 'trailing.', '--bad']) {
    assert.throws(() => createProject([name, dir], source));
  }
  assert.throws(() => createProject([], source));
  assert.throws(() => createProject(['x', dir, 'extra'], source));
  assert.throws(() => createProject(['--into', path.join(dir, 'missing')], source));
  write(dir, 'exists', 'preserve');
  assert.throws(() => createProject(['exists', dir], source));
  assert.equal(fs.readFileSync(path.join(dir, 'exists'), 'utf8'), 'preserve');
});

test('self, ancestor and descendant targets are rejected before writes', (t) => {
  const { dir, source } = fixture(t);
  for (const args of [['--into', source], ['--into', dir], ['nested', source]]) {
    assert.throws(() => createProject(args, source), /相互包含/);
  }
  assert.equal(fs.existsSync(path.join(source, 'nested')), false);
});

test('--into does not write through directory junctions', (t) => {
  const { dir, source } = fixture(t);
  const target = path.join(dir, 'existing');
  const outside = path.join(dir, 'outside');
  fs.mkdirSync(target);
  fs.mkdirSync(outside);
  fs.symlinkSync(outside, path.join(target, 'docs'), process.platform === 'win32' ? 'junction' : 'dir');
  createProject(['--into', target], source);
  assert.deepEqual(fs.readdirSync(outside), []);
});

test('source links fail before creating a target', (t) => {
  const { dir, source } = fixture(t);
  const outside = path.join(dir, 'outside');
  fs.mkdirSync(outside);
  fs.symlinkSync(outside, path.join(source, 'docs/linked'), process.platform === 'win32' ? 'junction' : 'dir');
  assert.throws(() => createProject(['new', dir], source), /符号链接/);
  assert.equal(fs.existsSync(path.join(dir, 'new')), false);
});

test('a junction alias cannot bypass template nesting protection', (t) => {
  const { dir, source } = fixture(t);
  const alias = path.join(dir, 'alias');
  fs.symlinkSync(source, alias, process.platform === 'win32' ? 'junction' : 'dir');
  assert.throws(() => createProject(['nested', alias], source), /相互包含/);
  assert.equal(fs.existsSync(path.join(source, 'nested')), false);
});

test('missing git reports a useful failure before creating project files', (t) => {
  const { dir } = fixture(t);
  const result = spawnSync(process.execPath, [path.join(repoRoot, 'scripts/create-project.cjs'), 'new', dir], {
    env: { ...process.env, PATH: '' }, encoding: 'utf8', windowsHide: true,
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /git/);
  assert.equal(fs.existsSync(path.join(dir, 'new')), false);
});

test('action checker reports CRLF/unpinned actions and accepts immutable/local references', (t) => {
  const dir = temp(t);
  const workflow = '.github/workflows/ci.yml';
  write(dir, workflow, `steps:\r\n  - uses: actions/checkout@${'a'.repeat(40)}\r\n  - uses: ./local\r\n  - uses: docker://image@sha256:${'b'.repeat(64)}\r\n`);
  checkActions(dir);
  write(dir, workflow, 'steps:\r\n  - uses: "actions/checkout@main"\r\n');
  assert.throws(() => checkActions(dir), /:2: actions\/checkout@main/);
});

test('document and repository checkers still require their skeletons', (t) => {
  const dir = temp(t);
  assert.throws(() => checkDocs(dir), /缺少必要文件/);
  assert.throws(() => checkRepo(dir), /缺少必要文件/);
  const docs = docsFixture(t);
  checkDocs(docs);
  fs.rmSync(path.join(docs, 'docs/exec-plans/completed'), { recursive: true });
  assert.throws(() => checkDocs(docs), /缺少必要目录: docs\/exec-plans\/completed/);
  fs.mkdirSync(path.join(docs, 'docs/exec-plans/completed'));
  write(docs, 'AGENTS.md', '# Instructions without a knowledge entry\n');
  assert.throws(() => checkDocs(docs), /AGENTS.md 应明确指向 docs\//);
});

test('document links resolve relative paths, encoded names, titles, images and references locally', (t) => {
  const dir = docsFixture(t);
  write(dir, 'docs/指南 (入门).md', '# Guide\n');
  write(dir, 'docs/part(one).md', '# Parentheses\n');
  write(dir, 'docs/image.bin', Buffer.from([0, 255]));
  write(dir, 'src/example.py', '# linked source\n');
  write(dir, 'README.md', [
    '# Links', '[guide](docs/%E6%8C%87%E5%8D%97%20(%E5%85%A5%E9%97%A8).md#section)',
    '[angle](<docs/指南 (入门).md> "title")', '[parentheses](docs/part(one).md)',
    '![image](docs/image.bin)', '[source](/src/example.py?raw=1#example)',
    '[directory](docs/)', '[guide][ref]', '[ref]: <docs/指南 (入门).md> "title"',
  ].join('\n'));
  write(dir, 'docs/nested/guide.md', '[root](../../README.md)\n[source](../../src/example.py)\n');
  checkDocs(dir);
});

test('document links report missing targets with source lines, including reference definitions', (t) => {
  const dir = docsFixture(t);
  write(dir, 'README.md', '# Links\r\n[missing](docs/missing.md#section)\r\n');
  write(dir, 'docs/nested/guide.md', '# Guide\n![image](missing.png)\n[guide][ref]\n[ref]: ../absent.md "title"\n');
  assert.throws(() => checkDocs(dir), (error) => {
    assert.match(error.message, /README\.md:2: 本地链接目标不存在: docs\/missing\.md#section/);
    assert.match(error.message, /docs\/nested\/guide\.md:2: 本地链接目标不存在: missing\.png/);
    assert.match(error.message, /docs\/nested\/guide\.md:4: 本地链接目标不存在: \.\.\/absent\.md/);
    return true;
  });
  write(dir, 'README.md', '[outside](../outside.md)\n[invalid](docs/%broken.md)\n');
  assert.throws(() => checkDocs(dir), (error) => {
    assert.match(error.message, /本地链接超出仓库: \.\.\/outside\.md/);
    assert.match(error.message, /无效的本地链接编码: docs\/%broken\.md/);
    return true;
  });
});

test('document links ignore external URLs, anchors and Markdown code examples', (t) => {
  const dir = docsFixture(t);
  write(dir, 'README.md', [
    '[web](https://unreachable.invalid/missing.md)', '[web](//unreachable.invalid/missing.md)',
    '[email](mailto:missing@unreachable.invalid)', '[anchor](#missing)', '[query](?view=missing)',
    '`[inline](missing.md)` and ``[backtick](also-missing.md)``',
    '\\[escaped](missing.md) and a literal unmatched ](missing.md)',
    '<!-- [comment](missing.md) -->', '```md', '[fenced](missing.md)', '```',
    '~~~~markdown', '[tilde](missing.md)', '~~~', '[still-fenced](missing.md)', '~~~~',
  ].join('\n'));
  checkDocs(dir);
});

test('document scan excludes dependencies, generated directories and directory junctions', (t) => {
  const dir = docsFixture(t);
  for (const folder of ['node_modules', 'dist', '.venv', '.local', 'coverage', 'build', 'test-results', 'playwright-report', '__pycache__', '.vitepress']) {
    write(dir, `${folder}/bad.md`, '[missing](missing.md)\n');
    write(dir, `docs/nested/${folder}/bad.md`, '[missing](missing.md)\n');
  }
  // Source Markdown is not a documentation entry point, but can be a link target.
  write(dir, 'src/example.md', '[missing](missing.md)\n');
  const outside = temp(t);
  write(outside, 'bad.md', '[missing](missing.md)\n');
  fs.symlinkSync(outside, path.join(dir, 'docs/linked'), process.platform === 'win32' ? 'junction' : 'dir');
  checkDocs(dir);
});

test('packaging preserves unrelated dist files and escapes manifest values', (t) => {
  const { source } = fixture(t);
  write(source, 'dist/keep.txt', 'preserve');
  const previous = process.env.GITHUB_REPOSITORY;
  process.env.GITHUB_REPOSITORY = 'owner/"quoted"';
  try { packageRelease(source); } finally {
    if (previous === undefined) delete process.env.GITHUB_REPOSITORY;
    else process.env.GITHUB_REPOSITORY = previous;
  }
  const manifest = JSON.parse(fs.readFileSync(path.join(source, 'dist/release-manifest.json'), 'utf8'));
  assert.equal(manifest.repository, 'owner/"quoted"');
  assert.match(manifest.note, /Source archive only; not an installer or deployable binary/);
  assert.equal(fs.readFileSync(path.join(source, 'dist/keep.txt'), 'utf8'), 'preserve');
  const entries = run('tar', ['-tzf', path.join(source, 'dist/repo-metadata.tgz')]);
  assert.match(entries, /README.md/);
  assert.doesNotMatch(entries, /dist\/|\.git\//);
  packageRelease(source);
  assert.equal(fs.readFileSync(path.join(source, 'dist/keep.txt'), 'utf8'), 'preserve');
});

test('missing tar leaves existing release output unchanged', (t) => {
  const { source } = fixture(t);
  write(source, 'dist/repo-metadata.tgz', 'old archive');
  const result = spawnSync(process.execPath, [
    '-e', 'require(process.argv[1]).packageRelease(process.argv[2])',
    path.join(repoRoot, 'scripts/release-package.cjs'), source,
  ], { env: { ...process.env, PATH: '' }, encoding: 'utf8', windowsHide: true });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /tar/);
  assert.equal(fs.readFileSync(path.join(source, 'dist/repo-metadata.tgz'), 'utf8'), 'old archive');
});

test('packaging refuses a directory occupying an artifact path', (t) => {
  const { source } = fixture(t);
  write(source, 'dist/repo-metadata.tgz/keep', 'preserve');
  assert.throws(() => packageRelease(source), /拒绝覆盖非普通文件/);
  assert.equal(fs.readFileSync(path.join(source, 'dist/repo-metadata.tgz/keep'), 'utf8'), 'preserve');
});

test('packaging rejects a dist junction without touching its destination', (t) => {
  const { dir, source } = fixture(t);
  const outside = path.join(dir, 'outside');
  fs.mkdirSync(outside);
  fs.symlinkSync(outside, path.join(source, 'dist'), process.platform === 'win32' ? 'junction' : 'dir');
  assert.throws(() => packageRelease(source), /dist 必须是普通目录/);
  assert.deepEqual(fs.readdirSync(outside), []);
});

test('real CLI, generated template and extracted release work outside the source cwd', (t) => {
  const dir = temp(t);
  const cli = path.join(repoRoot, 'scripts/create-project.cjs');
  assert.match(run(process.execPath, [cli, '--help'], { cwd: dir }), /用法/);
  run(process.execPath, [cli, 'generated-app', dir], { cwd: dir });
  const generated = path.join(dir, 'generated-app');
  for (const script of ['check-docs', 'check-repo-hygiene', 'check-action-pinning']) {
    run(process.execPath, [path.join(generated, `scripts/${script}.cjs`)], { cwd: dir });
  }
  // CommonJS entries must work when --into preserves an ESM project's package.json.
  const pkg = JSON.parse(fs.readFileSync(path.join(generated, 'package.json'), 'utf8'));
  pkg.type = 'module';
  fs.writeFileSync(path.join(generated, 'package.json'), JSON.stringify(pkg));
  run(process.execPath, [path.join(generated, 'scripts/check-docs.cjs')]);
  run(process.execPath, [path.join(generated, 'scripts/release-package.cjs')]);
  const extracted = path.join(dir, '解包 release');
  fs.mkdirSync(extracted);
  run('tar', ['-xzf', path.join(generated, 'dist/repo-metadata.tgz'), '-C', extracted]);
  checkDocs(extracted);
  checkRepo(extracted);
  checkActions(extracted);
  const applicationFiles = ['package-lock.json', 'docs/index.md', 'docs/.vitepress/config.mts',
    'docs/.vitepress/theme/index.ts', 'docs/.vitepress/theme/style.css', ...['frontend', 'evals'].flatMap((directory) =>
    filesIn(path.join(repoRoot, directory)).map((file) => path.relative(repoRoot, file)))];
  const knowledgeFiles = filesIn(path.join(repoRoot, 'docs')).map((file) => path.relative(repoRoot, file))
    .filter((file) => /^docs\/(?:histories|learnings|exec-plans|exec-runs)\//.test(file.split(path.sep).join('/')));
  const sourceName = JSON.parse(fs.readFileSync(path.join(repoRoot, 'package.json'), 'utf8')).name;
  for (const root of [generated, extracted]) {
    for (const file of [...applicationFiles, ...knowledgeFiles]) {
      const original = fs.readFileSync(path.join(repoRoot, file));
      const expected = /\.(md|json|jsonc|ya?ml)$/.test(file)
        ? Buffer.from(original.toString('utf8').split(sourceName).join(pkg.name)) : original;
      assert.deepEqual(fs.readFileSync(path.join(root, file)), expected, file);
    }
    for (const file of ['frontend/node_modules', 'frontend/dist', 'frontend/test-results',
      'frontend/playwright-report', 'evals/__pycache__', '.local',
      'docs/.vitepress/cache', 'docs/.vitepress/dist', 'docs/.vitepress/.temp']) {
      assert.equal(fs.existsSync(path.join(root, file)), false, file);
    }
  }
  assert.ok(fs.existsSync(path.join(extracted, 'tests/tooling.test.cjs')));
  assert.equal(fs.existsSync(path.join(extracted, 'public')), false);
  assert.equal(fs.existsSync(path.join(extracted, 'docs/nono-profiles')), false);
  assert.equal(fs.existsSync(path.join(extracted, 'scripts/ci.sh')), false);
  assert.equal(fs.readFileSync(path.join(extracted, 'README.md'), 'utf8'),
    fs.readFileSync(path.join(repoRoot, 'README.md'), 'utf8').split(sourceName).join(pkg.name));
  assert.doesNotMatch(fs.readFileSync(path.join(extracted, 'README.md'), 'utf8'), /public\//);
  run(process.execPath, [path.join(extracted, 'scripts/create-project.cjs'), 'from-release', dir]);
  checkDocs(path.join(dir, 'from-release'));
});
