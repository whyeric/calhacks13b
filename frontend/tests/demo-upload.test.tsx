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
import { delay, http, HttpResponse } from "msw";
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
  PRECOMPUTED_RESEARCH,
  RESEARCH_ROWS,
  liveResearch,
  parseRevenueCsv,
  type ResearchResponse,
} from "@/lib/demoScript";
import researchFixture from "@/fixtures/research_response.json";
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
const api = "http://localhost:8000";
// A live response that differs from the precomputed one, so tests can tell
// which one rendered.
const liveResponse = (): ResearchResponse => {
  const res = structuredClone(researchFixture) as ResearchResponse;
  res.summary = "Live summary from the research service.";
  res.n_days = 990;
  res.first = "2024-01-02";
  res.last = "2026-09-29";
  res.rows[0].train.text = "−17.9% · −$1,900.00/day";
  return res;
};
const upload: DemoUpload = {
  name: "Hudson Bike Co.",
  kind: "Bike rental",
  csv: parseRevenueCsv(sampleText)!,
  research: liveResearch(researchFixture as ResearchResponse),
};

function Harness({ value = upload }: { value?: DemoUpload }) {
  const demo = useDemo();
  const { start } = demo;
  useEffect(() => start(value), [start, value]);
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

const drawerServer = setupServer();
describe("upload drawer", () => {
  beforeAll(() => drawerServer.listen({ onUnhandledRequest: "error" }));
  afterEach(() => {
    drawerServer.resetHandlers();
    vi.restoreAllMocks();
  });
  afterAll(() => drawerServer.close());
  const pickSample = async () => {
    fireEvent.change(screen.getByLabelText("Daily revenue (CSV)"), {
      target: { files: [sampleFile()] },
    });
    await screen.findByRole("status");
  };
  const submit = () =>
    fireEvent.click(
      screen.getByRole("button", { name: "Upload and research" }),
    );
  it("is prefilled, shows the notes and sample link, and reports the parsed file", async () => {
    drawerServer.use(
      http.post(`${api}/research`, async () => {
        await delay(50);
        return HttpResponse.json(liveResponse());
      }),
    );
    // jsdom's FormData can't be re-read through msw, so inspect what the
    // component handed to fetch instead.
    const fetchSpy = vi.spyOn(globalThis, "fetch");
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
    expect(
      await screen.findByRole("button", { name: /Researching/ }),
    ).toBeDisabled();
    await waitFor(() => expect(onStart).toHaveBeenCalledTimes(1));
    const started: DemoUpload = onStart.mock.calls[0][0];
    // Live result: the CSV line uses the response's n_days/first/last.
    expect(started.csv).toEqual({
      rows: 990,
      first: "2024-01-02",
      last: "2026-09-29",
    });
    expect(started.research.source).toBe("live");
    expect(started.research.summary).toBe(
      "Live summary from the research service.",
    );
    expect(started.research.rows[0].train.text).toBe("−17.9% · −$1,900.00/day");
    const [url, init] = fetchSpy.mock.calls.find(([u]) =>
      String(u).endsWith("/research"),
    )!;
    expect(url).toBe(`${api}/research`);
    expect(init?.method).toBe("POST");
    const body = init?.body as FormData;
    expect(body.get("name")).toBe("Hudson Bike Co.");
    expect(body.get("kind")).toBe("Bike rental");
    expect((body.get("file") as File).name).toBe(
      "hudson_bike_co_daily_revenue.csv",
    );
  });
  it("shows a 422 message plainly and lets the owner pick another file", async () => {
    let calls = 0;
    drawerServer.use(
      http.post(`${api}/research`, () => {
        calls++;
        return calls === 1
          ? HttpResponse.json(
              {
                error: {
                  code: "too_short",
                  message:
                    "We need at least 540 days with revenue; this file has 120.",
                  detail: { days: 120, min_days: 540 },
                },
              },
              { status: 422 },
            )
          : HttpResponse.json(liveResponse());
      }),
    );
    const onStart = vi.fn();
    render(<DemoUploadDrawer open onClose={() => {}} onStart={onStart} />);
    await pickSample();
    submit();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "We need at least 540 days with revenue; this file has 120.",
    );
    expect(onStart).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Daily revenue (CSV)")).toBeEnabled();
    await pickSample();
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    submit();
    await waitFor(() => expect(onStart).toHaveBeenCalledTimes(1));
    expect(onStart.mock.calls[0][0].research.source).toBe("live");
  });
  it.each([
    ["a network failure", () => HttpResponse.error()],
    [
      "a 500",
      () =>
        HttpResponse.json(
          { error: { code: "internal", message: "boom", detail: null } },
          { status: 500 },
        ),
    ],
  ])("falls back to the precomputed report on %s", async (_, reply) => {
    drawerServer.use(http.post(`${api}/research`, reply));
    const onStart = vi.fn();
    render(<DemoUploadDrawer open onClose={() => {}} onStart={onStart} />);
    await pickSample();
    submit();
    await waitFor(() => expect(onStart).toHaveBeenCalledTimes(1));
    const started: DemoUpload = onStart.mock.calls[0][0];
    expect(started.research).toBe(PRECOMPUTED_RESEARCH);
    // The CSV line still describes the owner's own file.
    expect(started.csv).toEqual(parseRevenueCsv(sampleText));
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("report source", () => {
  it("a live report has no precomputed label", () => {
    render(
      <Harness value={{ ...upload, research: liveResearch(liveResponse()) }} />,
    );
    expect(
      screen.getByText("Live summary from the research service."),
    ).toBeVisible();
    expect(screen.getByTestId("research-row-rain")).toHaveTextContent(
      "−17.9% · −$1,900.00/day",
    );
    expect(screen.queryByText("Precomputed on the sample file")).toBeNull();
    expect(screen.queryByText("Running analysis…")).toBeNull();
    expect(screen.queryByRole("progressbar")).toBeNull();
  });
  it("the fallback report is labeled precomputed (I6)", () => {
    render(<Harness value={{ ...upload, research: PRECOMPUTED_RESEARCH }} />);
    expect(screen.getByText("Precomputed on the sample file")).toBeVisible();
    expect(
      screen.getByText(/Rain and cold reliably cost you money/),
    ).toBeVisible();
    expect(screen.getByTestId("research-row-rain")).toHaveTextContent(
      RESEARCH_ROWS[0].train.text,
    );
  });
  it("offers Send to the desk only on FOUND and sendable rows", () => {
    const res = liveResponse();
    res.rows[0].sendable = false; // rain: FOUND, not sendable
    res.rows[1].sendable = true; // cold: FOUND, sendable
    res.rows[3].sendable = true; // hot: NOT FOUND, sendable (ignored)
    render(<Harness value={{ ...upload, research: liveResearch(res) }} />);
    const buttons = screen.getAllByRole("button", { name: /Send to the desk/ });
    expect(buttons).toHaveLength(1);
    expect(screen.getByTestId("research-row-cold")).toContainElement(
      buttons[0],
    );
  });
});

describe("research report", () => {
  afterEach(() => vi.useRealTimers());
  it("renders the response's values", () => {
    render(<Harness />);
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
    expect(row("hot")).toHaveTextContent("90% CI −$1,000.13 to +$512.89");
    expect(row("knicks_home")).toHaveTextContent("+2.9% · +$354.37/day");
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
    expect(screen.getAllByRole("img", { name: /: 2024 / })).toHaveLength(6);
  });
  it("send to the desk animates, proposes the hedge and approve logs it", () => {
    vi.useFakeTimers();
    render(<Harness />);
    expect(screen.getByTestId("remaining")).toHaveTextContent("1000.00");
    fireEvent.click(screen.getByRole("button", { name: /Send to the desk/ }));
    advance(100);
    expect(screen.getByText("Pricing protection…")).toBeVisible();
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
    render(<Harness />);
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
    http.post(`${api}/research`, () => HttpResponse.json(liveResponse())),
  );
  beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
  afterAll(() => server.close());
  it("header button → drawer → /research → new uploaded business selected, no business API calls for it", async () => {
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
    expect(screen.getByTestId("research-row-rain")).toHaveTextContent(
      "−17.9% · −$1,900.00/day",
    );
    expect(
      screen.getByText(/Hudson Bike Co\. · 990 days · 2024-01-02 → 2026-09-29/),
    ).toBeVisible();
    expect(screen.queryByText("Precomputed on the sample file")).toBeNull();
    fireEvent.change(screen.getByLabelText("Your business"), {
      target: { value: "taxi" },
    });
    await waitFor(() =>
      expect(screen.queryByTestId("demo-research")).not.toBeInTheDocument(),
    );
    expect(demoCalls).toEqual([]);
  }, 20000);
});
