'use strict';

const { fs, path, excluded, stat, filesIn } = require('./common.cjs');

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

// Only root Markdown and docs/ are documentation inputs. Never walk installed
// dependencies, local evidence, generated output or directory links.
function markdownFiles(root, directory = root) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    if (excluded(entry.name) || ['.local', 'build', 'test-results', 'playwright-report', '__pycache__', '.vitepress'].includes(entry.name)) return [];
    const file = path.join(directory, entry.name);
    if (entry.isDirectory() && (directory !== root || entry.name === 'docs')) return markdownFiles(root, file);
    return entry.isFile() && /\.md$/i.test(entry.name) ? [file] : [];
  });
}

function markdownLinks(source) {
  const blank = (text) => text.replace(/[^\n]/g, ' ');
  let fence;
  const prose = source.replace(/<!--[^]*?-->/g, blank).split('\n').map((line) => {
    const marker = line.match(/^ {0,3}(`{3,}|~{3,})/);
    if (fence) {
      if (marker && marker[1][0] === fence[0] && marker[1].length >= fence.length && /^\s*$/.test(line.slice(marker[0].length))) fence = undefined;
      return blank(line);
    }
    if (marker) { fence = marker[1]; return blank(line); }
    return line;
  }).join('\n').replace(/(?<!`)(`+)(?!`)[^]*?(?<!`)\1(?!`)/g, blank);
  // Inline links/images (including angle destinations and one balanced pair of
  // parentheses), plus reference definitions. Anchors are not slug-validated.
  const inline = /(?<!\\)\[(?:\\.|[^\]\\\n])*\]\(\s*(?:<([^>\n]*)>|((?:\\.|[^\\\s()]|\([^()\n]*\))+))(?:\s+(?:"[^"\n]*"|'[^'\n]*'|\([^()\n]*\)))?\s*\)/g;
  const reference = /^ {0,3}\[[^\]\n]+\]:[ \t]*(?:<([^>\n]*)>|(\S+))/gm;
  return [...prose.matchAll(inline), ...prose.matchAll(reference)].map((match) => ({
    target: match[1] ?? match[2], line: prose.slice(0, match.index).split('\n').length,
  }));
}

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
  for (const file of markdownFiles(root)) {
    for (const { target, line } of markdownLinks(fs.readFileSync(file, 'utf8'))) {
      if (!target || /^(?:[a-z][a-z\d+.-]*:|\/\/|#|\?)/i.test(target)) continue;
      const location = `${path.relative(root, file).split(path.sep).join('/')}:${line}`;
      let local;
      try { local = decodeURIComponent(target.split(/[?#]/)[0]).replace(/\\([!"#$%&'()*+,\-./:;<=>?@[\]^_`{|}~\\])/g, '$1'); }
      catch { errors.push(`${location}: 无效的本地链接编码: ${target}`); continue; }
      const resolved = local.startsWith('/') ? path.resolve(root, `.${local}`) : path.resolve(path.dirname(file), local);
      const relative = path.relative(path.resolve(root), resolved);
      if (relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) {
        errors.push(`${location}: 本地链接超出仓库: ${target}`);
      } else if (!stat(resolved)) errors.push(`${location}: 本地链接目标不存在: ${target}`);
    }
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
