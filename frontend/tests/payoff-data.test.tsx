import { render } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { PayoffChart } from "@/components/HedgeCard";
import type { PayoffRow } from "@/lib/types";
import fixture from "@/fixtures/hedge_proposed_rain.json";
const capture = vi.hoisted(() => vi.fn());
vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: unknown }) => children,
  BarChart: (props: unknown) => {
    capture(props);
    return null;
  },
  Bar: () => null,
  XAxis: () => null,
  YAxis: () => null,
}));
it("C7-A11 passes the exact API payoff rows into Recharts", () => {
  const rows = fixture.payoff as PayoffRow[];
  render(<PayoffChart rows={rows} />);
  expect(capture.mock.calls[0][0].data).toBe(rows);
  expect(capture.mock.calls[0][0].data).toEqual(fixture.payoff);
});
