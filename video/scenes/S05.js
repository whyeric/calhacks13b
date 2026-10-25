// S5 · Match → decide. "Then it finds a Kalshi contract that pays when it hits. And you decide."
// Cuts in on S4's end frame. Match and Propose light in turn, then the row glides left to make
// room for the green "You decide" pill, which lands on "you decide".
import { caption } from "../lib.js";
import { buildRail, rowX } from "./S04.js";

// Word onsets in the VO clip (whisper): finds 0.24, Kalshi 0.70, pays 1.80, hits 2.40, you 3.12, decide 3.24.
const W = { finds: 0.24, kalshi: 0.7, pays: 1.8, hits: 2.4, you: 3.12, decide: 3.24 };

export default {
  id: "S5",
  label: "Match → decide",
  transition: "cut",
  build(k) {
    const at = w => k.vo.lead + W[w];
    const R = buildRail(k, 3);
    R.lf.style.opacity = 1;
    R.lit(0).style.opacity = 1;

    R.light(1, at("finds") + 0.15);
    R.light(2, at("pays") + 0.1);

    // Make room: the row (laid out for 3) glides to the 4-pill layout, the owner pill and its link arrive.
    const shift = rowX(4)[0] - rowX(3)[0], tMove = at("hits") - 0.1;
    k.tween(R.row, { x: [0, shift] }, { at: tMove, dur: 0.75, ease: "move" });
    k.cue("whoosh", tMove);
    const owner = R.pills[3], link = R.links[2].l;
    k.tween(link, { clipR: [100, 0] }, { at: tMove + 0.45, dur: 0.45, ease: "move" });
    k.tween(owner, { opacity: [0, 1], scale: [0.96, 1] }, { at: tMove + 0.55, dur: 0.45 });
    R.light(3, at("you") + 0.1);

    const c1 = caption(k, "Finds a *Kalshi* contract that pays when it hits", at("finds"), tMove + 0.3, { wordStagger: 0.06 });
    Object.assign(c1.style, { left: 0, width: "1920px", top: "720px", textAlign: "center", fontSize: "44px" });
    const c2 = caption(k, "*Your call.*", at("you"), null, { cls: "section abs", y: 14 });
    Object.assign(c2.style, { left: 0, width: "1920px", top: "722px", textAlign: "center", fontSize: "76px", lineHeight: "84px" });
  },
};
