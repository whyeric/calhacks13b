import {
  fireEvent,
  render,
  screen,
  within,
  waitFor,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  HedgeCard,
  HedgeList,
  ApproveBar,
  HeadlineStrip,
  PayoffChart,
} from "@/components/HedgeCard";
import { Header } from "@/components/Header";
import { ModelCheck, NotHedgedList } from "@/components/ExposureList";
import { DecisionLog } from "@/components/DecisionLog";
import type { Analyze, Business, Hedge, LogEntry } from "@/lib/types";
import { fmtUsd } from "@/lib/format";
import proposedJson from "@/fixtures/hedge_proposed_rain.json";
import declinedJson from "@/fixtures/hedge_declined_overpriced.json";
import missingJson from "@/fixtures/hedge_declined_no_market.json";
import pendingJson from "@/fixtures/hedge_pending_over_budget.json";
import mixedJson from "@/fixtures/hedges_mixed.json";
import businessesJson from "@/fixtures/businesses.json";
import analyzeJson from "@/fixtures/analyze_taxi.json";
import logsJson from "@/fixtures/decisions.json";
const fixture = <T,>(value: unknown): T => structuredClone(value) as T;
const proposed = fixture<Hedge>(proposedJson),
  declined = fixture<Hedge>(declinedJson),
  missing = fixture<Hedge>(missingJson),
  pending = fixture<Hedge>(pendingJson);
const changed = async () => {};
describe("dashboard contract rendering", () => {
  it("C7-A4 declined cards show reason labels, exact metrics and no approval", () => {
    render(<HedgeCard hedge={declined} onChanged={changed} />);
    expect(screen.getByText("Declined")).toBeVisible();
    expect(
      screen.getAllByText("Price above historical frequency").length,
    ).toBeGreaterThan(0);
    expect(screen.getByText("62¢")).toBeVisible();
    expect(screen.getByText("27%")).toBeVisible();
    expect(screen.getByText("36.65%")).toBeVisible();
    expect(screen.getByText(declined.decision.summary!)).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Approve" }),
    ).not.toBeInTheDocument();
  });
  it("C7-A5 retains every mixed card and the region count", () => {
    render(
      <HedgeList hedges={fixture<Hedge[]>(mixedJson)} onChanged={changed} />,
    );
    expect(screen.getAllByTestId("hedge-card")).toHaveLength(3);
    expect(screen.getByText("3 decisions")).toBeVisible();
    expect(screen.getByText("Declined")).toBeVisible();
  });
  it("C7-A6 no market has a reason and no chart or link", () => {
    render(<HedgeCard hedge={missing} onChanged={changed} />);
    expect(screen.getAllByText("No open market").length).toBeGreaterThan(0);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
  it("C7-A2 passes sentinel values directly through formatting", () => {
    render(
      <HedgeCard
        hedge={{
          ...proposed,
          premium: "1234.50",
          fee: "0.62",
          headline: {
            unhedged_swing: "1234.50",
            hedged_swing: "0.62",
            cost: "1234.50",
          },
        }}
        onChanged={changed}
      />,
    );
    expect(
      screen.getByText(
        "Unhedged swing $1,234.50 · hedged swing $0.62 · cost $1,234.50",
      ),
    ).toBeVisible();
    expect(
      screen.getByText("Premium $1,234.50 · includes $0.62 in fees"),
    ).toBeVisible();
  });
  it("C7-A10 payoff table keeps both outcomes and each API premium", () => {
    render(<PayoffChart rows={proposed.payoff!} />);
    const table = screen.getByRole("table");
    expect(within(table).getByText("It rains")).toBeVisible();
    expect(within(table).getByText("It stays dry")).toBeVisible();
    for (const row of within(table).getAllByRole("row").slice(1))
      expect(within(row).getAllByRole("cell")[2]).toHaveTextContent(
        fmtUsd(proposed.payoff![0].premium),
      );
    for (const row of proposed.payoff!)
      for (const value of [
        row.revenue_vs_base,
        row.contract_payout,
        row.net_vs_base,
      ])
        expect(
          within(table).getAllByText(fmtUsd(value)).length,
        ).toBeGreaterThan(0);
  });
  it("C7-A12 exact premium headline", () => {
    render(
      <HeadlineStrip
        headline={{ unhedged_swing: "900", hedged_swing: "60", cost: "41" }}
      />,
    );
    expect(
      screen.getByText("Unhedged swing $900 · hedged swing $60 · cost $41"),
    ).toBeVisible();
  });
  it.each([
    "proposed",
    "pending_approval",
    "declined",
    "approved",
    "rejected",
    "expired_unapproved",
    "settled",
  ] as const)("C7-A13 owner actions for %s", (status) => {
    render(<ApproveBar hedge={{ ...proposed, status }} onChanged={changed} />);
    expect(screen.queryByRole("button", { name: "Approve" }) !== null).toBe(
      ["proposed", "pending_approval"].includes(status),
    );
    expect(screen.queryByRole("button", { name: "Reject" }) !== null).toBe(
      ["proposed", "pending_approval"].includes(status),
    );
  });
  it("C7-A14 disables pending action, sends owner, and requests refresh", async () => {
    let finish!: (response: Response) => void;
    const fetcher = vi.spyOn(global, "fetch").mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const refresh = vi.fn(async () => {});
    render(<ApproveBar hedge={proposed} onChanged={refresh} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(screen.getByRole("button", { name: "Saving…" })).toBeDisabled();
    expect(fetcher).toHaveBeenCalledWith(
      expect.stringContaining(`/hedges/${proposed.id}/approve`),
      expect.objectContaining({ body: JSON.stringify({ actor: "owner" }) }),
    );
    finish(new Response(JSON.stringify({ ...proposed, status: "approved" })));
    await waitFor(() => expect(refresh).toHaveBeenCalledOnce());
  });
  it("C7-A14 failed approval stays actionable", async () => {
    vi.spyOn(global, "fetch").mockRejectedValue(new Error("Try again"));
    render(<ApproveBar hedge={proposed} onChanged={changed} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Try again");
    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
  });
  it("C7-A15 displays the server alternative", () => {
    render(<ApproveBar hedge={pending} onChanged={changed} />);
    expect(screen.getByText("Within-budget alternative")).toBeVisible();
    expect(screen.getByText("331 contracts · $249.40 premium")).toBeVisible();
  });
  it.each([true, false])(
    "C7-A7/A9 label follows estimated=%s even when the name disagrees",
    (estimated) => {
      const businesses = fixture<Business[]>(businessesJson);
      businesses[0].estimated = estimated;
      render(
        <Header
          businesses={businesses}
          selectedId="taxi"
          onSelect={() => {}}
          onRun={() => {}}
          running={false}
        />,
      );
      expect(screen.getByText(estimated ? /Estimated/ : "Real")).toBeVisible();
      if (estimated)
        expect(screen.getByText(/visits × average check/)).toBeVisible();
    },
  );
  it("C7-A23/A24 log is newest first, collapsed and has fallback marker", () => {
    const entries = fixture<LogEntry[]>(logsJson);
    const { container } = render(<DecisionLog decisions={entries} />);
    const rows = container.querySelectorAll("details");
    expect(rows[0]).not.toHaveAttribute("open");
    expect(rows[0]).toHaveTextContent("Automatic summary");
    fireEvent.click(rows[0].querySelector("summary")!);
    expect(rows[0]).toHaveAttribute("open");
    expect(
      within(rows[0] as HTMLElement).getAllByText("Pass", { exact: false })
        .length,
    ).toBeGreaterThan(0);
  });
  it("C7-A25 model check uses canonical fields", () => {
    const data = fixture<Analyze>(analyzeJson);
    render(<ModelCheck data={data.model_check} r2={data.r2_holdout} />);
    expect(screen.getByText("$500")).toBeVisible();
    expect(screen.getByText("$512.40")).toBeVisible();
    expect(screen.getByText("90% interval: $371.80 to $653")).toBeVisible();
    expect(screen.getByText("Coverage 90% · 50 trials")).toBeVisible();
    expect(screen.getByText("Holdout R²: 0.58")).toBeVisible();
  });
  it("model check rounds a raw holdout R² to two places", () => {
    const data = fixture<Analyze>(analyzeJson);
    const { rerender } = render(
      <ModelCheck data={data.model_check} r2={0.23632632956599453} />,
    );
    expect(screen.getByText("Holdout R²: 0.24")).toBeVisible();
    rerender(<ModelCheck data={data.model_check} r2={-0.0712} />);
    expect(screen.getByText("Holdout R²: −0.07")).toBeVisible();
    rerender(<ModelCheck data={data.model_check} r2={null} />);
    expect(
      screen.getByText("Holdout R²: Not available (no holdout rows)"),
    ).toBeVisible();
  });
  it("C7-A26 dropped list is collapsed with count and reasons", () => {
    const { container } = render(
      <NotHedgedList dropped={fixture<Analyze>(analyzeJson).dropped} />,
    );
    expect(screen.getByText("Measured, not hedged (2)")).toBeVisible();
    expect(container.querySelector("details")).not.toHaveAttribute("open");
    fireEvent.click(screen.getByText("Measured, not hedged (2)"));
    expect(screen.getAllByText(/Evidence is not strong enough/)).toHaveLength(
      2,
    );
  });
  it("C7-A30 safe Kalshi link comes from API", () => {
    render(<HedgeCard hedge={proposed} onChanged={changed} />);
    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      proposed.market_url,
    );
    expect(screen.getByRole("link")).toHaveAttribute(
      "rel",
      "noopener noreferrer",
    );
    expect(screen.getByRole("link")).toHaveAttribute("target", "_blank");
  });
});
