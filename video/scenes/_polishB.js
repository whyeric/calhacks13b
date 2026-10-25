// Helpers shared by S09–S16: scene CSS, image-space boxes, a ring that glides between targets,
// reveal pieces that live inside the camera (so they pan and zoom with the screenshot), a cursor.
import { SHOT_META, shotSrc } from "../lib.js";

// Scene-scoped styles (classes are prefixed pb-).
export const CSS = `
.pb-ring { position: absolute; border-radius: 10px; border: 3px solid var(--orange); pointer-events: none; opacity: 0; transform-origin: 50% 50%; }
.pb-ring.red { border-color: var(--neg); box-shadow: 0 0 0 6px rgba(170,80,55,0.18); }
.pb-ring.amber { border-color: var(--warn); box-shadow: 0 0 0 6px rgba(180,122,29,0.18); }
.pb-ring.green { border-color: var(--pos); box-shadow: 0 0 0 6px rgba(36,113,83,0.18); }
/* The dim is its own layer, eased separately so it never switches on in one frame. */
.pb-dim { position: absolute; border-radius: 10px; pointer-events: none; opacity: 0; box-shadow: 0 0 0 4000px rgba(15,26,20,0.42); }
.pb-piece { position: absolute; background-repeat: no-repeat; will-change: transform, opacity; }
.pb-cover { position: absolute; }
.pb-stamp { position: absolute; transform-origin: 50% 50%; white-space: nowrap; font: 600 30px/1 var(--mono); letter-spacing: 0.22em;
  text-transform: uppercase; padding: 14px 20px 14px 26px; border-radius: 8px; border: 4px solid currentColor;
  box-shadow: inset 0 0 0 3px rgba(255,255,255,0.0), 0 0 0 0 transparent; background: rgba(255,250,246,0.94); }
.pb-stamp::after { content: ""; position: absolute; inset: 5px; border: 1.5px solid currentColor; border-radius: 4px; opacity: 0.6; }
.pb-stamp.red { color: #aa5037; }
.pb-stamp.green { color: #247153; }
.pb-cursor { position: absolute; width: 40px; height: 52px; margin: -3px 0 0 -4px; transform-origin: 4px 3px; pointer-events: none;
  filter: drop-shadow(0 3px 6px rgba(15,26,20,0.35)); }
.pb-click { position: absolute; width: 90px; height: 90px; margin: -45px 0 0 -45px; border-radius: 50%; border: 3px solid var(--orange); opacity: 0; }
.pb-eq { position: absolute; display: flex; align-items: flex-end; gap: 28px; color: var(--paper); }
.pb-eq .term { display: flex; flex-direction: column; gap: 10px; }
.pb-eq .val { font: 500 68px/1 var(--mono); letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }
.pb-eq .lab { font: 500 24px/30px var(--sans); color: var(--muted-d); }
.pb-eq .le { font: 400 84px/1 var(--sans); color: var(--orange); padding-bottom: 46px; transform-origin: 50% 60%; }
.pb-eq .i1 { font: 600 18px/1 var(--sans); letter-spacing: 0.12em; text-transform: uppercase; color: #0f1a14; background: var(--orange);
  border-radius: 999px; padding: 8px 12px; align-self: center; margin-bottom: 46px; }
.pb-tag { position: absolute; font: 600 20px/1 var(--mono); padding: 8px 12px; border-radius: 8px; background: rgba(243,245,239,0.08);
  border: 1px solid rgba(243,245,239,0.24); color: var(--paper); white-space: nowrap; }
`;

// Scene styles (the engine paints each scene's backdrop, so crossfades are true dissolves).
export function style(k) { k.el("style", null, CSS); }

// Width and height (px at camera zoom 1) of a screenshot shown in a shot() window.
export function dims(s, file) {
  const m = SHOT_META[file] || { w: 3840, h: 2160 };
  return { W: s.vw, H: s.vw * m.h / m.w };
}
// Box in CSS px of the screenshot (as read off the 2x PNG / 2) → fractions of the image.
export function px(file, [x, y, w, h]) {
  const m = SHOT_META[file] || { w: 3840, h: 2160 };
  return [2 * x / m.w, 2 * y / m.h, 2 * w / m.w, 2 * h / m.h];
}
export const pad = ([x, y, w, h], fx, fy = fx) => [x - fx, y - fy, w + 2 * fx, h + 2 * fy];

// A div inside the camera covering image box [fx, fy, fw, fh] (moves and scales with the shot).
export function inCam(k, s, file, box, cls = "pb-piece") {
  const { W, H } = dims(s, file), [bx, by, bw, bh] = box;
  const d = k.el("div", cls, null, s.cam);
  Object.assign(d.style, { left: bx * W + "px", top: by * H + "px", width: bw * W + "px", height: bh * H + "px" });
  return d;
}
// Solid cover over a box (hides that part of the screenshot until revealed).
export function cover(k, s, file, box, bg = "#fffefa") {
  const c = inCam(k, s, file, box, "pb-cover"); c.style.background = bg; return c;
}
// A slice of the screenshot itself, laid exactly over its own place.
export function piece(k, s, file, box) {
  const { W, H } = dims(s, file), [bx, by] = box;
  const p = inCam(k, s, file, box);
  Object.assign(p.style, { backgroundImage: `url(${shotSrc(file)})`, backgroundSize: `${W}px ${H}px`, backgroundPosition: `${-bx * W}px ${-by * H}px` });
  return p;
}
// Reveal a region of the screenshot: covered until `at`, then its own pixels ease in (opacity + a short rise).
// The piece is the screenshot's own pixels in place, so once it lands the frame is the untouched capture.
export function reveal(k, s, file, box, at, { bg = "#fffefa", dy = 14, dur = 0.5 } = {}) {
  const c = cover(k, s, file, box, bg);
  const p = piece(k, s, file, box);
  k.tween(p, { opacity: [0, 1], y: [dy, 0] }, { at, dur });
  return { c, p };
}

// Highlight ring that can glide from one target to the next (one highlight at a time, per the brand).
export function glideRing(k, s, { color = "", pd = 8 } = {}) {
  const dim = k.el("div", "pb-dim", null, s.vp);
  const r = k.el("div", "pb-ring " + color, null, s.vp);
  const o = { o: 0, d: 0, s: 1.03, x: 0, y: 0, w: 0, h: 0 };
  let cur = null;
  const R = {
    el: r,
    // Appear on box at `at`.
    on(box, at) { cur = box; Object.assign(o, { x: box[0], y: box[1], w: box[2], h: box[3] });
      k.tween(o, { o: [0, 1], s: [1.04, 1], x: [box[0], box[0]], y: [box[1], box[1]], w: [box[2], box[2]], h: [box[3], box[3]] }, { at, dur: 0.4 });
      k.tween(o, { d: [0, 1] }, { at, dur: 0.3, ease: "move" }); return R; },
    // Glide to another box.
    to(box, at, dur = 0.6) { const a = cur; cur = box;
      k.tween(o, { x: [a[0], box[0]], y: [a[1], box[1]], w: [a[2], box[2]], h: [a[3], box[3]] }, { at, dur, ease: "move" }); return R; },
    // Hop to a box that isn't adjacent: fade out, jump, fade back in (never sweeps across other content).
    hop(box, at) { const a = cur; cur = box;
      k.tween(o, { o: [1, 0] }, { at, dur: 0.18, ease: "in" });
      k.tween(o, { x: [a[0], box[0]], y: [a[1], box[1]], w: [a[2], box[2]], h: [a[3], box[3]] }, { at: at + 0.18, dur: 0 });
      k.tween(o, { o: [0, 1], s: [1.04, 1] }, { at: at + 0.2, dur: 0.35 }); return R; },
    // Stamp-like settle (scale 1.06 → 1) at `at`.
    pop(at) { k.tween(o, { s: [1.06, 1] }, { at, dur: 0.3 }); return R; },
    off(at, dur = 0.3) { k.tween(o, { o: [1, 0] }, { at, dur, ease: "in" }); k.tween(o, { d: [1, 0] }, { at, dur: Math.max(dur, 0.3), ease: "move" }); return R; },
  };
  k.after(() => {
    const [x0, y0] = s.point(o.x, o.y), [x1, y1] = s.point(o.x + o.w, o.y + o.h);
    const box = { left: x0 - pd + "px", top: y0 - 41 - pd + "px", width: x1 - x0 + 2 * pd + "px", height: y1 - y0 + 2 * pd + "px" };
    Object.assign(r.style, box, { opacity: o.o, transform: `scale(${o.s})` });
    Object.assign(dim.style, box, { opacity: o.d });
  });
  return R;
}

// Pointer cursor drawn over a shot (position in image fractions, tracks the camera).
export function cursor(k, s) {
  const c = k.el("div", "pb-cursor", `<svg width="40" height="52" viewBox="0 0 17 22"><path d="M1.5 1.5v16.2l4.1-3.9 2.7 6.2 2.9-1.3-2.7-6.1h5.7z" fill="#fff" stroke="#0f1a14" stroke-width="1.3" stroke-linejoin="round"/></svg>`, s.vp);
  const o = { x: 0.5, y: 0.5, o: 0, s: 1 };
  k.after(() => { const [x, y] = s.point(o.x, o.y); Object.assign(c.style, { left: x + "px", top: y - 41 + "px", opacity: o.o, transform: `scale(${o.s})` }); });
  return o;
}

// Sound cue (no-op until the engine provides k.cue).
export const cue = (k, name, at) => { if (typeof k.cue === "function") k.cue(name, at); };
