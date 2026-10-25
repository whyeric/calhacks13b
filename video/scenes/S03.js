// S3 · Swings. "Either way, as an owner, your week swings, and you can't plan around it."
// Four weeks of an illustrative daily revenue line draw on, with rain-day dips and game-night
// spikes marked; the line lurches once on "swings", then a week of question marks lands on "can't plan".
import { clamp, caption, rand } from "../lib.js";

// Word onsets after the speech starts (user.m4a; phrase pauses from silencedetect, words spread within a phrase): Either 0.00, week 1.85,
// swings 2.10, can't 3.06, plan 3.30.
const W = { either: 0.0, week: 1.85, swings: 2.1, cant: 3.06, plan: 3.3 };

const N = 28, X0 = 160, X1 = 1760, Y0 = 560;
const RAIN = new Set([4, 11, 19, 24]), GAME = new Set([8, 16, 22]);
// Illustrative series (no units on screen): weekend lift, small noise, rain dips, game spikes.
const BASE = Array.from({ length: N }, (_, i) =>
  (i % 7 >= 5 ? 60 : 0) + (rand(i, 31) - 0.5) * 70 + (RAIN.has(i) ? -230 : 0) + (GAME.has(i) ? 190 : 0));

// Smooth path through points (Catmull-Rom as cubic Béziers).
function smooth(pts) {
  let d = `M${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6], c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    d += ` C${c1[0].toFixed(1)} ${c1[1].toFixed(1)} ${c2[0].toFixed(1)} ${c2[1].toFixed(1)} ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
  }
  return d;
}

const DROP = `<path d="M0 -16 C6 -6 10 0 10 5 A10 10 0 0 1 -10 5 C-10 0 -6 -6 0 -16 Z" fill="#8fb8a6"/>`;
const BALL = `<g fill="none" stroke="#e9ede4" stroke-width="2.4"><circle r="12"/><path d="M-12 0 H12 M0 -12 V12 M-8.5 -8.5 C-3 -3 -3 3 -8.5 8.5 M8.5 -8.5 C3 -3 3 3 8.5 8.5"/></g>`;

export default {
  id: "S3",
  label: "Swings",
  build(k) {
    const at = w => k.vo.lead + W[w];
    const xs = i => X0 + (X1 - X0) * i / (N - 1);

    const g = k.svg(`<svg class="abs" width="1920" height="1080" viewBox="0 0 1920 1080">
      <defs>
        <linearGradient id="s3area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f3f5ef" stop-opacity="0.16"/><stop offset="1" stop-color="#f3f5ef" stop-opacity="0"/></linearGradient>
        <clipPath id="s3clip"><rect class="clip" x="0" y="0" width="0" height="1080"/></clipPath>
      </defs>
      <g class="plot">
        <line class="base" x1="${X0}" y1="${Y0}" x2="${X1}" y2="${Y0}" stroke="#a4ada4" stroke-opacity="0.45" stroke-width="2" stroke-dasharray="4 10"/>
        <g clip-path="url(#s3clip)">
          <path class="area" fill="url(#s3area)"/>
          <path class="ln" fill="none" stroke="#f3f5ef" stroke-width="5" stroke-linejoin="round" stroke-linecap="round"/>
        </g>
        <g class="marks"></g>
        <circle class="halo" r="22" fill="#F28C28" opacity="0.22"/>
        <circle class="dot" r="9" fill="#F28C28"/>
      </g>
    </svg>`);
    const plot = g.querySelector(".plot"), ln = g.querySelector(".ln"), area = g.querySelector(".area"), clip = g.querySelector(".clip");
    const base = g.querySelector(".base"), dot = g.querySelector(".dot"), halo = g.querySelector(".halo"), marks = g.querySelector(".marks");

    // Markers above the dips and spikes, revealed as the pen passes them.
    const markEls = [];
    for (let i = 0; i < N; i++) if (RAIN.has(i) || GAME.has(i)) {
      const m = document.createElementNS("http://www.w3.org/2000/svg", "g");
      m.innerHTML = RAIN.has(i) ? DROP : BALL; marks.appendChild(m);
      markEls.push({ m, i, rain: RAIN.has(i) });
    }

    const P = { draw: 0, amp: 0.55, shake: 0 };
    k.tween(base, { opacity: [0, 1] }, { at: 0.05, dur: 0.5 });
    k.tween(P, { draw: [0, 1] }, { at: 0.15, dur: at("swings") + 0.1, ease: "move" });
    k.tween(P, { amp: [0.55, 1] }, { at: at("week") - 0.2, dur: 0.6, ease: "move" });
    // One lurch on "swings": a damped wobble, then it settles.
    k.fn(at("swings"), 0.9, p => { P.shake = Math.sin(p * Math.PI * 3) * (1 - p); }, "linear");
    k.cue("whoosh", at("swings"));
    markEls.forEach(e => {
      const t0 = 0.15 + (at("swings") + 0.1) * (e.i / (N - 1)) * 0.85;
      k.tween(e.m, { opacity: [0, 1] }, { at: t0, dur: 0.4 });
    });

    k.after(() => {
      const pts = BASE.map((v, i) => [xs(i), Y0 - v * 0.8 * P.amp * (1 + 0.35 * P.shake * (i % 2 ? 1 : -0.6))]);
      const d = smooth(pts);
      ln.setAttribute("d", d);
      area.setAttribute("d", `${d} L${X1} 830 L${X0} 830 Z`);
      plot.setAttribute("transform", `translate(0 ${(P.shake * 10).toFixed(2)})`);
      const x = X0 + (X1 - X0) * P.draw;
      clip.setAttribute("width", x + 4);
      // The pen sits exactly on the drawn curve: binary-search the path length for this x.
      const total = ln.getTotalLength();
      let lo = 0, hi = total;
      for (let it = 0; it < 22; it++) { const m = (lo + hi) / 2; if (ln.getPointAtLength(m).x < x) lo = m; else hi = m; }
      const y = ln.getPointAtLength(lo).y;
      dot.setAttribute("cx", x); dot.setAttribute("cy", y); halo.setAttribute("cx", x); halo.setAttribute("cy", y);
      const show = P.draw > 0.002 ? 1 : 0;
      dot.style.opacity = show; halo.style.opacity = show * 0.22;
      markEls.forEach(e => {
        const [mx, my] = pts[e.i];
        e.m.setAttribute("transform", `translate(${mx} ${e.rain ? my + 44 : my - 40})`);
      });
    });

    const title = caption(k, "Small-business owners: your week *swings*", at("either") + 0.2, null, { cls: "section abs" });
    Object.assign(title.style, { left: "160px", top: "150px", fontSize: "76px", lineHeight: "84px", whiteSpace: "nowrap" });
    const sw = title.querySelectorAll(".w")[4];   // "swings" lurches on the word
    sw.style.transformOrigin = "0% 80%";
    k.tween(sw, { rotate: [0, -2.5] }, { at: at("swings"), dur: 0.25, ease: "move" });
    k.tween(sw, { rotate: [-2.5, 0] }, { at: at("swings") + 0.25, dur: 0.6, ease: "move" });
    const eyebrow = k.el("div", "eyebrow abs", "Daily revenue · illustrative");
    Object.assign(eyebrow.style, { left: "166px", top: "252px" });
    k.enter(eyebrow, at("either") + 0.4, { y: 8 });

    // "…you can't plan around it": next week is a row of unknowns.
    const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], cw = 200, gap = (X1 - X0 - cw * 7) / 6;
    days.forEach((d, i) => {
      const c = k.el("div", "abs", `<div style="font:600 18px/1 var(--sans);letter-spacing:.12em;text-transform:uppercase;color:var(--muted-d)">${d}</div>
        <div style="font:600 52px/1 var(--serif);color:var(--paper);margin-top:10px">?</div>`);
      Object.assign(c.style, { left: X0 + i * (cw + gap) + "px", top: "880px", width: cw + "px", height: "110px", borderRadius: "14px",
        border: "1.5px solid rgba(243,245,239,0.18)", background: "rgba(243,245,239,0.04)", display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center" });
      k.enter(c, at("cant") + i * 0.07, { y: 14 });
    });
    const lab = k.el("div", "eyebrow abs", "Next week");
    Object.assign(lab.style, { left: "166px", top: "838px" });
    k.enter(lab, at("cant") - 0.05, { y: 8 });
  },
};
