// S1 · Rain. "Rain on a Saturday empties the shop."
// A bike shop at dusk: rain builds in three depth layers, the customers inside leave, and the warm
// window light (and its reflection on the wet street) dims. The camera creeps in the whole time.
import { clamp, caption, rand } from "../lib.js";

const NS = "http://www.w3.org/2000/svg";
const cue = (k, name, at) => k.cue?.(name, at);

// Word onsets in the VO clip (whisper): Rain 0.00, Saturday 0.44, empties 0.74, shop 1.42.
const W = { rain: 0.0, saturday: 0.44, empties: 0.74, shop: 1.42 };

export default {
  id: "S1",
  label: "Rain",
  transition: "cut", // open on the storefront, not a blank frame
  build(k) {
    const at = w => k.vo.lead + W[w];

    // Back layer: street, storefront, far rain. Grouped so the camera can push in on it.
    const bg = k.svg(`<svg class="abs" width="1920" height="1080" viewBox="0 0 1920 1080">
      <defs>
        <linearGradient id="s1win" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f8dfb0"/><stop offset="1" stop-color="#e7b25f"/></linearGradient>
        <linearGradient id="s1refl" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#e7b25f" stop-opacity="0.38"/><stop offset="1" stop-color="#e7b25f" stop-opacity="0"/></linearGradient>
        <radialGradient id="s1halo" cx="0.5" cy="0.5" r="0.5"><stop offset="0" stop-color="#f6cf86" stop-opacity="0.32"/><stop offset="1" stop-color="#f6cf86" stop-opacity="0"/></radialGradient>
        <linearGradient id="s1street" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0d1a13"/><stop offset="1" stop-color="#08100c"/></linearGradient>
        <filter id="s1blur" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="10 4"/></filter>
        <radialGradient id="s1vig" cx="0.55" cy="0.5" r="0.75"><stop offset="0.55" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity="0.55"/></radialGradient>
      </defs>
      <g class="world">
        <g fill="#0f271b">${Array.from({ length: 14 }, (_, i) => { const w = 110 + rand(i, 11) * 120, h = 260 + rand(i, 12) * 420, x = i * 150 - 40;
          return `<rect x="${x}" y="${910 - h}" width="${w}" height="${h}"/>` + Array.from({ length: 4 }, (_, j) => rand(i * 5 + j, 13) > 0.62
            ? `<rect x="${x + 18 + (j % 2) * (w / 2)}" y="${910 - h + 40 + Math.floor(j / 2) * 70}" width="22" height="30" fill="#3b4a32" opacity="0.32"/>` : "").join(""); }).join("")}</g>
        <g class="far"></g>
        <ellipse class="halo" cx="1230" cy="640" rx="560" ry="380" fill="url(#s1halo)"/>
        <g class="shop">
          <rect x="930" y="40" width="820" height="215" fill="#163b2a"/>
          ${Array.from({ length: 5 }, (_, i) => `<rect x="${985 + i * 150}" y="90" width="90" height="120" rx="3" fill="${i === 3 ? "#5c5a3c" : "#0f2a1d"}"/>`).join("")}
          <rect x="930" y="250" width="820" height="660" fill="#1b4532"/>
          <rect x="930" y="250" width="820" height="12" fill="#245a41"/>
          <rect x="930" y="262" width="820" height="78" fill="#143826"/>
          <text x="1340" y="314" text-anchor="middle" font-family="IBM Plex Sans" font-weight="600" font-size="34" letter-spacing="10" fill="#e9ede4">HUDSON BIKES</text>
          <g>${Array.from({ length: 11 }, (_, i) => `<path d="M${930 + i * 74.5} 350 h74.5 v52 a37.25 20 0 0 1 -74.5 0z" fill="${i % 2 ? "#e9ede4" : "#20583f"}"/>`).join("")}</g>
          <rect x="975" y="460" width="470" height="350" rx="4" fill="#0f2a1d"/>
          <rect class="glow" x="985" y="470" width="450" height="330" rx="2" fill="url(#s1win)"/>
          <g class="people" fill="#2c3a2f">
            <g class="p0"><circle cx="1080" cy="625" r="20"/><path d="M1052 720 q0 -66 28 -66 q28 0 28 66 z"/><rect x="1056" y="712" width="48" height="88" rx="10"/></g>
            <g class="p1"><circle cx="1330" cy="618" r="21"/><path d="M1300 718 q0 -70 30 -70 q30 0 30 70 z"/><rect x="1304" y="710" width="52" height="90" rx="10"/></g>
          </g>
          <g fill="none" stroke="#173b29" stroke-width="7" stroke-linecap="round">
            <circle cx="1165" cy="752" r="36"/><circle cx="1275" cy="752" r="36"/>
            <path d="M1165 752 L1200 712 L1258 712 L1275 752 M1200 712 L1220 752 L1258 712 M1196 700 h16 M1252 700 l8 -10"/>
          </g>
          <g stroke="#1b4532" stroke-width="10"><line x1="1210" y1="470" x2="1210" y2="800"/></g>
          <rect x="1505" y="460" width="190" height="450" fill="#0f2a1d"/>
          <rect x="1515" y="470" width="170" height="440" fill="#123323"/>
          <circle cx="1665" cy="700" r="6" fill="#F28C28"/>
          <rect class="sign" x="1540" y="510" width="120" height="48" rx="6" fill="#f3f5ef"/>
          <text class="signt" x="1600" y="543" text-anchor="middle" font-family="IBM Plex Sans" font-weight="600" font-size="24" letter-spacing="2" fill="#20583f">OPEN</text>
          <text class="signc" x="1600" y="543" text-anchor="middle" font-family="IBM Plex Sans" font-weight="600" font-size="22" letter-spacing="2" fill="#852f22" opacity="0">CLOSED</text>
          <rect x="930" y="900" width="820" height="10" fill="#122e20"/>
        </g>
        <rect x="0" y="910" width="1920" height="170" fill="url(#s1street)"/>
        <rect class="refl" x="985" y="914" width="450" height="160" fill="url(#s1refl)" filter="url(#s1blur)"/>
        <rect x="0" y="910" width="1920" height="3" fill="#1d3a2b"/>
        <g class="ripples" fill="none" stroke="#a9c7b6"></g>
      </g>
      <rect width="1920" height="1080" fill="url(#s1vig)"/>
    </svg>`);
    const world = bg.querySelector(".world"), far = bg.querySelector(".far"), ripples = bg.querySelector(".ripples");
    const shop = bg.querySelector(".shop"), glow = bg.querySelector(".glow"), refl = bg.querySelector(".refl"), halo = bg.querySelector(".halo");
    const people = [bg.querySelector(".p0"), bg.querySelector(".p1")];
    const sign = bg.querySelector(".sign"), signC = bg.querySelector(".signc");

    const title = caption(k, "Rain.", at("rain"), null, { cls: "hero abs", y: -36 });
    Object.assign(title.style, { left: "160px", top: "400px", fontSize: "176px", lineHeight: "1", color: "#f3f5ef" });
    const eyebrow = k.el("div", "eyebrow abs", "on a Saturday");
    Object.assign(eyebrow.style, { left: "168px", top: "600px", fontSize: "26px", letterSpacing: "0.16em" });
    k.enter(eyebrow, at("saturday"), { y: 10 });
    // Clear the title slot just before S2's title takes it.
    k.exit(title, k.dur - 0.3, { dur: 0.3 }); k.exit(eyebrow, k.dur - 0.3, { dur: 0.3 });

    // Front layer: near rain, over the title for depth.
    const fg = k.svg(`<svg class="abs" width="1920" height="1080" viewBox="0 0 1920 1080" style="pointer-events:none"><g class="near"></g></svg>`);
    const near = fg.querySelector(".near");

    const mk = (parent, n, layer) => Array.from({ length: n }, (_, i) => {
      const l = document.createElementNS(NS, "line"); parent.appendChild(l);
      const s = layer * 1000 + i;
      return { l, x: rand(s) * 2200 - 140, ph: rand(s, 4) * 1300, sp: [900, 1250, 1700][layer] + rand(s, 2) * 300,
        len: [18, 34, 64][layer] + rand(s, 3) * [12, 20, 34][layer], o: [0.22, 0.38, 0.55][layer] + rand(s, 5) * 0.2,
        w: [1.2, 1.8, 2.6][layer], gate: rand(s, 6) };
    });
    const layers = [mk(far, 110, 0), mk(far, 90, 1), mk(near, 34, 2)];
    for (const L of layers) for (const d of L) { d.l.setAttribute("stroke", "#b7d1c2"); d.l.setAttribute("stroke-width", d.w); d.l.setAttribute("stroke-linecap", "round"); }
    const rips = Array.from({ length: 16 }, (_, i) => { const e = document.createElementNS(NS, "ellipse"); ripples.appendChild(e); return e; });

    // Rain density ramps with the word, then holds heavy.
    const R = { d: 0.12 }, Cam = { s: 1 }, Dim = { v: 0 };
    k.tween(R, { d: [0.12, 1] }, { at: at("rain") - 0.2, dur: 1.4, ease: "move" });
    k.tween(Cam, { s: [1, 1.07] }, { at: 0, dur: k.dur, ease: "linear" });
    // "empties": customers leave one by one, the light goes down.
    people.forEach((p, i) => k.tween(p, { opacity: [1, 0], x: [0, i ? 26 : -26] }, { at: at("empties") + i * 0.16, dur: 0.6, ease: "move" }));
    k.tween(Dim, { v: [0, 1] }, { at: at("empties"), dur: 1.2, ease: "move" });
    // The OPEN sign gutters (two soft dips, no strobe) and turns to CLOSED as the shop empties.
    const signT = bg.querySelector(".signt"), t0 = at("shop") - 0.35;
    k.tween(sign, { opacity: [1, 0.45] }, { at: t0, dur: 0.12, ease: "move" });
    k.tween(sign, { opacity: [0.45, 0.9] }, { at: t0 + 0.12, dur: 0.12, ease: "move" });
    k.tween(sign, { opacity: [0.9, 0.3] }, { at: t0 + 0.3, dur: 0.15, ease: "move" });
    k.tween(sign, { opacity: [0.3, 0.55] }, { at: t0 + 0.5, dur: 0.4, ease: "move" });
    k.tween(signT, { opacity: [1, 0] }, { at: t0 + 0.3, dur: 0.15, ease: "move" });
    k.tween(signC, { opacity: [0, 1] }, { at: t0 + 0.5, dur: 0.4, ease: "move" });
    cue(k, "whoosh", 0);

    const wind = 0.2;
    k.after(t => {
      world.setAttribute("transform", `translate(${1230 * (1 - Cam.s)} ${600 * (1 - Cam.s)}) scale(${Cam.s})`);
      glow.style.opacity = 1 - 0.62 * Dim.v; refl.style.opacity = 1 - 0.7 * Dim.v; halo.style.opacity = 1 - 0.8 * Dim.v;
      shop.style.filter = `brightness(${1 - 0.28 * Dim.v})`;
      layers.forEach(L => L.forEach(d => {
        const on = d.gate < R.d;
        d.l.style.display = on ? "" : "none"; if (!on) return;
        const y = ((d.ph + t * d.sp) % 1300) - 120, x = d.x - (y + 120) * wind;
        d.l.setAttribute("x1", x); d.l.setAttribute("y1", y); d.l.setAttribute("x2", x - d.len * wind); d.l.setAttribute("y2", y + d.len);
        d.l.setAttribute("opacity", d.o);
      }));
      // Splash rings on the street, each on its own 0.7s cycle.
      rips.forEach((e, i) => {
        const p = ((t + rand(i, 8) * 0.7) / 0.7) % 1, cyc = Math.floor((t + rand(i, 8) * 0.7) / 0.7);
        const cx = 80 + rand(i * 7 + cyc, 9) * 1760, cy = 940 + rand(i * 3 + cyc, 10) * 120;
        e.setAttribute("cx", cx); e.setAttribute("cy", cy); e.setAttribute("rx", 4 + p * 26); e.setAttribute("ry", 1 + p * 5);
        e.setAttribute("stroke-width", 1.4); e.setAttribute("opacity", clamp(R.d * 1.2 - 0.2, 0, 1) * 0.5 * (1 - p));
      });
    });
  },
};
