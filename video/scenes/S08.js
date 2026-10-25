// S8 · Rain costs. "Rain costs it nearly $2,000 a day, and that holds up on data the model never saw."
// The caption rounds the way the VO does ("nearly $2,000/day"): true of the captured −$1,955.68 and of
// main's live −$1,923.43. Same window and spot as S7, so the dissolve only swaps the page. The camera eases from the whole
// table to the Risk → Verdict span (all six rows stay whole). One ring travels: the training-year
// loss as it counts up → the forest whiskers as they draw → the unseen years → FOUND · hedgeable.
import { shot, A, principleTag } from "../lib.js";
import { line, labelChip, BIKE_LABEL } from "./S07.js";

// Word onsets after the speech starts (user.m4a; phrase pauses from silencedetect, words spread within a phrase): Rain 0.00, nearly 0.84,
// $2,000 1.22, a day 2.15, holds 3.14, data 3.70, never 4.29.
const W = { rain: 0.0, nearly: 0.84, amount: 1.22, aday: 2.15, held: 3.14, data: 3.7, never: 4.29 };

export default {
  id: "S8",
  label: "Rain costs",
  build(k) {
    const at = w => k.vo.lead + W[w];
    const F = "shot-02-wizard-research-table.png";
    // Window height chosen so the table exactly fills it at the push-in zoom (no half rows).
    const s = shot(k, F, { h: 690 });
    s.vp.style.background = "#fffefa"; // the table's own paper, so z < fill shows no bands
    // Fractions of this image from CSS px (the table is 1582 x 564 CSS px).
    const css = (x, y, w, h) => [x / 1582, y / 564, w / 1582, h / 564];
    const train = A(F, "rain_train_text", css(253, 73, 180, 58)), unseen = A(F, "rain_unseen_text", css(454, 73, 180, 58));
    const v = A(F, "rain_verdict_text", css(1135, 76, 43, 14)), verdict = [v[0], v[1], 122 / 1582, v[3]]; // FOUND · hedgeable
    const whisk = css(668, 70, 108, 70);

    k.cue("whoosh", 0);
    s.set(css(0, 0, 1582, 564), { z: 1 });
    // Risk column through the Verdict, full height: z = 1582 / 1300.
    s.focus(css(0, 0, 1300, 564), 0.1, 1.0, { z: 1582 / 1300 });

    // Forest whiskers for the Rain row draw outward from the zero line.
    const wipe = k.el("div", "abs", null, s.vp);
    Object.assign(wipe.style, { background: "#fffefa", left: 0, top: 0 });
    const Wp = { p: 0 };
    k.tween(Wp, { p: [0, 1] }, { at: at("aday") - 0.1, dur: 0.9, ease: "out" });
    k.after(() => {
      const [x0, y0] = s.point(whisk[0], whisk[1]), [x1, y1] = s.point(whisk[0] + whisk[2], whisk[1] + whisk[3]);
      Object.assign(wipe.style, { left: x0 + "px", top: y0 - 41 + "px", width: x1 - x0 + "px", height: y1 - y0 + "px",
        clipPath: `inset(0 ${(Wp.p * 100).toFixed(2)}% 0 0)` });
    });

    // One ring: training-year loss → the whiskers → the unseen years → FOUND (turning green).
    s.ring(train, at("amount") - 0.05, null, { pad: 10 })
      .to(whisk, at("aday") - 0.15, 0.6)
      .to(unseen, at("held") - 0.1, 0.6)
      .to(verdict, at("data") + 0.2, 0.7, { color: "green" });
    k.cue("tick", at("amount") - 0.05);
    k.cue("tick", at("held") - 0.1);
    k.cue("stamp", at("data") + 0.9);

    labelChip(k, BIKE_LABEL);
    line(k, [["Rain costs", at("rain") + 0.2], ["nearly *$2,000/day*", at("nearly")]], at("held") - 0.4);
    line(k, [["Holds up on data the model never saw:", at("held")], ["*−20.4%*", at("data") - 0.2]], k.dur - 0.3);
    principleTag(k, 1);
  },
};
