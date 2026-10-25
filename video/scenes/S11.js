// S11 · Size & premium. "It buys only enough contracts to cover the measured loss, and not more, and shows
// the full cost up front." Same window as S10 (a cut, so the camera simply carries on): the eye goes
// 1,955 contracts → measured loss → "≤" (the I1 rule as an equation), then the payoff table's premium.
// The VO states no contract count; the equation's numbers are the captured card's own (earlier run).
import { caption, shot, A, principleTag } from "../lib.js";
import { style, px, glideRing, cue } from "./_polishB.js";
import { C, HEADER, HEADER_Z } from "./S10.js";
import { labelChip, BIKE_LABEL } from "./S07.js";

export default {
  id: "S11",
  label: "Size & premium",
  transition: "cut",
  build(k) {
    style(k);
    // Boxes in the card's CSS px (shot-06 at 2x); px() needs the preloaded image size, so build time.
    const TICKER = px(C, [27, 99, 294, 17]);
    const LOSS_BAR = px(C, [74, 210, 84, 168]);       // grey "It rains" bar and its −$1,955.68 label
    const CONTRACTS = px(C, [118, 141, 176, 28]);     // "1,955 contracts @ 33¢"
    const s = shot(k, C, { chip: "Example hedge · earlier run" });
    s.set(HEADER, { z: HEADER_Z });
    const ring = glideRing(k, s);
    ring.on(A(C, "ticker", TICKER), -1);

    // Down to the buy line and the payoff bars; the ring waits for the camera, then finds the contracts.
    ring.off(0.05, 0.25);
    s.focus([0, 0.16, 1, 0.3], 0.1, 0.9, { z: 1 });
    ring.on(CONTRACTS, Math.max(1.05, k.v(0.2)));                       // "only enough contracts"

    // I1 as an equation: contracts ≤ measured loss.
    const eq = k.el("div", "pb-eq");
    Object.assign(eq.style, { left: "210px", top: "850px" });
    eq.innerHTML = `<div class="term L" style="min-width:230px"><div class="val">1,955</div><div class="lab">contracts · pays $1,955.00 if it rains</div></div>
      <div class="le">≤</div>
      <div class="term R"><div class="val">$1,955.68</div><div class="lab">measured loss on a rain day</div></div>`;
    const [L, le, R] = eq.children;
    k.tween(L, { opacity: [0, 1], y: [12, 0] }, { at: k.v(0.2), dur: 0.5 });          // reads left to right
    ring.hop(LOSS_BAR, k.v(0.4));                                                         // "the measured loss"
    k.tween(R, { opacity: [0, 1], y: [12, 0] }, { at: k.v(0.42), dur: 0.5 });
    k.tween(le, { opacity: [0, 1], scale: [1.12, 1] }, { at: k.v(0.6), dur: 0.35 });     // "and not more"
    cue(k, "tick", k.v(0.6));
    k.tween(eq, { opacity: [1, 0] }, { at: k.v(0.74), dur: 0.3, ease: "in" });

    // The payoff table: both outcomes, premium column ringed ("the full cost up front").
    ring.off(k.v(0.72), 0.25);
    s.focus([0.02, 0.5, 0.96, 0.15], k.v(0.74), 0.9, { z: 1 });   // stops above the Reject/Approve row
    ring.on(A(C, "premium_col", px(C, [635, 483, 176, 99])), k.v(0.74) + 0.95);
    labelChip(k, BIKE_LABEL);
    caption(k, "Full cost up front: premium *$675.41*, fee included", k.v(0.8), null);
    caption(k, "Expected cost ≈ $64.86 at the 31% NOAA rain rate", k.v(0.92), null, { cls: "cap sub" });
    principleTag(k, 2);
  }};
