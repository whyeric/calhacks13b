// Upload demo constants. The research REPORT is live (POST /research, see components/DemoDesk.tsx
// and lib/researchView.ts); what stays SCRIPTED here is the hedge card shown after "Send to the
// desk" (DEMO_HEDGE, budgets and log lines), hardcoded and labeled in the UI. Every $ figure is a
// literal string (I2; the no-money-math lint rule applies).
//
// Where DEMO_HEDGE's numbers came from: a desk calculation on the rain effect the protocol found
// on the synthetic Hudson Bike Co. sample (public/samples/hudson_bike_co_daily_revenue.csv).
import type { Budget, Business, LogEntry, PayoffRow } from "./types";

export const DEMO_ID = "up_hudson_bike_co_demo";
export const DEMO_DEFAULTS = { name: "Hudson Bike Co.", kind: "Bike rental" };
export const DEMO_KINDS = [
  "Bike rental",
  "Bar",
  "Restaurant",
  "Shop",
  "Transport",
  "Other",
];
export const DEMO_SAMPLE = {
  file: "hudson_bike_co_daily_revenue.csv",
  href: "/samples/hudson_bike_co_daily_revenue.csv",
  title: "Hudson Bike Co. daily revenue (synthetic sample)",
};
export const PRIVACY_NOTE = "Analyzed by your desk server; never stored";

// Weekly budget states for the demo business (hardcoded, never derived).
const WEEK = "2026-10-26";
export const DEMO_BUDGETS: Record<"open" | "pending" | "approved", Budget> = {
  open: {
    budget: "1000.00",
    spent: "0.00",
    pending: "0.00",
    remaining: "1000.00",
    week_start: WEEK,
  },
  pending: {
    budget: "1000.00",
    spent: "0.00",
    pending: "675.41",
    remaining: "324.59",
    week_start: WEEK,
  },
  approved: {
    budget: "1000.00",
    spent: "675.41",
    pending: "0.00",
    remaining: "324.59",
    week_start: WEEK,
  },
};
export function demoBusiness(name: string, budget: Budget): Business {
  return {
    id: DEMO_ID,
    name,
    kind: "uploaded",
    data_label: "uploaded",
    estimated: false,
    uploaded: true,
    scripted: true,
    revenue_source: "Uploaded daily revenue CSV (researched live, not stored)",
    zone_id: null,
    avg_check_usd: null,
    avg_check_label: null,
    budget,
  };
}

// --- The CSV, read just enough to show real counts --------------------------
export type ParsedCsv = { rows: number; first: string; last: string };
export function parseRevenueCsv(text: string): ParsedCsv | null {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"));
  const dates = lines
    .slice(1)
    .map((line) => line.split(",")[0].replace(/^"|"$/g, "").trim())
    .filter((value) => /^\d{4}-\d{2}-\d{2}$/.test(value))
    .sort();
  if (!dates.length) return null;
  return { rows: dates.length, first: dates[0], last: dates[dates.length - 1] };
}
export const fmtCount = (count: number) => count.toLocaleString("en-US");
export const csvSummary = (csv: ParsedCsv) =>
  `${fmtCount(csv.rows)} days · ${csv.first} → ${csv.last}`;

// --- The proposed rain hedge -------------------------------------------------
export const DEMO_HEDGE = {
  id: "hdg_demo_rain_kxrainnyc",
  title: "Will it rain in Central Park on Oct 28?",
  ticker: "KXRAIN-26OCT28-NYC · series KXRAIN",
  line: "Buy YES · 1,955 contracts @ 33¢ · premium $675.41 (includes $30.26 fee) · pays $1,955.00 if it rains",
  payoff: [
    {
      outcome: "event",
      revenue_vs_base: "-1955.68",
      contract_payout: "1955.00",
      premium: "-675.41",
      net_vs_base: "-676.09",
    },
    {
      outcome: "no_event",
      revenue_vs_base: "0.00",
      contract_payout: "0.00",
      premium: "-675.41",
      net_vs_base: "-675.41",
    },
  ] satisfies PayoffRow[],
  expectedCost:
    "Expected cost ≈ $64.86 (premium minus expected payout at the 31% NOAA rain rate)",
  checks: [
    "Open market found",
    "Enough contracts available",
    "Price vs. how often it rains",
    "Cost vs. the swing it removes",
    "Settles on Central Park weather, the station we measured",
    "Contracts ≤ measured exposure",
  ],
};
export type DemoHedgeStatus = "proposed" | "approved" | "rejected";
export function demoLog(
  kind: "proposal" | "approval" | "rejection",
  businessName: string,
): LogEntry {
  const status: Record<typeof kind, LogEntry["status"]> = {
    proposal: "proposed",
    approval: "approved",
    rejection: "rejected",
  };
  const summary = {
    proposal: `Desk proposed rain protection for ${businessName}: KXRAIN-26OCT28-NYC, 1,955 YES contracts, premium $675.41 (scripted demo).`,
    approval:
      "Owner approved rain protection: premium $675.41 (scripted demo).",
    rejection: "Owner rejected rain protection (scripted demo).",
  }[kind];
  return {
    log_id: `demo_${kind}_${Date.now()}`,
    business_id: DEMO_ID,
    kind,
    created_at: new Date().toISOString(),
    actor: kind === "proposal" ? "desk" : "owner",
    agent: null,
    hedge_id: DEMO_HEDGE.id,
    decision_id: null,
    run_id: null,
    status: status[kind],
    checks: [],
    reasons: [],
    numbers: {},
    summary,
  };
}
