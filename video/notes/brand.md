# Offset brand notes for the product video

Source: `main` (`frontend/app/globals.css`, `frontend/public/offset-logo.svg`, `components/Header.tsx`).
Tagline in the app header: **"Steadier weeks. Your call."**

> Incoming: `origin/feat/blotter-theme` (cf21891, frontend only) restyles the app as a trader's blotter:
> ruled ledger paper, hedges as trade tickets, statuses as rubber stamps (green desk, red declines,
> amber waiting on owner, violet simulated), IBM Plex Sans / Sans Condensed / Mono via @fontsource,
> `--ledger #1f5c45`, `--pencil #a4ada4`. Not merged. Tokens below are from `main`. If that branch
> lands before capture, re-shoot screenshots; the palette is close (same green/red/amber/violet roles),
> and IBM Plex would become the type choice for the video too.

## Logo

Shield, left half solid, right half outlined, in one orange. The split shield is the idea: half the
week is covered, the owner keeps the rest. Copy at `video/assets/offset-logo.svg`.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" aria-label="Offset">
  <path d="M32 4 L56 12 V30 C56 45 46 55 32 60 C18 55 8 45 8 30 V12 Z" fill="none" stroke="#F28C28" stroke-width="5" stroke-linejoin="round"/>
  <path d="M32 4 L8 12 V30 C8 45 18 55 32 60 Z" fill="#F28C28"/>
</svg>
```

- **Light background** (`#f3f5ef` paper or `#fffefa` surface): use as is. Orange on paper is ~2.4:1, fine for
  a mark but don't render it smaller than 40 px tall; pair it with the wordmark in ink `#233b30`.
- **Dark background** (`#143c2a` deep green or `#0f1a14` near-black): use as is; orange reads well (>5:1
  on `#143c2a`). Wordmark in `#f3f5ef`.
- Don't recolor, add gradients, or put it on orange. Clear space around it = half its height.
- Wordmark: "Offset" set in the title face (see Typography), weight 600, letter-spacing -0.02em,
  gap between mark and word = 0.25 x mark height (app uses 10 px gap at 40 px mark).
- End card: mark at 160 px, wordmark 96 px, tagline 32 px muted below.

## Color tokens

| Token | Hex | Role / where it comes from |
|---|---|---|
| `bg` | `#f3f5ef` | Page background (warm off-white paper) |
| `surface` | `#fffefa` | Panels, hedge cards |
| `surface-tint` | `#eaf0e6` | Headline callout in hedge card |
| `border` | `#d7dfd1` | Panel borders; rules `#e3e7df` |
| `text` | `#233b30` | Body ink (dark green-black) |
| `muted` | `#52645a` | Captions, labels, small text |
| `primary` | `#20583f` | Brand green: primary button, links, active tab |
| `primary-deep` | `#143c2a` | Hover / dark-mode backdrop for video |
| `logo-orange` | `#F28C28` | Logo only; in video, use it sparingly as the single highlight color (highlight rings, cursor pulse) |
| `positive` / approve | `#247153` (chart/hedged), chip `#e2f0e7` bg / `#215637` text | Proposed, approved, settled; "hedged" bars |
| `unhedged` / neutral data | `#9aa99e` | Unhedged bars, training-period data |
| `negative` / decline | `#aa5037` rule, `#852f22` text, `#fbe9e2` bg, `#fff4ef` panel | Declined, rejected, mismatches |
| `warning` / estimate | `#b47a1d` rule, `#684611` text, `#faf0d9` bg | "Estimated" badge, pending approval, sample-week banner |
| `simulated` | `#3e3170` text, `#e8e4f4` bg | "Simulated" badge (I6 labels) |
| `uploaded` | `#24466b` text, `#e4ecf6` bg | "Uploaded · sample" badge |
| `focus` | `#906119` | Focus ring (amber) |

Video dark mode (title cards, transitions): background `#143c2a` -> `#0f1a14` vertical gradient,
text `#f3f5ef`, muted `#a4ada4`, accent `#F28C28`. App screenshots stay light and sit on this.

## Typography

The app on `main` uses system faces: **Arial/Helvetica** for UI and **Georgia** for display
(`.intro h2` 36 px, backtest headline, demo summary). Figures use `font-variant-numeric: tabular-nums`.

For the video, load from Google Fonts (closest matches, and aligned with the incoming blotter theme):

| Use | Google Fonts family | Weights |
|---|---|---|
| Titles / display (stand-in for Georgia) | `Source Serif 4` (or `Newsreader`) | 400, 600 |
| UI captions, labels | `IBM Plex Sans` | 400, 500, 600 |
| Numbers, prices, tickers | `IBM Plex Mono` | 400, 500 (always tabular) |

`https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap`

Type scale at 1920x1080 (safe area: 96 px side margins, 72 px top/bottom):

| Style | Face | Size / line-height | Weight | Tracking |
|---|---|---|---|---|
| Hero title | Source Serif 4 | 96 / 104 | 600 | -0.02em |
| Section title | Source Serif 4 | 64 / 72 | 600 | -0.015em |
| Big number | IBM Plex Mono | 120 / 120 | 500 | -0.02em |
| Caption (lower third) | IBM Plex Sans | 40 / 52 | 500 | -0.005em |
| Body / subtitle | IBM Plex Sans | 32 / 44 | 400 | 0 |
| Small label / eyebrow | IBM Plex Sans | 22 / 28 | 600 | +0.12em, uppercase |
| Badge text (Estimated/Simulated) | IBM Plex Sans | 22 / 28 | 600 | +0.04em |

Max caption width ~1100 px (about 45 characters per line). Left-align captions; center only hero and end cards.

## Motion language

Calm, precise, unhurried. It should feel like a careful accountant, not a trading floor. Nothing bounces, spins, or flashes.

1. **Easing.** Default `cubic-bezier(0.22, 1, 0.36, 1)` (ease-out-quint) for entrances;
   `cubic-bezier(0.64, 0, 0.78, 0)` (ease-in-quint) for exits; `cubic-bezier(0.65, 0, 0.35, 1)` for
   moves between positions. If using Motion springs: `{ type: "spring", stiffness: 170, damping: 26, mass: 1 }`
   (critically damped, no overshoot). No bounce, ever.
2. **Durations.** Text in 500 ms, out 300 ms. Screen transitions 600–700 ms. Holds: a caption stays
   up at least 2.5 s + 0.3 s per word beyond 6. One thing moves at a time; stagger siblings 60–80 ms.
3. **Text enters** with opacity 0 -> 1 plus translateY 12 px -> 0 (matches the app's own `demo-in`
   keyframe, scaled up). Exits are opacity-only, slightly faster. Words aren't typed out except for the
   desk's chat/hypothesis lines, which the app itself types. Numbers count up only when they come from
   the product screen (I2: never invent a number on a title card); count over 800 ms, ease-out, tabular mono.
4. **Screenshot framing.** App captures sit in a light window: 16 px corner radius, 1 px `#d7dfd1`
   border, a 40 px top bar `#e6ebe1` with three 12 px muted dots (`#cdd7cb`), shadow
   `0 30px 80px rgba(15,26,20,0.35), 0 4px 12px rgba(15,26,20,0.15)` on the dark backdrop. Window fills
   about 82% of frame width. Slow Ken Burns: scale 1.00 -> 1.04 over the shot's length, linear, drift
   toward the area being discussed; never pan and zoom at the same time as a highlight.
5. **Highlighting UI.** To point at an element: dim the rest of the screenshot to 55% brightness (300 ms),
   draw a 3 px `#F28C28` rounded ring (radius 10 px, 8 px padding) that fades + scales from 1.03 -> 1.00
   over 400 ms, and optionally push in to 1.15–1.3x with the move easing over 900 ms. One highlight at a
   time. For the decline moment use the app's own red (`#aa5037`) ring instead of orange.
6. **Status changes are stamps, not fireworks.** Approve/decline/booked: badge fades in with scale
   0.96 -> 1.00 over 250 ms (matches `demo-pop`, softened). Keep "Estimated" and "Simulated" labels on
   screen whenever their numbers are (I6); never crop them out of a framed shot.

Transitions between scenes: 600 ms crossfade through the dark backdrop, or a horizontal slide of the
window (move easing, 700 ms). No whip pans, no glitch, no zoom blur.
