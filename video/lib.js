// Shared engine pieces for the Offset video: easing, the seekable tween Kit, and the
// building blocks scenes use (captions, screenshot windows, crops, the rail, the logo).
import { stagger, cubicBezier } from "https://cdn.jsdelivr.net/npm/motion@14.6.0/+esm";
export { stagger };

// Filled by app.js before scenes build: highlight anchors from assets/shots.json.
export const DATA = { SHOTS: { dsf: 2, anchors: {} } };

// ---------- Easing & tween engine ----------
export const EASE = {
  out: cubicBezier(0.22, 1, 0.36, 1),   // entrances
  in: cubicBezier(0.64, 0, 0.78, 0),    // exits
  move: cubicBezier(0.65, 0, 0.35, 1),  // moves between positions
  linear: p => p,
};
export const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
export const lerp = (a, b, p) => a + (b - a) * p;
export const TRANSFORM = new Set(["x", "y", "scale", "rotate"]);

export class Kit {
  constructor(root, dur, vo) { this.root = root; this.dur = dur; this.vo = vo; this.tracks = []; this.fns = []; this.afters = []; this.cues = []; this.pre = []; this.caps = {}; }
  // Sound-design cue at scene-local seconds: "whoosh" | "tick" | "stamp" | "click" | "count" | "logo".
  cue(type, at) { this.cues.push({ type, at }); }
  // Time helpers: v(f) is f of the way through this scene's voiceover.
  v(f) { return this.vo.lead + f * this.vo.len; }
  el(tag, cls, html, parent = this.root) {
    const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; parent.appendChild(e); return e;
  }
  svg(markup, parent = this.root) {
    const wrap = document.createElement("div"); wrap.innerHTML = markup.trim(); const s = wrap.firstChild; parent.appendChild(s); return s;
  }
  tween(target, props, { at = 0, dur = 0.5, ease = "out" } = {}) {
    for (const [k, [a, b]] of Object.entries(props)) this.tracks.push({ target, k, a, b, at, dur, ease: EASE[ease] || ease });
    return at + dur;
  }
  enter(el, at, { y = 12, dur = 0.5, from = 0 } = {}) { this.tween(el, { opacity: [from, 1], y: [y, 0] }, { at, dur }); }
  exit(el, at, { dur = 0.3 } = {}) { this.tween(el, { opacity: [1, 0] }, { at, dur, ease: "in" }); }
  fn(at, dur, f, ease = "out") { this.fns.push({ at, dur, f, ease: EASE[ease] || ease }); }
  after(f) { this.afters.push(f); }
  prepare() {
    for (const f of this.pre) f();  // deferred builders that need the whole scene (e.g. rings vs camera moves)
    const groups = new Map();
    for (const tr of this.tracks) {
      let byTarget = groups.get(tr.target); if (!byTarget) groups.set(tr.target, byTarget = new Map());
      let list = byTarget.get(tr.k); if (!list) byTarget.set(tr.k, list = []); list.push(tr);
    }
    for (const byTarget of groups.values()) for (const list of byTarget.values()) list.sort((p, q) => p.at - q.at);
    this.groups = groups;
  }
  render(t) {
    for (const [target, byTarget] of this.groups) {
      const vals = {};
      for (const [k, list] of byTarget) {
        // The latest track that has started owns the property; before any start, the first track's "from".
        let tr = list[0]; for (const c of list) if (c.at <= t) tr = c;
        const p = tr.dur > 0 ? clamp((t - tr.at) / tr.dur, 0, 1) : (t >= tr.at ? 1 : 0);
        vals[k] = lerp(tr.a, tr.b, tr.ease(p));
      }
      apply(target, vals);
    }
    for (const { at, dur, f, ease } of this.fns) f(ease(dur > 0 ? clamp((t - at) / dur, 0, 1) : (t >= at ? 1 : 0)), t);
    for (const f of this.afters) f(t);
  }
}

export function apply(target, v) {
  if (!(target instanceof Element)) { Object.assign(target, v); return; }
  const s = target.style, st = target.__st || (target.__st = { x: 0, y: 0, scale: 1, rotate: 0 });
  let tf = false;
  for (const k in v) {
    const val = v[k];
    if (TRANSFORM.has(k)) { st[k] = val; tf = true; }
    else if (k === "opacity") s.opacity = val;
    else if (k === "brightness") s.filter = `brightness(${val})`;
    else if (k === "clipR") s.clipPath = `inset(-20px ${val}% -20px -20px)`;
    else if (k === "dash") s.strokeDashoffset = 1 - val;
    else if (k === "w") s.width = val + "px";
    else if (k.startsWith("--")) s.setProperty(k, val);
    else s[k] = val + "px";
  }
  if (tf) s.transform = `translate3d(${st.x}px, ${st.y}px, 0) scale(${st.scale}) rotate(${st.rotate}deg)`;
}

// ---------- Shared pieces ----------
export const SHOT_FILES = new Set();
export const SHOT_META = {}; // file -> {w, h, ok}
export const shotSrc = f => "assets/" + f;
// Box (fractions of the image) for a named element from shots.json anchors, else the fallback.
// Fractions are relative to the shot's own image; ring() rescales when a shot shows a different file.
// `base`: express the box in another shot's fractions (for a swapped-in layer; both are width-fit).
export function A(file, name, fallback, { base } = {}) {
  const a = DATA.SHOTS.anchors?.[file]?.[name], m = SHOT_META[file];
  if (!a || !m?.ok) return fallback;
  const d = DATA.SHOTS.dsf, b = base ? SHOT_META[base] : m, hy = m.w * b.h / b.w;
  return [a[0] * d / m.w, a[1] * d / hy, a[2] * d / m.w, a[3] * d / hy];
}

// Kinetic caption. "{-$1,955.68}" counts up from zero (tabular mono); "*word*" is emphasis.
export function caption(k, text, at, out, { cls = "cap", parent, wordStagger = 0, y = 12 } = {}) {
  // Swap guard: a caption on the same line (same cls) never enters until the previous one has faded out.
  const prev = k.caps[cls];
  if (prev && prev.out != null && at >= prev.at && at < prev.out + 0.3) {
    at = prev.out + 0.3;
    if (out != null && out < at + 0.6) out = at + 0.6;
  }
  k.caps[cls] = { at, out };
  const el = k.el("div", cls, null, parent);
  const st = stagger(wordStagger);
  const tokens = text.match(/\*[^*]*\*\S*|\S+/g);
  tokens.forEach((tok, i) => {
    const w = k.el("span", "w", null, el);
    const em = tok.match(/^\*([^*]*)\*(.*)$/);
    const host = em ? k.el("em", null, null, w) : w;
    const body = em ? em[1] : tok;
    const num = body.match(/^(.*?)\{([^}]*)\}(.*)$/);
    if (num) {
      const [, before, inner, rest] = num;
      if (before) host.append(before);
      const n = k.el("span", "num", inner, host); if (rest) host.append(rest);
      const m = inner.match(/^([^\d]*)([\d,]*\.?\d+)(.*)$/);
      if (m) {
        const [, pre, digits, post] = m, to = parseFloat(digits.replace(/,/g, "")), dec = (digits.split(".")[1] || "").length;
        const fmt = x => pre + x.toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec }) + post;
        k.fn(at + st(i, tokens.length), 0.8, p => { n.textContent = fmt(to * p); });
        if (!el.dataset.cued) { k.cue("count", at + st(i, tokens.length)); el.dataset.cued = 1; }  // one per caption
      }
    } else host.textContent = body;
    if (em && em[2]) w.append(em[2]);
    if (i < tokens.length - 1) w.append(" ");
    k.tween(w, { opacity: [0, 1], y: [y, 0] }, { at: at + st(i, tokens.length), dur: 0.5 });
  });
  if (out != null) k.exit(el, out);
  return el;
}

// Browser-window frame around a screenshot, with a camera that focuses on boxes in the image
// (fractions 0..1 of the image) and highlight rings that track the camera.
export function shot(k, file, { x = 210, y = 72, w = 1500, h = 760, chip, chipCls = "warn", url = "localhost · Offset", parent } = {}) {
  SHOT_FILES.add(file);
  const win = k.el("div", "win will", null, parent);
  Object.assign(win.style, { left: x + "px", top: y + "px", width: w + "px", height: h + "px" });
  const bar = k.el("div", "bar", "<i></i><i></i><i></i>", win);
  k.el("span", "url", url, bar);
  if (chip) k.el("span", "chip " + chipCls, chip, bar);
  const vw = w - 2, vh = h - 41;
  const vp = k.el("div", "vp", null, win); Object.assign(vp.style, { width: vw + "px", height: vh + "px" });
  const cam = k.el("div", "cam", null, vp);
  const layers = [];
  const addLayer = f => {
    const meta = SHOT_META[f] || { w: 3840, h: 2160, ok: false };
    let node;
    if (meta.ok) { node = k.el("img", null, null, cam); node.src = shotSrc(f); node.alt = ""; }
    else { node = k.el("div", "ph", `<div class="phbar">Offset</div><div class="phlabel">${f}<br>(screenshot placeholder)</div>`, cam); }
    node.style.width = vw + "px"; node.style.height = vw * meta.h / meta.w + "px";
    node.style.containerType = "inline-size";
    layers.push({ f, node, ar: meta.h / meta.w });
    return node;
  };
  addLayer(file);
  const ar = layers[0].ar, dispW = vw, dispH = vw * ar;
  // Start framed on the top of the image.
  const cs = { z: 1, cx: 0.5, cy: 0, kb: 1 };
  const S = { win, vp, cam, vw, vh, cs, state: { z: 1, cx: 0.5, cy: 0 }, rings: [], moves: [] };
  // S.settle(t): t, or the end of the camera move it falls in. Only valid inside k.pre hooks or after
  // all focus() calls; ring() applies it automatically.
  S.settle = t => { for (const [m0, m1] of S.moves) if (t > m0 - 0.05 && t < m1) t = m1; return t; };
  const view = () => {
    const z = cs.z * cs.kb, iw = dispW * z, ih = dispH * z;
    let tx = vw / 2 - cs.cx * iw, ty = vh / 2 - cs.cy * ih;
    tx = iw <= vw ? (vw - iw) / 2 : clamp(tx, vw - iw, 0);
    ty = ih <= vh ? (vh - ih) / 2 : clamp(ty, vh - ih, 0);
    return { z, tx, ty };
  };
  // Move the camera so box [bx,by,bw,bh] fills `fill` of the viewport (zoom capped at maxZ).
  S.focus = (box, at, dur = 0.9, { fill = 0.8, maxZ = 2.6, minZ = 1, ease = "move", z: forceZ } = {}) => {
    const [bx, by, bw, bh] = box;
    const z = forceZ ?? clamp(Math.min(vw * fill / (bw * dispW), vh * fill / (bh * dispH)), minZ, maxZ);
    const to = { z, cx: bx + bw / 2, cy: by + bh / 2 };
    k.tween(cs, { z: [S.state.z, to.z], cx: [S.state.cx, to.cx], cy: [S.state.cy, to.cy] }, { at, dur, ease });
    if (dur > 0) S.moves.push([at, at + dur]);
    S.state = to;
  };
  S.set = (box, opts) => S.focus(box, -1, 0, opts);
  S.kenburns = (from = 1, to = 1.04) => k.tween(cs, { kb: [from, to] }, { at: 0, dur: k.dur, ease: "linear" });
  // Highlight ring around box. The dim (an outer shadow on its own layer) eases in evenly over
  // 0.3 s; the ring itself fades and settles from 1.03x. Both track the camera.
  S.ring = (box, at, until, { color = "", pad = 8 } = {}) => {
    const d = k.el("div", "dim", null, vp), r = k.el("div", "ring " + color, null, vp);
    const o = { o: 0, d: 0, s: 1.03 };
    // Registered at prepare time so every camera move is known: a ring that would start during a
    // focus() move waits for the camera to settle, so it never lands on content still in motion.
    k.pre.push(() => {
      const a = S.settle(at);
      const u = until == null ? null : Math.max(until, a + 0.6);
      k.tween(o, { d: [0, 1] }, { at: a, dur: 0.3, ease: "move" });
      k.tween(o, { o: [0, 1], s: [1.03, 1] }, { at: a, dur: 0.4 });
      if (u != null) k.tween(o, { o: [1, 0], d: [1, 0] }, { at: u, dur: 0.3, ease: "move" });
    });
    // ring.to(box2, at, dur, { color }): glide this ring to another box ("move" ease) instead of
    // fading one out and another in. Chainable; moves apply in time order.
    const moves = [];
    r.to = (to, mAt, mDur = 0.6, { color: c } = {}) => { moves.push({ to, at: mAt, dur: mDur, color: c }); moves.sort((p, q) => p.at - q.at); return r; };
    k.after(t => {
      let b = box, cls = color;
      for (const m of moves) {
        if (t < m.at) break;
        const p = EASE.move(clamp((t - m.at) / m.dur, 0, 1));
        b = b.map((v, i) => lerp(v, m.to[i], p));
        if (m.color != null) cls = m.color;
      }
      const cn = "ring " + cls; if (r.className !== cn) r.className = cn;
      const { z, tx, ty } = view(); const [bx, by, bw, bh] = b;
      const L = tx + bx * dispW * z - pad, T = ty + by * dispH * z - pad, W = bw * dispW * z + pad * 2, H = bh * dispH * z + pad * 2;
      const size = { width: W + "px", height: H + "px" };
      Object.assign(d.style, size, { opacity: o.d, transform: `translate3d(${L}px, ${T}px, 0)` });
      Object.assign(r.style, size, { opacity: o.o, transform: `translate3d(${L}px, ${T}px, 0) scale(${o.s})` });
    });
    return r;
  };
  // Screen position (stage px, relative to the window) of a point in the image.
  S.point = (fx, fy) => { const { z, tx, ty } = view(); return [tx + fx * dispW * z, 41 + ty + fy * dispH * z]; };
  // Crossfade to another screenshot (same framing).
  S.swap = (f, at) => { const n = addLayer(f); n.style.opacity = 0; k.tween(n, { opacity: [0, 1] }, { at, dur: 0.25 }); };
  k.after(() => { const { z, tx, ty } = view(); cam.style.transform = `translate3d(${tx}px, ${ty}px, 0) scale(${z})`; });
  return S;
}

// Static crop of a screenshot region, scaled to width w.
export function crop(k, file, box, { x, y, w, parent }) {
  SHOT_FILES.add(file);
  const meta = SHOT_META[file] || { w: 3840, h: 2160, ok: false };
  const [bx, by, bw, bh] = box, iw = w / bw, ih = iw * meta.h / meta.w, h = bh * ih;
  const c = k.el("div", "crop will", null, parent);
  Object.assign(c.style, { left: x + "px", top: y + "px", width: w + "px", height: h + "px" });
  const img = meta.ok ? k.el("img", null, null, c) : k.el("div", "ph", `<div class="phlabel">${file}</div>`, c);
  if (meta.ok) img.src = shotSrc(file);
  Object.assign(img.style, { width: iw + "px", height: ih + "px", left: -bx * iw + "px", top: -by * ih + "px" });
  return c;
}

// Pad a box by f of its size on every side.
export const grow = ([x, y, w, h], f) => [x - w * f, y - h * f, w * (1 + 2 * f), h * (1 + 2 * f)];

export const LOGO = (size, id = "") => `<svg ${id} width="${size}" height="${size}" viewBox="0 0 64 64" aria-label="Offset">
  <path class="lo" pathLength="1" d="M32 4 L56 12 V30 C56 45 46 55 32 60 C18 55 8 45 8 30 V12 Z" fill="none" stroke="#F28C28" stroke-width="5" stroke-linejoin="round" stroke-dasharray="1"/>
  <path class="lf" d="M32 4 L8 12 V30 C8 45 18 55 32 60 Z" fill="#F28C28"/></svg>`;

// Deterministic pseudo-random for motion graphics.
export const rand = (i, s = 1) => { const x = Math.sin(i * 127.1 + s * 311.7) * 43758.5453; return x - Math.floor(x); };

// S4/S5: shield, then the Measure → Match → Propose rail; S5 adds the owner pill.
export function rail(k, part) {
  const logo = k.el("div", "abs", LOGO(120)); Object.assign(logo.style, { left: "160px", top: "150px" });
  const lo = logo.querySelector(".lo"), lf = logo.querySelector(".lf");
  const word = k.el("div", "hero abs", "Offset"); Object.assign(word.style, { left: "310px", top: "160px", color: "#f3f5ef" });
  const steps = ["Measure", "Match", "Propose", "You decide"], xs = [160, 520, 860, 1240], ws = [300, 280, 320, 340];
  const pills = steps.map((s, i) => {
    const p = k.el("div", "pill" + (i === 3 ? " owner" : ""), `${s}<div class="lit">${s}</div>`);
    Object.assign(p.style, { left: xs[i] + "px", top: "540px", width: ws[i] + "px" });
    if (i < 3) { const a = k.el("div", "abs", "→"); Object.assign(a.style, { left: xs[i] + ws[i] + 14 + "px", top: "550px", font: "400 40px/52px var(--sans)", color: "#a4ada4" });
      if (part === 0 && i === 2) a.style.display = "none";
      if (part === 1 && i === 2) k.tween(a, { opacity: [0, 1] }, { at: k.v(0.75), dur: 0.4 }); }
    return p;
  });
  const lit = i => pills[i].querySelector(".lit");
  if (part === 0) {
    k.tween(logo, { opacity: [0, 1] }, { at: 0, dur: 0.3 });
    k.tween(lo, { dash: [0, 1] }, { at: 0.05, dur: 1.0, ease: "move" });
    k.tween(lf, { opacity: [0, 1] }, { at: 0.7, dur: 0.5 });
    k.tween(word, { clipR: [100, 0] }, { at: 0.5, dur: 0.8, ease: "move" });
    const st = stagger(0.08);
    for (let i = 0; i < 3; i++) k.enter(pills[i], k.v(0.25) + st(i, 3));
    pills[3].style.display = "none";
    k.tween(lit(0), { opacity: [0, 1] }, { at: k.v(0.4), dur: 0.3 });
    caption(k, "Measures the swing in *real dollars*, from your own revenue", k.v(0.45), null);
  } else {
    lit(0).style.opacity = 1;
    k.tween(lit(1), { opacity: [0, 1] }, { at: k.v(0.12), dur: 0.3 });
    k.tween(lit(2), { opacity: [0, 1] }, { at: k.v(0.45), dur: 0.3 });
    k.tween(pills[3], { opacity: [0, 1], scale: [0.96, 1] }, { at: k.v(0.78), dur: 0.25 });
    k.tween(lit(3), { opacity: [0, 1] }, { at: k.v(0.82), dur: 0.3 });
    caption(k, "A *Kalshi* contract that pays when it hits", k.v(0.1), k.v(0.72));
    caption(k, "*You decide.*", k.v(0.78), null);
  }
}
