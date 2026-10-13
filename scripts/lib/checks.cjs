'use strict';

const { fs, path, stat, filesIn } = require('./common.cjs');

const requiredDocs = [
  'AGENTS.md', 'README.md', 'CONTRIBUTING.md', 'docs/REPO_COLLAB_GUIDE.md',
  'docs/HISTORY_GUIDE.md', 'docs/PLANS_GUIDE.md', 'docs/ARCHITECTURE.md',
  'docs/CICD.md', 'docs/WINDOWS.md', 'docs/PRODUCT_SENSE.md', 'docs/QUALITY_SCORE.md',
  'docs/RELIABILITY.md', 'docs/SECURITY.md', 'docs/SUPPLY_CHAIN_SECURITY.md',
  'docs/design-docs/core-beliefs.md', 'docs/design-docs/index.md',
  'docs/references/README.md',
  'docs/exec-plans/templates/execution-plan.md', 'docs/exec-plans/tech-debt-tracker.md',
  'docs/histories/template.md', 'docs/releases/feature-release-notes.md',
];

function checkDocs(root) {
  const errors = requiredDocs.filter((file) => !stat(path.join(root, file))?.isFile())
    .map((file) => `缺少必要文件: ${file}`);
  for (const dir of ['docs/exec-plans/active', 'docs/exec-plans/completed', 'docs/histories']) {
    if (!stat(path.join(root, dir))?.isDirectory()) errors.push(`缺少必要目录: ${dir}`);
  }
  const agents = path.join(root, 'AGENTS.md');
  if (stat(agents)?.isFile() && !fs.readFileSync(agents, 'utf8').includes('docs/')) {
    errors.push('AGENTS.md 应明确指向 docs/，说明它是仓库知识的正式来源');
  }
  if (errors.length) throw new Error(errors.join('\n'));
}

function checkRepo(root) {
  const missing = ['.gitignore', '.editorconfig', 'CODEOWNERS']
    .filter((file) => !stat(path.join(root, file))?.isFile());
  if (missing.length) throw new Error(`缺少必要文件: ${missing.join(', ')}`);
}

function checkActions(root) {
  const errors = [];
  const workflows = filesIn(path.join(root, '.github/workflows')).filter((file) => /\.ya?ml$/.test(file));
  if (!workflows.length) throw new Error('没有找到 GitHub Actions workflow');
  for (const file of workflows) {
    fs.readFileSync(file, 'utf8').split(/\r?\n/).forEach((line, index) => {
      const match = line.match(/^\s*(?:-\s*)?uses:\s*["']?([^\s"'#]+)/);
      if (!match) return;
      const reference = match[1];
      if (reference.startsWith('./')) return;
      const pinned = reference.startsWith('docker://')
        ? /@sha256:[0-9a-f]{64}$/.test(reference)
        : /^[^@]+@[0-9a-f]{40}$/.test(reference);
      if (!pinned) errors.push(`${path.relative(root, file)}:${index + 1}: ${reference}`);
    });
  }
  if (errors.length) throw new Error(`发现未固定 SHA 的 GitHub Action 引用:\n${errors.join('\n')}`);
}

module.exports = { checkDocs, checkRepo, checkActions };
