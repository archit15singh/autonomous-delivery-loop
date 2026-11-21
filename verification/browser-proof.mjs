// Run a primary interaction and an adjacent control on two local deployments.
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const [specPath, output, playwrightPath, executablePath] = process.argv.slice(2);
if (!executablePath) throw new Error('Usage: browser-proof.mjs SPEC OUTPUT PLAYWRIGHT_MODULE BROWSER');
const { chromium } = await import(pathToFileURL(resolve(playwrightPath)));
const spec = JSON.parse(await readFile(specPath, 'utf8'));
const outcomes = {};
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ executablePath });
try {
  for (const phase of ['before', 'after']) {
    const target = spec[phase];
    const origin = new URL(target.origin);
    if (origin.protocol !== 'http:' || !['127.0.0.1', '[::1]'].includes(origin.hostname)) {
      throw new Error('Use an isolated loopback deployment');
    }
    const context = await browser.newContext({ serviceWorkers: 'block' });
    await context.route('**/*', route =>
      new URL(route.request().url()).origin === origin.origin ? route.continue() : route.abort());
    outcomes[phase] = {};
    try {
      const identity = async () => {
        const response = await context.request.get(new URL('/_revision', origin).href, { timeout: 5000, maxRedirects: 0 });
        const { revision, deployment } = await response.json();
        if (!response.ok() || revision !== target.revision || deployment !== target.deployment ||
            !/^[a-f0-9]{40}$/.test(revision)) {
          throw new Error('Browser target identity changed or could not be verified');
        }
      };
      await identity();
      for (const name of ['primary', 'control']) {
        const scenario = spec[name];
        const page = await context.newPage();
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
        page.setDefaultTimeout(5000);
        const url = new URL(scenario.path, origin);
        if (url.origin !== origin.origin) throw new Error('Scenario path escapes its deployment');
        const response = await page.goto(url.href, { timeout: 10000 });
        if (!response?.ok()) throw new Error('Scenario did not load successfully');
        for (const step of scenario.steps) {
          const element = page.locator(step.selector);
          if (step.action === 'click') await element.click();
          else if (step.action === 'fill') await element.fill(step.value);
          else throw new Error('Unknown browser interaction');
        }
        const observed = (await page.locator(scenario.assert.selector).innerText()).trim();
        const screenshot = `${phase}-${name}.png`;
        const bytes = await page.screenshot({ path: join(output, screenshot) });
        const wanted = scenario.assert[phase];
        if (typeof wanted !== 'string') throw new Error('Specify the expected text for both deployments');
        outcomes[phase][name] = { observed, expected: wanted, errors, screenshot,
          sha256: createHash('sha256').update(bytes).digest('hex'), passed: observed === wanted && !errors.length };
        await page.close();
      }
      await identity();
    } finally {
      await context.close();
    }
  }
} finally {
  await browser.close();
}
const passed = Object.values(outcomes).every(scenarios => Object.values(scenarios).every(result => result.passed));
await writeFile(join(output, 'browser.json'), JSON.stringify({ passed, before: spec.before.revision,
  after: spec.after.revision, outcomes }, null, 2) + '\n');
process.exitCode = passed ? 0 : 1;
