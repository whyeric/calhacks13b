// S12 · Owner only. A cursor glides to Approve and clicks; the buttons dissolve into the approved card,
// the camera rises to the status chip, and "Approved by you" lands like a stamp.
import { caption, shot, A } from "../lib.js";
import { style, px, piece, inCam, glideRing, cursor, cue } from "./_polishB.js";

const C = "shot-06-hedge-card-full.png", AP = "shot-10-approved-chip.png";

export default {
  id: "S12",
  label: "Owner only",
  build(k) {
    style(k);
    const BTN = A(C, "approve_btn", px(C, [897, 749, 90, 46]));
    const CHIP = A(C, "status_chip", px(C, [797, 23, 190, 26]));          // "Proposed · only you can approve"
    const CHIP_AP = px(AP, [883, 23, 104, 26]);                            // "Approved by you", in shot-10's own fractions
    const s = shot(k, C, { chip: "Scripted demo" });
    k.tween(s.win, { y: [24, 0] }, { at: 0, dur: 0.7 });
    s.set([0, 0.8, 1, 0.2], { z: 1 });

    // Hover state: the button darkens as the cursor arrives.
    const hover = inCam(k, s, C, BTN, "pb-cover");
    Object.assign(hover.style, { background: "rgba(10,30,20,0.22)", borderRadius: "10px" });
    const cur = cursor(k, s);
    const [bx, by] = [BTN[0] + BTN[2] * 0.52, BTN[1] + BTN[3] * 0.56];
    const click = k.v(0.5);
    k.tween(cur, { o: [0, 1] }, { at: 0.1, dur: 0.3 });
    k.tween(cur, { x: [0.62, bx] }, { at: 0.15, dur: click - 0.35, ease: "move" });
    k.tween(cur, { y: [0.84, by] }, { at: 0.15, dur: click - 0.35, ease: "out" });
    k.tween(hover, { opacity: [0, 1] }, { at: click - 0.35, dur: 0.15 });
    // Click: press and release, a ring spreads from the tip.
    k.tween(cur, { s: [1, 0.86] }, { at: click, dur: 0.08, ease: "in" });
    k.tween(cur, { s: [0.86, 1] }, { at: click + 0.08, dur: 0.2 });
    const rp = k.el("div", "pb-click", null, s.vp);
    k.after(() => { const [x, y] = s.point(bx, by); rp.style.left = x + "px"; rp.style.top = y - 41 + "px"; });
    k.tween(rp, { opacity: [0.9, 0], scale: [0.35, 1.5] }, { at: click, dur: 0.6 });
    cue(k, "click", click);
    k.tween(cur, { o: [1, 0] }, { at: click + 0.22, dur: 0.2, ease: "in" });

    // The card becomes the approved one (its buttons are gone); the old chip stays until the camera arrives.
    const base = s.cam.querySelector("img, .ph");
    s.swap(AP, click + 0.45);
    k.tween(base, { opacity: [1, 0] }, { at: click + 0.45, dur: 0.35 });
    k.tween(hover, { opacity: [1, 0] }, { at: click + 0.3, dur: 0.2 });
    const oldChip = piece(k, s, C, CHIP);
    s.focus([0, 0, 1, 0.3], click + 0.15, 0.85, { z: 1 });

    // "Approved by you" lands: the proposed chip lifts off, the new one settles in, a green ring.
    const land = click + 1.05;
    s.focus([0.6, 0.0, 0.4, 0.1], land - 0.15, 0.9, { z: 1.8 });   // push in on the chip as it flips
    k.tween(oldChip, { opacity: [1, 0] }, { at: land - 0.12, dur: 0.15, ease: "in" });
    const newChip = piece(k, s, AP, CHIP_AP);
    newChip.style.transformOrigin = "50% 50%";
    k.tween(newChip, { opacity: [0, 1], scale: [1.18, 1] }, { at: land, dur: 0.22, ease: "in" });
    cue(k, "stamp", land + 0.2);
    glideRing(k, s, { color: "green" }).on(A(AP, "status_chip", px(C, [883, 23, 104, 26]), { base: C }), land + 0.18).pop(land + 0.18);

    caption(k, "*Owner only.* Nothing happens until you approve.", k.v(0.05), null);
  }};
