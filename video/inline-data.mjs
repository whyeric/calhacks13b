#!/usr/bin/env node
// Copy assets/vo/timing.json and the highlight anchors from assets/shots.json into app.js,
// so index.html also works from file:// (where fetch() is blocked). Run after re-recording
// the VO (vo-sync.py) or re-capturing screenshots. Over http the page reads the live files anyway.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const read = p => JSON.parse(fs.readFileSync(path.join(HERE, p), "utf8"));
const timing = read("assets/vo/timing.json");
const shots = read("assets/shots.json");
const anchors = {};
for (const s of shots.shots || []) {
  if (!s.anchors) continue;
  anchors[s.file] = Object.fromEntries(Object.entries(s.anchors).map(([k, b]) => [k, [b.x, b.y, b.width, b.height]]));
}
const block = `// @inline-start (written by inline-data.mjs from assets/vo/timing.json and assets/shots.json)
let TIMING = ${JSON.stringify({ source: timing.source, full: timing.full, total: timing.total, scenes: timing.scenes.map(({ scene, file, duration, start }) => ({ scene, file, duration, start })) })};
let SHOTS = ${JSON.stringify({ dsf: shots.deviceScaleFactor || 2, anchors })};
// @inline-end`;
const app = path.join(HERE, "app.js");
const src = fs.readFileSync(app, "utf8");
const out = src.replace(/\/\/ @inline-start[\s\S]*?\/\/ @inline-end/, block);
if (out === src && !src.includes(block)) throw new Error("inline markers not found in app.js");
fs.writeFileSync(app, out);
console.log(`inlined ${timing.scenes.length} VO scenes, anchors for ${Object.keys(anchors).length} shots`);
