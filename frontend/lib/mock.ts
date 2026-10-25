import businessesFixture from "@/fixtures/businesses.json";
import negativeFixture from "@/fixtures/businesses_negative.json";
import taxi from "@/fixtures/analyze_taxi.json";
import restaurant from "@/fixtures/analyze_restaurant.json";
import mixed from "@/fixtures/hedges_mixed.json";
import longtext from "@/fixtures/hedges_longtext.json";
import decisionsFixture from "@/fixtures/decisions.json";
import snapshots from "@/fixtures/budget_snapshots.json";
import type { Business, Hedge, LogEntry } from "./types";

const clone = <T>(data: unknown): T => structuredClone(data) as T;
function initialHedges() {
  return businessesFixture.flatMap((business) =>
    clone<Hedge[]>(mixed).map((row) => ({
      ...row,
      id: `${row.id}_${business.id}`,
      business_id: business.id,
    })),
  );
}
let hedges = initialHedges();
let decisions = clone<LogEntry[]>(decisionsFixture);
export function resetMock() {
  hedges = initialHedges();
  decisions = clone<LogEntry[]>(decisionsFixture);
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
  if (scenario === "error" && route !== "/businesses")
    throw new Error("The desk could not load this region. Please retry.");
  const id = route.split("/")[2];
  let result: unknown;
  if (route === "/businesses")
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
      id === "restaurant" || scenario === "negative" ? restaurant : taxi;
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
  else if (route.endsWith("/desk/run"))
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
    decisions = [
      ...decisions,
      {
        log_id: crypto.randomUUID(),
        business_id: row.business_id,
        kind: approved ? "approval" : "rejection",
        created_at: row.decided_at,
        actor: "owner",
        agent: null,
        hedge_id: row.id,
        decision_id: row.decision.id,
        run_id: null,
        status: row.status,
        checks: [],
        reasons: [],
        numbers: {},
        summary: approved
          ? "Owner approved protection (mock)."
          : "Owner rejected protection (mock).",
      },
    ];
    result = row;
  } else throw new Error(`Mock route unavailable: ${method} ${route}`);
  return structuredClone(result) as T;
}
