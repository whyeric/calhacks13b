// S12 · Decline: the trust moment ("…So Offset says no, and explains why."). A beat of black and a line
// of type, then the taxi card drops in with its verdict held back: the eye reads last year vs. recent
// months, the DECLINED stamp lands, and the card's own reasons are revealed one at a time, then the full
// explanation. Long hold.
import { caption, shot, principleTag } from "../lib.js";
import { style, px, pad, cover, reveal, glideRing, cue } from "./_polishB.js";

const T = "shot-07-taxi-declined-card.png";
const SURFACE = "#fffefa", PANEL = "#fff4ef";

export default {
  id: "S12",
  label: "Decline",
  build(k) {
    style(k);
    // Boxes in the card's CSS px (shot-07 at 2x).
    const B = {
      chip: px(T, [600, 32, 73, 36]),         // "Declined"
      text: px(T, [30, 70, 640, 112]),        // title + the "Declined: …" sentence
      r1: px(T, [64, 198, 130, 26]),          // "No open market"
      r2: px(T, [64, 222, 392, 27]),          // "Not reliable: the effect didn't hold up in recent months"
      reasons: px(T, [64, 198, 392, 51]),
      last: px(T, [48, 256, 98, 52]),         // Last year $2,080.20
      recent: px(T, [162, 256, 92, 52]),      // Recent months $228.41
      d1: px(T, [62, 316, 600, 46]),          // "No open market · Fail" and its numbers
      d2: px(T, [62, 366, 600, 250]),         // "Not reliable … · Fail" and its numbers
    };

    // Beat of black, then one line of type.
    const head = caption(k, "Not every risk gets a *hedge.*", k.v(0.0), k.v(0.16), { cls: "section abs", wordStagger: 0.08 });
    Object.assign(head.style, { left: "0", width: "1920px", top: "500px", textAlign: "center", color: "#f3f5ef" });

    // The card drops in, verdict hidden.
    const s = shot(k, T, { x: 400, y: 64, w: 1120, h: 760, chip: "Taxi fleet · real data", chipCls: "real" });
    s.set([0, 0, 1, 0.62], { z: 1 });
    const drop = k.v(0.2);
    k.tween(s.win, { y: [-48, 0], opacity: [0, 1] }, { at: drop, dur: 0.75 });
    cue(k, "whoosh", drop);
    // Soft fade at the window's bottom edge, so a row is never sliced mid-line.
    const fade = k.el("div", "abs", null, s.vp);
    fade.style.cssText = "left:0;right:0;bottom:0;height:110px;background:linear-gradient(rgba(255,244,239,0),#fff4ef 85%);pointer-events:none";
    const chipCover = cover(k, s, T, B.chip, SURFACE);
    const r1 = cover(k, s, T, B.r1, PANEL), r2 = cover(k, s, T, B.r2, PANEL);

    // Rain looked big last year, then almost vanished.
    s.focus(pad([0.03, 0.36, 0.6, 0.13], 0.02), k.v(0.33), 1.0, { z: 1.55 });
    const ring = glideRing(k, s, { color: "red" });
    ring.on(B.last, k.v(0.38));
    ring.to(B.recent, k.v(0.55), 0.3);
    caption(k, "Taxi fleet, rain: *+$2,080/day* last year, *+$228* lately", k.v(0.3), k.v(0.66));
    ring.off(k.v(0.66));

    // Pull back and hold a breath, then the stamp.
    const MID = [0, 0.2, 0.84, 0.54];
    s.focus(MID, k.v(0.64), 0.9, { z: 1.25 });
    const at = k.v(0.76), why = k.v(0.88);
    const ring2 = glideRing(k, s, { color: "red" });   // made before the stamp so the stamp sits above its dim
    // The stamp rides with the camera but stays above the highlight dim.
    const stamp = k.el("div", "pb-stamp red", "Declined", s.vp);
    Object.assign(stamp.style, { fontSize: "46px", padding: "16px 22px 16px 32px" });
    k.after(() => { const [x, y] = s.point(0.5, 0.385); stamp.style.left = x + "px"; stamp.style.top = y - 41 + "px"; });
    k.tween(stamp, { opacity: [0, 1], scale: [0.96, 1], rotate: [-7, -7] }, { at, dur: 0.25 });
    cue(k, "stamp", at);
    k.tween(chipCover, { opacity: [1, 0] }, { at: at + 0.1, dur: 0.25 });

    // The reasons, one by one (the card's own lines), with the red ring walking down them.
    ring2.on(B.r1, why);
    k.tween(r1, { opacity: [1, 0] }, { at: why, dur: 0.35 });
    reveal(k, s, T, B.d1, why + 0.1, { bg: PANEL, dy: 8 });
    ring2.to(B.r2, why + 0.6, 0.3);
    k.tween(r2, { opacity: [1, 0] }, { at: why + 0.6, dur: 0.35 });
    reveal(k, s, T, B.d2, why + 0.7, { bg: PANEL, dy: 8 });
    cue(k, "tick", why); cue(k, "tick", why + 0.6);
    ring2.to(B.reasons, why + 1.25, 0.3);
    caption(k, "*Says no,* and explains why: no open market · not reliable", k.v(0.79), null);
    // Then the camera eases up to the whole card and the full explanation settles in.
    s.focus([0, 0.02, 1, 0.62], why + 1.3, 1.0, { z: 1 });
    reveal(k, s, T, B.text, why + 1.6, { bg: SURFACE, dy: 8, dur: 0.6 });
    principleTag(k, 4, { at: k.v(0.2) });   // with the card: a decline that shows its evidence
  }};
