// S4 · Principles. "Offset is built on four principles. Measured, not guessed. Built for steady income.
// The owner's call, every time. And interpretable, human-facing."
// The shield and a title, then all four principles (the slide's exact wording) in a 2 x 2 grid. All four
// stay up for the whole line; each card's number lights orange as the VO names it, then they all rest even.
import { caption, LOGO, PRINCIPLES } from "../lib.js";

// Word onsets after the speech starts (user.m4a; phrase pauses from silencedetect, words spread within a phrase): principles 1.25,
// Measured 2.38, Built 3.85, The (owner's) 5.43, And (interpretable) 7.20.
const W = { principles: 1.25, p1: 2.38, p2: 3.85, p3: 5.43, p4: 7.2 };

const X = 160, Y = 330, CW = 776, CH = 270, GX = 48, GY = 40;

export default {
  id: "S4",
  label: "Principles",
  build(k) {
    const at = w => k.vo.lead + W[w];

    const head = k.el("div", "abs");
    Object.assign(head.style, { left: X + "px", top: "128px", display: "flex", alignItems: "center", gap: "28px" });
    const mark = k.el("div", null, LOGO(84), head);
    mark.querySelector(".lo").style.strokeDasharray = "none";
    const title = caption(k, "Built on *four principles*", 0.15, null, { cls: "section", parent: head, y: 12 });
    Object.assign(title.style, { position: "relative", fontSize: "72px", lineHeight: "80px", color: "#f3f5ef" });
    k.tween(mark, { opacity: [0, 1], scale: [0.96, 1] }, { at: 0.05, dur: 0.5 });
    k.cue("whoosh", 0);

    const cards = PRINCIPLES.map((p, i) => {
      const c = k.el("div", "abs will");
      Object.assign(c.style, { left: X + (i % 2) * (CW + GX) + "px", top: Y + Math.floor(i / 2) * (CH + GY) + "px", width: CW + "px", height: CH + "px",
        padding: "34px 38px", borderRadius: "18px", background: "rgba(243,245,239,0.05)", border: "1.5px solid rgba(243,245,239,0.16)" });
      const num = k.el("div", null, `#${p.n}`, c);
      Object.assign(num.style, { font: "500 28px/1 var(--mono)", color: "var(--muted-d)", marginBottom: "18px" });
      const name = k.el("div", null, p.name, c);
      Object.assign(name.style, { font: "600 46px/54px var(--serif)", letterSpacing: "-0.015em", color: "#f3f5ef", marginBottom: "16px" });
      const body = k.el("div", null, p.body, c);
      Object.assign(body.style, { font: "400 28px/38px var(--sans)", color: "var(--muted-d)" });
      // All four arrive together before the first is named (60-80 ms sibling stagger).
      k.enter(c, at("principles") - 0.55 + i * 0.07, { y: 16, dur: 0.55 });
      return { c, num };
    });

    // The named card lights (orange number, brighter edge); it settles back as the next is named.
    const beats = [at("p1"), at("p2"), at("p3"), at("p4")], rest = k.dur - 0.6;
    cards.forEach(({ c, num }, i) => {
      const on = beats[i], off = i < 3 ? beats[i + 1] : rest;
      const L = { v: 0 };
      k.tween(L, { v: [0, 1] }, { at: on - 0.1, dur: 0.35, ease: "move" });
      k.tween(L, { v: [1, 0] }, { at: off - 0.1, dur: 0.45, ease: "move" });
      k.cue("tick", on - 0.1);
      k.after(() => {
        num.style.color = L.v > 0.5 ? "#F28C28" : "var(--muted-d)";
        c.style.borderColor = `rgba(242,140,40,${(0.16 + 0.64 * L.v).toFixed(3)})`;
        c.style.background = `rgba(243,245,239,${(0.05 + 0.04 * L.v).toFixed(3)})`;
      });
    });
  },
};
