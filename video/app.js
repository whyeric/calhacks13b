// Offset product video: a seekable timeline of scenes on a 1920x1080 stage.
// Every frame is a pure function of time t, so scrubbing, playback and frame-by-frame
// recording all render the same picture. Motion supplies the easing curves and stagger.
// The engine only: timeline, player, controls. Scenes live in scenes/S01.js … S16.js and
// shared helpers in lib.js. Loaded as an ES module, so serve video/ over http (record.mjs does).
import { animate } from "https://cdn.jsdelivr.net/npm/motion@14.6.0/+esm";
import { EASE, clamp, Kit, SHOT_FILES, SHOT_META, shotSrc, DATA } from "./lib.js";
import S1 from "./scenes/S01.js";
import S2 from "./scenes/S02.js";
import S3 from "./scenes/S03.js";
import S4 from "./scenes/S04.js";
import S5 from "./scenes/S05.js";
import S6 from "./scenes/S06.js";
import S7 from "./scenes/S07.js";
import S8 from "./scenes/S08.js";
import S9 from "./scenes/S09.js";
import S10 from "./scenes/S10.js";
import S11 from "./scenes/S11.js";
import S12 from "./scenes/S12.js";
import S13 from "./scenes/S13.js";
import S14 from "./scenes/S14.js";
import S15 from "./scenes/S15.js";
import S16 from "./scenes/S16.js";

const Q = new URLSearchParams(location.search);
const AUTOPLAY = Q.has("autoplay"), RECORD = Q.has("record"), FRAMES = Q.has("frames");
if (RECORD) document.body.classList.add("record");

// ---------- Voiceover timing (assets/vo/timing.json, inlined so file:// works) ----------
// @inline-start (written by inline-data.mjs from assets/vo/timing.json and assets/shots.json)
let TIMING = {"source":"ai-tts","full":"vo/full.m4a","total":81.025,"scenes":[{"scene":"S1","file":"vo/S1.m4a","duration":1.889,"start":0},{"scene":"S2","file":"vo/S2.m4a","duration":2.412,"start":2.239},{"scene":"S3","file":"vo/S3.m4a","duration":3.236,"start":5.001},{"scene":"S4","file":"vo/S4.m4a","duration":3.487,"start":8.587},{"scene":"S5","file":"vo/S5.m4a","duration":3.889,"start":12.425},{"scene":"S6","file":"vo/S6.m4a","duration":4.745,"start":16.663},{"scene":"S7","file":"vo/S7.m4a","duration":6.138,"start":21.759},{"scene":"S8","file":"vo/S8.m4a","duration":6.288,"start":28.247},{"scene":"S9","file":"vo/S9.m4a","duration":4.68,"start":34.885},{"scene":"S10","file":"vo/S10.m4a","duration":7.776,"start":39.915},{"scene":"S11","file":"vo/S11.m4a","duration":8.562,"start":48.042},{"scene":"S12","file":"vo/S12.m4a","duration":2.273,"start":56.954},{"scene":"S13","file":"vo/S13.m4a","duration":3.411,"start":59.576},{"scene":"S14","file":"vo/S14.m4a","duration":7.01,"start":63.337},{"scene":"S15","file":"vo/S15.m4a","duration":7.42,"start":70.697},{"scene":"S16","file":"vo/S16.m4a","duration":2.558,"start":78.467}]};
let SHOTS = {"dsf":2,"anchors":{"shot-01-wizard-upload.png":{"upload_btn":[219,264,179,46],"status":[219,328,1002,26]},"shot-02-wizard-research-page.png":{},"shot-02-wizard-research-table.png":{"rain_row":[0,61,1582,90],"rain_train":[245,61,201,90],"rain_unseen":[446,61,201,90],"rain_verdict":[1128,71,57,26],"rain_kalshi":[1387,61,195,90]},"shot-02b-rain-row.png":{"rain_row":[10,10,1582,90],"rain_train":[255,10,201,90],"rain_unseen":[456,10,201,90],"rain_verdict":[1138,20,57,26],"rain_kalshi":[1397,10,195,90]},"shot-03-wizard-declined-list.png":{"knicks_rows":[16,82,1002,56]},"shot-03-wizard-risks-page.png":{},"shot-04-model-check.png":{"planted":[16,127,294,60],"interval":[16,197,294,52]},"shot-04-wizard-hedges-page.png":{},"shot-05-hedge-card-header.png":{"title":[8,48,312,21],"ticker":[8,84,294,17],"status_chip":[778,8,190,26]},"shot-06-hedge-card-full.png":{"title":[27,63,312,21],"ticker":[27,99,294,17],"buy_line":[27,130,960,50],"check_le":[271,677,228,39],"premium_col":[635,483,176,99],"expected_cost":[27,595,167,17],"approve_btn":[897,749,90,46],"status_chip":[797,23,190,26]},"shot-07-taxi-declined-card.png":{"reasons":[52,200,603,416],"compare":[52,258,603,51]},"shot-08-not-hedged-list.png":{"real_badge":[292,37,39,26],"not_hedged":[37,254,294,94],"planted":[37,479,294,60]},"shot-09-approve-hover.png":{"title":[27,63,312,21],"ticker":[27,99,294,17],"buy_line":[27,130,960,50],"check_le":[271,677,228,39],"premium_col":[635,483,176,99],"expected_cost":[27,595,167,17],"approve_btn":[897,749,90,46],"status_chip":[797,23,190,26]},"shot-10-approved-chip.png":{"status_chip":[883,23,104,26]},"shot-10-wizard-approved-page.png":{},"shot-11-dashboard-bike-page.png":{},"shot-11-decision-log.png":{"approval_entry":[37,112,413,134],"proposal_entry":[37,258,413,154]},"shot-12-dashboard-books-page.png":{},"shot-12-ledger.png":{"ledger_table":[37,172,659,577],"flagged_row":[720,355,659,34],"flag_note":[720,402,659,100],"sim_badge":[872,103,507,26]},"shot-13-dashboard-reconciled-page.png":{},"shot-13-reconcile.png":{"flagged_row":[8,221,659,34],"flag_note":[8,267,659,100],"sim_badge":[235,18,170,26]},"shot-14-labels.png":{"no_orders_badge":[1030,250,149,26],"real_badge":[362,100,39,26]},"shot-15-dashboard-wide.png":{}}};
// @inline-end
// Over http, prefer the live file so a re-recorded VO (vo-sync.py) is picked up without editing this.
if (location.protocol.startsWith("http")) {
  try { const r = await fetch("assets/vo/timing.json", { cache: "no-store" }); if (r.ok) TIMING = await r.json(); } catch {}
  try {
    const r = await fetch("assets/shots.json", { cache: "no-store" });
    if (r.ok) {
      const j = await r.json(), anchors = {};
      for (const s of j.shots || []) if (s.anchors)
        anchors[s.file] = Object.fromEntries(Object.entries(s.anchors).map(([k, b]) => [k, [b.x, b.y, b.width, b.height]]));
      SHOTS = { dsf: j.deviceScaleFactor || 2, anchors };
    }
  } catch {}
}
const VO = Object.fromEntries(TIMING.scenes.map(s => [s.scene, s]));
DATA.SHOTS = SHOTS;

const SCENES = [S1, S2, S3, S4, S5, S6, S7, S8, S9, S10, S11, S12, S13, S14, S15, S16];
// Padding around each AI voiceover clip, [lead before the VO, hold after it] in seconds. The only
// place scene length is set besides timing.json. Ignored for a "recorded" VO, which has its own pacing.
const HOLD_DEFAULT = [0.2, 0.35];
const HOLD = {
  S1: [0.5, 0.6],
  S7: [0.3, 0.9],    // camera reaches the FOUND verdict
  S8: [0.3, 0.9],    // "an honest check" needs a beat
  S10: [0.25, 1.5],  // let the payoff table land
  S11: [0.9, 2.0],   // beat of black before, hold on the decline after
  S12: [0.3, 1.2],   // cursor → click → approved
  S14: [0.2, 0.9],   // the fee connector lands late
  S16: [0.4, 2.2],   // logo close; the music's final chord blooms after "Your call."
};

// ---------- Timeline ----------
async function preload(files) {
  await Promise.all([...files].map(f => new Promise(res => {
    const im = new Image();
    im.onload = () => { SHOT_META[f] = { w: im.naturalWidth, h: im.naturalHeight, ok: true }; res(); };
    im.onerror = () => { SHOT_META[f] = { w: 3840, h: 2160, ok: false }; res(); };
    im.src = shotSrc(f);
  })));
}
// Shots referenced by scenes (preloaded so their aspect ratios are known when scenes build).
// Every shot in shots.json is preloaded so scenes can use any of them.
const NEEDED = [...Object.keys(SHOTS.anchors), "shot-01-wizard-upload.png", "shot-02-wizard-research-table.png", "shot-03-wizard-declined-list.png", "shot-04-model-check.png",
  "shot-06-hedge-card-full.png", "shot-07-taxi-declined-card.png", "shot-09-approve-hover.png", "shot-10-approved-chip.png",
  "shot-11-decision-log.png", "shot-12-ledger.png", "shot-14-labels.png"];
await Promise.all([preload(new Set(NEEDED)), document.fonts.ready]);

const stage = document.getElementById("stage");
// A "recorded" VO (vo-sync.py) has its own pacing: scenes start where timing.json says and
// full.m4a plays as one track. The AI placeholder VO is cut into clips and spaced by HOLD.
const RECORDED = TIMING.source === "recorded";
const XF = 0.5;        // default crossfade into a scene (s); a scene can set `transition: "cut"` or `{ xf }`
const OPEN_FADE = 0.3; // the first scene fades up from the stage colour (#112b1f)
const END_FADE = 1.0;  // fade to black at the very end
const END_TAIL = 1.0;  // recorded VO: time after the last word before the end
// `fadeIn: false` (or fade: { in: 0 }) is an alias for a cut into the scene.
const xfOf = sc => sc.transition === "cut" || sc.fadeIn === false || sc.fade?.in === 0 ? 0 : sc.transition?.xf ?? sc.fade?.in ?? XF;
let cursor = 0;
const timeline = SCENES.map((sc, i) => {
  const vo = VO[sc.id] || { duration: 3 };
  let start, dur, lead;
  if (RECORDED) {
    const next = VO[SCENES[i + 1]?.id];
    start = vo.start; lead = 0;
    dur = (next ? next.start : Math.max(TIMING.total ?? 0, vo.start + vo.duration) + END_TAIL) - start;
  } else {
    const [l, tail] = HOLD[sc.id] || HOLD_DEFAULT;
    start = cursor; lead = l; dur = lead + vo.duration + tail;
  }
  cursor = start + dur;
  const root = document.createElement("div"); root.className = "scene"; root.dataset.id = sc.id; stage.appendChild(root);
  const inner = document.createElement("div"); inner.className = "scene-in"; root.appendChild(inner);
  const k = new Kit(inner, dur, { lead, len: vo.duration });
  sc.build(k);
  if (i === SCENES.length - 1) k.tween(inner, { opacity: [1, 0] }, { at: dur - END_FADE, dur: END_FADE, ease: "move" });
  k.prepare();
  // Sound-design cues: static `cues` ({at: fraction of the scene, or s: seconds}) plus k.cue() calls.
  const cues = [...(sc.cues || []).map(c => ({ type: c.type, at: c.s ?? c.at * dur })), ...k.cues]
    .map(c => ({ ...c, t: start + c.at, scene: sc.id }));
  const audio = RECORDED ? null : new Audio("assets/" + (vo.file || `vo/${sc.id}.m4a`));
  if (audio) audio.preload = "auto";
  return { ...sc, start, dur, k, root, audio, cues, xf: i === 0 ? OPEN_FADE : xfOf(sc), voStart: start + lead, voDur: vo.duration, voFile: vo.file };
});
const TOTAL = cursor;
const FULL = RECORDED ? new Audio("assets/" + (TIMING.full || "vo/full.m4a")) : null;
if (FULL) FULL.preload = "auto";

// ---------- Player ----------
let t = 0, playing = false, anchor = 0, anchorT = 0, current = null;
const sceneAt = time => timeline.find(s => time >= s.start && time < s.start + s.dur) || timeline[timeline.length - 1];
const shown = new Set();
const openFade = document.createElement("div"); openFade.id = "openfade"; stage.appendChild(openFade);

// Cross-dissolve both ways: the incoming scene (opaque backdrop) eases in on top while the outgoing
// one, still rendering past its end, eases out over the first 60% of the overlap. Its text is gone
// before the incoming text is legible, and it is fully transparent before it is removed.
function render(time) {
  t = clamp(time, 0, TOTAL);
  const s = sceneAt(t), i = timeline.indexOf(s);
  current = s;
  const local = t - s.start, prev = i > 0 && local < s.xf ? timeline[i - 1] : null;
  const vis = new Set([s, prev].filter(Boolean));
  for (const o of shown) if (!vis.has(o)) { o.root.classList.remove("on"); shown.delete(o); }
  if (prev) {
    prev.root.classList.add("on"); prev.root.style.zIndex = 1; shown.add(prev);
    prev.root.style.opacity = 1 - EASE.move(clamp(local / (s.xf * 0.6), 0, 1));
    prev.k.render(t - prev.start);
  }
  s.root.classList.add("on"); s.root.style.zIndex = 2; shown.add(s);
  const p = s.xf > 0 ? EASE.move(clamp(local / s.xf, 0, 1)) : 1;
  // The first scene is drawn from frame 0 and a flat #112b1f veil lifts off it.
  if (i === 0) { s.root.style.opacity = 1; openFade.style.opacity = 1 - p; }
  else { s.root.style.opacity = p; openFade.style.opacity = 0; }
  s.k.render(local);
  ui();
}

function syncClip(audio, local, len) {
  if (playing && !RECORD && local >= 0 && local < len) {
    if (audio.paused) { audio.currentTime = local; audio.play().catch(() => {}); }
    else if (Math.abs(audio.currentTime - local) > 0.2) audio.currentTime = local;
  } else if (!audio.paused) audio.pause();
}
function syncAudio() {
  if (FULL) return syncClip(FULL, t, FULL.duration || TOTAL);
  for (const s of timeline) syncClip(s.audio, t - s.voStart, s.voDur);
}

function tick() {
  if (!playing) return;
  const now = performance.now() / 1000;
  const next = anchorT + (now - anchor);
  if (next >= TOTAL) { render(TOTAL); pause(); window.__done = true; return; }
  render(next); syncAudio();
  requestAnimationFrame(tick);
}
function play() {
  if (t >= TOTAL - 0.01) t = 0;
  playing = true; anchor = performance.now() / 1000; anchorT = t; overlay.hidden = true; ui(); syncAudio(); requestAnimationFrame(tick);
}
function pause() { playing = false; syncAudio(); ui(); }
function seek(time) { render(time); anchor = performance.now() / 1000; anchorT = t; syncAudio(); }

// ---------- Controls ----------
const overlay = document.getElementById("overlay"), pp = document.getElementById("pp"), track = document.getElementById("track");
const fill = track.querySelector(".fill"), knob = track.querySelector(".knob"), timeEl = document.getElementById("time"), nameEl = document.getElementById("scene-name");
const ICON_PLAY = '<svg viewBox="0 0 24 24"><path d="M7 4.5v15l13-7.5z" fill="currentColor"/></svg>';
const ICON_PAUSE = '<svg viewBox="0 0 24 24"><path d="M6 4h4v16H6zM14 4h4v16h-4z" fill="currentColor"/></svg>';
const fmt = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
let lastIcon = null;
function ui() {
  const p = (t / TOTAL) * 100;
  fill.style.width = p + "%"; knob.style.left = p + "%";
  timeEl.textContent = `${fmt(t)} / ${fmt(TOTAL)}`;
  if (current) nameEl.textContent = current.id;
  if (lastIcon !== playing) { pp.innerHTML = playing ? ICON_PAUSE : ICON_PLAY; lastIcon = playing; }
}
for (const s of timeline) {
  const m = document.createElement("div"); m.className = "mk"; m.style.left = (s.start / TOTAL) * 100 + "%";
  m.innerHTML = `<span>${s.id} · ${s.label}</span>`; track.appendChild(m);
}
const toggle = () => (playing ? pause() : play());
pp.onclick = toggle;
document.getElementById("bigplay").onclick = e => { e.stopPropagation(); unlockAudio(); play(); };
overlay.onclick = () => { unlockAudio(); play(); };
// iOS only lets an <audio> play later if it was started inside a user gesture once.
let unlocked = false;
function unlockAudio() {
  if (unlocked) return; unlocked = true;
  for (const a of FULL ? [FULL] : timeline.map(s => s.audio)) { a.muted = true; a.play().then(() => { a.pause(); a.muted = false; }).catch(() => { a.muted = false; }); }
}
let dragging = false, wasPlaying = false;
const scrubTo = e => { const r = track.getBoundingClientRect(); seek(clamp((e.clientX - r.left) / r.width, 0, 1) * TOTAL); };
track.addEventListener("pointerdown", e => { dragging = true; wasPlaying = playing; if (playing) pause(); track.setPointerCapture(e.pointerId); scrubTo(e); });
track.addEventListener("pointermove", e => dragging && scrubTo(e));
track.addEventListener("pointerup", () => { dragging = false; unlockAudio(); if (wasPlaying) play(); });
addEventListener("keydown", e => {
  if (e.code === "Space") { e.preventDefault(); unlockAudio(); toggle(); }
  else if (e.code === "ArrowRight" || e.code === "ArrowLeft") {
    e.preventDefault();
    const dir = e.code === "ArrowRight" ? 1 : -1;
    if (e.shiftKey) { // jump scene
      const i = timeline.indexOf(sceneAt(t)), j = clamp(i + (dir > 0 ? 1 : (t - timeline[i].start > 0.5 ? 0 : -1)), 0, timeline.length - 1);
      seek(timeline[j].start);
    } else seek(t + dir * 5);
  } else if (e.code === "Home") seek(0);
});
// Auto-hide controls while playing.
const controls = document.getElementById("controls");
let idleTimer;
const wake = () => { controls.classList.remove("idle"); clearTimeout(idleTimer); idleTimer = setTimeout(() => playing && controls.classList.add("idle"), 2200); };
addEventListener("pointermove", wake); addEventListener("keydown", wake);

// Fit the 1920x1080 stage to the window (letterboxed).
function fit() {
  const s = Math.min(innerWidth / 1920, innerHeight / 1080);
  stage.style.transform = `scale(${s}) translate(-50%, -50%)`;
}
addEventListener("resize", fit); fit();

// Controls fade in with Motion once the engine is ready.
animate(controls, { opacity: [0, 1] }, { duration: 0.4 });

// Hook for record.mjs: seek deterministically, read the schedule.
// Hook for record.mjs (and audio/mix.py via out/schedule.json): deterministic seek plus the
// schedule of VO clips and sound cues in absolute seconds.
window.__video = {
  total: TOTAL, seek: time => render(time), play, pause,
  schedule: {
    total: TOTAL, source: TIMING.source || "ai-tts",
    full: RECORDED ? "assets/" + (TIMING.full || "vo/full.m4a") : null,
    scenes: timeline.map(s => ({ id: s.id, label: s.label, start: s.start, dur: s.dur })),
    vo: timeline.map(s => ({ scene: s.id, file: "assets/" + (s.voFile || `vo/${s.id}.m4a`), start: s.voStart, duration: s.voDur })),
    cues: timeline.flatMap(s => s.cues).sort((p, q) => p.t - q.t),
  },
  missing: Object.entries(SHOT_META).filter(([, m]) => !m.ok).map(([f]) => f),
};
const startAt = parseFloat(Q.get("t") || "0");
render(startAt);
window.__ready = true;
if (FRAMES) { /* record.mjs drives __video.seek */ }
else if (AUTOPLAY) play();
else overlay.hidden = false;
