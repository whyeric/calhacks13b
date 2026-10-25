// SCRIPTED DEMO. Everything here is hardcoded for the "Upload your revenue" →
// "Research my risks" → "Send to the desk" walkthrough. Nothing is fetched from
// the API and nothing is computed in the browser: every $ figure is a literal
// string (I2; the no-money-math lint rule applies).
//
// Where the numbers came from: the real research protocol run on the synthetic
// Hudson Bike Co. sample (public/samples/hudson_bike_co_daily_revenue.csv)
// against NOAA Central Park weather; see experiments/ for the method. Train =
// 2024, unseen = 2025–26, DOW + year-month controls, 90% CIs, placebo = flags
// shifted 7 days, BH correction across the 6 hypotheses.
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
export const PRIVACY_NOTE = "Stays on this machine";

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
    revenue_source: "Uploaded daily revenue CSV (scripted demo)",
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

// --- Research animation ------------------------------------------------------
export const HYPOTHESES = [
  { label: "Rain day", mechanism: "Riders skip rentals when it rains." },
  { label: "Cold day below 40°F", mechanism: "Few people ride in the cold." },
  {
    label: "Warm day above 80°F",
    mechanism: "Nice weather brings casual riders.",
  },
  {
    label: "Hot day above 90°F",
    mechanism: "Extreme heat might keep riders indoors.",
  },
  {
    label: "Knicks home game",
    mechanism: "Game crowds near MSG might rent bikes.",
  },
  { label: "Knicks win", mechanism: "Celebrations might bring extra riders." },
];
export const TYPE_MS = 16; // per typed character
export const HYPOTHESIS_PAUSE_MS = 180;
export type Step = { id: string; text: string; ms: number };
const kindPhrase = (kind: string) =>
  kind.toLowerCase().trim().replaceAll(/\s+/g, "-") || "small";
export const claudeMs = (lead = 400) =>
  HYPOTHESES.reduce(
    (total, row) =>
      total + row.mechanism.length * TYPE_MS + HYPOTHESIS_PAUSE_MS,
    lead,
  );
export function researchSteps(rows: number, kind: string): Step[] {
  return [
    { id: "read", text: `Reading ${fmtCount(rows)} days of revenue`, ms: 1100 },
    {
      id: "noaa",
      text: "Matching NOAA Central Park weather (the same station Kalshi's NYC contracts settle on)",
      ms: 1300,
    },
    { id: "games", text: "Matching Knicks and Rangers schedules", ms: 1100 },
    {
      id: "claude",
      text: `Claude is choosing hypotheses for a ${kindPhrase(kind)} business…`,
      ms: claudeMs(),
    },
    { id: "train", text: "Testing each on 2024 (training year)…", ms: 1300 },
    {
      id: "unseen",
      text: "Re-testing on 2025–26: data the model never saw…",
      ms: 1300,
    },
    {
      id: "placebo",
      text: "Placebo check: same flags shifted 7 days…",
      ms: 1100,
    },
    { id: "bh", text: "Correcting for 6 hypotheses tested…", ms: 900 },
    { id: "done", text: "Done: 3 risks hold up, 3 don't.", ms: 0 },
  ];
}
export const SEND_STEPS: Step[] = [
  { id: "market", text: "Finding a market… KXRAIN-26OCT28-NYC", ms: 1100 },
  { id: "size", text: "Sizing to your measured exposure…", ms: 1100 },
  { id: "rules", text: "Checking the decline rules… all passed", ms: 1000 },
];

// --- Research report ---------------------------------------------------------
export const SUMMARY =
  "Rain and cold reliably cost you money; warm days help. Game days and Knicks wins make no measurable difference. The desk can protect rain days with Kalshi's daily NYC rain contract.";
export const PROTOCOL_CHIPS = [
  "Training year: 2024",
  "Unseen: 2025–26",
  "Day-of-week + month controls",
  "90% intervals",
  "Placebo: flags shifted 7 days",
  "Corrected for 6 tests",
  "At least 10 event days",
];
// Decimal strings for the forest plot geometry only: [point, ci_low, ci_high].
type Interval = [string, string, string];
export type ResearchRow = {
  id: string;
  label: string;
  mechanism: string;
  train: { text: string; ci: string; days: string; plot: Interval };
  unseen: {
    text: string;
    ci: string | null;
    days: string | null;
    plot: Interval | [string] | null;
  };
  placebo: string;
  verdict: "FOUND" | "NOT FOUND";
  verdictNote: string | null;
  kalshi: string;
  sendable: boolean;
};
export const RESEARCH_ROWS: ResearchRow[] = [
  {
    id: "rain",
    label: "Rain day",
    mechanism: HYPOTHESES[0].mechanism,
    train: {
      text: "−18.4% · −$1,955.68/day",
      ci: "90% CI −$2,171.00 to −$1,734.86",
      days: "124 days",
      plot: ["-1955.68", "-2171.00", "-1734.86"],
    },
    unseen: {
      text: "−20.4% · −$2,485.41/day",
      ci: "90% CI −$2,657.97 to −$2,309.72",
      days: "229 days",
      plot: ["-2485.41", "-2657.97", "-2309.72"],
    },
    placebo: "Not significant (p 0.38)",
    verdict: "FOUND",
    verdictNote: "hedgeable",
    kalshi: "KXRAIN · NYC daily rain (Central Park, The Weather Company)",
    sendable: true,
  },
  {
    id: "cold",
    label: "Cold day <40°F",
    mechanism: HYPOTHESES[1].mechanism,
    train: {
      text: "−27.0% · −$2,861.35/day",
      ci: "90% CI −$3,233.31 to −$2,470.61",
      days: "28 days",
      plot: ["-2861.35", "-3233.31", "-2470.61"],
    },
    unseen: {
      text: "−26.4% · −$3,207.58/day",
      ci: "90% CI −$3,533.44 to −$2,869.42",
      days: "89 days",
      plot: ["-3207.58", "-3533.44", "-2869.42"],
    },
    placebo: "Not significant (p 0.11)",
    verdict: "FOUND",
    verdictNote: null,
    kalshi: "KXHIGHNY low strikes",
    sendable: false,
  },
  {
    id: "warm",
    label: "Warm day >80°F",
    mechanism: HYPOTHESES[2].mechanism,
    train: {
      text: "+10.9% · +$1,159.56/day",
      ci: "90% CI +$706.87 to +$1,630.36",
      days: "84 days",
      plot: ["1159.56", "706.87", "1630.36"],
    },
    unseen: {
      text: "+15.5% · +$1,886.89/day",
      ci: "90% CI +$1,501.52 to +$2,283.13",
      days: "160 days",
      plot: ["1886.89", "1501.52", "2283.13"],
    },
    placebo: "Not significant (p 0.81)",
    verdict: "FOUND",
    verdictNote: "upside, no protection needed",
    kalshi: "KXHIGHNY",
    sendable: false,
  },
  {
    id: "hot",
    label: "Hot day >90°F",
    mechanism: HYPOTHESES[3].mechanism,
    train: {
      text: "+1.1% · +$112.43/day",
      ci: "90% CI −$472.81 to +$731.48",
      days: "15 days",
      plot: ["112.43", "-472.81", "731.48"],
    },
    unseen: {
      text: "−2.2% · −$267.65/day",
      ci: null,
      days: null,
      plot: ["-267.65"],
    },
    placebo: "—",
    verdict: "NOT FOUND",
    verdictNote: "Not distinguishable from zero",
    kalshi: "KXHIGHNY",
    sendable: false,
  },
  {
    id: "knicks_home",
    label: "Knicks home game",
    mechanism: HYPOTHESES[4].mechanism,
    train: {
      text: "+3.0% · +$322.69/day",
      ci: "90% CI −$673.58 to +$1,418.89",
      days: "14 days",
      plot: ["322.69", "-673.58", "1418.89"],
    },
    unseen: { text: "+2.9%", ci: null, days: null, plot: null },
    placebo: "—",
    verdict: "NOT FOUND",
    verdictNote: "Not distinguishable from zero",
    kalshi: "None (games are scheduled)",
    sendable: false,
  },
  {
    id: "knicks_win",
    label: "Knicks win",
    mechanism: HYPOTHESES[5].mechanism,
    train: {
      text: "+1.1% · +$121.56/day",
      ci: "90% CI −$2,362.83 to +$3,354.79",
      days: "10 days",
      plot: ["121.56", "-2362.83", "3354.79"],
    },
    unseen: { text: "+2.8%", ci: null, days: null, plot: null },
    placebo: "—",
    verdict: "NOT FOUND",
    verdictNote: "Not distinguishable from zero",
    kalshi: "KXNBAGAME",
    sendable: false,
  },
];
// Shared $/day axis for every forest-plot row.
export const FOREST_DOMAIN: [number, number] = [-3600, 3600];

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
