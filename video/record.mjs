#!/usr/bin/env node
// Record the Offset product video to out/offset-product.mp4.
//
//   node video/record.mjs                 deterministic: seek each frame, screenshot, pipe to ffmpeg (default, smooth)
//   node video/record.mjs --realtime      Playwright's recordVideo of ?autoplay=1&record=1 in real time (faster, may drop frames)
//   node video/record.mjs --stills 0,5,12  save PNGs of those timestamps (layout checks)
//   node video/record.mjs --final         the deliverable: full render to out/offset-product.mp4 (+ mix.m4a, schedule.json)
//   Without --final everything goes to out/scratch/<label>/ (--label name, default stills-/render-<time>),
//   or to --out <dir>.
//   options: --fps 60  --from 0 --to 90 (seconds, deterministic mode only)  --fast (JPEG frames, preset medium)
//
// Audio: the page's schedule (VO clips and sound cues, absolute seconds) is written to out/schedule.json.
// If audio/mix.py exists it builds out/mix.m4a from that (music, cues, VO); otherwise the VO clips are
// placed at their start times with ffmpeg (or full.m4a is used as-is for a recorded VO). Needs ffmpeg on
// PATH and Playwright (resolved from frontend/node_modules).
import { createRequire } from "node:module";
import { spawn } from "node:child_process";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(HERE, "out");
const require = createRequire(path.join(HERE, "..", "frontend", "package.json"));
const { chromium } = require("playwright");

const args = process.argv.slice(2);
const opt = (name, dflt) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : dflt; };
const FPS = Number(opt("--fps", 60));
const FAST = args.includes("--fast");
// BT.709 limited-range yuv420p, tagged so players don't guess (x264 only writes the range with a colorspace).
const ENC = ["-vf", "scale=out_range=tv:out_color_matrix=bt709,format=yuv420p", "-c:v", "libx264", "-pix_fmt", "yuv420p",
  "-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"];
const REALTIME = args.includes("--realtime");
const STILLS = opt("--stills", null);
// Output hygiene: only `--final` (a full render) writes out/offset-product.mp4, out/mix.m4a and
// out/schedule.json. Everything else goes to out/scratch/<label>/ unless --out <dir> is given.
const FINAL = args.includes("--final");
const stamp = new Date().toISOString().replace(/[-:]/g, "").replace("T", "-").slice(0, 15);
const LABEL = opt("--label", `${STILLS ? "stills" : "render"}-${stamp}`);
const DEST = path.resolve(opt("--out", FINAL ? OUT : path.join(OUT, "scratch", LABEL)));
if (FINAL && (STILLS || args.includes("--from") || args.includes("--to"))) {
  console.error("--final is for a full render only (no --stills/--from/--to)"); process.exit(2);
}
fs.mkdirSync(DEST, { recursive: true });

// Static server for video/ so fetch() and media work the same as on a real host.
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml", ".m4a": "audio/mp4", ".css": "text/css" };
const server = http.createServer((req, res) => {
  const p = path.join(HERE, decodeURIComponent(new URL(req.url, "http://x").pathname));
  if (!p.startsWith(HERE) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": TYPES[path.extname(p)] || "application/octet-stream" });
  fs.createReadStream(p).pipe(res);
});
await new Promise(r => server.listen(0, "127.0.0.1", r));
const BASE = `http://127.0.0.1:${server.address().port}/index.html`;

const run = (cmd, a, { input } = {}) => new Promise((resolve, reject) => {
  const p = spawn(cmd, a, { stdio: [input ? "pipe" : "ignore", "inherit", "inherit"] });
  p.on("error", reject); p.on("close", c => (c === 0 ? resolve() : reject(new Error(`${cmd} exited ${c}`))));
  if (input) input(p.stdin);
});

const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
const errors = [];
const watch = page => {
  page.on("console", m => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", e => errors.push(String(e)));
};

async function openPage(query, ctxOpts = {}) {
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1, ...ctxOpts });
  const page = await ctx.newPage(); watch(page);
  await page.goto(`${BASE}?${query}`);
  await page.waitForFunction(() => window.__ready === true, null, { timeout: 30000 });
  return { ctx, page };
}

async function mixAudio(schedule, total) {
  const json = path.join(DEST, "schedule.json");
  fs.writeFileSync(json, JSON.stringify({ root: HERE, fps: FPS, ...schedule }, null, 2));
  const mixPy = path.join(HERE, "audio", "mix.py");
  if (fs.existsSync(mixPy)) {
    const out = path.join(DEST, "mix.m4a");
    try { await run("python3", [mixPy, json, out]); if (fs.existsSync(out)) return out; }
    catch (e) { console.error(`audio/mix.py failed (${e.message}); falling back to the VO-only mix`); }
  }
  const out = path.join(DEST, "vo-mix.m4a");
  if (schedule.full) {
    await run("ffmpeg", ["-hide_banner", "-loglevel", "error", "-y", "-i", path.join(HERE, schedule.full),
      "-af", `apad=whole_dur=${total.toFixed(3)}`, "-t", total.toFixed(3), "-ar", "48000", "-ac", "2", "-c:a", "aac", "-b:a", "192k", out]);
    return out;
  }
  const clips = schedule.vo.filter(s => fs.existsSync(path.join(HERE, s.file)));
  const a = ["-y"];
  clips.forEach(s => a.push("-i", path.join(HERE, s.file)));
  const delays = clips.map((s, i) => `[${i}:a]adelay=${Math.round(s.start * 1000)}:all=1[a${i}]`).join(";");
  const mix = `${delays};${clips.map((_, i) => `[a${i}]`).join("")}amix=inputs=${clips.length}:normalize=0,apad=whole_dur=${total.toFixed(3)}[out]`;
  a.push("-filter_complex", mix, "-map", "[out]", "-t", total.toFixed(3), "-ar", "48000", "-ac", "2", "-c:a", "aac", "-b:a", "192k", out);
  await run("ffmpeg", ["-hide_banner", "-loglevel", "error", ...a]);
  return out;
}

try {
  if (STILLS) {
    const { page } = await openPage("record=1&frames=1");
    for (const ts of STILLS.split(",").map(Number)) {
      await page.evaluate(t => window.__video.seek(t), ts);
      const f = path.join(DEST, `t${ts.toFixed(2).padStart(6, "0")}.png`);
      await page.screenshot({ path: f });
      console.log("wrote", path.relative(process.cwd(), f));
    }
    const info = await page.evaluate(() => ({ total: window.__video.total, missing: window.__video.missing, schedule: window.__video.schedule }));
    console.log(info.schedule.scenes.map(s => `${s.id} ${s.start.toFixed(2)}+${s.dur.toFixed(2)}`).join("  "));
    console.log("total", info.total.toFixed(2), "s; missing shots:", info.missing.length ? info.missing.join(", ") : "none");
  } else {
    const silent = path.join(DEST, "video-silent.mp4");
    let schedule, total, from = 0;
    if (REALTIME) {
      const dir = path.join(DEST, "rt"); fs.rmSync(dir, { recursive: true, force: true });
      const { ctx, page } = await openPage("autoplay=1&record=1", { recordVideo: { dir, size: { width: 1920, height: 1080 } } });
      ({ schedule, total } = await page.evaluate(() => ({ schedule: window.__video.schedule, total: window.__video.total })));
      await page.waitForFunction(() => window.__done === true, null, { timeout: (total + 30) * 1000 });
      const video = page.video(); await ctx.close();
      const webm = await video.path();
      // Trim the page-load lead-in: the clip ends when playback ends, so keep the last `total` seconds.
      await run("ffmpeg", ["-hide_banner", "-loglevel", "error", "-y", "-sseof", `-${total.toFixed(3)}`, "-i", webm,
        "-r", String(FPS), ...ENC, "-crf", "16", "-preset", opt("--preset", FAST ? "medium" : "slow"), silent]);
    } else {
      const { page } = await openPage("record=1&frames=1");
      ({ schedule, total } = await page.evaluate(() => ({ schedule: window.__video.schedule, total: window.__video.total })));
      from = Number(opt("--from", 0)); const to = Math.min(Number(opt("--to", total)), total);
      const n = Math.round((to - from) * FPS);
      console.log(`rendering ${n} frames at ${FPS} fps (${from}s → ${to.toFixed(2)}s)`);
      await run("ffmpeg", ["-hide_banner", "-loglevel", "error", "-y", "-f", "image2pipe", "-framerate", String(FPS), "-c:v", FAST ? "mjpeg" : "png", "-i", "-",
        ...ENC, "-crf", "16", "-preset", opt("--preset", FAST ? "medium" : "slow"), silent], {
        input: async stdin => {
          for (let i = 0; i < n; i++) {
            await page.evaluate(t => window.__video.seek(t), from + i / FPS);
            const buf = await page.screenshot(FAST ? { type: "jpeg", quality: 95, timeout: 0 } : { type: "png", timeout: 0 });
            if (!stdin.write(buf)) await new Promise(r => stdin.once("drain", r));
            if (i % (FPS * 5) === 0) process.stdout.write(`\r  ${(from + i / FPS).toFixed(1)}s`);
          }
          stdin.end(); process.stdout.write("\n");
        },
      });
    }
    const audio = await mixAudio(schedule, total);
    const final = path.join(DEST, "offset-product.mp4");
    await run("ffmpeg", ["-hide_banner", "-loglevel", "error", "-y", "-i", silent, "-ss", String(from), "-i", audio, "-map", "0:v", "-map", "1:a",
      "-c:v", "copy", "-c:a", "copy", "-shortest", "-movflags", "+faststart", final]);
    console.log("wrote", path.relative(process.cwd(), final), `(${total.toFixed(2)}s)`);
  }
} finally {
  if (errors.length) { console.error("console errors:\n  " + errors.join("\n  ")); process.exitCode = 1; }
  await browser.close(); server.close();
}
