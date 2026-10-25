// Captures the shot list in video/notes/script.md from the real Offset app (offline demo week).
// Usage: node capture.mjs stills|video   (run.sh seeds a fresh db and starts API + prod frontend first)
// Env: WEB (default http://localhost:3010), OUT (default ../assets)
import { createRequire } from "module";
import { mkdirSync, writeFileSync, renameSync } from "fs";
import path from "path";
import { fileURLToPath } from "url";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(here, "../../frontend/package.json"));
const { chromium } = require("@playwright/test");

const WEB = process.env.WEB ?? "http://localhost:3010";
const OUT = path.resolve(process.env.OUT ?? path.join(here, "../assets"));
const MODE = process.argv[2] ?? "stills";
const SAMPLE = path.join(here, "../../frontend/public/samples/hudson_bike_co_daily_revenue.csv");
const VIEW = { width: 1440, height: 900 };
const DSF = 2;
mkdirSync(OUT, { recursive: true });

const manifest = {
  viewport: VIEW,
  deviceScaleFactor: DSF,
  note: "bbox is in CSS px within the parent full-page shot (`page`); anchors are CSS px from the shot image top-left; multiply by deviceScaleFactor for image px. A shot with its own `viewport` overrides the top-level one.",
  shots: [],
};
const values = {}; // on-screen values for verify.md
let currentPage = null; // last full-page shot; parent for element bboxes
const round = (o) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, Math.round(v)]));

async function settle(page, ms = 600) {
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(ms);
}

async function shotPage(page, file, note, anchors) {
  await settle(page);
  await page.screenshot({ path: path.join(OUT, file), fullPage: true, animations: "disabled" });
  const size = await page.evaluate(() => ({ width: innerWidth, height: document.documentElement.scrollHeight }));
  manifest.shots.push({ file, kind: "full-page", url: page.url(), size, note, anchors: await anchorBoxes(anchors, { x: 0, y: 0, ...size }) });
  currentPage = file;
  console.log("  ", file);
}

// Page-coordinate box covering every locator, plus padding.
async function unionBox(locators, pad) {
  const boxes = [];
  for (const l of locators)
    boxes.push(
      await l.evaluate((el) => {
        const r = el.getBoundingClientRect();
        return { x: r.x + scrollX, y: r.y + scrollY, r: r.right + scrollX, b: r.bottom + scrollY };
      }),
    );
  const p = typeof pad === "number" ? { t: pad, r: pad, b: pad, l: pad } : pad; // number or {t,r,b,l}
  const x = Math.min(...boxes.map((b) => b.x)) - p.l;
  const y = Math.min(...boxes.map((b) => b.y)) - p.t;
  return { x, y, width: Math.max(...boxes.map((b) => b.r)) + p.r - x, height: Math.max(...boxes.map((b) => b.b)) + p.b - y };
}

// Page-coordinate box of the first occurrence of `text` inside `within` (a sub-span of a text node).
async function textBox(within, text) {
  return within.evaluate((root, t) => {
    const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      const i = n.data.indexOf(t);
      if (i < 0) continue;
      const range = document.createRange();
      range.setStart(n, i);
      range.setEnd(n, i + t.length);
      const r = range.getBoundingClientRect();
      return { x: r.x + scrollX, y: r.y + scrollY, width: r.width, height: r.height };
    }
    return null;
  }, text);
}

// Page-coordinate union of the rendered text (Range over contents, getClientRects) of elements:
// the glyph lines only, without the element's padding, borders or extra line box.
async function inkBox(els) {
  const rects = [];
  for (const el of els)
    rects.push(
      ...(await el.evaluate((node) => {
        const out = [];
        const walk = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
        for (let t = walk.nextNode(); t; t = walk.nextNode()) {
          if (!t.data.trim()) continue;
          const range = document.createRange();
          range.selectNodeContents(t);
          for (const r of range.getClientRects())
            if (r.width > 0 && r.height > 0) out.push({ x: r.x + scrollX, y: r.y + scrollY, r: r.right + scrollX, b: r.bottom + scrollY });
        }
        return out;
      })),
    );
  if (!rects.length) return null;
  const x = Math.min(...rects.map((r) => r.x)), y = Math.min(...rects.map((r) => r.y));
  return { x, y, width: Math.max(...rects.map((r) => r.r)) - x, height: Math.max(...rects.map((r) => r.b)) - y };
}

// Anchors: {name: locator | [locators] | {text, within}} -> boxes relative to the shot image's top-left.
// Element anchors also get `<name>_text`, the tight box around their text; {text} anchors are
// already tight, so their `_text` is the same box.
async function anchorBoxes(anchors, origin) {
  const out = {};
  // Clamp to the image (e.g. the research row runs past the table's visible scroll box).
  const rel = (box) => {
    const x0 = Math.max(box.x, origin.x), y0 = Math.max(box.y, origin.y);
    const x1 = Math.min(box.x + box.width, origin.x + origin.width), y1 = Math.min(box.y + box.height, origin.y + origin.height);
    return round({ x: x0 - origin.x, y: y0 - origin.y, width: x1 - x0, height: y1 - y0 });
  };
  for (const [name, spec] of Object.entries(anchors ?? {})) {
    let box = null, ink = null;
    try {
      if (spec && spec.text) box = ink = await textBox(spec.within, spec.text);
      else {
        // Every match of every locator (e.g. a table column) goes into the union.
        const all = (await Promise.all([].concat(spec).map((l) => l.all()))).flat();
        if (all.length) [box, ink] = [await unionBox(all, 0), await inkBox(all)];
      }
    } catch { box = null; }
    if (box) out[name] = rel(box);
    else console.log(`   (anchor ${name} not found)`);
    if (ink) out[`${name}_text`] = rel(ink);
  }
  return out;
}

// Crop of one or more elements (union), taken from the full page so the bbox matches `currentPage`.
async function shotEl(page, file, locators, selector, { pad = 16, parent = true, note, anchors } = {}) {
  locators = [].concat(locators);
  await locators[0].scrollIntoViewIfNeeded();
  await settle(page, 400);
  const bbox = await unionBox(locators, pad);
  await page.screenshot({ path: path.join(OUT, file), fullPage: true, clip: bbox, animations: "disabled" });
  manifest.shots.push({
    file, kind: "element", page: parent ? currentPage : null, url: page.url(), selector, bbox: round(bbox), pad, note,
    anchors: await anchorBoxes(anchors, bbox),
  });
  console.log("  ", file);
}

// A drawn arrow cursor (screenshots and Playwright videos show none).
const CURSOR = () => {
  const add = () => {
    if (document.getElementById("__cursor")) return;
    const c = document.createElement("div");
    c.id = "__cursor";
    c.innerHTML =
      '<svg width="26" height="26" viewBox="0 0 24 24"><path d="M4 2l15 11-6.6 1.2 3.9 7.3-2.7 1.4-3.9-7.3L4 20z" fill="#111" stroke="#fff" stroke-width="1.5" stroke-linejoin="round"/></svg>';
    Object.assign(c.style, {
      position: "fixed", left: "-60px", top: "-60px", zIndex: 2147483647, pointerEvents: "none",
      transform: "translate(-4px,-2px)", display: window.__cursorHidden ? "none" : "block",
    });
    document.body.appendChild(c);
    addEventListener("mousemove", (e) => { c.style.left = e.clientX + "px"; c.style.top = e.clientY + "px"; }, true);
  };
  if (document.body) add(); else addEventListener("DOMContentLoaded", add);
};
const showCursor = (page, on) =>
  page.evaluate((v) => { const c = document.getElementById("__cursor"); if (c) c.style.display = v ? "block" : "none"; }, on);

// --- shared flow ------------------------------------------------------------------------------
async function uploadBikeShop(page, act) {
  await page.goto(WEB + "/");
  await page.getByText(/Step 1 of 5/).waitFor();
  await act.click(page.getByRole("button", { name: "Upload your revenue" }));
  await page.locator("#upload-file").setInputFiles(SAMPLE);
  await page.locator(".upload-parsed").waitFor();
  const name = page.locator("#upload-name");
  if (!(await name.inputValue())) await name.fill("Hudson Bike Co.");
  await act.click(page.getByRole("button", { name: "Upload and research" }));
  await page.locator(".wizard-picked").waitFor();
}

async function runTaxiDesk(page, act) {
  await page.getByLabel("Your business").selectOption("taxi");
  await page.getByTestId("hedge-card").first().waitFor();
  await act.click(page.getByRole("button", { name: /^Run desk/ }));
  await page.getByRole("button", { name: "Running…" }).waitFor({ timeout: 5000 }).catch(() => {});
  await page.waitForFunction(() => !document.body.innerText.includes("Running…"), null, { timeout: 180000 });
  // The dashboard doesn't refetch /health after a run, so the sample-week banner lingers until a reload.
  await page.reload();
  await page.getByLabel("Your business").selectOption("taxi");
  await page.getByTestId("hedge-card").first().waitFor();
  await page.locator(".sample-banner").waitFor({ state: "detached", timeout: 30000 });
  await page.getByTestId("hedge-card").filter({ hasText: "Declined" }).first().waitFor();
}

// --- stills -----------------------------------------------------------------------------------
async function stills() {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: VIEW, deviceScaleFactor: DSF });
  await ctx.addInitScript(() => { window.__cursorHidden = true; });
  await ctx.addInitScript(CURSOR);
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const act = { click: (l) => l.click() };

  console.log("wizard: upload");
  await uploadBikeShop(page, act);
  await page.mouse.move(0, 0);
  await shotPage(page, "shot-01-wizard-upload.png", "Step 1, Upload your revenue pressed, Hudson Bike Co. status line + Uploaded · sample badge", {
    upload_btn: page.getByRole("button", { name: "Upload your revenue" }),
    status: page.locator(".wizard-picked"),
  });
  values.upload_status = (await page.locator(".wizard-picked").innerText()).trim();

  console.log("wizard: research");
  const next = page.getByRole("button", { name: "Next →" });
  await next.click();
  await page.getByText("Running analysis…").waitFor();
  await page.getByTestId("research-row-rain").waitFor({ timeout: 30000 });
  // The wizard is capped at 1100px and its research table (min-width 1080px) scrolls sideways, cutting
  // off the Kalshi column at any viewport, so shot-02/02b come from the dashboard's upload panel
  // (same ResearchTable) in research() below. This page is only the parent of shot-03.
  await shotPage(page, "shot-03-wizard-risks-page.png", "Step 2 full page (parent of shot-03)");
  values.rain_row_wizard = (await page.getByTestId("research-row-rain").innerText()).replace(/\s+/g, " ").trim();
  await shotEl(
    page, "shot-03-wizard-declined-list.png",
    [page.getByRole("heading", { name: "Declined, and why" }), page.locator(".wizard-declines")],
    "h3:has-text('Declined, and why') + ul.wizard-declines",
    { anchors: { knicks_rows: [page.locator(".wizard-declines li", { hasText: "Knicks home game" }), page.locator(".wizard-declines li", { hasText: "Knicks win" })] } },
  );
  values.declined_list = (await page.locator(".wizard-declines").innerText()).trim();

  console.log("wizard: hedge");
  await next.click(); // settings
  await next.click(); // hedges
  await page.getByRole("button", { name: "Send to the desk →" }).click();
  const card = page.getByTestId("demo-hedge-card");
  await card.waitFor({ timeout: 30000 });
  const cardAnchors = () => ({
    title: { text: "Will it rain in Central Park on Oct 28?", within: card },
    ticker: { text: "KXRAIN-26OCT28-NYC · series KXRAIN", within: card },
    buy_line: card.locator("p.headline").first(),
    check_le: card.locator("li", { hasText: "Contracts ≤ measured exposure" }),
    premium_col: card.locator("table tr > :nth-child(4)"),
    expected_cost: { text: "Expected cost ≈ $64.86", within: card },
    approve_btn: card.getByRole("button", { name: "Approve", exact: true }),
    status_chip: card.locator(".chip").first(),
  });
  await shotPage(page, "shot-04-wizard-hedges-page.png", "Step 4 full page, Proposed (parent of shot-05/06/09)");
  await shotEl(
    page, "shot-05-hedge-card-header.png",
    [card.locator(".row").first(), card.locator("h3").first(), card.locator("p.muted").first()],
    "[data-testid=demo-hedge-card] header: eyebrow/chip, title, ticker",
    { pad: 8, anchors: { title: { text: "Will it rain in Central Park on Oct 28?", within: card }, ticker: { text: "KXRAIN-26OCT28-NYC · series KXRAIN", within: card }, status_chip: card.locator(".chip").first() } },
  );
  await shotEl(page, "shot-06-hedge-card-full.png", card, "[data-testid=demo-hedge-card]", { pad: { t: 2, r: 6, b: 6, l: 6 }, anchors: cardAnchors() });
  values.hedge_card = (await card.innerText()).replace(/\n+/g, " | ").trim();

  const approve = card.getByRole("button", { name: "Approve", exact: true });
  await approve.scrollIntoViewIfNeeded();
  const ab = await approve.boundingBox();
  await page.mouse.move(ab.x + ab.width * 0.55, ab.y + ab.height * 0.6, { steps: 5 });
  await showCursor(page, true);
  await shotEl(page, "shot-09-approve-hover.png", card, "[data-testid=demo-hedge-card] (cursor on Approve)", { pad: { t: 2, r: 6, b: 6, l: 6 }, anchors: cardAnchors() });
  await approve.click();
  await card.getByText("Approved by you").waitFor();
  await showCursor(page, false);
  await page.mouse.move(0, 0);
  await shotPage(page, "shot-10-wizard-approved-page.png", "Step 4 after Approve (parent of shot-10)");
  await shotEl(page, "shot-10-approved-chip.png", card, "[data-testid=demo-hedge-card] after Approve", { pad: { t: 2, r: 6, b: 6, l: 6 }, anchors: { status_chip: card.locator(".chip").first() } });

  console.log("dashboard: bike shop");
  await next.click();
  await page.getByRole("button", { name: "Open my dashboard →" }).click();
  const log = page.getByRole("region", { name: "Decision log", exact: true });
  await log.waitFor();
  await page.waitForTimeout(800);
  await shotPage(page, "shot-11-dashboard-bike-page.png", "Dashboard on Hudson Bike Co. after approval (parent of shot-11)");
  await shotEl(page, "shot-11-decision-log.png", log, "section[aria-label='Decision log']", {
    anchors: {
      approval_entry: log.locator("details.decision-row", { hasText: /approval/i }),
      proposal_entry: log.locator("details.decision-row", { hasText: /proposal/i }),
    },
  });
  values.decision_log_bike = (await log.innerText()).replace(/\n+/g, " | ").trim();

  console.log("dashboard: taxi run desk");
  await runTaxiDesk(page, act);
  await page.locator(".exposure-panel summary", { hasText: "Measured, not hedged" }).click();
  await page.mouse.move(0, 0);
  await shotPage(page, "shot-15-dashboard-wide.png", "Taxi after Run desk, full page (parent of 04/07/08/14)");
  const exposure = page.locator(".exposure-panel");
  const model = exposure.locator("section.subsection", { hasText: "Model check" });
  await shotEl(page, "shot-04-model-check.png", model, ".exposure-panel section.subsection:has-text('Model check')", {
    anchors: {
      planted: model.locator("dl.model-values"),
      interval: [model.locator("p", { hasText: "90% interval" }), model.locator("p", { hasText: "Coverage" })],
    },
  });
  values.model_check = (await model.innerText()).replace(/\n+/g, " | ").trim();
  const declined = page.getByTestId("hedge-card").filter({ hasText: "Declined" }).first();
  await shotEl(page, "shot-07-taxi-declined-card.png", declined, "[data-testid=hedge-card]:has-text('Declined')", {
    anchors: { reasons: declined.locator(".decline-reasons > ul:not(.checks)"), compare: declined.locator(".unstable-compare") },
  });
  values.taxi_declined = (await declined.innerText()).replace(/\n+/g, " | ").trim();
  const cmp = declined.locator(".unstable-compare");
  values.taxi_unstable = (await cmp.count()) ? (await cmp.innerText()).replace(/\n+/g, " | ") : "(no Last year / Recent months block)";
  await shotEl(page, "shot-08-not-hedged-list.png", exposure, ".exposure-panel (Measured, not hedged opened)", {
    anchors: {
      real_badge: exposure.getByText("Real", { exact: true }),
      not_hedged: exposure.locator("details.subsection", { hasText: "Measured, not hedged" }),
      planted: exposure.locator("dl.model-values"),
    },
  });
  values.taxi_exposures = (await exposure.innerText()).replace(/\n+/g, " | ").trim();
  await shotEl(
    page, "shot-14-labels.png",
    [page.locator("header").first(), page.locator(".intro-actions")],
    "header + .intro-actions (Real/Estimated badge, No real orders are placed)",
    {
      pad: 12,
      anchors: {
        no_orders_badge: page.locator(".intro-actions").getByText("No real orders are placed"),
        real_badge: page.locator("header").first().getByText("Real", { exact: true }),
      },
    },
  );

  console.log("taxi books");
  await page.getByRole("tab", { name: /Books/ }).click();
  const bottom = page.locator(".bottom-panel");
  await bottom.locator("table").first().waitFor();
  await page.waitForTimeout(500);
  await shotPage(page, "shot-12-dashboard-books-page.png", "Taxi Books tab before reconciliation (parent of shot-12)");
  const booksAnchors = () => ({
    ledger_table: bottom.locator("table").first(),
    flagged_row: bottom.getByTestId("mismatch-row"),
    flag_note: bottom.locator(".mismatch-note"),
    sim_badge: bottom.getByText(/^Simulated · settlements/),
  });
  await shotEl(page, "shot-12-ledger.png", bottom, ".bottom-panel (Books & reconciliation)", { anchors: booksAnchors() });
  values.ledger = (await bottom.innerText()).replace(/\n+/g, " | ").trim();
  await bottom.getByRole("button", { name: "Run reconciliation" }).click();
  await page.mouse.move(0, 0);
  await page.evaluate(() => document.activeElement?.blur());
  await bottom.locator("[data-testid=mismatch-row], .reconcile table").first().waitFor({ timeout: 30000 });
  await page.waitForTimeout(500);
  await shotPage(page, "shot-13-dashboard-reconciled-page.png", "Taxi Books tab after Run reconciliation (parent of shot-13)");
  await shotEl(page, "shot-13-reconcile.png", bottom.locator(".reconcile"), ".reconcile (after Run reconciliation)", {
    pad: 8,
    anchors: { flagged_row: bottom.getByTestId("mismatch-row"), flag_note: bottom.locator(".mismatch-note"), sim_badge: bottom.locator(".reconcile").getByText(/^Simulated/) },
  });
  values.reconcile = (await bottom.locator(".reconcile").innerText()).replace(/\n+/g, " | ").trim();

  await research(browser, errors);
  if (errors.length) console.log("page errors:", errors);
  values.page_errors = errors;
  await browser.close();
  manifest.shots.sort((a, b) => a.file.localeCompare(b.file));
  writeFileSync(path.join(OUT, "shots.json"), JSON.stringify(manifest, null, 2));
  writeFileSync(path.join(OUT, "onscreen-values.json"), JSON.stringify(values, null, 2));
}

// --- research table, full width -------------------------------------------------------------
// Dashboard "Upload your revenue" drawer -> Upload and research: the same scripted ResearchTable as
// wizard step 2, but in a panel wide enough for every column at 1920.
const WIDE = { width: 1920, height: 1080 };
async function research(browser, errors) {
  console.log("research table (1920)");
  const ctx = await browser.newContext({ viewport: WIDE, deviceScaleFactor: DSF });
  await ctx.addInitScript(() => window.localStorage.setItem("hedge-desk:setup-done", "1"));
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(WEB + "/");
  await page.getByRole("button", { name: "Upload your revenue" }).first().click();
  await page.locator("#upload-file").setInputFiles(SAMPLE);
  await page.locator(".upload-parsed").waitFor();
  const name = page.locator("#upload-name");
  if (!(await name.inputValue())) await name.fill("Hudson Bike Co.");
  await page.getByRole("button", { name: "Upload and research" }).click();
  const rain = page.getByTestId("research-row-rain");
  await rain.waitFor({ timeout: 30000 });
  await page.mouse.move(0, 0);
  const n = manifest.shots.length;
  await shotPage(page, "shot-02-wizard-research-page.png", "Dashboard upload panel at 1920 (parent of shot-02/02b); same table as wizard step 2");
  const table = page.locator("[data-testid=demo-research] .research-scroll").first();
  const cells = rain.locator(":scope > th, :scope > td");
  const rainAnchors = {
    rain_row: rain, rain_train: cells.nth(1), rain_unseen: cells.nth(2), rain_verdict: rain.locator(".chip.found"),
    rain_kalshi: cells.nth(6),
  };
  await shotEl(page, "shot-02-wizard-research-table.png", table, "[data-testid=demo-research] .research-scroll", { pad: 0, anchors: rainAnchors });
  await shotEl(page, "shot-02b-rain-row.png", rain, "[data-testid=research-row-rain]", { pad: { t: 10, r: 10, b: 10, l: 10 }, anchors: rainAnchors });
  values.rain_row = (await rain.innerText()).replace(/\s+/g, " ").trim();
  for (const shot of manifest.shots.slice(n)) shot.viewport = WIDE;
  await ctx.close();
}

// --- recording --------------------------------------------------------------------------------
async function video() {
  const browser = await chromium.launch();
  const vdir = path.join(OUT, ".video-tmp");
  const ctx = await browser.newContext({ viewport: VIEW, deviceScaleFactor: 1, recordVideo: { dir: vdir, size: VIEW } });
  await ctx.addInitScript(CURSOR);
  const page = await ctx.newPage();
  const act = {
    async click(loc, wait = 900) {
      await loc.scrollIntoViewIfNeeded();
      const b = await loc.boundingBox();
      await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 25 });
      await page.waitForTimeout(250);
      await loc.click();
      await page.waitForTimeout(wait);
    },
  };
  const scrollTo = async (loc, wait = 1500) => {
    await loc.evaluate((el) => el.scrollIntoView({ behavior: "smooth", block: "center" }));
    await page.waitForTimeout(wait);
  };

  await uploadBikeShop(page, act);
  await page.waitForTimeout(1500);
  const next = page.getByRole("button", { name: "Next →" });
  await act.click(next);
  await page.getByTestId("research-row-rain").waitFor({ timeout: 30000 });
  await scrollTo(page.getByTestId("research-row-rain"), 2500);
  await scrollTo(page.getByRole("heading", { name: "Declined, and why" }), 2000);
  await act.click(next, 1200);
  await act.click(next, 1200);
  await act.click(page.getByRole("button", { name: "Send to the desk →" }));
  const card = page.getByTestId("demo-hedge-card");
  await card.waitFor({ timeout: 30000 });
  const cardAnchors = () => ({
    title: { text: "Will it rain in Central Park on Oct 28?", within: card },
    ticker: { text: "KXRAIN-26OCT28-NYC · series KXRAIN", within: card },
    buy_line: card.locator("p.headline").first(),
    check_le: card.locator("li", { hasText: "Contracts ≤ measured exposure" }),
    premium_col: card.locator("table tr > :nth-child(4)"),
    expected_cost: { text: "Expected cost ≈ $64.86", within: card },
    approve_btn: card.getByRole("button", { name: "Approve", exact: true }),
    status_chip: card.locator(".chip").first(),
  });
  await scrollTo(card, 2500);
  await act.click(card.getByRole("button", { name: "Approve", exact: true }), 2000);
  await act.click(next, 1000);
  await act.click(page.getByRole("button", { name: "Open my dashboard →" }), 2500);
  await runTaxiDesk(page, act);
  await scrollTo(page.getByTestId("hedge-card").filter({ hasText: "Declined" }).first(), 3000);
  await act.click(page.getByRole("tab", { name: /Books/ }), 1500);
  await scrollTo(page.locator(".bottom-panel"), 1500);
  await act.click(page.getByRole("button", { name: "Run reconciliation" }), 1000);
  await scrollTo(page.locator(".reconcile"), 3000);

  const v = page.video();
  await ctx.close();
  await browser.close();
  const dest = path.join(OUT, "rec-01-bike-wizard-to-taxi-books.webm");
  renameSync(await v.path(), dest);
  console.log("  ", path.basename(dest));
}

if (MODE === "video") await video();
else await stills();
