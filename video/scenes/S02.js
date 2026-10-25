// S2 · Game night. "A home game could crowd the street, or it might not."
// The arena's floodlights come on one by one, a crowd fills the street in front of it, and on
// "or it might not" most of that crowd drains away again.
import { caption, rand } from "../lib.js";

const NS = "http://www.w3.org/2000/svg";

// Word onsets after the speech starts (user.m4a; phrase pauses from silencedetect, words spread within a phrase): home 0.19, game 0.46,
// crowd 0.89, street 1.35, or 1.60, might 2.07.
const W = { home: 0.19, game: 0.46, crowd: 0.89, street: 1.35, or: 1.6, might: 2.07 };

export default {
  id: "S2",
  label: "Game night",
  build(k) {
    const at = w => k.vo.lead + W[w];
    const CX = 1360; // arena centre
    const towers = [[960, 340], [1110, 260], [1610, 260], [1760, 340]];

    const g = k.svg(`<svg class="abs" width="1920" height="1080" viewBox="0 0 1920 1080">
      <defs>
        <linearGradient id="s2beam" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff2cf" stop-opacity="0.5"/><stop offset="1" stop-color="#fff2cf" stop-opacity="0"/></linearGradient>
        <radialGradient id="s2glow" cx="0.5" cy="0.5" r="0.5"><stop offset="0" stop-color="#f7e2ad" stop-opacity="0.38"/><stop offset="1" stop-color="#f7e2ad" stop-opacity="0"/></radialGradient>
        <radialGradient id="s2lamp" cx="0.5" cy="0.5" r="0.5"><stop offset="0" stop-color="#fff6dc" stop-opacity="0.9"/><stop offset="1" stop-color="#fff6dc" stop-opacity="0"/></radialGradient>
        <radialGradient id="s2pool" cx="0.5" cy="0.4" r="0.5"><stop offset="0" stop-color="#6d6a48" stop-opacity="0.55"/><stop offset="1" stop-color="#6d6a48" stop-opacity="0"/></radialGradient>
        <linearGradient id="s2street" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0d1a13"/><stop offset="1" stop-color="#070e0a"/></linearGradient>
        <radialGradient id="s2vig" cx="0.6" cy="0.5" r="0.78"><stop offset="0.55" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity="0.55"/></radialGradient>
      </defs>
      <g class="world">
        <ellipse class="glow" cx="${CX}" cy="560" rx="760" ry="420" fill="url(#s2glow)" opacity="0"/>
        <g class="beams"></g>
        <path d="M780 900 C830 610 1080 510 ${CX} 510 C1640 510 1890 610 1940 900 Z" fill="#0c2218"/>
        <path d="M840 900 C890 670 1100 590 ${CX} 590 C1620 590 1830 670 1880 900" fill="none" stroke="#1d4a35" stroke-width="5"/>
        <g class="rows" stroke="#163a29" stroke-width="3" fill="none">
          ${[0, 1, 2].map(i => `<path d="M${890 + i * 40} 900 C${940 + i * 40} ${710 + i * 30} ${1130} ${650 + i * 30} ${CX} ${650 + i * 30} C${1590} ${650 + i * 30} ${1790 - i * 40} ${710 + i * 30} ${1830 - i * 40} 900"/>`).join("")}
        </g>
        <g class="towers"></g>
        <rect x="0" y="900" width="1920" height="180" fill="url(#s2street)"/>
        <rect x="0" y="900" width="1920" height="3" fill="#1d3a2b"/>
        <ellipse class="pool" cx="${CX}" cy="960" rx="900" ry="120" fill="url(#s2pool)" opacity="0"/>
        <g class="crowd" fill="#050c08"></g>
      </g>
      <rect width="1920" height="1080" fill="url(#s2vig)"/>
    </svg>`);
    const world = g.querySelector(".world"), beams = g.querySelector(".beams"), tw = g.querySelector(".towers");
    const glow = g.querySelector(".glow"), pool = g.querySelector(".pool"), crowdG = g.querySelector(".crowd");

    const lamps = towers.map(([x, y], i) => {
      tw.insertAdjacentHTML("beforeend", `<line x1="${x}" y1="${y}" x2="${x}" y2="${y + 340}" stroke="#0c2218" stroke-width="12"/>
        <rect x="${x - 46}" y="${y - 26}" width="92" height="34" rx="5" fill="#26372d"/>
        <rect class="lamp" x="${x - 46}" y="${y - 26}" width="92" height="34" rx="5" fill="#fff6dc" opacity="0"/>
        <ellipse class="bloom" cx="${x}" cy="${y - 9}" rx="120" ry="70" fill="url(#s2lamp)" opacity="0"/>`);
      const tx = CX + (x - CX) * 0.18;
      beams.insertAdjacentHTML("beforeend", `<path class="bm" d="M${x - 46} ${y} L${x + 46} ${y} L${tx + 230} 820 L${tx - 230} 820 Z" fill="url(#s2beam)" opacity="0"/>`);
      return i;
    });
    const lampEls = g.querySelectorAll(".lamp"), blooms = g.querySelectorAll(".bloom"), bms = g.querySelectorAll(".bm");
    // Lights come on across the "home game" beat, left to right: a quick warm-up, never a strobe.
    lamps.forEach(i => {
      const t0 = at("game") + i * 0.11;
      k.tween(lampEls[i], { opacity: [0, 1] }, { at: t0, dur: 0.18 });
      k.tween(blooms[i], { opacity: [0, 1] }, { at: t0, dur: 0.35 });
      k.tween(bms[i], { opacity: [0, 1] }, { at: t0 + 0.05, dur: 0.6 });
      k.cue("tick", t0);
    });
    k.tween(glow, { opacity: [0, 1] }, { at: at("game"), dur: 0.9 });
    k.tween(pool, { opacity: [0, 1] }, { at: at("game") + 0.2, dur: 0.9 });

    // The crowd: silhouettes along the street, filling from the arena outwards on "crowd".
    const people = Array.from({ length: 64 }, (_, i) => {
      const x = 520 + (i / 63) * 1400 + (rand(i, 21) - 0.5) * 36, row = rand(i, 22), s = 1.0 + row * 0.7;
      const y = 930 + row * 140, el = document.createElementNS(NS, "g");
      el.innerHTML = `<circle cx="0" cy="${-58 * s}" r="${13 * s}"/><path d="M${-22 * s} 0 q0 ${-46 * s} ${22 * s} ${-46 * s} q${22 * s} 0 ${22 * s} ${46 * s} z"/>`;
      el.setAttribute("transform", `translate(${x.toFixed(1)} ${y.toFixed(1)})`);
      crowdG.appendChild(el);
      const d = Math.abs(x - CX) / 1300;
      return { el, at: at("crowd") + d * 0.55 + rand(i, 23) * 0.12, stays: rand(i, 24) < 0.22, y };
    });
    people.sort((a, b) => a.y - b.y).forEach(p => crowdG.appendChild(p.el));
    people.forEach((p, i) => {
      k.tween(p.el, { opacity: [0, 1] }, { at: p.at, dur: 0.45 });
      if (!p.stays) k.tween(p.el, { opacity: [1, 0] }, { at: at("or") + 0.1 + rand(i, 25) * 0.45, dur: 0.5, ease: "in" });
    });
    // When the street empties, the glow over it softens too.
    k.tween(glow, { opacity: [1, 0.55] }, { at: at("or") + 0.1, dur: 0.8, ease: "move" });

    const title = caption(k, "Game night.", at("home"), null, { cls: "hero abs", wordStagger: 0.09 });
    Object.assign(title.style, { left: "160px", top: "400px", fontSize: "136px", lineHeight: "1", color: "#f3f5ef" });
    // A small second line under the title, landing with "crowd the street".
    const line2 = k.el("div", "abs", "Packed street, or empty tables?");
    Object.assign(line2.style, { left: "166px", top: "556px", font: "500 36px/44px var(--sans)", color: "var(--paper)", opacity: 0 });
    k.enter(line2, at("crowd") - 0.1, { y: 10 });
    const sub = k.el("div", "abs", "Or it might not.");
    Object.assign(sub.style, { left: "166px", top: "624px", font: "400 italic 64px/1.1 var(--serif)", color: "var(--muted-d)" });
    k.enter(sub, at("might") - 0.12, { y: 10 });
    k.exit(title, k.dur - 0.3, { dur: 0.3 }); k.exit(line2, k.dur - 0.3, { dur: 0.3 }); k.exit(sub, k.dur - 0.3, { dur: 0.3 });

    const Cam = { s: 1 };
    k.tween(Cam, { s: [1.0, 1.06] }, { at: 0, dur: k.dur, ease: "linear" });
    k.after(() => world.setAttribute("transform", `translate(${CX * (1 - Cam.s)} ${620 * (1 - Cam.s)}) scale(${Cam.s})`));
  },
};
