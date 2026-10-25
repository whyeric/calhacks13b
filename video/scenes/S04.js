// S4 · Measure. "Offset measures that swing in real dollars, from your own revenue."
// The shield draws on, the wordmark wipes in, and the Measure → Match → Propose rail staggers in
// with Measure lit. S5 cuts in on exactly this end frame (it imports the layout from here).
import { caption, LOGO } from "../lib.js";

// Word onsets in the VO clip (whisper): Offset 0.00, measures 0.32, swing 0.92, real 1.32, own 2.66.
const W = { offset: 0.0, measures: 0.32, swing: 0.92, real: 1.32, own: 2.66 };

export const STEPS = ["Measure", "Match", "Propose", "You decide"];
const WIDTHS = [264, 224, 254, 290], GAP = 96, PILL_Y = 560;
// Left edge of each pill when the row holds n pills, centred on the stage.
export function rowX(n) {
  const total = WIDTHS.slice(0, n).reduce((a, b) => a + b, 0) + GAP * (n - 1);
  let x = (1920 - total) / 2;
  return WIDTHS.map(w => { const at = x; x += w + GAP; return at; });
}

// The lockup and the rail, positioned for a row of `n` pills. Returns handles for animating.
export function buildRail(k, n) {
  const lock = k.el("div", "abs");
  Object.assign(lock.style, { left: 0, width: "1920px", top: "250px", display: "flex", justifyContent: "center", alignItems: "center", gap: "30px" });
  const mark = k.el("div", null, LOGO(116), lock);
  const word = k.el("div", "hero", "Offset", lock);
  Object.assign(word.style, { color: "#f3f5ef", fontSize: "112px", lineHeight: "1" });

  const row = k.el("div", "abs will"); Object.assign(row.style, { left: 0, top: 0, width: "1920px", height: "1080px" });
  const xs = rowX(n);
  const pills = STEPS.map((s, i) => {
    const p = k.el("div", "pill will" + (i === 3 ? " owner" : ""), `${s}<div class="lit">${s}</div>`, row);
    Object.assign(p.style, { left: xs[i] + "px", top: PILL_Y + "px", width: WIDTHS[i] + "px", padding: 0 });
    return p;
  });
  const links = [0, 1, 2].map(i => {
    const l = k.el("div", "abs", null, row);
    Object.assign(l.style, { left: xs[i] + WIDTHS[i] + 14 + "px", top: PILL_Y + 37 + "px", width: GAP - 28 + "px", height: "2px",
      background: "rgba(243,245,239,0.35)", borderRadius: "1px" });
    const dot = k.el("div", "abs", null, row);
    Object.assign(dot.style, { left: xs[i] + WIDTHS[i] + 8 + "px", top: PILL_Y + 32 + "px", width: "12px", height: "12px",
      borderRadius: "50%", background: "#F28C28", opacity: 0, boxShadow: "0 0 14px 4px rgba(242,140,40,0.45)" });
    return { l, dot };
  });
  const lit = i => pills[i].querySelector(".lit");
  // Light pill i, with a spark travelling along the link into it.
  const light = (i, t) => {
    if (i > 0) {
      const { dot } = links[i - 1];
      k.tween(dot, { opacity: [0, 1] }, { at: t - 0.42, dur: 0.12 });
      k.tween(dot, { x: [0, GAP - 16] }, { at: t - 0.42, dur: 0.42, ease: "move" });
      k.tween(dot, { opacity: [1, 0] }, { at: t - 0.05, dur: 0.2, ease: "in" });
    }
    k.tween(lit(i), { opacity: [0, 1] }, { at: t, dur: 0.35 });
    k.tween(pills[i], { scale: [1, 1.04] }, { at: t, dur: 0.18, ease: "move" });
    k.tween(pills[i], { scale: [1.04, 1] }, { at: t + 0.18, dur: 0.4, ease: "move" });
    k.cue("tick", t);
  };
  return { lock, mark, word, row, pills, links, lit, light, lo: mark.querySelector(".lo"), lf: mark.querySelector(".lf") };
}

export default {
  id: "S4",
  label: "Measure",
  build(k) {
    const at = w => k.vo.lead + W[w];
    const R = buildRail(k, 3);
    R.pills[3].style.display = "none";
    R.links[2].l.style.display = "none";

    // Shield draws on with the first word, then fills; the wordmark wipes in beside it.
    k.tween(R.mark, { opacity: [0, 1], scale: [0.94, 1] }, { at: 0.15, dur: 0.7 });
    k.tween(R.lo, { dash: [0, 1] }, { at: 0.2, dur: 0.9, ease: "move" });
    k.tween(R.lf, { opacity: [0, 1] }, { at: 0.7, dur: 0.5 });
    k.tween(R.word, { clipR: [100, 0] }, { at: 0.42, dur: 0.8, ease: "move" });
    k.cue("logo", 0.2);

    // Rail staggers in, links draw between the pills.
    [0, 1, 2].forEach(i => k.enter(R.pills[i], at("measures") - 0.15 + i * 0.08, { y: 16, dur: 0.55 }));
    [0, 1].forEach(i => k.tween(R.links[i].l, { clipR: [100, 0] }, { at: at("measures") + 0.05 + i * 0.08, dur: 0.5, ease: "move" }));
    R.light(0, at("measures") + 0.25);

    const cap = caption(k, "The swing, in *real dollars,*", at("swing"), k.dur - 0.32, { wordStagger: 0.08 });
    Object.assign(cap.style, { left: 0, width: "1920px", top: "720px", textAlign: "center", fontSize: "48px", lineHeight: "60px" });
    const cap2 = caption(k, "from your own revenue.", at("own") - 0.15, k.dur - 0.32, { wordStagger: 0.08 });
    Object.assign(cap2.style, { left: 0, width: "1920px", top: "788px", textAlign: "center", fontSize: "40px", color: "var(--muted-d)" });
  },
};
