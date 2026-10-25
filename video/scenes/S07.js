// S7 · Upload. "Here's a bike shop with fictional sales but real weather. Upload its daily revenue."
// The wizard rises into frame, with the fictional-shop label as a chip under the window. The camera
// pushes in on the upload button, a click lands, and the ring glides down to the status line
// as 1,004 days count up.
import { caption, shot, A } from "../lib.js";

// Word onsets after the speech starts (user.m4a; phrase pauses from silencedetect, words spread within a phrase): bike 0.59, fictional 1.22,
// sales 1.61, real 2.24, upload 2.93, daily 3.60.
const W = { bike: 0.59, fictional: 1.22, sales: 1.61, real: 2.24, upload: 2.93, daily: 3.6 };

// A caption line built from segments that each land on their own word: [[text, at], ...].
export function line(k, segs, out, style = {}) {
  const c = k.el("div", "cap");
  segs.forEach(([txt, t], i) => {
    const e = caption(k, txt, t, null, { parent: c, cls: "seg" });
    e.style.display = "inline";
    if (i < segs.length - 1) c.append(" ");
  });
  if (out != null) k.exit(c, out);
  Object.assign(c.style, style);
  return c;
}

// The I6 label as a chip under the window, right-aligned to the default window's right edge (1710).
// The same wording and spot are used from S7 through S11, so it holds still across the dissolves.
export const BIKE_LABEL = "Fictional shop · synthetic sales · real weather";
export function labelChip(k, text = BIKE_LABEL, { cls = "warn", right = 1710, top = 866, at = null } = {}) {
  const c = k.el("div", "chip abs " + cls, text);
  Object.assign(c.style, { right: 1920 - right + "px", top: top + "px", font: "600 22px/28px var(--sans)", letterSpacing: "0.04em",
    padding: "6px 14px", borderRadius: "999px", transformOrigin: "100% 50%", whiteSpace: "nowrap" });
  if (at != null) k.enter(c, at, { y: 8 });
  return c;
}

export default {
  id: "S7",
  label: "Upload",
  build(k) {
    const at = w => k.vo.lead + W[w];
    const F = "shot-01-wizard-upload.png";
    const s = shot(k, F, { h: 690 }); // same window as S7, so the dissolve only swaps the page
    // Image fractions from CSS px (the capture is 1440 x 900 CSS px).
    const css = (x, y, w, h) => [x / 1440, y / 900, w / 1440, h / 900];

    // Rise into frame. Framed on the header, tabs and card, ending above Back / Next (they start at 510 CSS px).
    k.tween(s.win, { y: [60, 0], scale: [0.97, 1] }, { at: 0, dur: 0.9 });
    k.cue("whoosh", 0);
    s.set(css(198, 19, 1044, 462), { z: 1.35 });
    s.kenburns(1, 1.03);
    const btn = A(F, "upload_btn", css(219, 264, 179, 46)), status = A(F, "status_text", css(219, 330, 548, 22));
    // Push in on the upload row once the "fictional" beat has read (z 1.84 x 1.03 is about 1:1).
    s.focus(css(200, 250, 620, 115), at("upload") - 1.05, 1.0, { z: 1.84 });

    // The I6 label: lands with "fictional sales" and stays.
    const chip = labelChip(k, BIKE_LABEL, { at: at("fictional") - 0.1 });
    k.tween(chip, { scale: [1, 1.06] }, { at: at("fictional") + 0.4, dur: 0.25, ease: "move" });
    k.tween(chip, { scale: [1.06, 1] }, { at: at("fictional") + 0.65, dur: 0.5, ease: "move" });
    k.cue("tick", at("fictional"));

    // Click on Upload, then the ring glides to the status line.
    s.ring(btn, at("upload") + 0.05, null, { pad: 8 }).to(status, at("upload") + 0.45, 0.55);
    const rp = k.el("div", "ripple", null, s.vp);
    k.tween(rp, { opacity: [0, 0] }, { at: 0, dur: 0 });
    k.after(() => { const [px, py] = s.point(btn[0] + btn[2] / 2, btn[1] + btn[3] / 2); rp.style.left = px + "px"; rp.style.top = py - 41 + "px"; });
    k.tween(rp, { opacity: [0.9, 0], scale: [0.3, 1.5] }, { at: at("upload") + 0.2, dur: 0.6 });
    k.cue("click", at("upload") + 0.2);

    line(k, [["A bike shop.", at("bike")], ["Fictional sales,", at("fictional")], ["*real weather.*", at("real")]], at("upload") - 0.1);
    line(k, [["Upload daily revenue:", at("upload")], ["*{1,004} days*", at("upload") + 0.4]], k.dur - 0.3);
  },
};
