// S9 · Match. The hedge card's header: Central Park in the title, then the Kalshi ticker, and the
// station we measured (the Rain row's market cell from step 2) tied to it with a drawn line.
import { caption, shot, crop, A } from "../lib.js";
import { labelChip, BIKE_LABEL } from "./S06.js";
import { style, px, glideRing, cue } from "./_polishB.js";

export const C = "shot-06-hedge-card-full.png";
// Opening framing of S10 matches this scene's end (same window, same camera).
export const HEADER = [0, 0, 1, 0.3];
export const HEADER_Z = 1;

export default {
  id: "S9",
  label: "Match",
  build(k) {
    style(k);
    const s = shot(k, C, { chip: "Scripted demo · real offline run" });
    k.tween(s.win, { y: [36, 0], opacity: [0, 1] }, { at: 0, dur: 0.7 });
    s.set(HEADER, { z: HEADER_Z });
    cue(k, "whoosh", 0);

    const ring = glideRing(k, s);
    ring.on(px(C, [132, 60, 110, 26]), k.v(0.26));                        // "Central Park"
    ring.to(A(C, "ticker", px(C, [27, 99, 294, 17])), k.v(0.46), 0.3);   // down one line    // KXRAIN-26OCT28-NYC · series KXRAIN

    caption(k, "Kalshi · *Central Park* rain", k.v(0.05), k.v(0.6));

    // The station we measured: the Rain row's market cell from step 2, tied to the ticker.
    const card = k.el("div", "abs");
    Object.assign(card.style, { left: "1110px", top: "470px", width: "540px", padding: "18px 20px 20px", borderRadius: "14px",
      background: "rgba(15,26,20,0.88)", border: "1px solid rgba(243,245,239,0.18)", boxShadow: "0 24px 60px rgba(0,0,0,0.45)" });
    k.el("div", "eyebrow", "Measured in step 2 · Rain day", card).style.cssText += "font-size:17px;line-height:20px;margin-bottom:14px;color:#a4ada4";
    const cell = crop(k, "shot-02b-rain-row.png", [0.872, 0.11, 0.126, 0.66], { x: 0, y: 0, w: 500, parent: card });
    Object.assign(cell.style, { position: "relative", boxShadow: "none" });
    k.tween(card, { opacity: [0, 1], y: [16, 0] }, { at: k.v(0.64), dur: 0.55 });
    k.exit(card, k.dur - 0.45, { dur: 0.35 });

    // Connector from the card up to the ringed ticker line.
    const g = k.svg(`<svg class="abs" width="1920" height="1080" viewBox="0 0 1920 1080" style="left:0;top:0;pointer-events:none">
      <path class="ln" pathLength="1" stroke-dasharray="1" fill="none" stroke="#F28C28" stroke-width="3" stroke-linecap="round"/>
      <circle class="d0" r="6" fill="#F28C28"/><circle class="d1" r="6" fill="#F28C28"/></svg>`);
    const ln = g.querySelector(".ln"), d0 = g.querySelector(".d0"), d1 = g.querySelector(".d1");
    const L = { p: 0, o: 0 };
    k.tween(L, { o: [0, 1] }, { at: k.v(0.7), dur: 0.2 });
    k.tween(L, { p: [0, 1] }, { at: k.v(0.7), dur: 0.7, ease: "move" });
    k.tween(L, { o: [1, 0] }, { at: k.dur - 0.45, dur: 0.35, ease: "in" });
    k.after(() => {
      const tk = A(C, "ticker", px(C, [27, 99, 294, 17]));
      const [tx, ty] = s.point(tk[0] + tk[2], tk[1] + tk[3] / 2);
      const x0 = 210 + 1 + tx + 12, y0 = 64 + 1 + ty, x1 = 1470, y1 = 470 - 4;
      ln.setAttribute("d", `M${x0} ${y0} C${x1} ${y0}, ${x1} ${y0}, ${x1} ${y1}`);
      ln.style.strokeDashoffset = 1 - L.p; g.style.opacity = L.o;
      d0.setAttribute("cx", x0); d0.setAttribute("cy", y0);
      d1.setAttribute("cx", x1); d1.setAttribute("cy", y1); d1.style.opacity = L.p > 0.98 ? 1 : 0;
    });

    caption(k, "Settles on the *same station* we measured", k.v(0.66), k.dur - 0.45);
    labelChip(k, BIKE_LABEL);
  }};
