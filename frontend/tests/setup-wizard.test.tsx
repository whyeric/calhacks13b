import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { SWRConfig } from "swr";
import Home from "@/app/page";
import { RESEARCH_MS, SEND_MS } from "@/components/DemoDesk";
import { SETUP_KEY, newestPriceTime } from "@/lib/setup";
import businesses from "@/fixtures/businesses.json";
import restaurant from "@/fixtures/analyze_restaurant.json";
import hedges from "@/fixtures/hedges_mixed.json";
import logs from "@/fixtures/decisions.json";
import backtest from "@/fixtures/backtest_taxi.json";
import settings from "@/fixtures/settings.json";
import type { Hedge } from "@/lib/types";

const api = "http://localhost:8000";
const approvals: string[] = [];
const server = setupServer(
  http.get(`${api}/businesses`, () => HttpResponse.json(businesses)),
  http.post(`${api}/businesses/:id/analyze`, () =>
    HttpResponse.json(restaurant),
  ),
  http.get(`${api}/businesses/:id/hedges`, () => HttpResponse.json(hedges)),
  http.get(`${api}/businesses/:id/decisions`, () => HttpResponse.json(logs)),
  http.get(`${api}/businesses/:id/backtest`, () => HttpResponse.json(backtest)),
  http.get(`${api}/businesses/:id/settings`, () => HttpResponse.json(settings)),
  http.post(`${api}/hedges/:id/approve`, ({ params }) => {
    approvals.push(String(params.id));
    return HttpResponse.json(hedges[0]);
  }),
  http.get(`${api}/health`, () =>
    HttpResponse.json({ status: "ok", offline: true, anthropic: "fallback" }),
  ),
);
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
beforeEach(() => {
  window.localStorage.removeItem(SETUP_KEY);
  approvals.length = 0;
});
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
function mount() {
  return render(
    <SWRConfig
      value={{
        provider: () => new Map(),
        dedupingInterval: 0,
        shouldRetryOnError: false,
      }}
    >
      <Home />
    </SWRConfig>,
  );
}
const next = () =>
  fireEvent.click(screen.getByRole("button", { name: "Next →" }));

describe("first-run setup wizard", () => {
  it("walks the demo bar through 5 steps, never auto-approves, then opens the dashboard", async () => {
    mount();
    expect(screen.getByText(/Step 1 of 5/)).toBeVisible();
    expect(screen.getByRole("button", { name: "← Back" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next →" })).toBeDisabled();
    expect(
      screen.getByRole("button", {
        name: "Connect Square / QuickBooks (coming soon)",
      }),
    ).toBeDisabled();
    fireEvent.click(
      screen.getByRole("button", { name: "Use demo: bar near MSG" }),
    );
    next();

    expect(screen.getByText(/Step 2 of 5/)).toBeVisible();
    expect(await screen.findByText("Declined, and why")).toBeVisible();
    const declines = document.querySelector(".wizard-declines")!;
    // The declined rain hedge is listed with its reason, not hidden.
    expect(
      await within(declines as HTMLElement).findByText(/Rain/),
    ).toBeVisible();
    next();

    expect(screen.getByText(/Step 3 of 5/)).toBeVisible();
    expect(await screen.findByLabelText("Weekly budget ($)")).toBeVisible();
    expect(screen.getByText(/approval line/, { selector: "p" })).toBeVisible();
    next();

    expect(screen.getByText(/Step 4 of 5/)).toBeVisible();
    expect(screen.getByText(/Nothing is approved automatically/)).toBeVisible();
    expect(await screen.findAllByTestId("hedge-card")).not.toHaveLength(0);
    expect(approvals).toEqual([]);
    next();

    expect(screen.getByText(/Step 5 of 5/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "← Back" }));
    expect(screen.getByText(/Step 4 of 5/)).toBeVisible();
    next();
    fireEvent.click(
      screen.getByRole("button", { name: "Open my dashboard →" }),
    );

    expect(window.localStorage.getItem(SETUP_KEY)).toBe("1");
    expect(screen.getByLabelText("Your business")).toHaveValue("restaurant");
    expect(screen.getByTestId("freshness")).toHaveTextContent(
      /Last updated .* · Kalshi prices as of/,
    );
    expect(approvals).toEqual([]);
  });

  it("opens straight to the dashboard once set up, and Re-run setup resets it", async () => {
    window.localStorage.setItem(SETUP_KEY, "1");
    mount();
    expect(screen.queryByText(/Step 1 of 5/)).toBeNull();
    expect(await screen.findAllByTestId("hedge-card")).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "Re-run setup" }));
    expect(window.localStorage.getItem(SETUP_KEY)).toBeNull();
    expect(screen.getByText(/Step 1 of 5/)).toBeVisible();
  });

  it("still shows setup when storage throws", () => {
    const spy = vi
      .spyOn(Storage.prototype, "getItem")
      .mockImplementation(() => {
        throw new Error("blocked");
      });
    mount();
    expect(screen.getByText(/Step 1 of 5/)).toBeVisible();
    spy.mockRestore();
  });
});

describe("wizard with an upload", () => {
  afterEach(() => vi.useRealTimers());
  it("uses #74's upload, shows declines with reasons, and waits for the owner to approve", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mount();
    fireEvent.click(
      screen.getByRole("button", { name: "Upload your revenue" }),
    );
    const text = readFileSync(
      resolve(process.cwd(), "public/samples/hudson_bike_co_daily_revenue.csv"),
      "utf-8",
    );
    fireEvent.change(screen.getByLabelText("Daily revenue (CSV)"), {
      target: { files: [new File([text], "sample.csv", { type: "text/csv" })] },
    });
    await screen.findByText(/1,004 days/);
    fireEvent.click(
      screen.getByRole("button", { name: "Upload and research" }),
    );
    expect(screen.getByText(/Hudson Bike Co\./)).toBeVisible();
    next();
    expect(screen.getByText("Running analysis…")).toBeVisible();
    await act(() => vi.advanceTimersByTimeAsync(RESEARCH_MS + 100));
    expect(screen.getByTestId("research-row-rain")).toBeVisible();
    expect(screen.getByText("Declined, and why")).toBeVisible();
    next();
    expect(screen.getByText(/fixed settings/)).toBeVisible();
    next();
    fireEvent.click(screen.getByRole("button", { name: "Send to the desk →" }));
    await act(() => vi.advanceTimersByTimeAsync(SEND_MS + 100));
    const card = screen.getByTestId("demo-hedge-card");
    expect(card).toHaveTextContent("Proposed · only you can approve");
    fireEvent.click(within(card).getByRole("button", { name: "Approve" }));
    expect(card).toHaveTextContent("Approved by you");
    next();
    fireEvent.click(
      screen.getByRole("button", { name: "Open my dashboard →" }),
    );
    expect(screen.getByTestId("demo-hedge-card")).toHaveTextContent(
      "Approved by you",
    );
    expect(screen.getByTestId("freshness")).toHaveTextContent(
      "Kalshi prices: scripted sample",
    );
  });
});

it("price time prefers an exact cache stamp and otherwise the newest desk run", () => {
  const rows = hedges as unknown as Hedge[];
  expect(newestPriceTime([])).toBeNull();
  expect(newestPriceTime(rows)).toBe(
    [...rows.map((row) => row.created_at)].sort().at(-1),
  );
  expect(
    newestPriceTime([
      { ...rows[0], prices_fetched_at: "2026-10-24T23:09:49Z" } as Hedge,
    ]),
  ).toBe("2026-10-24T23:09:49Z");
});
