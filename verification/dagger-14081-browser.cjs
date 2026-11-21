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
  const assets = new Map();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (response.ok() && url.origin === origin && url.pathname.startsWith("/assets/js/")) {
      const kinds = assets.get(url.pathname) ?? new Set();
      kinds.add(response.request().resourceType());
      assets.set(url.pathname, kinds);
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
  let scriptBytes = 0;
  const schemaAssets = [];
  for (const [asset, kinds] of assets) {
    const script = fs.readFileSync(path.join(process.cwd(), "build", asset));
    const bytes = gzipSync(script).length;
    if (asset.includes("dagger-api-schema") || script.includes("temporary directory on the engine")) {
      schemaAssets.push({ asset, kinds: [...kinds], bytes });
    }
    total += bytes;
    if (kinds.has("script")) scriptBytes += bytes;
  }
  console.log(JSON.stringify({ route, scripts: assets.size, gzipBytes: total, scriptBytes, schemaAssets }));
  assert.ok(assets.size > 0, route);
  if (mode === "candidate") {
    const loadedSchemas = schemaAssets.filter(({ kinds }) => kinds.includes("script"));
    const expectedVersion = expectedDisk === undefined ? null : expectedDisk ? "current" : "1.0-beta";
    if (expectedVersion === null) {
      assert.deepEqual(loadedSchemas, [], route);
    } else {
      assert.equal(loadedSchemas.length, 1, route);
      assert.ok(loadedSchemas[0].asset.includes(`dagger-api-schema-${expectedVersion}`), route);
    }
  }
  await page.close();
}

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    await measure(browser, "/reference/glossary/");
    await measure(browser, "/reference/api/container/", mode === "base");
    await measure(browser, "/next/reference/api/container/", true);
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
