// S16 · Offset. The shield draws in its lockup place and its left half fills from the base up (half the
// week covered) as the wordmark wipes in, landing on "Offset"; the tagline follows the VO. Rest.
import { style, cue } from "./_polishB.js";

const MARK = 168, GAP = 44, WORD = 128;

export default {
  id: "S16",
  label: "Offset",
  build(k) {
    style(k);
    // Lockup geometry: measure the wordmark so mark + word sit centered.
    const ctx = document.createElement("canvas").getContext("2d");
    ctx.font = `600 ${WORD}px "Source Serif 4"`;
    const ww = ctx.measureText("Offset").width - 0.02 * WORD * 5;
    const total = MARK + GAP + ww, x0 = 960 - total / 2, cy = 470;

    // A faint warm glow behind the mark.
    const glow = k.el("div", "abs");
    Object.assign(glow.style, { left: "560px", top: cy - 400 + "px", width: "800px", height: "800px", borderRadius: "50%",
      background: "radial-gradient(closest-side, rgba(242,140,40,0.10), rgba(242,140,40,0))" });
    k.tween(glow, { opacity: [0, 1] }, { at: 0.3, dur: 1.6, ease: "move" });

    // The mark draws in its lockup place while the wordmark wipes in beside it: lands with "Offset".
    const mark = k.svg(`<svg class="abs" width="${MARK}" height="${MARK}" viewBox="0 0 64 64" aria-label="Offset" style="left:${x0}px;top:${cy - MARK / 2}px;overflow:visible">
      <defs><clipPath id="pb-fill"><rect class="lvl" x="0" y="64" width="64" height="64"/></clipPath></defs>
      <path class="lf" d="M32 4 L8 12 V30 C8 45 18 55 32 60 Z" fill="#F28C28" clip-path="url(#pb-fill)"/>
      <path class="lo" pathLength="1" stroke-dasharray="1" d="M32 4 L56 12 V30 C56 45 46 55 32 60 C18 55 8 45 8 30 V12 Z" fill="none" stroke="#F28C28" stroke-width="5" stroke-linejoin="round" stroke-linecap="round"/>
    </svg>`);
    const lo = mark.querySelector(".lo"), lvl = mark.querySelector(".lvl");
    k.tween(mark, { opacity: [0, 1], scale: [0.97, 1] }, { at: 0.0, dur: 0.4 });
    k.tween(lo, { dash: [0, 1] }, { at: 0.0, dur: 0.55, ease: "move" });
    // The left half fills from the base up: half the week covered.
    const F = { y: 64 };
    k.tween(F, { y: [64, 0] }, { at: 0.2, dur: 0.5, ease: "move" });
    k.after(() => lvl.setAttribute("y", F.y));
    cue(k, "logo", 0.2);

    const word = k.el("div", "hero abs", "Offset");
    Object.assign(word.style, { left: x0 + MARK + GAP + "px", top: cy - WORD * 0.58 + "px", font: `600 ${WORD}px/1 var(--serif)`, letterSpacing: "-0.02em", color: "#f3f5ef", whiteSpace: "nowrap" });
    // Wipe from the word's left edge (no bleed back over the mark).
    k.tween(word, { x: [-18, 0] }, { at: 0.1, dur: 0.5, ease: "move" });   // lands on the spoken "Offset"
    k.fn(0.1, 0.5, p => { word.style.clipPath = `inset(-30px ${(1 - p) * 100}% -30px 0)`; }, "move");

    // Tagline, on the VO.
    const tag = k.el("div", "abs");
    Object.assign(tag.style, { left: "0", width: "1920px", top: cy + 140 + "px", textAlign: "center", font: "400 40px/52px var(--sans)", color: "#a4ada4" });
    const a = k.el("span", null, "Steadier weeks. ", tag), b = k.el("span", null, "Your call.", tag);
    b.style.color = "#f3f5ef"; b.style.fontWeight = "500";
    [a, b].forEach(e => { e.style.display = "inline-block"; e.style.whiteSpace = "pre"; });
    k.tween(a, { opacity: [0, 1], y: [12, 0] }, { at: k.v(0.27), dur: 0.5 });
    k.tween(b, { opacity: [0, 1], y: [12, 0] }, { at: k.v(0.72), dur: 0.5 });
  }};
