// S10 · Size & premium. Same window as S9 (a cut, so the camera simply carries on): the eye goes
// measured loss → "≤" → 1,955 contracts (the I1 rule as an equation), then the payoff table's premium.
import { caption, shot, A } from "../lib.js";
import { style, px, glideRing, cue } from "./_polishB.js";
import { C, HEADER, HEADER_Z } from "./S09.js";
import { labelChip, BIKE_LABEL } from "./S06.js";

export default {
  id: "S10",
  label: "Size & premium",
  transition: "cut",
  build(k) {
    style(k);
    // Boxes in the card's CSS px (shot-06 at 2x); px() needs the preloaded image size, so build time.
    const TICKER = px(C, [27, 99, 294, 17]);
    const LOSS_BAR = px(C, [74, 210, 84, 168]);       // grey "It rains" bar and its −$1,955.68 label
    const CONTRACTS = px(C, [118, 141, 176, 28]);     // "1,955 contracts @ 33¢"
    const PAYS = px(C, [604, 141, 192, 28]);          // "pays $1,955.00 if it rains"
    const s = shot(k, C, { chip: "Scripted demo · real offline run" });
    s.set(HEADER, { z: HEADER_Z });
    const ring = glideRing(k, s);
    ring.on(A(C, "ticker", TICKER), -1);

    // Down to the buy line and the payoff bars; the ring waits for the camera, then finds the measured loss.
    ring.off(0.05, 0.25);
    s.focus([0, 0.16, 1, 0.3], 0.1, 0.9, { z: 1 });
    ring.on(LOSS_BAR, Math.max(1.05, k.v(0.12)));

    // I1 as an equation: contracts ≤ measured loss.
    const eq = k.el("div", "pb-eq");
    Object.assign(eq.style, { left: "210px", top: "850px" });
    eq.innerHTML = `<div class="term L" style="min-width:230px"><div class="val">1,955</div><div class="lab">contracts · pays $1,955.00 if it rains</div></div>
      <div class="le">≤</div>
      <div class="term R"><div class="val">$1,955.68</div><div class="lab">measured loss on a rain day</div></div>`;
    const [L, le, R] = eq.children;
    k.tween(R, { opacity: [0, 1], y: [12, 0] }, { at: k.v(0.15) + 0.2, dur: 0.5 });   // reads left to right
    k.tween(le, { opacity: [0, 1], scale: [1.12, 1] }, { at: k.v(0.27), dur: 0.35 });
    cue(k, "tick", k.v(0.27));
    ring.hop(CONTRACTS, k.v(0.35));
    k.tween(L, { opacity: [0, 1], y: [12, 0] }, { at: k.v(0.15), dur: 0.5 });   // both sides together, then the "≤"
    ring.to(PAYS, k.v(0.5), 0.3);   // along the same line
    k.tween(eq, { opacity: [1, 0] }, { at: k.v(0.62), dur: 0.3, ease: "in" });

    // The payoff table: both outcomes, premium column ringed.
    ring.off(k.v(0.6), 0.25);
    s.focus([0.02, 0.5, 0.96, 0.15], k.v(0.62), 0.9, { z: 1 });   // stops above the Reject/Approve row
    ring.on(A(C, "premium_col", px(C, [635, 483, 176, 99])), k.v(0.62) + 0.95);
    labelChip(k, BIKE_LABEL);
    caption(k, "Full premium up front: *$675.41*, fee included", k.v(0.74), null);
    caption(k, "Expected cost ≈ $64.86 at the 31% NOAA rain rate", k.v(0.88), null, { cls: "cap sub" });
  }};
