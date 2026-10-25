import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { useEffect } from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import {
  afterAll,
  afterEach,
  beforeAll,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { SWRConfig } from "swr";
import Home from "@/app/page";
import {
  DemoDesk,
  DemoUploadDrawer,
  RESEARCH_MS,
  useDemo,
  type DemoUpload,
  type ResearchFn,
} from "@/components/DemoDesk";
import { DEMO_ID, parseRevenueCsv } from "@/lib/demoScript";
import type { ResearchReport } from "@/lib/types";
import research from "@/fixtures/research_report.json";
import businesses from "@/fixtures/businesses.json";
import taxi from "@/fixtures/analyze_taxi.json";
import hedges from "@/fixtures/hedges_mixed.json";
import logs from "@/fixtures/decisions.json";
import backtest from "@/fixtures/backtest_taxi.json";

const sampleText = readFileSync(
  resolve(process.cwd(), "public/samples/hudson_bike_co_daily_revenue.csv"),
  "utf-8",
);
const sampleFile = () =>
  new File([sampleText], "hudson_bike_co_daily_revenue.csv", {
    type: "text/csv",
  });
const upload: DemoUpload = {
  name: "Hudson Bike Co.",
  kind: "Bike rental",
  csv: parseRevenueCsv(sampleText)!,
  text: sampleText,
};
// The report a real backend run returned for the sample (fixtures/research_report.json).
const report = research as ResearchReport;
const resolved: ResearchFn = () => Promise.resolve(report);

function Harness({
  skip = false,
  fn = resolved,
}: {
  skip?: boolean;
  fn?: ResearchFn;
}) {
  const demo = useDemo(fn);
  const { start, upload: current, skip: skipNow } = demo;
  useEffect(() => start(upload), [start]);
  useEffect(() => {
    if (skip && current) skipNow();
  }, [skip, current, skipNow]);
  return (
    <>
      <span data-testid="remaining">{demo.business?.budget.remaining}</span>
      <DemoDesk demo={demo} onRemoved={() => {}} />
    </>
  );
}
const advance = (ms: number) =>
  act(async () => {
    vi.advanceTimersByTime(ms);
  });

describe("CSV parsing", () => {
  it("counts the real sample's rows and date range, skipping # comments", () => {
    expect(parseRevenueCsv(sampleText)).toEqual({
      rows: 1004,
      first: "2024-01-01",
      last: "2026-09-30",
    });
    expect(parseRevenueCsv("# only a comment\n")).toBeNull();
  });
});

describe("upload drawer", () => {
  it("is prefilled, shows the notes and sample link, and reports the parsed file", async () => {
    const onStart = vi.fn();
    render(<DemoUploadDrawer open onClose={() => {}} onStart={onStart} />);
    expect(screen.getByLabelText("Business name")).toHaveValue(
      "Hudson Bike Co.",
    );
    expect(screen.getByLabelText("Type")).toHaveValue("Bike rental");
    expect(
      screen.getByText("Analyzed by your desk server; never stored"),
    ).toBeVisible();
    expect(screen.getByText(/one row per day/)).toBeVisible();
    expect(
      screen.getByRole("link", { name: /Download Hudson Bike Co\./ }),
    ).toHaveAttribute("href", "/samples/hudson_bike_co_daily_revenue.csv");
    const submit = screen.getByRole("button", { name: "Upload and research" });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Daily revenue (CSV)"), {
      target: { files: [sampleFile()] },
    });
    expect(await screen.findByRole("status")).toHaveTextContent(
      "1,004 days · 2024-01-01 → 2026-09-30",
    );
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    expect(onStart).toHaveBeenCalledWith(upload);
  });
});

describe("running analysis", () => {
  afterEach(() => vi.useRealTimers());
  it("shows a single running bar, then the live report", async () => {
    vi.useFakeTimers();
    render(<Harness />);
    expect(screen.getByText("Running analysis…")).toBeVisible();
    const bar = screen.getByRole("progressbar");
    expect(Number(bar.getAttribute("aria-valuenow"))).toBeLessThan(100);
    expect(screen.queryByTestId("research-row-rain")).toBeNull();
    await advance(RESEARCH_MS / 2);
    const mid = Number(
      screen.getByRole("progressbar").getAttribute("aria-valuenow"),
    );
    expect(mid).toBeGreaterThan(0);
    expect(mid).toBeLessThan(100);
    await advance(RESEARCH_MS);
    expect(screen.queryByText("Running analysis…")).toBeNull();
    expect(
      screen.getByText(
        /Rain days and cold days \(<40°F\) reliably cost you money/,
      ),
    ).toBeVisible();
    expect(screen.getByTestId("research-file-notes")).toHaveTextContent(
      "SYNTHETIC demo data",
    );
    expect(screen.getByTestId("research-row-rain")).toBeVisible();
  });
});

describe("research report", () => {
  afterEach(() => vi.useRealTimers());
  it("renders the API's values", async () => {
    vi.useFakeTimers();
    render(<Harness skip />);
    await advance(100);
    const row = (id: string) => screen.getByTestId(`research-row-${id}`);
    const rain = row("rain");
    for (const text of [
      "Customers stay in when it rains.",
      "−18.2% · −$1,923.43/day",
      "90% CI −$2,137.76 to −$1,703.67",
      "125 days",
      "−20.4% · −$2,488.09/day",
      "90% CI −$2,660.85 to −$2,312.19",
      "228 days",
      "Not significant (p 0.29)",
      "FOUND",
      "· hedgeable",
    ])
      expect(within(rain).getByText(text)).toBeInTheDocument();
    expect(rain).toHaveTextContent("Kalshi KXRAIN (NYC, Central Park)");
    expect(row("cold")).toHaveTextContent("−26.5% · −$2,804.78/day");
    expect(row("cold")).toHaveTextContent("90% CI −$3,536.86 to −$2,872.26");
    expect(row("cold")).toHaveTextContent("Not significant (p 0.13)");
    expect(row("cold")).toHaveTextContent("no daily contract to buy");
    expect(row("warm")).toHaveTextContent("90% CI +$698.13 to +$1,623.44");
    expect(row("warm")).toHaveTextContent("upside, no protection needed");
    expect(row("hot")).toHaveTextContent("−2.1% · −$257.69/day");
    expect(row("hot")).toHaveTextContent("90% CI −$996.62 to +$530.09");
    expect(row("knicks_home")).toHaveTextContent("+3.0% · +$359.61/day");
    expect(row("knicks_home")).toHaveTextContent("None: games are scheduled");
    expect(row("knicks_win")).toHaveTextContent(
      "90% CI −$1,538.50 to +$2,731.74",
    );
    for (const id of ["hot", "knicks_home", "knicks_win"]) {
      expect(row(id)).toHaveTextContent("NOT FOUND");
      expect(row(id)).toHaveTextContent("Not distinguishable from zero");
    }
    expect(
      screen.getAllByRole("button", { name: /Send to the desk/ }),
    ).toHaveLength(report.hypotheses.filter((r) => r.sendable).length);
    expect(screen.getAllByRole("img", { name: /: 2024 / })).toHaveLength(6);
    expect(
      screen.getByRole("columnheader", { name: /Unseen \(2025–26\)/ }),
    ).toBeInTheDocument();
  });
  it("shows the API's error instead of a report", async () => {
    vi.useFakeTimers();
    const failing: ResearchFn = () =>
      Promise.reject(
        new Error(
          "Need at least 540 open days inside the weather record; found 28.",
        ),
      );
    render(<Harness skip fn={failing} />);
    await advance(100);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Need at least 540 open days",
    );
    expect(screen.queryByText("Running analysis…")).toBeNull();
    expect(screen.queryByTestId("research-row-rain")).toBeNull();
  });
  it("send to the desk animates, proposes the hedge and approve logs it", async () => {
    vi.useFakeTimers();
    render(<Harness skip />);
    await advance(100);
    expect(screen.getByTestId("remaining")).toHaveTextContent("1000.00");
    fireEvent.click(screen.getByRole("button", { name: /Send to the desk/ }));
    await advance(100);
    expect(screen.getByText("Pricing protection…")).toBeVisible();
    await advance(3300);
    const card = screen.getByTestId("demo-hedge-card");
    expect(within(card).getByTestId("demo-hedge-scripted")).toHaveTextContent(
      "Example hedge (scripted)",
    );
    for (const text of [
      "Rain protection · Hudson Bike Co.",
      "Buy YES · 1,955 contracts @ 33¢ · premium $675.41 (includes $30.26 fee) · pays $1,955.00 if it rains",
      "Expected cost ≈ $64.86 (premium minus expected payout at the 31% NOAA rain rate)",
      "Proposed · only you can approve",
    ])
      expect(within(card).getByText(text)).toBeVisible();
    const rains = within(card).getByRole("row", { name: /It rains/ });
    expect(rains).toHaveTextContent("−$1,955.68");
    expect(rains).toHaveTextContent("−$675.41");
    expect(rains).toHaveTextContent("−$676.09");
    expect(
      within(card).getByRole("row", { name: /It stays dry/ }),
    ).toHaveTextContent("$0$0−$675.41−$675.41");
    expect(screen.getByTestId("remaining")).toHaveTextContent("324.59");
    expect(
      screen.getByText(/Desk proposed rain protection/),
    ).toBeInTheDocument();
    fireEvent.click(within(card).getByRole("button", { name: "Approve" }));
    expect(within(card).getByText("Approved by you")).toBeVisible();
    expect(
      within(card).queryByRole("button", { name: "Approve" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/Owner approved rain protection/),
    ).toBeInTheDocument();
  });
  it("reject logs a rejection and frees the budget", async () => {
    vi.useFakeTimers();
    render(<Harness skip />);
    await advance(100);
    fireEvent.click(screen.getByRole("button", { name: /Send to the desk/ }));
    await advance(3500);
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(screen.getByText("Rejected by you")).toBeVisible();
    expect(
      screen.getByText(/Owner rejected rain protection/),
    ).toBeInTheDocument();
    expect(screen.getByTestId("remaining")).toHaveTextContent("1000.00");
  });
});

describe("dashboard integration (live mode, msw)", () => {
  const api = "http://localhost:8000";
  const demoCalls: string[] = [];
  const researchCalls: {
    name: string | null;
    type: string | null;
    rows: number;
  }[] = [];
  const server = setupServer(
    http.post(`${api}/research`, async ({ request }) => {
      const text = await request.text();
      researchCalls.push({
        name: new URL(request.url).searchParams.get("name"),
        type: request.headers.get("Content-Type"),
        rows: text.split("\n").filter((l) => /^\d{4}-/.test(l)).length,
      });
      return HttpResponse.json(research);
    }),
    http.get(`${api}/businesses`, () => HttpResponse.json(businesses)),
    http.all(`${api}/businesses/${DEMO_ID}/*`, ({ request }) => {
      demoCalls.push(request.url);
      return HttpResponse.json({}, { status: 404 });
    }),
    http.post(`${api}/businesses/:id/analyze`, () => HttpResponse.json(taxi)),
    http.get(`${api}/businesses/:id/hedges`, () => HttpResponse.json(hedges)),
    http.get(`${api}/businesses/:id/decisions`, () => HttpResponse.json(logs)),
    http.get(`${api}/businesses/:id/backtest`, () =>
      HttpResponse.json(backtest),
    ),
    http.get(`${api}/health`, () =>
      HttpResponse.json({ status: "ok", offline: true, anthropic: "fallback" }),
    ),
  );
  beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
  afterAll(() => server.close());
  it("header button → drawer → new uploaded business selected, no API calls for it", async () => {
    render(
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
    fireEvent.click(
      await screen.findByRole("button", { name: "Upload your revenue" }),
    );
    const drawer = screen.getByRole("dialog", { name: "Upload your revenue" });
    fireEvent.change(within(drawer).getByLabelText("Daily revenue (CSV)"), {
      target: { files: [sampleFile()] },
    });
    await within(drawer).findByRole("status");
    fireEvent.click(
      within(drawer).getByRole("button", { name: "Upload and research" }),
    );
    await waitFor(() =>
      expect(screen.getByLabelText("Your business")).toHaveValue(DEMO_ID),
    );
    expect(
      screen.getByRole("option", { name: "Hudson Bike Co. · Uploaded" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Uploaded · sample")).toBeVisible();
    expect(screen.getByRole("button", { name: "Run desk →" })).toBeDisabled();
    expect(screen.getByText("Running analysis…")).toBeVisible();
    expect(
      await screen.findByTestId("research-row-rain", {}, { timeout: 10000 }),
    ).toBeVisible();
    fireEvent.change(screen.getByLabelText("Your business"), {
      target: { value: "taxi" },
    });
    await waitFor(() =>
      expect(screen.queryByTestId("demo-research")).not.toBeInTheDocument(),
    );
    expect(demoCalls).toEqual([]);
    expect(researchCalls).toEqual([
      { name: "Hudson Bike Co.", type: "text/csv", rows: 1004 },
    ]);
  }, 20000);
});
