import businessesFixture from "@/fixtures/businesses.json";
import negativeFixture from "@/fixtures/businesses_negative.json";
import taxi from "@/fixtures/analyze_taxi.json";
import restaurant from "@/fixtures/analyze_restaurant.json";
import mixed from "@/fixtures/hedges_mixed.json";
import longtext from "@/fixtures/hedges_longtext.json";
import decisionsFixture from "@/fixtures/decisions.json";
import snapshots from "@/fixtures/budget_snapshots.json";
import backtestTaxi from "@/fixtures/backtest_taxi.json";
import backtestRestaurant from "@/fixtures/backtest_restaurant.json";
import ledgerFixture from "@/fixtures/ledger_with_mismatch.json";
import chatFixture from "@/fixtures/chat_reply.json";
import settingsFixture from "@/fixtures/settings.json";
import healthFixture from "@/fixtures/health.json";
import researchFixture from "@/fixtures/research_report.json";
import playoffFixture from "@/fixtures/hedges_playoff.json";
import unstableFixture from "@/fixtures/hedge_declined_unstable.json";
import playoffExposure from "@/fixtures/exposure_playoff_home.json";
import { ApiError } from "./api";
import type {
  Business,
  Hedge,
  Ledger,
  LogEntry,
  Settings,
  Thresholds,
} from "./types";

const clone = <T>(data: unknown): T => structuredClone(data) as T;
// The bar across from MSG shows the research-driven rows: the hot hedge, an
// "unstable" decline and the multi-leg playoff season protection.
function hedgesFor(businessId: string): Hedge[] {
  if (businessId !== "restaurant") return clone<Hedge[]>(mixed);
  return [
    clone<Hedge[]>(mixed)[0],
    clone<Hedge>(unstableFixture),
    ...clone<Hedge[]>(playoffFixture),
  ];
}
function initialHedges() {
  return businessesFixture.flatMap((business) =>
    hedgesFor(business.id).map((row) => ({
      ...row,
      id: `${row.id}_${business.id}`,
      business_id: business.id,
    })),
  );
}
let hedges = initialHedges();
let decisions = clone<LogEntry[]>(decisionsFixture);
let settings: Record<string, Settings> = {};
export function resetMock() {
  hedges = initialHedges();
  decisions = clone<LogEntry[]>(decisionsFixture);
  settings = {};
}
const settingsFor = (id: string) =>
  (settings[id] ??= clone<Settings>(settingsFixture));

// Order of two non-negative decimal strings, by digits only (no float coercion).
function compareDecimal(a: string, b: string): number {
  const [aWhole, aFrac = ""] = a.split(".");
  const [bWhole, bFrac = ""] = b.split(".");
  const wa = aWhole.replace(/^0+/, "");
  const wb = bWhole.replace(/^0+/, "");
  if (wa.length !== wb.length) return wa.length < wb.length ? -1 : 1;
  if (wa !== wb) return wa < wb ? -1 : 1;
  const fa = aFrac.padEnd(12, "0");
  const fb = bFrac.padEnd(12, "0");
  return fa === fb ? 0 : fa < fb ? -1 : 1;
}
// Mock stand-in for the server's deterministic rules re-run (R14). The real
// re-evaluation lives in the backend; the browser never decides.
const thresholdChecks: Record<string, [string, keyof Thresholds]> = {
  overpriced: ["overpay", "overpay_max"],
  too_expensive: ["ratio", "cost_ratio_max"],
};
function reevaluate(row: Hedge, th: Thresholds): Hedge["status"] {
  for (const check of row.decision.checks) {
    const rule = thresholdChecks[check.code];
    const value = rule && check.metric[rule[0]];
    if (typeof value === "string")
      check.passed = compareDecimal(value, String(th[rule[1]])) <= 0;
  }
  const failed = row.decision.checks
    .filter((check) => check.passed === false)
    .map((check) => check.code);
  const blocking = failed.filter((code) => code !== "over_budget");
  row.decision.reasons = blocking.length
    ? blocking
    : failed.includes("over_budget")
      ? ["over_budget"]
      : [];
  row.decision.status = blocking.length
    ? "declined"
    : failed.length
      ? "pending_approval"
      : "proposed";
  return row.decision.status;
}
function logRow(row: Partial<LogEntry> & Pick<LogEntry, "business_id">) {
  decisions = [
    ...decisions,
    {
      log_id: crypto.randomUUID(),
      kind: "proposal",
      created_at: new Date().toISOString(),
      actor: "owner",
      agent: null,
      hedge_id: null,
      decision_id: null,
      run_id: null,
      status: null,
      checks: [],
      reasons: [],
      numbers: {},
      summary: "",
      ...row,
    },
  ];
}
export async function mockRequest<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const scenario =
    typeof window === "undefined"
      ? "default"
      : (new URLSearchParams(window.location.search).get("scenario") ??
        "default");
  await new Promise((resolve) =>
    setTimeout(resolve, scenario === "slow" ? 2500 : 150),
  );
  const route = path.split("?")[0];
  if (scenario === "error" && route !== "/businesses" && route !== "/health")
    throw new Error("The desk could not load this region. Please retry.");
  const id = route.split("/")[2];
  let result: unknown;
  if (route === "/health") result = healthFixture;
  else if (route === "/businesses")
    result =
      scenario === "negative"
        ? negativeFixture
        : clone<Business[]>(businessesFixture).map((business) => {
            const key = hedges
              .filter(
                (row) =>
                  row.business_id === business.id && row.status !== "declined",
              )
              .map((row) => row.status)
              .join("|");
            return {
              ...business,
              budget:
                snapshots[key as keyof typeof snapshots] ?? business.budget,
            };
          });
  else if (route.endsWith("/analyze")) {
    const data =
      scenario === "negative"
        ? restaurant
        : id === "restaurant"
          ? {
              ...restaurant,
              exposures: [...restaurant.exposures, playoffExposure],
            }
          : taxi;
    result =
      scenario === "empty" ? { ...data, exposures: [], dropped: [] } : data;
  } else if (route.endsWith("/hedges")) {
    // Scenario fixtures are explicitly labelled mock data; never substitute them in live mode.
    result =
      scenario === "empty"
        ? []
        : scenario === "longtext"
          ? longtext
          : hedges.filter((row) => row.business_id === id);
  } else if (route.endsWith("/decisions"))
    result =
      scenario === "empty"
        ? []
        : decisions.filter((row) => row.business_id === id);
  else if (route.endsWith("/backtest")) {
    if (scenario === "empty")
      throw new ApiError(
        "The backtest has not been run for this business yet.",
        409,
        "backtest_not_ready",
      );
    result = id === "restaurant" ? backtestRestaurant : backtestTaxi;
  } else if (route.endsWith("/ledger")) {
    const ledger = clone<Ledger>(ledgerFixture);
    ledger.entries.forEach((row) => (row.business_id = id));
    if (ledger.reconciliation) ledger.reconciliation.business_id = id;
    result =
      scenario === "empty"
        ? { entries: [], reconciliation: null, simulated: true }
        : ledger;
  } else if (method === "POST" && route.endsWith("/reconcile")) {
    if (scenario === "empty")
      throw new ApiError(
        "No hedge has settled yet, so there is nothing to reconcile.",
        409,
        "nothing_to_reconcile",
      );
    const recon = clone<Ledger>(ledgerFixture).reconciliation!;
    recon.business_id = id;
    logRow({
      business_id: id,
      kind: "reconciliation",
      actor: "desk",
      agent: "fallback",
      summary: recon.mismatches.length
        ? recon.mismatches[0].explanation
        : "Every payout matched the bank (mock).",
    });
    result = recon;
  } else if (method === "POST" && route.endsWith("/chat")) result = chatFixture;
  // Fixture mode answers every upload with the Hudson Bike Co. report (a real backend run).
  else if (method === "POST" && route === "/research") result = researchFixture;
  else if (route.endsWith("/settings")) {
    if (method === "PUT") {
      const next = clone<Settings>(body);
      settings[id] = next;
      for (const row of hedges) {
        if (
          row.business_id !== id ||
          !["proposed", "pending_approval", "declined"].includes(row.status)
        )
          continue;
        const before = row.status;
        row.status = reevaluate(row, next.thresholds);
        if (row.status !== before)
          logRow({
            business_id: id,
            kind: "threshold_changed",
            hedge_id: row.id,
            decision_id: row.decision.id,
            status: row.status,
            checks: row.decision.checks,
            reasons: row.decision.reasons,
            summary: `Settings changed: ${row.id} went from ${before} to ${row.status} (mock).`,
          });
      }
    }
    result = settingsFor(id);
  } else if (route.endsWith("/desk/run"))
    result = { run_id: `mock_${id}`, business_id: id, status: "queued" };
  else if (route.startsWith("/runs/")) result = { run_id: id, status: "done" };
  else if (
    method === "POST" &&
    /\/hedges\/[^/]+\/(approve|reject)$/.test(route)
  ) {
    if ((body as { actor?: string })?.actor !== "owner")
      throw new Error("Only the owner may decide.");
    const row = hedges.find((item) => item.id === id);
    if (!row || !["proposed", "pending_approval"].includes(row.status))
      throw new Error("This hedge is no longer awaiting your decision.");
    const approved = route.endsWith("/approve");
    row.status = approved ? "approved" : "rejected";
    row.decided_by = "owner";
    row.decided_at = new Date().toISOString();
    row.ledger_entry_ids = approved ? [`mock_${row.id}`] : [];
    logRow({
      business_id: row.business_id,
      kind: approved ? "approval" : "rejection",
      created_at: row.decided_at,
      hedge_id: row.id,
      decision_id: row.decision.id,
      status: row.status,
      summary: approved
        ? "Owner approved protection (mock)."
        : "Owner rejected protection (mock).",
    });
    result = row;
  } else throw new Error(`Mock route unavailable: ${method} ${route}`);
  return structuredClone(result) as T;
}
