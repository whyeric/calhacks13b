#!/usr/bin/env node
// Print the page's real schedule (window.__video.schedule: scenes with lead/tail holds, VO clips, cues) as JSON.
//   node video/finish/dump-schedule.mjs [videoRoot] > schedule.json
// Same static-server + Playwright setup as record.mjs, read-only.
import { createRequire } from "node:module";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(process.argv[2] || path.join(path.dirname(fileURLToPath(import.meta.url)), ".."));
const require = createRequire(path.join(ROOT, "..", "frontend", "package.json"));
const { chromium } = require("playwright");

const TYPES = { ".html": "text/html", ".js": "text/javascript", ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml", ".m4a": "audio/mp4", ".css": "text/css" };
const server = http.createServer((req, res) => {
  const p = path.join(ROOT, decodeURIComponent(new URL(req.url, "http://x").pathname));
  if (!p.startsWith(ROOT) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": TYPES[path.extname(p)] || "application/octet-stream" });
  fs.createReadStream(p).pipe(res);
});
await new Promise(r => server.listen(0, "127.0.0.1", r));
const browser = await chromium.launch();
try {
  const page = await (await browser.newContext({ viewport: { width: 1920, height: 1080 } })).newPage();
  await page.goto(`http://127.0.0.1:${server.address().port}/index.html?record=1&frames=1`);
  await page.waitForFunction(() => window.__ready === true, null, { timeout: 30000 });
  const info = await page.evaluate(() => window.__video.schedule);
  process.stdout.write(JSON.stringify(info, null, 2) + "\n");
} finally {
  await browser.close(); server.close();
}
