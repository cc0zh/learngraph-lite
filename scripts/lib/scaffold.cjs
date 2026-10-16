'use strict';

const { path, stat } = require('./common.cjs');

const projectRoots = new Set([
  'AGENTS.md', 'CLAUDE.md', 'README.md', 'CONTRIBUTING.md', 'LICENSE', 'SECURITY.md',
  'CODEOWNERS', '.gitignore', '.gitattributes', '.editorconfig', '.markdownlint.json',
  'package.json', 'package-lock.json', 'pyproject.toml', 'uv.lock',
  'docs', 'scripts', 'src', 'tests', 'frontend', 'evals', '.github',
]);

function applicationPayload(root) {
  const frontend = stat(path.join(root, 'frontend'));
  const manifest = stat(path.join(root, 'frontend/package.json'));
  return Boolean(frontend?.isDirectory() && !frontend.isSymbolicLink()
    && manifest?.isFile() && !manifest.isSymbolicLink());
}

// Generic templates start clean; application docs retain their linked evidence.
function projectPath(relative, application = false) {
  const parts = relative.split('/');
  if (!projectRoots.has(parts[0])) return false;
  if (relative === 'docs/.vitepress/cache' || relative.startsWith('docs/.vitepress/cache/')) return false;
  if (relative === 'docs/nono-profiles' || relative.startsWith('docs/nono-profiles/')) return false;
  if (relative === 'docs/code-understanding/01-EventStream-讲解版.html') return false;
  if (application) return true;
  const retained = {
    'docs/histories': ['template.md'],
    'docs/learnings': ['README.md', 'WRITING_GUIDE.md'],
    'docs/exec-runs': ['README.md', 'templates'],
    'docs/exec-plans/active': ['.gitkeep'],
    'docs/exec-plans/completed': ['.gitkeep'],
  };
  for (const [directory, names] of Object.entries(retained)) {
    if (relative.startsWith(`${directory}/`)) {
      return names.includes(relative.slice(directory.length + 1).split('/')[0]);
    }
  }
  return true;
}

const documentOverrides = {
  'README.md': 'README.md',
  'docs/QUALITY_SCORE.md': 'QUALITY_SCORE.md',
  'docs/releases/feature-release-notes.md': 'feature-release-notes.md',
};

module.exports = { applicationPayload, projectPath, documentOverrides };
