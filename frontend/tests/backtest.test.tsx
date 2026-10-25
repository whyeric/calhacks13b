import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BacktestPanel } from "@/components/BacktestPanel";
import type { Backtest } from "@/lib/types";
import taxiJson from "@/fixtures/backtest_taxi.json";
import restaurantJson from "@/fixtures/backtest_restaurant.json";
const fixture = <T,>(value: unknown): T => structuredClone(value) as T;
const taxi = fixture<Backtest>(taxiJson);

describe("C7-A27 backtest panel", () => {
  it("builds the headline only from API fields", () => {
    render(<BacktestPanel data={taxi} />);
    expect(
      screen.getByText(
        (_, node) =>
          node?.className === "backtest-headline" &&
          node.textContent ===
            "Weekly income swings fell 37.7% for $1,684.55 in premiums",
      ),
    ).toBeVisible();
  });
  it("shows worst week before and after", () => {
    render(<BacktestPanel data={taxi} />);
    expect(screen.getByText("Worst week · Oct 27, 2025")).toBeVisible();
    expect(
      screen.getByText("$35,120 unhedged → $38,530.70 hedged"),
    ).toBeVisible();
    expect(screen.getByText("$3,312.64 → $2,064.16")).toBeVisible();
  });
  it("flags ineffective exposures", () => {
    render(<BacktestPanel data={taxi} />);
    const hot = screen.getByText("Hot weather").closest("li")!;
    expect(
      within(hot).getByText("Ineffective · under 10% reduction"),
    ).toBeVisible();
    const rain = screen.getByText("Rain").closest("li")!;
    expect(within(rain).queryByText(/Ineffective/)).not.toBeInTheDocument();
  });
  it("labels frequency-priced share when priced_real_pct < 1", () => {
    render(<BacktestPanel data={taxi} />);
    expect(
      screen.getByText(
        "64.5% priced from real Kalshi prices · the rest frequency-priced",
      ),
    ).toBeVisible();
  });
  it("drops the frequency label when fully real-priced", () => {
    render(
      <BacktestPanel
        data={{ ...taxi, priced_real_pct: 1, pricing_tier: "real" }}
      />,
    );
    expect(screen.queryByText(/frequency-priced/)).not.toBeInTheDocument();
    expect(screen.getByText("Priced from real Kalshi prices")).toBeVisible();
  });
  it("restaurant backtest carries the Estimated badge (flag-driven)", () => {
    render(<BacktestPanel data={fixture<Backtest>(restaurantJson)} />);
    expect(screen.getByText("Estimated")).toBeVisible();
    render(<BacktestPanel data={taxi} />);
    expect(screen.getAllByText("Estimated")).toHaveLength(1);
  });
  it("weekly table passes API strings through formatting", () => {
    render(<BacktestPanel data={taxi} />);
    const table = screen.getByRole("table", { hidden: true });
    expect(within(table).getByText("$43,339.90")).toBeInTheDocument();
    expect(within(table).getByText("$212.40")).toBeInTheDocument();
  });
});
