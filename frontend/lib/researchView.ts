// Display strings for the live research report (POST /research). Formatting only: every figure
// is an API string or stat, shown as is (I2; the no-money-math lint rule applies).
import { fmtUsd } from "./format";
import type {
  ResearchEstimate,
  ResearchHypothesis,
  ResearchPeriod,
  ResearchReport,
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

// --- What the report table renders: a live report, or the labeled precomputed fallback ---
// Decimal strings for the forest plot geometry only: [point, ci_low, ci_high].
export type Interval = [string, string, string];
export type EstimateView = {
  text: string;
  ci: string;
  days: string;
  plot: Interval;
} | null; // null: not estimable
export type ResearchRow = {
  id: string;
  label: string;
  mechanism: string;
  train: EstimateView;
  unseen: EstimateView;
  placebo: string;
  verdict: "FOUND" | "NOT FOUND";
  verdictNote: string | null;
  venue: string;
  sendable: boolean;
};
export type ReportView = {
  source: "live" | "precomputed";
  summary: string;
  chips: string[];
  rows: ResearchRow[];
  periods: [string, string]; // training, unseen
  plotMax: string; // largest |CI end|: forest-plot geometry only
};
const estimateView = (e: ResearchEstimate | null): EstimateView =>
  e && { text: estimateText(e), ci: ciText(e), days: daysText(e), plot: plotOf(e) };
export const reportView = (report: ResearchReport): ReportView => ({
  source: "live",
  summary: report.summary,
  chips: report.protocol,
  rows: report.hypotheses.map((h) => ({
    id: h.id,
    label: h.label,
    mechanism: h.mechanism,
    train: estimateView(h.train),
    unseen: estimateView(h.holdout),
    placebo: placeboText(h),
    verdict: h.verdict,
    verdictNote: verdictNote(h),
    venue: h.venue,
    sendable: h.sendable,
  })),
  periods: [periodLabel(report.train), periodLabel(report.holdout)],
  plotMax: report.plot_max_usd,
});
