// S14 · Ledger. Taxi's books (simulated, labeled in the window bar and on every row): ledger rows
// cascade in, then the three-way check runs, the short deposit is flagged, and the note naming the
// fee is tied back to the fee posting in the ledger.
import { caption, shot, A } from "../lib.js";
import { labelChip } from "./S06.js";
import { style, pad, cover, reveal, glideRing, cue } from "./_polishB.js";

const G = "shot-12-ledger.png";
// Fractions of shot-12 (read off the 2832×1571 capture).
const fx = x => x / 2000, fy = y => y / 1109;
const box = (x0, y0, x1, y1) => [fx(x0), fy(y0), fx(x1 - x0), fy(y1 - y0)];
const ROWS = [[327, 400], [400, 502], [502, 604], [604, 706], [706, 808], [808, 882], [882, 984], [984, 1057]].map(([a, b]) => box(52, a, 982, b));
const CHECK = [[408, 455], [455, 500]].map(([a, b]) => box(1016, a, 1947, b));
const FLAGGED = box(1016, 500, 1947, 550);
const SUMMARY = box(1012, 288, 1600, 325);
const NOTE = box(1016, 566, 1947, 708);
const FEE = box(580, 440, 872, 464);                   // "Expenses:Hedging:Fees $0.89" on Oct 19

export default {
  id: "S14",
  label: "Ledger",
  build(k) {
    style(k);
    const s = shot(k, G, { chip: "Simulated settlements & bank", chipCls: "sim" });
    k.tween(s.win, { y: [24, 0] }, { at: 0, dur: 0.7 });

    // The ledger: rows cascade in while the camera drifts down the table.
    s.set([0, 0.2, 0.52, 0.5], { z: 1.32 });
    s.focus([0, 0.42, 0.52, 0.5], 0.3, k.v(0.3) - 0.3, { z: 1.32, ease: "linear" });
    cover(k, s, G, pad(box(52, 327, 982, 1057), 0.002));
    ROWS.forEach((r, i) => { reveal(k, s, G, r, 0.35 + i * 0.09, { bg: "#fffefa", dy: 10, dur: 0.45 }); if (i % 3 === 0) cue(k, "tick", 0.35 + i * 0.09); });
    const ring = glideRing(k, s);
    ring.on(FEE, k.v(0.14)).off(k.v(0.3));
    caption(k, "Books and bank, *reconciled*", k.v(0.03), k.v(0.46));
    labelChip(k, "Simulated books · taxi fleet", { cls: "sim" });

    // Reconciliation: the three-way check fills in, one payout flags.
    const rec = k.v(0.31);
    s.focus([0.5, 0.18, 0.48, 0.48], rec, 1.0, { z: 1.6 });
    cover(k, s, G, pad(box(1012, 288, 1947, 708), 0.002, 0.002));
    reveal(k, s, G, box(1016, 365, 1947, 407), rec + 0.5, { dy: 6 });
    CHECK.forEach((r, i) => reveal(k, s, G, r, rec + 0.65 + i * 0.12, { dy: 8 }));
    const flag = rec + 1.05;
    reveal(k, s, G, FLAGGED, flag, { dy: 8 });
    reveal(k, s, G, SUMMARY, flag + 0.25, { dy: 6 });
    const amber = glideRing(k, s, { color: "amber" });
    amber.on(FLAGGED, k.v(0.52)).pop(k.v(0.52));
    cue(k, "tick", k.v(0.52));
    caption(k, "A *$0.89* gap, flagged", k.v(0.5), k.v(0.71));

    // The cause: the note appears, then the camera pulls back and ties it to the fee posting.
    const why = k.v(0.69);   // "short"; the fee ring and connector then land on "fee"
    reveal(k, s, G, NOTE, why, { dy: 10, dur: 0.45 });
    amber.to(NOTE, why + 0.05, 0.3);                 // down one row, camera still
    amber.off(why + 0.55, 0.2);
    s.focus([0.24, 0.17, 0.76, 0.66], why + 0.55, 0.7, { z: 1.3 });
    const fee = glideRing(k, s);
    fee.on(FEE, why + 1.25).pop(why + 1.25);
    // A drawn line ties the note's "$0.89 fee" back to the posting it names.
    const g = k.svg(`<svg class="abs" style="left:0;top:0;overflow:visible;pointer-events:none" width="1" height="1">
      <path pathLength="1" stroke-dasharray="1" fill="none" stroke="#F28C28" stroke-width="3" stroke-linecap="round"/><circle r="5" fill="#F28C28"/></svg>`, s.vp);
    const path = g.querySelector("path"), dot = g.querySelector("circle"), L = { p: 0 };
    k.tween(L, { p: [0, 1] }, { at: why + 1.3, dur: 0.5, ease: "move" });
    k.after(() => {
      const [x0, y0] = s.point(FEE[0] + FEE[2], FEE[1] + FEE[3] / 2), [x1, y1] = s.point(fx(1040), fy(628));
      const a = [x0 + 12, y0 - 41], b = [x1 - 6, y1 - 41];
      path.setAttribute("d", `M${a[0]} ${a[1]} C${a[0] + 80} ${a[1]}, ${b[0] - 60} ${b[1]}, ${b[0]} ${b[1]}`);
      path.style.strokeDashoffset = 1 - L.p; g.style.opacity = L.p > 0 ? 1 : 0;
      dot.setAttribute("cx", b[0]); dot.setAttribute("cy", b[1]); dot.style.opacity = L.p > 0.97 ? 1 : 0;
    });
    caption(k, "The gap is the *$0.89 fee*", why + 0.15, null);
  }};
