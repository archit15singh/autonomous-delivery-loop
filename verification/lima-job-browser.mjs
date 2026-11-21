import { chromium } from '/playwright/index.mjs';

const [revision, deployment] = process.argv.slice(2);
const origin = 'http://127.0.0.1:8080';
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ serviceWorkers: 'block', viewport: { width: 900, height: 550 } });
const page = await context.newPage();
const errors = [];
let job, failure;
try {
  await context.route('**/*', route => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    if (url.pathname === '/favicon.ico') return route.fulfill({ status: 204 });
    return route.continue();
  });
  page.on('pageerror', error => errors.push(error.message));
  const identity = async () => {
    const result = await context.request.get(origin + '/_revision', { timeout: 3000, maxRedirects: 0 });
    const observed = await result.json();
    if (!result.ok() || observed.revision !== revision || observed.deployment !== deployment) {
      throw new Error('Unexpected browser deployment identity');
    }
  };
  await identity();
  const response = await page.goto(origin + '/jobs/ui', { timeout: 6000 });
  if (!response?.ok() || (await page.getByRole('status').innerText()) !== 'Ready') {
    throw new Error('The browser control did not start ready');
  }
  await page.getByRole('button', { name: 'Run job' }).click({ timeout: 5000 });
  await page.getByText('Completed', { exact: true }).waitFor({ timeout: 10000 });
  job = await page.getByRole('status').getAttribute('data-job');
  if (!/^[0-9a-f]{32}$/.test(job || '')) throw new Error('Missing browser job identity');
  await identity();
} catch (error) {
  failure = error.message;
} finally {
  try {
    const screenshot = (await page.screenshot({ timeout: 4000 })).toString('base64');
    process.stdout.write(JSON.stringify({ revision, deployment, job, errors, failure,
      passed: Boolean(job) && !failure && !errors.length, screenshot }));
  } finally {
    await browser.close();
  }
}
