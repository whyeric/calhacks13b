// Upload demo constants. The research REPORT is live (POST /research, see components/DemoDesk.tsx
// and lib/researchView.ts). The hedge card after "Send to the desk" is SCRIPTED (fixed market and
// 33¢ price, labeled in the UI) but SIZED from the live report: the backend sends it as
// `report.demo_hedge` (markets/demo_card.py). Every $ figure is an API string or a literal (I2;
// the no-money-math lint rule applies).
//
// PRECOMPUTED_*: an earlier offline run of the protocol on the synthetic Hudson Bike Co. sample
// (public/samples/hudson_bike_co_daily_revenue.csv) and the card sized from it, shown only when
// the research request fails, labeled "Precomputed on the sample file" (I6).
import { fmtCents, fmtUsd, fmtPct } from "./format";
import type { ReportView, ResearchRow } from "./researchView";
import type {
  Budget,
  Business,
  DemoHedgePlan,
  LogEntry,
  PayoffRow,
} from "./types";

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

// Weekly budget states for the precomputed card (hardcoded, never derived).
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

// --- The proposed rain hedge (scripted market, sized from the report) --------
export const DEMO_HEDGE = {
  id: "hdg_demo_rain_kxrainnyc",
  title: "Will it rain in Central Park on Oct 28?",
  ticker: "KXRAIN-26OCT28-NYC · series KXRAIN",
  checks: [
    "Open market found",
    "Enough contracts available",
    "Price vs. how often it rains",
    "Cost vs. the swing it removes",
    "Settles on Central Park weather, the station we measured",
    "Contracts ≤ measured exposure",
  ],
};
// What the card shows: formatted strings and API/literal payoff rows only.
export type HedgeCardView = {
  contracts: string; // "1,923"
  premium: string; // decimal string
  line: string;
  expectedCost: string;
  payoff: PayoffRow[];
  budgets: Record<"open" | "pending" | "approved", Budget>;
};
export const liveCard = (plan: DemoHedgePlan): HedgeCardView => {
  const contracts = fmtCount(plan.contracts);
  return {
    contracts,
    premium: plan.premium,
    line: `Buy YES · ${contracts} contracts @ ${fmtCents(plan.price)} · premium ${fmtUsd(plan.premium)} (includes ${fmtUsd(plan.fee)} fee) · pays ${fmtUsd(plan.payout)} if it rains`,
    expectedCost: `Expected cost ≈ ${fmtUsd(plan.expected_cost)} (premium minus expected payout at the ${fmtPct(plan.p_event)} training-year rain-day share)`,
    payoff: plan.payoff,
    budgets: plan.budgets,
  };
};
export const PRECOMPUTED_CARD: HedgeCardView = {
  contracts: "1,955",
  premium: "675.41",
  line: "Buy YES · 1,955 contracts @ 33¢ · premium $675.41 (includes $30.26 fee) · pays $1,955.00 if it rains",
  expectedCost:
    "Expected cost ≈ $64.86 (premium minus expected payout at the 31% NOAA rain rate)",
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
  ],
  budgets: DEMO_BUDGETS,
};
export type DemoHedgeStatus = "proposed" | "approved" | "rejected";
export function demoLog(
  kind: "proposal" | "approval" | "rejection",
  businessName: string,
  card: HedgeCardView,
): LogEntry {
  const status: Record<typeof kind, LogEntry["status"]> = {
    proposal: "proposed",
    approval: "approved",
    rejection: "rejected",
  };
  const summary = {
    proposal: `Desk proposed rain protection for ${businessName}: KXRAIN-26OCT28-NYC, ${card.contracts} YES contracts, premium ${fmtUsd(card.premium)} (scripted demo).`,
    approval: `Owner approved rain protection: premium ${fmtUsd(card.premium)} (scripted demo).`,
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

// --- Precomputed report (fallback only, labeled) ------------------------------
export const PRECOMPUTED_LABEL = "Precomputed on the sample file";
const PRECOMPUTED_ROWS: ResearchRow[] = [
  {
    id: "rain",
    label: "Rain day",
    mechanism: "Riders skip rentals when it rains.",
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
    venue: "KXRAIN · NYC daily rain (Central Park, The Weather Company)",
    sendable: true,
  },
  {
    id: "cold",
    label: "Cold day <40°F",
    mechanism: "Few people ride in the cold.",
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
    venue: "KXHIGHNY low strikes",
    sendable: false,
  },
  {
    id: "warm",
    label: "Warm day >80°F",
    mechanism: "Nice weather brings casual riders.",
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
    venue: "KXHIGHNY",
    sendable: false,
  },
  {
    id: "hot",
    label: "Hot day >90°F",
    mechanism: "Extreme heat might keep riders indoors.",
    train: {
      text: "+1.1% · +$112.43/day",
      ci: "90% CI −$472.81 to +$731.48",
      days: "15 days",
      plot: ["112.43", "-472.81", "731.48"],
    },
    unseen: {
      text: "−2.2% · −$267.65/day",
      ci: "90% CI −$1,000.13 to +$512.89",
      days: "19 days",
      plot: ["-267.65", "-1000.13", "512.89"],
    },
    placebo: "Not significant (p 0.15)",
    verdict: "NOT FOUND",
    verdictNote: "Not distinguishable from zero",
    venue: "KXHIGHNY",
    sendable: false,
  },
  {
    id: "knicks_home",
    label: "Knicks home game",
    mechanism: "Game crowds near MSG might rent bikes.",
    train: {
      text: "+3.0% · +$322.69/day",
      ci: "90% CI −$673.58 to +$1,418.89",
      days: "14 days",
      plot: ["322.69", "-673.58", "1418.89"],
    },
    unseen: {
      text: "+2.9% · +$354.37/day",
      ci: "90% CI −$124.48 to +$852.25",
      days: "85 days",
      plot: ["354.37", "-124.48", "852.25"],
    },
    placebo: "Not significant (p 0.66)",
    verdict: "NOT FOUND",
    verdictNote: "Not distinguishable from zero",
    venue: "None (games are scheduled)",
    sendable: false,
  },
  {
    id: "knicks_win",
    label: "Knicks win",
    mechanism: "Celebrations might bring extra riders.",
    train: {
      text: "+1.1% · +$121.56/day",
      ci: "90% CI −$2,362.83 to +$3,354.79",
      days: "10 days",
      plot: ["121.56", "-2362.83", "3354.79"],
    },
    unseen: {
      text: "+2.8% · +$337.78/day",
      ci: "90% CI −$568.06 to +$1,314.38",
      days: "58 days",
      plot: ["337.78", "-568.06", "1314.38"],
    },
    placebo: "Not significant (p 0.79)",
    verdict: "NOT FOUND",
    verdictNote: "Not distinguishable from zero",
    venue: "KXNBAGAME",
    sendable: false,
  },
];
export const PRECOMPUTED_REPORT: ReportView = {
  source: "precomputed",
  summary:
    "Rain and cold reliably cost you money; warm days help. Game days and Knicks wins make no measurable difference. The desk can protect rain days with Kalshi's daily NYC rain contract.",
  chips: [
    "Training year: 2024",
    "Unseen: 2025–26",
    "Day-of-week + month controls",
    "90% intervals",
    "Placebo: flags shifted 7 days",
    "Corrected for 6 tests",
    "At least 10 event days",
  ],
  rows: PRECOMPUTED_ROWS,
  periods: ["2024", "2025–26"],
  plotMax: "3354.79",
};
