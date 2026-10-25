// S15 · Trust. Three lines set in the display face, each ticked as the VO lands, with the app's own
// evidence for the active line beside it. Earlier lines step back while the next speaks; at the end
// the evidence clears and all three stand together.
import { caption, crop, grow, A } from "../lib.js";
import { style, px, cue } from "./_polishB.js";

const LINES = ["Never approves its own hedge", "Every number comes from a tool", "Estimates and simulations are labeled"];
const BEATS = [0.0, 0.27, 0.64];

export default {
  id: "S15",
  label: "Trust",
  build(k) {
    style(k);
    const C = "shot-06-hedge-card-full.png", D = "shot-11-decision-log.png", G = "shot-12-ledger.png", L = "shot-14-labels.png";
    const X = 160, Y0 = 370, DY = 170;
    const head = k.el("div", "eyebrow abs", "How the desk behaves"); Object.assign(head.style, { left: X + "px", top: "280px" });
    k.enter(head, 0.05);
    const end = k.dur - 0.9;

    // Evidence cards (one per line): crops of the real screens on a dark glass panel.
    const card = (i, build) => {
      const c = k.el("div", "abs");
      Object.assign(c.style, { left: "1170px", top: Y0 + DY * i - 24 + "px", width: "654px", padding: "22px", borderRadius: "16px", display: "flex",
        flexDirection: "column", gap: "16px", alignItems: "flex-start", background: "rgba(15,26,20,0.6)", border: "1px solid rgba(243,245,239,0.14)" });
      build(c);
      [...c.children].forEach(ch => Object.assign(ch.style, { position: "relative", left: "0", top: "0" }));
      const at = k.v(BEATS[i]) + 0.25, out = i < 2 ? k.v(BEATS[i + 1]) - 0.05 : end;
      k.tween(c, { opacity: [0, 1], y: [16, 0] }, { at, dur: 0.55 });
      k.tween(c, { opacity: [1, 0] }, { at: out, dur: 0.3, ease: "in" });
      return c;
    };
    const label = (c, t) => { const e = k.el("div", "eyebrow", t, c); e.style.cssText += "font-size:18px;line-height:22px;letter-spacing:0.1em"; };
    card(0, c => {
      label(c, "The hedge card");
      crop(k, C, grow(A(C, "status_chip", px(C, [797, 23, 190, 26])), 0.12), { x: 0, y: 0, w: 560, parent: c });
      label(c, "The decision log");
      crop(k, D, grow(px(D, [36, 128, 160, 28]), 0.08), { x: 0, y: 0, w: 470, parent: c });
    });
    card(1, c => {
      label(c, "Sized by the tool, not the model");
      crop(k, C, px(C, [122, 136, 315, 38]), { x: 0, y: 0, w: 610, parent: c });   // "1,955 contracts @ 33¢ · premium $675.41"
      k.el("div", "pb-tag", "tool · size_hedge", c).style.cssText += "font-size:26px;padding:10px 14px";
    });
    card(2, c => {
      label(c, "Labels on screen");
      // Fractions of shot-12 (2832×1571) and shot-14 (2816×572), read off the captures.
      const row = (items) => { const r = k.el("div", null, null, c); Object.assign(r.style, { display: "flex", gap: "14px", alignItems: "center" });
        items.forEach(([f, b, w]) => { crop(k, f, b, { x: 0, y: 0, w, parent: r }).style.position = "relative"; }); };
      row([[G, grow([0.439, 0.3066, 0.05, 0.0379], 0.06), 190], [G, grow([0.6685, 0.1939, 0.12, 0.0325], 0.05), 400]]);
      row([[L, grow([0.257, 0.308, 0.027, 0.091], 0.2), 130], [L, grow([0.731, 0.83, 0.106, 0.094], 0.06), 420]]);
    });

    // The lines, each with a tick that draws on.
    LINES.forEach((txt, i) => {
      const y = Y0 + DY * i, at = k.v(BEATS[i]);
      const c = caption(k, txt, at, null, { cls: "section abs", wordStagger: 0.06 });
      Object.assign(c.style, { left: X + 92 + "px", top: y + "px", fontSize: "56px", lineHeight: "64px", width: "900px" });
      const tk = k.svg(`<svg class="abs" width="60" height="60" viewBox="0 0 60 60" style="left:${X}px;top:${y + 2}px">
        <circle class="bg" cx="30" cy="30" r="27" fill="#247153" opacity="0"/>
        <circle class="o" cx="30" cy="30" r="27" fill="none" stroke="#8fd1ad" stroke-width="2.5" pathLength="1" stroke-dasharray="1" transform="rotate(-90 30 30)"/>
        <path class="ck" d="M18 31 l8 8 l16 -17" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" pathLength="1" stroke-dasharray="1"/></svg>`);
      const tAt = at + 0.45;
      k.tween(tk.querySelector(".o"), { dash: [0, 1] }, { at: tAt, dur: 0.45, ease: "move" });
      k.tween(tk.querySelector(".bg"), { opacity: [0, 1] }, { at: tAt + 0.3, dur: 0.3 });
      k.tween(tk.querySelector(".ck"), { dash: [0, 1] }, { at: tAt + 0.35, dur: 0.35 });
      cue(k, "tick", tAt + 0.35);
      // Step back while the next line speaks, then all three come forward together.
      const dim = { o: 1 };
      if (i < 2) { k.tween(dim, { o: [1, 0.42] }, { at: k.v(BEATS[i + 1]), dur: 0.4, ease: "move" }); k.tween(dim, { o: [0.42, 1] }, { at: end, dur: 0.5, ease: "move" }); }
      k.after(() => { c.style.opacity = dim.o; tk.style.opacity = dim.o; });
    });
  }};
