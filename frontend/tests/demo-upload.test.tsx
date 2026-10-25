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
  useDemo,
  type DemoUpload,
} from "@/components/DemoDesk";
import {
  DEMO_ID,
  HYPOTHESES,
  RESEARCH_ROWS,
  parseRevenueCsv,
} from "@/lib/demoScript";
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
};

function Harness({ skip = false }: { skip?: boolean }) {
  const demo = useDemo();
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
const advance = (ms: number) => act(() => vi.advanceTimersByTime(ms));

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
    expect(screen.getByText("Stays on this machine")).toBeVisible();
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

describe("staged research animation", () => {
  afterEach(() => vi.useRealTimers());
  it("walks every step, types the mechanisms and reaches Done", () => {
    vi.useFakeTimers();
    render(<Harness />);
    expect(screen.getByText("Reading 1,004 days of revenue")).toBeVisible();
    expect(screen.queryByText(/Matching NOAA/)).not.toBeInTheDocument();
    advance(1200);
    expect(
      screen.getByText(
        "Matching NOAA Central Park weather (the same station Kalshi's NYC contracts settle on)",
      ),
    ).toBeVisible();
    advance(2600);
    expect(
      screen.getByText(
        "Claude is choosing hypotheses for a bike-rental business…",
      ),
    ).toBeVisible();
    advance(5000);
    for (const row of HYPOTHESES)
      expect(
        screen.getByText(new RegExp(row.mechanism.replace(".", "\\."))),
      ).toBeVisible();
    expect(screen.queryByText("Done: 3 risks hold up, 3 don't.")).toBeNull();
    advance(6000);
    for (const text of [
      "Testing each on 2024 (training year)…",
      "Re-testing on 2025–26: data the model never saw…",
      "Placebo check: same flags shifted 7 days…",
      "Correcting for 6 hypotheses tested…",
      "Done: 3 risks hold up, 3 don't.",
    ])
      expect(screen.getByText(text)).toBeVisible();
    expect(screen.queryByLabelText("working")).not.toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute(
      "aria-valuenow",
      "100",
    );
    expect(
      screen.getByText(/Rain and cold reliably cost you money/),
    ).toBeVisible();
  });
});

describe("research report", () => {
  afterEach(() => vi.useRealTimers());
  it("renders the exact scripted values", () => {
    vi.useFakeTimers();
    render(<Harness skip />);
    advance(100);
    const row = (id: string) => screen.getByTestId(`research-row-${id}`);
    const rain = row("rain");
    for (const text of [
      "Riders skip rentals when it rains.",
      "−18.4% · −$1,955.68/day",
      "90% CI −$2,171.00 to −$1,734.86",
      "124 days",
      "−20.4% · −$2,485.41/day",
      "90% CI −$2,657.97 to −$2,309.72",
      "229 days",
      "Not significant (p 0.38)",
      "FOUND",
      "· hedgeable",
      "KXRAIN · NYC daily rain (Central Park, The Weather Company)",
    ])
      expect(within(rain).getByText(text)).toBeInTheDocument();
    expect(row("cold")).toHaveTextContent("−27.0% · −$2,861.35/day");
    expect(row("cold")).toHaveTextContent("90% CI −$3,533.44 to −$2,869.42");
    expect(row("cold")).toHaveTextContent("Not significant (p 0.11)");
    expect(row("warm")).toHaveTextContent("90% CI +$706.87 to +$1,630.36");
    expect(row("warm")).toHaveTextContent("upside, no protection needed");
    expect(row("hot")).toHaveTextContent("−2.2% · −$267.65/day");
    expect(row("knicks_home")).toHaveTextContent("None (games are scheduled)");
    expect(row("knicks_win")).toHaveTextContent(
      "90% CI −$2,362.83 to +$3,354.79",
    );
    for (const id of ["hot", "knicks_home", "knicks_win"]) {
      expect(row(id)).toHaveTextContent("NOT FOUND");
      expect(row(id)).toHaveTextContent("Not distinguishable from zero");
    }
    expect(
      screen.getAllByRole("button", { name: /Send to the desk/ }),
    ).toHaveLength(RESEARCH_ROWS.filter((r) => r.sendable).length);
    expect(screen.getAllByRole("img", { name: /training/ })).toHaveLength(6);
  });
  it("send to the desk animates, proposes the hedge and approve logs it", () => {
    vi.useFakeTimers();
    render(<Harness skip />);
    advance(100);
    expect(screen.getByTestId("remaining")).toHaveTextContent("1000.00");
    fireEvent.click(screen.getByRole("button", { name: /Send to the desk/ }));
    advance(100);
    expect(
      screen.getByText("Finding a market… KXRAIN-26OCT28-NYC"),
    ).toBeVisible();
    advance(3300);
    const card = screen.getByTestId("demo-hedge-card");
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
  it("reject logs a rejection and frees the budget", () => {
    vi.useFakeTimers();
    render(<Harness skip />);
    advance(100);
    fireEvent.click(screen.getByRole("button", { name: /Send to the desk/ }));
    advance(3500);
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
  const server = setupServer(
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
    expect(screen.getByText("Scripted demo")).toBeVisible();
    expect(screen.getByRole("button", { name: "Run desk →" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Skip animation" }));
    expect(
      await screen.findByText("Done: 3 risks hold up, 3 don't."),
    ).toBeVisible();
    expect(screen.getByTestId("research-row-rain")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Your business"), {
      target: { value: "taxi" },
    });
    await waitFor(() =>
      expect(screen.queryByText("Scripted demo")).not.toBeInTheDocument(),
    );
    expect(demoCalls).toEqual([]);
  });
});
