"use strict";
const el = (s) => document.querySelector(s);
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const fmt = (n) =>
  typeof n === "number" && Number.isFinite(n) ? n.toLocaleString() : "—";
const date = (s) =>
  s && !isNaN(Date.parse(s))
    ? new Date(s).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";
const label = (s) => String(s ?? "").replaceAll("_", " ");
const paths = [
  "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  "M3 12h4l3-7 4 14 3-7h4",
  "M6 5v14 M16 5v5q0 4-6 4 M4 4h4v4H4z M14 3h4v4h-4z M4 17h4v4H4z",
  "M4 4h6v5H4z M14 15h6v5h-6z M7 9v8h7",
  "M4 7h16v13H4z M8 3v4 M16 3v4 M8 12h8 M8 16h4",
  "M12 3l8 4v5q0 6-8 9-8-3-8-9V7z M8 12l3 3 5-6",
  "M4 17l6-6 4 3 6-9 M15 5h5v5",
  "M4 20V8 M10 20V4 M16 20v-8 M22 20H2",
  "M3 18h18 M5 14V9 M10 14V5 M15 14v-4 M20 14V7",
];
const sections = {
  overview: "Overview",
  runs: "Runs & traces",
  prs: "Pull requests",
  workflows: "Workflows",
  agents: "Agents",
  judges: "Judge scores",
  improvements: "Self-improvement",
  benchmarks: "Benchmarks",
  usage: "Usage",
};
let data = { prs: [], runs: [], traces: [] },
  learning = {},
  page = "",
  filter = "",
  query = "",
  runTab = "runs",
  links = [],
  learningError = "",
  requestNo = 0;
const actions = {
  await_approval: "Workflow approval",
  checks_passed: "Checks passed",
  investigate_failure: "Failing checks",
  inspect_missing_evidence: "Missing evidence",
  wait_for_ci: "CI running",
  merged: "Merged",
};
const nice = (s) => actions[s] || label(s) || "Unknown";
const badge = (s) =>
  '<span class="badge ' +
  (/passed|verified|merged|success/i.test(s)
    ? "good"
    : /fail|error|conflict/i.test(s)
      ? "bad"
      : /wait|pending|approval/i.test(s)
        ? "wait"
        : "") +
  '">' +
  esc(nice(s)) +
  "</span>";
function ghUrl(value) {
  try {
    const u = new URL(value);
    return u.protocol === "https:" && u.hostname === "github.com"
      ? u.href
      : null;
  } catch {
    return null;
  }
}
function link(v, txt) {
  const u = ghUrl(v);
  return u
    ? '<a class="action" target="_blank" rel="noopener noreferrer" href="' +
        esc(u) +
        '">' +
        esc(txt) +
        " ↗</a>"
    : "";
}
function bind(fn) {
  links.push(fn);
  return 'data-act="' + (links.length - 1) + '"';
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-act]");
  if (b) links[Number(b.dataset.act)]?.();
});
const content = el("#content"),
  dlg = el("dialog");
function modal(title, body) {
  el("#detail").innerHTML =
    '<div class="eyebrow">Factory evidence</div><h2>' +
    esc(title) +
    "</h2>" +
    body;
  if (!dlg.open) dlg.showModal();
}
function facts(obj) {
  return Object.entries(obj || {})
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(
      ([k, v]) =>
        '<div class="detailrow"><h3>' +
        esc(label(k)) +
        "</h3>" +
        (typeof v === "object"
          ? "<pre>" + esc(JSON.stringify(v, null, 2)) + "</pre>"
          : "<p>" + esc(v) + "</p>") +
        "</div>",
    )
    .join("");
}
function nav() {
  let s = "",
    i = 0;
  for (const [k, v] of Object.entries(sections)) {
    if (k === "overview" || k === "workflows" || k === "judges")
      s +=
        '<div class="group">' +
        {
          overview: "Workspace",
          workflows: "Configuration",
          judges: "Evaluation",
        }[k] +
        "</div>";
    s +=
      '<a href="#' +
      k +
      '" ' +
      (page === k ? 'class="active" aria-current="page"' : "") +
      '><svg viewBox="0 0 24 24" aria-hidden="true"><path d="' +
      paths[i++] +
      '"/></svg>' +
      v +
      "</a>";
  }
  el("nav").innerHTML = s;
}
const count = (a, key) =>
  a.reduce((acc, r) => {
    const k = r[key] || "Unknown";
    acc[k] = (acc[k] || 0) + 1;
    return acc;
  }, {});
function volume() {
  const days = count(
    data.runs
      .filter((x) => x.finished_at && !isNaN(Date.parse(x.finished_at)))
      .map((x) => ({
        day: new Date(x.finished_at).toISOString().slice(0, 10),
      })),
    "day",
  );
  const last = Object.keys(days).sort().at(-1);
  if (!last) return '<p class="sub">No dated runs recorded.</p>';
  const labels = Array.from({ length: 14 }, (_, i) =>
    new Date(Date.parse(last) + (i - 13) * 86400000).toISOString().slice(0, 10),
  );
  const max = Math.max(1, ...labels.map((k) => days[k] || 0));
  const grid = [10, 40, 70, 100]
    .map(
      (y) =>
        '<path d="M0 ' + y + 'H420" stroke="#42614d" stroke-dasharray="2 4"/>',
    )
    .join("");
  const bars = labels
    .map((day, i) => {
      const h = ((days[day] || 0) * 89) / max;
      return (
        '<rect x="' +
        (i * 30 + 5) +
        '" y="' +
        (99 - h) +
        '" width="18" height="' +
        Math.max(1, h) +
        '" rx="2" fill="' +
        (i === 13 ? "#d9f9a3" : "#80ac81") +
        '"><title>' +
        day +
        " · " +
        (days[day] || 0) +
        " runs</title></rect>"
      );
    })
    .join("");
  return (
    '<svg role="img" aria-label="Daily indexed runs for the 14 days ending ' +
    last +
    '" class="plot" viewBox="0 0 420 104" preserveAspectRatio="none">' +
    grid +
    bars +
    '</svg><div class="dates"><span>' +
    labels[0] +
    "</span><span>" +
    last +
    " · UTC</span></div>"
  );
}
function overview() {
  const prs = data.prs,
    merged = prs.filter((x) => x.state === "MERGED"),
    open = prs.filter((x) => x.state === "OPEN");
  const metrics = [
    ["Tracked PRs", prs.length],
    ["Upstream merges", merged.length],
    ["Indexed runs", data.runs.length],
    ["Codex traces", data.traces.length],
  ];
  return (
    '<div class="metrics">' +
    metrics
      .map(
        ([k, v]) =>
          '<div class="metric"><span>' +
          k +
          "</span><strong>" +
          fmt(v) +
          "</strong></div>",
      )
      .join("") +
    '</div><div class="overviewgrid"><section class="panel chartpanel"><span class="eyebrow">Execution history</span><h2>Run volume</h2><p class="sub">Indexed factory runs per day</p>' +
    volume() +
    '</section><section class="panel"><div class="panelhead"><h2>PR queue</h2><span class="chip">' +
    open.length +
    " open</span></div>" +
    Object.entries(count(open, "action"))
      .sort((a, b) => b[1] - a[1])
      .map(
        ([k, n]) =>
          '<button class="dispo" ' +
          bind(() => goto("prs", k)) +
          "><span>" +
          esc(nice(k)) +
          "</span><span>" +
          n +
          " →</span></button>",
      )
      .join("") +
    '</section></div><section class="panel"><div class="panelhead"><h2>Recent runs</h2><button ' +
    bind(() => goto("runs")) +
    ">View all →</button></div>" +
    runTable(data.runs.slice(0, 6)) +
    "</section>"
  );
}
function table(headers, rows) {
  if (!rows.length) return '<p class="empty">No matching records.</p>';
  return (
    '<div class="tablewrap"><table><thead><tr>' +
    headers.map((s) => '<th scope="col">' + esc(s) + "</th>").join("") +
    "</tr></thead><tbody>" +
    rows
      .map(
        (r) => "<tr>" + r.map((c) => "<td>" + c + "</td>").join("") + "</tr>",
      )
      .join("") +
    "</tbody></table></div>"
  );
}
function button(title, fn) {
  return '<button class="link" ' + bind(fn) + ">" + esc(title) + "</button>";
}
function repoName(pr) {
  return (pr || "").replace("https://github.com/", "").replace("/pull/", " #");
}
function runTable(rs) {
  return table(
    ["Run / subject", "Outcome", "Tokens", "Finished"],
    rs.map((r) => [
      button(repoName(r.pr) || r.id, () => runDetail(r)),
      badge(r.outcome),
      fmt(r.tokens),
      date(r.finished_at),
    ]),
  );
}
function runDetail(r) {
  modal(
    repoName(r.pr) || r.id,
    facts({
      run: r.id,
      outcome: r.outcome,
      revision: r.head,
      finished: r.finished_at,
      tokens: r.tokens,
      seconds: r.seconds,
      human_interventions: r.interventions,
      scores: r.scores,
      receipts: r.receipts,
      evidence: r.details,
    }) +
      link(r.pr, "Open pull request") +
      " <button " +
      bind(() => toggleSaved(r)) +
      ">" +
      (saved().includes(r.id)
        ? "Remove from benchmark selection"
        : "Select for benchmark") +
      "</button>",
  );
}
function saved() {
  try {
    const v = JSON.parse(localStorage.getItem("foundry.benchmark") || "[]");
    return Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}
function toggleSaved(r) {
  const current = saved();
  try {
    localStorage.setItem(
      "foundry.benchmark",
      JSON.stringify(
        current.includes(r.id)
          ? current.filter((x) => x !== r.id)
          : [...current, r.id],
      ),
    );
  } catch {
    modal("Benchmark selection", "Browser storage is unavailable.");
    return;
  }
  dlg.close();
  render();
}
function goto(k, f = "") {
  if (page !== k) {
    location.hash = k;
    page = k;
    query = "";
    filter = f;
    render();
  } else {
    filter = f;
    render();
  }
}
function prDetail(p) {
  modal(
    p.title || repoName(p.url),
    '<div class="toolbar">' +
      badge(p.state) +
      link(p.url, "Open pull request") +
      "</div>" +
      facts({
        repository: p.repo,
        head: p.head,
        base: p.base,
        disposition: nice(p.action),
        review: p.review,
      }) +
      "<h3>Checks</h3>" +
      table(
        ["Check", "Result", "Evidence"],
        (p.checks || []).map((x) => [
          esc(x.name),
          badge(x.state),
          link(x.url, "View"),
        ]),
      ),
  );
}
async function traceDetail(t, messages = false) {
  modal(t.label, "<p>Reading local transcript…</p>");
  const id = ++requestNo;
  try {
    const response = await fetch(
      "/api/trace?id=" +
        encodeURIComponent(t.id) +
        (messages ? "&messages=1" : ""),
    );
    if (!response.ok) throw Error();
    const d = await response.json();
    if (id !== requestNo || !dlg.open) return;
    const events = Array.isArray(d) ? d : d.events || [];
    modal(
      t.label,
      (messages
        ? ""
        : "<button " +
          bind(() => traceDetail(t, true)) +
          ">Show recorded agent messages</button>") +
        '<p class="statsline">' +
        fmt(t.turns) +
        " turns · " +
        fmt(t.tokens) +
        " observed tokens · " +
        fmt(t.events_count) +
        " events</p>" +
        events
          .map(
            (e) =>
              '<div class="detailrow"><span class="mono">#' +
              esc(e.line) +
              "</span> &nbsp;<b>" +
              esc(label(e.item?.type || e.type)) +
              "</b>" +
              (e.item?.text ? "<pre>" + esc(e.item.text) + "</pre>" : "") +
              (e.item?.status
                ? '<p class="sub">' + esc(label(e.item.status)) + "</p>"
                : "") +
              (e.usage
                ? '<p class="sub">' +
                  fmt(e.usage.input_tokens) +
                  " input · " +
                  fmt(e.usage.output_tokens) +
                  " output</p>"
                : "") +
              "</div>",
          )
          .join("") +
        (d.truncated
          ? "<p>Showing a bounded excerpt of this transcript.</p>"
          : ""),
    );
  } catch {
    if (dlg.open && id === requestNo)
      modal(t.label, "Could not load this transcript.");
  }
}
function controls(opts = []) {
  return (
    '<div class="toolbar"><input type="search" aria-label="Search records" placeholder="Search ' +
    esc(sections[page].toLowerCase()) +
    '…" value="' +
    esc(query) +
    '">' +
    (opts.length
      ? '<select aria-label="Filter records"><option value="">All statuses</option>' +
        opts
          .map(
            (k) =>
              '<option value="' +
              esc(k) +
              '" ' +
              (k === filter ? "selected" : "") +
              ">" +
              esc(nice(k)) +
              "</option>",
          )
          .join("") +
        "</select>"
      : "") +
    "</div>"
  );
}
const matches = (o) =>
  JSON.stringify(o).toLowerCase().includes(query.toLowerCase());
function listing() {
  if (page === "prs") {
    const options = [
      ...new Set(data.prs.flatMap((x) => [x.state, x.action]).filter(Boolean)),
    ];
    let rs = data.prs.filter(
      (x) =>
        matches(x) && (!filter || x.action === filter || x.state === filter),
    );
    return (
      controls(options) +
      '<div class="panel">' +
      table(
        ["Pull request", "Repository", "Disposition", "State"],
        rs.map((p) => [
          button(p.title || "#" + p.number, () => prDetail(p)),
          esc(p.repo),
          badge(p.action),
          badge(p.state),
        ]),
      ) +
      "</div>"
    );
  }
  if (page === "runs") {
    const traceTab = runTab === "traces";
    return (
      '<div class="tabs">' +
      ["runs", "traces"]
        .map(
          (k) =>
            '<button aria-pressed="' +
            (runTab === k) +
            '" ' +
            bind(() => {
              runTab = k;
              filter = "";
              query = "";
              render();
            }) +
            ">" +
            { runs: "Indexed runs", traces: "Codex traces" }[k] +
            "</button>",
        )
        .join("") +
      "</div>" +
      controls() +
      '<section class="panel">' +
      (traceTab
        ? table(
            ["Session", "Turns", "Tokens", "Recorded"],
            data.traces
              .filter(matches)
              .map((t) => [
                button(t.label, () => traceDetail(t)),
                fmt(t.turns),
                fmt(t.tokens),
                date(t.date),
              ]),
          )
        : runTable(data.runs.filter(matches))) +
      "</section>"
    );
  }
  return learnView();
}
function benchmarkPlot(rows) {
  const dollars = rows.some(
    (r) => Number.isFinite(r.cost) && Number.isFinite(r.quality),
  );
  const field = dollars ? "cost" : "median_seconds";
  const unit = dollars ? " USD" : "s";
  const axis = dollars ? "billed cost" : "elapsed time";
  const comparable = rows.filter(
    (r) => Number.isFinite(r.quality) && Number.isFinite(r[field]),
  );
  if (!comparable.length) return "";
  const max = Math.max(0.01, ...comparable.map((r) => r[field]));
  const points = comparable
    .map((r) => {
      const x = 45 + (430 * r[field]) / max,
        y = 135 - 110 * r.quality;
      return (
        '<circle cx="' +
        x +
        '" cy="' +
        y +
        '" r="5" fill="#37744c"><title>' +
        esc(r.title + " / " + r.subtitle) +
        ": " +
        r[field] +
        unit +
        ", " +
        Math.round(100 * r.quality) +
        "% solved</title></circle>"
      );
    })
    .join("");
  return (
    '<section class="panel"><div class="panelhead"><h2>Quality vs. ' +
    axis +
    '</h2><span class="chip">Paired cohort</span></div><svg viewBox="0 0 510 170" role="img" aria-label="Task solve rate versus ' +
    axis +
    '" class="scatter"><path d="M45 25V135H478 M45 80H478 M45 25H478" fill="none" stroke="#d6dfd2"/><g fill="#58675a" font-size="10"><text x="1" y="29">100%</text><text x="8" y="84">50%</text><text x="16" y="140">0%</text><text x="45" y="154">0</text><text x="443" y="154">' +
    max.toFixed(2) +
    unit +
    "</text></g>" +
    points +
    "</svg><details><summary>View measured trials</summary>" +
    table(
      [
        "Model / variant",
        "Round",
        "Solved",
        dollars ? "Billed cost" : "Median time",
      ],
      comparable.map((r) => [
        esc(r.title),
        esc(r.subtitle),
        Math.round(r.quality * 100) + "%",
        r[field] + unit,
      ]),
    ) +
    "</details></section>"
  );
}
function performancePanel() {
  const times = data.runs
      .map((r) => r.seconds)
      .filter(Number.isFinite)
      .sort((a, b) => a - b),
    n = times.length;
  const median = n
    ? (times[Math.floor(n / 2)] + times[Math.floor((n - 1) / 2)]) / 2
    : null;
  const counters = [
    ["Median recorded run", median === null ? "—" : Math.round(median) + "s"],
    ["Runs with timing", fmt(n)],
    [
      "Runs with token counts",
      fmt(data.runs.filter((r) => Number.isFinite(r.tokens)).length),
    ],
  ];
  return (
    '<section class="panel section"><h2>Execution coverage</h2><div class="toolbar">' +
    counters
      .map(
        ([k, v]) => '<span class="chip">' + esc(k) + " · " + esc(v) + "</span>",
      )
      .join("") +
    '</div><p class="sub">Durations measure indexed factory runs. End-to-end time from issue creation to merge requires both lifecycle timestamps.</p></section>'
  );
}
function learnView() {
  if (learningError) return '<p class="error">' + esc(learningError) + "</p>";
  let rows = (learning[page] || []).filter(matches);
  if (page === "improvements")
    rows = rows.filter((r) => !r.url && r.title !== "Delivery score");
  if (page === "judges")
    rows = rows.concat(
      (learning.improvements || []).filter(
        (r) => (r.url || r.title === "Delivery score") && matches(r),
      ),
    );
  let extra = "";
  if (page === "benchmarks") {
    const selected = data.runs.filter((r) => saved().includes(r.id));
    extra =
      '<section class="panel section"><div class="panelhead"><h2>Benchmark selection</h2><span class="chip">This browser</span></div>' +
      (selected.length
        ? runTable(selected)
        : '<p class="sub">Select a run from its evidence panel to collect examples for comparison.</p>') +
      "</section>";
    const measured = rows.filter(
      (r) => Number.isFinite(r.cost) && Number.isFinite(r.quality),
    );
    if (measured.length)
      extra +=
        '<section class="panel section"><h2>Measured quality and cost</h2>' +
        table(
          ["Model", "Quality", "Cost (USD)"],
          measured.map((r) => [
            esc(r.model || r.title),
            esc(r.quality),
            esc(r.cost),
          ]),
        ) +
        "</section>";
  }
  return (
    controls() +
    (page === "benchmarks"
      ? benchmarkPlot(rows)
      : page === "usage"
        ? performancePanel()
        : "") +
    (rows.length
      ? '<div class="cards">' +
        rows
          .map(
            (r) =>
              '<button class="card" ' +
              bind(() =>
                modal(r.title, facts(r.details) + link(r.url, "View source")),
              ) +
              "><strong>" +
              esc(r.title) +
              '</strong><span class="sub">' +
              esc(r.subtitle) +
              "</span>" +
              badge(r.status) +
              "</button>",
          )
          .join("") +
        "</div>"
      : '<div class="panel empty">No matching evidence recorded.</div>') +
    extra
  );
}
const descriptions = {
  overview: "Delivery outcomes and execution across your local factory.",
  runs: "Inspect indexed evidence and recorded Codex sessions.",
  prs: "Follow each contribution through CI, review, and merge.",
  workflows: "The checked-in definitions behind factory execution.",
  agents: "Local agent roles, skills, and execution policies.",
  judges: "Inspect recorded judgments and calibration evidence.",
  improvements: "Review observed failures and proposed changes to the factory.",
  benchmarks: "Compare measured outcomes on the factory’s own tasks.",
  usage: "Inspect recorded token consumption and cost estimates.",
};
function render() {
  if (dlg.open) dlg.close();
  links = [];
  nav();
  el("#crumb").textContent = sections[page];
  document.title = "Foundry / " + sections[page];
  el("#boarddate").textContent = data.as_of
    ? "Board snapshot · " + date(data.as_of)
    : "";
  content.innerHTML =
    '<div class="eyebrow">Software factory</div><div class="titleline"><div><h1>' +
    (page === "overview" ? "Factory overview" : sections[page]) +
    '</h1><p class="caption">' +
    descriptions[page] +
    "</p></div></div>" +
    (page === "overview" ? overview() : listing());
  const box = content.querySelector("input");
  if (box)
    box.oninput = () => {
      query = box.value;
      render();
      content.querySelector("input").focus();
    };
  const sel = content.querySelector("select");
  if (sel)
    sel.onchange = () => {
      filter = sel.value;
      render();
    };
}
function route() {
  const k = location.hash.slice(1);
  const next = Object.hasOwn(sections, k) ? k : "overview";
  if (next !== page) {
    filter = "";
    query = "";
    page = next;
  }
  el("aside").classList.remove("open");
  render();
}
async function load() {
  el("#refresh").disabled = true;
  try {
    const results = await Promise.allSettled(
      ["snapshot", "learning"].map(async (k) => {
        const res = await fetch("/api/" + k);
        if (!res.ok) throw Error(k + " unavailable");
        return res.json();
      }),
    );
    if (results[0].status !== "fulfilled")
      throw Error("The factory evidence could not be read. Refresh to retry.");
    data = results[0].value;
    data.runs.sort((a, b) =>
      String(b.finished_at || "").localeCompare(String(a.finished_at || "")),
    );
    learningError =
      results[1].status === "rejected"
        ? "Learning evidence is unavailable. Refresh to retry."
        : "";
    learning = results[1].value || {};
    route();
  } catch (e) {
    content.innerHTML = '<p class="error">' + esc(e.message) + "</p>";
  } finally {
    el("#refresh").disabled = false;
  }
}
el("#menu").onclick = () => el("aside").classList.toggle("open");
el("#refresh").onclick = load;
window.addEventListener("hashchange", route);
dlg.addEventListener("close", () => {
  requestNo++;
});
load();
