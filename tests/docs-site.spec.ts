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

test('desktop: doc-layout home leads to first run and core concepts without browser errors', async ({ page }) => {
  await page.goto('/');
  await expect(main(page).getByRole('heading', { level: 1, name: /^开发者文档/ })).toBeVisible();
  for (const name of ['开发入门', '架构与链路', '参考手册']) {
    await expect(page.getByRole('banner').getByText(name, { exact: true }).filter({ visible: true })).toBeVisible();
  }

  await main(page).locator('a[href*="getting-started.html"]').first().click();
  await expectDocument(page, '/developer/getting-started.html');
  await expect(main(page)).toContainText('首次运行');

  await page.locator('a[href*="/developer/concepts.html"]').filter({ visible: true }).first().click();
  await expectDocument(page, '/developer/concepts.html');
  await expect(main(page).getByRole('heading', { level: 1 })).toContainText('领域概念');
  await expect(main(page)).toContainText('掌握度');
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

test('relative Markdown links stay on the docs site and root reference pages are built without /docs/', async ({ page }) => {
  await page.goto('/');
  const link = main(page).locator('a[href*="concepts.html"]').first();
  await expect(link).toBeVisible();
  const href = await link.getAttribute('href');
  expect(href).not.toBeNull();
  const destination = new URL(href!, page.url());
  expect(destination.origin).toBe(new URL(page.url()).origin);
  expect(destination.pathname).toBe('/developer/concepts.html');
  await link.click();
  await expectDocument(page, destination.pathname);

  for (const pathname of ['/README.html', '/CONTRIBUTING.html']) {
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

  test('390x844: expanding the menu opens a guide without horizontal overflow', async ({ page }) => {
    await page.goto('/');
    await expect(main(page).getByRole('heading', { level: 1, name: /^开发者文档/ })).toBeVisible();
    await expectNoHorizontalOverflow(page);

    const menu = page.getByRole('banner').getByRole('button', { name: /mobile navigation|菜单|导航/i });
    await expect(menu).toHaveAttribute('aria-expanded', 'false');
    await menu.click();
    await expect(menu).toHaveAttribute('aria-expanded', 'true');
    await expectNoHorizontalOverflow(page);
    await page.getByRole('banner').getByRole('link', { name: '开发入门', exact: true })
      .filter({ visible: true }).click();

    await expectDocument(page, '/developer/getting-started.html');
    await expect(menu).toHaveAttribute('aria-expanded', 'false');
    await expectNoHorizontalOverflow(page);
  });
});
