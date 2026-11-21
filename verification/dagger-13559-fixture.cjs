const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");

const docs = process.argv[2];
const jiti = require(require.resolve("jiti", { paths: [docs] }))(__filename);
const loadPlugin = jiti(path.join(docs, "plugins/llms-txt-plugin/index.ts")).default;

async function verify() {
  const outDir = await fs.mkdtemp(path.join(os.tmpdir(), "dagger-llms-fixture-"));
  for (const route of ["stable", "next/new"]) {
    await fs.mkdir(path.join(outDir, route), { recursive: true });
    await fs.writeFile(path.join(outDir, route, "index.html"), `
      <article><div class="theme-doc-markdown">
      <h1>${route}<a class="hash-link" href="#title">Anchor</a></h1>
      <p><a href="/guide/link#heading">Guide</a></p>
      </div></article>
    `);
  }

  const baseUrl = "/guide/";
  const context = { siteConfig: { title: "Dagger", url: "https://example.test" }, baseUrl };
  const plugin = loadPlugin(context);
  const current = {
    versionName: "current",
    docs: [
      { id: "new", title: "New", description: "", permalink: "/guide/next/new" },
      { id: "stable", title: "Upcoming", description: "", permalink: "/guide/next/stable" },
    ],
    sidebars: { main: [{ type: "doc", id: "stable" }, { type: "ref", id: "new" }] },
  };
  const stable = {
    versionName: "0.0.1",
    isLast: true,
    docs: [{
      id: "stable",
      title: "Released",
      description: "First release",
      permalink: "/guide/stable",
      lastUpdatedAt: Date.parse("2025-03-01T12:00:00.000Z"),
    }],
  };
  const args = {
    outDir,
    plugins: [{
      name: "docusaurus-plugin-content-docs",
      content: { loadedVersions: [current, stable] },
    }],
  };
  await plugin.postBuild(args);
  const index = await fs.readFile(path.join(outDir, "llms.txt"), "utf8");
  const corpus = await fs.readFile(path.join(outDir, "llms-full.txt"), "utf8");
  assert.match(index, /\(https:\/\/example\.test\/guide\/llms-full\.txt\)/);
  assert.match(index, /Released.*guide\/stable.*First release\n.*New.*guide\/next\/new/);
  assert.match(corpus, /title: "Released"\ndescription: "First release"\nsource: https:\/\/example\.test\/guide\/stable\nlast_updated: 2025-03-01/);
  assert.match(corpus, /title: "New"\ndescription: ""\nsource: https:\/\/example\.test\/guide\/next\/new/);
  assert.match(corpus, /\[Guide\]\(https:\/\/example\.test\/guide\/link#heading\)/);
  assert.doesNotMatch(corpus, /Upcoming|Anchor/);

  await fs.writeFile(path.join(outDir, "stable", "index.html"), `
    <article><div class="theme-doc-markdown"><a href="source.mdx">Invalid link</a></div></article>
  `);
  await assert.rejects(plugin.postBuild(args), /Unresolved documentation source link/);
  console.log("Plugin fixture passed for a nested base URL, next-only page, date metadata, and rejected source links");
}

verify().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
