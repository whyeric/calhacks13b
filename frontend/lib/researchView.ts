// Display strings for the live research report (POST /research). Formatting only: every figure
// is an API string or stat, shown as is (I2; the no-money-math lint rule applies).
import { fmtUsd } from "./format";
import type {
  ResearchEstimate,
  ResearchHypothesis,
  ResearchPeriod,
} from "./types";

const minus = (s: string) => s.replace(/^-/, "−");
// Signed dollars: "−$1,923.43", "+$1,151.68".
export const signedUsd = (value: string) =>
  value.startsWith("-") ? fmtUsd(value) : `+${fmtUsd(value)}`;
// The % effect is a stat (a number), shown to one decimal: "−18.2%", "+10.9%".
export const signedPct = (pct: number) => {
  const text = pct.toFixed(1);
  return text.startsWith("-") ? `${minus(text)}%` : `+${text}%`;
};
export const estimateText = (e: ResearchEstimate) =>
  `${signedPct(e.pct)} · ${signedUsd(e.effect_usd)}/day`;
export const ciText = (e: ResearchEstimate) =>
  `90% CI ${signedUsd(e.ci90[0])} to ${signedUsd(e.ci90[1])}`;
export const daysText = (e: ResearchEstimate) =>
  `${e.n_event_days.toLocaleString("en-US")} ${e.n_event_days === 1 ? "day" : "days"}`;
// [point, ci_low, ci_high] decimal strings for the forest plot geometry.
export const plotOf = (e: ResearchEstimate): [string, string, string] => [
  e.effect_usd,
  e.ci90[0],
  e.ci90[1],
];

export function placeboText(h: ResearchHypothesis): string {
  if (h.placebo_p === null) return "Not run (too few days)";
  const p = h.placebo_p.toFixed(2);
  return h.reasons.includes("placebo_fired")
    ? `Fired (p ${p})`
    : `Not significant (p ${p})`;
}

const REASON_TEXT: Record<ResearchHypothesis["reasons"][number], string> = {
  not_significant: "Not distinguishable from zero",
  thin_support: "Too few event days",
  failed_bh: "Didn't survive the correction for multiple tests",
  placebo_fired: "The placebo also fired",
  did_not_replicate: "Didn't hold up on unseen data",
  sign_flipped: "Flipped sign on unseen data",
};
export function verdictNote(h: ResearchHypothesis): string | null {
  if (h.verdict === "NOT FOUND")
    return h.reasons.map((r) => REASON_TEXT[r]).join("; ");
  if (h.upside) return "upside, no protection needed";
  if (h.sendable) return "hedgeable";
  return "no daily contract to buy";
}

// "2024", "2025–26": the years a period spans (string slicing only).
export function periodLabel(p: ResearchPeriod): string {
  const a = p.start.slice(0, 4);
  const b = p.end.slice(0, 4);
  return a === b ? a : `${a}–${b.slice(2)}`;
}
