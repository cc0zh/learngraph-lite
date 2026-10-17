import { readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitepress';

const repository = fileURLToPath(new URL('../../', import.meta.url));
const rootDocuments = new Set(['README.md', 'CONTRIBUTING.md', 'AGENTS.md', 'CLAUDE.md', 'SECURITY.md']);
const excluded = readdirSync(repository).filter((name) => name !== 'docs' && !rootDocuments.has(name));

export default defineConfig({
  lang: 'zh-CN',
  title: 'LearnGraph Lite',
  description: '从首次运行、理解核心机制到修改与验证功能',
  // Only official Markdown is a page input. Never scan application source,
  // dependencies, local databases/evidence or generated output for pages.
  srcDir: '../',
  srcExclude: [...excluded.flatMap((name) => [name, `${name}/**`]), '**/.vitepress/**', '**/.local*/**'],
  rewrites: { 'docs/:page*': ':page*', 'SECURITY.md': 'repository/SECURITY.md' },
  ignoreDeadLinks: false,
  appearance: true,
  markdown: {
    // These pages are portable Markdown, not executable Vue/HTML components.
    html: false,
    config(md) {
      const renderLink = md.renderer.rules.link_open!;
      md.renderer.rules.link_open = (tokens, index, options, env, renderer) => {
        const token = tokens[index];
        const href = token.attrGet('href');
        // Resolve against the real source, not its rewritten website location.
        // This keeps the same relative .md links readable in Git and the site.
        if (href && !/^(?:[a-z][a-z\d+.-]*:|\/\/|#|\?)/i.test(href) && /\.md(?:[?#]|$)/i.test(href)) {
          const [, destination, suffix] = href.match(/^([^?#]+)(.*)$/)!;
          const original = path.resolve(path.dirname(env.realPath ?? env.path), decodeURI(destination));
          const relative = path.relative(repository, original).split(path.sep).join('/');
          const page = relative.startsWith('docs/') ? relative.slice(5)
            : relative === 'SECURITY.md' ? 'repository/SECURITY.md' : relative;
          token.attrSet('href', `/${page}${suffix}`);
        }
        return renderLink(tokens, index, options, env, renderer);
      };
    },
  },
  themeConfig: {
    siteTitle: 'LearnGraph Lite / 文档',
    nav: [
      { text: '开始使用', link: '/developer/getting-started' },
      { text: '核心机制', link: '/core/' },
      { text: '参与开发', link: '/developer/architecture' },
      { text: '参考手册', link: '/api-guide' },
    ],
    sidebar: [
      { text: '开始使用', items: [
        { text: '文档总览', link: '/' },
        { text: '安装与首次运行', link: '/developer/getting-started' },
        { text: '运行模式与配置', link: '/developer/configuration' },
        { text: '常见问题与排错', link: '/developer/troubleshooting' },
      ] },
      { text: '核心机制', items: [
        { text: '机制总览', link: '/core/' },
        { text: '目标规划与图谱审核', link: '/core/planning' },
        { text: '节点教学、练习与掌握度', link: '/core/learning' },
        { text: '资料检索与引用', link: '/core/documents' },
        { text: '学习包与交互解释', link: '/core/lessons' },
        { text: 'Agent 执行、取消与恢复', link: '/core/agent-loop' },
        { text: '应用 Agent Skill', link: '/agent-skills' },
      ] },
      { text: '参与开发', collapsed: true, items: [
        { text: '领域概念与状态归属', link: '/developer/concepts' },
        { text: '架构与源码地图', link: '/developer/architecture' },
        { text: '关键业务链路', link: '/developer/flows' },
        { text: '第一次业务改动', link: '/developer/change-guide' },
        { text: '测试与验证', link: '/developer/testing' },
        { text: '贡献指南', link: '/CONTRIBUTING' },
        { text: '编码纪律', link: '/CODING_BEHAVIOR' },
        { text: 'CI/CD', link: '/CICD' },
        { text: '文档维护', link: '/developer/documentation' },
      ] },
      { text: '参考手册', collapsed: true, items: [
        { text: 'API 手册', link: '/api-guide' },
        { text: '架构详细参考', link: '/ARCHITECTURE' },
        { text: '恢复与可靠性', link: '/RELIABILITY' },
        { text: '安全约束', link: '/SECURITY' },
        { text: '质量与验收', link: '/QUALITY_SCORE' },
        { text: '已知技术债', link: '/exec-plans/tech-debt-tracker' },
      ] },
    ],
    outline: { level: [2, 3], label: '本页内容' },
    docFooter: { prev: '上一篇', next: '下一篇' },
    sidebarMenuLabel: '目录',
    darkModeSwitchLabel: '主题',
    lightModeSwitchTitle: '切换到浅色',
    darkModeSwitchTitle: '切换到深色',
    returnToTopLabel: '返回顶部',
    search: {
      provider: 'local',
      options: {
        _render(source, env, md) {
          // Historical evidence stays linkable, but is not the default answer
          // to a newcomer searching for today's behavior.
          if (/^docs\/(?:histories|exec-runs|exec-plans\/(?:active|completed|templates))(?:\/|$)/.test(env.relativePath)) return '';
          const html = md.render(source, env);
          return env.frontmatter?.search === false ? '' : html;
        },
        miniSearch: { options: {
          tokenize: (text) => Array.from(new Intl.Segmenter('zh-CN', { granularity: 'word' }).segment(text), ({ segment }) => segment)
            .filter((segment) => /[\p{L}\p{N}]/u.test(segment)),
        } },
        locales: { root: { translations: {
          button: { buttonText: '搜索文档', buttonAriaLabel: '搜索文档' },
          modal: {
            displayDetails: '显示详细列表', resetButtonTitle: '清空搜索',
            backButtonTitle: '关闭搜索', noResultsText: '没有找到相关内容',
            footer: { selectText: '选择', navigateText: '切换', closeText: '关闭' },
          },
        } } },
      },
    },
  },
});
