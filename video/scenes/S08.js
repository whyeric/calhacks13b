// S8 · Model check. "Knicks games? Nothing there. And a planted test effect lands inside the model's
// interval, so the check is honest."
// The declined list slides in with the Knicks rows ringed; then the taxi model-check panel swings in,
// a number line draws the 90% interval from the panel, and the planted $500 drops inside it.
// (The point estimate is off, so nothing here says the $500 was "found".)
import { clamp, caption, shot, A } from "../lib.js";
import { line } from "./S06.js";

// Word onsets in the VO clip (whisper): Knicks 0.00, nothing 0.86, planted 1.98, effect 2.56,
// lands 2.88, inside 3.28, interval 4.30, so 4.98, honest 5.70.
const W = { knicks: 0.0, nothing: 0.86, planted: 1.98, lands: 2.88, inside: 3.28, interval: 4.3, so: 4.98, honest: 5.7 };

// Values read off shot-04 (taxi model check).
const LO = -4085.85, HI = 796.42, PLANTED = 500;

export default {
  id: "S8",
  label: "Model check",
  build(k) {
    const at = w => k.vo.lead + W[w];
    const D = "shot-03-wizard-declined-list.png", M = "shot-04-model-check.png";

    // Both windows share a top (120) and a height (316): the list on the left, the model check right.
    const TOP = 120, H = 316;
    // Left: the declined list (step 2, bike shop), at about 1:1 of the 2x capture (≈ 30 px text).
    const L = shot(k, D, { x: 210, y: TOP, w: 920, h: H, chip: "Fictional shop", chipCls: "warn" });
    L.vp.style.background = "#fffefa";
    L.set([0, 0, 0.44, 1], { z: 2.0 });
    k.tween(L.win, { x: [-40, 0] }, { at: 0, dur: 0.8 });
    k.cue("whoosh", 0);
    L.ring(A(D, "knicks_rows_text", [16 / 1034, 85 / 154, 367 / 1034, 49 / 154]), at("knicks") + 0.1, at("planted") - 0.3, { pad: 10 });
    k.cue("tick", at("knicks") + 0.1);
    // It steps back once the model check takes over.
    k.tween(L.win, { opacity: [1, 0.5] }, { at: at("planted") - 0.2, dur: 0.6, ease: "move" });

    // Right: the taxi model check at its native 2x size (652 px), cropped to Planted → Coverage
    // (no title, no unrounded R²), sliding in from the right. It is a cross-check on the taxi data.
    const R = shot(k, M, { x: 1170, y: TOP, w: 654, h: H, chip: "Taxi fleet · real data", chipCls: "real" });
    R.set([0, 238 / 591, 1, 275 / 591], { z: 1 });
    R.vp.style.background = "#fffefa";
    // Slides in from the right (no tilt: brand.md, nothing spins).
    const tIn = at("nothing") + 0.55;
    k.tween(R.win, { x: [60, 0], opacity: [0, 1] }, { at: tIn, dur: 0.8 });
    k.cue("whoosh", tIn);
    const mbox = (x, y, w, h) => [x / 652, y / 591, w / 652, h / 591];
    // "Recovered −$1,644.72" stays visible but recedes, so $500 and the interval carry the frame.
    const veil = k.el("div", "abs", null, R.vp);
    const rec = mbox(190, 255, 300, 112);
    k.after(() => {
      const [x0, y0] = R.point(rec[0], rec[1]), [x1, y1] = R.point(rec[0] + rec[2], rec[1] + rec[3]);
      Object.assign(veil.style, { left: x0 + "px", top: y0 - 41 + "px", width: x1 - x0 + "px", height: y1 - y0 + "px", background: "rgba(255,254,250,0.6)" });
    });
    const planted = mbox(28, 300, 128, 62), interval = mbox(28, 396, 464, 40), coverage = mbox(28, 458, 318, 38);
    R.ring(planted, at("planted") + 0.05, null, { pad: 8 })
      .to(interval, at("lands") + 0.1, 0.6)
      .to(coverage, at("so") + 0.1, 0.6);
    k.cue("tick", at("planted") + 0.05);
    k.cue("tick", at("so") + 0.1);

    // A number line under the list: the 90% interval draws out, the planted $500 drops in inside it.
    const X0 = 230, X1 = 1110, Y = 620, vMin = -4600, vMax = 1300;
    const X = v => X0 + (v - vMin) / (vMax - vMin) * (X1 - X0);
    const g = k.svg(`<svg class="abs" width="1920" height="1080" viewBox="0 0 1920 1080" style="pointer-events:none">
      <line class="axis" x1="${X0}" y1="${Y}" x2="${X1}" y2="${Y}" stroke="#a4ada4" stroke-opacity="0.4" stroke-width="2"/>
      <g class="iv">
        <line class="bar" x1="${X(LO)}" y1="${Y}" x2="${X(HI)}" y2="${Y}" stroke="#f3f5ef" stroke-width="6" stroke-linecap="round"/>
        <line class="capl" x1="${X(LO)}" y1="${Y - 18}" x2="${X(LO)}" y2="${Y + 18}" stroke="#f3f5ef" stroke-width="4" stroke-linecap="round"/>
        <line class="capr" x1="${X(HI)}" y1="${Y - 18}" x2="${X(HI)}" y2="${Y + 18}" stroke="#f3f5ef" stroke-width="4" stroke-linecap="round"/>
      </g>
      <g class="pin">
        <line x1="${X(PLANTED)}" y1="${Y - 64}" x2="${X(PLANTED)}" y2="${Y - 14}" stroke="#F28C28" stroke-width="3"/>
        <circle cx="${X(PLANTED)}" cy="${Y}" r="13" fill="#F28C28" stroke="#0f1a14" stroke-width="4"/>
      </g>
    </svg>`);
    const bar = g.querySelector(".bar"), capl = g.querySelector(".capl"), capr = g.querySelector(".capr"), pin = g.querySelector(".pin");
    const label = (html, x, y, align, color = "var(--paper)") => {
      const e = k.el("div", "abs", html);
      Object.assign(e.style, { left: x + "px", top: y + "px", transform: align === "c" ? "translateX(-50%)" : align === "r" ? "translateX(-100%)" : "",
        font: "500 28px/1 var(--sans)", fontVariantNumeric: "tabular-nums", color, whiteSpace: "nowrap" });
      const wrap = k.el("div", "abs"); wrap.appendChild(e); return wrap;
    };
    const head = k.el("div", "eyebrow abs", "Taxi model check · 90% interval");
    Object.assign(head.style, { left: X0 + "px", top: Y - 130 + "px" });
    const lLo = label("−$4,085.85", X(LO), Y + 34, "l", "var(--muted-d)"), lHi = label("$796.42", X(HI), Y + 34, "r", "var(--muted-d)");
    const lPin = label(`Planted <b style="color:#F28C28;font-weight:500">$500</b>`, X(PLANTED), Y - 102, "r");

    const D0 = at("lands") - 0.05, mid = X((LO + HI) / 2), Iv = { p: 0 };
    k.enter(head, D0 - 0.25, { y: 8 });
    k.tween(g.querySelector(".axis"), { opacity: [0, 1] }, { at: D0 - 0.25, dur: 0.5 });
    k.tween(Iv, { p: [0, 1] }, { at: D0, dur: 0.8, ease: "move" });
    k.after(() => {
      const a = mid + (X(LO) - mid) * Iv.p, b = mid + (X(HI) - mid) * Iv.p;
      bar.setAttribute("x1", a); bar.setAttribute("x2", b);
      capl.setAttribute("transform", `translate(${a - X(LO)} 0)`); capr.setAttribute("transform", `translate(${b - X(HI)} 0)`);
      const vis = Iv.p > 0.001 ? 1 : 0; bar.style.opacity = vis; capl.style.opacity = vis; capr.style.opacity = vis;
    });
    k.enter(lLo, D0 + 0.5, { y: 8 }); k.enter(lHi, D0 + 0.55, { y: 8 });
    k.tween(pin, { opacity: [0, 1], y: [-40, 0] }, { at: at("inside"), dur: 0.55 });
    k.enter(lPin, at("inside") + 0.1, { y: -8 });
    k.cue("tick", at("inside") + 0.3);

    // Each caption starts only after the previous one has fully faded (out + 0.3 s).
    line(k, [["Knicks games:", at("knicks") + 0.05], ["*nothing there.*", at("nothing")]], at("planted") - 0.4);
    line(k, [["Taxi model check: a planted *$500*", at("planted")], ["lands inside the 90% interval.", at("lands")]], at("so") - 0.55);
    line(k, [["*Coverage 96%* over 50 trials:", at("so") + 0.05], ["an honest check.", at("honest") - 0.15]], k.dur - 0.3);
  },
};
