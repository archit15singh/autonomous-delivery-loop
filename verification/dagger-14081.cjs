const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { gzipSync } = require("node:zlib");
const mode = process.argv[2];
const docs = process.cwd();
const { load } = require(require.resolve("cheerio", { paths: [docs] }));
const startingRoute = "reference/api/container";
const liveOnlyDescription = "Keep the temporary directory on the engine's disk";

for (const [route, diskExpected] of [
  [startingRoute, mode === "base"],
  [`next/${startingRoute}`, true],
]) {
  const filename = path.join(docs, "build", route, "index.html");
  const $ = load(fs.readFileSync(filename, "utf8"));
  const article = $("article .theme-doc-markdown");
  assert.equal(article.length, 1, route);
  assert.equal(article.find("[id=withMountedTemp]").length, 1, route);
  assert.equal(article.text().includes(liveOnlyDescription), diskExpected, route);
  console.log(`${route} exposes withMountedTemp.disk: ${diskExpected}`);
}

const $ = load(fs.readFileSync(path.join(docs, "build", startingRoute, "index.html"), "utf8"));
const scripts = $("script[src]").map((_, el) => $(el).attr("src")).get()
  .filter((src) => src.startsWith("/assets/js/"));
const gzipBytes = scripts.reduce((total, src) =>
  total + gzipSync(fs.readFileSync(path.join(docs, "build", src))).length, 0);
console.log(`Initial released API page scripts: ${scripts.length}; total gzip bytes: ${gzipBytes}`);
