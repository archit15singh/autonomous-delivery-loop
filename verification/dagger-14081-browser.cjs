const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { gzipSync } = require("node:zlib");
const { chromium } = require(process.env.PLAYWRIGHT_PACKAGE);
const mode = process.argv[2];
const origin = "http://127.0.0.1:4173";
const diskDescription = "Keep the temporary directory on the engine's disk";

async function measure(browser, route, expectedDisk) {
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  const assets = new Set();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (response.ok() && url.origin === origin && url.pathname.startsWith("/assets/js/")) {
      assets.add(url.pathname);
    }
  });
  await page.route("**/*", async (request) => {
    if (new URL(request.request().url()).origin === origin) {
      await request.continue();
    } else {
      await request.abort();
    }
  });
  assert.equal((await page.goto(origin + route, { waitUntil: "networkidle" })).status(), 200);
  if (expectedDisk !== undefined) {
    const field = page.locator("article [id=withMountedTemp]");
    await field.waitFor();
    const article = await page.locator("article .theme-doc-markdown").innerText();
    assert.equal(article.includes(diskDescription), expectedDisk, route);
    assert.equal(await page.locator('aside a[href="#withMountedTemp"]').count(), 1, route);
  }
  assert.deepEqual(errors, [], route);
  let total = 0;
  let hasNextSchema = false;
  for (const asset of assets) {
    const script = fs.readFileSync(path.join(process.cwd(), "build", asset));
    hasNextSchema ||= script.includes(diskDescription);
    total += gzipSync(script).length;
  }
  assert.ok(assets.size > 0, route);
  assert.equal(hasNextSchema, mode !== "candidate" || expectedDisk === true, route);
  console.log(JSON.stringify({ route, scripts: assets.size, gzipBytes: total, hasNextSchema }));
  await page.close();
}

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    await measure(browser, "/");
    await measure(browser, "/reference/api/container/", mode === "base");
    await measure(browser, "/next/reference/api/container/", true);
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
