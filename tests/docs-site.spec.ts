import { expect, test as base, type Page } from '@playwright/test';

// Every scenario runs without external services, fonts, analytics or search APIs.
const test = base.extend<{ docsGuard: void }>({
  docsGuard: [async ({ context, page }, use) => {
    const errors: string[] = [];
    page.on('console', message => {
      if (message.type() === 'error') errors.push(message.text());
    });
    page.on('pageerror', error => errors.push(error.message));
    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      const loopback = url.hostname === 'localhost'
        || url.hostname === '[::1]'
        || /^127(?:\.\d{1,3}){3}$/.test(url.hostname);
      if (url.protocol === 'data:' || (loopback && /^(?:http|https):$/.test(url.protocol))) {
        await route.continue();
      } else {
        await route.abort('blockedbyclient');
      }
    });
    await use();
    expect(errors, 'The documentation site must not log console or runtime errors').toEqual([]);
  }, { auto: true }],
});

function main(page: Page) {
  return page.getByRole('main');
}

const mechanismPages = ['planning', 'learning', 'documents', 'lessons', 'agent-loop'];

async function expectDocument(page: Page, pathname: string) {
  await expect.poll(() => new URL(page.url()).pathname).toBe(pathname);
  const title = main(page).getByRole('heading', { level: 1 });
  await expect(title).toBeVisible();
  await expect(title).not.toContainText(/404|not found|未找到/i);
}

async function expectNoHorizontalOverflow(page: Page) {
  expect(page.viewportSize()).toEqual({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() =>
    Math.max(document.documentElement.scrollWidth, document.body.scrollWidth)
      - document.documentElement.clientWidth,
  )).toBeLessThanOrEqual(1);
}

test('desktop: home exposes three reading paths and leads to first run and the core overview', async ({ page }) => {
  await page.goto('/');
  await expect(main(page).getByRole('heading', { level: 1, name: /^LearnGraph Lite 文档/ })).toBeVisible();
  for (const name of ['先跑起来', '理解核心机制', '修改与验证功能']) {
    await expect(main(page)).toContainText(name);
  }
  await page.screenshot({ path: test.info().outputPath('home-desktop.png') });
  await page.setViewportSize({ width: 768, height: 1000 });
  await expect(page.locator('.VPSidebar')).not.toBeInViewport();
  await page.screenshot({ path: test.info().outputPath('home-tablet.png') });
  await page.setViewportSize({ width: 1440, height: 1000 });

  await main(page).locator('a[href*="getting-started.html"]').first().click();
  await expectDocument(page, '/developer/getting-started.html');
  await expect(main(page)).toContainText('首次运行');

  await page.goto('/');
  await main(page).locator('a[href="/core/"], a[href="./core/"], a[href="core/"]').first().click();
  await expectDocument(page, '/core/');
  for (const mechanism of mechanismPages) {
    await expect(main(page).locator(`a[href$="/${mechanism}.html"]`).first()).toBeVisible();
  }
});

test('desktop: core navigation opens the overview and the sidebar exposes all four groups', async ({ page }) => {
  await page.goto('/');
  const coreNavigation = page.getByRole('banner').getByRole('link', { name: '核心机制', exact: true })
    .filter({ visible: true });
  await expect(coreNavigation).toHaveAttribute('href', '/core/');
  await coreNavigation.click();
  await expectDocument(page, '/core/');

  for (const name of ['开始使用', '核心机制', '参与开发', '参考手册']) {
    await expect(page.locator('.VPSidebar').getByText(name, { exact: true }).first()).toBeVisible();
  }
});

for (const mechanism of mechanismPages) {
  test(`core mechanism: /core/${mechanism}.html is a readable document`, async ({ page }) => {
    const pathname = `/core/${mechanism}.html`;
    const response = await page.goto(pathname);
    expect(response?.status(), `${pathname} must be a built document, not a missing route`).toBe(200);
    await expectDocument(page, pathname);
    await expect(main(page).locator('p').first()).toBeVisible();
    await expect(main(page).locator('p').first()).not.toBeEmpty();
  });
}

test('core mechanisms and summaries use resolvable fragments and navigate to a flow section', async ({ page }) => {
  const flowLinks: string[] = [];
  for (const mechanism of mechanismPages) {
    await page.goto(`/core/${mechanism}.html`);
    flowLinks.push(...await main(page).locator('a[href]').evaluateAll(links =>
      links.map(link => (link as HTMLAnchorElement).href)
        .filter(href => new URL(href).pathname === '/developer/flows.html' && new URL(href).hash.length > 1),
    ));
  }
  expect(flowLinks.length, 'At least one core mechanism must link to an existing flow section').toBeGreaterThan(0);

  // Validate every cross-page fragment, not just the first flow link: Markdown
  // file checks do not guarantee that punctuation/case matches rendered IDs.
  const fragments = new Set<string>(flowLinks);
  for (const pathname of ['/core/', ...mechanismPages.map(name => `/core/${name}.html`), '/developer/flows.html']) {
    await page.goto(pathname);
    const links = await main(page).locator('a[href]').evaluateAll(anchors =>
      anchors.map(anchor => (anchor as HTMLAnchorElement).href)
        .filter(href => new URL(href).origin === location.origin && new URL(href).hash.length > 1),
    );
    links.forEach(href => fragments.add(href));
  }
  const documents = new Map<string, string>();
  for (const href of fragments) {
    const url = new URL(href);
    if (!documents.has(url.pathname)) {
      const response = await page.request.get(url.pathname);
      expect(response.status(), `${url.pathname} must exist`).toBe(200);
      documents.set(url.pathname, await response.text());
    }
    const id = decodeURIComponent(url.hash.slice(1));
    const exists = await page.evaluate(({ html, id }) =>
      new DOMParser().parseFromString(html, 'text/html').getElementById(id) !== null,
    { html: documents.get(url.pathname)!, id });
    expect(exists, `${url.pathname} must contain fragment #${id}`).toBe(true);
  }

  const destination = new URL(flowLinks[0]);
  expect(destination.origin).toBe(new URL(page.url()).origin);
  await page.goto('/core/planning.html');
  await main(page).locator('a[href*="/developer/flows.html#"]').first().click();
  await expectDocument(page, '/developer/flows.html');
  await expect.poll(() => decodeURIComponent(new URL(page.url()).hash)).toBe(decodeURIComponent(destination.hash));
  const anchor = main(page).locator(`[id=${JSON.stringify(decodeURIComponent(destination.hash.slice(1)))}]`);
  await expect(anchor).toBeVisible();
  await expect(anchor).toBeInViewport();
});

test('local Chinese search: 掌握度 finds a guide and selecting its result navigates there', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /搜索/ }).filter({ visible: true }).click();
  const dialog = page.locator('.VPLocalSearchBox');
  await expect(dialog).toBeVisible();
  await dialog.getByRole('textbox').or(dialog.getByRole('searchbox')).fill('掌握度');

  const result = dialog.locator('a[href*="/developer/"]').first();
  await expect(result).toBeVisible();
  await expect(dialog.locator('a[href*="/histories/"], a[href*="/exec-runs/"], a[href*="/exec-plans/completed/"], a[href*="/exec-plans/active/"]')).toHaveCount(0);
  const href = await result.getAttribute('href');
  expect(href).not.toBeNull();
  const destination = new URL(href!, page.url());
  expect(destination.origin).toBe(new URL(page.url()).origin);
  expect(destination.pathname).toMatch(/^\/developer\/[^/]+\.html$/);
  await result.click();

  await expectDocument(page, destination.pathname);
  await expect(dialog).toBeHidden();
  await expect(main(page)).toContainText('掌握度');
});

test('local Chinese search includes the new core mechanism pages', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /搜索/ }).filter({ visible: true }).click();
  const dialog = page.locator('.VPLocalSearchBox');
  await dialog.getByRole('textbox').or(dialog.getByRole('searchbox')).fill('资料检索');
  const result = dialog.locator('a[href*="/core/documents.html"]').first();
  await expect(result).toBeVisible();
  await result.click();
  await expectDocument(page, '/core/documents.html');
  await expect(dialog).toBeHidden();
});

test('relative Markdown links stay on the docs site and root reference pages are built without /docs/', async ({ page }) => {
  await page.goto('/');
  const link = main(page).locator('a[href*="getting-started.html"]').first();
  await expect(link).toBeVisible();
  const href = await link.getAttribute('href');
  expect(href).not.toBeNull();
  const destination = new URL(href!, page.url());
  expect(destination.origin).toBe(new URL(page.url()).origin);
  expect(destination.pathname).toBe('/developer/getting-started.html');
  await link.click();
  await expectDocument(page, destination.pathname);

  for (const pathname of ['/README.html', '/CONTRIBUTING.html', '/agent-skills.html', '/developer/concepts.html', '/developer/flows.html']) {
    const response = await page.goto(pathname);
    expect(response?.status(), `${pathname} must be a built document, not a missing route`).toBe(200);
    await expectDocument(page, pathname);
  }
  await page.goto('/repository/SECURITY.html');
  await expect(main(page).getByRole('heading', { level: 1 })).toContainText('安全');
  const reporting = await main(page).textContent();
  await page.goto('/SECURITY.html');
  await expect(main(page).getByRole('heading', { level: 1 })).toContainText('安全默认约束');
  expect(await main(page).textContent()).not.toBe(reporting);
});

test('source references remain inline repository paths, not fabricated documentation-page links', async ({ page }) => {
  await page.goto('/developer/architecture.html');
  await expectDocument(page, '/developer/architecture.html');
  await expect(main(page).locator('code').filter({ hasText: 'frontend/src' }).first()).toBeVisible();

  const sourceLinks = await main(page).locator('a[href]').evaluateAll(links =>
    links.map(link => (link as HTMLAnchorElement).href)
      .filter(href => /\/(?:frontend\/src|src\/learngraph_lite)(?:[/.#?]|$)/.test(href)),
  );
  expect(sourceLinks, 'Source paths must not become /frontend/src/...html or /src/...html routes').toEqual([]);
});

test.describe('phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  test('390x844: the mobile menu reaches the core overview and a mechanism without horizontal overflow', async ({ page }) => {
    await page.goto('/');
    await expectDocument(page, '/');
    await expectNoHorizontalOverflow(page);
    await page.screenshot({ path: test.info().outputPath('home-phone.png') });

    const menu = page.getByRole('banner').getByRole('button', { name: /mobile navigation|菜单|导航/i });
    await expect(menu).toHaveAttribute('aria-expanded', 'false');
    await menu.click();
    await expect(menu).toHaveAttribute('aria-expanded', 'true');
    await expectNoHorizontalOverflow(page);
    await page.getByRole('banner').getByRole('link', { name: '核心机制', exact: true })
      .filter({ visible: true }).click();

    await expectDocument(page, '/core/');
    await expect(menu).toHaveAttribute('aria-expanded', 'false');
    await expectNoHorizontalOverflow(page);

    await main(page).locator('a[href$="/planning.html"]').first().click();
    await expectDocument(page, '/core/planning.html');
    await expectNoHorizontalOverflow(page);
    await main(page).locator('pre').first().screenshot({ path: test.info().outputPath('planning-flow-phone.png') });

    for (const mechanism of mechanismPages.slice(1)) {
      await page.goto(`/core/${mechanism}.html`);
      await expectDocument(page, `/core/${mechanism}.html`);
      await expectNoHorizontalOverflow(page);
    }
  });
});
